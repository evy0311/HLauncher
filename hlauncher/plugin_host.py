"""Process supervision, display leases and the plugin control interface."""

from collections import deque
import json
import mmap
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from .config import ROOT, LOG_DIR, STATE_DIR
from sdk.hlauncher_sdk.buttons import BUTTONS, ACTIONS

sys.path.insert(0, str(ROOT / "sdk"))
from hlauncher_sdk import encode, decode, SLOTS, MAX_PACKET


def channel():
    try:
        return socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    except OSError:
        return socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)


class Worker:
    def __init__(self, manifest, width, height, event, playback=None):
        self.manifest = manifest
        self.event = event
        self.width, self.height = width, height
        self.frame_bytes = width * height * 2
        self.socket, child = channel()
        self.socket.setblocking(False)
        # TemporaryFile is anonymous after opening on Linux and closes with the worker.
        self.file = tempfile.TemporaryFile()
        self.file.truncate(self.frame_bytes * SLOTS)
        self.memory = mmap.mmap(self.file.fileno(), self.frame_bytes * SLOTS)
        self.queue = deque()
        self.queue_lock = threading.Lock()
        self.pending = None
        self.inflight = set()
        self.last_sequence = 0
        self.frames_received = 0
        self.frames_superseded = 0
        self.frames_copied = 0
        self.video_available = False
        self.ready = False
        self.metrics = {}
        self.button_subscription = frozenset()
        self.closed = False
        self.active = False
        self.started = self.last_message = time.monotonic()
        self.status = "Starting " + manifest.name + "..."
        logs = LOG_DIR / "plugins" / manifest.id
        logs.mkdir(parents=True, exist_ok=True)
        self.stderr = open(os.devnull, "wb")
        env = dict(os.environ)
        env.update(
            HLAUNCHER_CONTROL_FD=str(child.fileno()),
            HLAUNCHER_FRAME_FD=str(self.file.fileno()),
            HLAUNCHER_WIDTH=str(width),
            HLAUNCHER_HEIGHT=str(height),
            HLAUNCHER_LOG_DIR=str(logs),
            HLAUNCHER_STATE_DIR=str(STATE_DIR),
            PYTHONPATH=str(ROOT / "sdk"),
        )
        env.pop("HLAUNCHER_RADIO_ADDRESS", None)
        command = [
            sys.executable if manifest.entrypoint[0] == "python3" else "/usr/bin/node",
            manifest.entrypoint[1],
        ]
        audio_socket = playback.open_plugin(manifest) if playback and hasattr(playback,'open_plugin') else None
        if audio_socket:env['HLAUNCHER_PLAYBACK_FD']=str(audio_socket.fileno())
        try:
            self.proc = subprocess.Popen(
                command,
                cwd=manifest.path,
                env=env,
                pass_fds=(child.fileno(), self.file.fileno())+((audio_socket.fileno(),) if audio_socket else ()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            threading.Thread(target=self.capture_output,args=(logs,),daemon=True).start()
        except Exception:
            self.socket.close()
            self.memory.close()
            self.file.close()
            self.stderr.close()
            raise
        finally:
            child.close()
            if audio_socket:audio_socket.close()
        self.send(
            type="host.hello",
            api_version=1,
            width=width,
            height=height,
            pixel_format="rgb565le",
            max_contacts=2,
            slots=SLOTS,
            capabilities=sorted(manifest.capabilities),
        )

    def capture_output(self, logs):
        import logging
        from logging.handlers import RotatingFileHandler
        from sdk.hlauncher_sdk.logging import output_summary
        handler=None
        try:
            try:
                handler=RotatingFileHandler(logs/'worker.log',maxBytes=2*1024*1024,backupCount=2)
            except OSError:
                pass  # Keep draining the pipe even when storage is unavailable.
            while line:=self.proc.stdout.readline(8192):
                summary=output_summary(line)
                if handler is not None and summary is not None:
                    handler.emit(logging.LogRecord('plugin',logging.INFO,'',0,summary,(),None))
        except (OSError,ValueError):pass
        finally:
            if handler:handler.close()
            if self.proc.stdout:self.proc.stdout.close()

    def send(self, **message):
        raw = encode(message)
        return self.send_raw(raw)

    def send_raw(self, raw):
        if self.closed:
            return False
        with self.queue_lock:
            if len(self.queue) >= 64:
                return False
            self.queue.append(raw)
        return True

    def release(self, slot):
        self.inflight.discard(slot)
        if not self.send(type="frame.release", slot=slot):
            raise RuntimeError("plugin control queue full")

    def drain(self):
        with self.queue_lock:
            for _ in range(64):
                if not self.queue:
                    break
                try:
                    raw = self.queue[0]
                    if self.socket.send(raw) != len(raw):
                        raise RuntimeError("short plugin control send")
                    self.queue.popleft()
                except BlockingIOError:
                    break

    def read(self):
        messages = []
        for _ in range(64):
            try:
                raw, _, flags, _ = self.socket.recvmsg(MAX_PACKET)
            except BlockingIOError:
                break
            if not raw:
                raise EOFError("plugin connection closed")
            if flags & socket.MSG_TRUNC:
                raise ValueError("oversized plugin packet")
            message = decode(raw)
            self.last_message = time.monotonic()
            if message["type"] == "audio.pcm":
                raise ValueError("capture PCM cannot be submitted as playback")
            if message["type"] == "frame.ready":
                if "display" not in self.manifest.capabilities:
                    raise ValueError("display capability missing")
                slot = message.get("slot")
                seq = message.get("sequence")
                if (
                    type(slot) is not int
                    or not 0 <= slot < SLOTS
                    or slot in self.inflight
                ):
                    raise ValueError("invalid video slot lease")
                if (
                    type(seq) is not int
                    or seq <= self.last_sequence
                    or message.get("bytes") != self.frame_bytes
                ):
                    raise ValueError("invalid video frame")
                self.frames_received += 1
                self.last_sequence = seq
                self.inflight.add(slot)
                if self.pending is not None:
                    self.frames_superseded += 1
                    self.release(self.pending[0])
                self.pending = (slot, seq)
            else:
                messages.append(message)
        return messages

    def take_frame(self):
        if self.pending is None:
            return None
        slot, sequence = self.pending
        self.pending = None
        try:
            at = slot * self.frame_bytes
            self.frames_copied += 1
            return self.memory[at : at + self.frame_bytes]
        finally:
            self.release(slot)

    def close(self):
        if self.closed:
            return
        self.closed = True
        # Signal the group, including the dongle bridge, without blocking Bluetooth.
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        self.socket.close()
        self.memory.close()
        self.file.close()
        self.stderr.close()

        def reap():
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.event(state="plugin_cleanup_pending", plugin=self.manifest.id)

        threading.Thread(target=reap, daemon=True).start()


class PluginHost:
    def __init__(self, manifests, width, height, event, home, audio, background_allowed=None):
        self.manifests = manifests
        self.width = width
        self.height = height
        self.event = event
        self.home = home
        self.audio = audio
        self.background_allowed = background_allowed or (lambda m: m.keep_alive)
        self.workers = {}
        self.active = None
        self.session = {"connected": False, "authenticated": False}
        self.button_results = {}
        self.button_pending = {}
        self.button_owners = {}
        from .media import NowPlaying
        self.media = NowPlaying(event)
        from .projection_voice import ProjectionVoice
        self.voice = ProjectionVoice(event)

    def activate(self, plugin_id):
        if plugin_id not in self.manifests:
            raise ValueError("plugin not installed")
        self.deactivate()
        worker = self.workers.get(plugin_id)
        if worker is None:
            worker = Worker(
                self.manifests[plugin_id], self.width, self.height, self.event,
                playback=getattr(self.audio,'playback',None)
            )
            self.workers[plugin_id] = worker
        self.active = plugin_id
        if 'audio.playback' in worker.manifest.capabilities:
            self.media.select_source(plugin_id)
            if hasattr(self.audio,'select_source'):self.audio.select_source(plugin_id)
        worker.active = True
        if hasattr(getattr(self.audio,'playback',None),'enable'):self.audio.playback.enable(plugin_id,True)
        worker.background_enabled = self.background_allowed(worker.manifest)
        worker.send(type="radio.session", **self.session)
        worker.send(type="host.activate")
        self.event(state="plugin_activated", plugin=plugin_id)

    def deactivate(self):
        plugin_id = self.active
        self.active = None
        if plugin_id is None:
            return
        if worker := self.workers.get(plugin_id):
            worker.active = False
            worker.send(type="touch.cancel")
            worker.background_enabled = self.background_allowed(worker.manifest)
            worker.send(type="host.deactivate", background=worker.background_enabled)
            if not worker.background_enabled:
                self.stop(plugin_id)
        self.event(state="plugin_deactivated", plugin=plugin_id)

    def background_changed(self, plugin_id):
        worker = self.workers.get(plugin_id)
        if worker:
            worker.background_enabled = self.background_allowed(worker.manifest)
            if not worker.active and not worker.background_enabled:
                self.stop(plugin_id)

    def stop(self, plugin_id):
        if self.active == plugin_id:
            self.active = None
        self.audio.stop(plugin_id)
        self.voice.clear(plugin_id)
        if getattr(self.audio,'capture_source',None)==plugin_id:self.audio.select_source(None)
        self.media.clear(plugin_id)
        self.button_owners = {key: owner for key, owner in self.button_owners.items() if owner != plugin_id}
        for sequence, (record, _) in list(self.button_pending.items()):
            if record['plugin'] == plugin_id:
                record['result'] = 'Plugin stopped before acknowledgement'
                self.event(state='radio_button_result', **record)
                self.button_pending.pop(sequence, None)
        if worker := self.workers.pop(plugin_id, None):
            worker.close()

    def session_changed(self, **values):
        self.session.update(values)
        for worker in self.workers.values():
            if "session" in worker.manifest.capabilities:
                worker.send(type="radio.session", **self.session)
        if values.get("connected") is False:
            self.deactivate()

    def touch(self, touch):
        if worker := self.workers.get(self.active):
            if "touch" in worker.manifest.capabilities:
                if not worker.send(type="touch", **touch):
                    self.failed(worker.manifest.id, "Input queue full")

    def button(self, message):
        # Routing is independent of projection command encodings. Plugins opt in.
        name, action = message.get('button'), message.get('action')
        if (not isinstance(name, str) or name not in BUTTONS or not isinstance(action, str)
                or action not in ACTIONS or type(message.get('sequence')) is not int
                or type(message.get('input_epoch', 0)) is not int
                or not isinstance(message.get('source', ''), str)):
            return
        source, epoch = message.get('source', ''), message.get('input_epoch', 0)
        self.button_owners = {key: owner for key, owner in self.button_owners.items()
                              if key[0] != source or key[1] == epoch}
        key = (source, epoch, name)
        candidates = [self.workers.get(self.active)]
        candidates += [w for key,w in self.workers.items() if key != self.active and
                       w.background_enabled]
        if key in self.button_owners:
            candidates = [self.workers.get(self.button_owners[key])]
        for worker in candidates:
            if (worker and worker.ready and 'input.buttons' in worker.manifest.capabilities
                    and name in worker.button_subscription):
                sent=worker.send(type='radio.button', **message)
                record=dict(button=name, action=action, sequence=message['sequence'],plugin=worker.manifest.id,
                    result='Sent to plugin' if sent else 'Plugin input queue full')
                if action in ('down', 'trigger', 'activate'):
                    self.button_results[name] = record
                if sent:
                    if action in ('down', 'activate'):
                        self.button_owners[key] = worker.manifest.id
                    if len(self.button_pending) >= 128:
                        expired, _ = self.button_pending.pop(next(iter(self.button_pending)))
                        expired['result'] = 'Plugin acknowledgement capacity exceeded'
                        self.event(state='radio_button_result', **expired)
                    self.button_pending[message['sequence']] = (record, time.monotonic()+3)
                if action in ('up', 'deactivate'):
                    self.button_owners.pop(key, None)
                self.event(state='radio_button_forwarded' if sent else 'radio_button_failed',
                           **record)
                return
        if action in ('down', 'trigger', 'activate'):
            self.button_results[name]=dict(button=name,action=action,sequence=message['sequence'],
                                          plugin='',result='No plugin subscribed to this control')

    def subscribe_buttons(self, worker, message):
        buttons = message.get('buttons')
        if ('input.buttons' not in worker.manifest.capabilities or not isinstance(buttons, list)
                or len(buttons) > len(BUTTONS) or any(type(b) is not str or b not in BUTTONS for b in buttons)):
            self.event(state='plugin_buttons_rejected', plugin=worker.manifest.id)
            return
        worker.button_subscription = frozenset(buttons)
        self.event(state='plugin_buttons_subscribed', plugin=worker.manifest.id, buttons=sorted(buttons))

    def button_result(self, worker, message):
        sequence = message.get('sequence')
        if type(sequence) is not int:
            return
        pending = self.button_pending.get(sequence)
        if not pending:
            return
        record, _ = pending
        if record['plugin'] != worker.manifest.id or record['button'] != message.get('button'):
            return
        record['result'] = str(message.get('result', ''))[:80]
        self.event(state='radio_button_result', **record)
        if message.get('final', True) is not False:
            self.button_pending.pop(sequence, None)

    def failed(self, plugin_id, error):
        foreground = self.active == plugin_id
        self.event(state="plugin_failed", plugin=plugin_id, error=str(error))
        self.stop(plugin_id)
        if foreground:
            self.home(str(error)[:120])

    def tick(self):
        for sequence, (record, deadline) in list(self.button_pending.items()):
            if time.monotonic() >= deadline:
                record['result'] = 'Plugin command acknowledgement timed out'
                self.event(state='radio_button_result', **record)
                self.button_pending.pop(sequence, None)
        for plugin_id, worker in list(self.workers.items()):
            try:
                if worker.proc.poll() is not None:
                    raise RuntimeError(worker.manifest.name + " closed unexpectedly")
                worker.drain()
                for message in worker.read():
                    kind = message["type"]
                    if kind == "plugin.ready":
                        if message.get("api_version") != 1:
                            raise ValueError("plugin API mismatch")
                        worker.ready = True
                    elif kind == "plugin.status":
                        worker.status = str(message.get("text", ""))[:240]
                        worker.video_available = message.get("video_available") is True
                    elif kind == "launcher.home" and self.active == plugin_id:
                        self.deactivate()
                        self.home("")
                        break
                    elif kind == "health":
                        if isinstance(message.get("metrics"), dict):
                            worker.metrics = message["metrics"]
                            self.event(
                                state="plugin_frame_stats",
                                plugin=plugin_id,
                                metrics=message["metrics"],
                                received=worker.frames_received,
                                superseded=worker.frames_superseded,
                                copied=worker.frames_copied,
                            )
                    elif kind == 'radio.button.result':
                        if 'input.buttons' in worker.manifest.capabilities:
                            self.button_result(worker, message)
                    elif kind == 'input.buttons.subscribe':
                        self.subscribe_buttons(worker, message)
                    elif kind == 'media.now_playing':
                        try:
                            if 'media.publish' not in worker.manifest.capabilities:
                                raise ValueError('media.publish capability missing')
                            if type(message.get('clear', False)) is not bool:
                                raise ValueError('invalid media clear flag')
                            self.media.publish(plugin_id, message.get('fields'), clear=message.get('clear', False))
                        except (ValueError, TypeError) as exc:
                            self.event(state='plugin_media_rejected', plugin=plugin_id, error=str(exc))
                    elif kind == 'projection.voice':
                        if 'projection.voice' not in worker.manifest.capabilities:
                            raise ValueError('projection.voice capability missing')
                        self.voice.update(plugin_id,message.get('fields'))
                    elif kind == 'projection.microphone':
                        fields=message.get('fields')
                        keys={'mic_received_bytes','mic_dropped_bytes','mic_usb_bytes','mic_usb_errors'}
                        if ('projection.voice' not in worker.manifest.capabilities or not isinstance(fields,dict)
                            or set(fields)!=keys or any(type(v) is not int or not 0<=v<2**63 for v in fields.values())):
                            raise ValueError('Invalid projection microphone statistics')
                        self.event(state='projection_mic_stats',plugin=plugin_id,**fields)
                    elif kind.startswith("audio."):
                        self.audio.request(
                            worker, message, active=self.active == plugin_id
                        )
                    elif kind != "launcher.home":
                        raise ValueError("unsupported plugin message " + kind)
                if plugin_id not in self.workers:
                    continue
                if worker.pending is not None and self.active != plugin_id:
                    slot, _ = worker.pending
                    worker.pending = None
                    worker.release(slot)
                if time.monotonic() - worker.last_message > 10:
                    raise RuntimeError(worker.manifest.name + " stopped responding")
            except (OSError, ValueError, RuntimeError, EOFError) as exc:
                self.failed(plugin_id, exc)

        self.media.flush()
        try:self.voice.tick(self.media.source_plugin)
        except OSError as exc:self.event(state='projection_voice_export_error',error=str(exc))

    def frame(self):
        worker = self.workers.get(self.active)
        return worker.take_frame() if worker else None

    def status(self):
        worker = self.workers.get(self.active)
        return worker.status if worker else ""

    def close(self):
        for plugin_id in list(self.workers):
            self.stop(plugin_id)
