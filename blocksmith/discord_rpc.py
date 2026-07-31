from __future__ import annotations

import queue
import threading
import time
from typing import Callable

DEFAULT_CLIENT_ID = "1532827104994005083"


class DiscordRPC:
    """Non-blocking Discord Rich Presence connection for the desktop app."""

    def __init__(
        self,
        client_id: str = DEFAULT_CLIENT_ID,
        enabled: bool = True,
        status: Callable[[str], None] | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.enabled = enabled and self.client_id.isdigit()
        self._commands: queue.Queue[dict | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._status = status or (lambda _message: None)

    def configure(self, client_id: str, enabled: bool) -> None:
        self.close()
        self._commands = queue.Queue()
        self._thread = None
        self.client_id = client_id.strip()
        self.enabled = enabled and self.client_id.isdigit()
        if self.enabled:
            self.update("In the launcher", "Choosing a profile")

    def update(self, details: str, state: str, *, playing: bool = False) -> None:
        if not self.enabled:
            return
        payload = {
            "details": details[:128],
            "state": state[:128],
            "large_text": "Blocksmith Launcher",
        }
        if playing:
            payload["start"] = int(time.time())
        self._commands.put(payload)
        if self._thread is None or not self._thread.is_alive():
            commands = self._commands
            client_id = self.client_id
            status = self._status
            self._thread = threading.Thread(
                target=self._worker, args=(commands, client_id, status), daemon=True, name="discord-rpc"
            )
            self._thread.start()

    @staticmethod
    def _worker(commands: queue.Queue, client_id: str, status: Callable[[str], None]) -> None:
        rpc = None
        try:
            from pypresence import Presence

            rpc = Presence(client_id)
            rpc.connect()
            status("Connected to Discord.")
            while True:
                payload = commands.get()
                if payload is None:
                    break
                # Collapse queued state changes so Discord receives the newest.
                stop_after_update = False
                while not commands.empty():
                    newer = commands.get_nowait()
                    if newer is None:
                        stop_after_update = True
                        break
                    payload = newer
                rpc.update(**payload)
                if stop_after_update:
                    break
        except ModuleNotFoundError:
            status("Discord RPC module is missing. Reinstall Blocksmith or run: pip install pypresence")
        except Exception as exc:
            # Discord being closed or IPC being unavailable must never block play.
            status(f"Discord is unavailable: {exc}")
        finally:
            if rpc is not None:
                try:
                    rpc.close()
                except Exception:
                    pass

    def close(self) -> None:
        self.enabled = False
        self._commands.put(None)
