"""Hotspot-only HTTP probe redirects for phone captive-network assistants."""
import errno
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import threading

ADDRESS='192.168.4.1'
SETUP_URL='http://192.168.4.1:8080/'
DNS_CONFIG='address=/#/192.168.4.1\nlocal=/#/\n'


class Redirect(BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(5)
    def log_message(self,*args):pass
    def redirect(self):
        self.send_response(302)
        self.send_header('Location',SETUP_URL)
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length','0')
        self.end_headers()
    do_GET=redirect
    do_HEAD=redirect


class Portal:
    def __init__(self,server_class=ThreadingHTTPServer):
        self.server_class=server_class;self.server=None
    def configure_dns(self,path=Path('/etc/NetworkManager/dnsmasq-shared.d/90-hlauncher.conf')):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists() or path.read_text()!=DNS_CONFIG:path.write_text(DNS_CONFIG)
    def start(self):
        if self.server:return True
        try:self.server=self.server_class((ADDRESS,80),Redirect)
        except OSError as exc:
            if exc.errno in (errno.EADDRNOTAVAIL,errno.EADDRINUSE):return False
            raise
        self.server.daemon_threads=True
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        return True
    def close(self):
        if self.server:
            self.server.shutdown();self.server.server_close();self.server=None
