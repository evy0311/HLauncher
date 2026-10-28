"""Regression tests for contact lifetimes and offscreen presentation."""

import ctypes
import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "carplay_input", ROOT / "plugins/carplay/input.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from hlauncher.touch import decode_touch, for_viewport
from hlauncher.plugin_host import PluginHost
from hlauncher.audio import AudioBroker
from hlauncher.drm import KMSDisplay, CreateDumb, MapDumb, Mode, Crtc


def contact(slot, action, x=0.5, y=0.5):
    return {
        "slot": slot,
        "action": action,
        "has_position": action in ("down", "move"),
        "x_raw": round(x * 32767),
        "y_raw": round(y * 32767),
    }


class InputDisplay(unittest.TestCase):
    def test_two_contacts_reach_plugin_with_viewport(self):
        raw = (
            bytes.fromhex("00001002")
            + bytes([1])
            + int(4000).to_bytes(2, "big")
            + int(8000).to_bytes(2, "big")
            + bytes([2])
            + int(24000).to_bytes(2, "big")
            + int(16000).to_bytes(2, "big")
        )
        touch = for_viewport(decode_touch(raw), 720, 480)
        host = PluginHost(
            {},
            720,
            480,
            lambda **kw: None,
            lambda *a: None,
            AudioBroker(lambda **kw: None),
        )
        worker = Mock()
        worker.manifest.capabilities = {"touch"}
        worker.send.return_value = True
        host.active = "test"
        host.workers["test"] = worker
        host.touch(touch)
        sent = worker.send.call_args.kwargs
        self.assertEqual(sent["reported_contacts"], 2)
        self.assertEqual([c["id"] for c in sent["contacts"]], [0, 1])
        self.assertEqual(sent["contacts"][1]["x_raw"], 24000)
        self.assertAlmostEqual(sent["contacts"][1]["x"], 24000 / 32767)
        self.assertEqual(sent["width"], 720)

    def test_single_to_pinch_and_one_finger_release_preserves_ids(self):
        r = module.TouchRouter()
        one = r.feed({"contacts": [contact(0, "down", 0.2, 0.5)]})
        self.assertEqual(one[0]["action"], 14)
        two = r.feed(
            {"contacts": [contact(0, "move", 0.2, 0.5), contact(1, "down", 0.8, 0.5)]}
        )
        self.assertEqual(two[0]["action"], 16)
        self.assertEqual([c["action"] for c in two[1]["touches"]], [1, 1])
        moved = r.feed(
            {"contacts": [contact(0, "move", 0.1, 0.5), contact(1, "move", 0.9, 0.5)]}
        )
        self.assertTrue(moved[0]["_motion"])
        self.assertEqual([c["action"] for c in moved[0]["touches"]], [2, 2])
        lifted = r.feed({"contacts": [contact(0, "up"), contact(1, "move", 0.95, 0.5)]})
        self.assertEqual([c["action"] for c in lifted[0]["touches"]], [0, 2])
        self.assertFalse(lifted[0]["_motion"])
        self.assertAlmostEqual(lifted[0]["touches"][0]["x"], 0.1, places=4)
        cancel = r.cancel()
        self.assertEqual([c["action"] for c in cancel[0]["touches"]], [0, 0])
        self.assertEqual(r.cancel(), [])
        self.assertEqual(r.feed({"contacts": [contact(1, "down")]})[0]["action"], 14)

    def test_zero_contact_packet_releases_single(self):
        r = module.TouchRouter()
        r.feed({"contacts": [contact(0, "down")]})
        self.assertEqual(r.feed({"contacts": []})[0]["action"], 16)
        self.assertEqual(r.feed({"contacts": []}), [])

    def test_drm_abi_sizes(self):
        self.assertEqual(ctypes.sizeof(Mode), 68)
        self.assertEqual(ctypes.sizeof(Crtc), 100)
        self.assertEqual(ctypes.sizeof(CreateDumb), 32)
        self.assertEqual(ctypes.sizeof(MapDumb), 16)

    def test_scanout_buffers_are_not_overwritten_while_flip_pending(self):
        display = KMSDisplay.__new__(KMSDisplay)
        display.w, display.h = 2, 1
        display.frames = display.dropped = 0
        display.pending = None
        display.error = None
        display.stop = threading.Event()
        display.condition = threading.Condition()
        display.event = Mock()
        display.cleanup = Mock()
        display.fd = 9
        display.original = Mock(crtc_id=100)
        display.buffers = [
            {"memory": bytearray(4), "pitch": 4, "fb": 10},
            {"memory": bytearray(4), "pitch": 4, "fb": 11},
        ]
        flips = []
        queued = threading.Event()
        release = threading.Event()

        def flip(fd, crtc, fb, flags, data):
            self.assertEqual(flags, 1)
            flips.append(fb)
            queued.set()
            return 0

        def wait_flip():
            release.wait(2)
            release.clear()
            return not display.stop.is_set()

        display.lib = Mock()
        display.lib.drmModePageFlip.side_effect = flip
        display.wait_flip = wait_flip
        thread = threading.Thread(target=display.run, daemon=True)
        thread.start()
        try:
            display.present(b"AAAA")
            self.assertTrue(queued.wait(1))
            queued.clear()
            display.present(b"BBBB")
            display.present(b"CCCC")
            self.assertEqual(display.buffers[0]["memory"], b"\0" * 4)
            self.assertEqual(display.buffers[1]["memory"], b"AAAA")
            self.assertEqual(flips, [11])
            release.set()
            self.assertTrue(queued.wait(1))
            self.assertEqual(display.buffers[0]["memory"], b"CCCC")
            self.assertEqual(display.buffers[1]["memory"], b"AAAA")
            self.assertEqual(flips, [11, 10])
            self.assertEqual(display.dropped, 1)
        finally:
            display.stop.set()
            release.set()
            with display.condition:
                display.condition.notify_all()
            thread.join(2)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
