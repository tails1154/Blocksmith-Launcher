from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from portablemc.fabric import FABRIC_API, QUILT_API, FabricVersion
from portablemc.forge import (
    ForgePostProcessedEvent,
    ForgePostProcessingEvent,
    ForgeVersion,
)
from portablemc.standard import (
    Context,
    DownloadCompleteEvent,
    DownloadProgressEvent,
    DownloadStartEvent,
    JvmLoadedEvent,
    JvmLoadingEvent,
    OfflineAuthSession,
    SimpleWatcher,
    StandardRunner,
    Version,
    VersionFetchingEvent,
    VersionLoadedEvent,
    VersionLoadingEvent,
)

from .models import Profile
from .storage import LauncherStorage


class LogRunner(StandardRunner):
    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.process: subprocess.Popen | None = None

    def process_create(self, args, work_dir):
        self.emit("Minecraft process started.")
        self.process = subprocess.Popen(
            args,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return self.process

    def process_wait(self, process):
        assert process.stdout is not None
        for line in process.stdout:
            self.emit(line.rstrip())
        code = process.wait()
        self.emit(f"Minecraft exited with code {code}.")


class MinecraftService:
    def __init__(self, storage: LauncherStorage) -> None:
        self.storage = storage

    def _context(self, profile: Profile) -> Context:
        return Context(self.storage.shared_dir, self.storage.instance_dir(profile))

    def version(self, profile: Profile):
        context = self._context(profile)
        loader_version = profile.loader_version or None
        if profile.loader == "Vanilla":
            return Version(profile.minecraft_version, context=context)
        if profile.loader == "Fabric":
            return FabricVersion(FABRIC_API, profile.minecraft_version, loader_version, "fabric", context=context)
        if profile.loader == "Quilt":
            return FabricVersion(QUILT_API, profile.minecraft_version, loader_version, "quilt", context=context)
        if profile.loader == "Forge":
            spec = profile.loader_version or f"{profile.minecraft_version}-recommended"
            if loader_version and not loader_version.startswith(profile.minecraft_version):
                spec = f"{profile.minecraft_version}-{loader_version}"
            return ForgeVersion(spec, context=context, prefix="forge")
        if profile.loader == "NeoForge":
            spec = profile.loader_version or profile.minecraft_version
            return ForgeVersion(spec, context=context, prefix="neoforge")
        raise ValueError(f"Unsupported loader: {profile.loader}")

    @staticmethod
    def watcher(emit: Callable[[str], None], progress: Callable[[float], None]) -> SimpleWatcher:
        total = {"bytes": 0}

        def download_start(event):
            total["bytes"] = max(event.size, 1)
            emit(f"Downloading {event.entries_count} files…")

        def download_progress(event):
            progress(min(0.99, event.size / total["bytes"]))

        return SimpleWatcher({
            VersionLoadingEvent: lambda e: emit(f"Loading Minecraft {e.version}…"),
            VersionFetchingEvent: lambda e: emit(f"Fetching version metadata for {e.version}…"),
            VersionLoadedEvent: lambda e: emit(f"Version {e.version} ready."),
            JvmLoadingEvent: lambda e: emit("Checking Java runtime…"),
            JvmLoadedEvent: lambda e: emit(f"Java runtime ready ({e.version or 'system'})."),
            ForgePostProcessingEvent: lambda e: emit(f"Installing mod loader: {e.task}…"),
            ForgePostProcessedEvent: lambda e: emit("Mod loader installed."),
            DownloadStartEvent: download_start,
            DownloadProgressEvent: download_progress,
            DownloadCompleteEvent: lambda e: progress(1.0),
        })

    def install(self, profile: Profile, emit, progress):
        emit(f"Installing {profile.subtitle}…")
        environment = self.version(profile).install(watcher=self.watcher(emit, progress))
        emit("Installation complete.")
        progress(1.0)
        return environment

    def launch(self, profile: Profile, session, emit, progress) -> None:
        emit(f"Preparing {profile.subtitle}…")
        version = self.version(profile)
        version.auth_session = session
        width, _, height = profile.resolution.partition("x")
        if width.isdigit() and height.isdigit():
            version.resolution = (int(width), int(height))
        environment = version.install(watcher=self.watcher(emit, progress))
        environment.jvm_args.extend([
            f"-Xms512M",
            f"-Xmx{profile.memory_mb}M",
            "-Dlog4j2.formatMsgNoLookups=true",
        ])
        environment.run(LogRunner(emit))

    @staticmethod
    def offline_session(username: str) -> OfflineAuthSession:
        clean = username.strip()
        if not 3 <= len(clean) <= 16 or not clean.replace("_", "").isalnum():
            raise ValueError("Offline username must be 3–16 letters, numbers, or underscores")
        return OfflineAuthSession(clean, None)
