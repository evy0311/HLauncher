# Copyright (C) 2026 Evan Horsley (evy0311)
# GPL-3.0; see LICENSE and NOTICE at the project root.
"""Translate HLauncher's two stable contacts to Android pointer transitions."""

class TouchRouter:
    def __init__(self):
        self.points = {}

    def feed(self, message):
        desired = {}
        for c in message.get('contacts', []):
            slot = c.get('slot')
            if slot in (0, 1) and c.get('action') in ('down', 'move') and c.get('has_position'):
                desired[slot] = {'id': slot, 'x': max(0,min(799,round(c['x_raw']/32767*799))),
                                 'y': max(0,min(479,round(c['y_raw']/32767*479)))}
        output = []
        for slot in self.points.keys() & desired.keys():
            self.points[slot] = desired[slot]
        # Release with the old contact still present; action index is its position.
        for slot in sorted(self.points.keys() - desired.keys(), reverse=True):
            ids = sorted(self.points)
            output.append(self.event(1 if len(ids)==1 else 6,ids.index(slot)))
            del self.points[slot]
        for slot in sorted(desired.keys() - self.points.keys()):
            self.points[slot] = desired[slot]
            ids = sorted(self.points)
            output.append(self.event(0 if len(ids)==1 else 5,ids.index(slot)))
        if not output and self.points:
            output.append(self.event(2,0))
        return output

    def event(self, action, index):
        return {'type':'touch','action':action,'index':index,
                'points':[dict(self.points[i]) for i in sorted(self.points)]}
