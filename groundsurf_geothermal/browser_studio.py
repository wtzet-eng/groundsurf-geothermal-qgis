"""Local-only static browser preview for Studio by GroundSurf.

No project files are served. Browser file chooser reads explicitly selected
VTK output files. This is an experimental bridge, not a QGIS plugin release.
"""
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class BrowserStudio:
    def __init__(self, assets):
        self.assets = Path(assets).resolve()
        self._token = secrets.token_urlsafe(24)
        self._server = None
        self._thread = None

    def start(self):
        if self._server:
            return self.url
        if not (self.assets / 'index.html').is_file():
            raise ValueError('Bundled Studio web files are missing. Build the experimental preview first.')
        owner = self

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send(self, status, body, content_type='text/plain; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy',
                                 "default-src 'self'; script-src 'self'; "
                                 "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                                 "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                                 "base-uri 'self'")
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                expected_host = '127.0.0.1:' + str(self.server.server_port)
                if self.headers.get('Host') != expected_host:
                    return self._send(403, b'Local host only')
                prefix = '/' + owner._token + '/'
                route = urlsplit(self.path).path
                if not route.startswith(prefix):
                    return self._send(404, b'Not found')
                relative = unquote(route[len(prefix):])
                if not relative:
                    relative = 'index.html'
                # Reject traversal, absolute paths, backslashes and encoded slashes.
                components = relative.split('/')
                if ('\\' in relative or any(x in ('', '.', '..') for x in components)
                        or '\x00' in relative):
                    return self._send(404, b'Not found')
                original = owner.assets / relative
                if original.is_symlink() or any(parent.is_symlink() for parent in
                                               original.parents if parent != owner.assets):
                    return self._send(404, b'Not found')
                target = original.resolve()
                if owner.assets not in target.parents or not target.is_file():
                    return self._send(404, b'Not found')
                allowed = ('.html', '.js', '.css', '.png', '.jpg', '.jpeg',
                           '.webp', '.svg', '.woff', '.woff2', '.ico', '.wasm')
                if target.suffix.lower() not in allowed:
                    return self._send(404, b'Not found')
                if target.stat().st_size > 12 * 1024 * 1024:
                    return self._send(413, b'Asset exceeds browser budget')
                data = target.read_bytes()
                typ = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                if target.suffix == '.js':
                    typ = 'text/javascript'
                if typ.startswith('text/') or target.suffix in ('.js', '.svg'):
                    typ += '; charset=utf-8'
                return self._send(200, data, typ)

            def do_POST(self):
                return self._send(405, b'Only static files may be served')

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), RequestHandler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name='GroundSurfStudioLocalBrowser')
        self._thread.start()
        return self.url

    @property
    def url(self):
        if self._server:
            return 'http://127.0.0.1:%d/%s/' % (
                self._server.server_port, self._token)
        return None

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            self._server = None
            self._thread = None
