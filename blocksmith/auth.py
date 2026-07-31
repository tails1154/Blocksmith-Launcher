from __future__ import annotations

import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import uuid4

from portablemc.auth import AuthDatabase, MicrosoftAuthSession
from portablemc.cli import MICROSOFT_AZURE_APP_ID


class AuthenticationCancelled(RuntimeError):
    pass


class MicrosoftAuthenticator:
    REDIRECT_URI = "https://www.theorozier.fr/portablemc/auth"

    def __init__(self, database_file: Path) -> None:
        self.database = AuthDatabase(database_file)
        self.database.load()

    def saved_accounts(self) -> list[str]:
        # AuthDatabase deliberately keeps its serialization small and stable.
        sessions = getattr(self.database, "sessions", {})
        if isinstance(sessions, dict):
            return sorted(sessions.keys())
        return []

    def get_cached(self, email: str) -> MicrosoftAuthSession | None:
        session = self.database.get(email, MicrosoftAuthSession)
        if session is None:
            return None
        if not session.validate():
            session.refresh()
            self.database.put(email, session)
            self.database.save()
        return session

    def login(
        self,
        email: str,
        status: callable,
        cancelled: threading.Event | None = None,
    ) -> MicrosoftAuthSession:
        cached = self.get_cached(email)
        if cached is not None:
            status(f"Signed in as {cached.username}")
            return cached

        nonce = uuid4().hex
        app_id = MICROSOFT_AZURE_APP_ID
        result: dict[str, str | None] = {"query": None}

        class Server(HTTPServer):
            timeout = 0.5

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *args):
                return

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path in ("", "/"):
                    result["query"] = parsed.query
                    self.send_response(200)
                    body = b"<h2>Signed in.</h2><p>You may close this tab and return to Blocksmith.</p>"
                else:
                    self.send_response(404)
                    body = b"Not found"
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with Server(("127.0.0.1", 0), Handler) as server:
            state = f"port:{server.server_port}"
            params = {
                "client_id": app_id,
                "redirect_uri": self.REDIRECT_URI,
                "response_type": "code id_token",
                "scope": "xboxlive.signin offline_access openid email",
                "login_hint": email,
                "nonce": nonce,
                "state": state,
                "prompt": "login",
                "response_mode": "fragment",
            }
            url = "https://login.live.com/oauth20_authorize.srf?" + urllib.parse.urlencode(params)
            status("Complete sign-in in your browser…")
            if not webbrowser.open(url):
                raise RuntimeError(f"Could not open a browser. Open this URL manually:\n{url}")
            while result["query"] is None:
                if cancelled is not None and cancelled.is_set():
                    raise AuthenticationCancelled("Sign-in cancelled")
                server.handle_request()

        query = urllib.parse.parse_qs(result["query"] or "")
        if "error" in query:
            raise RuntimeError(query.get("error_description", query["error"])[0])
        if "code" not in query or "id_token" not in query:
            raise RuntimeError("Microsoft sign-in did not return the required tokens")
        if not MicrosoftAuthSession.check_token_id(query["id_token"][0], email, nonce):
            raise RuntimeError("Microsoft returned identity data that did not match this sign-in")

        status("Verifying Minecraft ownership…")
        session = MicrosoftAuthSession.authenticate(
            self.database.get_client_id(),
            app_id,
            query["code"][0],
            self.REDIRECT_URI,
        )
        self.database.put(email, session)
        self.database.save()
        status(f"Signed in as {session.username}")
        return session

    def logout(self, email: str) -> None:
        session = self.database.remove(email, MicrosoftAuthSession)
        if session is not None:
            try:
                session.invalidate()
            finally:
                self.database.save()

