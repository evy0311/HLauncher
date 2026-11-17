"""Render host-owned HondaLink data in a foreground plugin process."""

import time

from hlauncher_sdk import Client
from hlauncher.display import encode

from dashboard import Dashboard


def main():
    client = Client()
    dashboard = Dashboard((client.width, client.height))
    active, dirty = False, False
    last_health = 0
    latest = None
    revision = None
    frames = 0
    try:
        while True:
            while message := client.receive(0):
                kind = message['type']
                if kind == 'host.activate':
                    active = True
                    client.status('Vehicle', video_available=True)
                elif kind in ('host.stop', 'host.deactivate'):
                    return
                elif kind == 'vehicle.dashboard' and latest != message:
                    latest = message
                    if revision != message['revision']:
                        revision = message['revision']
                        dashboard.reports.clear()
                    dashboard.update(message['snapshot'], message['hidden'], message['colors'], message['layout'])
                    dirty = True
                elif kind == 'vehicle.report' and message['revision'] == revision:
                    report = message['kind']
                    start = message['start']
                    records = dashboard.reports.get(report, ([], 0))[0]
                    dashboard.reports[report] = (records[:start] + message['records'], message['total'], message['complete'])
                    dirty = True
                elif kind == 'touch.cancel':
                    dashboard.touch('cancel')
                    dirty = True
                elif kind == 'touch' and active:
                    contacts = message.get('contacts', [])
                    contact = contacts[0] if contacts else {}
                    point = (contact['x_px'], contact['y_px']) if (
                        contact.get('x_px') is not None and contact.get('y_px') is not None) else None
                    if dashboard.touch(contact.get('action', 'unused'), point) == 'home':
                        client.home()
                        active = False
                    dirty = True
            if active and dirty and client.free and client.present(encode(dashboard.render())):
                dirty = False
                frames += 1
            now = time.monotonic()
            if now-last_health >= 2:
                client.send(type='health', metrics={'frames': frames})
                last_health = now
            time.sleep(.012 if active else .025)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        client.close()


if __name__ == '__main__':
    main()
