"""HondaLink Bluetooth profile owner. Protocol payload handling matches V42."""


class ProfileRegistry:
    """Re-register local profiles after bluetoothd releases them or changes owner."""
    def __init__(self, entries, manager, event):
        self.entries, self.manager, self.event = entries, manager, event
        self.errors = {}

    def lost(self):
        for path, profile, options in self.entries:
            profile.registered = False
            profile.close_all()

    def tick(self):
        for path, profile, options in self.entries:
            if profile.registered: continue
            try:
                self.manager().RegisterProfile(path, profile.uuid, options)
                profile.registered = True
                self.errors.pop(path, None)
                self.event(state='registered', uuid=profile.uuid, channel=int(options['Channel']))
            except Exception as exc:
                error=str(exc)
                if self.errors.get(path)!=error:
                    self.event(state='profile_registration_waiting',uuid=profile.uuid,error=error)
                    self.errors[path]=error
        return True


def main():
    import argparse, os, pathlib, socket
    from hlauncher.config import RADIO_PATH, RADIO_ADDRESS
    from hlauncher.protocol_diagnostics import ProtocolDiagnostics
    from hlauncher.protocol.session import StartProbe
    from hlauncher.touch import decode_touch
    from hlauncher.bootstrap import BootstrapLauncher
    from hlauncher.setup_state import SetupState, atomic_json, address
    from hlauncher.event_log import EventLog
    import dbus, dbus.service, dbus.mainloop.glib
    from gi.repository import GLib

    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=900)
    a = p.parse_args()
    protocols = ProtocolDiagnostics()
    event = EventLog(protocols)
    state = SetupState()
    launcher = BootstrapLauncher(event, protocols, state)
    launch_app = launcher.launch
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()
    if not state.path.exists() and RADIO_ADDRESS != '00:00:00:00:00:00':
        try:
            values = dbus.Interface(bus.get_object('org.bluez', RADIO_PATH),
                                    'org.freedesktop.DBus.Properties').GetAll('org.bluez.Device1')
            if values.get('Paired'):
                atomic_json(state.path, {'address': address(RADIO_ADDRESS), 'verified': True})
        except (ValueError, dbus.DBusException):
            pass
    import signal

    # Normal service stops run the existing cleanup and restore console mode.
    GLib.unix_signal_add(
        GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (loop.quit(), False)[1]
    )
    GLib.unix_signal_add(
        GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (loop.quit(), False)[1]
    )

    class Profile(dbus.service.Object):
        def __init__(self, path, uuid):
            super().__init__(bus, path)
            self.uuid = uuid
            self.registered = False
            self.sockets = {}
            self.watches = {}
            self.parsers = {}
            self.tx = {}
            self.txw = {}

        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            self.registered = False
            self.close_all()
            event(state="released", uuid=self.uuid)

        @dbus.service.method(
            "org.bluez.Profile1", in_signature="oha{sv}", out_signature=""
        )
        def NewConnection(self, device, fd, props):
            if str(device) in self.sockets:
                self.RequestDisconnection(device)
            n = fd.take()
            try:
                values = dbus.Interface(bus.get_object('org.bluez', device),
                                        'org.freedesktop.DBus.Properties').GetAll('org.bluez.Device1')
                peer = address(values.get('Address',''))
                permitted = bool(values.get('Paired')) and state.allowed(peer)
            except (ValueError, dbus.DBusException):
                permitted = False
            if not permitted:
                os.close(n)
                raise dbus.exceptions.DBusException(
                    "Peer not permitted", name="org.bluez.Error.Rejected"
                )
            launcher.set_peer(peer)
            s = socket.socket(fileno=n)
            s.setblocking(False)
            self.sockets[str(device)] = s
            if self.uuid.endswith("cafe"):
                launcher.session_changed(connected=True, authenticated=False)
            self.parsers[str(device)] = StartProbe(launch_app=launch_app)
            self.watches[str(device)] = GLib.io_add_watch(
                s.fileno(),
                GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                self.read,
                str(device),
            )
            event(state="connected", uuid=self.uuid, device=str(device))

        def read(self, fd, cond, device):
            try:
                b = self.sockets[device].recv(4096)
                if b:
                    event(state="rx", uuid=self.uuid, hex=b.hex())
                    if self.uuid.endswith("cafe"):
                        events, replies = self.parsers[device].feed(b)
                        for e in events:
                            if (e.get('state') == 'honda_authentication_result_received'
                                    and e.get('result') == 1 and launcher.peer_address):
                                state.verify(launcher.peer_address)
                            event(uuid=self.uuid, **e)
                            launcher.inputs.receive_iap_remote(e)
                            if e.get('state') == 'honda_frame' and e.get('message') != 0x43:
                                payload=e.get('payload','')
                                launcher.inputs.observe('hondalink',f"Message 0x{e['message']:02x} / {len(payload)//2} bytes",
                                                        bytes=len(payload)//2)
                            if e.get('state') == 'honda_steering_mode':
                                launcher.inputs.steering_mode=e['mode']
                                launcher.inputs.observe('hondalink',f"Steering mode {e['mode']}",recognized=True)
                            if e.get("state") == "iap_accessory_key_proof":
                                launcher.session_changed(
                                    authenticated=bool(e.get("verified"))
                                )
                            if e.get("state") == "honda_touch_candidate":
                                try:
                                    touch = decode_touch(bytes.fromhex(e["payload"]))
                                    event(
                                        state="honda_touch_decoded",
                                        session=e["session"],
                                        **touch
                                    )
                                    try:
                                        launcher.update(touch)
                                    except Exception as exc:
                                        event(
                                            state="touch_overlay_error", error=str(exc)
                                        )
                                except ValueError as exc:
                                    event(
                                        state="honda_touch_invalid",
                                        error=str(exc),
                                        payload=e["payload"],
                                    )
                        for reply in replies:
                            event(state='protocol_tx',uuid=self.uuid,hex=reply.hex())
                            self.tx.setdefault(device, bytearray()).extend(reply)
                        if self.tx.get(device) and device not in self.txw:
                            self.txw[device] = GLib.io_add_watch(
                                fd,
                                GLib.IO_OUT | GLib.IO_HUP | GLib.IO_ERR,
                                self.write,
                                device,
                            )
                    return True
            except BlockingIOError:
                return True
            except OSError as e:
                event(state="socket_error", uuid=self.uuid, error=str(e))
            self.sockets.pop(device).close()
            if device in self.txw:
                GLib.source_remove(self.txw.pop(device))
            self.tx.pop(device, None)
            self.parsers.pop(device, None)
            if self.uuid.endswith("cafe"):
                launcher.session_changed(connected=False, authenticated=False)
            self.watches.pop(device, None)
            event(state="closed", uuid=self.uuid)
            return False

        def write(self, fd, cond, device):
            try:
                if cond & (GLib.IO_HUP | GLib.IO_ERR):
                    raise OSError("write channel closed")
                pending = self.tx[device]
                n = self.sockets[device].send(pending)
                del pending[:n]
                event(state="tx_bytes", uuid=self.uuid, count=n)
                if pending:
                    return True
            except BlockingIOError:
                return True
            except (OSError, KeyError) as e:
                event(state="tx_error", error=str(e))
            self.txw.pop(device, None)
            return False

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, device):
            key = str(device)
            self.tx.pop(key, None)
            self.parsers.pop(key, None)
            if key in self.txw:
                GLib.source_remove(self.txw.pop(key))
            if key in self.watches:
                GLib.source_remove(self.watches.pop(key))
            if key in self.sockets:
                self.sockets.pop(key).close()
                event(state='closed',uuid=self.uuid,device=key)
                if self.uuid.endswith("cafe"):
                    launcher.session_changed(connected=False, authenticated=False)

        def close_all(self):
            for device in list(self.sockets):
                self.RequestDisconnection(device)

    def draw_tick():
        try:
            event.refresh()
            launcher.tick()
        except Exception as exc:
            event(state="touch_overlay_error", error=str(exc))
        return True

    def protocol_tick():
        import time
        connection=dict(connected=bool(launcher.session.get('connected')),
                        authenticated=bool(launcher.session.get('authenticated')),
                        hondalink_ready=any(parser.vehicle_auth_sessions for _, profile in profiles
                            for parser in profile.parsers.values()), monotonic=time.monotonic())
        try: atomic_json(pathlib.Path('/run/hlauncher/connection.json'),connection)
        except OSError as exc:event(state='connection_status_error',error=str(exc))
        from hlauncher import __version__
        try: atomic_json(pathlib.Path('/run/hlauncher/update-health.json'),
                         dict(version=__version__,monotonic=time.monotonic(),
                              profiles_ready=all(profile.registered for _,profile in profiles)))
        except OSError as exc:event(state='update_health_error',error=str(exc))
        for _, profile in profiles:
            if profile.uuid.endswith('cafe'):
                for parser in list(profile.parsers.values()):
                    for item in parser.tick():
                        event(uuid=profile.uuid, **item)
        return True

    # Availability sampling is faster than scanout; KMS still paces actual frames.
    GLib.timeout_add(4, draw_tick)
    profiles = []
    entries = []
    def manager():
        # A fresh proxy resolves the new unique bus owner after a daemon restart.
        return dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
    registry = ProfileRegistry(entries, manager, event)
    def bluetooth_owner(name, old, new):
        if old != new:
            registry.lost()
            if new: GLib.idle_add(lambda: (registry.tick(), False)[1])
    bus.add_signal_receiver(bluetooth_owner, dbus_interface='org.freedesktop.DBus',
                            signal_name='NameOwnerChanged', arg0='org.bluez')
    try:
        for i, (uuid, channel) in enumerate([
            ("00001101-0000-1000-8000-00805f9b34fb", 10),
            ("00000000-deca-fade-deca-deafdecacafe", 11),
        ]):
            path = "/hlauncher/profile" + str(i)
            profile = Profile(path, uuid)
            profiles.append((path, profile))
            entries.append((path, profile, {
                "Name": dbus.String("HLauncher"), "Role": dbus.String("server"),
                "Channel": dbus.UInt16(channel), "RequireAuthentication": dbus.Boolean(True),
                "RequireAuthorization": dbus.Boolean(False), "AutoConnect": dbus.Boolean(False),
            }))
        registry.tick()
        event(state='bluetooth_profiles_ready')
        GLib.idle_add(launcher.show_pairing)
        GLib.timeout_add_seconds(2, registry.tick)
        GLib.timeout_add_seconds(1, protocol_tick)
        if a.seconds > 0:
            GLib.timeout_add_seconds(a.seconds, lambda: (loop.quit(), False)[1])
        loop.run()
    finally:
        for path, profile in profiles:
            profile.close_all()
            try:
                manager().UnregisterProfile(path)
            except dbus.DBusException:
                pass
        launcher.close()
        event.close()
