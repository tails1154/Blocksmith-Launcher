from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_data_path

from .models import Profile


class LauncherStorage:
    def __init__(self, root: Path | None = None) -> None:
        override = os.environ.get("BLOCKSMITH_HOME")
        self.root = Path(override) if override else (root or user_data_path("Blocksmith", "Blocksmith"))
        self.shared_dir = self.root / "minecraft"
        self.instances_dir = self.root / "instances"
        self.auth_file = self.root / "portablemc_auth.json"
        self.profiles_file = self.root / "profiles.json"
        self.settings_file = self.root / "settings.json"
        self.ensure()

    def ensure(self) -> None:
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        self.instances_dir.mkdir(parents=True, exist_ok=True)

    def instance_dir(self, profile: Profile) -> Path:
        path = self.instances_dir / profile.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)

    def load_profiles(self) -> list[Profile]:
        values = self._read_json(self.profiles_file, [])
        profiles = []
        for value in values:
            try:
                profiles.append(Profile.from_dict(value))
            except (TypeError, ValueError):
                continue
        return profiles

    def save_profiles(self, profiles: list[Profile]) -> None:
        self._write_json(self.profiles_file, [profile.to_dict() for profile in profiles])

    def load_settings(self) -> dict:
        return self._read_json(self.settings_file, {})

    def save_settings(self, settings: dict) -> None:
        self._write_json(self.settings_file, settings)

