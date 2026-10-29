"""CarPlay plugin. Radio transport and display ownership belong to HLauncher."""

import time
import json
from hlauncher_sdk import Client
from backend import CarplayHDMI


def main():
    client = Client()
    backend = CarplayHDMI(lambda **event: print(json.dumps(event), flush=True), audio=client.playback)
    active = False
    last_frame = -1
    last_status = -1
    heartbeat = 0
    last_video = None
    published_frames = 0
    slot_backpressure = 0
    pending_media = {}
    clear_media = False
    try:
        while True:
            while message := client.receive(0):
                kind = message["type"]
                if kind == "host.activate":
                    active = True
                    backend.set_visible(True)
                    last_frame = last_status = -1
                    backend.start(client.width, client.height)
                elif kind in ("host.deactivate", "touch.cancel"):
                    backend.touch({"contacts": []})
                    if kind == "host.deactivate":
                        active = False
                        backend.set_visible(False)
                elif kind == "touch" and active:
                    backend.touch(message)
                elif kind == "radio.button":
                    print(json.dumps(dict(state="radio_button_received", **message)), flush=True)
                elif kind == "host.stop":
                    return
            if backend.take_host_ui_request():
                client.home()
                active = False
                backend.set_visible(False)
            if report := backend.take_media():
                fields, clear = report
                if clear:
                    pending_media = {}
                    clear_media = True
                pending_media.update(fields)
            if pending_media or clear_media:
                if client.now_playing(clear=clear_media, **pending_media):
                    pending_media, clear_media = {}, False
            version, frame, status_version, status = backend.snapshot()
            if status_version != last_status or (frame is not None) != last_video:
                if client.status(status, video_available=frame is not None):
                    last_status = status_version
                    last_video = frame is not None
            if active and frame is not None and version != last_frame:
                if client.present(frame):
                    last_frame = version
                    published_frames += 1
                else:
                    slot_backpressure += 1
            if time.monotonic() - heartbeat > 2:
                client.send(
                    type="health",
                    metrics=dict(
                        backend.metrics(),
                        published_frames=published_frames,
                        slot_backpressure=slot_backpressure,
                    ),
                )
                heartbeat = time.monotonic()
            time.sleep(0.001 if active else 0.02)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        backend.stop()
        client.close()


if __name__ == "__main__":
    main()
