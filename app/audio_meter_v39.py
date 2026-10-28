"""Process-isolated level probe; no capture code runs in the launcher process."""

import json, os, pathlib, signal, subprocess, sys, threading, time


class AudioMeter:
    def __init__(self, event=lambda **v: None):
        self.event = event
        self.lock = threading.Lock()
        self.proc = None
        self.state = dict(
            status="Select Microphone test",
            dbfs=-90.0,
            peak=0.0,
            bytes=0,
            rate=0,
            codec="",
            channels=0,
            running=False,
        )

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        with self.lock:
            self.state.update(
                status="Starting isolated microphone probe...",
                dbfs=-90.0,
                peak=0.0,
                bytes=0,
                rate=0,
                codec="",
                channels=0,
                running=True,
            )
        try:
            p = subprocess.Popen(
                [
                    sys.executable,
                    str(pathlib.Path(__file__).with_name("mic_worker_v39.py")),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                start_new_session=True,
            )
            self.proc = p
            threading.Thread(target=self.read, args=(p,), daemon=True).start()
        except OSError as exc:
            with self.lock:
                self.state.update(
                    status="Microphone probe could not start. Tap Retry.", running=False
                )
            self.event(state="mic_probe_launch_error", error=str(exc))

    def read(self, p):
        had_status = False
        try:
            while True:
                line = p.stdout.readline(8193)
                if not line:
                    break
                if len(line) > 8192:
                    raise ValueError("oversized microphone diagnostic")
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                if self.proc is not p:
                    return
                if v.get("type") == "status":
                    x = v["value"]
                    if not isinstance(x, dict):
                        continue
                    allowed = {
                        k: x[k]
                        for k in (
                            "status",
                            "dbfs",
                            "peak",
                            "bytes",
                            "rate",
                            "codec",
                            "channels",
                        )
                        if k in x
                    }
                    with self.lock:
                        self.state.update(allowed)
                    had_status = True
                elif v.get("type") == "event":
                    self.event(**v["value"])
            code = p.wait(timeout=1)
            if self.proc is p:
                with self.lock:
                    self.state["running"] = False
                    if code != 0 or not had_status:
                        self.state.update(
                            status="Microphone probe stopped. Tap Retry.",
                            dbfs=-90.0,
                            peak=0.0,
                        )
                self.event(state="mic_probe_exit", code=code)
        except Exception as exc:
            if self.proc is p:
                with self.lock:
                    self.state.update(
                        status="Microphone probe failed. Tap Retry.",
                        running=False,
                        dbfs=-90.0,
                        peak=0.0,
                    )
                self.event(state="mic_probe_error", error=str(exc))
            self.terminate(p)
        finally:
            p.stdout.close()

    def stop(self):
        p = self.proc
        self.proc = None
        with self.lock:
            self.state.update(running=False, dbfs=-90.0, peak=0.0)
        if p:
            self.terminate(p)

    @staticmethod
    def terminate(p):
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        def reap():
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            # Also kill descendants if the supervisor exited before its capture child.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        threading.Thread(target=reap, daemon=True).start()
