"""Isolated radio controls: basic AVRCP target plus BlueALSA AT dispatcher.

The bluetoothd AVRCP plugin stays disabled. No browsing endpoint is advertised.
Only the configured paired radio is accepted. This process never owns PCM.
"""
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import sys
import threading
import time
from .config import RADIO_ADDRESS, RADIO_PATH, RFCOMM_PATH
from .control_protocols import AvrcpTarget, HfpProjection, hfp_request, hfp_observation, avrcp_observation
from .media import radio_metadata
from .projection_voice import read_voice

STOP=threading.Event()
OUTPUT=threading.Lock()
STATUS={}

class ControlConnections:
    """Own one control channel and invalidate in-flight connects on BlueZ loss."""
    def __init__(self):
        self.lock=threading.Lock();self.sockets={};self.epoch=0;self.active=False

    def enable(self):
        with self.lock:self.active=True

    def token(self):
        with self.lock:return self.epoch if self.active and not self.sockets else None

    def attach(self,device,sock,token=None):
        with self.lock:
            accepted=self.active and (token is None or token==self.epoch) and device not in self.sockets
            if accepted:self.sockets[device]=sock
        if not accepted:sock.close()
        return accepted

    def discard(self,device,sock):
        with self.lock:
            if self.sockets.get(device) is sock:self.sockets.pop(device,None)

    def disconnect(self,device):
        with self.lock:sock=self.sockets.pop(device,None)
        if sock:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass

    def release(self):
        with self.lock:
            self.active=False;self.epoch+=1
            sockets=list(self.sockets.values());self.sockets.clear()
        for sock in sockets:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass

def outbound_mtu(sock):
    try:
        # Linux l2cap_options begins with the negotiated outbound MTU.
        mtu=struct.unpack_from('<H',sock.getsockopt(6,1,12))[0]
        return max(48,min(512,mtu))
    except OSError:return 48  # AVRCP's minimum, safe for test/local sockets too.

def radio_ready(properties):
    """AVRCP uses the paired ACL connection, independently of hands-free state."""
    return all(bool(properties.get(key)) for key in ('Connected','Paired','Trusted','ServicesResolved'))

def emit(**item):
    with OUTPUT:
        print(json.dumps(item),flush=True)

def note(transport,status):
    if STATUS.get(transport)!=status:
        STATUS[transport]=status
        emit(transport=transport,status=status)

def metadata():
    try:
        path=Path(os.environ.get('HLAUNCHER_RUNTIME_DIR','/run/hlauncher'))/'now-playing.json'
        if path.stat().st_size>65536:return {}
        doc=json.loads(path.read_text());pid=doc.get('launcher_pid')
        if not isinstance(pid,int):return {}
        os.kill(pid,0)
        return radio_metadata(doc.get('source_plugin'))
    except (OSError,ValueError,TypeError):return {}

def serve_avrcp(sock):
    target=AvrcpTarget(outbound_mtu(sock));sock.settimeout(.5);note('avrcp','Connected')
    target.update(metadata())  # Populate the first query, before any subscription.
    last_event={};received=0;started=time.monotonic();reason='Radio closed connection'
    try:
        while not STOP.is_set():
            if select.select([sock],[],[],.2)[0]:
                raw=sock.recv(1024)
                if not raw:break
                received+=1
                emit(state='protocol_packet',source='avrcp',direction='rx',hex=raw.hex())
                reply,event=target.receive(raw)
                emit(observation=avrcp_observation(raw,reply),recognized=bool(event))
                if reply:
                    if sock.send(reply)!=len(reply):raise OSError('Short control packet write')
                    emit(state='protocol_packet',source='avrcp',direction='tx',hex=reply.hex())
                if event:
                    # Some controllers resend held-key presses. Treat a press as one action.
                    name,action=event
                    if action=='up' or time.monotonic()-last_event.get(name,-100)>2:emit(button=name,action=action,source='avrcp')
                    if action=='up':last_event.pop(name,None)
                    else:last_event[name]=time.monotonic()
            for reply in target.update(metadata()):
                if sock.send(reply)!=len(reply):raise OSError('Short control notification write')
                emit(state='protocol_packet',source='avrcp',direction='tx',hex=reply.hex())
    except (OSError,ValueError,TypeError,OverflowError) as exc:
        reason=type(exc).__name__+(f' errno={exc.errno}' if isinstance(exc,OSError) else '')
    finally:
        sock.close()
        if STOP.is_set():reason='Control worker stopped'
        emit(transport='avrcp',status=f'Disconnected / {reason} / {received} RX',
             rx_packets=received,session_seconds=round(time.monotonic()-started,3))
        STATUS['avrcp']='Disconnected'

def serve_hfp():
    import dbus
    bus=dbus.SystemBus(private=True)
    try:
        while not STOP.is_set():
            s=None;reason='Waiting for radio'
            mirror=HfpProjection()
            try:
                fd=dbus.Interface(bus.get_object('org.bluealsa',RFCOMM_PATH),'org.bluealsa.RFCOMM1').Open(timeout=2)
                s=socket.socket(fileno=fd.take());s.settimeout(.3);note('hfp','Connected')
                while not STOP.is_set():
                    if select.select([s],[],[],.2)[0]:
                        raw=s.recv(1024)
                        if not raw:break
                        responses,event=hfp_request(raw)
                        emit(observation=hfp_observation(raw),recognized=bool(event))
                        for response in responses:s.send(('\r\n'+response+'\r\n').encode())
                        if event:emit(button=event[0],action=event[1],source='hfp-command')
                    changes=mirror.update(read_voice())
                    for response in changes:
                        s.send(('\r\n'+response+'\r\n').encode())
                        emit(state='projection_hfp_tx',summary=response)
                    if changes:emit(state='projection_hfp_state',call_audio=mirror.previous[0],siri=mirror.previous[1])
            except Exception as exc:
                reason='Waiting for radio / '+type(exc).__name__
            finally:
                if s:
                    try:
                        for response in mirror.update({}):s.send(('\r\n'+response+'\r\n').encode())
                    except OSError:pass
                    s.close()
                note('hfp',reason)
            STOP.wait(.25)
    finally:bus.close()

SDP='''<?xml version="1.0" encoding="UTF-8" ?>
<record>
 <attribute id="0x0001"><sequence><uuid value="0x110c"/></sequence></attribute>
 <attribute id="0x0004"><sequence>
  <sequence><uuid value="0x0100"/><uint16 value="0x0017"/></sequence>
  <sequence><uuid value="0x0017"/><uint16 value="0x0104"/></sequence>
 </sequence></attribute>
 <attribute id="0x0005"><sequence><uuid value="0x1002"/></sequence></attribute>
 <attribute id="0x0009"><sequence><sequence><uuid value="0x110e"/><uint16 value="0x0103"/></sequence></sequence></attribute>
 <attribute id="0x0100"><text value="HLauncher controls"/></attribute>
 <attribute id="0x0311"><uint16 value="0x0001"/></attribute>
</record>'''

def main():
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus=dbus.SystemBus();loop=GLib.MainLoop();path='/org/hlauncher/avrcp'
    class Profile(dbus.service.Object):
        def __init__(self):
            super().__init__(bus,path);self.registered=False;self.connections=ControlConnections()
        @dbus.service.method('org.bluez.Profile1',in_signature='',out_signature='')
        def Release(self):
            self.registered=False
            self.connections.release()
        @dbus.service.method('org.bluez.Profile1',in_signature='oha{sv}',out_signature='')
        def NewConnection(self,device,fd,properties):
            s=socket.socket(fileno=fd.take())
            if str(device)!=RADIO_PATH:
                s.close();raise dbus.exceptions.DBusException('Wrong peer',name='org.bluez.Error.Rejected')
            if not self.attach(str(device),s):
                raise dbus.exceptions.DBusException('Control channel already active',name='org.bluez.Error.Rejected')
        def attach(self,device,s,token=None):
            if not self.connections.attach(device,s,token):return False
            def run():
                try:serve_avrcp(s)
                finally:self.connections.discard(device,s)
            threading.Thread(target=run,daemon=True).start()
            return True
        @dbus.service.method('org.bluez.Profile1',in_signature='o',out_signature='')
        def RequestDisconnection(self,device):
            self.connections.disconnect(str(device))
    profile=Profile()
    def reconnect_control():
        peer_bus=dbus.SystemBus(private=True)
        try:
            while not STOP.wait(10):
                token=profile.connections.token()
                if token is None:continue
                s=None
                try:
                    properties=dbus.Interface(peer_bus.get_object('org.bluez',RADIO_PATH),
                                              'org.freedesktop.DBus.Properties').GetAll('org.bluez.Device1',timeout=2)
                    if not radio_ready(properties):continue
                    s=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_SEQPACKET,socket.BTPROTO_L2CAP)
                    # BT_SECURITY_MEDIUM requires the existing authenticated pairing.
                    s.setsockopt(274,4,bytes([2,0]));s.settimeout(2)
                    s.connect((RADIO_ADDRESS,0x17))
                    profile.attach(RADIO_PATH,s,token)
                except (OSError,dbus.DBusException):
                    if s:s.close()
                    note('avrcp','Ready / waiting for radio control connection')
        finally:peer_bus.close()
    threading.Thread(target=reconnect_control,daemon=True).start()
    def register():
        if STOP.is_set():loop.quit();return False
        if not profile.registered:
            try:
                dbus.Interface(bus.get_object('org.bluez','/org/bluez'),'org.bluez.ProfileManager1').RegisterProfile(
                    path,'0000110c-0000-1000-8000-00805f9b34fb',
                    {'ServiceRecord':SDP,'PSM':dbus.UInt16(0x17),'Role':'server','RequireAuthentication':True,'RequireAuthorization':False},timeout=2)
                profile.registered=True;profile.connections.enable();note('avrcp','Ready / waiting for radio')
            except dbus.DBusException as exc:note('avrcp','Unavailable / '+exc.get_dbus_name())
        return True
    def owner(name,old,new):
        if name=='org.bluez' and old!=new:profile.Release()
    bus.add_signal_receiver(owner,dbus_interface='org.freedesktop.DBus',signal_name='NameOwnerChanged',arg0='org.bluez')
    signal.signal(signal.SIGTERM,lambda *_:STOP.set());signal.signal(signal.SIGINT,lambda *_:STOP.set())
    threading.Thread(target=serve_hfp,daemon=True).start()
    register();GLib.timeout_add_seconds(2,register)
    try:loop.run()
    finally:
        STOP.set();profile.Release()
        try:dbus.Interface(bus.get_object('org.bluez','/org/bluez'),'org.bluez.ProfileManager1').UnregisterProfile(path,timeout=1)
        except dbus.DBusException:pass

if __name__=='__main__':main()
