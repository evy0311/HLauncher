"""On-demand Honda HFP microphone level meter. PCM is never saved or forwarded."""

import array, math, os, select, subprocess, threading, time, sys
from settings import RADIO_ADDRESS as DEVICE, RADIO_PATH as PATH


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


class AudioMeter:
    def __init__(self, event=lambda **v: None):
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
