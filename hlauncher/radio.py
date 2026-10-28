"""HondaLink Bluetooth profile owner. Protocol payload handling matches V42."""


def main():
    import argparse, datetime, json, os, pathlib, socket
    from hlauncher.config import LOG_DIR, RADIO_PATH, RADIO_ADDRESS
    from hlauncher.protocol.session import StartProbe
    from hlauncher.touch import decode_touch
    from hlauncher.launcher import Launcher
    import dbus, dbus.service, dbus.mainloop.glib
    from gi.repository import GLib

    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=900)
    a = p.parse_args()
    if RADIO_ADDRESS == "00:00:00:00:00:00":
        raise SystemExit(
            "Set HLAUNCHER_RADIO_ADDRESS to the paired HandsFreeLink address"
        )
    root = LOG_DIR
    root.mkdir(parents=True, exist_ok=True)
    f = (
        root
        / ("listener-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl")
    ).open("x", buffering=1)
    import threading

    log_lock = threading.Lock()

    def event(**v):
        with log_lock:
            if f.closed:
                return
            v["wall"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            s = json.dumps(v)
            print(s, flush=True)
            f.write(s + "\n")

    launcher = Launcher(event)
    try:
        launcher.home()
        event(state="hdmi_launcher_ready")
    except Exception:
        launcher.close()
        raise
    launch_app = launcher.launch
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()
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
            self.sockets = {}
            self.watches = {}
            self.parsers = {}
            self.tx = {}
            self.txw = {}

        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            self.close_all()
            event(state="released", uuid=self.uuid)

        @dbus.service.method(
            "org.bluez.Profile1", in_signature="oha{sv}", out_signature=""
        )
        def NewConnection(self, device, fd, props):
            if str(device) in self.sockets:
                self.RequestDisconnection(device)
            n = fd.take()
            if str(device) != RADIO_PATH:
                os.close(n)
                raise dbus.exceptions.DBusException(
                    "Peer not permitted", name="org.bluez.Error.Rejected"
                )
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
                            event(uuid=self.uuid, **e)
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
                if self.uuid.endswith("cafe"):
                    launcher.session_changed(connected=False, authenticated=False)

        def close_all(self):
            for device in list(self.sockets):
                self.RequestDisconnection(device)

    def draw_tick():
        try:
            launcher.tick()
        except Exception as exc:
            event(state="touch_overlay_error", error=str(exc))
        return True

    GLib.timeout_add(16, draw_tick)
    manager = dbus.Interface(
        bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1"
    )
    profiles = []
    try:
        for i, (uuid, channel) in enumerate(
            [
                ("00001101-0000-1000-8000-00805f9b34fb", 10),
                ("00000000-deca-fade-deca-deafdecacafe", 11),
            ]
        ):
            path = "/hlauncher/profile" + str(i)
            profile = Profile(path, uuid)
            manager.RegisterProfile(
                path,
                uuid,
                {
                    "Name": dbus.String("HLauncher"),
                    "Role": dbus.String("server"),
                    "Channel": dbus.UInt16(channel),
                    "RequireAuthentication": dbus.Boolean(True),
                    "RequireAuthorization": dbus.Boolean(False),
                    "AutoConnect": dbus.Boolean(False),
                },
            )
            profiles.append((path, profile))
            event(state="registered", uuid=uuid, channel=channel)
        if a.seconds > 0:
            GLib.timeout_add_seconds(a.seconds, lambda: (loop.quit(), False)[1])
        loop.run()
    finally:
        for path, profile in profiles:
            profile.close_all()
            try:
                manager.UnregisterProfile(path)
            except dbus.DBusException:
                pass
        launcher.close()
        f.close()
