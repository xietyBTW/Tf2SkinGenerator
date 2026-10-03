# Works, drafts and the mod library

[Documentation](../README.md) · [Русская версия](../ru/works-and-mods.md)

The app keeps your edits between sessions in two ways: silent drafts and saved works. This page explains how they differ, how undo works, how to open someone else's VPK mod and build on top of it, and how to merge several mods into one file.

## Drafts

While **Settings → Keep a draft of edits** is on (it is by default), every edit of an item is written to disk right away: images on cards, parts, material maps, per-texture settings, a custom model and its fit, the QC, team mode, festive lights, War Paint layouts. You never have to remember to save, and a crash or a power cut doesn't lose your work.

A draft belongs to the item, and it's not a mod or a work yet. When you open the same item from the catalog later, it opens with its game look, and the **Restore edits** button under the album offers the draft back.

> [!IMPORTANT]
> Each item has one place for its edits. If you open an item from the catalog and start editing without pressing **Restore edits**, the new edits replace the old draft, and the same happens to a saved work of that item. To continue earlier work, open it from **Custom Mod** or press **Restore edits** first.

**Discard edits** throws away both the current edits and the draft on disk, and returns the item to its game look.

Drafts take disk space, mostly for copies of your images. **Settings → Delete drafts…** lists them with their sizes. Everything is ticked by default; untick what you want to keep and press **Delete**. Saved works aren't in that list and aren't affected.

With **Keep a draft of edits** turned off, the app writes nothing on its own. Only **Save work** stores the item then.

## Saved works

**Save work** under the album turns the item's edits into a work. Works are what you come back to: they're listed in the catalog, in the **Custom Mod** category, with their names and when they were saved ("today", "yesterday", "3 days ago").

Clicking a work opens the item together with all its edits. A cosmetic opens on the style where you left it, with the edits of its other styles in place. A work made on top of a VPK mod reopens the mod first and then puts your edits back.

Once the item is saved as a work, further edits keep being written into it, and the button under the album turns into **Delete work**. That button deletes the work and returns the item to its game look.

### What a work contains

| Part of the item | In the work |
|---|---|
| Images on cards, for every team, style and variant | yes |
| Painting by parts: colors, images and their placement, cuts, outlines | yes |
| Material maps and per-texture settings | yes |
| Custom model, its fit and its QC edit | yes |
| Team mode (**Make team-colored**), festive lights, War Paint layouts | yes |
| VMT edits | no: they belong to the material name, see [Materials and effects](materials.md#good-to-know) |
| Build settings: resolution, format, file name | no: they're the same for all items |

## Undo and redo

Every item has one history of edits: <kbd>Ctrl</kbd>+<kbd>Z</kbd> undoes the last one, <kbd>Ctrl</kbd>+<kbd>Y</kbd> (or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>) redoes it. The history covers images, parts, a custom model and the rest of the item's work. It starts over when you open another item.

The particle editor keeps a separate history of its own, with the same keys and the **Undo** and **Redo** buttons under the preview.

## The mod library

The **Custom Mod** category also holds VPK mods you've opened: your older builds or someone else's mods.

**Open a VPK mod…** picks a `.vpk` from disk. The app copies it into its library and opens it: the mod's model and textures replace what was on screen, and the title shows the mod's name. From there you can work with it like with any item: repaint its textures, cut it into parts, apply a War Paint. **Build VPK** makes a new mod based on the opened one, with your changes on top.

The library keeps a copy, so the mod stays available even if you delete or move the original file. Cards show the mod's size and, where the app can find one, its texture as a cover. The **×** on a card removes the copy from the library. The file you originally opened stays where it was.

Some tools aren't available for opened mods. The VMT editor can't edit a mod's materials. There's no first-person view, because the mod contains an already compiled model and the app can't tell what weapon is inside. When the mod brings a model of its own, War Paints work in universal mode only.

## Merging several mods into one

**Tools → Merge several VPKs into one** combines mods from the export folder into a single file. It's handy for sharing a set of skins, or for keeping `tf/custom` tidy.

1. Tick at least two mods in the list and press **Next**.
2. Enter a name for the result (`merged_mod.vpk` by default).
3. If two of the mods change the same item, the app warns you and lists which mods touch which item. Only one version of a file can survive in a VPK, so one mod will override the other. Confirm with **Merge** or cancel and pick the mods again.

The merged mod appears in the export folder.

## See also

- [Settings and data folders](settings.md): where drafts, works and the library are stored.
- [Installing mods and troubleshooting](troubleshooting.md): checking a mod with Diagnostics.
