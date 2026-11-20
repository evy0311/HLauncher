"""Core-owned ALSA playback with bounded queues and a single stereo mixer."""

from collections import deque
import os
from pathlib import Path
import select
import subprocess
import threading
import time
import sys
import signal

import numpy as np
from .resample import Resampler
from .audio_settings import AudioSettings

RATE = 48000
FRAMES = 960  # 20 ms at the mixer output rate.
BLOCK = FRAMES * 8  # Stereo float32 throughout the mixer and EQ transport.


class Stream:
    def __init__(self, rate, channels):
        self.rate, self.channels = rate, channels
        self.queue = deque()
        self.queued = self.dropped = 0
        self.limit = rate * channels * 2 // 2  # Half-second startup/scheduling budget.
        self.pending = bytearray()
        self.resampler = None
        self.source_peak = self.converted_peak = 0.0
        self.source_full_scale_samples = 0
        self.last_input = time.monotonic()

    def feed(self, pcm):
        self.last_input = time.monotonic()
        while self.queue and self.queued + len(pcm) > self.limit:
            old = self.queue.popleft()
            self.queued -= len(old)
            self.dropped += len(old)
        if len(pcm) > self.limit:
            self.dropped += len(pcm)
            return
        self.queue.append(pcm)
        self.queued += len(pcm)


class Playback:
    def __init__(self, event, start_worker=True):
        self.event = event
        self.settings = AudioSettings()
        self.device = self.settings.device()
        self.route = 'bluetooth' if self.device.startswith('bluealsa:') else ('hdmi' if self.device == 'hlauncher_hdmi' else 'alsa')
        self.streams = {}
        self.condition = threading.Condition()
        self.start_worker = start_worker
        self.thread = None
        self.proc = None
        self.stderr_reader = None
        self.written = self.failures = 0
        self.peak=0.0
        self.clip_samples=0
        self.capture_file=None
        self.pipewire_service=None
        self.starvation_at = None
        self.last_starvation_log = 0
        self.max_write_ms = 0

    def feed(self, plugin, message):
        rate, channels, stream = (message[k] for k in ('sample_rate', 'channels', 'stream'))
        pcm = message['pcm']
        if rate not in (8000, 16000, 24000, 44100, 48000) or channels not in (1, 2) or not 0 <= stream <= 255 or len(pcm) % (channels * 2):
            raise ValueError('Invalid PCM format or alignment')
        with self.condition:
            key = (plugin, stream)
            entry = self.streams.get(key)
            if entry and (entry.rate, entry.channels) != (rate, channels):
                del self.streams[key]
                entry = None
            if not entry:
                if len(self.streams) >= 8:
                    raise ValueError('Too many audio streams')
                entry = self.streams[key] = Stream(rate, channels)
                self.event(state='audio_stream_format', plugin=plugin, stream=stream,
                           rate=rate, channels=channels, route=self.route, device=self.device)
            gap = time.monotonic() - entry.last_input
            if gap >= .1:
                self.event(state='audio_input_gap', plugin=plugin, stream=stream,
                           gap_ms=round(gap*1000), queued_bytes=entry.queued,
                           monotonic_ms=round(time.monotonic()*1000))
            entry.feed(pcm)
            if self.start_worker and (not self.thread or not self.thread.is_alive()):
                self.thread = threading.Thread(target=self.run, daemon=True)
                self.thread.start()
            self.condition.notify()

    def stop(self, plugin):
        with self.condition:
            for key in list(self.streams):
                if key[0] == plugin:
                    del self.streams[key]
            self.condition.notify()

    def mix(self):
        # Preserve source PCM in float; sum streams without normalization or clipping.
        with self.condition:
            jobs = []
            for entry in self.streams.values():
                raw = b''.join(entry.queue)
                entry.queue.clear()
                entry.queued = 0
                jobs.append((entry, raw))
        for entry, raw in jobs:
            samples = None
            if raw:
                samples = np.frombuffer(raw, dtype='<i2').astype(np.float32).reshape(-1, entry.channels) / 32768.0
                entry.source_peak = max(entry.source_peak, float(np.max(np.abs(samples))))
                entry.source_full_scale_samples += int(np.count_nonzero((samples >= 32767/32768) | (samples <= -1)))
                if entry.channels == 1:
                    samples = np.repeat(samples, 2, axis=1)
                if entry.rate != RATE:
                    if entry.resampler is None:
                        entry.resampler = Resampler(entry.rate, RATE)
                    samples = entry.resampler.process(samples)
            elif entry.resampler is not None and time.monotonic()-entry.last_input > .15:
                samples = entry.resampler.flush()
                entry.resampler.close()
                entry.resampler = None
            if samples is not None:
                if len(samples):
                    entry.converted_peak = max(entry.converted_peak, float(np.max(np.abs(samples))))
                entry.pending.extend(samples.astype('<f4', copy=False).tobytes())
                if len(entry.pending) > RATE*4:
                    cut = (len(entry.pending) - RATE*4 + 7) // 8 * 8
                    del entry.pending[:cut]
                    entry.dropped += cut
        now = time.monotonic()
        ready = [entry for entry, _ in jobs if len(entry.pending) >= BLOCK
                 or (entry.pending and now - entry.last_input > .15)]
        if not ready:
            return None
        mixed=np.zeros(FRAMES*2,dtype=np.float32)
        for entry in ready:
            # Another stream becoming ready must not pad a live partial block
            # with silence. Hold those samples for their next PCM packet.
            data = bytes(entry.pending[:BLOCK])
            del entry.pending[:BLOCK]
            data += bytes(BLOCK - len(data))
            mixed += np.frombuffer(data, dtype='<f4')
        peak=float(np.max(np.abs(mixed)))
        self.peak=max(self.peak,peak)
        self.clip_samples+=int(np.count_nonzero(np.abs(mixed)>1.0))
        return mixed.astype('<f4',copy=False).tobytes()

    def run(self):
        failed_at = 0
        startup_until = 0
        applied = None
        checked = 0
        last_data = last_stats = time.monotonic()
        next_block = last_data
        try:
            while True:
                with self.condition:
                    if not self.streams:
                        return
                now = time.monotonic()
                if now - checked > .2:
                    self.settings.refresh()
                    checked = now
                device = self.settings.device()
                desired = (device, self.settings.values['pipewire'])
                if desired != applied:
                    self.reap()
                    if self.pipewire_service:
                        try:
                            self.pipewire_service.set_enabled(desired[1])
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            self.event(state='audio_route_error', error=str(exc))
                            time.sleep(1)
                            continue
                    self.device = device
                    self.route = self.settings.values['output']
                    applied = desired
                pcm = self.mix()
                now = time.monotonic()
                if pcm is None:
                    if self.proc and self.starvation_at is None:
                        self.starvation_at = now
                    if (self.starvation_at is not None and now-self.starvation_at >= .1
                            and now-self.last_starvation_log >= 1):
                        self.last_starvation_log = now
                        self.event(state='audio_mixer_starved', duration_ms=round((now-self.starvation_at)*1000),
                                   monotonic_ms=round(now*1000))
                    if self.proc and now - last_data > 2:
                        self.reap()
                    with self.condition:
                        self.condition.wait(.01)
                    next_block = time.monotonic()
                    continue
                if self.starvation_at is not None:
                    duration = now-self.starvation_at
                    if duration >= .1:
                        self.event(state='audio_mixer_resumed', gap_ms=round(duration*1000),
                                   monotonic_ms=round(now*1000))
                    self.starvation_at = None
                if now - failed_at < 5:
                    time.sleep(.02)
                    continue
                try:
                    if self.proc and self.proc.poll() is not None:
                        raise RuntimeError(f'Audio player exited ({self.proc.returncode})')
                    opening = not self.proc
                    if opening:
                        env = dict(os.environ)
                        env['ALSA_CONFIG_PATH'] = str(Path(__file__).resolve().parents[1] / 'config/alsa-hdmi.conf')
                        device = self.device
                        command = [sys.executable, '-m', 'hlauncher.pipewire_worker', '--device', device] if applied[1] else [
                            'aplay', '-q', '-D', device, '-t', 'raw', '-f', 'FLOAT_LE',
                            '-r', str(RATE), '-c', '2', '--buffer-time=80000']
                        if applied[1] and self.capture_file:
                            command += ['--capture-file', self.capture_file]
                        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
                        self.proc = subprocess.Popen(
                            command,
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=env, bufsize=0, start_new_session=True,
                            pipesize=131072)  # Float stereo uses twice the former S16 pipe capacity.
                        self.stderr_reader = threading.Thread(
                            target=self.read_diagnostics, args=(self.proc.stderr,), daemon=True,
                        )
                        self.stderr_reader.start()
                        startup_until = time.monotonic() + (5 if applied[1] else 2)
                        try:
                            code = self.proc.wait(timeout=.05)
                            raise RuntimeError(f'Audio device open failed ({code})')
                        except subprocess.TimeoutExpired:
                            pass
                        os.set_blocking(self.proc.stdin.fileno(), False)
                        self.event(state='audio_hdmi_open', device=device, route=self.route, pipewire=applied[1], rate=RATE, channels=2, pcm_format='float32', resampler='soxr-vhq-28bit')
                    write_started = time.monotonic()
                    remaining = memoryview(pcm)
                    # Bluetooth transport acquisition can exceed the steady-state write limit.
                    deadline = max(time.monotonic() + .2, startup_until)
                    while remaining:
                        if time.monotonic() > deadline:
                            raise TimeoutError('Audio playback stalled')
                        if select.select([], [self.proc.stdin], [], .02)[1]:
                            try:
                                n = os.write(self.proc.stdin.fileno(), remaining)
                                remaining = remaining[n:]
                                self.written += n
                            except BlockingIOError:
                                pass
                    last_data = time.monotonic()
                    self.max_write_ms = max(self.max_write_ms, (last_data-write_started)*1000)
                except Exception as exc:
                    self.failures += 1
                    self.event(state='audio_hdmi_error', error=str(exc), failures=self.failures)
                    failed_at = time.monotonic()
                    self.reap()
                if now - last_stats > 2:
                    with self.condition:
                        drops = sum(s.dropped for s in self.streams.values())
                        levels=[dict(plugin=key[0], stream=key[1], source_peak=entry.source_peak,
                                     source_full_scale_samples=entry.source_full_scale_samples,
                                     converted_peak=entry.converted_peak) for key,entry in self.streams.items()]
                    self.event(state='audio_hdmi_progress', bytes_written=self.written, dropped_bytes=drops,
                               peak=self.peak, clip_samples=self.clip_samples,
                               stream_levels=levels, write_ms_max=round(self.max_write_ms, 2),
                               monotonic_ms=round(time.monotonic()*1000))
                    self.max_write_ms = 0
                    last_stats = now
                # The output device owns pacing. Drain available PCM without a second software timer.
        finally:
            self.reap()

    def read_diagnostics(self, stream):
        # Timestamp underruns as they happen and keep stderr from filling up.
        with stream:
            for line in iter(lambda: stream.readline(4096), b''):
                diagnostic = line.decode(errors='replace').strip()
                if diagnostic:
                    self.event(state='audio_hdmi_alsa', diagnostic=diagnostic)

    def reap(self):
        self.starvation_at = None
        proc, self.proc = self.proc, None
        reader, self.stderr_reader = self.stderr_reader, None
        if not proc:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return
        proc.stdin.close()
        if reader:
            reader.join(timeout=.2)
