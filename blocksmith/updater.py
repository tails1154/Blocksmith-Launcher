from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__


REPOSITORY = "tails1154/Blocksmith-Launcher"
API_BASE = f"https://api.github.com/repos/{REPOSITORY}"
USER_AGENT = f"Blocksmith/{__version__} updater"


class UpdateError(RuntimeError):
    pass


@dataclass(slots=True)
class UpdateInfo:
    release_id: int
    version: str
    name: str
    page_url: str
    download_url: str
    checksum_url: str
    asset_name: str
    channel: str


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else (0,)


class GitHubUpdater:
    def __init__(self, current_version: str = __version__) -> None:
        self.current_version = current_version

    @staticmethod
    def platform_asset() -> str:
        machine = platform.machine().lower()
        if machine not in ("x86_64", "amd64"):
            raise UpdateError(f"Automatic updates are not published for {machine} yet.")
        if sys.platform == "win32":
            return "Blocksmith-windows-x86_64.zip"
        raise UpdateError(f"Automatic updates are not supported on {sys.platform}.")

    @staticmethod
    def _json(url: str):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise UpdateError(f"GitHub update check failed (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise UpdateError(f"Could not reach GitHub: {exc}") from exc

    def check(self, channel: str, installed_release_id: int | None = None) -> UpdateInfo | None:
        development = channel.lower() == "development"
        endpoint = "/releases/tags/development" if development else "/releases/latest"
        release = self._json(API_BASE + endpoint)
        if release.get("draft"):
            return None
        if not development and _version_tuple(release.get("tag_name", "")) <= _version_tuple(self.current_version):
            return None

        wanted = self.platform_asset()
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        artifact = assets.get(wanted)
        checksum_names = [
            wanted + ".sha256",
            wanted.removesuffix(".tar.gz").removesuffix(".zip") + ".sha256",
            "SHA256SUMS.txt",
        ]
        checksum = next((assets.get(name) for name in checksum_names if assets.get(name)), None)
        if artifact is None or checksum is None:
            raise UpdateError(f"Release {release.get('tag_name')} has no verified {wanted} build.")
        if development and installed_release_id == int(artifact["id"]):
            return None
        return UpdateInfo(
            # Asset IDs change whenever the rolling development build is
            # replaced, unlike the release ID which remains constant.
            release_id=int(artifact["id"] if development else release["id"]),
            version=release.get("tag_name", "development"),
            name=release.get("name") or release.get("tag_name", "Update"),
            page_url=release.get("html_url", ""),
            download_url=artifact["browser_download_url"],
            checksum_url=checksum["browser_download_url"],
            asset_name=wanted,
            channel="Development" if development else "Stable",
        )

    @staticmethod
    def _download(url: str, progress: Callable[[float], None] | None = None) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                size = int(response.headers.get("Content-Length", 0))
                chunks, downloaded = [], 0
                while chunk := response.read(1024 * 256):
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if progress and size:
                        progress(downloaded / size)
                return b"".join(chunks)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise UpdateError(f"Update download failed: {exc}") from exc

    def download(self, update: UpdateInfo, progress: Callable[[float], None]) -> Path:
        checksum_text = self._download(update.checksum_url).decode("utf-8", "replace")
        expected = None
        for line in checksum_text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and Path(parts[-1].lstrip("*")).name == update.asset_name:
                expected = parts[0].lower()
                break
        if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise UpdateError("The release does not contain a valid checksum for this build.")

        data = self._download(update.download_url, progress)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise UpdateError("Update checksum verification failed. The downloaded file was discarded.")

        destination = Path(tempfile.mkdtemp(prefix="blocksmith-update-"))
        executable_name = "Blocksmith.exe" if sys.platform == "win32" else "Blocksmith"
        output = destination / executable_name
        if update.asset_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                member = next((name for name in archive.namelist() if Path(name).name == executable_name), None)
                if member is None:
                    raise UpdateError("The update archive does not contain Blocksmith.")
                output.write_bytes(archive.read(member))
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                member = next((item for item in archive.getmembers() if Path(item.name).name == executable_name and item.isfile()), None)
                if member is None:
                    raise UpdateError("The update archive does not contain Blocksmith.")
                source = archive.extractfile(member)
                if source is None:
                    raise UpdateError("Could not read the executable from the update archive.")
                output.write_bytes(source.read())
        output.chmod(0o755)
        return output

    @staticmethod
    def can_self_update() -> tuple[bool, str]:
        if sys.platform.startswith("linux"):
            return False, "Automatic updates are disabled on Linux. Update Blocksmith with your package manager."
        if not getattr(sys, "frozen", False):
            return False, "Source checkouts should update with git pull."
        executable = Path(sys.executable).resolve()
        if not os.access(executable.parent, os.W_OK):
            return False, "This installation is managed by the system. Update it with your package manager."
        return True, ""

    @staticmethod
    def apply_and_restart(new_executable: Path) -> None:
        allowed, reason = GitHubUpdater.can_self_update()
        if not allowed:
            raise UpdateError(reason)
        target = Path(sys.executable).resolve()
        pid = os.getpid()
        helper_dir = new_executable.parent
        if sys.platform == "win32":
            helper = helper_dir / "install-update.ps1"
            quote = lambda value: str(value).replace("'", "''")
            helper.write_text(
                f"Wait-Process -Id {pid}\n"
                f"Move-Item -Force -LiteralPath '{quote(new_executable)}' -Destination '{quote(target)}'\n"
                f"Start-Process -FilePath '{quote(target)}'\n"
                "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force\n",
                encoding="utf-8",
            )
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
                creationflags=flags,
                close_fds=True,
            )
        else:
            helper = helper_dir / "install-update.sh"
            helper.write_text(
                "#!/bin/sh\n"
                f"while kill -0 {pid} 2>/dev/null; do sleep 1; done\n"
                + f"mv -f {shlex.quote(str(new_executable))} {shlex.quote(str(target))}\n"
                + f"chmod 755 {shlex.quote(str(target))}\n"
                + "status=$?\n"
                + "rm -f \"$0\"\n"
                + "[ \"$status\" -eq 0 ] || exit \"$status\"\n"
                + f"exec {shlex.quote(str(target))}\n",
                encoding="utf-8",
            )
            helper.chmod(0o755)
            subprocess.Popen([str(helper)], start_new_session=True, close_fds=True)
