"""Reuse installed node-carplay bridge/H264 decoder; bounded asynchronous input."""

import json, os, pathlib, struct, subprocess, sys, threading, time, select
from hlauncher_sdk.picture import PictureSettings
from collections import deque
from input import TouchRouter
from media import normalize

RUNTIME = pathlib.Path(__file__).resolve().parent / "runtime/usb"
LOG_DIR = pathlib.Path(
    os.environ.get("HLAUNCHER_LOG_DIR", "/var/log/hlauncher/carplay")
)


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
    if kind not in (1, 2, 3) or n > 8 * 1024 * 1024:
        raise ValueError("invalid bridge packet")
    return kind, exact(n)


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
        self.version = 0
        self.status = "Select CarPlay"
        self.status_version = 0
        self.touch_router = TouchRouter()
        self.frames = 0
        self.host_ui_requested = False
        self.audio_forwarded = self.audio_dropped = 0
        self.decode_packets = 0
        self.decode_seconds = 0.0
        self.decode_max_ms = 0.0
        self.media_pending = {}
        self.media_clear = False
        self.visible = threading.Event()
        self.background_video_packets = 0

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
        self.touch_router = TouchRouter()
        self.frame = None
        self.frames = 0
        self.host_ui_requested = False
        self.set_status("Starting CarPlay")
        self.thread = threading.Thread(target=self.run, args=(w, h), daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()
        with self.cond:
            self.queue.clear()
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

    def send_inputs(self, proc):
        while not self.stop_event.is_set() and proc.poll() is None:
            with self.cond:
                if not self.queue:
                    self.cond.wait(0.1)
                    continue
                item = dict(self.queue.popleft())
                item.pop("_motion", None)
            try:
                proc.stdin.write((json.dumps(item) + "\n").encode())
                proc.stdin.flush()
            except (OSError, ValueError):
                return
            self.notify("carplay_hdmi_touch_forwarded", **item)

    def take_host_ui_request(self):
        with self.lock:
            requested = self.host_ui_requested
            self.host_ui_requested = False
            return requested

    def metrics(self):
        with self.lock:
            return {
                "decoded_frames": self.frames,
                "audio_packets_forwarded": self.audio_forwarded,
                "audio_packets_dropped": self.audio_dropped,
                "input_packets": self.decode_packets,
                "video_visible": self.visible.is_set(),
                "background_video_packets": self.background_video_packets,
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
            return self.version, self.frame, self.status_version, self.status

    def run(self, w, h):
        decoder = None
        proc = None
        try:
            sys.path.insert(
                0, str(pathlib.Path(__file__).resolve().parent / "runtime/video")
            )
            from h264 import H264StreamDecoder

            decoder = H264StreamDecoder(w, h)
            picture = PictureSettings()
            decoder.decoder.picture = dict(picture.values)
            picture_check = 0
            last_color_metadata = None
            logdir = LOG_DIR
            logdir.mkdir(parents=True, exist_ok=True)
            with (logdir / f"carplay-hdmi-node-{time.time_ns()}.log").open("wb") as err:
                env = dict(os.environ, CIVIC_CARPLAY_FPS="60", CIVIC_CARPLAY_RESET="0")
                proc = subprocess.Popen(
                    ["/usr/bin/node", str(RUNTIME / "bridge.mjs")],
                    cwd=RUNTIME,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=err,
                    bufsize=0,
                    env=env,
                )
                self.proc = proc
                self.notify("carplay_hdmi_bridge_started", pid=proc.pid)
                threading.Thread(
                    target=self.send_inputs, args=(proc,), daemon=True
                ).start()
                titles = {
                    "waiting_dongle": "Waiting for Carlinkit USB dongle",
                    "dongle_ready": "Connect iPhone to Carlinkit",
                    "phone_connected": "iPhone connected; waiting for video",
                    "phone_disconnected": "iPhone disconnected",
                    "usb_failure": "USB dongle connection lost",
                }
                last_visible = False
                while not self.stop_event.is_set():
                    visible = self.visible.is_set()
                    if visible and not last_visible:
                        preview = decoder.decoder.redraw()
                        if preview is not None:
                            with self.lock:
                                self.frame = preview
                                self.version += 1
                    last_visible = visible
                    if time.monotonic() - picture_check > .1:
                        picture_check = time.monotonic()
                        if picture.refresh():
                            decoder.decoder.picture = dict(picture.values)
                            preview = decoder.decoder.redraw() if visible else None
                            if preview is not None:
                                with self.lock:
                                    self.frame = preview
                                    self.version += 1
                            self.notify('carplay_picture_applied', **picture.values)
                    if not select.select([proc.stdout], [], [], .05)[0]:
                        continue
                    kind, data = read_packet(proc.stdout)
                    if kind == 1:
                        began = time.perf_counter()
                        pictures = decoder.feed(data, render=visible)
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
                    elif kind == 3:
                        if len(data) < 12:
                            self.notify("carplay_audio_invalid", bytes=len(data))
                            continue
                        decode_type, stream, volume = struct.unpack("<IIf", data[:12])
                        formats = {1:(44100,2), 2:(44100,2), 3:(8000,1), 4:(48000,2), 5:(16000,1), 6:(24000,1), 7:(16000,2)}
                        if decode_type in formats and 0 <= stream <= 255:
                            try:
                                if self.audio(data[12:], *formats[decode_type], stream):
                                    self.audio_forwarded += 1
                                else:
                                    self.audio_dropped += 1
                            except Exception as exc:
                                self.notify("carplay_audio_forward_error", error=str(exc))
                    else:
                        state = json.loads(data)
                        self.notify("carplay_hdmi_status", bridge=state)
                        if state.get('state') == 'media_metadata':
                            self.queue_media(normalize(state.get('media')))
                        if state.get("state") == "host_ui_requested":
                            with self.lock:
                                self.host_ui_requested = True
                        if state.get("state") in titles:
                            self.set_status(titles[state["state"]])
                            if state["state"] in ("phone_disconnected", "usb_failure"):
                                self.queue_media(clear=True)
                                with self.lock:
                                    self.frame = None
                                    self.version += 1
        except Exception as exc:
            if not self.stop_event.is_set():
                with self.lock:
                    self.frame = None
                    self.version += 1
                self.queue_media(clear=True)
                self.set_status("CarPlay stopped: " + str(exc)[:90])
                self.notify("carplay_hdmi_error", error=repr(exc))
        finally:
            if decoder:
                decoder.close()
            if proc:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                self.reap(proc)
                if proc.poll() is not None:
                    for stream in (proc.stdin, proc.stdout):
                        if stream:
                            stream.close()
            self.proc = None
