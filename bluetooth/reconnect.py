#!/usr/bin/env python3
"""Event-driven reconnect to the saved radio, with bounded failure retries."""
import logging
import time

log=logging.getLogger('civic-bt-connect')
REQUIRED={'0000110a-0000-1000-8000-00805f9b34fb',
          '0000111f-0000-1000-8000-00805f9b34fb'}


class ReconnectPolicy:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.pending=False;self.next_attempt=0;self.backoff=2;self.peer=None
    def ready(self,peer,controller,device):
        if peer!=self.peer:
            self.peer=peer;self.pending=False;self.next_attempt=0;self.backoff=2
        if device.get('Connected'):
            self.next_attempt=0;self.backoff=2
            return False
        return bool(peer and controller.get('Powered') and
            REQUIRED.issubset({str(v).lower() for v in controller.get('UUIDs',[])}) and
            device.get('Paired') and not self.pending and self.clock()>=self.next_attempt)
    def begin(self):self.pending=True
    def complete(self,success):
        self.pending=False
        self.next_attempt=self.clock()+(2 if success else self.backoff)
        self.backoff=2 if success else min(30,self.backoff*2)


def main():
    import signal
    from pathlib import Path
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib,Gio
    from hlauncher.setup_state import SetupState
    from sdk.hlauncher_sdk.logging import DebugFilter
    logging.basicConfig(level=logging.INFO,format='%(message)s');log.addFilter(DebugFilter())
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus=dbus.SystemBus();loop=GLib.MainLoop();policy=ReconnectPolicy();snapshot_pending=False
    state=SetupState();epoch=0

    def request(*unused,**kwargs):
        nonlocal snapshot_pending
        if snapshot_pending:return
        snapshot_pending=True;generation=epoch
        def failed(error):
            nonlocal snapshot_pending
            if generation!=epoch:return
            snapshot_pending=False
        def objects(items):
            nonlocal snapshot_pending
            if generation!=epoch:return
            snapshot_pending=False
            try:
                peer=state.peer
                for adapter,interfaces in items.items():
                    controller=interfaces.get('org.bluez.Adapter1')
                    if controller is not None and not controller.get('Powered'):
                        props=dbus.Interface(bus.get_object('org.bluez',str(adapter)),'org.freedesktop.DBus.Properties')
                        props.Set('org.bluez.Adapter1','Powered',dbus.Boolean(True),reply_handler=lambda:None,error_handler=lambda e:None)
                candidates=[(str(path),interfaces['org.bluez.Device1']) for path,interfaces in items.items()
                    if 'org.bluez.Device1' in interfaces and str(interfaces['org.bluez.Device1'].get('Address','')).upper()==peer]
                for path,device in candidates:
                    adapter_path=str(device.get('Adapter',path.split('/dev_')[0]))
                    controller=items.get(adapter_path,{}).get('org.bluez.Adapter1',{})
                    if not controller.get('Powered'):
                        props=dbus.Interface(bus.get_object('org.bluez',adapter_path),'org.freedesktop.DBus.Properties')
                        props.Set('org.bluez.Adapter1','Powered',dbus.Boolean(True),reply_handler=lambda:None,error_handler=lambda e:None)
                    if not policy.ready(peer,controller,device):continue
                    interface=dbus.Interface(bus.get_object('org.bluez',path),'org.bluez.Device1')
                    policy.begin();attempt_peer=peer
                    def complete(success,error=None):
                        if generation!=epoch or policy.peer!=attempt_peer:return
                        policy.complete(success)
                        if error:log.warning('Radio connection deferred: %s',str(error)[:160])
                    if not device.get('Trusted'):
                        props=dbus.Interface(bus.get_object('org.bluez',path),'org.freedesktop.DBus.Properties')
                        props.Set('org.bluez.Device1','Trusted',dbus.Boolean(True),reply_handler=lambda:None,error_handler=lambda e:None)
                    log.info('Connecting to HandsFreeLink')
                    try:
                        interface.Connect(reply_handler=lambda:complete(True),error_handler=lambda e:complete(False,e),timeout=12)
                    except dbus.DBusException as error:complete(False,error)
                    break
            except (dbus.DBusException,OSError,ValueError) as error:log.warning('Radio reconnect: %s',str(error)[:160])
        try:
            manager=dbus.Interface(bus.get_object('org.bluez','/'),'org.freedesktop.DBus.ObjectManager')
            manager.GetManagedObjects(reply_handler=objects,error_handler=failed,timeout=3)
        except dbus.DBusException as error:failed(error)

    def owner(name,old,new):
        nonlocal epoch,snapshot_pending,policy
        epoch+=1;snapshot_pending=False;policy=ReconnectPolicy()
        if new:request()
    bus.add_signal_receiver(request,signal_name='PropertiesChanged',dbus_interface='org.freedesktop.DBus.Properties',bus_name='org.bluez')
    for name in ('InterfacesAdded','InterfacesRemoved'):
        bus.add_signal_receiver(request,signal_name=name,dbus_interface='org.freedesktop.DBus.ObjectManager',bus_name='org.bluez')
    bus.add_signal_receiver(owner,signal_name='NameOwnerChanged',dbus_interface='org.freedesktop.DBus',arg0='org.bluez')
    # Pairing writes radio.json atomically; directory monitoring catches its rename.
    state.folder.mkdir(parents=True,exist_ok=True)
    monitor=Gio.File.new_for_path(str(state.folder)).monitor_directory(Gio.FileMonitorFlags.NONE,None)
    monitor.connect('changed',lambda monitor,file,other,event: request() if file.get_basename()=='radio.json' else None)
    GLib.timeout_add_seconds(1,lambda:(request(),True)[1])  # recovery/backoff watchdog; readiness uses signals
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,lambda:(loop.quit(),False)[1])
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,lambda:(loop.quit(),False)[1])
    request()
    try:loop.run()
    finally:monitor.cancel()


if __name__=='__main__':main()
