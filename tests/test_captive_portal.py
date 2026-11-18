import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from hlauncher.captive_portal import configure_dns, DNS_CONFIG
from hlauncher.recovery import Maintenance,handler_for
from hlauncher.setup_state import SetupState


class CaptivePortal(unittest.TestCase):
    def test_phone_probes_and_arbitrary_hosts_redirect_to_fixed_setup_address(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        state = SetupState(Path(folder))
        self.enterContext(patch('hlauncher.captive_portal.ADDRESS', '127.0.0.1'))
        self.enterContext(patch('hlauncher.captive_portal.SETUP_URL', 'http://127.0.0.1/'))
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(state,Maintenance(state)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        conn=http.client.HTTPConnection(*server.server_address,timeout=3)
        try:
            for path in ('/generate_204','/hotspot-detect.html','/connecttest.txt','/arbitrary'):
                conn.request('GET',path,headers={'Host':'untrusted.example'})
                reply=conn.getresponse();self.assertEqual(reply.status,302)
                self.assertEqual(reply.getheader('Location'),'http://127.0.0.1/')
                self.assertEqual(reply.getheader('Cache-Control'),'no-store');reply.read()
            conn.request('HEAD','/hotspot-detect.html')
            reply=conn.getresponse();self.assertEqual(reply.status,302);reply.read()
            conn.request('GET','/')
            reply=conn.getresponse();self.assertEqual(reply.status,200)
            self.assertIn(b'Nearby networks', reply.read())
        finally:conn.close();server.shutdown();server.server_close();thread.join(3)
    def test_dns_config_is_separate_from_normal_network_dns(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'dnsmasq-shared.d/90-hlauncher.conf'
            configure_dns(path)
            self.assertEqual(path.read_text(),DNS_CONFIG)
            self.assertIn('192.168.4.1',path.read_text())
