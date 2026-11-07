"""A temporary microphone connection must never terminate the launcher."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


class SiriTeardown(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('dbus') and importlib.util.find_spec('gi'),
                         'Requires native Pi D-Bus/GLib libraries')
    def test_capture_bus_close_does_not_exit_running_glib_loop(self):
        # Run in a child: without set_exit_on_disconnect(False), libdbus exits
        # with status 1 and no Python exception when Capture.run closes its bus.
        code = '''
import threading
from unittest.mock import patch
import dbus, dbus.mainloop.glib
from gi.repository import GLib
from hlauncher.audio import Capture
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
main_bus = dbus.SystemBus()
main_bus.set_exit_on_disconnect(False)
loop = GLib.MainLoop()
events = []
capture = Capture(event=lambda **e: events.append(e))
class Manager:
    def GetManagedObjects(self, **kw):
        capture.cancel.set()
        return {}
    def ConnectProfile(self, *a, **kw): pass
def run():
    with patch.object(dbus, 'Interface', return_value=Manager()):
        capture.run()
def start():
    threading.Thread(target=run).start()
    return False
GLib.timeout_add(10, start)
GLib.timeout_add(500, lambda: (loop.quit(), False)[1])
loop.run()
assert any(e['state'] == 'audio_capture_bus_closed' for e in events), events
assert any(e['state'] == 'audio_capture_closed' for e in events), events
print('launcher survived microphone teardown')
'''
        root=Path(__file__).resolve().parents[1]
        env=dict(os.environ,PYTHONPATH=os.pathsep.join((str(root),str(root/'sdk'))))
        result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('launcher survived',result.stdout)
