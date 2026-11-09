"""SH4 firmware196E64/183884 touch wire layout, with coordinates from1834E0."""

ACTIONS = {0: "unused", 1: "down", 2: "move", 255: "up"}


def decode_touch(payload):
    if len(payload) < 4:
        raise ValueError("touch header truncated")
    count = payload[3]
    if count > 2:
        raise ValueError("unsupported contact count")
    expected = 14 if count else 4
    if len(payload) != expected:
        raise ValueError("touch payload length mismatch")
    contacts = []
    for slot in range(2 if count else 0):
        at = 4 + slot * 5
        action = payload[at]
        x = int.from_bytes(payload[at + 1 : at + 3], "big")
        y = int.from_bytes(payload[at + 3 : at + 5], "big")
        if action not in ACTIONS:
            raise ValueError("unknown contact action")
        has_position = action in (1, 2) and x <= 32767 and y <= 32767
        if action in (1, 2) and not has_position:
            raise ValueError("active contact coordinates out of range")
        contacts.append(
            {
                "slot": slot,
                "action": ACTIONS[action],
                "raw_action": action,
                "x_raw": x,
                "y_raw": y,
                "has_position": has_position,
            }
        )
    return {
        "elapsed_ms": int.from_bytes(payload[:3], "big"),
        "reported_contacts": count,
        "contacts": contacts,
    }


def pixels(contact, width, height):
    if not contact["has_position"]:
        return None
    return (
        round(contact["x_raw"] * (width - 1) / 32767),
        round(contact["y_raw"] * (height - 1) / 32767),
    )


def for_viewport(touch, width, height):
    """Keep both raw contacts and add viewport coordinates for plugin consumers."""
    event = dict(touch, width=width, height=height)
    event["contacts"] = []
    for contact in touch.get("contacts", []):
        item = dict(contact)
        point = pixels(contact, width, height)
        item.update(
            id=contact["slot"],
            x=contact["x_raw"] / 32767 if point else None,
            y=contact["y_raw"] / 32767 if point else None,
            x_px=point[0] if point else None,
            y_px=point[1] if point else None,
        )
        event["contacts"].append(item)
    return event
