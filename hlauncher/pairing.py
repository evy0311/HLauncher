"""Early BlueZ enrollment agent. It never imports the renderer or projection apps."""
import time
from .setup_state import SetupState, address, atomic_json


def main():
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus(); state = SetupState()
    loop = GLib.MainLoop()
    manager = lambda: dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.AgentManager1')
    objects = lambda: dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager').GetManagedObjects()

    def props(path):
        return dbus.Interface(bus.get_object('org.bluez', path), 'org.freedesktop.DBus.Properties')

    class Agent(dbus.service.Object):
        @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
        def Release(self): self.registered = False

        def admit(self, device):
            values = props(device).GetAll('org.bluez.Device1')
            peer = address(values.get('Address', ''))
            manual = False
            try:
                import json
                request = json.loads((state.folder/'manual-peer.json').read_text())
                manual = request.get('address') == peer and time.time() < request.get('expires', 0)
            except (OSError, ValueError, TypeError): pass
            if not state.admit(peer, values, manual):
                raise dbus.exceptions.DBusException('Radio enrollment is closed or peer is not a candidate',
                                                    name='org.bluez.Error.Rejected')

        @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
        def RequestConfirmation(self, device, passkey): self.admit(device)

        @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
        def RequestAuthorization(self, device): self.admit(device)

        @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
        def AuthorizeService(self, device, uuid): self.admit(device)

        @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
        def RequestPinCode(self, device):
            raise dbus.exceptions.DBusException('Use the radio confirmation flow', name='org.bluez.Error.Rejected')

        @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
        def RequestPasskey(self, device):
            raise dbus.exceptions.DBusException('Use the radio confirmation flow', name='org.bluez.Error.Rejected')

        @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
        def DisplayPinCode(self, device, pin): self.admit(device)

        @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
        def DisplayPasskey(self, device, key, entered): self.admit(device)

        @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
        def Cancel(self): pass

    agent = Agent(bus, '/hlauncher/pairing')
    agent.registered = False
    last_request = None
    last_status = None

    def tick():
        nonlocal last_request
        def report(status, error=None):
            nonlocal last_status
            key=(status,error)
            if key != last_status:
                try:
                    atomic_json(state.folder/'pairing-status.json',dict(status=status,error=error))
                except OSError:
                    print('HLauncher pairing status could not be saved',flush=True)
                if error:
                    import json
                    print(json.dumps(dict(state='pairing_error',error=error)),flush=True)
                last_status=key
        try:
            if not agent.registered:
                try:
                    manager().RegisterAgent('/hlauncher/pairing', 'DisplayYesNo')
                except dbus.DBusException as exc:
                    if exc.get_dbus_name() != 'org.bluez.Error.AlreadyExists': raise
                manager().RequestDefaultAgent('/hlauncher/pairing')
                agent.registered = True
            request = state.folder/'pairing-request.json'
            version = request.stat().st_mtime_ns if request.exists() else None
            if version != last_request:
                state.deadline = state.clock()+300; last_request = version
            saved = state.peer
            entries = objects()
            for path, interfaces in entries.items():
                if 'org.bluez.Adapter1' in interfaces:
                    p = props(path)
                    p.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
                    p.Set('org.bluez.Adapter1', 'Alias', 'HLauncher')
                    p.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(state.pairing_open()))
                    p.Set('org.bluez.Adapter1', 'DiscoverableTimeout', dbus.UInt32(300))
                    p.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(state.pairing_open()))
                device = interfaces.get('org.bluez.Device1')
                if device and saved == str(device.get('Address', '')).upper():
                    props(path).Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
            # Remove only our failed enrollment, never unrelated pre-existing bonds.
            if state.candidate and state.clock() >= state.candidate_deadline and not saved:
                for path, interfaces in entries.items():
                    device = interfaces.get('org.bluez.Device1', {})
                    if str(device.get('Address', '')).upper() == state.candidate:
                        adapter = device.get('Adapter')
                        if adapter:
                            dbus.Interface(bus.get_object('org.bluez', adapter), 'org.bluez.Adapter1').RemoveDevice(path)
                state.candidate = None
                (state.folder/'pairing-candidate.json').unlink(missing_ok=True)
            report('Radio saved' if saved else 'Pairing open' if state.pairing_open() else 'Pairing window closed')
        except dbus.DBusException as exc:
            agent.registered = False
            report('Waiting for Bluetooth', exc.get_dbus_name())
        except (OSError, ValueError) as exc:
            # Do not silently accept a peer when persistence fails.
            print('HLauncher pairing state unavailable: '+type(exc).__name__,flush=True)
        return True

    def owner(name, old, new):
        agent.registered = False
    bus.add_signal_receiver(owner, dbus_interface='org.freedesktop.DBus',
                            signal_name='NameOwnerChanged', arg0='org.bluez')
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    tick(); GLib.timeout_add_seconds(2, tick)
    try: loop.run()
    finally:
        try: manager().UnregisterAgent('/hlauncher/pairing')
        except dbus.DBusException: pass


if __name__ == '__main__': main()
