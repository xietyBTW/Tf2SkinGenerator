# Third-Party Licenses & Notices

Tf2SkinGenerator (the "Software") is licensed under the MIT License (see `LICENSE`).
The MIT License covers **only the original source code of this project**.

The Software invokes several third-party command-line tools and libraries as
**separate programs** (subprocesses / dynamically-loaded libraries). They are
**not** part of this project's source code and are **not** relicensed under MIT.
Each retains its own license, listed below.

Distribution of these tools:

- **Crowbar** (`tools/crowbar/`) **is included** in this repository under CC BY-SA 3.0
  with attribution (see below) — its license permits redistribution.
- **VPK** (`vpk.exe`): **not** shipped. At runtime the app uses Valve's official
  `vpk.exe` from the user's own installed *Team Fortress 2* (`<TF2>/bin/vpk.exe`),
  falling back to an optional local `tools/VPK/` bundle if present. No proprietary
  Valve binaries are redistributed.
- **VTF tools** (`tools/VTF/`: VTFCmd/VTFLib/HLLib/DevIL) **are included** in this
  repository. Their licenses permit redistribution: VTFLib/HLLib/DevIL are LGPL and
  VTFCmd is GPL — both are shipped **unmodified** as separate programs, with their
  corresponding source available at the official links in the table below.

This project is an **unofficial** fan tool. It is **not affiliated with, endorsed
by, or sponsored by Valve Corporation**. *Team Fortress 2*, the Source engine, and
all related game assets are trademarks and/or copyrighted works of Valve Corporation.
No Valve game assets or proprietary Valve binaries are distributed with this project.

---

## Bundled / required external tools

| Tool | Purpose | Author | License | Source |
|------|---------|--------|---------|--------|
| VTFLib (`VTFLib.dll`) | Read/write VTF & VMT image files | Neil Jedrzejewski, Ryan Gregg | LGPL | https://nemstools.github.io/pages/VTFLib.html |
| VTFCmd (`VTFCmd.exe`) | CLI frontend for VTFLib | Neil Jedrzejewski, Ryan Gregg | **GPL** | https://nemstools.github.io/pages/VTFLib.html |
| HLLib (`HLLib.dll`) | Read Half-Life/Source package files | Ryan Gregg | LGPL | https://nemstools.github.io/pages/Miscellaneous-HLLib.html |
| DevIL (`DevIL.dll`) | Image loading library (used by VTFCmd) | DevIL / OpenIL project | LGPL | https://openil.sourceforge.net/ |
| Crowbar (`CrowbarCommandLineDecomp.exe`) | Decompile Source engine models | ZeqMacaw | CC BY-SA 3.0 | https://github.com/ZeqMacaw/Crowbar |
| meshoptimizer (`tools/meshoptimizer/meshoptimizer.dll`) | Mesh simplification with UV preservation for imported OBJ/GLB models (built from source by `scripts/build_meshoptimizer.ps1`, v1.2) | Arseny Kapoulkine | MIT | https://github.com/zeux/meshoptimizer |

### Notes on compliance

- **LGPL** (VTFLib, HLLib, DevIL): used as separate dynamic libraries and left
  unmodified. The MIT license of this project is unaffected. Any modifications to
  these libraries must be made available on request; the original source is linked
  above.
- **GPL** (VTFCmd): invoked **only as a separate executable (subprocess)**. This is
  mere aggregation and does **not** place this project under the GPL. VTFCmd is
  redistributed unmodified; source is available at the link above.
- **CC BY-SA 3.0** (Crowbar): used as a separate executable with attribution to
  ZeqMacaw. If you modify Crowbar and redistribute it, you must rename it and mark
  it as "Modified" per its license. License text:
  https://creativecommons.org/licenses/by-sa/3.0/

## Python dependencies

Direct runtime dependencies (`requirements.txt`):

| Package | Purpose | License |
|---------|---------|---------|
| pywebview | The application window (Edge WebView2 on Windows) | BSD-3-Clause |
| Pillow | Image reading and conversion | MIT-CMU (HPND) |
| vpk | Reading VPK archives | MIT |
| srctools | Source engine file formats (KeyValues, PCF and others) | MIT |
| NumPy | Image and mesh processing | BSD-3-Clause (bundled parts under 0BSD, MIT, Zlib, CC0-1.0) |

Packages that pywebview pulls in on Windows and that end up in the built app:

| Package | License |
|---------|---------|
| pythonnet | MIT |
| clr_loader | MIT |
| cffi | MIT |
| pycparser | BSD-3-Clause |
| proxy_tools | MIT |
| bottle | MIT |
| typing_extensions | PSF-2.0 |

Optional: `vtf2img` (MIT) converts extracted textures to PNG, TGA or JPG when it is
installed.

The interface no longer uses Qt; PySide6 is not a dependency of the project.

## JavaScript libraries

| Library | Where | Author | License |
|---------|-------|--------|---------|
| three.js r160 (`three.module.js`, `OrbitControls`, `TransformControls`, `OBJLoader`) | `src/static/js/` | three.js authors | MIT |
| Particle simulation logic ported from noclip.website (`ParticleSystem.ts`) | `src/static/js/particles/engine.js` | Copyright (c) 2018 Jasper St. Pierre | MIT |

The MIT license texts are available at https://github.com/mrdoob/three.js/blob/dev/LICENSE
and https://github.com/magcius/noclip.website/blob/main/LICENSE.
