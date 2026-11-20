"""Bounded, session-local facts reported by a projection adapter."""
import re


def text(value, limit=80):
    if not isinstance(value, str):
        return ''
    return ''.join(c for c in value if c.isprintable()).strip()[:limit]


class AdapterInfo:
    def __init__(self):
        self.fields = {}

    def update(self, event):
        kind = event.get('state')
        if kind in ('waiting_dongle', 'usb_failure'):
            self.fields.clear()
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
            phone = event.get('phone_type')
            self.fields['protocol'] = {3: 'CarPlay', 5: 'Android Auto'}.get(phone, '') if type(phone) is int else ''
            wifi = event.get('wifi')
            self.fields['transport'] = {0: 'USB (reported)', 1: 'Wireless (reported)'}.get(wifi, '') if type(wifi) is int else ''
        elif kind in ('phone_disconnected', 'dongle_ready'):
            self.fields.pop('protocol', None)
            self.fields.pop('transport', None)

    def snapshot(self):
        return {key: value for key, value in self.fields.items() if value}
