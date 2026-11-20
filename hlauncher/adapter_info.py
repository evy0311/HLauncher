"""Bounded, session-local facts reported by a projection adapter."""
import re
import hashlib


def text(value, limit=80):
    if not isinstance(value, str):
        return ''
    return ''.join(c for c in value if c.isprintable()).strip()[:limit]


class AdapterInfo:
    def __init__(self):
        self.fields = {}
        self.phones = {}
        self.connected = False
        self.peer = None
        self.paired = set()
        self.addresses = {}

    def phone_reports(self):
        return [dict(phone, connected=self.connected and key == self.peer, paired=key in self.paired)
                for key, phone in self.phones.items()]

    def phone(self, report):
        if not isinstance(report, dict):
            return None
        identity = text(report.get('btMacAddr') or report.get('id'), 128).upper()
        if identity == '00:00:00:00:00:00' or not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', identity):
            return None
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.addresses[key] = identity
        previous = self.phones.get(key, {})
        self.phones[key] = dict(previous, id=key,
            name=text(report.get('btName') or report.get('name')) or previous.get('name', 'Phone'),
            protocol=text(report.get('MDLinkType') or report.get('type')) or previous.get('protocol', ''),
            transport=self.fields.get('transport', '') if key == self.peer else previous.get('transport', ''))
        self.phones = dict(list(self.phones.items())[-32:])
        self.addresses = {key: value for key, value in self.addresses.items() if key in self.phones}
        return key

    def update(self, event):
        kind = event.get('state')
        if kind in ('waiting_dongle', 'usb_failure'):
            self.fields.clear()
            self.phones.clear()
            self.connected = False
            self.peer = None
            self.paired.clear()
            self.addresses.clear()
        elif kind == 'dongle_identity':
            vendor, product = event.get('vendor_id'), event.get('product_id')
            if all(type(v) is int and 0 <= v <= 65535 for v in (vendor, product)):
                self.fields['usb_id'] = f'{vendor:04x}:{product:04x}'
        elif kind == 'dongle_software_version':
            self.fields['firmware'] = text(event.get('version'))
        elif kind == 'dongle_box_info':
            settings = event.get('settings')
            if not isinstance(settings, dict):
                return
            devices = settings.get('DevList')
            if isinstance(devices, list):
                self.paired.clear()
                for device in devices[:32]:
                    key = self.phone(device)
                    if key:
                        self.paired.add(key)
            if settings.get('btMacAddr'):
                self.peer = self.phone(settings)
                if self.peer:
                    self.phones[self.peer]['transport'] = self.fields.get('transport', '')
            for source, target in (('productType', 'product'), ('hwVersion', 'hardware'),
                                   ('boxType', 'box_type')):
                if source in settings:
                    self.fields[target] = text(settings[source])
            supported = text(settings.get('supportLinkType'), 160)
            if supported:
                modes = {re.sub(r'[-_]', '', mode).casefold()
                         for mode in re.split(r'[,;|\s]+', supported)}
                self.fields['aa_support'] = 'Reported' if 'androidauto' in modes else 'Not advertised'
        elif kind == 'phone_connected':
            self.connected = True
            self.peer = None
            phone = event.get('phone_type')
            self.fields['protocol'] = {3: 'CarPlay', 5: 'Android Auto'}.get(phone, '') if type(phone) is int else ''
            wifi = event.get('wifi')
            self.fields['transport'] = {0: 'USB (reported)', 1: 'Wireless (reported)'}.get(wifi, '') if type(wifi) is int else ''
        elif kind in ('phone_disconnected', 'dongle_ready'):
            self.connected = False
            self.peer = None
            self.fields.pop('protocol', None)
            self.fields.pop('transport', None)

    def snapshot(self):
        return {key: value for key, value in self.fields.items() if value}
