import sys, time, subprocess
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import audio_meter_v39 as backend
import launcher_hdmi_v42 as ui
from audio_meter_v37 import levels

assert levels(b"\0" * 1600) == (-90.0, 0.0)
real_popen = subprocess.Popen


# A disposable worker exits unexpectedly; the parent remains usable and can retry.
def failed_worker(*args, **kwargs):
    return real_popen([sys.executable, "-c", "import os;os._exit(42)"], **kwargs)


with patch.object(backend.subprocess, "Popen", failed_worker):
    m = backend.AudioMeter()
    for i in range(2):
        m.start()
        deadline = time.monotonic() + 3
        while m.snapshot()["running"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not m.snapshot()["running"] and "Retry" in m.snapshot()["status"]
    m.stop()


class FB:
    def __init__(self):
        self.w = 720
        self.h = 480
        self.images = []

    def open(self):
        pass

    def image(self, im):
        self.images.append(im)

    def close(self):
        pass


class Overlay:
    def reset(self):
        pass

    def update(self, x):
        pass

    def tick(self):
        pass

    def close(self):
        pass


class Meter:
    def __init__(self, event):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def enable_test_call(self):
        self.enabled = True

    def snapshot(self):
        return dict(
            call_mode=getattr(self, "enabled", False),
            gate_status="test",
            status="Probe stopped. Tap Retry.",
            dbfs=-90.0,
            peak=0.0,
            rate=0,
            codec="",
            bytes=0,
        )


class Carplay:
    def __init__(self, event):
        pass

    def start(self, *a):
        self.starts = getattr(self, "starts", 0) + 1
        return True

    def stop(self):
        pass


with patch.object(ui, "Framebuffer", FB), patch.object(
    ui, "TouchOverlay", Overlay
), patch.object(ui, "AudioMeter", Meter), patch.object(ui, "CarplayHDMI", Carplay):
    u = ui.Launcher()
    assert u.launch("com.honda.hondalink.connect")
    assert len(u.tiles) == 2

    def tap(x, y):
        for action in ("down", "up"):
            u.update(
                {
                    "contacts": [
                        dict(
                            action=action,
                            has_position=action == "down",
                            x_raw=round(x * 32767 / 719),
                            y_raw=round(y * 32767 / 479),
                        )
                    ]
                }
            )

    tap(140, 210)
    assert u.mode == "audio" and u.audio.starts == 1
    u.tick()
    tap(600, 440)
    assert u.audio.starts == 2
    tap(120, 440)
    assert u.audio.enabled
    assert u.launch("com.honda.hondalink.connect") and u.mode == "audio"
    tap(20, 20)
    assert u.mode == "home"
    assert not getattr(u.carplay, "starts", 0)
    tap(500, 210)
    assert u.mode == "carplay" and u.carplay.starts == 1
    assert u.audio.stops > 0
    tap(20, 20)
    assert u.mode == "home"
    tap(140, 210)
    assert u.mode == "audio" and u.carplay.starts == 1
    u.show("touch")
    assert u.mode == "touch"  # Hidden, not removed.
    u.close()
print(
    "PASS: worker crash isolated, Retry can launch again; microphone tile/Retry/Home; hidden Touch test retained; CarPlay button starts bridge; microphone page does not start CarPlay."
)

from hfp_test_call_v41 import response, BEGIN, END

assert response("AT+CLCC") == ("+CLCC:1,0,0,0,0", "OK")
assert BEGIN[-1] == "+CIEV:2,1" and END[0] == "+CIEV:2,0"
print(
    "PASS: bounded mic-enable control routing and Mic page retained on HondaLink relaunch during test."
)

import io
import audio_meter_v41 as combined


class Gate:
    def __init__(self, payload, code):
        self.stdout = io.BytesIO(payload)
        self.code = code

    def wait(self, timeout=None):
        return self.code


# A normal gate exit reports its cleanup; an abrupt exit requests independent cleanup.
m = combined.AudioMeter()
p = Gate(b'{"state":"mic_test_call_cleared"}\n', 0)
m.gate = p
with patch.object(combined.subprocess, "run") as fallback:
    m.read_gate(p)
    assert m.gate is None and not m.gate_active
    fallback.assert_not_called()
p = Gate(b"", 42)
m.gate = p
with patch.object(
    combined.subprocess,
    "run",
    return_value=subprocess.CompletedProcess(
        [], 0, b'{"state":"mic_test_call_cleared"}'
    ),
) as fallback:
    m.read_gate(p)
    fallback.assert_called_once()
    assert m.gate is None and not m.gate_active
with patch.object(m, "end_test_call") as end:
    m.handle_event(state="mic_probe_exit")
    end.assert_called_once()
print(
    "PASS: normal gate cleanup, fallback after abrupt gate exit, and capture-failure gate shutdown."
)
