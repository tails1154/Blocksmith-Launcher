from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .models import Profile
from .storage import LauncherStorage


API_BASE = "https://api.curseforge.com/v1"
USER_AGENT = f"Blocksmith/{__version__}"
MINECRAFT_GAME_ID = 432
MOD_CLASS_ID = 6
LOADER_IDS = {"Forge": 1, "Fabric": 4, "Quilt": 5, "NeoForge": 6}


class CurseForgeError(RuntimeError):
    pass


@dataclass(slots=True)
class ModProject:
    id: int | str
    name: str
    slug: str
    summary: str
    downloads: int
    author: str
    icon_url: str = ""
    body: str = ""
    updated: str = ""
    categories: tuple[str, ...] = ()
    source_url: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "ModProject":
        authors = data.get("authors") or []
        return cls(
            id=int(data["id"]),
            name=data.get("name", "Unknown"),
            slug=data.get("slug", ""),
            summary=data.get("summary", ""),
            downloads=int(data.get("downloadCount", 0)),
            author=authors[0].get("name", "Unknown") if authors else "Unknown",
            icon_url=(data.get("logo") or {}).get("thumbnailUrl", ""),
            source_url=(data.get("links") or {}).get("websiteUrl", ""),
        )


class CurseForgeClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()

    def _request(self, path: str, params: dict | None = None):
        if not self.api_key:
            raise CurseForgeError("Add a CurseForge API key in the Settings tab first.")
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "x-api-key": self.api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response).get("data")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise CurseForgeError("CurseForge rejected the API key.") from exc
            raise CurseForgeError(f"CurseForge request failed (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CurseForgeError(f"Could not reach CurseForge: {exc}") from exc

    def search_mods(self, query: str, profile: Profile, limit: int = 30) -> list[ModProject]:
        params = {
            "gameId": MINECRAFT_GAME_ID,
            "classId": MOD_CLASS_ID,
            "gameVersion": profile.minecraft_version,
            "searchFilter": query,
            "sortField": 2,  # popularity
            "sortOrder": "desc",
            "pageSize": limit,
        }
        loader_id = LOADER_IDS.get(profile.loader)
        if loader_id:
            params["modLoaderType"] = loader_id
        return [ModProject.from_api(value) for value in (self._request("/mods/search", params) or [])]

    def compatible_files(self, project_id: int, profile: Profile) -> list[dict]:
        params = {
            "gameVersion": profile.minecraft_version,
            "pageSize": 50,
        }
        loader_id = LOADER_IDS.get(profile.loader)
        if loader_id:
            params["modLoaderType"] = loader_id
        files = self._request(f"/mods/{project_id}/files", params) or []
        return [file for file in files if file.get("isAvailable", True)]

    def project(self, project_id: int) -> ModProject:
        return ModProject.from_api(self._request(f"/mods/{project_id}"))

    def file(self, project_id: int, file_id: int) -> dict:
        return self._request(f"/mods/{project_id}/files/{file_id}")

    def download_url(self, project_id: int, file: dict) -> str:
        url = file.get("downloadUrl")
        if not url:
            url = self._request(f"/mods/{project_id}/files/{file['id']}/download-url")
        if not url:
            raise CurseForgeError(
                f"{file.get('displayName', 'This file')} does not permit third-party downloads."
            )
        return url

    def download(self, url: str, destination: Path, progress: Callable[[float], None]) -> None:
        request = urllib.request.Request(url, headers={"x-api-key": self.api_key, "User-Agent": USER_AGENT})
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                while chunk := response.read(1024 * 128):
                    output.write(chunk)
                    downloaded += len(chunk)
                    if size:
                        progress(downloaded / size)
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


class ModManager:
    """Provider-neutral mod installer used by CurseForge and Modrinth clients."""

    def __init__(self, storage: LauncherStorage, client) -> None:
        self.storage = storage
        self.client = client

    def _paths(self, profile: Profile) -> tuple[Path, Path]:
        instance = self.storage.instance_dir(profile)
        mods = instance / "mods"
        mods.mkdir(parents=True, exist_ok=True)
        return mods, instance / "blocksmith_mods.json"

    def _metadata(self, profile: Profile) -> list[dict]:
        _, path = self._paths(profile)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, profile: Profile, entries: list[dict]) -> None:
        _, path = self._paths(profile)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        temporary.replace(path)

    def installed(self, profile: Profile) -> list[dict]:
        mods, _ = self._paths(profile)
        entries = self._metadata(profile)
        for entry in entries:
            entry["enabled"] = (mods / entry["filename"]).exists()
        return entries

    def install(
        self,
        project: ModProject,
        profile: Profile,
        emit: Callable[[str], None],
        progress: Callable[[float], None],
        seen: set[int | str] | None = None,
    ) -> None:
        if profile.loader == "Vanilla":
            raise CurseForgeError("Choose Fabric, Forge, NeoForge, or Quilt before installing mods.")
        seen = seen or set()
        if project.id in seen:
            return
        seen.add(project.id)
        files = self.client.compatible_files(project.id, profile)
        if not files:
            raise CurseForgeError(
                f"No {profile.loader} file for {project.name} supports Minecraft {profile.minecraft_version}."
            )
        file = files[0]
        for relation in file.get("dependencies") or []:
            if relation.get("relationType") == 3:  # required dependency
                dependency = self.client.project(int(relation["modId"]))
                emit(f"Installing required dependency: {dependency.name}")
                self.install(dependency, profile, emit, progress, seen)

        mods, _ = self._paths(profile)
        filename = os.path.basename(file.get("fileName") or f"{project.slug}-{file['id']}.jar")
        if not filename.lower().endswith((".jar", ".zip")):
            raise CurseForgeError("The mod provider returned an unsafe filename.")
        destination = mods / filename
        emit(f"Downloading {project.name}…")
        progress(0.0)
        self.client.download(self.client.download_url(project.id, file), destination, progress)
        entries = [entry for entry in self._metadata(profile) if str(entry["project_id"]) != str(project.id)]
        entries.append({
            "project_id": str(project.id),
            "file_id": str(file["id"]),
            "name": project.name,
            "filename": filename,
            "version": file.get("displayName", str(file["id"])),
            "summary": project.summary,
            "icon_url": project.icon_url,
        })
        self._save(profile, sorted(entries, key=lambda value: value["name"].lower()))
        emit(f"Installed {project.name}.")

    def set_enabled(self, profile: Profile, project_id: int | str, enabled: bool) -> None:
        mods, _ = self._paths(profile)
        entry = next((item for item in self._metadata(profile) if str(item["project_id"]) == str(project_id)), None)
        if entry is None:
            raise CurseForgeError("The selected mod is no longer tracked.")
        enabled_path = mods / entry["filename"]
        disabled_path = enabled_path.with_name(enabled_path.name + ".disabled")
        source, destination = (disabled_path, enabled_path) if enabled else (enabled_path, disabled_path)
        if source.exists():
            source.replace(destination)

    def remove(self, profile: Profile, project_id: int | str) -> None:
        mods, _ = self._paths(profile)
        entries = self._metadata(profile)
        entry = next((item for item in entries if str(item["project_id"]) == str(project_id)), None)
        if entry is None:
            return
        path = mods / entry["filename"]
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".disabled").unlink(missing_ok=True)
        self._save(profile, [item for item in entries if str(item["project_id"]) != str(project_id)])
