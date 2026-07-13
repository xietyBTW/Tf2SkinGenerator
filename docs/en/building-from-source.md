# Building from source

[← Docs index](../README.md)

For developers who want to run the app from a checkout. **Windows only.**

## Prerequisites

- **Python 3.12+** on `PATH`.
- **Team Fortress 2 installed** (needed to build mods, and `vpk.exe` is used from `<TF2>\bin\`).

## Third‑party tools

Crowbar and the VTF tools (`VTFCmd.exe`, `VTFLib.dll`, `HLLib.dll`, `DevIL.dll`) are **committed in
`tools/`** — nothing to download. Their licenses (CC BY‑SA 3.0 / LGPL / GPL) permit redistribution;
see [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).

The only tool **not** in the repo is **`vpk.exe`** — it's Valve's proprietary binary. The app uses
it from your installed TF2 (`<TF2>\bin\vpk.exe`) automatically; optionally drop a copy in
`tools/VPK/` as a fallback.

## Set up and run

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

`requirements.txt` = runtime deps (PySide6 Essentials + Addons, Pillow, `vpk`, `srctools`, NumPy).
`requirements-dev.txt` adds the dev/test tooling.

## Project layout

```
main.py                 entry point (logging, splash, launches MainWindow)
src/
  ui/                   PySide6 widgets — main window, panels, dialogs, preview
  services/             build pipeline: VTF/VMT/VPK, model decompile/compile, diagnostics
  data/                 static tables (weapons, hats, characters, skyboxes…)
  config/, shared/      config, logging, version, constants
tools/
  crowbar/, VTF/        Crowbar decompiler + VTF tools (committed)
  VPK/                  optional vpk.exe fallback (taken from TF2 otherwise)
  Model/                empty per-class placeholders (.gitkeep)
requirements*.txt       runtime + dev dependencies
```

The version lives in `src/shared/version.py` (single source of truth).

## Release builds

The Windows release is produced with **PyInstaller** (`--onedir --windowed`), with `tools/` copied
into the output root so the frozen app finds them by relative path. The maintainer's build scripts
and the Inno Setup installer are **not** part of the repository (`.gitignore`), so this is a
reference, not a step you run from a clone.

## Notes

- Logs go to `tf2sg.log` next to the app (repo root when run from source).
- Config is stored per‑user (`AppConfig` in `src/config/app_config.py`); created with defaults on
  first run. Committed config is examples only (`config/*.example.json`).
- Third‑party tool licenses: see [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).
