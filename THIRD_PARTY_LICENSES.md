# Third-Party Licenses & Notices

Tf2SkinGenerator (the "Software") is licensed under the MIT License (see `LICENSE`).
The MIT License covers **only the original source code of this project**.

The Software invokes several third-party command-line tools and libraries as
**separate programs** (subprocesses / dynamically-loaded libraries). They are
**not** part of this project's source code and are **not** relicensed under MIT.
Each retains its own license, listed below.

These tools are **not distributed in this repository** — they must be obtained
separately from their official sources (see `.gitignore`: `tools/crowbar/`,
`tools/VPK/`, `tools/VTF/`).

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

| Package | License |
|---------|---------|
| PySide6 (Qt for Python) | LGPLv3 / commercial |
| Pillow | MIT-CMU (HPND) |
| vpk | MIT |
| srctools | MIT |

Qt (via PySide6) is used under the **LGPLv3**. Qt libraries are shipped as separate
dynamic libraries and can be replaced by the user; no modifications are made to Qt.
