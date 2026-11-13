"""Reuse installed node-carplay bridge/H264 decoder; bounded asynchronous input."""

import base64, json, os, pathlib, struct, subprocess, sys, threading, time, select
import socket
from contextlib import ExitStack
from hlauncher_sdk.picture import PictureSettings
from hlauncher_sdk.projection import inherited_fds
from collections import deque
from input import TouchRouter
from media import normalize

RUNTIME = pathlib.Path(__file__).resolve().parent / "runtime/usb"
LOG_DIR = pathlib.Path(
    os.environ.get("HLAUNCHER_LOG_DIR", "/var/log/hlauncher/carplay")
)
CONNECTION_STATUS = {
    "waiting_dongle": "Waiting for Carlinkit USB dongle",
    "dongle_ready": "Connect iPhone to Carlinkit",
    "phone_connected": "iPhone connected; waiting for video",
    "phone_disconnected": "iPhone disconnected",
    "usb_failure": "USB dongle connection lost",
}
# The bridge requests a fresh keyframe every five seconds. Allow two requests
# plus a margin before hiding a frozen frame when no disconnect event arrives.
VIDEO_TIMEOUT_SECONDS = 12


def read_packet(stream):
    def exact(n):
        b = bytearray()
        while len(b) < n:
            p = stream.read(n - len(b))
            if not p:
                raise EOFError("CarPlay bridge closed")
            b.extend(p)
        return bytes(b)

    kind, n = struct.unpack("!BI", exact(5))
    if kind not in (1, 2, 3, 4) or n > 8 * 1024 * 1024 or (kind == 4 and n):
        raise ValueError("invalid bridge packet")
    return kind, exact(n)


class BridgePackets:
    """Drain audio and control while the decoder reads its separate video pipe."""
    def __init__(self, stream, stop, audio, state, *, video):
        self.stream, self.stop, self.audio, self.state = stream, stop, audio, state
        self.condition = threading.Condition()
        self.pending = deque()
        self.bytes = 0
        self.error = None
        self.video = video
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while not self.stop.is_set():
                if not select.select([self.stream], [], [], .05)[0]:
                    continue
                kind, data = read_packet(self.stream)
                if self.stop.is_set():
                    return
                if kind == 3:
                    self.audio(data)
                    continue
                if kind != 2:
                    raise ValueError('Unexpected packet on CarPlay audio channel')
                # Apply voice controls in wire order before the next PCM packet.
                state = json.loads(data)
                self.state(state)
                if state.get('state') == 'projection_call':
                    continue  # Caller details are never queued for UI diagnostics.
                with self.condition:
                    # Audio/voice and connection state already took effect. A
                    # stalled video consumer can lose old UI notifications.
                    while self.pending and (len(self.pending) >= 256
                                            or self.bytes + len(data) > 8*1024*1024):
                        _, old = self.pending.popleft()
                        self.bytes -= len(old)
                    self.pending.append((kind, data))
                    self.bytes += len(data)
                    self.condition.notify()
        except Exception as exc:
            with self.condition:
                self.error = exc
                self.condition.notify()

    def take(self):
        with self.condition:
            if self.error:
                raise self.error
            if not self.pending and self.video is None:
                self.condition.wait(.05)
            if self.error:
                raise self.error
            if self.pending:
                kind, data = self.pending.popleft()
                self.bytes -= len(data)
                return kind, data
        if self.video is not None and select.select([self.video], [], [], .02)[0]:
            try:
                kind, data = read_packet(self.video)
                if kind not in (1, 4):
                    raise ValueError('Unexpected packet on CarPlay video channel')
                return kind, data
            except (EOFError, ValueError):
                self.video = None
        return None


class CarplayHDMI:
    def __init__(self, event=lambda **kw: None, audio=lambda *args: None):
        self.audio = audio
        self.event = event
        self.lock = threading.RLock()
        self.cond = threading.Condition()
        self.queue = deque()
        self.thread = None
        self.proc = None
        self.stop_event = threading.Event()
        self.frame = None
        self.phone_connected = False
        self.last_decoded_at = None
        self.connection_epoch = 0
        self.version = 0
        self.status = "Select CarPlay"
        self.status_version = 0
        self.touch_router = TouchRouter()
        self.frames = 0
        self.host_ui_requested = False
        self.audio_forwarded = self.audio_dropped = 0
        self.bridge_audio = {}
        self.decode_packets = 0
        self.decode_seconds = 0.0
        self.decode_max_ms = 0.0
        self.button_pending = {}
        self.button_results = deque(maxlen=64)
        self.media_pending = {}
        self.media_clear = False
        self.visible = threading.Event()
        self.background_video_packets = 0
        self.voice = dict(call_audio=False,siri=False,recording=False)
        self.call_details = {}
        self.mic_queue=deque(maxlen=10)
        self.mic_received=self.mic_dropped=self.mic_usb_bytes=self.mic_usb_errors=self.mic_usb_dropped=0
        self.mic_format=None
        self.voice_streams={}
        self.last_bridge_message=0
        self.adapter_branding="waiting"
        self.adapter_branding_request_id=None
        self.adapter_branding_error=""
        self.pending_branding=None
        self.night_mode = False

    def notify(self, state, **extra):
        self.event(state=state, **extra)

    def set_status(self, text):
        with self.lock:
            if self.status != text:
                self.status = text
                self.status_version += 1

    def start(self, w, h):
        if self.thread and self.thread.is_alive():
            return not self.stop_event.is_set()
        self.stop_event = threading.Event()
        self.queue.clear()
        if self.pending_branding:self.queue.append(dict(self.pending_branding))
        self.adapter_branding_request_id=None
        self.adapter_branding_error=''
        self.touch_router = TouchRouter()
        self.frame = None
        self.phone_connected = False
        self.last_decoded_at = None
        self.frames = 0
        self.host_ui_requested = False
        self.adapter_branding="waiting"
        self.set_status("Starting CarPlay")
        self.thread = threading.Thread(target=self.run, args=(w, h), daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()
        with self.cond:
            self.queue.clear()
            self.mic_queue.clear()
            self.cond.notify_all()
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            # Cleanup cannot block the GLib Bluetooth loop (USB/IP can hang in kernel).
            threading.Thread(target=self.reap, args=(proc,), daemon=True).start()

    def reap(self, proc):
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.notify("carplay_process_cleanup_pending", pid=proc.pid)

    def touch(self, event):
        with self.cond:
            for item in self.touch_router.feed(event):
                if (
                    item.get("_motion")
                    and self.queue
                    and self.queue[-1].get("_motion")
                    and self.queue[-1]["type"] == item["type"]
                ):
                    self.queue[-1] = item
                else:
                    if len(self.queue) >= 64:
                        moves = [
                            i
                            for i, value in enumerate(self.queue)
                            if value.get("_motion")
                        ]
                        if moves:
                            del self.queue[moves[0]]
                        else:
                            self.queue.clear()
                            self.queue.extend(self.touch_router.cancel())
                            self.notify(
                                "carplay_input_overflow", released_contacts=True
                            )
                            break
                    self.queue.append(item)
            self.cond.notify()

    def button(self, message):
        from hlauncher_sdk.buttons import ButtonGate, CARPLAY
        if message.get('button') not in CARPLAY:
            return 'Unsupported CarPlay control'
        if not hasattr(self, 'button_gate'):
            self.button_gate = ButtonGate()
        command = self.button_gate.command(message, CARPLAY)
        if command is None:
            return ('Voice activation ended' if message.get('button') == 'voice_assistant'
                    and message.get('action') == 'deactivate' else 'Ignored release / duplicate')
        with self.cond:
            if not self.proc or self.proc.poll() is not None:
                return 'CarPlay USB bridge unavailable'
            if len(self.queue) >= 64:
                return 'CarPlay input queue full'
            with self.lock:
                if len(self.button_pending) >= 64:
                    return 'CarPlay command acknowledgements full'
                self.button_pending[message.get('sequence',0)] = message['button']
            self.queue.append(dict(type='button', command=command, button=message['button'],
                                   sequence=message.get('sequence',0), queued_at=time.monotonic()))
            self.cond.notify()
        return 'Queued to CarPlay USB'

    def apply_branding(self, request_id=None):
        with self.cond:
            if len(self.queue)>=64:
                self.adapter_branding='failed'
                return False
            self.adapter_branding='sending'
            self.adapter_branding_request_id=request_id
            self.pending_branding=dict(type='adapter.branding',request_id=request_id)
            self.queue.append(dict(self.pending_branding))
            self.cond.notify()
        return True

    def set_night_mode(self, night_mode):
        with self.cond:
            self.night_mode = night_mode
            self.cond.notify()

    def send_inputs(self, proc, sent_night_mode=False):
        while not self.stop_event.is_set() and proc.poll() is None:
            with self.cond:
                if self.night_mode != sent_night_mode:
                    sent_night_mode = self.night_mode
                    item = dict(type='projection.appearance', night_mode=sent_night_mode)
                elif self.queue or self.mic_queue:
                    item = dict(self.queue.popleft() if self.queue else self.mic_queue.popleft())
                else:
                    self.cond.wait(0.1)
                    continue
                item.pop("_motion", None)
                queued = item.pop("queued_at", None)
                if queued is not None and time.monotonic()-queued > 1:
                    self.notify("carplay_button_expired", sequence=item.get("sequence"))
                    self.finish_button(item.get('sequence'), 'Command expired')
                    continue
            try:
                proc.stdin.write((json.dumps(item) + "\n").encode())
                proc.stdin.flush()
            except (OSError, ValueError):
                self.finish_button(item.get('sequence'), 'CarPlay USB bridge write failed')
                return
            if item.get('type')!='microphone':self.notify("carplay_input_forwarded", **item)

    def microphone(self, pcm):
        if self.mic_format!=(16000,1) or len(pcm)%2:return False
        with self.cond:
            if not self.proc or self.proc.poll() is not None:return False
            for start in range(0,len(pcm),640):
                raw=pcm[start:start+640]
                if len(self.mic_queue)==self.mic_queue.maxlen:
                    old=self.mic_queue.popleft();self.mic_dropped+=old['bytes']
                self.mic_queue.append(dict(type='microphone',pcm=base64.b64encode(raw).decode(),bytes=len(raw)))
                self.mic_received+=len(raw)
            self.cond.notify()
        return True

    def voice_snapshot(self):
        with self.lock:
            if not self.proc or self.proc.poll() is not None or time.monotonic()-self.last_bridge_message>5:
                return dict(call_audio=False,siri=False,recording=False)
            voice = dict(self.voice)
            if voice['call_audio'] and self.call_details:
                voice['call'] = dict(self.call_details)
            return voice

    def finish_button(self, sequence, result):
        with self.lock:
            name = self.button_pending.pop(sequence, None)
            if name:
                self.button_results.append(dict(button=name, sequence=sequence, result=result))

    def take_button_results(self):
        with self.lock:
            results=list(self.button_results)
            self.button_results.clear()
            return results

    def take_host_ui_request(self):
        with self.lock:
            requested = self.host_ui_requested
            self.host_ui_requested = False
            return requested

    def metrics(self):
        with self.lock:
            return {
                "adapter_branding": self.adapter_branding,
                "adapter_branding_request_id":self.adapter_branding_request_id,
                "adapter_branding_error":self.adapter_branding_error,
                "decoded_frames": self.frames,
                "audio_packets_forwarded": self.audio_forwarded,
                "audio_packets_dropped": self.audio_dropped,
                **self.bridge_audio,
                "input_packets": self.decode_packets,
                "video_visible": self.visible.is_set(),
                "background_video_packets": self.background_video_packets,
                "mic_received_bytes":self.mic_received,"mic_dropped_bytes":self.mic_dropped+self.mic_usb_dropped,
                "mic_usb_bytes":self.mic_usb_bytes,"mic_usb_errors":self.mic_usb_errors,
                "decode_ms_avg": round(
                    self.decode_seconds * 1000 / max(1, self.decode_packets), 3
                ),
                "decode_ms_max": round(self.decode_max_ms, 3),
            }

    def set_visible(self, visible):
        if visible:
            self.visible.set()
        else:
            self.visible.clear()
            with self.lock:
                self.frame = None
                self.version += 1
        self.notify('carplay_visibility', visible=visible)

    def take_media(self):
        with self.lock:
            if not self.media_pending and not self.media_clear:
                return None
            fields, clear = self.media_pending, self.media_clear
            self.media_pending, self.media_clear = {}, False
            return fields, clear

    def queue_media(self, fields=None, clear=False):
        with self.lock:
            if clear:
                self.media_pending = {}
                self.media_clear = True
            self.media_pending.update(fields or {})

    def snapshot(self):
        with self.lock:
            frame = self.frame if self.phone_connected else None
            if (frame is not None and self.last_decoded_at is not None
                    and time.monotonic() - self.last_decoded_at >= VIDEO_TIMEOUT_SECONDS):
                return self.version, None, self.status_version, "CarPlay video paused. Check your iPhone connection."
            return self.version, frame, self.status_version, self.status

    def forward_audio(self, data):
        self.last_bridge_message = time.monotonic()
        if len(data) < 12:
            self.notify("carplay_audio_invalid", bytes=len(data))
            return
        decode_type, stream, volume = struct.unpack("<IIf", data[:12])
        formats = {1:(44100,2), 2:(44100,2), 3:(8000,1), 4:(48000,2), 5:(16000,1), 6:(24000,1), 7:(16000,2)}
        if decode_type in formats and 0 <= stream <= 255:
            try:
                voice_stream=stream in self.voice_streams.values() and any(self.voice_snapshot().values())
                accepted=(self.audio(data[12:],*formats[decode_type],stream,voice=True) if voice_stream
                          else self.audio(data[12:],*formats[decode_type],stream))
                if accepted:
                    self.audio_forwarded += 1
                else:
                    self.audio_dropped += 1
            except Exception as exc:
                self.notify("carplay_audio_forward_error", error=str(exc))

    def receive_connection_state(self, state):
        kind = state.get('state')
        if kind not in CONNECTION_STATUS:
            return
        with self.lock:
            self.phone_connected = kind == 'phone_connected'
            if not self.phone_connected:
                self.connection_epoch += 1
                self.last_decoded_at = None
                self.frame = None
                self.version += 1
                self.voice = dict(call_audio=False, siri=False, recording=False)
                self.call_details = {}
                self.voice_streams.clear()
            self.set_status(CONNECTION_STATUS[kind])

    def receive_state(self, state):
        self.last_bridge_message = time.monotonic()
        self.receive_connection_state(state)
        if state.get('state') == 'stream_stats':
            with self.lock:
                self.bridge_audio = {key: state[key] for key in
                                     ('pcm_packets', 'pcm_gap_max_ms', 'video_packets_dropped')
                                     if key in state}
        if state.get('state')=='projection_voice':
            fields=state.get('fields',{})
            if set(fields)==set(self.voice) and all(type(v) is bool for v in fields.values()):
                with self.lock:
                    if self.voice['call_audio'] and not fields['call_audio']:
                        self.call_details = {}
                    self.voice = dict(fields)
        if state.get('state') == 'projection_call':
            details = state.get('call')
            with self.lock:
                self.call_details = details if isinstance(details, dict) else {}
        if state.get('state')=='audio_control':
            command=state.get('command');stream=state.get('audio_type')
            role='call' if command in (4,5) else 'siri'
            if command in (4,8) and type(stream) is int and 0<=stream<=255:self.voice_streams[role]=stream
            if command in (5,9):self.voice_streams.pop(role,None)

    def run(self, w, h):
        decoder = None
        proc = None
        packets = None
        reader_stop = threading.Event()
        try:
            sys.path.insert(
                0, str(pathlib.Path(__file__).resolve().parent / "runtime/video")
            )
            from h264 import H264StreamDecoder

            picture = PictureSettings()
            def open_decoder():
                try:
                    result = H264StreamDecoder(w, h)
                    result.decoder.picture = dict(picture.values)
                    return result
                except (OSError, RuntimeError, ValueError) as exc:
                    self.notify('carplay_video_error', error=str(exc))
                    return None

            picture_check = 0
            last_color_metadata = None
            logdir = LOG_DIR
            logdir.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                err = stack.enter_context((logdir / f"carplay-hdmi-node-{time.time_ns()}.log").open("wb"))
                pcm_reader, pcm_writer = socket.socketpair()
                stack.enter_context(pcm_reader)
                stack.enter_context(pcm_writer)
                pcm = stack.enter_context(pcm_reader.makefile('rb', buffering=0))
                initial_night_mode = self.night_mode
                env = dict(os.environ, CIVIC_CARPLAY_RESET="0",
                           HLAUNCHER_NIGHT_MODE='1' if initial_night_mode else '0',
                           HLAUNCHER_CARPLAY_PCM_FD=str(pcm_writer.fileno()))
                proc = subprocess.Popen(
                    ["/usr/bin/node", str(RUNTIME / "bridge.mjs")],
                    cwd=RUNTIME,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=err,
                    bufsize=0,
                    env=env,
                    pass_fds=(*inherited_fds(), pcm_writer.fileno()),
                )
                pcm_writer.close()
                self.proc = proc
                self.notify("carplay_hdmi_bridge_started", pid=proc.pid)
                threading.Thread(
                    target=self.send_inputs, args=(proc, initial_night_mode), daemon=True
                ).start()
                packets = BridgePackets(pcm, reader_stop, self.forward_audio, self.receive_state,
                                        video=proc.stdout)
                # On Linux nice is per thread. The bridge, audio reader and input
                # threads above keep their original priority.
                if sys.platform.startswith('linux'):
                    try:
                        os.nice(5)
                    except OSError as exc:
                        self.notify('carplay_video_priority_error', error=str(exc))
                decoder = open_decoder()
                last_visible = False
                decoded_epoch = None
                while not self.stop_event.is_set():
                    visible = self.visible.is_set()
                    if decoder and visible and not last_visible:
                        preview = decoder.decoder.redraw() if self.phone_connected else None
                        if preview is not None:
                            with self.lock:
                                if self.phone_connected and decoded_epoch == self.connection_epoch:
                                    self.frame = preview
                                    self.version += 1
                    last_visible = visible
                    if time.monotonic() - picture_check > .1:
                        picture_check = time.monotonic()
                        if picture.refresh() and decoder:
                            decoder.decoder.picture = dict(picture.values)
                            preview = decoder.decoder.redraw() if visible and self.phone_connected else None
                            if preview is not None:
                                with self.lock:
                                    if self.phone_connected and decoded_epoch == self.connection_epoch:
                                        self.frame = preview
                                        self.version += 1
                            self.notify('display_picture_applied', **picture.values)
                    packet = packets.take()
                    if packet is None:
                        continue
                    kind, data = packet
                    if kind == 4:
                        if decoder:
                            decoder.close()
                        decoder = open_decoder()
                        continue
                    if kind == 1:
                        if decoder is None:
                            continue
                        with self.lock:
                            frame_epoch = self.connection_epoch if self.phone_connected else None
                        began = time.perf_counter()
                        try:
                            pictures = decoder.feed(data, render=visible)
                        except (RuntimeError, ValueError) as exc:
                            self.notify('carplay_video_error', error=str(exc))
                            decoder.close()
                            decoder = open_decoder()
                            continue
                        if not visible:
                            self.background_video_packets += 1
                        elapsed = time.perf_counter() - began
                        if pictures and decoder.decoder.conversion_color != last_color_metadata:
                            last_color_metadata = dict(decoder.decoder.conversion_color)
                            self.notify('carplay_color_conversion', **last_color_metadata)
                        with self.lock:
                            self.decode_packets += 1
                            self.decode_seconds += elapsed
                            self.decode_max_ms = max(self.decode_max_ms, elapsed * 1000)
                        for frame in pictures:
                            with self.lock:
                                if not self.phone_connected or frame_epoch != self.connection_epoch:
                                    continue
                                decoded_epoch = frame_epoch
                                self.last_decoded_at = time.monotonic()
                                self.frame = frame
                                self.version += 1
                                self.frames += 1
                            if self.frames == 1:
                                self.notify(
                                    "carplay_hdmi_first_frame",
                                    bytes=len(frame),
                                    width=w,
                                    height=h,
                                )
                        if pictures and self.frames and self.frames % 30 == 0:
                            self.notify("carplay_hdmi_frame_count", frames=self.frames)
                    else:
                        state = json.loads(data)
                        self.notify("carplay_hdmi_status", bridge=state)
                        if state.get('state')=='adapter_branding':
                            with self.lock:
                                self.adapter_branding=state.get('result','failed')
                                self.adapter_branding_request_id=state.get('request_id')
                                self.adapter_branding_error=state.get('error','')
                                if self.pending_branding and self.pending_branding.get('request_id')==self.adapter_branding_request_id and self.adapter_branding in ('sent','transferred','failed'):self.pending_branding=None
                        if state.get('state')=='stream_stats':
                            self.mic_usb_bytes=int(state.get('mic_bytes',0));self.mic_usb_errors=int(state.get('mic_errors',0))
                            self.mic_usb_dropped=int(state.get('mic_dropped',0))
                        if state.get('state') in ('button_usb_result','button_expired'):
                            sequence=state.get('sequence')
                            result={'sent':'Sent over USB','failed':'USB send failed','no_device':'USB device unavailable',
                                    'error':'USB send failed'}.get(state.get('result'),'Command expired')
                            self.finish_button(sequence, result)
                        if state.get('state') == 'media_metadata':
                            self.queue_media(normalize(state.get('media')))
                        elif state.get('state') in ('phone_disconnected', 'usb_failure'):
                            self.queue_media(clear=True)
                        if state.get("state") == "host_ui_requested":
                            with self.lock:
                                self.host_ui_requested = True
        except Exception as exc:
            if not self.stop_event.is_set():
                with self.lock:
                    self.frame = None
                    self.version += 1
                self.queue_media(clear=True)
                self.set_status("CarPlay stopped: " + str(exc)[:90])
                self.notify("carplay_hdmi_error", error=repr(exc))
        finally:
            reader_stop.set()
            with self.lock:
                for sequence in list(self.button_pending):
                    self.finish_button(sequence, 'CarPlay USB bridge stopped')
            if decoder:
                decoder.close()
            if proc:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                self.reap(proc)
                if packets:
                    packets.thread.join(timeout=2)
                if proc.poll() is not None:
                    for stream in (proc.stdin, proc.stdout):
                        if stream:
                            stream.close()
            with self.lock:
                self.voice = dict(call_audio=False, siri=False, recording=False)
                self.call_details = {}
                self.voice_streams.clear()
            self.proc = None
