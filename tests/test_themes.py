"""Layout themes are persistent data and never replace launcher routes."""

from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from hlauncher.recovery import handler_for
from hlauncher.setup_state import SetupState
from hlauncher.themes import OEM, Themes


def theme_document(identifier='my-garage', name='My Garage', **layouts):
    return dict(format=1, id=identifier, name=name, layouts=layouts,
                colors=dict(background='#11191E', panel='#213139', accent='#82D4C4',
                            text='#F4F8F6', muted='#A7BEC5'))


class ThemeTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = SetupState(Path(folder.name))
        self.themes = Themes(self.state.folder)
        self.document = theme_document(home='grid', settings='list')

    def request(self, method, data=None, *, origin=None, host='192.168.4.1'):
        handler_type = handler_for(self.state, Mock())
        handler = handler_type.__new__(handler_type)
        raw = json.dumps(data).encode()
        handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw)),
                           'Host': host}
        handler.connection = Mock()
        handler.connection.getsockname.return_value = ('192.168.4.1', 80)
        if origin:
            handler.headers['Origin'] = origin
        handler.path = '/api/layout-themes'
        handler.rfile = BytesIO(raw)
        handler.wfile = BytesIO()
        handler.send = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        getattr(handler, 'do_' + method)()
        return handler

    def test_setup_site_imports_and_exports_validated_layouts(self):
        handler = self.request('POST', self.document, origin='http://192.168.4.1')
        handler.send.assert_called_once_with(201, {'id': 'my-garage', 'name': 'My Garage'})
        self.themes.reload()
        self.assertEqual(self.themes.get('my-garage').layouts, {'home': 'grid', 'settings': 'list'})
        response = self.request('GET').send.call_args.args[1]
        self.assertIn(self.document, response['themes'])
        self.assertIs(self.themes.get('missing'), OEM)
        starter = response['templates']['touring']
        self.request('POST', starter).send.assert_called_once_with(201, {
            'id': 'touring-copy', 'name': 'Touring copy',
        })
        response = self.request('GET').send.call_args.args[1]
        self.assertIn(starter, response['themes'])
        self.assertEqual(response['templates']['touring']['id'], 'touring-copy-2')

    def test_import_rejects_foreign_hosts_and_falls_back_on_corrupt_files(self):
        self.request('POST', self.document, host='untrusted.example').send.assert_called_once_with(403, {'error': 'Host rejected'})
        rejected = self.request('POST', self.document, origin='http://other.example')
        rejected.send.assert_called_once_with(403, {'error': 'Origin rejected'})
        for data in (dict(self.document, id='../main'),
                     dict(self.document, layouts={'home': 'python'}),
                     dict(self.document, supports_color_selection='true'),
                     dict(self.document, id='oem')):
            response = self.request('POST', data)
            self.assertEqual(response.send.call_args.args[0], 400)
        self.themes.install_document(self.document)
        (self.themes.folder/'my-garage.json').write_text('invalid')
        self.themes.reload()
        self.assertIs(self.themes.get('my-garage'), OEM)


if __name__ == '__main__':
    unittest.main()
