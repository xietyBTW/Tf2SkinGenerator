# TF2 Skin Generator

**Language:** English · [Русский](README.ru.md)

TF2 Skin Generator is a Windows app for making Team Fortress 2 mods without juggling command-line tools. You pick a weapon, a cosmetic or an effect straight from the game, drop your image on it, look at the result in 3D and build a `.vpk` file for `tf/custom`.

The app does the tedious part on its own. It finds the model and textures in the game files, decompiles the model with Crowbar, converts your images to VTF, writes the VMT materials, recompiles the model with the game's own `studiomdl` and packs the result into a VPK.

## What you can make

| Task | Where in the app | Guide |
|---|---|---|
| Retexture a weapon, a projectile, a health or ammo pickup, a taunt prop | **Weapons** | [Your first skin](docs/en/reskin.md) |
| Repaint a hat or any other cosmetic, each of its styles included | **Cosmetics** | [Cosmetics](docs/en/cosmetics.md) |
| Paint one piece of a model: the scope, the grip, a logo on the stock | **Split into parts** | [Painting by parts](docs/en/model-parts.md) |
| Bake an in-game War Paint into a texture and keep painting on top of it | **War Paint** | [War Paint](docs/en/war-paint.md) |
| Add glow, gloss, reflections, transparency or surface relief | **Material maps**, **VMT**, build options | [Materials and effects](docs/en/materials.md) |
| Replace a weapon model with your own SMD, OBJ or GLB | **Replace model** | [Custom models](docs/en/custom-models.md) |
| Reskin class bodies and hands, Spy masks, the crit text, sprays, death effects, skyboxes | **Weapons**, category list | [Characters, effects and skyboxes](docs/en/special-items.md) |
| Edit particle effects, unusuals included | **Particles** | [Particle editor](docs/en/particles.md) |
| Replace weapon sounds, voice lines and world sounds | **Sounds** | [Sounds](docs/en/sounds.md) |
| Find out why a mod doesn't show up in game | **Diagnostics** | [Installing mods and troubleshooting](docs/en/troubleshooting.md) |

## Requirements

- 64-bit Windows 10 or 11.
- Team Fortress 2 installed through Steam. The app reads the game's archives and uses `studiomdl.exe` and `vpk.exe` from the game's `bin` folder, so without the game it can't build anything.
- Microsoft Edge WebView2 Runtime, which draws the interface. Windows 11 includes it, and on Windows 10 it usually arrives with Windows or Office updates. If the app window stays blank, see [troubleshooting](docs/en/troubleshooting.md#the-app-window-is-blank-or-does-not-open).

## Installation

Download the latest release from the [Releases page](https://github.com/xietyBTW/Tf2SkinGenerator/releases/latest). It has two files:

| File | What it is |
|---|---|
| `Tf2SkinGenerator-Setup.exe` | The installer. It doesn't ask for administrator rights and installs for the current user, by default into `%LOCALAPPDATA%\Programs\Tf2SkinGenerator`. |
| `Tf2SkinGenerator-portable.zip` | The same app as a plain folder. Unzip it into any folder you can write to and run `Tf2SkinGenerator.exe`. |

Both versions update from inside the app: **Settings → Check for updates**. Your works, imported mods, settings and the export folder are stored in `%LOCALAPPDATA%\Tf2SkinGenerator`, apart from the program files, so updating or reinstalling doesn't touch them. This holds for the portable version too.

## First launch

1. The app looks for TF2 through the Steam registry entries and Steam's library list, including libraries on other drives. If it finds the game, it shows the path and asks you to save it. If not, paste the path to the folder that contains `tf` and `bin`, for example `D:\Steam\steamapps\common\Team Fortress 2`.
2. A short tutorial starts on top of the interface. It walks through one skin from start to finish. You can skip it and replay it later from **Settings → Replay the tutorial**.
3. The interface language is English by default. Russian is available in **Settings → Application language**.

## A skin in five steps

1. Click **Select an item** at the top, keep the category on **Weapon** and pick a weapon. The **Class** and **Type** filters and the search box help with long lists.
2. Wait a moment while the model loads. The first time takes a few seconds because the app decompiles it; after that the model comes from the cache.
3. Drag your image onto the texture card on the left. Double-clicking the card opens a file dialog instead.
4. Rotate the model with the left mouse button to check how it looks. **First person** shows the weapon in hand with its animations.
5. Click **Build VPK** at the bottom right. The finished file goes to the export folder: **Tools → Open export folder**.

Copy the `.vpk` into `...\Team Fortress 2\tf\custom\` and restart the game. That's it. The [first skin guide](docs/en/reskin.md) goes through the same path in detail, with team colors, build settings and the questions the app may ask while building.

## Documentation

The full guide set is in [`docs/`](docs/README.md).

**Getting started**
- [Your first skin](docs/en/reskin.md): the whole path from picking a weapon to seeing it in game
- [Interface tour](docs/en/usage.md): every panel, button and keyboard shortcut

**Topics**
- [Cosmetics](docs/en/cosmetics.md)
- [Painting by parts](docs/en/model-parts.md)
- [War Paint](docs/en/war-paint.md)
- [Materials and effects](docs/en/materials.md)
- [Custom models](docs/en/custom-models.md)
- [Characters, effects and skyboxes](docs/en/special-items.md)
- [Particle editor](docs/en/particles.md)
- [Sounds](docs/en/sounds.md)
- [Works, drafts and the mod library](docs/en/works-and-mods.md)

**Reference**
- [Settings and data folders](docs/en/settings.md)
- [Installing mods and troubleshooting](docs/en/troubleshooting.md)
- [Building from source](docs/en/building-from-source.md)

## Casual servers and sv_pure

Valve's casual servers run with `sv_pure`, which makes the game ignore most custom files. For skins that live on a model (weapons, cosmetics, characters, projectiles, pickups, taunt props) the app uses a known workaround: it moves the model's materials into a folder that `sv_pure` lets through. Skyboxes, sounds, particle effects and the crit, spray and death effect skins don't go through it. Details and caveats are in [troubleshooting](docs/en/troubleshooting.md#casual-servers-and-sv_pure).

## Building from source

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Python 3.12 or newer is required. The development setup, project layout, tests and the release process are described in [Building from source](docs/en/building-from-source.md).

## License

The source code is released under the [MIT license](LICENSE). Crowbar, VTFLib and meshoptimizer are bundled under their own licenses, listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

TF2 Skin Generator is a fan-made tool. It isn't affiliated with or endorsed by Valve. Team Fortress 2 and its assets belong to Valve Corporation, and no game files are distributed with the app.
