# Custom models

[← Docs index](../README.md)

A reskin only changes the texture. A **custom model** replaces the weapon's geometry itself,
which is a bigger job: it needs a working TF2 install, because the app recompiles the model
with `studiomdl` from `<TF2>\bin\`.

> You should already be comfortable exporting an **SMD** (or a finished compiled `.mdl`) from
> Blender or whatever tool you model in. This app packages and compiles models. It doesn't
> model them for you. The exception is downloaded models in **OBJ / GLB / glTF**: the app
> reads those itself and lets you fit them to the weapon without Blender, see
> [below](#a-model-from-the-internet-obj--glb).

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
   | **Shape only — the weapon's materials** | Your model is just a mesh with **every vertex bound to a single `root` bone**. Its materials collapse into the original weapon's one material, so your single texture gets mapped onto the new geometry. The simple case. |
   | **With its own materials and bones** | Your model has **its own skeleton and its own set of materials**. Separate parts stay rigged to their bones, and each material becomes its own texture slot. |

   **The cost of "shape only":** because every vertex is welded to `root`, the weapon becomes
   one rigid lump. Anything that used to move on its own bone stops behaving like a separate
   part. A magazine won't drop out during the reload animation anymore, for instance, because
   it's now fused to the body. If parts need to keep animating, rig your model to the weapon's
   skeleton and build it with **With its own materials and bones** instead.

3. **Load textures** into the resulting slot(s), same as a [reskin](reskin.md). If your model
   came in with more than one skin family baked in, a row of skin/style pills appears in the
   toolbar so you can assign a different texture to each one.

4. *Optional:* click **QC** to hand-edit the compile script: `$scale`, extra `$bodygroup`s, a
   custom `$cdmaterials`, whatever you need. This button only shows up for "own materials"
   models; a "shape only" replacement has no model-specific QC left to touch. The editor
   locks the directives the build depends on (`$modelname`, `$cdmaterials`, `$bodygroup`, bone
   and LOD definitions, and so on) behind a small padlock icon next to each block. Click the
   lock to unprotect a block before editing it, so you don't accidentally break something the
   packaging step relies on.

5. **Build.** You may be asked whether to also replace any **extra model parts** (shells,
   scopes…) during the build. Answer **No** to keep the original game part.

## A model from the internet (OBJ / GLB)

If the model was downloaded rather than made for TF2, the same **Replace model** button
accepts `.obj`, `.glb` and `.gltf`. In the file dialog pick the model **together with** its
companion files: `.mtl`, `.bin`, images (Ctrl+click) — they land in one folder so the model's
references resolve. The app converts the model into a geometry-only SMD itself (every vertex
on one bone, then step 2 as usual).

Once a custom model is in the frame (any, SMD included), a **Scale & fit** button appears
next to it. It turns on fit mode: a **translucent ghost of the original weapon** as a
reference and Blender-style controls: **G** move, **R** rotate, **S** scale — after the
key the model follows the mouse with no button held, **X / Y / Z** constrain the axis
(again to clear), left click confirms, **Esc** or right click cancels. A draggable gizmo is
there too (the icons on the right pick its tool). **Esc** with no operation running, or
**Enter**, finishes. The numbers in the panel mirror the same values and can be typed:

| Field | What it does |
|-------|--------------|
| **Scale** | One factor for all axes. |
| **Rotation** | Degrees around X, Y (up) and Z (along the barrel), in weapon axes. |
| **Offset** | Game units along the same axes. |

The fit is baked into the SMD vertices, not written as `$scale` in the QC: `$scale` would
stretch the skeleton and attachments (muzzle flash, shell ejection) too and the weapon
would drift out of the hands. The SMD is rebuilt after a pause in editing; first-person view
and the build use the fitted model. For your own SMD the bones and weights stay as they
were; only the vertices move.

Things to know:

- **Game limits** (`studio.h`): 65,536 triangles, 65,536 vertices and 32 materials per model.
  Vertices are counted *after* splitting by UV seams and hard edges. Anything above the limit
  the app **simplifies itself** (meshoptimizer, UVs preserved; normals are recomputed, edges
  sharper than 60° stay hard) to about 60,000 triangles and reports "simplified: N → M" in
  the status line. A million-triangle sculpt takes seconds. Too many materials can't be fixed
  this way — merge them in an editor.
- **Bones.** OBJ carries no bones — the model is one rigid piece, magazine and bolt won't
  animate. GLB/glTF does (a skin from Blender): name the bones as the game does
  (`weapon_bone`, `weapon_bone_1`… — see the original's QC via **Tools → Extract model**),
  model in the original's pose, pick **With its own materials and bones** — bones match by
  name and part animations work. Bones with unknown names fall onto the grip bone. A mesh
  without a skin but "parented to bone" in Blender rides that bone entirely.
- **Base colour** from `map_Kd` in the MTL or `baseColorTexture` in glTF lands in the slots
  automatically (per material for a "finished" model, on the main material for
  geometry-only). Other PBR maps (metallic, roughness, normal) mean nothing to the game.
  Without a UV map no texture will land.
- FBX is not supported — save as GLB or OBJ.

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
