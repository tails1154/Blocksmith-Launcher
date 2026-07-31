import json
import hashlib
import io
import os
import queue
import sys
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from blocksmith.minecraft import MinecraftService
from blocksmith.curseforge import ModManager, ModProject
from blocksmith.models import Profile
from blocksmith.modrinth import ModrinthClient
from blocksmith.storage import LauncherStorage
from blocksmith.updater import GitHubUpdater
from blocksmith.protocol import ProtocolError, install_uri, parse_uri
from blocksmith.discord_rpc import DiscordRPC


def test_profile_round_trip(tmp_path):
    storage = LauncherStorage(tmp_path)
    profile = Profile("Fabric Pack", "1.21.1", "Fabric", memory_mb=6144)
    storage.save_profiles([profile])
    loaded = storage.load_profiles()
    assert loaded == [profile]
    assert json.loads(storage.profiles_file.read_text())[0]["loader"] == "Fabric"


def test_instances_are_isolated(tmp_path):
    storage = LauncherStorage(tmp_path)
    first = Profile("One", "1.20.1")
    second = Profile("Two", "1.20.1")
    assert storage.instance_dir(first) != storage.instance_dir(second)
    assert storage.shared_dir.is_dir()


@pytest.mark.parametrize("loader", ["Vanilla", "Fabric", "Forge", "NeoForge", "Quilt"])
def test_all_supported_loaders_construct(tmp_path, loader):
    service = MinecraftService(LauncherStorage(tmp_path))
    version = service.version(Profile("Test", "1.20.1", loader))
    assert version is not None


@pytest.mark.parametrize("bad", ["ab", "space name", "symbols!"])
def test_offline_username_validation(bad):
    with pytest.raises(ValueError):
        MinecraftService.offline_session(bad)


def test_offline_username(tmp_path):
    session = MinecraftService.offline_session("Steve_123")
    assert session.username == "Steve_123"


class FakeCurseForge:
    def compatible_files(self, project_id, profile):
        dependencies = [{"modId": 2, "relationType": 3}] if project_id == 1 else []
        return [{
            "id": project_id * 10,
            "fileName": f"mod-{project_id}.jar",
            "displayName": f"Version {project_id}",
            "dependencies": dependencies,
        }]

    def project(self, project_id):
        return ModProject(project_id, "Library", "library", "", 0, "Author")

    def download_url(self, project_id, file):
        return f"https://example.invalid/{file['fileName']}"

    def download(self, url, destination, progress):
        destination.write_bytes(b"fake jar")
        progress(1)


def test_mod_install_dependencies_toggle_and_remove(tmp_path):
    storage = LauncherStorage(tmp_path)
    profile = Profile("Modded", "1.21.1", "Fabric")
    manager = ModManager(storage, FakeCurseForge())
    project = ModProject(1, "Main Mod", "main", "", 10, "Author")

    manager.install(project, profile, lambda _: None, lambda _: None)
    installed = manager.installed(profile)
    assert {entry["project_id"] for entry in installed} == {"1", "2"}
    assert all(entry["enabled"] for entry in installed)

    manager.set_enabled(profile, 1, False)
    assert not next(entry for entry in manager.installed(profile) if entry["project_id"] == "1")["enabled"]
    manager.set_enabled(profile, 1, True)
    assert next(entry for entry in manager.installed(profile) if entry["project_id"] == "1")["enabled"]

    manager.remove(profile, 1)
    assert {entry["project_id"] for entry in manager.installed(profile)} == {"2"}


def test_mod_install_reports_download_progress(tmp_path):
    manager = ModManager(LauncherStorage(tmp_path), FakeCurseForge())
    values = []
    manager.install(
        ModProject(3, "Progress Mod", "progress", "", 1, "Author"),
        Profile("Modded", "1.21.1", "Fabric"),
        lambda _: None,
        values.append,
    )
    assert values[0] == 0.0
    assert values[-1] == 1


def test_modrinth_normalizes_versions_and_required_dependencies(monkeypatch):
    client = ModrinthClient()
    response = [{
        "id": "version123",
        "name": "Release 1.0",
        "files": [{"filename": "example.jar", "url": "https://cdn.example/mod.jar", "primary": True}],
        "dependencies": [
            {"project_id": "fabric-api", "dependency_type": "required"},
            {"project_id": "optional-lib", "dependency_type": "optional"},
        ],
    }]
    monkeypatch.setattr(client, "_request", lambda path, params=None: response)
    files = client.compatible_files("example", Profile("Fabric", "1.21.1", "Fabric"))
    assert files[0]["fileName"] == "example.jar"
    assert files[0]["downloadUrl"] == "https://cdn.example/mod.jar"
    assert files[0]["dependencies"] == [{"modId": "fabric-api", "relationType": 3}]


def test_modrinth_search_keeps_rich_project_metadata(monkeypatch):
    client = ModrinthClient()
    monkeypatch.setattr(client, "_request", lambda path, params=None: {"hits": [{
        "project_id": "sodium",
        "title": "Sodium",
        "slug": "sodium",
        "description": "A rendering optimization mod.",
        "downloads": 1234,
        "author": "jellysquid3",
        "icon_url": "https://cdn.example/sodium.png",
        "date_modified": "2026-01-02T03:04:05Z",
        "categories": ["fabric", "optimization"],
    }]})
    project = client.search_mods("sodium", Profile("Fabric", "1.21.1", "Fabric"))[0]
    assert project.icon_url == "https://cdn.example/sodium.png"
    assert project.categories == ("fabric", "optimization")
    assert project.source_url == "https://modrinth.com/mod/sodium"


def test_updater_stable_version_and_development_asset_identity(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    wanted = GitHubUpdater.platform_asset()
    release = {
        "id": 10,
        "tag_name": "v0.2.0",
        "name": "Version 0.2.0",
        "html_url": "https://example.invalid/release",
        "draft": False,
        "assets": [
            {"id": 99, "name": wanted, "browser_download_url": "https://example.invalid/app"},
            {"id": 100, "name": wanted + ".sha256", "browser_download_url": "https://example.invalid/hash"},
        ],
    }
    monkeypatch.setattr(GitHubUpdater, "_json", staticmethod(lambda _url: release))
    updater = GitHubUpdater("0.1.0")
    assert updater.check("Stable").version == "v0.2.0"
    assert GitHubUpdater("0.2.0").check("Stable") is None
    development = updater.check("Development")
    assert development.release_id == 99
    assert updater.check("Development", installed_release_id=99) is None


def test_updater_accepts_packaged_checksum_filename(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    wanted = GitHubUpdater.platform_asset()
    checksum_name = wanted.removesuffix(".tar.gz").removesuffix(".zip") + ".sha256"
    release = {
        "id": 10, "tag_name": "development", "name": "Development", "html_url": "", "draft": False,
        "assets": [
            {"id": 8, "name": wanted, "browser_download_url": "artifact"},
            {"id": 9, "name": checksum_name, "browser_download_url": "checksum"},
        ],
    }
    monkeypatch.setattr(GitHubUpdater, "_json", staticmethod(lambda _url: release))
    assert GitHubUpdater().check("Development").checksum_url == "checksum"


def test_updater_verifies_and_extracts_platform_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    updater = GitHubUpdater()
    wanted = updater.platform_asset()
    executable_name = "Blocksmith.exe" if sys.platform == "win32" else "Blocksmith"
    payload = b"new blocksmith executable"
    archive_buffer = io.BytesIO()
    if wanted.endswith(".zip"):
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr(executable_name, payload)
    else:
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(executable_name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    archive_data = archive_buffer.getvalue()
    digest = hashlib.sha256(archive_data).hexdigest()
    update = type("Update", (), {
        "asset_name": wanted,
        "checksum_url": "checksum",
        "download_url": "artifact",
    })()
    monkeypatch.setattr(
        updater,
        "_download",
        lambda url, progress=None: f"{digest}  {wanted}\n".encode() if url == "checksum" else archive_data,
    )
    extracted = updater.download(update, lambda _value: None)
    assert extracted.name == executable_name
    assert extracted.read_bytes() == payload


def test_linux_self_updates_are_disabled(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/usr/bin/Blocksmith")
    allowed, reason = GitHubUpdater.can_self_update()
    assert allowed is False
    assert "disabled on Linux" in reason


def test_discord_rpc_sends_latest_presence(monkeypatch):
    calls = []

    class FakePresence:
        def __init__(self, client_id):
            calls.append(("client", client_id))

        def connect(self):
            calls.append(("connect",))

        def update(self, **payload):
            calls.append(("update", payload))

        def close(self):
            calls.append(("close",))

    commands = queue.Queue()
    commands.put({"details": "In launcher", "state": "Profile A"})
    commands.put({"details": "Playing", "state": "Profile B"})
    commands.put(None)
    statuses = []
    monkeypatch.setitem(sys.modules, "pypresence", SimpleNamespace(Presence=FakePresence))
    DiscordRPC._worker(commands, "123456789012345678", statuses.append)
    updates = [call for call in calls if call[0] == "update"]
    assert updates == [("update", {"details": "Playing", "state": "Profile B"})]
    assert statuses == ["Connected to Discord."]


def test_mod_install_protocol_round_trip():
    uri = install_uri("AANobbMI")
    assert uri == "blocksmith://install/modrinth/AANobbMI"
    request = parse_uri(uri)
    assert request.provider == "modrinth"
    assert request.project_id == "AANobbMI"


@pytest.mark.parametrize("uri", [
    "https://modrinth.com/mod/sodium",
    "blocksmith://launch/modrinth/AANobbMI",
    "blocksmith://install/curseforge/12345",
    "blocksmith://install/modrinth/bad%20id",
])
def test_mod_install_protocol_rejects_untrusted_links(uri):
    with pytest.raises(ProtocolError):
        parse_uri(uri)
