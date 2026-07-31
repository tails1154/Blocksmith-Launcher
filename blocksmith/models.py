from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4


LOADERS = ("Vanilla", "Fabric", "Forge", "NeoForge", "Quilt")


@dataclass(slots=True)
class Profile:
    name: str
    minecraft_version: str
    loader: str = "Vanilla"
    loader_version: str = ""
    id: str = ""
    memory_mb: int = 4096
    resolution: str = "1280x720"
    last_played: str = ""
    installed: bool = False

    def __post_init__(self) -> None:
        self.id = self.id or uuid4().hex
        if self.loader not in LOADERS:
            raise ValueError(f"Unsupported loader: {self.loader}")
        if self.memory_mb < 512:
            raise ValueError("Memory must be at least 512 MB")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Profile":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def subtitle(self) -> str:
        suffix = f" · {self.loader_version}" if self.loader_version else ""
        return f"Minecraft {self.minecraft_version} · {self.loader}{suffix}"

