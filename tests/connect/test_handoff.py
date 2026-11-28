import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from groundsurf_geothermal.connect import handoff


class HandoffTests(unittest.TestCase):
    def test_unrecognised_portable_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Path(directory)/"Studio.html"
            f.write_bytes(handoff.MARK)
            self.assertIsNone(handoff.portable([f]))

    def test_desktop_requires_receiver_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root/"studio"
            exe.touch(mode=0o700)
            (root/"dist").mkdir()
            (root/"desktop").mkdir()
            with patch.object(handoff,"desktop_installations",return_value=[(exe,root)]):
                self.assertIsNone(handoff.desktop())
                (root/"dist/index.html").write_bytes(handoff.MARK)
                self.assertIsNone(handoff.desktop())
                (root/"desktop/main.cjs").write_text("'--groundsurf-transfer'")
                self.assertEqual(handoff.desktop(),exe)

    def test_links_and_size_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            f=root/"boreholes.geojson"
            original=root/"original"
            original.write_text("{}")
            f.symlink_to(original)
            with self.assertRaises(ValueError):
                handoff.prepare(root,True)
            f.unlink()
            with f.open("wb") as stream:
                stream.truncate(8*1024**2+1)
            with self.assertRaises(ValueError):
                handoff.prepare(root,True)

    def test_installer_matches_system_and_trusted_origin(self):
        a='<a href="https://example.com/windows-x64.exe">download</a>'
        self.assertIsNone(handoff.installer_link(a,"Windows","AMD64"))
        a='<a href="/downloads/Studio-Windows-x64.exe">download</a>'
        self.assertEqual(handoff.installer_link(a,"Windows","AMD64"),
                         "https://studio.groundsurf.net/downloads/Studio-Windows-x64.exe")
        self.assertIsNone(handoff.installer_link(a,"Darwin","arm64"))
