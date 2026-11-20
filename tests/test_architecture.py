"""Exercise plugin boundaries without Bluetooth, a dongle or /dev/fb0."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hlauncher.catalog import Manifest, discover
from hlauncher.config import Preferences
from hlauncher.launcher import Launcher
from hlauncher.audio import AudioBroker
from hlauncher.plugin_host import Worker, PluginHost
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from hlauncher.plugins import install


class Display:
    w, h = 720, 480

    def open(self):
        pass

    def close(self):
        pass

    def image(self, image):
        self.last = image.copy()

    def blit(self, frame):
        self.frame = frame


# UI tests unrelated to the lock run with a parked radio.
parked_radio = patch.object(ProtocolDiagnostics, "parked_for_setup", lambda self: True)


@parked_radio
class Architecture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.carplay = Manifest.load(ROOT / "plugins/carplay", bundled=True)

    def tearDown(self):
        self.temp.cleanup()

    def preferences(self):
        prefs = Preferences(self.root / "settings.json")
        prefs.accept_safety_notice()
        return prefs

    def test_preferences_survive_restart_and_disable_clears_default(self):
        prefs = self.preferences()
        self.assertTrue(prefs.enabled(self.carplay))
        prefs.set_default("carplay")
        prefs.set_enabled(self.carplay, False)
        loaded = self.preferences()
        self.assertFalse(loaded.enabled(self.carplay))
        self.assertIsNone(loaded.data["default_plugin"])
        with patch.object(loaded, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                loaded.set_enabled(self.carplay, True)
        self.assertFalse(loaded.enabled(self.carplay))
        loaded.path.write_text("broken")
        self.assertIsNone(self.preferences().data["default_plugin"])
        self.assertEqual(list(self.root.glob(".settings-*")), [])

    def test_manifest_rejects_bad_data_and_escaping_entrypoint(self):
        folder = self.root / "bad"
        folder.mkdir()
        for data in (
            [],
            {"api_version": 1, "id": 123},
            {
                "api_version": 1,
                "id": "bad",
                "name": "Bad",
                "entrypoint": ["python3", "../escape.py"],
            },
        ):
            (folder / "plugin.json").write_text(json.dumps(data))
            self.assertEqual(discover(roots=[(self.root, False)]), {})
        with self.assertRaises(ValueError):
            install(
                str(ROOT / "examples/hello"), self.root / "installed", subdir="../.."
            )
        target = install(str(ROOT / "examples/hello"), self.root / "installed")
        hello = Manifest.load(target)
        self.assertFalse(self.preferences().enabled(hello))
        with self.assertRaises(ValueError):
            install(str(ROOT / "plugins/carplay"), self.root / "installed")
        with self.assertRaises(ValueError):
            install(str(ROOT / "examples/hello"), self.root / "installed")

    def test_launcher_grid_settings_and_default(self):
        prefs = self.preferences()
        fb = Display()
        ui = Launcher(
            framebuffer=fb, preferences=prefs, manifests={"carplay": self.carplay}
        )
        try:
            self.assertEqual(ui.mode, "home")
            self.assertEqual(len(ui.actions), 2)
            carplay_box, _ = ui.actions[0]
            settings_box, callback = ui.actions[1]
            self.assertGreater(settings_box[0], carplay_box[0])
            callback()
            self.assertEqual(ui.mode, "settings")
            ui.cycle_default()
            self.assertEqual(prefs.data["default_plugin"], "carplay")
            ui.toggle_plugin("carplay")
            self.assertIsNone(prefs.data["default_plugin"])
            ui.home()
            self.assertEqual(len(ui.actions), 1)
            ui.toggle_plugin("carplay")
            prefs.set_default("carplay")
            prefs.data['setup_complete'] = True
            prefs.save()
            with patch.object(ui, "open_plugin") as opened:
                self.assertTrue(ui.launch("com.honda.hondalink.launcher"))
                ui.tick()
                opened.assert_called_once_with("carplay", projection_engine=True)
                ui.home()
                ui.tick()
                self.assertEqual(opened.call_count, 1)
            self.assertFalse(ui.launch("unknown"))
        finally:
            ui.close()

    def test_home_pagination_keeps_settings_and_plugin_callbacks(self):
        from dataclasses import replace
        manifests={f'app{i}':replace(self.carplay,id=f'app{i}',name=f'App {i}') for i in range(7)}
        display=Display()
        ui=Launcher(framebuffer=display,preferences=self.preferences(),manifests=manifests)
        try:
            with patch.object(ui,'open_plugin') as opened:
                ui.draw()
                self.assertEqual(len(ui.actions),8)  # six apps and paging
                for index,(a,_) in enumerate(ui.actions):
                    for b,_ in ui.actions[index+1:]:
                        self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])
                ui.actions[0][1]()
                opened.assert_called_with('app0')
                ui.actions[-1][1]()
                self.assertEqual(ui.page,1)
                self.assertEqual(len(ui.actions),4)
                ui.actions[0][1]()
                opened.assert_called_with('app6')
                ui.actions[1][1]()
                self.assertEqual(ui.mode,'settings')
                ui.home();ui.change_page(-1)
                self.assertEqual(ui.page,0)
            for size in ((640,480),(800,480)):
                from hlauncher.ui.home import Entry,render
                frame=render([[Entry('Settings','settings',lambda:None)]],size=size)
                self.assertEqual(frame.image.size,size)
                for (x,y,right,bottom),_ in frame.actions:
                    self.assertTrue(0<=x<right<size[0] and 0<=y<bottom<size[1])
        finally:ui.close()

    def test_crashed_plugin_returns_home_without_waiting(self):
        home = []
        host = PluginHost(
            {"carplay": self.carplay},
            16,
            16,
            lambda **kw: None,
            home.append,
            AudioBroker(lambda **kw: None),
        )
        worker = type(
            "Failed",
            (),
            {
                "proc": type("Process", (), {"poll": lambda _: 1})(),
                "manifest": self.carplay,
                "close": lambda _: None,
            },
        )()
        host.workers["carplay"] = worker
        host.active = "carplay"
        began = time.monotonic()
        host.tick()
        self.assertLess(time.monotonic() - began, 0.1)
        self.assertTrue(home)
        self.assertIsNone(host.active)

    def test_worker_frame_lease_and_return_message(self):
        from hlauncher import plugin_host

        manifest = Manifest.load(ROOT / "examples/hello", bundled=True)
        with patch.object(plugin_host, "LOG_DIR", self.root / "logs"):
            worker = Worker(manifest, 32, 24, lambda **kw: None)
        try:
            worker.active = True
            worker.send(type="host.activate")
            frame = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and frame is None:
                worker.drain()
                messages = worker.read()
                frame = worker.take_frame()
                time.sleep(0.01)
            self.assertIsNotNone(frame)
            self.assertEqual(len(frame), 32 * 24 * 2)
            self.assertEqual(worker.inflight, set())
            worker.send(type="touch", contacts=[{"action": "down"}])
            deadline = time.monotonic() + 2
            returned = False
            while time.monotonic() < deadline and not returned:
                worker.drain()
                returned = any(m["type"] == "launcher.home" for m in worker.read())
                time.sleep(0.01)
            self.assertTrue(returned)
        finally:
            worker.close()

    def test_old_capture_cannot_send_pcm_to_new_plugin(self):
        class FakeWorker:
            manifest = type(
                "Manifest", (), {"id": "hello", "capabilities": {"audio.status"}}
            )()
            active = True

            def __init__(self):
                self.messages = []

            def send(self, **message):
                self.messages.append(message)
                return True

            def send_raw(self, raw):
                self.messages.append(raw)
                return True

        broker = AudioBroker(lambda **kw: None)
        worker = FakeWorker()
        broker.owner = "hello"
        broker.worker = worker
        broker.generation = 3
        broker.pcm(2, b"\0\0", 8000, 1)
        self.assertEqual(worker.messages, [])
        broker.request(worker, {"type": "audio.capture.start"}, active=True)
        self.assertEqual(worker.messages[-1]["type"], "audio.error")
        self.assertIsNone(broker.capture)
        broker.request(worker, {"type": "audio.status"}, active=True)
        self.assertTrue(worker.messages[-1]["playback_supported"])
        self.assertEqual(worker.messages[-1]["playback_route"], "hdmi")

    def test_video_status_does_not_draw_over_live_frame(self):
        ui = Launcher(
            framebuffer=Display(),
            preferences=self.preferences(),
            manifests={"carplay": self.carplay},
        )
        try:
            worker = type("Worker", (), {"video_available": True})()
            ui.mode = "plugin"
            ui.has_frame = True
            ui.host.active = "carplay"
            ui.host.workers["carplay"] = worker
            with patch.object(ui.host, "tick"), patch.object(
                ui.host, "frame", return_value=None
            ), patch.object(
                ui.host, "status", return_value="CarPlay connected"
            ), patch.object(
                ui, "draw"
            ) as draw:
                ui.tick()
                draw.assert_not_called()
                self.assertTrue(ui.has_frame)
                worker.video_available = False
                ui.last_status = None
                ui.tick()
                draw.assert_called_once()
                self.assertFalse(ui.has_frame)
        finally:
            ui.host.workers.clear()
            ui.host.active = None
            ui.close()

    def test_projection_child_pages_have_working_home_tab(self):
        manifests={source:Manifest.load(ROOT/'plugins'/source,bundled=True)
                   for source in ('carplay','android-auto')}
        ui=Launcher(framebuffer=Display(),preferences=self.preferences(),manifests=manifests)
        try:
            for source in manifests:
                ui.mode='plugin';ui.host.active=source;ui.has_frame=False
                with patch.object(ui.host,'status',return_value='Waiting for phone'):
                    ui.draw()
                self.assertIn(((0,0,80,52), ui.home), ui.actions)
                self.assertIn(((24,408,80,464), ui.projection_settings_page), ui.actions)
                ui.update({'contacts':[{'slot':0,'action':'down','has_position':True,
                    'x_raw':round(32*32767/719),'y_raw':round(26*32767/479)}]})
                ui.update({'contacts':[{'slot':0,'action':'up','has_position':False}]})
                self.assertEqual(ui.mode,'home')
                self.assertIsNone(ui.host.active)
        finally:ui.close()

    def test_settings_categories_preserve_navigation_and_default_selection(self):
        ui=Launcher(framebuffer=Display(),preferences=self.preferences(),manifests={'carplay':self.carplay})
        try:
            ui.settings()
            self.assertEqual([action for _, action in ui.actions], [ui.home,
                ui.plugin_settings, ui.about_settings, ui.audio_coming_soon,
                ui.startup_settings, ui.appearance_settings, ui.system_settings])
            ui.actions[4][1]()
            self.assertEqual(ui.mode,'startup_settings')
            ui.actions[1][1]()
            self.assertEqual(ui.prefs.data['default_plugin'],'carplay')
            self.assertEqual(ui.mode,'startup_settings')
            ui.settings();ui.actions[5][1]()
            self.assertEqual(ui.mode,'appearance_settings')
            ui.actions[1][1]()
            self.assertEqual(ui.mode,'tile_colors')
            ui.actions[0][1]()
            self.assertEqual(ui.mode,'appearance_settings')
            ui.settings();ui.actions[1][1]()
            self.assertEqual(ui.mode,'plugins_settings')
            ui.settings();ui.actions[6][1]()
            self.assertEqual(ui.mode,'system_settings')
            ui.settings()
            saved = ui.prefs.path.read_bytes()
            about_box, open_about = ui.actions[2]
            self.assertEqual(about_box, (368,144,696,208))
            open_about()
            self.assertEqual(ui.mode, 'about_settings')
            ui.actions[1][1]()
            self.assertEqual(ui.mode, 'legal_info')
            ui.actions[1][1]()
            self.assertEqual(ui.mode, 'safety_agreement')
            ui.actions[0][1]()
            self.assertEqual(ui.mode, 'legal_info')
            ui.actions[0][1]()
            self.assertEqual(ui.mode, 'about_settings')
            ui.actions[0][1]()
            self.assertEqual(ui.mode, 'settings')
            self.assertEqual(ui.prefs.path.read_bytes(), saved)
            ui.settings();ui.actions[0][1]()
            self.assertEqual(ui.mode,'home')
        finally:ui.close()

if __name__ == "__main__":
    unittest.main()
