# Custom models

[Documentation](../README.md) · [Русская версия](../ru/custom-models.md)

A reskin changes the texture. A custom model changes the shape: your geometry takes the place of the game's model, keeps the item's slot and file paths, and gets compiled into a real TF2 model. The app takes care of the compiling, so you don't need to write a QC or run `studiomdl` yourself.

The app accepts two kinds of model files:

- **SMD**, exported from Blender (with the Source Tools add-on) or another 3D editor. This is the format TF2 models are built from, and it gives you full control over bones and materials.
- **OBJ, GLB or glTF**, the formats you usually get from model sites. The app reads them itself and turns them into an SMD, so you don't need a 3D editor at all.

## How it works

1. The app decompiles the original item with Crowbar to get its QC and its reference mesh.
2. Your geometry replaces the reference mesh.
3. The QC is adjusted to your model, and `studiomdl.exe` from your TF2 installation compiles it into an MDL.
4. The model, the textures and the materials are packed into the VPK.

The decompiled original is kept in a cache, so the next builds of the same item are faster. When the game updates its model archives, the cache entry is rebuilt by itself.

## Loading a model

1. Pick the item you want to replace. Your model takes over its slot and its paths, so in game it appears wherever this item would.
2. Press **Replace model** under the 3D view.
3. In the file dialog, select the model **together with** the files it needs: the `.mtl` of an OBJ, the `.bin` of a glTF, the texture images. Hold <kbd>Ctrl</kbd> to select several files. They are stored side by side, so the references inside the model resolve.
4. The app asks **How to use the model?** and lists the materials it found in the file. The answer decides everything after this point, see the next section.

When the weapon has festive lights, the app first asks **What to replace?**: **The weapon itself** or one of its lights. See [Festive weapons](#festive-weapons-and-their-lights).

The status line reports what the app did on its own, for example how many textures it found in the file or how much it had to simplify the mesh.

## Two ways to use a model

| Choice | What happens | When to use |
|---|---|---|
| **With its own materials and bones** | Every material of your model gets its own texture card. Bones named like the game's bones keep moving in the weapon's animations. The QC can be edited. | Models made for this item: rigged to its skeleton, with your own material setup. |
| **Shape only — weapon materials** | All materials of your model collapse into the weapon's own material: one texture for everything, and the game's texture cards. The whole model is bound to a single bone. | Downloaded models and quick swaps, when you only need the shape. |

The price of **Shape only** is that the model moves as one solid piece. A magazine that used to drop out during the reload animation now stays fused to the gun, because it no longer has a bone of its own. If parts need to keep moving, rig your model to the weapon's skeleton and load it **With its own materials and bones**.

## Fitting the model

Downloaded models rarely come at the right size and angle. Once a custom model is on screen, **Scale & fit** appears under the 3D view. It turns on fitting mode:

- A translucent **ghost of the original item** appears as a reference.
- A toolbar on the right edge of the view offers **Move**, **Rotate** and **Scale**, plus **Reset fitting** and **Done**.
- A small panel shows the same values as numbers.

The controls follow Blender:

| Keys | What they do |
|---|---|
| <kbd>G</kbd>, <kbd>R</kbd>, <kbd>S</kbd> | Start moving, rotating or scaling. The model follows the mouse with no button held. |
| <kbd>X</kbd>, <kbd>Y</kbd>, <kbd>Z</kbd> | Lock the operation to an axis. Press the same key again to unlock. |
| Left click | Confirm the operation. |
| <kbd>Esc</kbd> or right click | Cancel the operation. |
| <kbd>Esc</kbd> with no operation running, or <kbd>Enter</kbd> | Finish fitting. |

You can also drag the gizmo in the view; the toolbar icons switch its tool. The numeric panel is there for exact values:

| Field | Meaning |
|---|---|
| **Scale** | One factor for all three axes. |
| **Rotation, °** | Degrees around X, Y (up) and Z (along the barrel), in the weapon's axes. |
| **Offset** | Game units along the same axes. |

The fit is baked into the vertices of the SMD instead of being written into the QC as `$scale`. A `$scale` would stretch the skeleton and the attachment points too (muzzle flash, shell ejection, the spot where an unusual effect hangs), and the weapon would drift out of the hands. The app rebuilds the SMD shortly after you stop changing the fit. The **First person** view and the build both use the fitted model. For an SMD of your own, bones and weights stay as they were; only the vertices move.

## Game limits

The engine has hard limits per model (from `studio.h` in the Source SDK):

| Limit | Value | What the app does |
|---|---|---|
| Triangles | 65,536 | Simplifies the mesh automatically. |
| Vertices | 65,536, counted after splitting along UV seams and hard edges | Simplifies the mesh automatically. |
| Materials | 32 | Can't be fixed automatically. Merge materials in a 3D editor. |

Automatic simplification uses meshoptimizer and keeps the UV layout. It brings the model down to about 60,000 triangles, recalculates the normals and keeps edges sharper than 60 degrees hard. A sculpt with a million triangles takes a few seconds, and the status line reports the result as `simplified: N → M triangles`.

## Bones and animation

- **OBJ** has no bones. The model is one rigid piece, and moving parts such as a magazine or a bolt won't animate.
- **GLB and glTF** can carry a skin from Blender. Name the bones the way the game does (`weapon_bone`, `weapon_bone_1` and so on; look at the original's QC via **Tools → Extract model (SMD)**), model the weapon in the original's pose, and load it **With its own materials and bones**. Bones are matched by name, and part animations work.
- Bones with names the game doesn't know are attached to the grip bone.
- A mesh without a skin that is parented to a bone in Blender follows that bone as a whole.

## Textures from the file

The base color of the model lands in the album by itself: `map_Kd` from an OBJ's MTL file, or `baseColorTexture` from a glTF. With **With its own materials and bones** each material gets its own texture; with **Shape only** the texture goes onto the main material. Other PBR maps (metallic, roughness, normal) mean nothing to TF2's shaders and are ignored.

A model without a UV layout can't carry a texture. Unwrap it in a 3D editor first.

## Editing the QC

**Edit QC** appears for models loaded **With its own materials and bones**. It opens the compile script the app prepared for your model: the game's QC adapted to your mesh. You can change it, for example add a `$bodygroup`, adjust an attachment or a material folder.

The title of the window says whether you're looking at the **auto QC** or at your **custom edit**. <kbd>Ctrl</kbd>+<kbd>S</kbd> saves, **Back to auto QC** throws your edit away. The app keeps the `$texturegroup` line in sync with the model's styles itself, and your other edits stay as they are. The QC edit is part of the item's work and can be undone like any other edit.

For **Shape only** models the QC isn't editable: the build assembles it from the game's QC every time.

## Model states during the build

Some weapons switch geometry by themselves in game: the bottle breaks, the Caber loses its head after the explosion. These are separate parts of the model. When your model replaced the main part, the build asks what to use for each of these states:

- **Keep the game one** leaves the state as it is in the game.
- **Choose an SMD file…** uses your own geometry for it, with bones and materials taken from the game's part.

Closing this question keeps the game's part and the build goes on.

## Festive weapons and their lights

Many weapons get festive lights in game: the festive version of the weapon or the Festivizer hangs a garland on top of the regular model. The **Version** row under the 3D view shows them: **Regular**, **Festive**, **Festivized**.

The lights are a separate model, and you can work on them separately:

- **Repaint them**: switch the version on and drop an image on the lights' card.
- **Replace them**: **Replace model** asks whether to replace **The weapon itself** or the lights. A custom garland keeps the bones of the stock one, so the game can hang it the usual way, and uses its own materials.
- **Fit them to your model**: with a custom weapon model, the lights still hang where they would on the stock weapon, and the row says so. **Fit the lights** opens the same fitting tools as for the model, plus **Bend**: drag the wire and the bulbs with the mouse, and change the grab radius with the wheel or the **Radius** field. **Straighten** removes all bends.

Edits of the lights go into the mod as a separate model and don't affect other weapons. A dot next to the version name means its lights were changed.

## Removing a custom model

**Remove custom model** brings back the game model. If you replaced both the weapon and its lights, the app asks which one to restore. **Discard edits** under the album removes the custom model too, together with all other edits of the item.

## Troubleshooting

| Problem | What to check |
|---|---|
| The build fails at compiling | `studiomdl` rejected the model: often a broken bone hierarchy, a missing material or a flex it can't read. The error window shows its message under **Technical details**, and the log has the full output. |
| `studiomdl.exe` not found | The game folder in the settings is wrong or the game isn't fully installed. The file must exist at `<TF2>\bin\studiomdl.exe`. |
| The model is invisible or huge in game | Fit it with **Scale & fit**, comparing with the ghost of the original. |
| Parts that should move are frozen | The model was loaded as **Shape only**, or its bones aren't named like the game's. |
| Purple and black checkerboard in game | A material of the model has no texture in the mod. Check that every card has an image, or answer the build's question about it. |
| The model became too simple | It was over the triangle or vertex limit and got simplified. Reduce it yourself in a 3D editor to keep control over the result. |
| FBX doesn't load | FBX isn't supported. Export to GLB or OBJ. |
| A glTF doesn't load | Its `.bin` file must be selected together with it. Saving the model as GLB (a single file) avoids the problem. |

## See also

- [War Paint](war-paint.md): War Paints on a custom model work in universal mode.
- [Painting by parts](model-parts.md): parts are rebuilt for your model's geometry.
- [Your first skin](reskin.md): textures, teams and building.
