# Using the app

[← Docs index](../README.md)

A full tour of the interface and every build option. For a quick task‑focused path, see
[Simple reskins](reskin.md).

## Layout

The window has three columns:

1. **Left — what you're modding** (Step 1). A tab bar switches between **Weapons**, **Hats**,
   and **Diagnostics**.
2. **Middle — preview.** 2D texture slots and an on‑demand 3D view.
3. **Right — export options** (Step 2): resolution, format, file name, **Build**, and an
   **Advanced** section.

The **gear icon** (top‑right) opens [Settings](#settings).

## Step 1 — pick your target

### Weapons tab

Choose a **Category**, then the fields below adapt:

| Category | What it builds |
|----------|----------------|
| **Weapon** | A stock weapon — pick Class → Slot → Weapon |
| **Character** | Player body parts and viewmodel hands (per class); Spy disguise masks |
| **Special** | Crit effect, spray, or death effects (ice / gold / fire) |
| **Projectile / Pickup / Taunt** | Rockets/arrows, health/ammo pickups, taunt props |
| **Skybox** | Replace the sky (all maps at once, or one named sky) |
| **Custom** | A `.vpk` mod you loaded into the 3D view |

### Hats tab

Browse cosmetics, pick one, and (optionally) edit **per class** and **per style**. During the
build you're asked whether **game paints** should apply to your texture.

### Diagnostics tab

Load an existing `.vpk` mod and the app inspects it for common problems (missing `$basetexture`,
wrong paths, VTF issues). Use it to debug a mod that "doesn't show up" in‑game.

## Step 2 — preview

The middle column has a toolbar:

| Control | What it does |
|---------|--------------|
| **3D / 2D** | Switch between the 3D model and the flat texture view |
| **Cube** — *Load 3D model* | **Renders the current weapon in 3D. The 3D view does not load by itself — press this after selecting.** |
| **VPK** | Load an existing `.vpk` mod into the 3D view |
| **🔄** | Replace the model with your own (see [Custom models](custom-models.md)) |
| **QC** | Edit the model's QC script (advanced, for custom models) |
| **RED / BLU** | Appear when the item has team skins — switch team and load a per‑team texture |
| **`+`** | Appears for weapons with **no** team variant — click to add a separate BLU texture |
| **Australium** / **eye** | Gold variant toggle; utility textures (eyes, über, etc.) |

Drop images onto the **main slot** and any **extra‑material slot cards**. Clicking a material card
puts Step 2 into **per‑texture edit mode** (a yellow banner appears) so you can give that one
material its own resolution/format/flags; press **Done** to return to global settings.

## Step 2 — export options

| Option | Notes |
|--------|-------|
| **Resolution** | 256 (Spray) / 512 (Normal) / 1024 (High) / 2048 (Ultra) |
| **Format** | VTF format (`DXT1`, `DXT5`, `RGBA8888`, …). The list auto‑narrows to what the current mode allows. |
| **File name** | Output `.vpk` name (max 50 chars, no `\ / : * ? " < > \|`). |
| **Build** | Runs the build; result goes to your export folder. |

### Advanced section

- **VTF flags** — `Clamp S`, `Clamp T`, `No Mipmaps`, `No LOD`, `No minimum Mipmap`, plus
  `Normal Map`, `No Thumbnail`, `No Reflectivity`, and `Gamma Correction` (with a value).
- **Material Maps…** — add detail / self‑illum / phong maps from images; the app builds the VTFs
  and wires the VMT. (Models only.)
- **Edit VMT…** — hand‑edit the VMT of the selected material. Each material keeps its own edits.
- **Isolate shoulders** — hands only; renames the arm/shoulder material so your edit doesn't
  affect the world character.
- **Tools** — *Extract Original Model (SMD)*, *Export UV Template (PNG)*, *Extract Original
  Texture*, and *Merge VPK* (combine several mods into one).

## Building & installing

1. Click **Build**. Progress is shown; the app may ask about extra materials/parts along the way.
2. The finished `<name>.vpk` lands in your **export folder** (`export/` by default).
3. Copy it into `…\Team Fortress 2\tf\custom\` and restart TF2.
4. To remove a mod, delete its `.vpk` from `tf\custom\` and restart.

> **`sv_pure`:** many servers block client‑side skins. Test locally or on servers that allow them.
> The Settings **sv_pure bypass** option only affects how *model* materials are foldered — it is
> not a guarantee.

## Settings

Open with the gear icon (top‑right).

- **Paths** — **TF2 Game Folder** (must contain `tf/` and `bin/`) and **Export Folder**.
- **Preferences** — **Language** (English / Русский), **Export Format**, **Theme** (Dark / Blue),
  **sv_pure bypass** (`console\` default or `vgui\replay\thumbnails\`).
- **Developer** — **Keep temp files** and **Debug mode** (for troubleshooting/bug reports),
  **Clear Model Cache** (delete cached decompiled models — use after a TF2 update if builds break),
  and a **Material blacklist** (patterns of materials to never show or write; one per line,
  prefix `=` for an exact name).

## See also

- [Simple reskins](reskin.md)
- [Custom models](custom-models.md)
- [Building from source](building-from-source.md)
