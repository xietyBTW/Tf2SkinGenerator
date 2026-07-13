# Simple reskins

[← Docs index](../README.md)

A "reskin" keeps the stock weapon model and only replaces its **texture**. This is the fastest
kind of mod and the best place to start.

## Before you begin

- TF2 must be installed and the **game folder** set in Settings (see the
  [main README](../README.md#first-time-setup)).
- Have your texture ready as a `PNG`, `JPG`, `TGA`, `BMP`, or existing `VTF`.
- Not sure of the size/layout? Load the weapon first, export its **UV template** from the preview,
  and paint over that.

## Steps

1. **Pick the weapon.** In the left panel choose **Category → Weapon**, then
   **Class → Slot (Primary / Secondary / Melee) → Weapon**.

2. **Show it in 3D (optional).** The 3D view does **not** load automatically. In the preview
   toolbar, click the **cube button** (*Load 3D model*) to render the selected weapon. The 2D
   view updates on its own. Toolbar buttons:

   | Button | Does |
   |--------|------|
   | **3D / 2D** | Switch between the 3D model and the flat 2D texture view |
   | **Cube** (*Load 3D model*) | Renders the current weapon in 3D — press it after selecting |
   | **VPK** | Load an existing `.vpk` mod into the 3D view |
   | **Replace model** | Swap in your own model (see [Custom models](custom-models.md)) |

3. **Load your texture.** Drag your image onto the **main texture slot** (or use the Browse
   button on the slot). The preview reflects it right away.

   - The model may have **extra materials** (scope lens, shell, etc.). You can pre‑load textures
     for those on the extra slot cards, or answer the prompt during the build
     (*Upload mine / Use game original / Use main texture*).

4. **RED / BLU team textures.**

   - If the weapon already has separate team skins, **RED** and **BLU** toggle buttons appear in
     the toolbar. Switch to **BLU** and load a second texture for the blue team.
   - If the weapon has **no** team variant in the base game, a **`+` button** appears instead
     (*Make weapon team‑colored: add a separate BLU texture*). Click it to turn on team mode — the
     RED/BLU toggles appear and the app synthesizes the blue material at build time. Leave BLU
     empty to reuse the RED texture for both teams.
   - Some weapons also expose an **Australium/Gold** toggle, and an **eye button** for utility
     textures (eyes, übercharge, etc.).

5. **Set the output options** on the right:

   | Option | Notes |
   |--------|-------|
   | **Resolution** | 256 / 512 / 1024 / 2048. Higher = sharper and larger file. |
   | **Format** | `DXT1` (no alpha) or `DXT5` (with alpha / transparency). |
   | **VTF flags** | `Clamp S/T`, `No Mipmaps`, `No LOD` — leave default unless you know you need them. |
   | **File name** | The output `.vpk` name. |

6. **Build.** Click **Build**. The app converts the texture to VTF, writes the VMT, packs
   everything, and drops `<name>.vpk` into your **export folder** (`export/` by default).

## Install the mod in‑game

1. Copy the built `.vpk` into:
   ```
   …\Steam\steamapps\common\Team Fortress 2\tf\custom\
   ```
   (Create the `custom` folder if it doesn't exist.)
2. Restart TF2 (or `snd_restart` won't do it — a full restart is safest).
3. Equip the weapon and check it in a loadout / on the map.

> **Removing a mod:** delete its `.vpk` from `tf\custom\` and restart.

## Troubleshooting

- **Weapon looks default / pink‑black checkerboard** — the VPK isn't in `tf\custom\`, or the
  file paths inside don't match the weapon. Rebuild and re‑copy.
- **Not sure why it doesn't apply** — open the **Diagnostics** tab and load your `.vpk`; it flags
  common problems (missing `$basetexture`, wrong paths, VTF issues).
- **Servers with `sv_pure`** — many servers block client skins. Test on a local server or a
  casual/community server that allows them.

## Next steps

- Replace the model itself → [Custom models](custom-models.md).
- Full option reference → [Using the app](usage.md).
