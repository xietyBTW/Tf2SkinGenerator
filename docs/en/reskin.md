# Simple reskins

[← Docs index](../README.md)

A reskin keeps the stock weapon model and only replaces its **texture**. It's the fastest kind
of mod to make and the best place to start if you've never used the app before.

## Before you begin

- TF2 needs to be installed, with the **game folder** set in Settings (see
  [the main README](../README.md#first-time-setup)).
- Have your texture ready as `PNG`, `JPG`, `TGA`, `BMP`, or an existing `VTF`.
- Not sure what size or layout to paint? Load the weapon first, export its **UV template** from
  the preview toolbar, and paint over that.

## Steps

1. **Pick the weapon.** In the left panel: **Category → Weapon**, then
   **Class → Slot (Primary / Secondary / Melee) → Weapon**.

2. **Show it in 3D, optional.** The 3D view doesn't load on its own. Click the **cube button**
   (*Load 3D model*) in the preview toolbar to render whatever you've selected; the 2D view
   updates by itself regardless. A few toolbar buttons you'll use here:

   | Button | Does |
   |--------|------|
   | **3D / 2D** | Switch between the 3D model and the flat 2D texture view |
   | **Cube** (*Load 3D model*) | Renders the current weapon in 3D, press it after selecting |
   | **VPK** | Load an existing `.vpk` mod into the 3D view |
   | **Replace model** | Swap in your own model (see [Custom models](custom-models.md)) |

3. **Load your texture.** Drag your image onto the **main texture slot**, or click Browse on the
   slot itself. The preview updates immediately.

   Some models have **extra materials**: a scope lens, a shell casing, that sort of thing. You
   can pre-load textures for those on their own slot cards, or just leave them and answer the
   prompt when you build (*Upload mine / Use game original / Use main texture*).

4. **RED / BLU team textures.**

   - If the weapon already has separate team skins in the base game, **RED** and **BLU** toggle
     buttons show up in the toolbar. Switch to **BLU** and load a second texture for the blue
     team.
   - If it doesn't, you'll see a **`+` button** instead (*make this weapon team-colored*). Click
     it and the RED/BLU toggles appear, and the app builds the blue material for you at build
     time. Leave BLU empty and both teams just get the RED texture.
   - Some weapons also have an **Australium/Gold** toggle for their gold variant, and an
     **eye-shaped button** that reveals hidden service textures (eyes, übercharge glow, etc.).

5. **Set the output options** on the right:

   | Option | Notes |
   |--------|-------|
   | **Resolution** | 256 / 512 / 1024 / 2048. Higher means sharper, and a bigger file. |
   | **Format** | `DXT1` (no alpha) or `DXT5` (alpha / transparency). |
   | **VTF flags** | `Clamp S/T`, `No Mipmaps`, `No LOD`. Leave these at their defaults unless you specifically need them. |
   | **File name** | The output `.vpk`'s name. |

6. **Build.** The app converts your texture to VTF, writes the VMT, packs everything up, and
   drops `<name>.vpk` into your **export folder** (`export/` by default).

## Install the mod in-game

1. Copy the built `.vpk` into:
   ```
   …\Steam\steamapps\common\Team Fortress 2\tf\custom\
   ```
   (Create the `custom` folder if it isn't there yet.)
2. Restart TF2. A full restart, not just `snd_restart`. That's the one that reliably works.
3. Equip the weapon and check it in your loadout or on a map.

> **Removing a mod:** delete its `.vpk` from `tf\custom\` and restart.

## Troubleshooting

- **Weapon looks default, or shows the pink-and-black checkerboard.** The VPK isn't actually in
  `tf\custom\`, or the paths inside it don't line up with the weapon. Rebuild and re-copy.
- **Not sure why it's not applying?** Open **Diagnostics**, load your `.vpk`, and let it flag
  the usual suspects (missing `$basetexture`, wrong paths, broken VTFs).
- **Servers running `sv_pure`** block a lot of client skins outright. Test on a local
  server, or one you know allows them, before assuming your mod is broken.

## Next steps

- Want to replace the model too, not just the texture? → [Custom models](custom-models.md).
- Full option reference → [Using the app](usage.md).
