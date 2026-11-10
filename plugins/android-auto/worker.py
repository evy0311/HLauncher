# Copyright (C) 2026 Evan Horsley (evy0311)
# GPL-3.0; see LICENSE and NOTICE at the project root.
"""OpenAuto projection plugin; HLauncher owns radio, HDMI, audio and touch."""
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
    def __init__(self,client):
        self.client=client;self.lock=threading.Lock();self.lifecycle_lock=threading.Lock();self.proc=None
        self.visible=threading.Event();self.done=threading.Event()
        self.inputs=queue.Queue(128);self.router=TouchRouter();self.button_pending={}
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
                self.proc=subprocess.Popen([str(ENGINE)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,pass_fds=inherited_fds())
            threading.Thread(target=self.capture_logs,daemon=True).start()
            threading.Thread(target=self.send_inputs,daemon=True).start()
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
                        if 'status' in event:
                            self.status=event['status']
                            if 'Connect an Android' in self.status:self.frame=None
                        if event.get('home'):self.home=True
                elif kind==3:
                    if len(data)<6:raise ValueError('Short PCM packet')
                    rate,channels,stream=struct.unpack('!IBB',data[:6])
                    if rate not in (16000,48000) or channels not in (1,2):raise ValueError('Invalid PCM format')
                    self.audio_packets+=1
                    if not self.client.playback(data[6:],rate,channels,stream):self.audio_dropped+=1
        except Exception as exc:
            with self.lock:self.status=str(exc);self.frame=None
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

    def send_inputs(self):
        while not self.done.is_set():
            try:item=self.inputs.get(timeout=.1)
            except queue.Empty:continue
            queued=item.pop('queued_at',None)
            if queued is not None and time.monotonic()-queued > 1: continue
            try:
                self.proc.stdin.write((json.dumps(item)+'\n').encode());self.proc.stdin.flush()
            except (OSError,ValueError):return

    def touch(self,message):
        for event in self.router.feed(message):
            try:self.inputs.put_nowait(event)
            except queue.Full:
                # A session restart is safer than leaving a contact stuck down.
                self.stop();return

    def button(self, message):
        from hlauncher_sdk.buttons import ButtonGate, ANDROID
        if not hasattr(self, 'button_gate'): self.button_gate=ButtonGate()
        code=self.button_gate.command(message, ANDROID)
        if code is None: return 'Ignored release / duplicate'
        if not self.proc or self.proc.poll() is not None: return 'Android Auto engine unavailable'
        with self.lock:
            self.button_pending[message.get('sequence',0)]=message['button']
            if len(self.button_pending)>128:self.button_pending.pop(next(iter(self.button_pending)))
        try: self.inputs.put_nowait(dict(type='button', code=code, sequence=message.get('sequence',0), queued_at=time.monotonic()))
        except queue.Full: return 'Android Auto input queue full'
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
    try:
        while True:
            while message:=client.receive(0):
                kind=message['type']
                if kind in ('host.activate','host.start'):
                    active=kind=='host.activate'
                    if active:engine.visible.set()
                    else:engine.visible.clear()
                    last_frame=-1
                    if not started or engine.done.is_set():
                        if started:
                            engine=Engine(client)
                            if active:engine.visible.set()
                        engine.start();started=True
                elif kind=='host.deactivate':
                    active=False;engine.visible.clear();engine.touch({'contacts':[]})
                elif kind=='radio.button':
                    result=engine.button(message)
                    client.send(type='radio.button.result',button=message.get('button'),sequence=message.get('sequence'),result=result)
                    print(json.dumps(dict(state='radio_button_received',result=result,**message)),flush=True)
                elif kind=='host.stop':return
                elif kind=='touch.cancel':engine.touch({'contacts':[]})
                elif kind=='touch' and active:engine.touch(message)
            with engine.lock:
                frame,seq,status,go_home=engine.frame,engine.sequence,engine.status,engine.home
                engine.home=False
            if go_home:client.home();active=False;engine.visible.clear()
            key=(status,frame is not None)
            if key!=last_status and client.status(status,video_available=frame is not None):last_status=key
            if active and frame is not None and seq!=last_frame:
                if client.present(frame):last_frame=seq
            if time.monotonic()-health>2:
                client.send(type='health',metrics={'engine':'OpenAuto','video_packets':engine.video_packets,
                    'frames':engine.decoded,'audio_packets':engine.audio_packets,'audio_dropped':engine.audio_dropped,'visible':active})
                health=time.monotonic()
            time.sleep(.002 if active else .02)
    except (EOFError,BrokenPipeError,ConnectionResetError):pass
    finally:engine.stop();client.close()


if __name__=='__main__':main()
