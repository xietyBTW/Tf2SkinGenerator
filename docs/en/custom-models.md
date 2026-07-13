# Custom models

[← Docs index](../README.md)

A reskin only changes the texture. A **custom model** replaces the weapon's geometry itself. This
is more involved: it requires a working TF2 install, because the app recompiles the model with
`studiomdl` from `<TF2>\bin\`.

> Prerequisite knowledge: you should be comfortable exporting an **SMD** (or a finished compiled
> `.mdl`) from Blender / a modeling tool. This app packages and compiles — it does not model.

## How it works

When you supply a custom model, the app:

1. **Decompiles** the original weapon with Crowbar (bundled) to get its QC and reference SMD.
2. **Swaps in your geometry** (your SMD replaces the reference mesh).
3. **Recompiles** the QC into a `.mdl` with `studiomdl.exe` from your TF2 install.
4. **Packs** the model, materials and VMTs into the `.vpk`.

The decompiled original is cached to speed up repeat builds (clear it from **Settings → Clear
Model Cache** if a TF2 update breaks compilation).

## Steps

1. **Select the weapon** you're replacing (Weapons tab → Class → Slot → Weapon). Your custom model
   takes this weapon's slot and paths.

2. **Load your model.** In the preview toolbar click the **Replace model** button and pick your `.smd`.
   The app asks how to treat its materials:

   | Choice | Use when |
   |--------|----------|
   | **No, geometry only** | Your model is just a mesh, with **all vertices bound to a single `root` bone**. Its materials collapse into the original weapon's single material — your one texture is mapped onto the new geometry. Simplest case. |
   | **Yes, keep materials** | Your model already has **both a proper skeleton (its own bones) and its own material set**. Separate parts stay rigged and each material becomes its own texture slot. |

   **What "geometry only" costs you:** because every vertex is welded to `root`, the weapon becomes
   one rigid piece. Any component that in the original moves on its own bone stops moving as a
   separate part. For example, a **magazine won't drop out during the reload animation** — it's
   fused to the body. If you need parts to animate, your model must be rigged to the weapon's
   skeleton and built with **Yes, keep materials**.

3. **Load textures** into the slot(s), exactly like a [reskin](reskin.md).

4. *(Optional)* Click **QC** to hand‑edit the compile script — for `$scale`, extra
   `$bodygroup`s, custom `$cdmaterials`, etc.

5. **Build.** During the build you may be asked whether to also replace **extra model parts**
   (shells, scopes…). Answer **No** to keep the original game part.

## Troubleshooting

- **Build fails at compile** — usually a QC/SMD issue `studiomdl` rejects (bad flex, missing
  material, malformed bone). Enable **Debug mode** + **Keep temp files** in Settings and read
  `tf2sg.log`.
- **`studiomdl.exe not found`** — your **TF2 Game Folder** is wrong or TF2 isn't fully installed;
  the file must exist at `<TF2>\bin\studiomdl.exe`.
- **Model is invisible / wrong size** — scale/origin mismatch; tweak `$scale` / `$origin` via the
  **QC** editor.
- **Broke after a TF2 update** — **Settings → Clear Model Cache**, then rebuild.

## See also

- [Simple reskins](reskin.md) · [Using the app](usage.md)
