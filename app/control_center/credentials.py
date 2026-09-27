"""Per-user encrypted credentials and an explicit, loopback MusicKit consent flow.

Neither this module nor the authorization page logs keys or tokens. Creating an
AuthServer does not open a browser or contact Apple; the user presses Authorize.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import re
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .paths import credential_store_file


class CredentialError(RuntimeError):
    pass


# settings.apple.consent (CONTROL_CENTER_V5.md sections 14.2 and 15.3; CL section 4.5): the app
# can now mark songs as Favorites (the Like), so the page no longer promises it does not
# modify the library. Plain text (no markup); shown at the next sign-in.
CONSENT_TEXT = ("Allow Desk Dial to read your Apple Music library and to mark songs as Favorites "
                "when you press Like. A Favorite can add the song to your library.")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise CredentialError("Encrypted credential storage requires Windows DPAPI.")
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(_Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(_Blob)]
        # UI_FORBIDDEN, deliberately without LOCAL_MACHINE: only this user can read it.
        args = (ctypes.byref(source), "Nano_D++ MusicKit", None, None, None, 1,
                ctypes.byref(result))
    function.restype = wintypes.BOOL
    if not function(*args):
        raise CredentialError("Windows could not unlock these credentials." if decrypt
                              else "Windows could not encrypt the credentials.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


class CredentialStore:
    MAGIC = b"NANOD-CREDENTIALS-1\n"

    def __init__(self, path: str | Path | None = None):
        # Default: %LOCALAPPDATA%\DeskDial\credentials.bin (control_center.paths). The file format and its
        # MAGIC header stay as they are (rename-desk-dial.md H10): old and new builds share them.
        self.path = Path(path) if path else credential_store_file()

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            encoded = self.path.read_bytes()
            if len(encoded) > 2_000_000 or not encoded.startswith(self.MAGIC):
                raise ValueError()
            result = json.loads(_dpapi(encoded[len(self.MAGIC):], decrypt=True))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("The encrypted credential file could not be read.") from None

    def save(self, credentials: dict) -> None:
        if not isinstance(credentials, dict):
            raise CredentialError("Credentials must be a mapping.")
        encoded = self.MAGIC + _dpapi(json.dumps(credentials).encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".credentials-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            raise CredentialError("The encrypted credential file could not be saved.") from None
        finally:
            if temporary and temporary.exists():
                temporary.unlink()


class MusicKitCredentials:
    @staticmethod
    def from_key_file(team_id: str, key_id: str, path: str | Path) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9]{10}", team_id.strip()) or not re.fullmatch(r"[A-Za-z0-9]{10}", key_id.strip()):
            raise CredentialError("Enter the 10-character Apple Team ID and Key ID.")
        try:
            key_path = Path(path)
            if not key_path.is_file() or key_path.stat().st_size > 16_384:
                raise ValueError()
            key = key_path.read_text(encoding="utf-8")
            if "-----BEGIN PRIVATE KEY-----" not in key:
                raise ValueError()
        except Exception:
            raise CredentialError("Choose the MusicKit .p8 private key file.") from None
        result = {"team_id": team_id.strip(), "key_id": key_id.strip(), "private_key": key}
        developer_token(result)  # Validate the key locally; no network request.
        return result


def developer_token(credentials: dict, *, origin: str | None = None) -> str:
    if credentials.get("private_key"):
        try:
            import jwt
        except ImportError:
            raise CredentialError("Install the control-center dependencies to enable MusicKit.") from None
        now = int(time.time())
        claims = {"iss": credentials["team_id"], "iat": now - 30, "exp": now + 3600}
        if origin:
            claims["origin"] = [origin]
        try:
            return jwt.encode(claims, credentials["private_key"], algorithm="ES256",
                              headers={"kid": credentials["key_id"]})
        except Exception:
            raise CredentialError("The MusicKit signing key or identifiers are invalid.") from None
    token = credentials.get("developer_token")
    if not isinstance(token, str) or not token:
        raise CredentialError("MusicKit developer credentials have not been configured.")
    return token


class AuthServer:
    """One-use, nonce-protected consent receiver bound only to 127.0.0.1.

    ``events`` contains only status, never tokens. ``on_token`` receives the new
    credential mapping and should save it via CredentialStore. Call stop() when
    the settings window closes. start() returns a URL for a normal browser.
    """
    def __init__(self, credentials: dict, on_token=None):
        self.credentials = dict(credentials)
        self.on_token = on_token
        self.events = queue.Queue()
        self._server = None
        self._thread = None
        self._nonce = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._complete = False
        self._expires = time.monotonic() + 900

    def start(self) -> str:
        if self._server:
            return self.url
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *args):
                pass

            def send(self, code, body, content_type="application/json"):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(data)

            def valid_host(self):
                return self.headers.get("Host") == owner.origin.removeprefix("http://")

            def do_GET(self):
                if not self.valid_host() or self.path != "/" or time.monotonic() > owner._expires:
                    self.send(404, "{}")
                    return
                self.send(200, owner._page, "text/html")

            def do_POST(self):
                if (not self.valid_host() or self.path != "/token" or
                        self.headers.get("Origin") != owner.origin or
                        not secrets.compare_digest(self.headers.get("X-NanoD-Nonce", ""), owner._nonce) or
                        time.monotonic() > owner._expires):
                    self.send(403, '{"error":"Authorization session is invalid or expired."}')
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 1 <= length <= 32768:
                        raise ValueError()
                    token = json.loads(self.rfile.read(length)).get("token")
                    if not isinstance(token, str) or not 1 <= len(token) <= 16384 or any(ord(c) < 32 for c in token):
                        raise ValueError()
                except Exception:
                    self.send(400, '{"error":"Invalid authorization response."}')
                    return
                with owner._lock:
                    if owner._complete:
                        self.send(409, '{"error":"Authorization is already complete."}')
                        return
                    updated = dict(owner.credentials, music_user_token=token)
                    try:
                        if owner.on_token:
                            owner.on_token(updated)
                    except Exception:
                        owner.events.put({"event": "error", "message": "Authorized, but credentials could not be saved."})
                        self.send(500, '{"error":"Could not save credentials. Return to the companion app."}')
                        return
                    owner.credentials = updated
                    owner._complete = True
                    owner.events.put({"event": "authorized"})
                    self.send(200, '{"ok":true}')

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self._server.server_port}"
        self.url = self.origin + "/"
        try:
            token = developer_token(self.credentials, origin=self.origin)
        except Exception:
            self._server.server_close()
            self._server = None
            raise
        payload = json.dumps({"token": token, "nonce": self._nonce}).replace("<", "\\u003c")
        self._page = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Connect Apple Music · Desk Dial</title><style>body{font:18px system-ui;max-width:36rem;margin:10vh auto;padding:24px;background:#111820;color:#eef4f8}button{font:inherit;padding:14px 22px;border:0;border-radius:10px;background:#80cfaa;color:#13251e}p{line-height:1.6}</style>
<h1>Connect Apple Music</h1><p>""" + CONSENT_TEXT + """</p>
<button id="authorize" disabled>Loading Apple Music…</button><p id="status" role="status"></p>
<script>const config=""" + payload + """;
document.addEventListener('musickitloaded',async()=>{try{await MusicKit.configure({developerToken:config.token,app:{name:'Desk Dial',build:'1.0'}});const b=document.getElementById('authorize');b.disabled=false;b.textContent='Authorize Apple Music';b.onclick=async()=>{b.disabled=true;try{const token=await MusicKit.getInstance().authorize();const r=await fetch('/token',{method:'POST',headers:{'Content-Type':'application/json','X-NanoD-Nonce':config.nonce},body:JSON.stringify({token})});if(!r.ok)throw new Error();document.getElementById('status').textContent='Connected. You can close this tab and return to the knob companion.';}catch(e){document.getElementById('status').textContent='Authorization did not finish. Try again or return to the companion app.';b.disabled=false;}};}catch(e){document.getElementById('status').textContent='Apple Music could not initialize. Check your MusicKit setup in the companion app.';}});
</script><script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js" onerror="document.getElementById('status').textContent='Apple Music could not load. Check your connection and retry.'"></script>"""
        self._thread = threading.Thread(target=self._server.serve_forever, name="MusicKit authorization", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            if self._thread:
                self._thread.join(timeout=2)
