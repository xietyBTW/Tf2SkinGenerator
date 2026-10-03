# Characters, effects and skyboxes

[Documentation](../README.md) · [Русская версия](../ru/special-items.md)

Most of the **Weapons** section works like the [first skin guide](reskin.md) describes. This page covers the categories that behave differently: class bodies and hands, the **Special** category, projectiles, pickups and taunt props, and skyboxes. All of them are in the **Category** list of the catalog.

## Characters

The **Character** category lists what each class is made of. Filter by **Class** to see one class at a time.

### Player Skin

**Player Skin** is the class's body: head, clothes, gear. A body is built from a couple dozen materials, so the album is long, and the cards also show the RED and BLU versions through the team buttons. Painting by parts works on bodies too, and it's often the easiest way to recolor one element of the outfit.

A body can't be replaced with your own model. Class models have a complex skeleton, facial flexes, bodygroups and LODs, and swapping the geometry alone would almost always break something, so **Replace model** isn't offered here.

**Tools → Extract original texture** asks which of the body's textures you want before saving them.

### Hands

**Hands** are the first-person arms of the class, the ones that hold every weapon. The Engineer has two: the regular **Hands** and the MvM **Robot Hand (MvM)**.

**Team colors.** The RED and BLU buttons appear only for hands that really differ between teams, usually by the sleeve. The Scout, Spy and Heavy have neutral hands, so they have no team switch.

### Isolating the shoulders

On several classes the sleeve and shoulder in first person use the same material as the class's body in third person. Paint it, and the change shows up on the whole character model as well.

**Isolate shoulders** in the build options fixes this. The app gives that material a separate name for the first-person model only (for example `vm_engineer_red` instead of `engineer_red`), so your edit stays on the hands. The option appears only for hands. If you don't touch the shoulder card, the shoulders keep the game's texture.

### Spy disguise masks

**Disguise Masks** contains the masks the Spy wears when disguised, one card per class. All of them sit on the same head model, so the 3D view shows the mask of the card you're on: scroll through the album to see each one.

## Special

The **Special** category has five items that aren't models: the crit text, the spray and three death effects. They have no **Replace model**, no parts and no VMT editor, and their VTF flags are locked.

### Crit

The text that pops up over a target on a critical hit. The preview plays a real scene: a Soldier takes a headshot, and your image hangs over him as a billboard.

- The image needs transparency, so the format list contains only formats with alpha: `DXT5`, `RGBA8888`, `DXT3`.
- A GIF plays as an animation.
- The game's own crit text is 256 × 256, and that's usually enough.

The game tints the crit text with a fixed color through its particle effect. To keep the colors of your image, the mod also carries a copy of the game's `crit.pcf` with that color removed. The app makes this copy from the file in your game installation.

### Spray

A 256 × 256 image with transparency. The resolution is fixed, and so is the format. The preview has no model, so it just shows the image in the frame.

### Death effects: Ice, Gold, Fire

These replace the textures the game puts on a dying player:

| Effect | When it appears in game |
|---|---|
| **Death effect: Ice** | A player is frozen into an ice statue, for example by the Spy-cicle. |
| **Death effect: Gold** | A player is turned into a golden statue, for example by the Golden Frying Pan. |
| **Death effect: Fire** | The flames on a burning player. |

The preview shows a Soldier playing the matching death animation: a backstab for ice and gold, burning for fire. Your image covers the whole body, because that's what the game does: it replaces all of the corpse's materials with this one. Until you add an image, the preview shows the game's texture.

The mod contains only the VTF. The game's own material for these effects relies on special shaders and proxies, and a custom VMT would break them, so the app keeps the game's VMT and lets it pick up your texture from the same path.

## Projectiles, health and ammo, taunt props

These three categories hold world models: things that fly, lie on the map or appear in a taunt.

| Category | Examples |
|---|---|
| **Projectiles** | rockets, grenades and stickybombs, arrows, flares, the Sandman's baseball, syringes |
| **Health & Ammo** | health kits and ammo packs of all sizes, including the Halloween and birthday versions |
| **Taunt Props** | props from taunts: the tank, the guitar, the beer crate, the scooter and many more |

They work like weapons: textures, team colors where the model has them, painting by parts, material maps, VMT, custom models. There's no first-person view because nobody holds them. Pickups are neutral, so they can't be made team-colored.

The taunt prop list starts from a hand-checked set, and the app adds the props it finds in the game's item schema, so new taunts appear on their own. A taunt prop gets one extra scene, **Taunt**: a class performs the taunt with your prop. When several classes can use it, the **Class** row picks who.

## Skyboxes

The **Skybox** category replaces the sky. In Source a sky is six textures, one per side of a cube: up, down and four sides. Each map names the sky it uses, so a mod can replace one particular sky or all of them.

| Item | What the mod replaces |
|---|---|
| **All maps (all stock skies)** | Every stock sky at once. Your sky appears on every map. |
| A sky by name, for example `sky_badlands_01` | Only this sky, on the maps that use it. Each card shows the sky's own horizon. |

The list of skies comes from your game installation, so skies added in updates appear on their own.

### Painting the sky

The album for a sky has seven cards:

- **360° panorama** comes first. Drop a 360-degree photo with a 2:1 aspect ratio, and the app cuts it into all six faces.
- Six face cards follow: `up`, `dn`, `lf`, `rt`, `ft`, `bk`. An image on a face card replaces just that face, on top of what the panorama gave.

The 3D view shows the sky as a cube around the camera, so you can look around and check the seams. If the game is missing some faces of a stock sky, the status line says how many were found.

### Building a sky

- **Formats**: only formats without alpha (`DXT1`, `BGR888`). Transparency in sky faces shows up as seams.
- **Flags**: only **Point Sample** is offered. It turns off smoothing, which keeps small stars crisp when a face is stretched across the screen. Clamping and the other settings a sky needs are set by the app.
- **Resolution**: the panorama is cut at the resolution you choose in the build settings.

> [!WARNING]
> Sky mods use the game's normal paths, and `sv_pure` blocks them on casual servers. They work in local games and on servers that allow custom content. See [troubleshooting](troubleshooting.md#casual-servers-and-sv_pure).

## See also

- [Your first skin](reskin.md): textures, team colors and building.
- [Painting by parts](model-parts.md): useful for class bodies, where one material covers many pieces of clothing.
- [Custom models](custom-models.md): for projectiles, pickups and props as well as weapons.
