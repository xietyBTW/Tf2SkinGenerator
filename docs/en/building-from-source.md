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

The Windows release is produced with **PyInstaller** (`--onedir --windowed`), with `tools/`
copied into the output root so the frozen app can still find everything by relative path. The
maintainer's own build script (`build.ps1`) and the Inno Setup installer script live outside the
repo (they're gitignored), so this section is a reference for how the release is made rather
than a step you can run straight from a clone.

## Notes

- Logs go to `tf2sg.log` next to the app (the repo root, when running from source).
- Config lives in `config/app_config.json`, created with defaults the first time you run the
  app. It's gitignored. Nothing in `config/` is actually checked into the repo, so there's
  nothing to inherit from a clone; your local config starts fresh.
- Third-party tool licenses: see [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).
