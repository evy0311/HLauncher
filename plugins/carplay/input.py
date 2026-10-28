"""Translate stable Honda contact slots to a continuous dongle contact stream."""


class TouchRouter:
    def __init__(self):
        self.points = [{"x": 0.5, "y": 0.5, "active": False} for _ in range(2)]

    def feed(self, event):
        before = [p["active"] for p in self.points]
        contacts = {
            c["slot"]: c for c in event.get("contacts", []) if c.get("slot") in (0, 1)
        }
        for slot, point in enumerate(self.points):
            contact = contacts.get(slot)
            active = bool(
                contact
                and contact.get("action") in ("down", "move")
                and contact.get("has_position")
            )
            if active:
                point["x"] = max(0.0, min(1.0, contact["x_raw"] / 32767))
                point["y"] = max(0.0, min(1.0, contact["y_raw"] / 32767))
            point["active"] = active
        after = [p["active"] for p in self.points]
        if not any(before) and not any(after):
            return []
        output = []
        simultaneous = not any(before) and all(after)
        if simultaneous:
            output.append(
                {
                    "type": "multitouch",
                    "touches": [
                        {"x": p["x"], "y": p["y"], "action": 1 if i == 0 else 0}
                        for i, p in enumerate(self.points)
                    ],
                    "_motion": False,
                }
            )
        # Fixed array positions are contact IDs. Never compact the array or end
        # pointer zero just because pointer one is being added.
        touches = []
        for slot, point in enumerate(self.points):
            active_before = before[slot] or (simultaneous and slot == 0)
            action = (2 if active_before else 1) if after[slot] else 0
            touches.append({"x": point["x"], "y": point["y"], "action": action})
        output.append(
            {
                "type": "multitouch",
                "touches": touches,
                "_motion": before == after and any(after),
            }
        )
        return output

    def cancel(self):
        return self.feed({"contacts": []})
