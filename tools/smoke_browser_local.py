"""Defensive tests for isolated 127.0.0.1 static browser preview."""
import importlib.util
import pathlib
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

path = pathlib.Path(__file__).resolve().parents[1] / 'groundsurf_geothermal' / 'browser_studio.py'
spec = importlib.util.spec_from_file_location('groundsurf_browser', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BrowserStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        (root / 'index.html').write_text('<html><body>GroundSurf Studio</body></html>')
        (root / 'assets').mkdir()
        (root / 'assets' / 'app.js').write_text('window.groundsurfStudio = true;')
        (root / 'model.json').write_text('{"not": "web accessible"}')
        self.server = module.BrowserStudio(root)
        self.url = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.tmp.cleanup()

    def status(self, address, method='GET', host=None):
        headers = {'Host': host} if host else {}
        try:
            with urlopen(Request(address, headers=headers, method=method), timeout=4) as r:
                return r.status, r.read(), dict(r.headers)
        except HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_static_assets_only(self):
        status, html, headers = self.status(self.url)
        self.assertEqual(status, 200)
        self.assertIn(b'GroundSurf Studio', html)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        status, js, _ = self.status(self.url + 'assets/app.js')
        self.assertEqual(status, 200)
        self.assertIn(b'groundsurfStudio', js)
        status, _, _ = self.status(self.url + 'model.json')
        self.assertEqual(status, 404)

    def test_denied_without_token(self):
        root = self.url.split('/', 3)
        self.assertEqual(self.status(root[0] + '//' + root[2] + '/')[0], 404)
        self.assertEqual(self.status(self.url + '%2e%2e/index.html')[0], 404)

    def test_reject_host_spoof_and_uploads(self):
        self.assertEqual(self.status(self.url, host='attacker.example')[0], 403)
        self.assertEqual(self.status(self.url, method='POST')[0], 405)

    def test_lifecycle(self):
        self.assertEqual(self.server.start(), self.url)
        self.server.stop()
        self.assertIsNone(self.server.url)
        self.server.start()
        self.assertTrue(self.server.url.startswith('http://127.0.0.1:'))


if __name__ == '__main__':
    unittest.main()
