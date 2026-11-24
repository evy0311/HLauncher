import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "image_downloads_badge",
    Path(__file__).resolve().parents[1] / "scripts/image_downloads_badge.py",
)
badge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(badge)


class ImageDownloadsBadgeTests(unittest.TestCase):
    def test_only_images_from_published_releases_are_counted(self):
        responses = {
            "/repos/test/repo/releases": [
                {"id": 1, "draft": False, "prerelease": False},
                {"id": 2, "draft": False, "prerelease": True},
                {"id": 3, "draft": True},
            ],
            "/repos/test/repo/releases/1/assets": [
                {"name": "HLauncher-v1.img", "download_count": 2},
                {"name": "HLauncher-v1.img.xz", "download_count": 3},
                {"name": "SHA256SUMS", "download_count": 100},
                {"name": "HLauncher.img.xz.sig", "download_count": 100},
                {"name": "update.hlu", "download_count": 100},
                {"name": "source.tar.gz", "download_count": 100},
            ],
            "/repos/test/repo/releases/2/assets": [
                {"name": "HLauncher-v2.IMG.XZ", "download_count": 4},
            ],
        }
        with patch.object(badge, "api_items", side_effect=lambda path, token: responses[path]):
            self.assertEqual(badge.image_downloads("test/repo", "token"), 9)

    def test_api_reads_beyond_first_page(self):
        first = [{"id": n} for n in range(100)]
        last = [{"id": 100}]
        with patch.object(badge, "urlopen", side_effect=[
            io.BytesIO(json.dumps(first).encode()),
            io.BytesIO(json.dumps(last).encode()),
        ]) as fetch:
            self.assertEqual(list(badge.api_items("/test", "token")), first + last)
        self.assertTrue(fetch.call_args_list[1].args[0].full_url.endswith("page=2"))


if __name__ == "__main__":
    unittest.main()
