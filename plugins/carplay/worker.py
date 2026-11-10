"""CarPlay plugin. Radio transport and display ownership belong to HLauncher."""

import time
import json
from hlauncher_sdk import Client
from hlauncher_sdk.buttons import CARPLAY
from backend import CarplayHDMI


def main():
    client = Client()
    backend = CarplayHDMI(lambda **event: print(json.dumps(event), flush=True), audio=client.playback)
    active = False
    started=False
    restart_at=0
    last_frame = -1
    last_status = -1
    heartbeat = 0
    last_video = None
    published_frames = 0
    slot_backpressure = 0
    pending_media = {}
    clear_media = False
    subscribed = False
    radio_ready = False
    capture_requested = False
    capture_retry = 0
    voice_sent = None
    voice_sent_at = 0
    mic_metrics_sent = None
    try:
        while True:
            if not subscribed:
                subscribed = client.subscribe_buttons(CARPLAY)
            while message := client.receive(0):
                kind = message["type"]
                if kind in ("host.activate","host.start"):
                    active = kind=="host.activate"
                    backend.set_visible(active)
                    last_frame = last_status = -1
                    backend.start(client.width, client.height)
                    started=True
                elif kind in ("host.deactivate", "touch.cancel"):
                    backend.touch({"contacts": []})
                    if kind == "host.deactivate":
                        active = False
                        backend.set_visible(False)
                elif kind == "touch" and active:
                    backend.touch(message)
                elif kind == "host.adapter.branding":
                    backend.apply_branding(message.get("request_id"))
                elif kind == "radio.button":
                    result = backend.button(message)
                    client.send(type='radio.button.result', button=message.get('button'),
                                sequence=message.get('sequence'), result=result,
                                final=result != 'Queued to CarPlay USB')
                    print(json.dumps(dict(state="radio_button_received", result=result, **message)), flush=True)
                elif kind == 'radio.session':
                    radio_ready=bool(message.get('connected') and message.get('authenticated'))
                elif kind == 'audio.format':
                    backend.mic_format=(message.get('sample_rate'),message.get('channels'))
                elif kind == 'audio.pcm':
                    backend.microphone(message['pcm'])
                elif kind == 'audio.error':
                    capture_requested=False;capture_retry=time.monotonic()+2
                elif kind == 'audio.capture.stopped':
                    capture_requested=False;backend.mic_format=None
                elif kind == "host.stop":
                    return
            if started and backend.thread and not backend.thread.is_alive() and time.monotonic()>=restart_at:
                backend.start(client.width,client.height)
                restart_at=time.monotonic()+3
            voice=backend.voice_snapshot()
            if voice!=voice_sent or time.monotonic()-voice_sent_at>2:
                if voice_sent and (voice_sent['call_audio'] or voice_sent['siri']) and not (voice['call_audio'] or voice['siri']):
                    client.send(type='audio.voice.stop')
                if client.send(type='projection.voice',fields=voice):
                    voice_sent=dict(voice);voice_sent_at=time.monotonic()
            wanted=radio_ready and any(voice.values())
            if wanted and not capture_requested and time.monotonic()>=capture_retry:
                capture_requested=client.send(type='audio.capture.start',sample_rate=16000)
                capture_retry=time.monotonic()+2
            elif not wanted and capture_requested:
                if client.send(type='audio.capture.stop'):
                    capture_requested=False;backend.mic_format=None
            for result in backend.take_button_results():
                client.send(type='radio.button.result', **result)
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
                metrics=backend.metrics()
                mic={key:metrics[key] for key in ('mic_received_bytes','mic_dropped_bytes','mic_usb_bytes','mic_usb_errors')}
                if mic!=mic_metrics_sent and client.send(type='projection.microphone',fields=mic):mic_metrics_sent=mic
                client.send(
                    type="health",
                    metrics=dict(
                        metrics,
                        published_frames=published_frames,
                        slot_backpressure=slot_backpressure,
                    ),
                )
                heartbeat = time.monotonic()
            time.sleep(0.001 if active else 0.02)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            client.send(type='audio.capture.stop')
            client.send(type='audio.voice.stop')
            client.send(type='projection.voice',fields=dict(call_audio=False,siri=False,recording=False))
        except (OSError,ValueError):pass
        backend.stop()
        client.close()


if __name__ == "__main__":
    main()
