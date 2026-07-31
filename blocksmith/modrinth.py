from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .curseforge import ModProject, CurseForgeError
from .models import Profile


API_BASE = "https://api.modrinth.com/v2"
LOADER_NAMES = {
    "Fabric": "fabric",
    "Forge": "forge",
    "NeoForge": "neoforge",
    "Quilt": "quilt",
}


class ModrinthClient:
    """No-key client for Modrinth's public project and version APIs."""

    def _request(self, path: str, params: dict | None = None):
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Blocksmith/0.1 (Minecraft launcher)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise CurseForgeError(f"Modrinth request failed (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CurseForgeError(f"Could not reach Modrinth: {exc}") from exc

    def search_mods(self, query: str, profile: Profile, limit: int = 30) -> list[ModProject]:
        loader = LOADER_NAMES.get(profile.loader)
        facets = [["project_type:mod"], [f"versions:{profile.minecraft_version}"]]
        if loader:
            facets.append([f"categories:{loader}"])
        data = self._request("/search", {
            "query": query,
            "facets": json.dumps(facets, separators=(",", ":")),
            "index": "downloads",
            "limit": limit,
        })
        return [
            ModProject(
                id=hit["project_id"],
                name=hit.get("title", "Unknown"),
                slug=hit.get("slug", ""),
                summary=hit.get("description", ""),
                downloads=int(hit.get("downloads", 0)),
                author=hit.get("author", "Unknown"),
                icon_url=hit.get("icon_url") or "",
                updated=hit.get("date_modified") or "",
                categories=tuple(hit.get("categories") or ()),
                source_url=f"https://modrinth.com/mod/{hit.get('slug') or hit['project_id']}",
            )
            for hit in data.get("hits", [])
        ]

    def compatible_files(self, project_id: str, profile: Profile) -> list[dict]:
        loader = LOADER_NAMES.get(profile.loader)
        params = {"game_versions": json.dumps([profile.minecraft_version])}
        if loader:
            params["loaders"] = json.dumps([loader])
        versions = self._request(f"/project/{urllib.parse.quote(str(project_id))}/version", params)
        # Modrinth returns newest first; prefer stable releases while preserving
        # that order within each release channel.
        channel_rank = {"release": 0, "beta": 1, "alpha": 2}
        versions = sorted(versions, key=lambda item: channel_rank.get(item.get("version_type"), 3))
        normalized = []
        for version in versions:
            files = version.get("files") or []
            primary = next((file for file in files if file.get("primary")), files[0] if files else None)
            if primary is None:
                continue
            dependencies = [
                {"modId": dependency.get("project_id"), "relationType": 3}
                for dependency in version.get("dependencies") or []
                if dependency.get("dependency_type") == "required" and dependency.get("project_id")
            ]
            normalized.append({
                "id": version["id"],
                "fileName": primary["filename"],
                "displayName": version.get("name") or version.get("version_number") or version["id"],
                "downloadUrl": primary["url"],
                "dependencies": dependencies,
                "isAvailable": True,
            })
        return normalized

    def project(self, project_id: str) -> ModProject:
        data = self._request(f"/project/{urllib.parse.quote(str(project_id))}")
        return ModProject(
            id=data["id"],
            name=data.get("title", "Unknown"),
            slug=data.get("slug", ""),
            summary=data.get("description", ""),
            downloads=int(data.get("downloads", 0)),
            author=data.get("team", "Modrinth"),
            icon_url=data.get("icon_url") or "",
            body=data.get("body") or data.get("description", ""),
            updated=data.get("updated") or "",
            categories=tuple(data.get("categories") or ()),
            source_url=f"https://modrinth.com/mod/{data.get('slug') or data['id']}",
        )

    def image(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "Blocksmith/0.2 (Minecraft launcher)"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.headers.get_content_type() not in ("image/png", "image/gif"):
                    raise CurseForgeError("Modrinth returned an unsupported icon format.")
                return response.read(2 * 1024 * 1024)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CurseForgeError(f"Could not load the mod icon: {exc}") from exc

    @staticmethod
    def download_url(project_id, file: dict) -> str:
        return file["downloadUrl"]

    def download(self, url, destination, progress) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Blocksmith/0.1 (Minecraft launcher)"})
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
