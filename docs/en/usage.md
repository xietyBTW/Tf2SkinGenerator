# Using the app

[← Docs index](../README.md)

A full tour of the interface, option by option. If you just want to get a texture into the
game as fast as possible, [Simple reskins](reskin.md) is the shorter path.

## Layout

Three columns:

1. **Left: what you're modding** (Step 1). A tab bar at the top switches between **Weapons**,
   **Hats**, and **Diagnostics**.
2. **Middle: preview.** 2D texture slots, plus a 3D view you load on demand.
3. **Right: export options** (Step 2): resolution, format, file name, **Build**, and an
   **Advanced** section.

The **gear icon** in the top-right corner opens [Settings](#settings). Switching to the
**Diagnostics** tab replaces the middle and right columns entirely with the diagnostics list.
That's expected, not a bug; Step 2 has nothing to do while you're just inspecting a `.vpk`.

## Step 1: pick your target

### Weapons tab

Pick a **Category** and the fields below it change to match:

| Category | What it builds |
|----------|----------------|
| **Weapon** | A stock weapon: pick Class → Slot → Weapon |
| **Character** | Player body parts and viewmodel hands (per class), plus Spy disguise masks |
| **Special** | Crit effect, spray, or a death effect (ice / gold / fire) |
| **Projectile / Pickup / Taunt** | Rockets/arrows, health/ammo pickups, taunt props |
| **Skybox** | Replace the sky, either every map at once or one specific named sky |
| **Custom** | A `.vpk` mod you've loaded into the 3D view, for inspecting or extending it |

Pick **Character → Spy disguise mask** and a row of small class buttons appears above the
toolbar. Each one loads that class's disguise mask so you can retexture it separately.

### Hats tab

There's more here than "browse and pick." Along the top: a **search box** that filters as you
type, a **refresh** button (↺) that re-reads `items_game.txt` from scratch (useful if you just
changed something in your TF2 install and the list looks stale), and a **filter** button
(funnel icon) with three toggles: **hide medals**, **hide Halloween items**, **hide seasonal
items** (Christmas etc.). Those choices are remembered between sessions. Below that is a row of
class chips to narrow the list to one class at a time.

Pick a hat and, if it has multiple **styles** or applies to multiple **classes**, a panel opens
below the list: a **"Build for styles"** row (pick one to edit; a dot marks styles you've
already customized) and a **"Build for classes"** row (checkboxes, at least one has to stay on).
During the build you'll be asked whether **game paints** should apply to your texture. Default
is yes.

### Diagnostics tab

Drop a `.vpk` on the tab (or use the **Choose VPK** button, which becomes **Re-check** once
something's loaded) and the app scans it for the usual reasons a mod fails to show up: missing
`$basetexture`, wrong paths, broken VTFs. Results show as colour-coded cards, red for errors,
amber for warnings, green for informational, each with a location and a suggested fix.

## Step 2: preview toolbar

Buttons appear or hide depending on what's selected, so don't worry if your toolbar looks
sparser than this list. Most of these only show up when they're relevant.

| Control | What it does |
|---------|--------------|
| **3D / 2D** | Switch between the 3D model and the flat texture view |
| **Cube icon** *(Load 3D model)* | Renders the current selection in 3D. **The 3D view never loads by itself, you have to press this after picking something.** |
| **VPK** | Load an existing `.vpk` mod into the 3D view, e.g. to inspect it or build on top of it |
| **Replace model** | Swap in your own model, see [Custom models](custom-models.md) for the full flow |
| **QC** | Opens the model's compile script for editing. Only shows up for custom models loaded with "keep materials" (rigged models); a "geometry only" replacement has no QC button because there's nothing model-specific left to edit |
| **RED / BLU** | Shows up when the item has separate team skins. Switch teams and load a texture for each |
| **`+`** | Shows up instead of RED/BLU when the weapon has no team variant in the base game. Click it to turn on team mode: RED/BLU toggles appear, and the app builds the blue material for you. Leave BLU empty and both teams get the RED texture |
| **Skin/style pills** | For custom or replaced models that come with multiple skin families baked in, one pill per skin, letting you assign a different texture per style |
| **Australium button** (gold icon) | Shows up when the app finds a gold/Australium variant of the current weapon. Toggle it to preview and retexture that variant separately from the normal one |
| **Eye icon** *(service textures)* | A separate button from Australium, shows up when the model has hidden "misc" materials (eyes, übercharge glow, etc.) worth exposing. Click it to reveal them for optional replacement |

Drop images onto the **main slot** or any of the extra-material cards in the row below the
toolbar. Clicking the card itself just opens a file picker for that material. To give one
material its *own* resolution, format, or flags, click the small **gear icon** in the card's
corner instead. That switches Step 2 into per-texture edit mode (a yellow banner appears);
click **Done** to go back to the global settings.

## Step 2: export options

| Option | Notes |
|--------|-------|
| **Resolution** | 256 (Spray) / 512 (Normal) / 1024 (High) / 2048 (Ultra) |
| **Format** | VTF format (`DXT1`, `DXT5`, `RGBA8888`, …). The list narrows itself to whatever the current material actually supports |
| **File name** | The output `.vpk` name: 50 characters max, and none of `\ / : * ? " < > \|` |
| **Build** | Runs the build and drops the result in your export folder |

### Advanced section

- **VTF flags**: `Clamp S`, `Clamp T`, `No Mipmaps`, `No LOD`, `No minimum Mipmap`, plus
  `Normal Map`, `No Thumbnail`, `No Reflectivity`, and `Gamma Correction` (with its own value
  field).
- **Material Maps…** *(models only)*: feed the app a plain image and it generates a properly
  formatted VTF and wires up the VMT for you, which saves you from hand-guessing formats and
  paths. Seven map types are available: **detail layer**, **self-illumination** (a glow mask),
  **Phong map** (gloss/shine), **reflection mask** (chrome vs. matte), **rim light** (a soft
  edge glow), **Phong warp** (tints the highlights instead of leaving them white), and
  **lightwarp** (restyles how light and shadow fall, the classic TF2 cartoon look).
- **Edit VMT…**: hand-edit the VMT of the selected material directly, with syntax highlighting
  and autocomplete for `$params`. The **Insert** menu drops in common parameters, proxies, or
  whole templates; **Reset to game original** throws away your edits and restores the game's
  VMT. Each material keeps its edits independently of the others.
- **Isolate shoulders**: hands only. Renames the arm/shoulder material so your edit doesn't
  bleed onto the world-model character.
- **Tools**: four buttons, not a menu.
  - *Extract Original Model (SMD)* decompiles the current weapon and opens a checklist of
    every extracted file (reference SMD, LODs, etc.) so you can pick which ones to save.
  - *Export UV Template (PNG)* gives you a flat UV layout to paint over.
  - *Extract Original Texture*: for character skins this opens a thumbnail picker over every
    VTF in that character's folder; for everything else it just grabs the current material.
  - *Merge into One* combines several built mods into a single `.vpk`. Pick the mods, name
    the result, and if the same weapon shows up in more than one of them you'll get a warning
    before it overwrites anything.

## Building & installing

1. Click **Build**. You'll see progress, and the app may ask a question or two along the way.
   See below.
2. The finished `<name>.vpk` lands in your **export folder** (`export/` by default).
3. Copy it into `…\Team Fortress 2\tf\custom\` and restart TF2.
4. To remove a mod, delete its `.vpk` from `tf\custom\` and restart.

Things the app might ask you during a build:

- **A material has no texture yet**: pick *Upload mine*, *Use game original*, or *Use main
  texture* (the default). Tick *apply to all remaining* if you want the same answer for every
  material left. If you already loaded something for that slot via its card, you won't see this
  prompt at all, the app just uses what you gave it.
- **The weapon has an extra model part** (a shell, a scope lens…): you're asked whether to
  replace it too. Answering *No* keeps the original game part, which is what most people want.
- **Keep-materials builds only:** if the texture count doesn't match what the app expected, it
  warns you before packing anything, so you can cancel and check your model instead of shipping
  a broken mod.

> **`sv_pure`:** a lot of servers block client-side skins outright. Test locally or on a server
> that allows them before assuming something's wrong with your mod. The **sv_pure bypass**
> setting only changes which folder *model* materials get written to. It's not a guarantee
> against every server's rules.

## Settings

Open with the gear icon, top-right. It's one scrollable dialog with a few labeled sections
rather than real tabs:

- **Paths**: **TF2 Game Folder** (must contain `tf/` and `bin/`) and **Export Folder**.
- **Preferences**: **Language** (English / Русский), **Export Format** (the image format used
  when *extracting* a texture, separate from the VTF build format in Step 2), **Theme** (Dark /
  Blue), and **sv_pure bypass** (`console\` by default, or `vgui\replay\thumbnails\`).
- **Developer**: **Keep temp files** and **Debug mode** (turn these on before filing a bug
  report), **Clear Model Cache** (deletes cached decompiled models, asks for confirmation and
  shows you how much space it'll free; use this after a TF2 update if builds start failing), and
  a **Material blacklist** (patterns of materials to hide everywhere, one per line; prefix a
  line with `=` to match the name exactly instead of as a substring).
- **Support**: a link to the developer's Steam trade page, if you'd like to say thanks.

## See also

- [Simple reskins](reskin.md)
- [Custom models](custom-models.md)
- [Building from source](building-from-source.md)
