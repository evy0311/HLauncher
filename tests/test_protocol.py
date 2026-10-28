import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from iap_honda_start_pi4_v32 import StartProbe, packet
from honda_frames import Frames, frame

# Golden fields follow the traced consumer:08/01 -> record+c -> ACBAC ->
# B4EAC launcher comparison. Actual captured09/02 request must get display text.
for width in range(1, 20):
    p = StartProbe(lambda _: True)
    p.authenticated = True
    p.sessions = {257: (1, "jp.co.honda.rd.dispaudio.app.generals")}
    e = []
    r = []
    p.start_local_app(257, e, r)
    assert (
        e[-1]["message"] == 8
        and bytes.fromhex(e[-1]["payload"]) == b"\x01com.honda.hondalink.launcher\0"
    )
    raw = packet(bytes.fromhex("004200220101") + frame(9, b"\x02"))
    events = []
    for i in range(0, len(raw), width):
        events += p.feed(raw[i : i + width])[0]
    q = [x for x in events if x["state"] == "general_app_metadata_reply_sent"]
    assert len(q) == 1 and q[0]["payload"] == b"\x02Civic Pi HDMI\0".hex()
    raw = packet(bytes.fromhex("004200230101") + frame(9, b"\x03"))
    e, r = p.feed(raw)
    assert any(
        x["state"] == "general_app_metadata_reply_sent" and x["payload"] == "0301"
        for x in e
    )
    e, r = p.feed(packet(bytes.fromhex("004200240101") + frame(1, b"\x13")))
    assert any(
        x["state"] == "general_metadata_transition_reply_sent"
        and x["payload"] == "1301"
        for x in e
    )
print(
    "PASS: firmware-derived identifier/name order, captured metadata requests at all split widths, category/transition behavior preserved."
)

# Only general-lingo bit24 changes. Launch must still require a real callback.
for lingo in [0, 2, 3, 4, 10, 12, 14]:
    p = StartProbe()
    e, r = p.feed(packet(bytes([0, 0x4B, 0x12, 0x34, lingo])))
    q = [v for v in e if v["state"] == "iap_options_reply_queued"]
    assert len(q) == 1
    assert int(q[0]["options"], 16) == (0x01002000 if lingo == 0 else 0)
    assert r == [
        packet(
            bytes([0, 0x4C, 0x12, 0x34, lingo])
            + (0x01002000 if lingo == 0 else 0).to_bytes(8, "big")
        )
    ]
for result in [False, True]:
    p = StartProbe(lambda _: result)
    p.authenticated = True
    e, r = p.feed(
        packet(bytes.fromhex("00641234") + bytes(3) + b"com.honda.hondalink.launcher\0")
    )
    q = [v for v in e if v["state"] == "iap_application_launch_result"]
    assert len(q) == 1 and (q[0]["status"] == 0) == result
print(
    "PASS: single general-option bit added; other lingoes unchanged; launch success still requires actual callback success."
)

for app_id in [
    "com.honda.hondalink.launcher",
    "com.honda.hondalink.connect",
    "unknown.test",
]:
    for success in [False, True]:
        called = []

        def cb(name):
            called.append(name)
            return success

        p = StartProbe(cb)
        p.authenticated = True
        e, r = p.feed(packet(bytes.fromhex("00640042000200") + app_id.encode() + b"\0"))
        q = [v for v in e if v["state"] == "iap_application_launch_result"]
        assert len(q) == 1
        allowed = app_id != "unknown.test"
        assert called == ([app_id] if allowed else [])
        assert (q[0]["status"] == 0) == (success and allowed)
        assert p.active_app == (app_id if success and allowed else None)
        e, r = p.feed(packet(bytes.fromhex("00650043")))
        assert r == [
            packet(
                bytes.fromhex("00660043")
                + (app_id if success and allowed else "").encode()
                + b"\0"
            )
        ]
