# TF2 Skin Generator

> **Language:** English · [Русский](README.ru.md)

A Windows desktop app for building **Team Fortress 2 VPK skin mods** without touching a
command line. Pick a weapon (or hat, character part, skybox…), drop in your texture, and get a
`.vpk` you can drop straight into the game. The app handles VTF conversion, VMT generation,
model decompile/recompile, and packaging for you.

<!-- Add a screenshot here: docs/img/main-window.png -->

---

## Features

- **Weapon reskins**: swap the texture on any stock weapon.
- **Custom models**: replace the geometry itself (decompile, then recompile via Crowbar +
  `studiomdl`).
- **Hats**: searchable/filterable cosmetic list, with per-class and per-style editing and
  optional game-paint support.
- **Character parts**: bodies and viewmodel hands, Spy disguise masks, shoulder isolation.
- **Special skins**: crit effects, sprays, death effects (ice / gold / fire).
- **Skyboxes**: replace the sky from a panorama or six face textures, with a 3D preview.
- **Projectiles, pickups, taunt props.**
- **Live 2D + 3D preview** before you commit to a build.
- **Diagnostics tab**: load an existing `.vpk` and get flagged on the usual reasons a mod
  doesn't show up in-game.
- English / Russian UI.

## Requirements

- **Windows** (the app bundles `vpk.exe`, `VTFCmd`, and Crowbar; model compiling uses
  `studiomdl.exe` from your game install).
- **Team Fortress 2 installed**, required for building. The app reads game files and uses
  `<TF2>/bin/studiomdl.exe` to compile models.
- For running from source: **Python 3.12+**.

## Install & run

### Option A: released build (recommended for users)

1. Download the latest release from the
   [Releases page](https://github.com/xietyBTW/Tf2SkinGenerator/releases/latest).
2. Run the installer, or unzip the portable build and launch `Tf2SkinGenerator.exe`.

### Option B: from source (for developers)

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Third-party tools (Crowbar, VTF tools) are already in `tools/`, so there's nothing extra to
download for that. See [docs/en/building-from-source.md](docs/en/building-from-source.md) for
the one exception (`vpk.exe`) and the rest of the dev setup.

## First-time setup

1. Launch the app and open **Settings** (the gear icon, top-right).
2. Set your **TF2 game folder**, the folder that contains `tf/` and `bin/`
   (e.g. `…\steamapps\common\Team Fortress 2`).
3. Pick your UI language and default export folder if you like.

## Quick start (30 seconds)

1. **Category → Weapon**, then choose class → slot → weapon on the left.
2. Drop your texture onto the main slot in the middle preview.
3. Set resolution / format / file name on the right, then click **Build**.
4. Copy the resulting `.vpk` from the `export/` folder into
   `…\Team Fortress 2\tf\custom\`, and restart the game.

## Guides

| Guide | What it covers |
|-------|----------------|
| [Using the app](docs/en/usage.md) | Full UI tour, build options, installing the mod in-game |
| [Simple reskins](docs/en/reskin.md) | Retexturing a stock weapon, step by step |
| [Custom models](docs/en/custom-models.md) | Replacing the model itself (geometry only vs. rigged) |
| [Building from source](docs/en/building-from-source.md) | Dev setup and producing the release `.exe` |

Russian versions live under [`docs/ru/`](docs/ru/).

## License

[MIT](LICENSE) © xiety
