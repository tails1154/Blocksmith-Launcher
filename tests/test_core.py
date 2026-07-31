import json

import pytest

from blocksmith.minecraft import MinecraftService
from blocksmith.curseforge import ModManager, ModProject
from blocksmith.models import Profile
from blocksmith.modrinth import ModrinthClient
from blocksmith.storage import LauncherStorage


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
