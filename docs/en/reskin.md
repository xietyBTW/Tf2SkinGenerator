# Your first skin

[Documentation](../README.md) · [Русская версия](../ru/reskin.md)

This guide takes one weapon from the catalog to the game. The example is the Scout's Scattergun, but every weapon works the same way, and so do projectiles, pickups and taunt props. A reskin keeps the game's model and replaces its texture, which makes it the quickest kind of mod and a good way to learn the app.

## Before you start

You need two things.

**The game path.** On first launch the app finds TF2 by itself or asks for the folder. The bottom bar shows where the game was found. If it says the game wasn't found, open **Settings** in the top right corner and fill in **Game folder** (the one with `tf` and `bin` inside), or press **Detect automatically**.

**An image.** PNG, JPG, TGA, BMP, WEBP and GIF all work, and so does a ready VTF. The size doesn't have to match anything: the app scales the image to the resolution you pick before building. If you plan to use transparency, keep the alpha channel in the file.

If you don't know how the texture is laid out yet, pick the weapon first and use **Tools → Export UV template (PNG)**. You get a picture of the model's UV layout to paint over. **Tools → Extract original texture** saves the game's own texture, which is often an even better starting point.

## 1. Pick the item

Click the item name at the top of the window. Until you pick something it reads **Select an item**. The catalog opens with a search box, a category list and filters.

1. Leave **Category** on **Weapon**.
2. Narrow the list with **Class** and **Type** (primary, secondary, melee, and the watch and PDA slots for the classes that have them). Both filters work on their own: **Type → Melee** with no class selected shows every melee weapon in the game.
3. Or type in the search box. Every word you type has to appear in the weapon name, the model file name or the class, in any order, so `scatter scout` and `c_scattergun` both find the Scattergun.
4. Click the weapon card.

The catalog closes and the model starts loading. The first time you open a weapon, the app extracts the model from the game archives and decompiles it with Crowbar, which takes a few seconds. After that it comes from the cache almost instantly.

> [!TIP]
> If the catalog keeps getting in the way, turn on **Settings → Pin the panels**. The catalog then stays on the left and the build settings on the right. This needs a window wider than 1100 pixels.

## 2. Find your way around the album

With the default **Together** view, the window is split in two. The textures are on the left, the 3D model is on the right. The buttons **Together**, **Texture** and **Model** at the top switch between both halves and one of them.

The left half is the album: one card per material of the model. Most weapons have one or two materials, some have more (a separate scope, shells, a strap). You can move between cards with the tabs above the album, the arrows at its sides or the mouse wheel. The counter under the album shows which card you're on, for example `02 / 03`.

The card the album stops on is the one the model wears in the preview. This matters for items that share one mesh between several textures, like the Spy's disguise masks.

## 3. Put your image on the model

There are three ways to do it.

- **Drag the image onto a card.** The card highlights while you hold the file over it.
- **Double-click a card** to choose a file in a dialog.
- **Drop the image onto the model itself.** The app highlights the piece under the cursor, and the image lands on that piece only. This opens painting by parts, which is described in [its own guide](model-parts.md).

The preview updates right away. An animated GIF becomes an animated texture: the build turns its frames into a multi-frame VTF and adds the animation proxy to the material.

To start over on a card, drop another image on it. <kbd>Ctrl</kbd>+<kbd>Z</kbd> undoes the last steps and <kbd>Ctrl</kbd>+<kbd>Y</kbd> brings them back. To return the whole item to its game look, use **Discard edits** under the album. It also deletes the item's saved draft, so use it when you really want a clean start (see [works and drafts](works-and-mods.md)).

## 4. Team colors, Australium and other variants

Many items look different for RED and BLU, and some have extra versions. The app shows only the buttons that make sense for the loaded model, so don't be surprised if your toolbar has fewer of them than this list.

| Control | Where | What it does |
|---|---|---|
| **RED** / **BLU** | top bar | Appear when the model has separate team textures. Switch to **BLU** and drop a second image to give the blue team its own look. If the game's BLU version looks exactly like RED, hovering **BLU** says so. |
| **Make team-colored** | under the model | Appears when the weapon has no team variant in the game. After you press it, **RED** and **BLU** show up and the build adds the blue material to the model. Give BLU its own image, or leave it empty and answer **Copy the main one** when the build asks about it. |
| **Australium** | top bar | Appears when the weapon has a gold version. While it's on, the album shows the Australium card, and an image dropped there goes to the gold version only. If you leave it alone, the gold version keeps its in-game look. |
| **Other** | under the album | Shows the model's service materials: eyes, teeth, invulnerability (über) overlays, zombie skins, sheen overlays. They are hidden by default because they rarely need changes. |
| **Style** | under the model | Extra skins baked into the model, such as the clean and bloody versions of some melee weapons. **Default** is the base skin. A style takes the base textures until you give it its own. |
| **Version** | under the model | **Regular**, **Festive** and **Festivized**: shows the festive lights the game hangs on this weapon. Lights you repaint or fit go into the mod as a separate model and don't affect other weapons. |
| **Model state** | under the model | Some models change on their own in game: a bottle breaks, the Caber loses its head after the explosion. These buttons let you look at each state. They only change the preview, every state goes into the mod. |

When a material has separate RED and BLU versions and you give only one of them an image, the build asks what to do with the other. That question is described in [step 7](#7-build).

## 5. Check it from every side

The 3D view uses the usual mouse controls:

| Action | Mouse |
|---|---|
| Rotate | Left button, drag |
| Zoom | Wheel |
| Pan | Right button, drag |

The buttons above the model switch the scene:

- **Model** is the item on its own, with a free camera.
- **First person** puts the weapon in the hands of its class, the way you'll see it in game. An **Animation** row appears under the view with the animations this weapon has in game, such as idle, draw, fire and inspect. The festive lights, if you turned them on, are shown here too.

Press <kbd>F11</kbd> to expand the 3D view to the whole window, and <kbd>F11</kbd> or <kbd>Esc</kbd> to get back.

## 6. Build settings

The bottom bar shows a summary of what will be built: size, VTF format, the estimated size of one texture and the file name. Click **Parameters** to open the build settings.

| Setting | What to choose |
|---|---|
| **Resolution** | 256, 512, 1024 or 2048 pixels per side. 512 is the default. 1024 looks noticeably sharper up close, 2048 is worth it for large, detailed items. The summary shows the cost: one DXT5 texture is about 1.3 MB at 1024 and about 5.3 MB at 2048. |
| **VTF format** | `DXT1` is compressed and has no transparency. `DXT5` is compressed and keeps the alpha channel. `RGBA8888` is uncompressed, the best quality at four times the size. The list contains only the formats that make sense for the selected item. |
| **VPK name** | The file name of the mod. The app suggests one based on the item, for example `scattergun_mod.vpk`, and stops suggesting once you type your own. Up to 50 characters, and none of `\ / : * ? " < > \|`. |
| **VTF flags** and **Options** | Leave them as they are unless you know you need them. They are explained in the [interface tour](usage.md#build-settings). |

**One texture, its own settings.** Each card has a small settings button in its corner (two sliders). Clicking it switches the build panel to that material only: a bar with its name appears on top, and whatever you change applies to this material alone. A badge on the card shows that it has its own settings. **Done** returns to the common settings, **Reset** drops the material's own settings. Use it when, say, a small detail doesn't need 2048 while the main texture does.

## 7. Build

Click **Build VPK** in the bottom right corner. While the build runs, the button turns into **Cancel**, and the bottom bar shows each step. The app may ask a few questions on the way:

| Question | When it appears | Answers |
|---|---|---|
| **What to put on "material"** | A material has no image of yours. It also covers the BLU version of a material when you painted only RED. | **Keep the game one** leaves the material out of the mod, so the game's texture stays. **Copy the main one** puts your main texture on it. **Pick a file…** takes a separate image. The checkbox **Same for the rest of the materials** applies your answer to the rest of this build. Closing the window cancels the build. |
| **The game will paint the item …** | The material takes its color from the VMT wherever the texture's alpha is white, and your image has no alpha, so in game the whole item would turn one color. | **As in the image** keeps what you see in the preview. **Remove paint from the VMT** gives the same result and also strips the paint parameters from the material. **Paint like the game** colors only the areas the game colors on the original. **Build as is** paints the whole item. |
| **No changes** | There's no image of yours, no VMT edit, no material maps, no custom model. | **Build anyway** builds a mod with the game's own look, which is useful for testing paths. |
| **Custom model for the "part" part** | Only with a [custom model](custom-models.md) when the weapon has extra model states. | Keep the game part or choose an SMD for it. |

When the build is done, the bottom bar shows **Built: name.vpk**. The file is in the export folder, which you can open with **Tools → Open export folder**. In the installed app it is `%LOCALAPPDATA%\Tf2SkinGenerator\export` unless you chose another folder in the settings.

If the build fails, a window explains what went wrong in plain words. **Technical details** shows the original error message, **Open the log** opens the folder with `tf2sg.log`, and **Copy** puts the whole thing on the clipboard for a bug report.

## 8. Install the mod and test it

1. Copy the `.vpk` into the game's `custom` folder:
   ```
   ...\Steam\steamapps\common\Team Fortress 2\tf\custom\
   ```
2. Restart TF2 completely. Mods are read when the game starts, so a running game won't pick them up.
3. Open your loadout and look at the weapon, or start a local game.

To remove the mod, delete its `.vpk` from `tf\custom` and restart the game.

The quickest place to check a mod is a local game, for example one started with the console command `map ctf_2fort`, because nothing there blocks custom files. If the skin works offline but not on some servers, read about [sv_pure](troubleshooting.md#casual-servers-and-sv_pure). If it doesn't work anywhere, open **Diagnostics** and let the app check the file (see [troubleshooting](troubleshooting.md#checking-a-mod-with-diagnostics)).

## Where to go next

- [Painting by parts](model-parts.md): color only the barrel, put a logo on the stock, add an outline.
- [War Paint](war-paint.md): start from an in-game War Paint instead of a blank texture.
- [Materials and effects](materials.md): glow, metallic gloss, reflections, transparency.
- [Custom models](custom-models.md): change the shape of the weapon, not only its texture.
- [Interface tour](usage.md): everything the window can do.
