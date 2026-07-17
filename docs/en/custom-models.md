# Custom models

[← Docs index](../README.md)

A reskin only changes the texture. A **custom model** replaces the weapon's geometry itself,
which is a bigger job: it needs a working TF2 install, because the app recompiles the model
with `studiomdl` from `<TF2>\bin\`.

> You should already be comfortable exporting an **SMD** (or a finished compiled `.mdl`) from
> Blender or whatever tool you model in. This app packages and compiles models. It doesn't
> model them for you.

## How it works

When you hand the app a custom model, it:

1. **Decompiles** the original weapon with the bundled Crowbar, to get its QC and reference SMD.
2. **Swaps in your geometry.** Your SMD replaces the reference mesh.
3. **Recompiles** the QC into a `.mdl` using `studiomdl.exe` from your TF2 install.
4. **Packs** the model, materials, and VMTs into the `.vpk`.

The decompiled original is cached so repeat builds are faster. If a TF2 update ever breaks
compilation, clear it from **Settings → Clear Model Cache** and try again.

## Steps

1. **Select the weapon** you're replacing (Weapons tab → Class → Slot → Weapon). Your model
   takes over this weapon's slot and file paths.

2. **Load your model.** Click **Replace model** in the preview toolbar and pick your `.smd`. The
   app then asks how to treat its materials:

   | Choice | Use when |
   |--------|----------|
   | **No, geometry only** | Your model is just a mesh with **every vertex bound to a single `root` bone**. Its materials collapse into the original weapon's one material, so your single texture gets mapped onto the new geometry. The simple case. |
   | **Yes, keep materials** | Your model has **its own skeleton and its own set of materials**. Separate parts stay rigged to their bones, and each material becomes its own texture slot. |

   **The cost of "geometry only":** because every vertex is welded to `root`, the weapon becomes
   one rigid lump. Anything that used to move on its own bone stops behaving like a separate
   part. A magazine won't drop out during the reload animation anymore, for instance, because
   it's now fused to the body. If parts need to keep animating, rig your model to the weapon's
   skeleton and build it with **Yes, keep materials** instead.

3. **Load textures** into the resulting slot(s), same as a [reskin](reskin.md). If your model
   came in with more than one skin family baked in, a row of skin/style pills appears in the
   toolbar so you can assign a different texture to each one.

4. *Optional:* click **QC** to hand-edit the compile script: `$scale`, extra `$bodygroup`s, a
   custom `$cdmaterials`, whatever you need. This button only shows up for "keep materials"
   models; a "geometry only" replacement has no model-specific QC left to touch. The editor
   locks the directives the build depends on (`$modelname`, `$cdmaterials`, `$bodygroup`, bone
   and LOD definitions, and so on) behind a small padlock icon next to each block. Click the
   lock to unprotect a block before editing it, so you don't accidentally break something the
   packaging step relies on.

5. **Build.** You may be asked whether to also replace any **extra model parts** (shells,
   scopes…) during the build. Answer **No** to keep the original game part.

## Troubleshooting

- **Build fails at compile.** Usually a QC/SMD problem `studiomdl` rejects: a bad flex, a
  missing material, a malformed bone. Turn on **Debug mode** and **Keep temp files** in
  Settings and check `tf2sg.log`.
- **`studiomdl.exe not found`.** Your **TF2 Game Folder** is wrong, or TF2 isn't fully
  installed. The file needs to exist at `<TF2>\bin\studiomdl.exe`.
- **Model is invisible, or the wrong size.** A scale/origin mismatch. Adjust `$scale` /
  `$origin` through the **QC** editor.
- **Everything broke after a TF2 update.** **Settings → Clear Model Cache**, then rebuild.

## See also

- [Simple reskins](reskin.md) · [Using the app](usage.md)
