"""Optional owner-local SIWC flow. The distributed private preview has this route gated."""

import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import uuid
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .inference import API, AUTH, ProviderError, request

PERSONAL_BUILD = False
TOKEN = AUTH + "/api/accounts/oauth/token"
DIRECT = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + DIRECT


def callback_fields(fields, state, selected):
    if not secrets.compare_digest(fields.get("state", ""), state):
        raise ValueError("The browser callback did not match this sign-in attempt.")
    if fields.get("error"):
        raise ValueError("Authorisation declined or cancelled.")
    client = fields.get("client_id", selected)
    if (
        not client
        or client == "dynamic_agent_client"
        or (selected and client != selected)
        or not fields.get("code")
    ):
        raise ValueError("The account registration did not match this sign-in.")
    return client, fields["code"]


def verify_identity(jwt, encoded, client, nonce):
    key_id = jwt.get_unverified_header(encoded).get("kid")
    keys = request(AUTH + "/.well-known/jwks.json")["keys"]
    key = next((k for k in keys if k.get("kid") == key_id and k.get("kty") == "RSA"), None)
    if key is None:
        raise ValueError("Identity signing key unavailable.")
    claims = jwt.decode(
        encoded,
        jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
        algorithms=["RS256"],
        issuer=AUTH,
        audience=client,
        options={"require": ["exp", "iat", "sub", "nonce", "iss", "aud"]},
    )
    if (
        claims["nonce"] != nonce
        or not isinstance(claims["sub"], str)
        or not claims["sub"]
        or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client)
    ):
        raise ValueError("Account identity could not be verified.")
    return claims


class Accounts:
    def __init__(self, directory):
        self.directory = Path(directory)

    @contextmanager
    def store(self):
        if os.name != "posix":
            raise ValueError("Personal account preview requires protected POSIX profile storage.")
        import fcntl

        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid():
            raise ValueError("Choose a private local profile.")
        self.directory.chmod(0o700)
        with (self.directory / "session.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            p = self.directory / "accounts.json"
            data = (
                json.loads(p.read_text())
                if p.exists()
                else dict(host="urn:uuid:" + str(uuid.uuid4()), accounts={})
            )
            yield data
            with tempfile.NamedTemporaryFile("w", dir=self.directory, delete=False) as temp:
                json.dump(data, temp)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp.name, p)

    def labels(self):
        with self.store() as db:
            return [(cid, r.get("email") or "ChatGPT account") for cid, r in db["accounts"].items()]

    def sign_in(self, selected, cancel, open_browser=webbrowser.open):
        if not PERSONAL_BUILD:
            raise ValueError(
                "ChatGPT plan access is pending confirmation for the private distributable."
            )
        try:
            import jwt
            from jwt.algorithms import RSAAlgorithm  # noqa: F401
        except ImportError:
            raise ValueError(
                "Personal sign-in requires PyJWT with cryptography in the QGIS Python environment."
            ) from None
        with self.store() as db:
            old = db["accounts"][selected].copy() if selected else {}
            host = db["host"]
        nonce, state, verifier = (secrets.token_urlsafe(48) for _ in range(3))
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        )
        result = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                qs = parse_qs(parts.query)
                valid = (
                    parts.path == "/auth/callback"
                    and self.headers.get("Host") == address
                    and all(len(v) == 1 for v in qs.values())
                    and qs.get("state") == [state]
                )
                self.send_response(200 if valid else 400)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if valid:
                    result.update({k: v[0] for k, v in qs.items()})
                self.wfile.write(b"Return to GroundSurf Connect to check the result.")

        with HTTPServer(("127.0.0.1", 0), Callback) as listener:
            address = f"127.0.0.1:{listener.server_port}"
            uri = "http://" + address + "/auth/callback"
            params = dict(
                client_id=selected or "dynamic_agent_client",
                scope=SCOPES,
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                code_challenge_method="S256",
                resource=API,
                ext_agent_host_id=host,
                response_type="code",
                redirect_uri=uri,
            )
            if not selected:
                params["agent_name_hint"] = "GroundSurf Connect"
            elif old.get("id_token"):
                params["id_token_hint"] = old["id_token"]
                if DIRECT not in old.get("scopes", []):
                    params["prompt"] = "consent"
            if not open_browser(AUTH + "/api/accounts/authorize?" + urlencode(params)):
                raise ValueError("The system browser could not open.")
            deadline = time.monotonic() + 180
            listener.timeout = 0.3
            while not result and not cancel() and time.monotonic() < deadline:
                listener.handle_request()
        if cancel() or not result:
            raise ValueError("Sign-in cancelled or timed out.")
        client, code = callback_fields(result, state, selected)
        tokens = request(
            TOKEN,
            dict(
                grant_type="authorization_code",
                client_id=client,
                code=code,
                code_verifier=verifier,
                redirect_uri=uri,
                resource=API,
            ),
            form=True,
        )
        claims = verify_identity(jwt, tokens["id_token"], client, nonce)
        record = dict(
            sub=claims["sub"],
            email=claims.get("email") if claims.get("email_verified") is True else "",
            id_token=tokens["id_token"],
            access=tokens.get("access_token", ""),
            refresh=tokens.get("refresh_token", ""),
            expires=time.time() + tokens.get("expires_in", 0),
            scopes=tokens.get("scope", "").split(),
        )
        with self.store() as db:
            previous = db["accounts"].get(client, {})
            if previous and previous.get("sub") != record["sub"]:
                raise ValueError("Sign-in belongs to another identity.")
            if cancel():
                raise ValueError("Sign-in cancelled.")
            db["accounts"][client] = record
        return client

    def access(self, client):
        if not PERSONAL_BUILD:
            raise ValueError("ChatGPT plan access is pending confirmation.")
        error = None
        with self.store() as db:
            r = db["accounts"].get(client, {})
            if DIRECT not in r.get("scopes", []) or not r.get("access"):
                raise ValueError("Continue with ChatGPT and grant plan usage permission.")
            if time.time() + 60 >= r["expires"]:
                if not r.get("refresh"):
                    raise ValueError("Session expired. Continue with ChatGPT again.")
                try:
                    tokens = request(
                        TOKEN,
                        dict(
                            grant_type="refresh_token",
                            refresh_token=r["refresh"],
                            client_id=client,
                            resource=API,
                        ),
                        form=True,
                    )
                    r.update(
                        access=tokens["access_token"],
                        expires=time.time() + tokens["expires_in"],
                        refresh=tokens.get("refresh_token", r["refresh"]),
                    )
                    if "scope" in tokens:
                        r["scopes"] = tokens["scope"].split()
                except ProviderError as exc:
                    if exc.code == "invalid_grant":
                        for k in ("access", "refresh", "id_token"):
                            r.pop(k, None)
                    error = exc
            access = r.get("access") if DIRECT in r.get("scopes", []) else None
        if error:
            raise error
        if not access:
            raise ValueError("Permission to use the ChatGPT plan has expired.")
        return access

    def sign_out(self, client):
        confirmed = True
        with self.store() as db:
            r = db["accounts"][client]
            if r.get("refresh"):
                try:
                    cfg = request(AUTH + "/.well-known/openid-configuration")
                    url = cfg["revocation_endpoint"]
                    if urlsplit(url).scheme != "https" or urlsplit(url).netloc != "auth.openai.com":
                        raise ValueError("Unrecognised revocation endpoint.")
                    request(
                        url,
                        dict(token=r["refresh"], token_type_hint="refresh_token", client_id=client),  # nosec B106
                        form=True,
                    )
                except (OSError, ValueError, KeyError):
                    confirmed = False
            for key in ("access", "refresh", "id_token", "scopes", "expires"):
                r.pop(key, None)
        return (
            "Signed out."
            if confirmed
            else "Signed out locally. Confirm disconnection in ChatGPT Settings."
        )
