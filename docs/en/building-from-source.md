# Building from source

[← Docs index](../README.md)

For developers who want to run the app from a checkout. **Windows only.**

## Prerequisites

- **Python 3.12+** on `PATH`.
- **Team Fortress 2 installed**, needed to build mods, and `vpk.exe` is used from
  `<TF2>\bin\`.

## Third-party tools

Crowbar and the VTF tools (`VTFCmd.exe`, `VTFLib.dll`, `HLLib.dll`, `DevIL.dll`) are already
**committed in `tools/`**, so there's nothing extra to download. Their licenses (CC BY-SA 3.0 /
LGPL / GPL) permit redistribution, see [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).

The one tool that's **not** in the repo is **`vpk.exe`**, since it's Valve's own binary. The app
picks it up automatically from your installed TF2 (`<TF2>\bin\vpk.exe`); you can also drop a
copy into `tools/VPK/` as a fallback if you'd rather not rely on the TF2 install for that.

## Set up and run

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

`requirements.txt` is the runtime dependencies: PySide6 (Essentials + Addons), Pillow, `vpk`,
`srctools`, NumPy. `requirements-dev.txt` adds the dev/test tooling (PyInstaller, coverage,
vulture, ruff) on top.

## Project layout

```
main.py                 entry point (logging, splash, launches MainWindow)
src/
  ui/                   PySide6 widgets: main window, panels, dialogs, preview
  services/             build pipeline: VTF/VMT/VPK, model decompile/compile, diagnostics
  data/                 static tables (weapons, hats, characters, skyboxes…)
  config/, shared/      config, logging, version, constants
tools/
  crowbar/, VTF/        Crowbar decompiler + VTF tools (committed)
  VPK/                  optional vpk.exe fallback (taken from TF2 otherwise)
  Model/                empty per-class placeholders (.gitkeep)
requirements*.txt       runtime + dev dependencies
```

The version lives in `src/shared/version.py`, the single source of truth, used by the UI's
update checker and by the build script when it stamps the installer.

## Release builds

A release is two files from one build: `Tf2SkinGenerator-Setup.exe` (an Inno Setup installer with
the app inside) and `Tf2SkinGenerator-portable.zip` (the same folder: unzip and run). Both are
produced by `build-release.ps1` (in the repo); the installer script
`installer/Tf2SkinGenerator-bundle.iss` is gitignored. You need `.venv` and
[Inno Setup 6](https://jrsoftware.org/isdl.php).

```bat
release.bat -Version 1.0.4
```

The script bumps the version in `src/shared/version.py`, builds the app with PyInstaller from the
spec (`--onedir --windowed`), copies `tools/` into the build root, packs everything into the
installer and then into the zip — both land in `installer\Output\`. `-SkipDeps` skips
reinstalling packages.

Then by hand:

1. Run the resulting `Setup.exe` locally and make sure the app installs and opens.
2. Commit the version bump.
3. Create a GitHub release tagged `v1.0.4` — a regular one, **not a draft and not a
   pre-release**: the update check skips those.
4. Attach both files with their exact names. The installer is required; the zip is for people
   who don't want to install.

In-app updates rely on these rules: the app asks GitHub for the latest release, compares the tag
with its own version, finds the installer by name (`ASSET_NAME` in
`src/services/update_checker.py`), verifies the SHA-256 that GitHub computes itself, and runs it
silently. The release text is shown in the app as the version notes.

A portable copy updates with the same installer: the `PORTABLE` marker file in its folder (the
script puts it into the zip) switches the updater to `Setup.exe /PORTABLE=1 /DIR="<that folder>"`,
which replaces the files in place and leaves nothing behind — no shortcuts, no uninstaller, no
entry in Programs and Features. The folder must be writable without administrator rights.

## Notes

- Logs go to `tf2sg.log` next to the app (the repo root, when running from source).
- Config lives in `config/app_config.json`, created with defaults the first time you run the
  app. It's gitignored. Nothing in `config/` is actually checked into the repo, so there's
  nothing to inherit from a clone; your local config starts fresh.
- Third-party tool licenses: see [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).
