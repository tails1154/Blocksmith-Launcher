# Blocksmith Launcher

A native Python Minecraft launcher built on the PortableMC module. Blocksmith
supports isolated profiles, offline play, Microsoft authentication, automatic
Java installation, and Vanilla, Fabric, Forge, NeoForge, and Quilt.

## Run

Python 3.10+ and Tk must be installed.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Or install the application command:

```bash
pip install -e .
blocksmith
```

## Distributable builds

The build script creates one-file PyInstaller applications for Linux and
Windows. Windows is built with a real Windows Python installation inside an
isolated Wine prefix; it is not a renamed Linux binary.

```bash
./build.sh linux      # Linux ELF application and tar.gz bundle
./build.sh windows    # Windows .exe and zip bundle through Wine
./build.sh all        # Both platforms
./build.sh clean      # Remove PyInstaller outputs; preserve cached Wine Python
```

Outputs:

- `dist/linux/Blocksmith`
- `dist/Blocksmith-linux-x86_64.tar.gz`
- `dist/windows/Blocksmith.exe`
- `dist/Blocksmith-windows-x86_64.zip`

The first Windows build downloads Python for Windows and initializes
`build/wine-prefix`. Later builds reuse it. Override its location with
`BLOCKSMITH_WINEPREFIX=/path/to/prefix`. Linux builds use an isolated virtual
environment under `build/venv-linux`, which avoids changing system Python.

The generated application artwork is in `assets/`, including a multi-resolution
Windows `.ico` and PNG desktop icons.

## Updates

Packaged portable builds can update themselves from GitHub Releases. Open
**Settings → Updates** to choose a channel:

- **Stable** follows normal versioned releases.
- **Development** follows the rolling prerelease built from every successful
  push to `main`.

Blocksmith downloads the platform archive and its published SHA-256 checksum,
verifies the archive, and only then stages a replacement and restarts. Linux
installations under system-owned paths such as `/usr/bin` are not modified;
update those through the package manager. Source checkouts should use
`git pull`.

## Profiles and data

Launcher data is stored in the operating system's application-data directory.
Set `BLOCKSMITH_HOME` to use a custom or portable directory:

```bash
BLOCKSMITH_HOME="$PWD/.blocksmith-data" python run.py
```

Each profile gets its own saves, mods, configuration, resource packs, and
screenshots. Assets, libraries, and Minecraft versions are shared to avoid
duplicate downloads. Microsoft tokens are managed by PortableMC and passwords
are never requested or stored by Blocksmith.

## Modrinth mods

No API key or account is required. Select a Fabric, Forge, NeoForge, or Quilt
profile and open the **Mods** tab. Searches are automatically filtered to that
profile's Minecraft version and loader.

Blocksmith uses Modrinth's public API to select the newest compatible file,
install required dependencies, and track every downloaded file in the profile.
Installed mods can be enabled, disabled, or removed from the Mods tab.

## Mod loader versions

Leave the loader version blank to use the loader's default:

- Fabric and Quilt use the newest compatible loader.
- Forge uses the recommended build for the selected Minecraft version.
- NeoForge uses the newest compatible build.

You can enter an exact loader version when required by a modpack.

## Development roadmap

Modrinth modpack import is planned. Individual Modrinth mods and their required
dependencies are supported now. The dormant CurseForge provider can be enabled
later when an approved API key is available.
