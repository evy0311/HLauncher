# Copyright (C) 2026 Evan Horsley (evy0311)
# GPL-3.0; see LICENSE and NOTICE at the project root.
"""OpenAuto projection plugin; HLauncher owns radio, HDMI, audio and touch."""
import base64
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import select
import struct
import subprocess
import threading
import time
from hlauncher_sdk import Client
from hlauncher_sdk.buttons import ANDROID, ButtonGate
from hlauncher_sdk.video.h264 import H264StreamDecoder
from hlauncher_sdk.picture import PictureSettings
from input import TouchRouter

ENGINE = Path(os.environ.get('HLAUNCHER_OPENAUTO_ENGINE','/opt/hlauncher-deps/bin/hlauncher-android-auto'))


def read_packet(stream):
    def exact(size):
        out=bytearray()
        while len(out)<size:
            part=stream.read(size-len(out))
            if not part:raise EOFError('OpenAuto engine stopped')
            out.extend(part)
        return bytes(out)
    size=struct.unpack('!I',exact(4))[0]
    if not 1<=size<=8*1024*1024+1:raise ValueError('Invalid OpenAuto packet length')
    data=exact(size)
    if data[0] not in (1,2,3):raise ValueError('Invalid OpenAuto packet type')
    return data[0],data[1:]


class Engine:
    def __init__(self, client, night_mode=False, vehicle=None, gps=None):
        self.client=client;self.lock=threading.Lock();self.lifecycle_lock=threading.Lock();self.proc=None
        self.night_mode = night_mode
        self.vehicle = vehicle
        self.gps = gps
        self.mic_requested = False
        self.call = {}
        self.call_stream = False
        self.media = {}
        self.clear_media = False
        self.mic_format = None
        self.button_gate = ButtonGate()
        self.visible=threading.Event();self.done=threading.Event()
        self.inputs=queue.Queue(128);self.router=TouchRouter();self.button_pending={}
        self.phone_connected=False
        self.frame=None;self.sequence=0;self.status='Starting Android Auto';self.home=False
        self.video_packets=0;self.decoded=0;self.audio_packets=0;self.audio_dropped=0

    def start(self):
        threading.Thread(target=self.run,daemon=True).start()

    def run(self):
        decoder=None
        try:
            if not ENGINE.is_file():
                raise RuntimeError('OpenAuto is not installed. Run scripts/install_android_auto.sh on the Pi.')
            with self.lifecycle_lock:
                if self.done.is_set():return
                from hlauncher_sdk.projection import inherited_fds
                initial_night_mode = self.night_mode
                env = dict(os.environ, HLAUNCHER_NIGHT_MODE='1' if initial_night_mode else '0')
                self.proc=subprocess.Popen([str(ENGINE)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,pass_fds=inherited_fds(),env=env)
            threading.Thread(target=self.capture_logs,daemon=True).start()
            threading.Thread(target=self.send_inputs,args=(initial_night_mode,),daemon=True).start()
            decoder=H264StreamDecoder(self.client.width,self.client.height)
            picture=PictureSettings();decoder.decoder.picture=dict(picture.values)
            picture_check=0;last_visible=False
            while not self.done.is_set():
                visible=self.visible.is_set()
                changed=False
                if time.monotonic()-picture_check>.1:
                    picture_check=time.monotonic()
                    changed=picture.refresh()
                    if changed:decoder.decoder.picture=dict(picture.values)
                if visible and (changed or not last_visible):
                    preview=decoder.decoder.redraw()
                    if preview is not None:
                        with self.lock:self.frame=preview;self.sequence+=1
                last_visible=visible
                if not select.select([self.proc.stdout],[],[],.05)[0]:continue
                kind,data=read_packet(self.proc.stdout)
                if kind==1:
                    with self.lock:self.phone_connected=True
                    self.video_packets+=1
                    pictures=decoder.feed(data,render=self.visible.is_set())
                    if pictures:
                        with self.lock:
                            self.frame=pictures[-1];self.sequence+=1;self.status='Android Auto connected'
                        self.decoded+=len(pictures)
                elif kind==2:
                    event=json.loads(data)
                    if event.get('state')=='button_result':
                        with self.lock: name=self.button_pending.pop(event.get('sequence'),None)
                        if name:self.client.send(type='radio.button.result',button=name,sequence=event.get('sequence'),result=event.get('result',''))
                    with self.lock:
                        if event.get('state') == 'microphone_request':
                            self.mic_requested = event.get('requested') is True
                        if event.get('state') == 'projection_call':
                            previous = self.call
                            self.call = event['call']
                            if self.call.get('phase') == 'active' and previous.get('phase') == 'incoming':
                                self.call['incoming'] = True
                            elif self.call.get('phase') == 'active' and previous.get('incoming') is True:
                                self.call['incoming'] = True
                        if event.get('state') == 'telephony_audio':
                            self.call_stream = event.get('active') is True
                        if event.get('state') == 'media_metadata':
                            if event.get('clear'):
                                self.media.clear()
                                self.clear_media = True
                            self.media.update(event['fields'])
                        if 'status' in event:
                            self.status=event['status']
                            if 'Connect an Android' in self.status:
                                self.frame = None
                                self.phone_connected = False
                                self.mic_requested = self.call_stream = False
                                self.call = {}
                                self.media.clear()
                                self.clear_media = True
                        if event.get('home'):self.home=True
                elif kind==3:
                    if len(data)<6:raise ValueError('Short PCM packet')
                    rate,channels,stream=struct.unpack('!IBB',data[:6])
                    if rate not in (16000,48000) or channels not in (1,2):raise ValueError('Invalid PCM format')
                    self.audio_packets+=1
                    with self.lock:
                        voice = stream == 3 or (stream == 2 and self.mic_requested)
                    if not self.client.playback(data[6:],rate,channels,stream,voice=voice):
                        self.audio_dropped+=1
        except Exception as exc:
            with self.lock:self.status=str(exc);self.frame=None;self.phone_connected=False
            print(json.dumps({'event':'openauto_error','error':str(exc)}),flush=True)
        finally:
            if decoder:decoder.close()
            self.stop()

    def capture_logs(self):
        handler=None
        try:
            logdir=Path(os.environ.get('HLAUNCHER_LOG_DIR','/var/log/hlauncher/plugins/android-auto'))
            logdir.mkdir(parents=True,exist_ok=True)
            handler=RotatingFileHandler(logdir/'engine.log',maxBytes=4*1024*1024,backupCount=2)
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        except OSError as exc:
            print(json.dumps({'event':'openauto_log_unavailable','error':str(exc)}),flush=True)
        try:
            while line:=self.proc.stderr.readline(8192):
                from hlauncher_sdk.logging import output_summary
                summary=output_summary(line)
                if handler and summary is not None:
                    record=logging.LogRecord('openauto',logging.INFO,'',0,summary,(),None)
                    handler.handle(record)
        finally:
            if handler:handler.close()

    def send_inputs(self, sent_night_mode=False):
        sent_vehicle = None
        sent_gps = None
        while not self.done.is_set():
            with self.lock:
                night_mode = self.night_mode
                vehicle = self.vehicle
                gps = self.gps
            if night_mode != sent_night_mode:
                sent_night_mode = night_mode
                item = dict(type='projection.appearance', night_mode=night_mode)
            elif vehicle != sent_vehicle:
                sent_vehicle = vehicle
                item = dict(type='projection.vehicle', **vehicle)
            elif gps != sent_gps:
                sent_gps = gps
                from hlauncher_sdk.vehicle_gps import fresh_gps_payload
                item = dict(type='projection.gps', fix=fresh_gps_payload(gps))
            else:
                try:item=self.inputs.get(timeout=.1)
                except queue.Empty:continue
            queued = item.pop('queued_at', None)
            max_age = .25 if item['type'] == 'microphone.pcm' else 1
            if queued is not None and time.monotonic() - queued > max_age:
                continue
            try:
                pending = memoryview((json.dumps(item) + '\n').encode())
                while pending:
                    written = self.proc.stdin.write(pending)
                    if not written:
                        return
                    pending = pending[written:]
                self.proc.stdin.flush()
            except (OSError, ValueError):
                return

    def touch(self,message):
        for event in self.router.feed(message):
            try:self.inputs.put_nowait(event)
            except queue.Full:
                # A session restart is safer than leaving a contact stuck down.
                self.stop();return

    def voice_snapshot(self):
        with self.lock:
            if self.done.is_set():
                return dict(call_audio=False, siri=False, recording=False)
            call = dict(self.call)
            in_call = call.get('phase') in ('active', 'held')
            call_audio = in_call or self.call_stream
            flags = dict(call_audio=call_audio, siri=self.mic_requested and not call_audio,
                         recording=self.mic_requested)
            if call:
                flags['call'] = call
            return flags

    def microphone(self, pcm):
        with self.lock:
            if not self.mic_requested or self.mic_format != (16000, 1):
                return
        if not pcm or len(pcm) > 4096 or len(pcm) % 2:
            return
        try:
            self.inputs.put_nowait(dict(type='microphone.pcm',
                pcm=base64.b64encode(pcm).decode('ascii'), queued_at=time.monotonic()))
        except queue.Full:
            pass

    def take_media(self):
        with self.lock:
            fields, clear = self.media, self.clear_media
            self.media, self.clear_media = {}, False
            return fields, clear

    def button(self, message):
        if not self.proc or self.proc.poll() is not None:
            return 'Android Auto engine unavailable'
        # HFP BVRA is a session command, not a key-down event. Some sessions
        # end on the phone without a matching BVRA=0 from the radio.
        activation = message.get('button') == 'voice_assistant' and message.get('action') == 'activate'
        code = self.button_gate.command(dict(message, action='trigger') if activation else message, ANDROID)
        if code is None: return 'Ignored release / duplicate'
        with self.lock:
            self.button_pending[message.get('sequence',0)]=message['button']
            if len(self.button_pending)>128:self.button_pending.pop(next(iter(self.button_pending)))
        try: self.inputs.put_nowait(dict(type='button', code=code, sequence=message.get('sequence',0), queued_at=time.monotonic()))
        except queue.Full:
            with self.lock:
                self.button_pending.pop(message.get('sequence', 0), None)
            return 'Android Auto input queue full'
        return 'Queued to Android Auto'

    def stop(self):
        with self.lifecycle_lock:
            if self.done.is_set():return
            self.done.set()
            proc=self.proc
        if proc and proc.poll() is None:
            proc.terminate()
            def reap():
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            threading.Thread(target=reap,daemon=True).start()


def main():
    client=Client();engine=Engine(client);active=False;started=False;last_frame=-1;last_status=None;health=0
    subscribed = capture_requested = False
    capture_retry = voice_sent_at = restart_at = 0
    voice_sent = None
    pending_media = {}
    clear_media = False
    try:
        while True:
            if not subscribed:
                subscribed = client.subscribe_buttons(ANDROID)
            while message:=client.receive(0):
                kind=message['type']
                if kind in ('host.activate','host.start'):
                    active=kind=='host.activate'
                    if active:engine.visible.set()
                    else:engine.visible.clear()
                    last_frame=-1
                    if not started or engine.done.is_set():
                        if started:
                            engine=Engine(client, night_mode=engine.night_mode, vehicle=engine.vehicle, gps=engine.gps)
                            if active:engine.visible.set()
                        engine.start();started=True
                elif kind=='host.deactivate':
                    active=False;engine.visible.clear();engine.touch({'contacts':[]})
                elif kind=='projection.appearance':
                    with engine.lock:
                        engine.night_mode = message.get('night_mode') is True
                elif kind == 'projection.vehicle':
                    with engine.lock:
                        engine.vehicle = {key: message.get(key) for key in ('speed_kph', 'parking_brake', 'speed_until', 'brake_until')}
                elif kind == 'projection.gps':
                    with engine.lock:
                        engine.gps = message.get('fix')
                elif kind == 'audio.format':
                    with engine.lock:
                        engine.mic_format = (message.get('sample_rate'), message.get('channels'))
                elif kind == 'audio.pcm':
                    engine.microphone(message['pcm'])
                elif kind in ('audio.error', 'audio.capture.stopped'):
                    capture_requested = False
                    capture_retry = time.monotonic() + 2 if kind == 'audio.error' else 0
                    with engine.lock:
                        engine.mic_format = None
                elif kind=='radio.button':
                    result=engine.button(message)
                    client.send(type='radio.button.result',button=message.get('button'),sequence=message.get('sequence'),result=result,
                                final=result != 'Queued to Android Auto')
                    print(json.dumps(dict(state='radio_button_received',result=result,**message)),flush=True)
                elif kind=='host.stop':return
                elif kind=='touch.cancel':engine.touch({'contacts':[]})
                elif kind=='touch' and active:engine.touch(message)
            now = time.monotonic()
            if started and engine.done.is_set() and now >= restart_at:
                pending_media, clear_media = {}, True
                engine = Engine(client, night_mode=engine.night_mode, vehicle=engine.vehicle, gps=engine.gps)
                if active:
                    engine.visible.set()
                last_frame = -1
                restart_at = now + 3
                engine.start()
            voice = engine.voice_snapshot()
            if voice != voice_sent or now - voice_sent_at > 2:
                if voice_sent and any(voice_sent[key] for key in ('call_audio', 'siri')) and not any(
                        voice[key] for key in ('call_audio', 'siri')):
                    client.send(type='audio.voice.stop')
                if client.send(type='projection.voice', fields=voice):
                    voice_sent, voice_sent_at = voice, now
            # BlueALSA capture is tied to the configured radio's HFP peer.
            # Its connection can be ready independently of HondaLink iAP.
            wanted = voice['recording']
            if wanted and not capture_requested and now >= capture_retry:
                capture_requested = client.send(type='audio.capture.start', sample_rate=16000)
                capture_retry = now + 2
            elif not wanted and capture_requested:
                if client.send(type='audio.capture.stop'):
                    capture_requested = False
                    capture_retry = 0
                    with engine.lock:
                        engine.mic_format = None
            fields, clear = engine.take_media()
            if clear:
                pending_media, clear_media = {}, True
            pending_media.update(fields)
            if (pending_media or clear_media) and client.now_playing(clear=clear_media, **pending_media):
                pending_media, clear_media = {}, False
            with engine.lock:
                frame,seq,status,go_home=engine.frame,engine.sequence,engine.status,engine.home
                engine.home=False
            if go_home:client.home();active=False;engine.visible.clear()
            key=(status,frame is not None)
            if key!=last_status and client.status(status,video_available=frame is not None):last_status=key
            if active and frame is not None and seq!=last_frame:
                if client.present(frame):last_frame=seq
            if time.monotonic()-health>2:
                client.send(type='health',metrics={'engine':'OpenAuto','phone_connected':engine.phone_connected,'video_packets':engine.video_packets,
                    'frames':engine.decoded,'audio_packets':engine.audio_packets,'audio_dropped':engine.audio_dropped,'visible':active})
                health=time.monotonic()
            time.sleep(.002 if active else .02)
    except (EOFError,BrokenPipeError,ConnectionResetError):pass
    finally:
        try:
            client.send(type='audio.capture.stop')
            client.send(type='audio.voice.stop')
            client.send(type='projection.voice', fields=dict(call_audio=False, siri=False, recording=False))
            client.now_playing(clear=True)
        except (OSError, ValueError):
            pass
        engine.stop()
        client.close()


if __name__=='__main__':main()
