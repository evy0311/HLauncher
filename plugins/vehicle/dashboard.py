"""Touch-first Vehicle dashboard for the 720 × 480 radio."""
from math import cos, radians, sin

from PIL import Image, ImageColor, ImageDraw
from hlauncher_sdk.fonts import font
from hlauncher.ui import home_art
from hlauncher.ui.chrome import BACK_BOUNDS
from hlauncher.ui.controls import Page
from hlauncher.ui.home import caption
from hlauncher.vehicle_fields import (
    DIAGNOSTIC_FIELDS, DIAGNOSTIC_KEYS, GROUPS, MINDER_IDS, SERVICE_ITEMS,
    field_label, unit, visible,
)
from diagnostics import fault_codes, record_title

WIDTH, HEIGHT = 720, 480
TABS = ('Maintenance', 'Health', 'Diagnostics', 'Readings')
FALLBACK_COLORS = dict(background='#101318', panel='#1b2129', accent='#f4b36a', text='#f3f2ee', muted='#aeb9c6')


def blend(low, high, fraction):
    return tuple(round(a + (b-a)*fraction) for a, b in zip(low, high))


class Dashboard:
    def __init__(self, size):
        self.size = size
        self.tab = 0
        self.page = 0
        self.view = None
        self.actions = []
        self.down = None
        self.last_point = None
        self.hidden = set()
        self.readings = {}
        self.reports = {}
        self.last_updated = 'No readings yet'
        self.colors = {}
        self.layout = 'menu'
        self.oem_color = None

    def update(self, snapshot, hidden, colors, layout, *, oem_color=None):
        self.hidden = set(hidden)
        self.readings = snapshot['readings']
        self.last_updated = snapshot['last_updated']
        self.colors = {**FALLBACK_COLORS, **colors}
        self.oem_color = oem_color
        self.layout = layout

    def navigate(self, view=None, *, tab=None):
        if tab is not None:
            self.tab = tab
        self.view, self.page = view, 0

    def turn(self, delta):
        self.page += delta

    def touch(self, action, point=None):
        if action == 'cancel':
            self.down = self.last_point = None
            return False
        if point is not None:
            self.last_point = (point[0]*WIDTH/self.size[0], point[1]*HEIGHT/self.size[1])
        match = next((key for box, key, _ in self.actions if self.inside(box)), None)
        if action == 'down':
            self.down = match
        elif action in ('up', 'unused'):
            selected, self.down = self.down, None
            if selected is not None and match == selected:
                handler = next(fn for _, key, fn in self.actions if key == selected)
                return handler()
        return False

    def inside(self, box):
        if self.last_point is None:
            return False
        x, y = self.last_point
        return box[0] <= x < box[2] and box[1] <= y < box[3]

    def render(self):
        colors = self.colors or FALLBACK_COLORS
        self.c = {k: ImageColor.getrgb(v) if isinstance(v, str) else tuple(v) for k, v in colors.items()}
        self.c['edge'] = blend(self.c['panel'], self.c['text'], .15)
        self.c['raised'] = blend(self.c['panel'], self.c['text'], .08)
        self.actions = []
        self.oem_page = None
        if self.oem_color:
            self.c['accent'] = home_art.blend(home_art.accent(self.oem_color), (245, 243, 255), .62)
            self.c['edge'] = home_art.blend(home_art.accent(self.oem_color), (62, 55, 66), .6)
            pressed = BACK_BOUNDS if self.down == 'home' and self.inside(BACK_BOUNDS) else None
            self.oem_page = Page('Vehicle', self.home, self.oem_color, (WIDTH, HEIGHT), pressed=pressed, heading_y=60)
            self.image, self.d = self.oem_page.image, self.oem_page.draw
            self.top = 144
            nav_y = 96
        else:
            self.image = Image.new('RGB', (WIDTH, HEIGHT), self.c['background'])
            self.d = ImageDraw.Draw(self.image)
            bottom = self.layout in ('console', 'dock')
            self.top = 80 if bottom else 128
            nav_y = 432 if bottom else 68
        self.bottom = self.top + 328
        self.header(nav_y)
        if self.tab == 0:
            self.maintenance()
        elif self.tab == 1:
            self.health()
        elif self.tab == 2:
            self.diagnostics()
        else:
            self.data()
        return self.image if self.size == self.image.size else self.image.resize(self.size, Image.Resampling.LANCZOS)

    def text(self, x, y, value, size=18, role='text', *, weight=400, width=None, anchor='lm'):
        value = str(value)
        if self.oem_page and weight >= 500 and role == 'text':
            label = caption(value, size)
            while width is not None and label.width > width and value:
                value = value[:-1]
                label = caption(value+'…', size)
            offset = {'lm': 0, 'mm': label.width//2, 'rm': label.width}.get(anchor, 0)
            self.image.paste(label, (x-offset, y-label.height//2), label)
            return
        face = font(size, weight)
        if width is not None and self.d.textlength(value, font=face) > width:
            while value and self.d.textlength(value+'…', font=face) > width:
                value = value[:-1]
            value += '…'
        self.d.text((x, y), value, fill=self.c[role], font=face, anchor=anchor)

    def panel(self, box, *, fill='panel', radius=12):
        if self.oem_page:
            x, y, right, bottom = box
            tile = home_art.tile(self.oem_color, right-x, bottom-y, radius=6, control=fill == 'raised')
            self.image.paste(tile, (x, y), tile)
        else:
            self.d.rounded_rectangle(box, radius=radius, fill=self.c[fill], outline=self.c['edge'])

    def rule(self, x, y, right):
        self.d.line((x, y, right, y), fill=self.c['edge'])

    def hit(self, box, key, action):
        self.actions.append((box, key, action))
        return self.down == key and self.inside(box)

    def button(self, box, key, label, action, *, selected=False, size=16):
        x, y, right, bottom = box
        pressed = self.hit(box, key, action)
        if self.oem_page:
            self.oem_page.pressed = box if pressed else None
            self.oem_page.button(box, label, action, selected=selected, size=size+3)
            return
        if selected or pressed:
            self.panel(box, fill='raised', radius=8)
        self.text((x+right)//2, (y+bottom)//2, label, size, weight=500 if selected else 400,
                  width=right-x-12, anchor='mm')

    def chevron(self, x, y, right=True):
        delta = 4 if right else -4
        self.d.line([(x-delta, y-5), (x, y), (x-delta, y+5)], fill=self.c['muted'], width=2)

    @staticmethod
    def home():
        return 'home'

    def header(self, nav_y):
        if self.oem_page:
            self.hit(BACK_BOUNDS, 'home', self.home)
            self.text(696, 74, f'Last updated · {self.last_updated}', 15, 'muted', anchor='rm')
        else:
            self.button((24, 12, 104, 56), 'home', '‹  Home', self.home)
            self.text(116, 34, 'Vehicle', 30, weight=500)
            self.text(696, 22, 'Last updated', 13, 'muted', anchor='rm')
            self.text(696, 42, self.last_updated, 16, width=420, anchor='rm')
            self.rule(24, 60 if nav_y == 68 else 64, 696)
        for i, tab in enumerate(TABS):
            left = 24 + i*170
            self.button((left, nav_y, left+162, nav_y+40), ('tab', i), tab,
                        lambda i=i: self.navigate(tab=i), selected=self.tab == i, size=17)
            if self.tab == i and not self.oem_page:
                self.d.rounded_rectangle((left+60, nav_y+36, left+102, nav_y+38), radius=1, fill=self.c['accent'])

    def has(self, key):
        return visible(key, self.hidden)

    def reading(self, key):
        return self.readings.get(key) if self.has(key) else None

    def value(self, key):
        value = self.reading(key)
        if value is None:
            return 'Waiting'
        if key == '42' and not 0 <= value <= 100:
            return 'Unavailable'
        if isinstance(value, bool):
            result = ('On' if value else 'Off')
        elif isinstance(value, float):
            result = f'{value:.7f}'.rstrip('0').rstrip('.') if key in ('latitude', 'longitude') else f'{value:.5g}'
        else:
            result = str(value)
        suffix = unit(key)
        return result + (f' {suffix}' if suffix else '')

    def dial(self, box):
        left, top, right, end = box
        self.panel(box)
        cx, cy, r = (left+right)//2, top+120, 84
        value = self.reading('42')
        valid = type(value) in (int, float) and 0 <= value <= 100
        for tick in range(41):
            angle = radians(142 + 256*tick/40)
            length = 10 if tick % 10 == 0 else 6
            here = [(cx+round(radius*cos(angle)), cy+round(radius*sin(angle))) for radius in (r-length, r)]
            self.d.line(here, fill=self.c['accent' if valid and 100*tick <= 40*value else 'edge'],
                        width=3 if tick % 10 == 0 else 2)
        self.text(cx, cy-6, f'{value:.0f}%' if valid else '—', 60, weight=500, anchor='mm')
        self.text(cx, cy+39, 'Engine oil life', 16, 'muted', anchor='mm')
        cluster = self.reading('72')
        note = 'HondaLink · engine ECU'
        if not valid and cluster is not None:
            note = 'Cluster code · ' + self.value('72')
        elif not valid:
            note = 'Waiting for oil life' if value is None else 'Oil life unavailable'
        elif value <= 15:
            note = 'Oil life depleted' if value == 0 else 'Service due now' if value <= 5 else 'Service due soon'
        self.text(cx, end-20, note, 14, 'muted', anchor='mm')

    def maintenance(self):
        if self.view == 'guide':
            self.guide()
            return
        if isinstance(self.view, tuple) and self.view[0] == 'service':
            self.service_detail(self.view[1])
            return
        y = self.top
        if 'maintenance' in self.hidden:
            self.empty('Maintenance hidden', 'Change visibility in Settings › Plugins › Vehicle')
            return
        oil = self.has('42')
        if oil:
            self.dial((24, y, 284, y+232))
        x = 300 if oil else 24
        self.panel((x, y, 696, y+232))
        service_fields = [(code, str(ident)) for code, ident in MINDER_IDS.items() if self.has(str(ident))]
        readings = [(code, self.reading(field)) for code, field in service_fields]
        active = [code for code, value in readings if value is True]
        self.text(x+20, y+24, 'Maintenance Minder', 23, weight=500)
        if active:
            for i, code in enumerate(active[:3]):
                row_y = y+48+i*44
                self.service_row(x+20, row_y, 676, code)
            if len(active) > 3:
                self.text(676, y+186, f'+{len(active)-3} more in code guide', 13, 'muted', anchor='rm')
        elif not readings or not any(value is not None for _, value in readings):
            self.text(x+20, y+80, 'Waiting for service codes' if readings else 'Service codes hidden', 21)
            self.text(x+20, y+113, 'Codes appear when the cluster reports them', 15, 'muted', width=656-x)
        else:
            complete = all(value is False for _, value in readings)
            self.text(x+20, y+80, 'No service codes reported' if complete else 'Service codes incomplete', 20,
                      width=656-x)
        self.rule(x+20, y+192, 676)
        self.button((x+12, y+194, 684, y+230), 'guide', 'Honda service code guide',
                    lambda: self.navigate('guide'), size=16)
        self.chevron(669, y+212)
        quick = [key for key in ('75', '144', '40', '77', '61', '132') if self.has(key)]
        for i, key in enumerate(quick[:3]):
            left = 24+i*228
            self.panel((left, y+248, left+216, y+324))
            self.text(left+16, y+268, field_label(key), 14, 'muted', width=184)
            value = self.value(key)
            if key == '75' and isinstance((odo := self.reading(key)), int):
                value = f'{odo:,}'
            self.text(left+16, y+300, value, 23, weight=500, width=184)

    def service_row(self, x, y, right, code, *, reported=False):
        box = (x, y, right, y+42)
        if self.hit(box, ('service', code), lambda: self.navigate(('service', code, self.view))):
            self.panel(box, fill='raised', radius=8)
        self.panel((x, y+4, x+38, y+38), radius=6)
        self.text(x+19, y+21, code, 21, 'accent', weight=500, anchor='mm')
        title = SERVICE_ITEMS.get(code, ('See your Honda manual',))[0]
        self.text(x+52, y+21, title, 17, width=right-x-(168 if reported else 76))
        if reported:
            self.text(right-24, y+21, 'Reported', 14, 'muted', anchor='rm')
        self.chevron(right-4, y+21)

    def guide(self):
        y = self.top
        self.heading('Honda service codes', '2014 Civic Sedan · i-MID', lambda: self.navigate())
        reported = [code for code, ident in MINDER_IDS.items() if self.reading(str(ident)) is True]
        codes = reported + [code for code in SERVICE_ITEMS if code not in reported]
        for i, code in enumerate(self.paginate(codes, 5)):
            self.service_row(24, y+52+i*44, 696, code,
                             reported=code in reported)
        self.pager('codes')

    def service_detail(self, code):
        previous = self.view[2]
        self.heading(f'Service code {code}', 'Maintenance Minder', lambda: self.navigate(previous))
        y = self.top
        title, detail = SERVICE_ITEMS.get(code, ('Check your Honda manual',
               'The 2014 Civic Sedan manual does not list this service item. Use the manual for your model and market.'))
        self.panel((24, y+64, 696, y+284))
        self.text(44, y+98, title, 27, weight=500, width=630)
        face = font(20)
        lines = ['']
        for word in detail.split():
            joined = (lines[-1] + ' ' + word).lstrip()
            if self.d.textlength(joined, font=face) > 628:
                lines.append(word)
            else:
                lines[-1] = joined
        for i, line in enumerate(lines):
            self.text(44, y+136+i*25, line, 20)
        if code in SERVICE_ITEMS:
            self.text(44, y+264, 'Honda 2014 Civic Sedan Owner’s Manual · p. 359', 14, 'muted')

    def heading(self, title, note, back=None):
        self.text(24, self.top+13, title, 25, weight=500, width=540)
        self.text(24, self.top+38, note, 14, 'muted', width=540)
        if back:
            self.button((592, self.top, 696, self.top+44), 'back', '‹  Back', back, selected=True)

    def empty(self, title, note):
        self.panel((24, self.top, 696, self.bottom-4))
        self.text(48, self.top+124, title, 26, weight=500)
        self.text(48, self.top+164, note, 17, 'muted', width=624)

    def list_row(self, y, key, label, value='', *, action=None, role='muted'):
        box = (24, y, 696, y+44)
        if self.oem_page and action:
            box = (24, y, 696, y+40)
            self.oem_page.pressed = box if self.hit(box, key, action) else None
            self.oem_page.bar(box, label, action, value=value, size=22)
            return
        if action:
            pressed = self.hit(box, key, action)
            if pressed:
                self.panel(box, fill='raised', radius=8)
            self.chevron(688, y+22)
        self.rule(24, y+44, 696)
        self.text(32, y+22, label, 17, width=392 if value else 630)
        self.text(664 if action else 688, y+22, value, 17, role, width=248, anchor='rm')

    def paginate(self, rows, limit):
        self.pages = max(1, (len(rows)+limit-1)//limit)
        self.page = min(max(0, self.page), self.pages-1)
        return rows[self.page*limit:(self.page+1)*limit]

    def pager(self, label):
        if self.pages < 2:
            return
        y = self.bottom-44
        for x, delta, name in ((24, -1, '‹  Previous'), (568, 1, 'Next  ›')):
            if 0 <= self.page+delta < self.pages:
                self.button((x, y, x+128, y+44), (label, delta), name, lambda delta=delta: self.turn(delta),
                            selected=True)
        self.text(360, y+22, f'{self.page+1} / {self.pages}', 15, 'muted', anchor='mm')

    def health(self):
        if self.view in ('warnings', 'tires'):
            group = self.view
            fields = [key for key in GROUPS[group][1] if self.has(key)]
            if group == 'warnings':
                fields.sort(key=lambda key: (self.reading(key) is not True, self.reading(key) is None))
            self.fields(group, fields, lambda: self.navigate(), health=True)
            return
        warnings = [key for key in GROUPS['warnings'][1] if self.has(key)]
        tires = [key for key in GROUPS['tires'][1] if self.has(key)]
        reported = [(key, self.reading(key)) for key in warnings]
        active = [key for key, value in reported if value is True]
        checked = sum(value is not None for _, value in reported)
        y = self.top
        if warnings:
            self.panel((24, y, 696, y+148))
            self.text(44, y+26, 'Warning indicators', 23, weight=500)
            if active:
                self.text(44, y+61, f'{len(active)} reported active', 26, 'accent', weight=500)
                self.text(44, y+90, ' · '.join(map(field_label, active)), 16, 'muted', width=626)
            else:
                self.text(44, y+70, 'No active warnings reported' if checked else 'Waiting for warning data', 23)
            self.button((44, y+104, 676, y+144), 'warnings', f'View indicators · {checked} of {len(warnings)} reported',
                        lambda: self.navigate('warnings'), size=16)
            self.chevron(672, y+124)
        if tires:
            top = y+164 if warnings else y
            self.panel((24, top, 696, top+160))
            self.text(44, top+26, 'Tires and TPMS', 23, weight=500)
            pressure = [k for k in ('126', '127', '128', '129') if self.has(k)]
            for index, key in enumerate(pressure):
                x = 44+index*156
                self.text(x, top+62, field_label(key).removesuffix(' pressure'), 15, 'muted')
                self.text(x, top+91, self.value(key), 20, width=144)
            if pressure and any(self.reading(key) is not None for key in pressure):
                self.text(676, top+26, 'Native pressure values', 14, 'muted', anchor='rm')
            if not pressure:
                self.text(44, top+76, 'View tire warning indicators', 17, 'muted')
            self.rule(44, top+116, 676)
            self.button((44, top+118, 676, top+158), 'tires', 'Tire readings and warnings',
                        lambda: self.navigate('tires'), size=16)
            self.chevron(672, top+138)
        else:
            fields = [key for key in ('40', '44', '1002', '77', '152', '140') if self.has(key)]
            if fields:
                self.powertrain_summary(y+164 if warnings else y, fields[:4])
            elif not warnings:
                self.empty('Health readings hidden', 'Change visibility in Settings › Plugins › Vehicle')

    def powertrain_summary(self, y, fields):
        self.panel((24, y, 696, y+160))
        self.text(44, y+26, 'Operating readings', 23, weight=500)
        for i, key in enumerate(fields):
            x = 44+i*156
            self.text(x, y+62, field_label(key), 15, 'muted', width=144)
            self.text(x, y+91, self.value(key), 20, width=144)
        self.rule(44, y+116, 676)
        self.button((44, y+118, 676, y+158), 'operating-readings', 'View all readings',
                    lambda: self.navigate(tab=3), size=16)
        self.chevron(672, y+138)

    def diagnostics(self):
        keys = [(kind, field) for kind, field in DIAGNOSTIC_KEYS.items() if self.has(field)]
        if isinstance(self.view, tuple):
            self.diagnostic_report(*self.view)
            return
        if not keys:
            self.empty('Diagnostics hidden', 'Change visibility in Settings › Plugins › Vehicle')
            return
        self.heading('Fault codes and freeze frames', 'Last reports from vehicle modules')
        for i, (kind, field) in enumerate(keys):
            y = self.top+64+i*76
            box = (24, y, 696, y+64)
            active = self.hit(box, field, lambda kind=kind: self.navigate((kind, 'codes' if kind != 3 else 'raw')))
            self.panel(box, fill='raised' if active else 'panel')
            label = DIAGNOSTIC_FIELDS[field]
            self.text(44, y+20, label, 20, weight=500)
            if kind in self.reports:
                records, total, complete = self.reports[kind]
                codes = fault_codes(kind, records)
                status = 'Receiving report'
                if complete:
                    count = f'{total} record' + ('s' if total != 1 else '')
                    status = count if kind == 3 else f'{len(codes)} decoded · {count}'
            else:
                status = 'Waiting for a report'
            self.text(44, y+44, status, 15, 'muted')
            self.chevron(676, y+32)

    def diagnostic_report(self, kind, view):
        records, total, complete = self.reports.get(kind, ([], 0, False))
        if kind not in self.reports:
            note = 'Waiting for a report from this stream'
        elif not complete:
            note = 'Receiving report'
        else:
            note = f'{len(records)} of {total} records available'
        self.heading(DIAGNOSTIC_FIELDS[DIAGNOSTIC_KEYS[kind]], note, lambda: self.navigate())
        base = self.top+56
        if kind != 3:
            for i, (key, label) in enumerate((('codes', 'Fault codes'), ('raw', 'Report records'))):
                x = 24+i*172
                self.button((x, base, x+160, base+40), key, label, lambda key=key: self.navigate((kind, key)),
                            selected=view == key)
            base += 44
        if view == 'codes':
            items = fault_codes(kind, records)
            if not items:
                self.text(32, base+36, 'No codes decoded in this report' if kind in self.reports
                          else 'No fault report received', 19, 'muted')
            for i, (code, module) in enumerate(self.paginate(items, 3)):
                y = base+4+i*56
                self.panel((24, y, 696, y+52))
                self.text(44, y+26, code, 25, weight=500)
                self.text(676, y+26, module, 17, 'muted', anchor='rm', width=300)
        else:
            items = [(mid, raw, raw[i:i+32], i//2) for mid, raw in records
                     for i in range(0, max(1, len(raw)), 32)]
            for i, (mid, raw, chunk, offset) in enumerate(self.paginate(items, 4 if kind != 3 else 5)):
                y = base+i*44
                self.text(32, y+11, f'0x{mid:X}   {record_title(kind, mid, raw)}', 15)
                data = ' '.join(chunk[n:n+2] for n in range(0, len(chunk), 2)).upper()
                self.text(32, y+29, f'+{offset:02X}   {data}' if offset else data or 'Empty record', 15, 'muted')
                self.rule(24, y+44, 696)
        self.pager('report')

    def fields(self, group, fields, back, *, health=False):
        label = GROUPS[group][0]
        note = 'Raw values shown where units are unknown'
        if health and group == 'warnings':
            note = 'Last states reported by the radio'
        self.heading(label, note, back)
        for i, key in enumerate(self.paginate(fields, 5)):
            value = self.value(key)
            role = 'text'
            if group in ('warnings', 'tires') and isinstance(self.reading(key), bool):
                on = self.reading(key)
                value = 'Active' if on else 'Off'
                role = 'accent' if on else 'muted'
            self.list_row(self.top+52+i*44, key, field_label(key), value, role=role)
        self.pager('fields')

    def data(self):
        if self.view is not None:
            group = self.view
            fields = [key for key in GROUPS[group][1] if self.has(key)]
            self.fields(group, fields, lambda: self.navigate())
            return
        groups = [(key, title, [k for k in fields if self.has(k)]) for key, (title, fields) in GROUPS.items()
                  if key != 'diagnostics']
        groups = [(key, title, fields) for key, title, fields in groups if fields]
        if not groups:
            self.empty('Readings hidden', 'Change visibility in Settings › Plugins › Vehicle')
            return
        self.heading('Vehicle readings', 'All visible HondaLink signals by system')
        for i, (key, title, fields) in enumerate(self.paginate(groups, 5)):
            saved = sum(self.reading(key) is not None for key in fields)
            self.list_row(self.top+52+i*44, key, title, f'{saved} of {len(fields)} recorded',
                          action=lambda key=key: self.navigate(key))
        self.pager('groups')
