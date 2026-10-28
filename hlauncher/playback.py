"""Core-owned HDMI playback with bounded queues and a single stereo mixer."""

from collections import deque
import os
from pathlib import Path
import select
import subprocess
import threading
import time

RATE = 48000
FRAMES = 960  # 20 ms at the HDMI output rate.
BLOCK = FRAMES * 4


class Stream:
    def __init__(self, rate, channels):
        self.rate, self.channels = rate, channels
        self.queue = deque()
        self.queued = self.dropped = 0
        self.limit = rate * channels * 2 // 4
        self.pending = bytearray()
        self.resampler = None

    def feed(self, pcm):
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
        self.streams = {}
        self.condition = threading.Condition()
        self.start_worker = start_worker
        self.thread = None
        self.proc = None
        self.written = self.failures = 0

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
                           rate=rate, channels=channels, route='hdmi')
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

    def mix(self, audioop):
        # Only the playback worker touches resampler state and converted buffers.
        with self.condition:
            jobs = []
            for entry in self.streams.values():
                raw = b''.join(entry.queue)
                entry.queue.clear()
                entry.queued = 0
                jobs.append((entry, raw))
        mixed = None
        for entry, raw in jobs:
            if raw:
                if entry.channels == 1:
                    raw = audioop.tostereo(raw, 2, 1, 1)
                if entry.rate != RATE:
                    raw, entry.resampler = audioop.ratecv(raw, 2, 2, entry.rate, RATE, entry.resampler)
                entry.pending.extend(raw)
                # Drop old audio rather than building delay after a stall.
                if len(entry.pending) > RATE:
                    cut = (len(entry.pending) - RATE + 3) // 4 * 4
                    del entry.pending[:cut]
                    entry.dropped += cut
            if entry.pending:
                data = bytes(entry.pending[:BLOCK])
                del entry.pending[:BLOCK]
                data += bytes(BLOCK - len(data))
                mixed = data if mixed is None else audioop.add(mixed, data, 2)
        return mixed

    def run(self):
        try:
            # Supported runtime is Raspberry Pi OS Bookworm / Python 3.11.
            import audioop
        except ImportError:
            self.event(state='audio_hdmi_error', error='PCM mixing requires Python 3.11/3.12 audioop')
            return
        failed_at = 0
        last_data = last_stats = time.monotonic()
        next_block = last_data
        try:
            while True:
                with self.condition:
                    if not self.streams:
                        return
                pcm = self.mix(audioop)
                now = time.monotonic()
                if pcm is None:
                    if self.proc and now - last_data > 2:
                        self.reap()
                    with self.condition:
                        self.condition.wait(.01)
                    next_block = time.monotonic()
                    continue
                if now - failed_at < 5:
                    time.sleep(.02)
                    continue
                try:
                    if self.proc and self.proc.poll() is not None:
                        raise RuntimeError(f'HDMI player exited ({self.proc.returncode})')
                    if not self.proc:
                        env = dict(os.environ)
                        env['ALSA_CONFIG_PATH'] = str(Path(__file__).resolve().parents[1] / 'config/alsa-hdmi.conf')
                        device = os.environ.get('HLAUNCHER_AUDIO_DEVICE', 'hlauncher_hdmi')
                        self.proc = subprocess.Popen(
                            ['aplay', '-q', '-D', device, '-t', 'raw', '-f', 'S16_LE',
                             '-r', str(RATE), '-c', '2', '--buffer-time=80000'],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=env, bufsize=0)
                        try:
                            code = self.proc.wait(timeout=.05)
                            raise RuntimeError(f'HDMI device open failed ({code})')
                        except subprocess.TimeoutExpired:
                            pass
                        os.set_blocking(self.proc.stdin.fileno(), False)
                        self.event(state='audio_hdmi_open', device=device, rate=RATE, channels=2)
                    remaining = memoryview(pcm)
                    deadline = time.monotonic() + .2
                    while remaining:
                        if time.monotonic() > deadline:
                            raise TimeoutError('HDMI playback stalled')
                        if select.select([], [self.proc.stdin], [], .02)[1]:
                            try:
                                n = os.write(self.proc.stdin.fileno(), remaining)
                                remaining = remaining[n:]
                                self.written += n
                            except BlockingIOError:
                                pass
                    last_data = time.monotonic()
                except Exception as exc:
                    self.failures += 1
                    self.event(state='audio_hdmi_error', error=str(exc), failures=self.failures)
                    failed_at = time.monotonic()
                    self.reap()
                if now - last_stats > 2:
                    with self.condition:
                        drops = sum(s.dropped for s in self.streams.values())
                    self.event(state='audio_hdmi_progress', bytes_written=self.written, dropped_bytes=drops)
                    last_stats = now
                next_block = max(next_block + .02, time.monotonic() - .02)
                time.sleep(max(0, next_block - time.monotonic()))
        finally:
            self.reap()

    def reap(self):
        proc, self.proc = self.proc, None
        if not proc:
            return
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=.3)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=.3)
            except subprocess.TimeoutExpired:
                return
        diagnostic = proc.stderr.read(4096).decode(errors='replace').strip()
        if diagnostic:
            self.event(state='audio_hdmi_alsa', diagnostic=diagnostic)
        proc.stdin.close()
        proc.stderr.close()
