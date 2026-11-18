"""Shared DNS configuration and HTTP responses for the setup hotspot."""
from pathlib import Path

ADDRESS = '192.168.4.1'
SETUP_URL = f'http://{ADDRESS}/'
DNS_CONFIG = f'address=/#/{ADDRESS}\nlocal=/#/\n'


def configure_dns(path=Path('/etc/NetworkManager/dnsmasq-shared.d/90-hlauncher.conf')):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != DNS_CONFIG:
        path.write_text(DNS_CONFIG)


def redirect(handler):
    handler.send_response(302)
    handler.send_header('Location', SETUP_URL)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', '0')
    handler.end_headers()
