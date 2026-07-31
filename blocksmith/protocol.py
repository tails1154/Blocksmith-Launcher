from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


SCHEME = "blocksmith"
PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InstallRequest:
    provider: str
    project_id: str


def install_uri(project_id: str, provider: str = "modrinth") -> str:
    if provider != "modrinth" or not PROJECT_ID.fullmatch(str(project_id)):
        raise ProtocolError("Invalid mod installation link")
    return f"{SCHEME}://install/{provider}/{quote(str(project_id), safe='')}"


def parse_uri(value: str) -> InstallRequest:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() != SCHEME or parsed.netloc.lower() != "install":
        raise ProtocolError("This is not a Blocksmith installation link")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0].lower() != "modrinth":
        raise ProtocolError("Only Modrinth mod links are currently supported")
    project_id = parts[1]
    if not PROJECT_ID.fullmatch(project_id):
        raise ProtocolError("The link contains an invalid Modrinth project ID")
    return InstallRequest("modrinth", project_id)


def _launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "run.py")]


def _desktop_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def register_protocol() -> str:
    """Register blocksmith:// for the current user and return a status message."""
    command = _launch_command()
    if sys.platform == "win32":
        import winreg

        root = rf"Software\Classes\{SCHEME}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:Blocksmith Mod Installer")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root + r"\DefaultIcon") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command[0] + ",0")
        invocation = subprocess.list2cmdline([*command, "%1"])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root + r"\shell\open\command") as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, invocation)
        return "blocksmith:// links are registered for this Windows account."

    if sys.platform.startswith("linux"):
        applications = Path.home() / ".local" / "share" / "applications"
        applications.mkdir(parents=True, exist_ok=True)
        desktop = applications / "blocksmith-url.desktop"
        invocation = " ".join(_desktop_quote(part) for part in command) + " %u"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Blocksmith Mod Installer\n"
            "Comment=Install a Modrinth mod with Blocksmith\n"
            f"Exec={invocation}\n"
            "Icon=blocksmith\n"
            "Terminal=false\n"
            "NoDisplay=true\n"
            "MimeType=x-scheme-handler/blocksmith;\n",
            encoding="utf-8",
        )
        desktop.chmod(0o644)
        database = shutil.which("update-desktop-database")
        if database:
            subprocess.run([database, str(applications)], check=False, capture_output=True)
        xdg_mime = shutil.which("xdg-mime")
        if xdg_mime:
            subprocess.run(
                [xdg_mime, "default", desktop.name, "x-scheme-handler/blocksmith"],
                check=False,
                capture_output=True,
            )
        return "blocksmith:// links are registered for this Linux account."

    raise ProtocolError(f"Protocol registration is not supported on {sys.platform}.")
