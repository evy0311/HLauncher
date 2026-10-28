"""Translate stable Honda contact slots to the dongle's touch messages."""


class TouchRouter:
    def __init__(self):
        self.points = [{"x": 0.5, "y": 0.5, "active": False} for _ in range(2)]
        self.multi = False
        self.single_slot = None

    def single(self, slot, action):
        p = self.points[slot]
        return {
            "type": "touch",
            "action": action,
            "x": p["x"],
            "y": p["y"],
            "_motion": action == 15,
        }

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
        output = []
        entering_multi = not self.multi and sum(after) == 2
        if entering_multi:
            if self.single_slot is not None:
                output.append(self.single(self.single_slot, 16))
                self.single_slot = None
            self.multi = True
            # Start contacts in order even if both arrive in one Honda report.
            # The dongle should see pointer zero before pointer one is added.
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
        if self.multi:
            # Always transmit both slots. Array index is the dongle contact ID;
            # compacting the list when slot zero lifts would change finger IDs.
            touches = []
            for slot, p in enumerate(self.points):
                action = (
                    (
                        2
                        if entering_multi and slot == 0
                        else 1 if entering_multi or not before[slot] else 2
                    )
                    if after[slot]
                    else 0
                )
                touches.append({"x": p["x"], "y": p["y"], "action": action})
            output.append(
                {
                    "type": "multitouch",
                    "touches": touches,
                    "_motion": before == after and any(after) and not entering_multi,
                }
            )
            if not any(after):
                self.multi = False
        elif any(after):
            slot = after.index(True)
            if self.single_slot is not None and self.single_slot != slot:
                output.append(self.single(self.single_slot, 16))
                self.single_slot = None
            output.append(self.single(slot, 14 if self.single_slot is None else 15))
            self.single_slot = slot
        elif self.single_slot is not None:
            output.append(self.single(self.single_slot, 16))
            self.single_slot = None
        return output

    def cancel(self):
        return self.feed({"contacts": []})
