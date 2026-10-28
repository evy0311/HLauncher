"""Isolated capture plus a bounded local HFP microphone-enable test."""

import json, os, pathlib, signal, subprocess, sys, threading
from audio_meter_v39 import AudioMeter as CaptureMeter


class AudioMeter(CaptureMeter):
    def __init__(self, event=lambda **v: None):
        self.gate = None
        self.gate_active = False
        self.gate_status = "Enable mic uses a 60-second local test call"
        self.outer_event = event
        super().__init__(self.handle_event)

    def handle_event(self, **v):
        if v.get("state") in (
            "mic_probe_exit",
            "mic_probe_error",
            "mic_probe_launch_error",
        ):
            self.end_test_call()
        self.outer_event(**v)

    def snapshot(self):
        v = super().snapshot()
        v.update(call_mode=self.gate_active, gate_status=self.gate_status)
        return v

    def enable_test_call(self):
        if self.gate:
            if self.gate.poll() is None:
                self.end_test_call()
            return
        if not self.snapshot()["running"] or not self.snapshot()["rate"]:
            self.gate_status = "Connect microphone first, then enable mic"
            return
        self.gate_status = "Enabling microphone test..."
        try:
            p = subprocess.Popen(
                [
                    sys.executable,
                    str(pathlib.Path(__file__).with_name("hfp_test_call_v41.py")),
                    "--seconds",
                    "60",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                bufsize=0,
            )
            self.gate = p
            threading.Thread(target=self.read_gate, args=(p,), daemon=True).start()
        except OSError as exc:
            self.gate_status = "Could not enable microphone test"
            self.outer_event(state="mic_test_gate_error", error=str(exc))

    def read_gate(self, p):
        code = None
        cleared = False
        try:
            for line in p.stdout:
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                if self.gate is not p:
                    return
                state = v.get("state")
                if state == "mic_test_call_enabled":
                    self.gate_active = True
                    self.gate_status = (
                        "Mic enabled (60s). Return via HondaLink if needed."
                    )
                if state == "mic_test_call_cleared":
                    cleared = True
                    self.gate_active = False
                    self.gate_status = "Mic test ended; enable again to repeat"
                self.outer_event(**v)
            code = p.wait(timeout=1)
        except Exception as exc:
            self.outer_event(state="mic_test_gate_reader_error", error=str(exc))
        finally:
            p.stdout.close()
            if self.gate is p:
                self.gate_active = False
                if not cleared:
                    self.gate_status = "Mic test stopped; requesting call-state cleanup"
                    # Keep this gate busy until fallback cleanup finishes, off the UI thread.
                    try:
                        result = subprocess.run(
                            [
                                sys.executable,
                                str(
                                    pathlib.Path(__file__).with_name(
                                        "hfp_test_call_v41.py"
                                    )
                                ),
                                "--clear-only",
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            timeout=4,
                        )
                        cleared = (
                            result.returncode == 0
                            and b'"mic_test_call_cleared"' in result.stdout
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        cleared = False
                    self.outer_event(
                        state="mic_test_gate_fallback_cleanup",
                        commands_sent=cleared,
                        radio_state_verified=False,
                    )
                    self.gate_status = (
                        "Mic test ended; enable again to repeat"
                        if cleared
                        else "Cleanup could not be confirmed; exit the radio phone screen"
                    )
                self.gate = None

    def end_test_call(self):
        p = self.gate
        if p and p.poll() is None:
            self.gate_status = "Ending microphone test..."
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

            def reap():
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            threading.Thread(target=reap, daemon=True).start()

    def stop(self):
        self.end_test_call()
        super().stop()
