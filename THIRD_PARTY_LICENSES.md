# Third-Party Licenses & Notices

Tf2SkinGenerator (the "Software") is licensed under the MIT License (see `LICENSE`).
The MIT License covers **only the original source code of this project**.

The Software invokes several third-party command-line tools and libraries as
**separate programs** (subprocesses / dynamically-loaded libraries). They are
**not** part of this project's source code and are **not** relicensed under MIT.
Each retains its own license, listed below.

Distribution of these tools:

- **Crowbar** (`tools/crowbar/`) **is included** in this repository under CC BY-SA 3.0
  with attribution (see below); its license permits redistribution.
- **VPK** (`vpk.exe`): **not** shipped. If a copy is placed in `tools/VPK/`, the app
  uses it; otherwise it runs Valve's official `vpk.exe` from the user's own installed
  *Team Fortress 2* (`<TF2>/bin/vpk.exe`). No proprietary Valve binaries are
  redistributed.
- **VTFLib** (`tools/VTF/VTFLib.dll`) **is included** in this repository under the
  LGPL, unmodified, as a separate dynamic library. Its source is available at the
  official link in the table below.

This project is an **unofficial** fan tool. It is **not affiliated with, endorsed
by, or sponsored by Valve Corporation**. *Team Fortress 2*, the Source engine, and
all related game assets are trademarks and/or copyrighted works of Valve Corporation.
No Valve game assets or proprietary Valve binaries are distributed with this project.

---

## Bundled / required external tools

| Tool | Purpose | Author | License | Source |
|------|---------|--------|---------|--------|
| VTFLib (`VTFLib.dll`) | Read/write VTF & VMT image files | Neil Jedrzejewski, Ryan Gregg | LGPL | https://nemstools.github.io/pages/VTFLib.html |
| Crowbar (`CrowbarCommandLineDecomp.exe`) | Decompile Source engine models | ZeqMacaw | CC BY-SA 3.0 | https://github.com/ZeqMacaw/Crowbar |
| meshoptimizer (`tools/meshoptimizer/meshoptimizer.dll`) | Mesh simplification with UV preservation for imported OBJ/GLB models (built from source by `scripts/build_meshoptimizer.ps1`, v1.2) | Arseny Kapoulkine | MIT | https://github.com/zeux/meshoptimizer |

### Notes on compliance

- **LGPL** (VTFLib): used as a separate dynamic library and left unmodified. The MIT
  license of this project is unaffected. Any modifications to the library must be
  made available on request; the original source is linked above.
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
| srctools | Source engine file formats (KeyValues, PCF, writing VTF; DXT compression through the bundled libsquish, MIT) | MIT |
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

Also shipped inside the built app:

| Component | License |
|-----------|---------|
| Python runtime | PSF-2.0 |
| Microsoft WebView2 SDK (`Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll`, `WebView2Loader.dll`), bundled by pywebview | BSD-3-Clause, Copyright (c) Microsoft Corporation |
| PyInstaller bootloader | GPL-2.0 with the PyInstaller bootloader exception (does not affect the app's license) |
| Native libraries inside the Pillow and NumPy wheels (libjpeg-turbo, libpng, zlib, FreeType, OpenBLAS and others) | Listed in each package's own license file |

The WebView2 runtime itself is not shipped; Windows provides it.

Optional: `vtf2img` (MIT) converts extracted textures to PNG, TGA or JPG when it is
installed.

The interface no longer uses Qt; PySide6 is not a dependency of the project.

## JavaScript libraries

| Library | Where | Author | License |
|---------|-------|--------|---------|
| three.js r160 (`three.module.js`, `OrbitControls`, `TransformControls`, `OBJLoader`) | `src/static/js/` | three.js authors | MIT |
| Particle simulation logic ported from noclip.website (`ParticleSystem.ts`) | `src/static/js/particles/engine.js` | Copyright (c) 2018 Jasper St. Pierre | MIT |

The noise permutation tables in `engine.js` repeat `noisedata.h` from Valve's
Source SDK so the preview matches the game's particle noise.

The MIT license texts are available at https://github.com/mrdoob/three.js/blob/dev/LICENSE
and https://github.com/magcius/noclip.website/blob/main/LICENSE.
