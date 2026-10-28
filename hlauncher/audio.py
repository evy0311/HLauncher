"""Core-owned HFP capture. PCM is delivered only to the requesting plugin."""

import array, math, os, select, subprocess, threading, time, sys
from .playback import Playback
from .config import RADIO_ADDRESS as DEVICE, RADIO_PATH as PATH


def levels(raw):
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return -90.0, 0.0
    rms = math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768
    peak = max(abs(x) for x in samples) / 32768
    return max(-90.0, 20 * math.log10(max(rms, 1e-12))), peak


class Capture:
    def __init__(self, event=lambda **v: None, pcm=lambda *args: None):
        self.pcm = pcm
        self.event = event
        self.lock = threading.Lock()
        self.thread = None
        self.cancel = threading.Event()
        self.state = {
            "status": "Select Audio test",
            "dbfs": -90.0,
            "peak": 0.0,
            "bytes": 0,
            "rate": 0,
            "codec": "",
            "channels": 0,
        }
        self.proc = None

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.cancel = threading.Event()
        self.update(
            status="Checking hands-free microphone...",
            dbfs=-90.0,
            peak=0.0,
            bytes=0,
            rate=0,
            codec="",
            channels=0,
        )
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def run(self):
        p = None
        bus = None
        try:
            import dbus

            bus = dbus.SystemBus(private=True)
            manager = dbus.Interface(
                bus.get_object("org.bluealsa", "/org/bluealsa"),
                "org.freedesktop.DBus.ObjectManager",
            )

            def find():
                for path, ifaces in manager.GetManagedObjects(timeout=3).items():
                    v = ifaces.get("org.bluealsa.PCM1", {})
                    if (
                        str(v.get("Device", "")) == PATH
                        and str(v.get("Transport", "")) == "HFP-AG"
                        and str(v.get("Mode", "")) == "source"
                    ):
                        return dict(v)

            v = find()
            if not v:
                self.update(status="Connecting Bluetooth hands-free profile...")
                try:
                    dbus.Interface(
                        bus.get_object("org.bluez", PATH), "org.bluez.Device1"
                    ).ConnectProfile("0000111e-0000-1000-8000-00805f9b34fb", timeout=8)
                except dbus.DBusException as exc:
                    self.event(state="audio_hfp_connect_error", error=str(exc))
                end = time.monotonic() + 4
                while not self.cancel.is_set() and time.monotonic() < end:
                    v = find()
                    if v:
                        break
                    self.cancel.wait(0.1)
            if self.cancel.is_set():
                return
            if not v:
                raise RuntimeError("Hands-free microphone unavailable. Tap Retry.")
            rate = int(v["Sampling"])
            channels = int(v["Channels"])
            codec = str(v["Codec"])
            if rate <= 0 or channels != 1:
                raise RuntimeError("Unsupported microphone PCM configuration")
            self.update(
                rate=rate,
                channels=channels,
                codec=codec,
                status="Opening radio microphone...",
            )
            self.event(
                state="audio_meter_pcm", rate=rate, channels=channels, codec=codec
            )
            p = subprocess.Popen(
                [
                    "/usr/bin/arecord",
                    "-q",
                    "-D",
                    f"bluealsa:DEV={DEVICE},PROFILE=sco",
                    "-t",
                    "raw",
                    "-f",
                    "S16_LE",
                    "-r",
                    str(rate),
                    "-c",
                    str(channels),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self.proc = p
            last = time.monotonic()
            total = 0
            last_log = 0
            carry = b""
            diagnostics = ""
            stderr_open = True
            while not self.cancel.is_set():
                ready, _, _ = select.select(
                    [p.stdout] + ([p.stderr] if stderr_open else []), [], [], 0.2
                )
                for stream in ready:
                    b = os.read(stream.fileno(), 3200)
                    if stream is p.stderr:
                        if b:
                            diagnostics = (diagnostics + b.decode(errors="replace"))[
                                -1200:
                            ]
                        else:
                            stderr_open = False
                        continue
                    if not b:
                        raise RuntimeError(
                            "Capture ended: " + diagnostics[-180:].strip()
                        )
                    last = time.monotonic()
                    total += len(b)
                    data = carry + b
                    end = len(data) // 2 * 2
                    carry = data[end:]
                    dbfs, peak = levels(data[:end])
                    self.pcm(data[:end], rate, channels)
                    self.update(
                        status=(
                            "Receiving microphone PCM"
                            if peak
                            else "Receiving PCM: digital silence"
                        ),
                        dbfs=dbfs,
                        peak=peak,
                        bytes=total,
                    )
                    if last - last_log >= 1:
                        self.event(
                            state="audio_meter_level",
                            dbfs=round(dbfs, 1),
                            peak=round(peak, 4),
                            bytes=total,
                        )
                        last_log = last
                if time.monotonic() - last > 3:
                    self.update(
                        status="No microphone samples yet; radio may need voice mode",
                        dbfs=-90.0,
                        peak=0.0,
                    )
                if p.poll() is not None:
                    raise RuntimeError("Capture exited: " + diagnostics[-180:].strip())
        except Exception as exc:
            if not self.cancel.is_set():
                text = str(exc)
                if text.startswith(("Capture ended:", "Capture exited:")):
                    text = "Microphone stream closed. Tap Retry."
                self.update(status=text, dbfs=-90.0, peak=0.0)
                self.event(state="audio_meter_error", error=str(exc))
        finally:
            if p:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        p.kill()
                for stream in (p.stdout, p.stderr):
                    stream.close()
            if bus:
                bus.close()
            self.proc = None


class AudioBroker:
    """Shared radio audio resources. PCM capture is opt-in; playback is routed to HDMI."""

    def __init__(self, event):
        self.event = event
        self.playback = Playback(event)
        self.owner = None
        self.capture = None
        self.worker = None
        self.format = None
        self.dropped = 0
        self.generation = 0

    def stop(self, plugin_id):
        self.playback.stop(plugin_id)
        self.stop_capture(plugin_id)

    def stop_capture(self, plugin_id):
        if self.owner != plugin_id:
            return
        self.generation += 1
        self.owner = None
        self.worker = None
        capture, self.capture = self.capture, None
        if capture:
            capture.stop()
        self.event(state="plugin_audio_stopped", plugin=plugin_id)

    def request(self, worker, message, active):
        request_id = message.get("request_id")
        kind = message["type"]
        allowed = "audio.capture" in worker.manifest.capabilities
        if kind == "audio.playback.pcm":
            if "audio.playback" not in worker.manifest.capabilities or not (active or getattr(worker, "background_enabled", False)):
                return
            try:
                self.playback.feed(worker.manifest.id, message)
            except Exception as exc:
                self.event(state="audio_playback_rejected", error=str(exc))
            return
        if kind == "audio.status" and (
            allowed or "audio.status" in worker.manifest.capabilities
        ):
            worker.send(
                type="audio.status",
                request_id=request_id,
                capture_supported=True,
                playback_supported=True,
                playback_route="hdmi",
                microphone_gated_by_radio=True,
                capturing=self.owner == worker.manifest.id,
            )
        elif kind == "audio.capture.start" and allowed and active:
            if self.owner and self.owner != worker.manifest.id:
                worker.send(
                    type="audio.error",
                    request_id=request_id,
                    error="Radio capture already in use",
                )
                return
            if not self.capture:
                self.owner = worker.manifest.id
                self.worker = worker
                self.format = None
                self.generation += 1
                generation = self.generation
                self.capture = Capture(
                    lambda **values: self.capture_event(generation, **values),
                    lambda *values: self.pcm(generation, *values),
                )
                self.capture.start()
            worker.send(type="audio.capture.started", request_id=request_id)
        elif kind == "audio.capture.stop" and allowed:
            self.stop(worker.manifest.id)
            worker.send(type="audio.capture.stopped", request_id=request_id)
        else:
            worker.send(
                type="audio.error",
                request_id=request_id,
                error="Audio request unsupported or not permitted",
            )

    def capture_event(self, generation, **values):
        self.event(**values)
        if (
            generation == self.generation
            and self.worker
            and values.get("state") == "audio_meter_error"
        ):
            self.worker.send(
                type="audio.error", error=str(values.get("error", "Capture failed"))
            )

    def pcm(self, generation, data, rate, channels):
        if generation != self.generation:
            return
        worker = self.worker
        if not worker or not worker.active:
            return
        fmt = (rate, channels)
        if self.format != fmt:
            if not worker.send(
                type="audio.format",
                sample_format="s16le",
                sample_rate=rate,
                channels=channels,
            ):
                return
            self.format = fmt
        for start in range(0, len(data), 4096):
            if not worker.send_raw(b"A" + data[start : start + 4096]):
                self.dropped += 1
