"""iAP identification and HondaLink application-session state machine."""

from .frames import frame as honda_frame, Frames as HondaFrames
import subprocess
import time
from pathlib import Path
from hlauncher.config import serial_number
from .auth import AccessoryProof
from .vehicle_can import VehicleSubscription, HONDALINK, GENERAL, SCOPES

DISPLAY_URL = b'com.honda.hondalink.connect://'


def packet(payload):
    n = len(payload)
    head = bytes([n]) if 0 < n < 256 else b"\0" + n.to_bytes(2, "big")
    return b"\x55" + head + payload + bytes([(-sum(head + payload)) & 255])


def pi_honda_device_info():
    # SDK uses six Wi-Fi MAC bytes, and derives its CAN key from these exact
    # bytes. Prefer the Pi's real interface address; serial is a stable fallback.
    for interface in ('wlan0', 'eth0'):
        try:
            raw = bytes.fromhex(Path('/sys/class/net', interface, 'address').read_text().strip().replace(':',''))
            if len(raw) == 6 and any(raw) and not raw[0] & 1:return raw
        except (OSError, ValueError):pass
    return serial_number()


def pi_honda_identity(device_info=None):
    manufacturer = b"Raspberry Pi"
    model = b"Pi 4 Model B"
    serial = pi_honda_device_info() if device_info is None else device_info
    return (
        b"\0"
        + bytes([len(manufacturer)])
        + manufacturer
        + bytes([len(model)])
        + model
        + (0x060C).to_bytes(2, "big")
        + bytes([len(serial)])
        + serial
        + (0).to_bytes(2, "big")  # native applicationVersion
        + (0xFF).to_bytes(4, "big")  # native applicationId
    )


class StartProbe:
    def __init__(self, launch_app=None, vehicle_scope=None, auth_executor=None):
        self.launch_app = launch_app
        self.vehicle_scope = vehicle_scope or (lambda:'diagnostics')
        self.active_app = None
        self.buffer = bytearray()
        self.tokens = []
        self.identification = False
        self.proof = AccessoryProof()
        self.auth_executor = auth_executor
        self.pending_auth = None
        self.auth_transaction = None
        self.authenticated = False
        self.ui_mode = 0
        self.session_pending = {}
        self.session_queue = []
        self.sessions = {}
        self.session_start_requested = False
        self.honda_decoders = {}
        self.honda_stage = {}
        self.phone_transaction = 0x8200
        self.honda_name_retry = set()
        self.start_ack_pending = {}
        self.app_started_sessions = set()
        self.app_metadata_sent = {}
        self.metadata_transition_replied = set()
        self.startup_ready = False
        self.ready_announced = set()
        self.app_restart_needed = False
        self.simple_remote_state = 0
        self.vehicle_subscription = VehicleSubscription()
        self.vehicle_auth_sessions = {}
        self.vehicle_session = None
        self.vehicle_identities = {}
        self.display_sequence = 0
        self.display_test = None

    def feed(self, data):
        self.buffer.extend(data)
        events = []
        replies = []
        while self.buffer:
            try:
                i = self.buffer.index(0x55)
            except ValueError:
                self.buffer.clear()
                break
            del self.buffer[:i]
            if len(self.buffer) < 2:
                break
            if self.buffer[1]:
                off = 2
                n = self.buffer[1]
            else:
                if len(self.buffer) < 4:
                    break
                off = 4
                n = int.from_bytes(self.buffer[2:4], "big")
            if n < 2:
                del self.buffer[0]
                continue
            end = off + n + 1
            if len(self.buffer) < end:
                break
            raw = bytes(self.buffer[:end])
            if sum(raw[1:]) & 255:
                events.append({"state": "iap_bad_checksum", "hex": raw.hex()})
                del self.buffer[0]
                continue
            del self.buffer[:end]
            p = raw[off:-1]
            events.append(
                {
                    "state": "iap_packet",
                    "lingo": p[0],
                    "command": (
                        int.from_bytes(p[1:3], "big")
                        if p[0] == 4 and len(p) >= 3
                        else p[1]
                    ),
                    "payload": p.hex(),
                }
            )
            if p[:2] == b'\x02\x00':
                # Honda wraps Simple Remote ContextButtonStatus in the same
                # transaction-bearing iAP format as its other commands.
                # State bytes are separate 8-bit banks, lowest bank first.
                if not self.authenticated or not 5 <= len(p) <= 8:
                    events.append(dict(state='iap_remote_buttons_rejected', bytes=len(p),
                                       reason='Unauthenticated' if not self.authenticated else 'Invalid length'))
                else:
                    mask = int.from_bytes(p[4:], 'little')
                    previous = self.simple_remote_state
                    self.simple_remote_state = mask
                    controls = ((0x01, 'play_pause'), (0x08, 'next'), (0x10, 'previous'),
                                (0x100, 'play'), (0x200, 'pause'))
                    supported = sum(bit for bit, _ in controls)
                    events.append(dict(state='iap_remote_buttons', transaction=int.from_bytes(p[2:4], 'big'),
                                       mask=mask, unsupported_mask=mask & ~supported, bytes=len(p)))
                    for bit, name in controls:
                        if (previous ^ mask) & bit:
                            events.append(dict(state='iap_remote_button', button=name,
                                               action='down' if mask & bit else 'up'))
                    # ContextButtonStatus has no iAP reply. Do not fabricate an ACK.
            elif len(p) == 4 and p[:2] == b"\0\x38":
                if self.display_test:
                    self.display_result(events, 'Session reset')
                    self.display_test = None
                self.vehicle_subscription.clear()
                self.vehicle_auth_sessions.clear()
                self.vehicle_identities.clear()
                self.vehicle_session = None
                self.simple_remote_state = 0
                events.append(dict(state='iap_remote_reset'))
                self.tokens = []
                self.identification = False
                self.cancel_auth()
                self.proof = AccessoryProof()
                self.auth_transaction = None
                self.authenticated = False
                self.ui_mode = 0
                self.session_pending = {}
                self.session_queue = []
                self.sessions = {}
                self.session_start_requested = False
                self.honda_decoders = {}
                self.honda_stage = {}
                self.phone_transaction = 0x8200
                self.honda_name_retry = set()
                self.start_ack_pending = {}
                self.app_started_sessions = set()
                self.app_metadata_sent = {}
                self.metadata_transition_replied = set()
                self.startup_ready = False
                self.ready_announced = set()
                self.app_restart_needed = False
                self.active_app = None
                reply = packet(b"\0\x02" + p[2:4] + b"\0\x38")
                replies.append(reply)
                events.append(
                    {
                        "state": "iap_startidps_ack_queued",
                        "transaction": int.from_bytes(p[2:4], "big"),
                        "hex": reply.hex(),
                    }
                )
            elif len(p) == 4 and p[:2] == b"\0\x11":
                reply = packet(b"\0\x12" + p[2:4] + (4096).to_bytes(2, "big"))
                replies.append(reply)
                events.append(
                    {
                        "state": "iap_max_payload_reply_queued",
                        "maximum": 4096,
                        "hex": reply.hex(),
                    }
                )
            elif len(p) == 5 and p[:2] == b"\0\x4b":
                # Experimental app-communication capability, derived from the radio FID builder.
                # NEvent D0774 loads general options at handler+10; CFFD8
                # requires low-word bit24 before D0C40 permits RequestApplicationLaunch.
                options = 0x01002000 if p[4] == 0 else 0
                reply = packet(b"\0\x4c" + p[2:5] + options.to_bytes(8, "big"))
                replies.append(reply)
                events.append(
                    {
                        "state": "iap_options_reply_queued",
                        "requested_lingo": p[4],
                        "options": f"{options:016x}",
                        "hex": reply.hex(),
                    }
                )
            elif len(p) >= 5 and p[:2] == b"\0\x39":
                try:
                    tokens = parse_tokens(p[4:])
                    self.tokens.extend(tokens)
                    for token in tokens:
                        if token[:2] == b"\0\4" and len(token) > 3:
                            events.append(
                                {
                                    "state": "iap_ea_protocol",
                                    "index": token[2],
                                    "name": token[3:]
                                    .split(b"\0")[0]
                                    .decode("utf-8", "replace"),
                                }
                            )
                        if token[:2] == b"\0\5":
                            events.append(
                                {"state": "iap_bundle_seed", "value": token[2:].hex()}
                            )
                    ack = bytearray([len(tokens)])
                    for t in tokens:
                        tid = t[:2]
                        supported = tid in [
                            b"\0\0",
                            b"\0\1",
                            b"\0\2",
                            b"\0\3",
                            b"\0\4",
                            b"\0\5",
                            b"\0\7",
                            b"\0\x08",
                            b"\1\0",
                        ]
                        status = 0 if supported else 1
                        a = tid + bytes([status])
                        if tid in [b"\0\2", b"\0\3", b"\0\4"]:
                            if len(t) < 3:
                                raise ValueError("missing token discriminator")
                            a += t[2:3]
                        ack += bytes([len(a)]) + a
                    reply = packet(b"\0\x3a" + p[2:4] + ack)
                    replies.append(reply)
                    events.append(
                        {
                            "state": "iap_fid_tokens",
                            "tokens": [t.hex() for t in tokens],
                            "ack": reply.hex(),
                        }
                    )
                except ValueError as e:
                    events.append({"state": "iap_invalid_tokens", "error": str(e)})
            elif len(p) == 5 and p[:2] == b"\0\x3b":
                status = {0: 0, 1: 4, 2: 6}.get(p[4])
                events.append({"state": "iap_endidps", "accessory_status": p[4]})
                if status is not None:
                    reply = packet(b"\0\x3c" + p[2:4] + bytes([status]))
                    replies.append(reply)
                    if p[4] == 0:
                        self.identification = True
                        # Request the radio's authentication information; record response only.
                        replies.append(packet(bytes.fromhex("00148000")))
                        events.append(
                            {"state": "iap_auth_info_requested", "transaction": 32768}
                        )
            elif (
                len(p) >= 8
                and p[:2] == b"\0\x15"
                and p[2:4] == bytes.fromhex("8000")
                and self.identification
            ):
                if self.pending_auth is not None:
                    continue
                major, minor, section, maximum = p[4:8]
                try:
                    if major != 2:
                        raise ValueError("unsupported authentication version")
                    complete = self.proof.add_section(section, maximum, p[8:])
                    events.append(
                        {
                            "state": "iap_certificate_section",
                            "section": section,
                            "maximum": maximum,
                            "bytes": len(p) - 8,
                        }
                    )
                    if complete:
                        self.run_auth('certificate', p[2:4], b'', events, replies)
                    else:
                        replies.append(packet(b"\0\x02" + p[2:4] + b"\0\x15"))
                except (
                    ValueError,
                    OSError,
                    TimeoutError,
                    subprocess.TimeoutExpired,
                ) as e:
                    events.append({"state": "iap_certificate_error", "error": str(e)})
            elif (
                len(p) > 4
                and p[:2] == b"\0\x18"
                and self.auth_transaction is not None
                and p[2:4] == self.auth_transaction
            ):
                if self.pending_auth is None:
                    self.run_auth('signature', p[2:4], p[4:], events, replies)
            elif p[:2] == b"\0\x64" and self.authenticated:
                # iAP RequestApplicationLaunch: three reserved bytes followed by an AppID.
                app_id = None
                status = 4
                error = None
                if len(p) >= 9 and p[-1] == 0 and b"\0" not in p[7:-1]:
                    try:
                        app_id = p[7:-1].decode("ascii")
                    except UnicodeDecodeError:
                        pass
                    if app_id is not None:
                        status = 2
                        if (
                            app_id
                            in (
                                "com.honda.hondalink.launcher",
                                "com.honda.hondalink.connect",
                            )
                            and self.launch_app is not None
                        ):
                            try:
                                if self.launch_app(app_id):
                                    status = 0
                                    self.active_app = app_id
                            except Exception as exc:
                                error = str(exc)
                replies.append(packet(b"\0\x02" + p[2:4] + bytes([status, 0x64])))
                events.append(
                    {
                        "state": "iap_application_launch_result",
                        "app_id": app_id,
                        "reserved": p[4:7].hex(),
                        "status": status,
                        "error": error,
                        "displayed": status == 0,
                    }
                )
                if status == 0 and self.startup_ready:
                    self.start_app_sessions(events, replies)
            elif p[:2] == b"\0\x65" and len(p) == 4 and self.authenticated:
                # Focus identity follows an actual successful local launch only.
                replies.append(
                    packet(
                        b"\0\x66"
                        + p[2:4]
                        + (self.active_app or "").encode("ascii")
                        + b"\0"
                    )
                )
                events.append(
                    {"state": "iap_focus_app_reply", "app_id": self.active_app}
                )
            elif len(p) == 4 and p[:2] == b"\0\x4f" and self.authenticated:
                reply = packet(b"\0\x51" + p[2:4] + bytes(8))
                replies.append(reply)
                events.append(
                    {
                        "state": "iap_supported_events_reply",
                        "mask": "0000000000000000",
                        "hex": reply.hex(),
                    }
                )
            elif len(p) == 4 and p[:2] == b"\0\x4d" and self.authenticated:
                replies.append(packet(b"\0\x4e" + p[2:4] + bytes(8)))
                events.append(
                    {"state": "iap_enabled_events_reply", "mask": "0000000000000000"}
                )
            elif len(p) == 12 and p[:2] == b"\0\x49" and self.authenticated:
                mask = int.from_bytes(p[4:], "big")
                # No asynchronous notification types implemented: accept only the empty mask.
                status = 0 if mask == 0 else 4
                replies.append(packet(b"\0\x02" + p[2:4] + bytes([status, 0x49])))
                events.append(
                    {
                        "state": "iap_set_events_reply",
                        "requested": hex(mask),
                        "status": status,
                    }
                )
            elif len(p) == 4 and p[:2] == b"\0\x24" and self.authenticated:
                replies.append(packet(b"\0\x25" + p[2:4] + bytes(8)))
                events.append(
                    {"state": "iap_legacy_options_reply", "options": "0000000000000000"}
                )
            elif len(p) == 4 and p[:2] in [b"\0\x03", b"\0\x35"] and self.authenticated:
                command = 4 if p[1] == 3 else 0x36
                replies.append(
                    packet(bytes([0, command]) + p[2:4] + bytes([self.ui_mode]))
                )
            elif p[:2] in [b"\0\x05", b"\0\x06", b"\0\x37"] and self.authenticated:
                if (p[1] in [5, 6] and len(p) == 4) or (
                    p[1] == 0x37 and len(p) == 5 and p[4] in [0, 1]
                ):
                    self.ui_mode = (1 if p[1] == 5 else 0) if p[1] != 0x37 else p[4]
                    replies.append(packet(b"\0\x02" + p[2:4] + bytes([0, p[1]])))
                    events.append({"state": "iap_ui_mode", "mode": self.ui_mode})
            elif (
                p[:3] == bytes.fromhex("04002c") and len(p) == 5 and self.authenticated
            ):
                replies.append(packet(bytes.fromhex("04002d") + p[3:5] + b"\0"))
                events.append({"state": "iap_shuffle_reply", "shuffle": 0})
            elif (
                p[:3] == bytes.fromhex("040026")
                and len(p) in [6, 9]
                and self.authenticated
            ):
                replies.append(
                    packet(bytes.fromhex("040001") + p[3:5] + bytes.fromhex("000026"))
                )
                events.append(
                    {"state": "iap_playback_notification_setup", "mask": p[5:].hex()}
                )
                self.startup_ready = True
                if self.active_app is not None:
                    self.start_app_sessions(events, replies)
                else:
                    events.append({"state": "app_channels_deferred_until_launch"})

            elif len(p) == 6 and p[:2] == b"\0\x41" and self.authenticated:
                txn = int.from_bytes(p[2:4], "big")
                status, command = p[4:6]
                events.extend(self.vehicle_subscription.transport_ack(txn, status, command))
                test = self.display_test
                if command == 0x43 and test and test['transaction'] == txn:
                    self.display_result(events, 'Transport rejected' if status else 'Transport acknowledged',
                                        code=status)
                    test['acknowledged'] = not status
                    if status:
                        self.display_test = None
                if txn in self.session_pending and command == 0x3F:
                    sid, index, name = self.session_pending.pop(txn)
                    if status == 0:
                        self.sessions[sid] = (index, name)
                    events.append(
                        {
                            "state": "iap_data_session_result",
                            "session": sid,
                            "protocol": name,
                            "status": status,
                        }
                    )
                    if status == 0 and name == "jp.co.honda.rd.dispaudio.app.hondalink":
                        self.honda_stage[sid] = "auth_requested"
                        self.send_honda(
                            sid,
                            0,
                            b"\0",
                            events,
                            replies,
                            "honda_authentication_request_sent",
                        )
                    self.open_next_session(events, replies)
                else:
                    events.append(
                        {
                            "state": "iap_accessory_ack",
                            "transaction": txn,
                            "status": status,
                            "command": command,
                        }
                    )
                    if command == 0x43 and txn in self.start_ack_pending:
                        ready_sid = self.start_ack_pending.pop(txn)
                        if status == 0:
                            self.start_local_app(ready_sid, events, replies)

            elif len(p) >= 6 and p[:2] == b"\0\x42" and self.authenticated:
                sid = int.from_bytes(p[4:6], "big")
                data = p[6:]
                events.append(
                    {
                        "state": "iap_honda_data",
                        "session": sid,
                        "protocol": self.sessions.get(sid),
                        "hex": data.hex(),
                    }
                )
                replies.append(packet(b"\0\x02" + p[2:4] + bytes.fromhex("0042")))
                if sid in self.sessions:
                    decoder = self.honda_decoders.setdefault(sid, HondaFrames())
                    for inner in decoder.feed(data):
                        events.append(dict(inner, session=sid, protocol=self.sessions.get(sid)))
                        if inner.get("state") == "honda_frame":
                            mid = inner["message"]
                            body = bytes.fromhex(inner["payload"])
                            test = self.display_test
                            if (mid == 0xC1 and len(body) == 3 and body[0] == 1 and test
                                    and sid == test['session'] and body[1] == test['sequence']):
                                status = 'Application receipt' if body[2] == 1 else 'Application rejected'
                                self.display_result(events, status, code=body[2])
                                if body[2] != 1 or test['action'] == 'exit':
                                    # Detaching the screen here leaves the radio on a black
                                    # HondaLink input and can prevent a same-session relaunch.
                                    self.display_test = None
                                else:
                                    test['receipt'] = True
                            if test and sid == test['session'] and test.get('receipt'):
                                if mid == 0x53 and body == b"\x01" + DISPLAY_URL:
                                    test['own_url'] = True
                                elif mid == 0x11 and body == b"\x05" and test.get('own_url'):
                                    # Connect rebinds its external screen on the
                                    # radio's second-screen refresh notification.
                                    self.send_display_status(sid, 0x20, events, replies)
                                    self.send_display_status(sid, 0x60, events, replies)
                                    self.display_result(events, 'External screen refresh reported')
                                    self.display_test = None
                            if self.sessions[sid][1] in (GENERAL, HONDALINK):
                                self.vehicle_subscription.observe(sid, mid, body, events, self.send_honda, replies)
                            # Stock Communication.exe: b9970 ->12bf44 ->1651c4.
                            # This reports the radio's mode; it is not a button or enable request.
                            if mid == 0xC1 and len(body) == 4 and body[:3] == b"\x00\x01\x64":
                                events.append(dict(state="honda_steering_mode",session=sid,mode=body[3]))
                            if (
                                self.honda_stage.get(sid) == "auth_requested"
                                and mid == 1
                                and body
                                in [
                                    bytes.fromhex("001000000000"),
                                    bytes.fromhex("001000010000"),
                                ]
                            ):
                                self.honda_stage[sid] = "session_start_notified"
                                self.send_honda(
                                    sid,
                                    0,
                                    bytes.fromhex("0101"),
                                    events,
                                    replies,
                                    "honda_session_start_notification_sent",
                                )
                                if (
                                    self.sessions[sid][1]
                                    == "jp.co.honda.rd.dispaudio.app.generals"
                                ):
                                    self.start_ack_pending[self.phone_transaction] = sid
                                if (
                                    self.sessions[sid][1]
                                    == "jp.co.honda.rd.dispaudio.app.hondalink"
                                ):
                                    for general_sid, (
                                        _,
                                        general_name,
                                    ) in self.sessions.items():
                                        if (
                                            general_name
                                            == "jp.co.honda.rd.dispaudio.app.generals"
                                            and general_sid not in self.honda_stage
                                        ):
                                            # Controlled hypothesis: test the existing auth exchange on the other
                                            # Honda protocol. Do not mark it ready without its own inner reply.
                                            self.honda_stage[general_sid] = (
                                                "auth_requested"
                                            )
                                            self.send_honda(
                                                general_sid,
                                                0,
                                                b"\0",
                                                events,
                                                replies,
                                                "general_app_auth_probe_sent",
                                            )

                            if (
                                mid == 9
                                and len(body) == 1
                                and sid in self.app_started_sessions
                            ):
                                fields = {
                                    1: b"\x01"
                                    + (
                                        self.active_app
                                        or "com.honda.hondalink.launcher"
                                    ).encode("ascii")
                                    + b"\0",
                                    2: b"\x02Civic Pi HDMI\0",
                                    3: b"\x03\x01",
                                }
                                if body[0] in fields:
                                    # Category1 is the receiver's fallback category (162118/182A48),
                                    # not a claim to implement a particular Honda navigation/media app.
                                    self.send_honda(
                                        sid,
                                        8,
                                        fields[body[0]],
                                        events,
                                        replies,
                                        "general_app_metadata_reply_sent",
                                    )
                                    self.app_metadata_sent.setdefault(sid, set()).add(
                                        body[0]
                                    )
                                else:
                                    events.append(
                                        {
                                            "state": "general_app_unknown_metadata_request",
                                            "session": sid,
                                            "payload": body.hex(),
                                        }
                                    )

                            # 161B38 routes63 to181ED0/181E00. 196C88 reads bit20 into
                            # basis struct[0];128BB8 selects primary state2 when that field is1.
                            # Other flags are deliberately zero; meanings are not established.
                            if (
                                mid == 0x62
                                and body == b"\x10\xff"
                                and self.active_app is not None
                                and sid in self.app_started_sessions
                            ):
                                # 181E00 ->128BB8: bit20 selects state2; bit40 fills record+14,
                                # required by B61EC before the display-ready branch.
                                self.send_honda(
                                    sid,
                                    0x63,
                                    b"\x10\x60",
                                    events,
                                    replies,
                                    "general_basis_state_reply_sent",
                                )
                                if sid not in self.ready_announced:
                                    # Distinct from message00/subtype10. 161B38 ->1818D8 publishes4.
                                    self.send_honda(
                                        sid,
                                        0x10,
                                        b"",
                                        events,
                                        replies,
                                        "general_connection_ready_notification_sent",
                                    )
                                    self.ready_announced.add(sid)

                            if (
                                mid == 1
                                and body == b"\x13"
                                and sid in self.app_started_sessions
                                and {2, 3} <= self.app_metadata_sent.get(sid, set())
                            ):
                                # 18246C sends01/13; 18292C reads a00/13 reply's second byte.
                                # Receiver18292C only tears down on second byte0.
                                # Test nonzero while local app is active; exact status name unknown.
                                self.send_honda(
                                    sid,
                                    0,
                                    b"\x13\x01",
                                    events,
                                    replies,
                                    "general_metadata_transition_reply_sent",
                                )
                                self.metadata_transition_replied.add(sid)
                            if mid == 3 and sid in self.metadata_transition_replied:
                                events.append(
                                    {
                                        "state": "general_metadata_transition_followup",
                                        "session": sid,
                                        "payload": body.hex(),
                                    }
                                )
                            if (
                                mid == 0xB1
                                and body == b"\0"
                                and self.active_app is not None
                            ):
                                identity = self.vehicle_identities.setdefault(sid, pi_honda_device_info())
                                self.send_honda(
                                    sid,
                                    0xB2,
                                    pi_honda_identity(identity),
                                    events,
                                    replies,
                                    "honda_device_information_reply_sent",
                                )
                                events.append(
                                    {
                                        "state": "honda_identity_test",
                                        "session": sid,
                                        "manufacturer": "Raspberry Pi",
                                        "model": "Pi 4 Model B",
                                        "os_version": 0x060C,
                                        "app_id": 0xFF,
                                        "app_version": 0,
                                        "individual_info": "actual Pi interface MAC or stable serial fallback",
                                    }
                                )
                            if mid == 0xB1 and len(body) == 13 and body[0] == 1:
                                events.append(
                                    {
                                        "state": "honda_authentication_result_received",
                                        "session": sid,
                                        "result": body[1],
                                        "value_1": int.from_bytes(body[2:6], "little"),
                                        "value_2": int.from_bytes(body[6:10], "little"),
                                        "flags": body[10],
                                        "language": body[11:13].decode(
                                            "ascii", "replace"
                                        ),
                                    }
                                )
                                if self.sessions[sid][1] in (GENERAL, HONDALINK):
                                    authorized = bool(body[1])
                                    if authorized:
                                        capable = bool(body[10] & 8)
                                        # Duplicate finish responses can clear the advertised
                                        # capability; native SDK retains an already configured feed.
                                        if sid not in self.vehicle_auth_sessions or capable:
                                            self.vehicle_auth_sessions[sid] = dict(result=body[1], flags=body[10], can_capable=capable)
                                        if capable:
                                            try:
                                                self.vehicle_subscription.authorize(sid, body[2:10], self.vehicle_identities.get(sid))
                                            except ValueError as exc:
                                                events.append(dict(state='honda_can_auth_invalid', session=sid, error=str(exc)))
                                    else:
                                        self.vehicle_auth_sessions.pop(sid, None)
                                        self.vehicle_subscription.clear(sid)
                                        if self.vehicle_session == sid:
                                            self.vehicle_session = None
                                    events.append(dict(state='honda_can_authorization', session=sid,
                                        protocol=self.sessions[sid][1], authorized=authorized,
                                        result=body[1], flags=body[10]))
                            if mid != 0xB3:
                                self.request_vehicle_data(events, replies)
                            if mid == 0xB3 and body == b"\0":
                                # Honda app disconnect is distinct from iAP EndDataSession40.
                                # Retain underlying transports, invalidate application handshake on retry.
                                self.app_restart_needed = True
                                if self.display_test:
                                    self.display_result(events, 'Session closed')
                                    self.display_test = None
                                self.vehicle_subscription.clear()
                                self.vehicle_auth_sessions.clear()
                                self.vehicle_identities.clear()
                                self.vehicle_session = None
                                events.append(
                                    {
                                        "state": "honda_app_disconnect_received",
                                        "session": sid,
                                        "restart_on_next_launch": True,
                                    }
                                )
                            if mid == 0x43:
                                events.append(
                                    {
                                        "state": "honda_touch_candidate",
                                        "session": sid,
                                        "payload": body.hex(),
                                    }
                                )
            elif len(p) == 6 and p[:2] == b"\0\x40" and self.authenticated:
                sid = int.from_bytes(p[4:6], "big")
                self.close_session(sid)
                events.append({"state": "iap_data_session_closed", "session": sid})
                replies.append(packet(b"\0\x02" + p[2:4] + bytes.fromhex("0040")))
            elif (
                p[:3] == bytes.fromhex("04002f") and len(p) == 5 and self.authenticated
            ):
                replies.append(packet(bytes.fromhex("040030") + p[3:5] + b"\0"))
            elif (
                p[:3] == bytes.fromhex("04001c") and len(p) == 5 and self.authenticated
            ):
                replies.append(packet(bytes.fromhex("04001d") + p[3:5] + bytes(9)))
            elif (
                p[:3] == bytes.fromhex("04003b") and len(p) == 6 and self.authenticated
            ):
                replies.append(
                    packet(bytes.fromhex("040001") + p[3:5] + bytes.fromhex("00003b"))
                )
            elif (
                p[:3] == bytes.fromhex("040018") and len(p) == 6 and self.authenticated
            ):
                replies.append(packet(bytes.fromhex("040019") + p[3:5] + bytes(4)))
            elif (
                p[:3] == bytes.fromhex("040035") and len(p) == 5 and self.authenticated
            ):
                replies.append(packet(bytes.fromhex("040036") + p[3:5] + bytes(4)))
            elif (
                p[:3] == bytes.fromhex("040009") and len(p) == 5 and self.authenticated
            ):
                replies.append(packet(bytes.fromhex("04000a") + p[3:5] + b"\0"))
                events.append({"state": "iap_audiobook_speed_reply", "speed": 0})
            elif p[:2] == b"\0\x07" and len(p) == 4 and self.authenticated:
                replies.append(packet(b"\0\x08" + p[2:4] + b"Civic HDMI Pi\0"))
                events.append(
                    {"state": "iap_device_name_reply", "name": "Civic HDMI Pi"}
                )
                # A single timing probe after replying to the later identity query. The first
                # request can precede the radio's higher-level app listener becoming ready.
                for sid, (_, name) in self.sessions.items():
                    if (
                        name == "jp.co.honda.rd.dispaudio.app.hondalink"
                        and self.honda_stage.get(sid) == "auth_requested"
                        and sid not in self.honda_name_retry
                    ):
                        self.honda_name_retry.add(sid)
                        self.send_honda(
                            sid,
                            0,
                            b"\0",
                            events,
                            replies,
                            "honda_auth_request_after_name_reply",
                        )
            elif p[:2] == b"\x03\x08" and len(p) == 8 and self.authenticated:
                replies.append(
                    packet(bytes.fromhex("0300") + p[2:4] + bytes.fromhex("0008"))
                )
                events.append(
                    {"state": "iap_display_event_subscription", "mask": p[4:].hex()}
                )
            elif p[:2] == b"\0\x0b" and len(p) == 4 and self.authenticated:
                replies.append(
                    packet(
                        bytes.fromhex("000c")
                        + p[2:4]
                        + b"CIVICPI"
                        + serial_number()
                        + b"\0"
                    )
                )
                events.append(
                    {
                        "state": "iap_serial_reply",
                        "serial": (b"CIVICPI" + serial_number()).decode("ascii"),
                    }
                )
            elif p[:2] == b"\0\x0d" and len(p) == 4 and self.authenticated:
                replies.append(
                    packet(
                        bytes.fromhex("000e") + p[2:4] + bytes(4) + b"CivicPiZero2W\0"
                    )
                )
                events.append(
                    {
                        "state": "iap_model_reply",
                        "model_id": 0,
                        "model": "CivicPiZero2W",
                    }
                )
            elif p[:2] == b"\0\x09" and len(p) == 4 and self.authenticated:
                replies.append(
                    packet(bytes.fromhex("000a") + p[2:4] + bytes.fromhex("010000"))
                )
                events.append(
                    {"state": "iap_software_version_reply", "version": "1.0.0"}
                )
            elif p[:2] != b"\0\x02":
                events.append(
                    {
                        "state": "iap_unhandled",
                        "lingo": p[0],
                        "command": (
                            int.from_bytes(p[1:3], "big")
                            if p[0] == 4 and len(p) >= 3
                            else p[1]
                        ),
                        "payload": p.hex(),
                    }
                )
        return events, replies

    def run_auth(self, kind, transaction, signature, events, replies):
        if kind == 'certificate':
            operation, args = self.proof.prepare_challenge, ()
        else:
            operation, args = self.proof.verify, (signature,)
        if self.auth_executor is None:
            self.finish_auth(kind, transaction, len(signature), lambda: operation(*args), events, replies)
        else:
            future = self.auth_executor.submit(operation, *args)
            self.pending_auth = (future, kind, transaction, len(signature))

    def finish_auth(self, kind, transaction, signature_bytes, result, events, replies):
        try:
            if kind == 'certificate':
                challenge, size, keys = result()
                replies.append(packet(b"\0\x16" + transaction + b"\0"))
                self.auth_transaction = bytes.fromhex("8001")
                replies.append(packet(b"\0\x17" + self.auth_transaction + challenge + b"\0"))
                events.append(dict(state='iap_signature_challenge_sent', certificate_bytes=size,
                                   public_keys=keys, challenge=challenge.hex(), chain_validation=False))
            else:
                ok, method = result()
                replies.append(packet(b"\0\x19" + transaction + bytes([0 if ok else 1])))
                events.append(dict(state='iap_accessory_key_proof', verified=ok, method=method,
                                   signature_bytes=signature_bytes, chain_validation=False))
                self.auth_transaction = None
                self.authenticated = ok
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            events.append(dict(state=f'iap_{kind}_error', error=str(exc)))

    def poll_auth(self):
        events, replies = [], []
        if self.pending_auth is not None:
            future, kind, transaction, count = self.pending_auth
            if future.done():
                self.pending_auth = None
                self.finish_auth(kind, transaction, count, future.result, events, replies)
        return events, replies

    def cancel_auth(self):
        if self.pending_auth is not None:
            self.pending_auth[0].cancel()
            self.pending_auth = None

    def close_session(self, sid):
        self.vehicle_subscription.clear(sid)
        self.vehicle_auth_sessions.pop(sid, None)
        self.vehicle_identities.pop(sid, None)
        if self.vehicle_session == sid:
            self.vehicle_session = None
        self.sessions.pop(sid,None)
        for mapping in (self.honda_decoders,self.honda_stage,self.app_metadata_sent):mapping.pop(sid,None)
        for values in (self.honda_name_retry,self.app_started_sessions,self.metadata_transition_replied,self.ready_announced):values.discard(sid)
        self.start_ack_pending={txn:value for txn,value in self.start_ack_pending.items() if value!=sid}
        self.session_pending={txn:value for txn,value in self.session_pending.items() if value[0]!=sid}
        self.session_start_requested=False

    def request_vehicle_data(self, events, replies):
        if not self.authenticated or self.active_app is None:
            return
        scope=self.vehicle_scope()
        if scope not in SCOPES:scope='off'
        now = time.monotonic()
        # Firmware C80C4 checks the specific app connection, not a global flag.
        # One owner per app connection; a bootstrap channel cannot borrow auth.
        for sid, auth in self.vehicle_auth_sessions.items():
            name = self.sessions.get(sid, (None, None))[1]
            if name not in (GENERAL, HONDALINK) or self.honda_stage.get(sid) != 'session_start_notified':
                continue
            if not auth.get('can_capable') or sid not in self.vehicle_subscription.keys:
                continue
            if self.vehicle_session is not None and self.vehicle_session != sid:
                continue
            if not self.vehicle_subscription.needs_request(sid, scope, now):
                continue
            self.vehicle_session = sid
            events.append(dict(state='honda_can_session_selected', session=sid,
                               protocol=name, authorization_session=sid, **auth))
            self.vehicle_subscription.request(sid, self.send_honda, events, replies, now=now,
                                              protocol=name, scope=scope)
            return

    def sync_vehicle_scope(self):
        events=[];replies=[]
        self.request_vehicle_data(events,replies)
        return events,replies

    def tick(self):
        events = self.vehicle_subscription.tick()
        test = self.display_test
        if test and (test['session'] not in self.vehicle_auth_sessions
                     or time.monotonic() - test['sent'] >= 5):
            if test['session'] not in self.vehicle_auth_sessions:
                status = 'Session closed'
            elif test.get('receipt'):
                status = 'No matching screen refresh received'
            elif test.get('acknowledged'):
                status = 'No application receipt'
            else:
                status = 'No transport acknowledgment'
            self.display_result(events, status)
            self.display_test = None
        return events

    def display_result(self, events, status, **fields):
        test = self.display_test
        events.append(dict(state='honda_display_test_result', status=status,
                           action=test['action'], session=test['session'], **fields))

    def send_display_status(self, sid, flags, events, replies):
        # Connect's sendStatusNotification packs appForeground (0x20)
        # and externalScreen (0x40) into General 63/10.
        self.send_honda(sid, 0x63, bytes((0x10, flags)) + bytes(5), events, replies,
                        'honda_display_status_sent')

    def request_display_test(self, action):
        events, replies = [], []
        sessions = [sid for sid in self.vehicle_auth_sessions
                    if self.sessions.get(sid, (None, None))[1] in (GENERAL, HONDALINK)
                    and self.honda_stage.get(sid) == 'session_start_notified']
        if not self.authenticated or not self.active_app or not sessions:
            return [dict(state='honda_display_test_result', action=action,
                         status='Waiting for authenticated HondaLink app session')], replies
        if self.display_test:
            return [dict(state='honda_display_test_result', action=action,
                         status='Previous command still awaiting a reply')], replies
        sid = self.vehicle_session if self.vehicle_session in sessions else sessions[0]
        sequence = 0
        if action == 'exit':
            # The app-level display-off command uses the same handler as Show.
            payload = bytes.fromhex('00010000')
        elif action == 'show':
            self.display_sequence = (self.display_sequence + 1) % 256
            sequence = self.display_sequence
            payload = bytes((0, 0, sequence, 4)) + len(DISPLAY_URL).to_bytes(2, 'big') + DISPLAY_URL
        else:
            raise ValueError('Unknown display test')
        self.send_honda(sid, 0xC2, payload, events, replies, 'honda_display_test_sent')
        self.display_test = dict(action=action, session=sid, sequence=sequence,
                                 transaction=events[-1]['transaction'], sent=time.monotonic())
        self.display_result(events, 'Sent')
        return events, replies

    def start_local_app(self, sid, events, replies):
        if sid in self.app_started_sessions:
            return
        app_id = self.active_app or "com.honda.hondalink.launcher"
        if self.launch_app is None:
            events.append(
                {
                    "state": "general_app_local_start_failed",
                    "session": sid,
                    "error": "no renderer",
                }
            )
            return
        try:
            if self.active_app != app_id and not self.launch_app(app_id):
                raise RuntimeError("renderer declined")
        except Exception as exc:
            events.append(
                {
                    "state": "general_app_local_start_failed",
                    "session": sid,
                    "error": str(exc),
                }
            )
            return
        self.active_app = app_id
        self.app_started_sessions.add(sid)
        events.append(
            {"state": "general_app_local_started", "session": sid, "app_id": app_id}
        )
        # Traced name/identifier/category exchange: 182B3C dispatches message08.
        # Field01 is the identifier (record+c compared against launcher ID).
        # Field02 is the display name; remaining fields follow radio09 requests.
        self.send_honda(
            sid,
            8,
            b"\x01" + app_id.encode("ascii") + b"\0",
            events,
            replies,
            "general_app_identifier_notification_sent",
        )

    def send_honda(self, sid, message, payload, events, replies, label):
        self.phone_transaction += 1
        data = honda_frame(message, payload)
        wire = packet(
            b"\0\x43"
            + self.phone_transaction.to_bytes(2, "big")
            + sid.to_bytes(2, "big")
            + data
        )
        replies.append(wire)
        events.append(
            {
                "state": label,
                "session": sid,
                "message": message,
                "payload": payload.hex(),
                "honda_frame": data.hex(),
                "transaction": self.phone_transaction,
            }
        )

    def start_app_sessions(self, events, replies):
        if self.app_restart_needed:
            self.vehicle_subscription.clear()
            self.vehicle_auth_sessions.clear()
            self.vehicle_identities.clear()
            self.vehicle_session = None
            # A successful real launch is required before this method is entered.
            self.honda_stage.clear()
            self.honda_decoders.clear()
            self.honda_name_retry.clear()
            self.start_ack_pending.clear()
            self.app_started_sessions.clear()
            self.app_metadata_sent.clear()
            self.metadata_transition_replied.clear()
            self.ready_announced.clear()
            self.app_restart_needed = False
            # B3 did not close EA transports. Avoid duplicate3F openings; restart Honda
            # exchange on the sessions the accessory has already acknowledged.
            for sid, (_, name) in self.sessions.items():
                if name == "jp.co.honda.rd.dispaudio.app.hondalink":
                    self.honda_stage[sid] = "auth_requested"
                    self.send_honda(
                        sid, 0, b"\0", events, replies, "honda_app_exchange_restarted"
                    )
                    events.append(
                        {
                            "state": "retry_using_existing_iap_sessions",
                            "sessions": sorted(self.sessions),
                        }
                    )
                    return
            # Transport really gone: normal opener can recreate missing sessions.
            self.session_start_requested = False
        if self.session_start_requested:
            return
        self.session_start_requested = True
        for token in self.tokens:
            if token[:2] == b"\0\4" and len(token) > 3:
                name = token[3:].split(b"\0")[0].decode("utf-8", "replace")
                if name in [
                    "jp.co.honda.rd.dispaudio.app.generals",
                    "jp.co.honda.rd.dispaudio.app.hondalink",
                ]:
                    known={entry[1] for entry in self.sessions.values()}
                    known.update(entry[2] for entry in self.session_pending.values())
                    known.update(entry[1] for entry in self.session_queue)
                    if name not in known:self.session_queue.append((token[2], name))
        events.append(
            {"state": "app_channels_start_after_launch", "app_id": self.active_app}
        )
        self.open_next_session(events, replies)

    def open_next_session(self, events, replies):
        if self.session_pending or not self.session_queue:
            return
        index, name = self.session_queue.pop(0)
        sid = 0x100 + index
        txn = 0x8100 + index
        self.session_pending[txn] = (sid, index, name)
        wire = packet(
            b"\0\x3f" + txn.to_bytes(2, "big") + sid.to_bytes(2, "big") + bytes([index])
        )
        replies.append(wire)
        events.append(
            {
                "state": "iap_data_session_open_requested",
                "session": sid,
                "index": index,
                "protocol": name,
                "transaction": txn,
                "hex": wire.hex(),
            }
        )


def parse_tokens(payload):
    if not payload:
        raise ValueError("missing token count")
    count = payload[0]
    i = 1
    tokens = []
    for _ in range(count):
        if i >= len(payload):
            raise ValueError("missing token length")
        n = payload[i]
        i += 1
        if n < 2 or i + n > len(payload):
            raise ValueError("invalid token length")
        tokens.append(payload[i : i + n])
        i += n
    if i != len(payload):
        raise ValueError("trailing token bytes")
    return tokens
