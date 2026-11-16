"""UI-side controller for a separate PCM mixer process and dedicated plugin FDs."""
import array
import json
import os
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace
from .audio_settings import AudioSettings

class MixerExited(RuntimeError):
    pass


class AudioProcess:
    def __init__(self,event,test_device=None,test_capture_file=None):
        if test_capture_file is not None and test_device != 'null':
            raise ValueError('Diagnostic capture requires the null test device')
        self.event=event;self.settings=AudioSettings();self.route='hdmi';self.device='hlauncher_hdmi'
        self.condition=threading.Lock();self.send_lock=threading.Lock();self.streams={}
        self.written=self.failures=0;self.peak=0.;self.clip_samples=0;self.closed=False
        self.socket,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        self.socket.setblocking(False)
        command=[sys.executable,'-m','hlauncher.audio_process','--fd',str(child.fileno())]
        if test_device is not None:command+=['--test-device',test_device]
        if test_capture_file is not None:command+=['--test-capture-file',str(test_capture_file)]
        self.proc=subprocess.Popen(command,
            pass_fds=(child.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=None,start_new_session=True)
        child.close()
        threading.Thread(target=self.receive,daemon=True).start()

    def check(self):
        if not self.closed and self.proc.poll() is not None:
            raise MixerExited('Audio mixer exited; restarting HLauncher')

    def send(self,message,fd=None):
        raw=json.dumps(message,separators=(',',':')).encode()
        ancillary=[] if fd is None else [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))]
        with self.send_lock:
            try:self.socket.sendmsg([raw],ancillary)
            except (OSError,BlockingIOError):return False
        return True

    def open_plugin(self,manifest):
        if 'audio.playback' not in manifest.capabilities:return None
        local,plugin=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        # Dedicated bounded queue, independent of control messages and video leases.
        local.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,262144)
        if not self.send(dict(command='attach',plugin=manifest.id),local.fileno()):
            local.close();plugin.close();raise RuntimeError('Audio service unavailable')
        local.close();return plugin

    def enable(self,plugin,enabled):self.send(dict(command='enable',plugin=plugin,enabled=bool(enabled)))
    def select_source(self,plugin):self.send(dict(command='select-source',plugin=plugin))
    def stop(self,plugin):self.send(dict(command='stop',plugin=plugin))
    def stop_voice(self,plugin):self.send(dict(command='stop-voice',plugin=plugin))
    def feed(self,plugin,message):
        if not self.send(dict(command='feed',plugin=plugin,**{k:v for k,v in message.items() if k!='pcm'},pcm=message['pcm'].hex())):
            raise RuntimeError('Audio service queue full')

    def receive(self):
        import select
        while not self.closed:
            try:
                if not select.select([self.socket],[],[],.2)[0]:continue
                raw=self.socket.recv(65536)
                if not raw:break
                item=json.loads(raw)
                if item.get('state')=='audio_process_status':
                    with self.condition:
                        self.streams={k:SimpleNamespace(**v) for k,v in item['streams'].items()}
                        self.written=item['written'];self.failures=item['failures']
                        self.peak=item['peak'];self.clip_samples=item['clip_samples']
                else:self.event(**item)
            except (OSError,ValueError):break
        if not self.closed:self.event(state='audio_process_unavailable')

    def close(self):
        if self.closed:return
        self.send(dict(command='close'));self.closed=True
        try:self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=1)
        self.socket.close()


def main():
    import argparse
    import select
    import time
    from .playback import Playback
    from sdk.hlauncher_sdk import decode
    parser=argparse.ArgumentParser();parser.add_argument('--fd',type=int,required=True)
    parser.add_argument('--test-device',choices=['null'])
    parser.add_argument('--test-capture-file');args=parser.parse_args()
    if args.test_capture_file and args.test_device != 'null':parser.error('Diagnostic capture requires --test-device null')
    control=socket.socket(fileno=args.fd);control.setblocking(False)
    connections={};enabled={};last_status=0;voice_owner=None
    def event(**item):
        try:control.send(json.dumps(item).encode())
        except (OSError,BlockingIOError):pass
    if args.test_device is None and sys.platform.startswith('linux'):
        # The mixer and its player children inherit this priority. Keep normal
        # time sharing so audio cannot monopolize CPU needed for USB input.
        try:
            os.nice(-5)
        except OSError as exc:
            event(state='audio_priority_unavailable', error=str(exc))
    playback=Playback(event)
    from .voice_audio import VoiceAudio,VoicePlaybackSettings
    voice_route=VoiceAudio()
    def voice_event(**item):
        state=item.pop('state','audio_voice')
        event(state=state.replace('audio_hdmi','audio_voice'),**item)
    voice_playback=Playback(voice_event)
    voice_playback.settings=VoicePlaybackSettings()
    def stop_audio(plugin):
        for target in (playback,voice_playback):
            target.stop(plugin);target.stop(plugin+':voice')
    if args.test_device is None:
        from .audio_settings import PipeWireService
        playback.pipewire_service = PipeWireService()
    if args.test_device:playback.settings.device=lambda:args.test_device
    if args.test_device:voice_playback.settings.device=lambda:args.test_device
    playback.capture_file=args.test_capture_file
    last_route_check = 0
    last_voice_check = 0
    try:
        running=True
        while running:
            if time.monotonic()-last_voice_check>.2:
                if voice_route.refresh():
                    for target in (playback,voice_playback):
                        for plugin in {k[0] for k in target.streams if k[0].endswith(':voice')}:target.stop(plugin)
                last_voice_check=time.monotonic()
            # No graph is needed for bypass. Reconcile even without PCM, outside
            # the UI; an active mixer reaps its clients before stopping the graph.
            if playback.pipewire_service and time.monotonic()-last_route_check > 1:
                if not playback.thread or not playback.thread.is_alive():
                    playback.settings.refresh()
                    try:
                        playback.pipewire_service.set_enabled(playback.settings.values['pipewire'])
                    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                        event(state='audio_route_error', error=str(exc))
                last_route_check = time.monotonic()
            ready=select.select([control,*connections],[],[],.05)[0]
            if control in ready:
                # Drain control first so attach/enable precede audio in the same cycle.
                for _ in range(64):
                    try:raw,anc,flags,_=control.recvmsg(65536,socket.CMSG_SPACE(4))
                    except BlockingIOError:break
                    if not raw:running=False;break
                    item=json.loads(raw);cmd=item.get('command');plugin=item.get('plugin')
                    if cmd=='attach':
                        for level,kind,data in anc:
                            if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
                                descriptors=array.array('i');descriptors.frombytes(data[:len(data)//4*4])
                                for fd in descriptors:
                                    s=socket.socket(fileno=fd);s.setblocking(False);connections[s]=plugin
                        enabled[plugin]=False
                    elif cmd=='enable':
                        enabled[plugin]=item.get('enabled') is True
                        if enabled[plugin] and voice_owner is None:voice_owner=plugin
                    elif cmd=='select-source':
                        if voice_owner!=plugin:
                            for target in (playback,voice_playback):
                                for name in {k[0] for k in target.streams if k[0].endswith(':voice')}:target.stop(name)
                        voice_owner=plugin
                    elif cmd=='stop':
                        enabled[plugin]=False;stop_audio(plugin)
                        for s,name in list(connections.items()):
                            if name==plugin:s.close();connections.pop(s)
                    elif cmd=='stop-voice':
                        for target in (playback,voice_playback):target.stop(plugin+':voice')
                    elif cmd=='feed':
                        item['pcm']=bytes.fromhex(item['pcm'])
                        if item.get('type')=='audio.voice.pcm' and plugin!=voice_owner:continue
                        target=voice_playback if item.get('type')=='audio.voice.pcm' and voice_route.output=='sco' else playback
                        target.feed(plugin+':voice' if item.get('type')=='audio.voice.pcm' else plugin,item)
                    elif cmd=='close':running=False;break
                ready.remove(control)
            for s in ready:
                if s not in connections:continue
                name=connections[s]
                for _ in range(128):
                    try:raw,_,flags,_=s.recvmsg(16384)
                    except BlockingIOError:break
                    except OSError:
                        s.close();connections.pop(s);stop_audio(name);break
                    if not raw:
                        s.close();connections.pop(s);stop_audio(name);break
                    if flags&socket.MSG_TRUNC:continue
                    if enabled.get(name):
                        try:
                            if raw[:1] not in (b'P', b'C'):
                                raise ValueError('Expected binary PCM')
                            message=decode(raw)
                            if message['type'] in ('audio.playback.pcm','audio.voice.pcm'):
                                if message['type']=='audio.voice.pcm' and name!=voice_owner:continue
                                target=voice_playback if message['type']=='audio.voice.pcm' and voice_route.output=='sco' else playback
                                # Switching voice output clears queued audio in the old sink.
                                other=playback if target is voice_playback else voice_playback
                                if message['type']=='audio.voice.pcm' and name+':voice' in {k[0] for k in other.streams}:other.stop(name+':voice')
                                target.feed(name+':voice' if message['type']=='audio.voice.pcm' else name,message)
                        except (ValueError,KeyError):event(state='audio_packet_rejected',plugin=name)
            if time.monotonic()-last_status>.5:
                with playback.condition:
                    streams={str(k):dict(queued=v.queued,dropped=v.dropped,source_peak=v.source_peak,
                        source_full_scale_samples=v.source_full_scale_samples,converted_peak=v.converted_peak)
                        for k,v in playback.streams.items()}
                event(state='audio_process_status',streams=streams,written=playback.written,failures=playback.failures,
                      peak=playback.peak,clip_samples=playback.clip_samples)
                last_status=time.monotonic()
    finally:
        for s in connections:s.close()
        for name in {k[0] for k in playback.streams}:playback.stop(name)
        for name in {k[0] for k in voice_playback.streams}:voice_playback.stop(name)
        if playback.thread:playback.thread.join(timeout=3)
        if voice_playback.thread:voice_playback.thread.join(timeout=3)
        if playback.pipewire_service:
            try:playback.pipewire_service.set_enabled(False)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                event(state='audio_route_error', error=str(exc))
        control.close()

if __name__=='__main__':main()
