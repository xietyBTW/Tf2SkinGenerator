# Building from source

[Documentation](../README.md) · [Русская версия](../ru/building-from-source.md)

This page is for people who want to run the app from a checkout, change it or build a release. The app runs on Windows only: it relies on the game's Windows tools, WebView2 and Windows-only libraries.

## What you need

| Tool | Why |
|---|---|
| Windows 10 or 11, 64-bit | The app and its bundled tools are Windows programs. |
| Python 3.12 or newer | The app itself. CI runs on 3.12. |
| Team Fortress 2 | The app reads its archives and uses `studiomdl.exe` and `vpk.exe` from `<TF2>\bin`. Without the game you can run the tests, but not the app's real work. |
| Microsoft Edge WebView2 Runtime | The window the interface is shown in. |
| Node.js (optional) | The type check of the page's JavaScript modules. |
| Inno Setup 6 (release only) | Building the installer. |
| Visual Studio 2022 Build Tools (rarely) | Only to rebuild `meshoptimizer.dll`. |

## Setting up

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python main.py
```

`requirements.txt` holds what the app needs at runtime: pywebview, Pillow, vpk, srctools and NumPy. `requirements-dev.txt` adds the development tools on top: PyInstaller, coverage, vulture and ruff.

Two packages are optional:

- `vtf2img` converts extracted textures to PNG, TGA or JPG (**Settings → Extraction format**). Without it, extraction keeps the VTF and writes a note to the log.
- `pytest` runs the test suite with the fixtures from `tests/conftest.py`, which redirect temporary files and drafts into a throwaway folder.

### Bundled tools

These live in `tools/` and are committed to the repository, so there's nothing to download:

| Folder | What's there |
|---|---|
| `tools/crowbar/` | Crowbar's command-line decompiler |
| `tools/VTF/` | VTFCmd with VTFLib, HLLib and DevIL |
| `tools/meshoptimizer/` | `meshoptimizer.dll` for simplifying imported models, built by `scripts/build_meshoptimizer.ps1` |

`vpk.exe` and `studiomdl.exe` are Valve's own programs and aren't in the repository. The app takes them from `<TF2>\bin`. If you'd rather not depend on the game for packing, a copy of `vpk.exe` in `tools/VPK/` takes priority.

Helper `.bat` and `.ps1` files are ignored by git, except `build-release.ps1` and `scripts/build_meshoptimizer.ps1`. If you see `run.bat` or `release.bat` mentioned somewhere, they're local conveniences, not part of the project.

## Running

| Command | What it does |
|---|---|
| `python main.py` | The full app: logging, the single-instance check, data migration, then the window. |
| `python frontend/app.py` | Only the window and its local server, without the rest of `main.py`. If pywebview isn't installed, it opens the page in an Edge or Chrome app window, or in the default browser. |
| `python frontend/devserver.py 5174 --work-dir .devwork` | The development server. Open `http://127.0.0.1:5174` in a browser. |

When you run from source, the data folder is the repository itself: `config/`, `work/`, `mods/`, `export/`, `cache/`, `tools/temp/`, `tools/edited_vmt/` and the logs appear next to the code. All of them are in `.gitignore`.

### The development server

The development server serves the same page and the same API over HTTP, so you can work on the interface in a normal browser with its developer tools.

- Open `127.0.0.1`, not `localhost`. With `localhost`, Chromium tries IPv6 first, gets refused and falls back, which adds about 300 ms to every API call.
- `--work-dir .devwork` keeps the server's drafts and works out of `work/`. Without it, a server running next to the open app writes into the same drafts as the app. The settings file and VMT edits are still shared between the two.
- The server answers only the API methods listed in `ALLOWED` in `frontend/devserver.py`. A new method in `src/app/api.py` has to be added there too.

## Project layout

```
main.py                   entry point: logging, single-instance check, data migration, UI start
frontend/
  app.py                  window host: local HTTP server plus a pywebview window
  devserver.py            HTTP transport: static files, POST /api/<method>, /upload, /events, /file
  mockup/                 the page: index.html, style.css and ES modules, app.js is the entry
  CONTROLS.md             which control appears in which mode, and why
  check.mjs, tsconfig.json, package.json   type check of the modules
src/
  app/                    application layer: api.py (what the page calls), session.py (AppSession),
                          preview_controller.py, parts_editor.py, particles_editor.py
  domain/                 state without I/O: the preview session, texture state, format choices
  services/               the actual work: VTF, VMT, VPK, decompiling and compiling, the build
                          pipeline, diagnostics, sounds, particles, War Paint, mesh import
  data/                   game data tables and parsers: weapons, items_game, cosmetics, sounds,
                          particle sources, translations
  shared/                 paths, logging, constants, validators, the error classifier, version
  config/                 AppConfig: reading and writing config/app_config.json
  static/                 the 3D viewer (viewer3d.html, three.js) and the particle engine (particles3d.html)
tools/                    bundled third-party tools
tests/                    the test suite
scripts/                  maintenance: coverage gate, frontend check, data table builders, meshoptimizer build
Tf2SkinGenerator.spec     PyInstaller spec: the single source of what goes into the build
build-release.ps1         release script
```

## How it fits together

**The window.** There's no GUI toolkit. `frontend/app.py` starts a small HTTP server on `127.0.0.1` with a random free port and opens the page in a pywebview window, which on Windows is Edge WebView2. The 3D viewer and the particle engine are separate pages from `src/static`, loaded into iframes.

**Calls.** The page talks to Python through one module, `frontend/mockup/api.js`. Each call is `POST /api/<method>` with JSON parameters; the server passes it to the function of the same name in `src/app/api.py` and returns `{result}` or `{error}`. `api.py` knows nothing about HTTP: its functions take and return plain values, so they can be tested without a browser.

**Events.** Long operations (loading a model, building, extracting) run in worker threads from `src/services`. The session (`src/app/session.py`) turns their signals into events in a queue, and the page receives them as Server-Sent Events from `GET /events`, where each subscriber gets a queue of its own. `frontend/mockup/events.js` dispatches them. Files that workers produce, such as OBJ meshes and PNG previews, are served by `GET /file`, only from the temporary folder and the app's data folders.

**Rules live in Python.** Which controls a mode shows is decided by `controls_for(mode)` in `src/app/api.py`; the page only applies the answer. `frontend/CONTROLS.md` explains the reasoning behind each rule. Keeping the rules on one side means the page can't drift away from what the build actually does.

**Layers.** `domain` imports nothing from `app` or `services`, and `services` imports nothing from `app`. `tests/test_layer_boundaries.py` enforces this by parsing the imports.

**Two roots on disk.** `src/shared/paths.py` separates `install_dir()`, the program files, which are read-only because an update replaces them, from `data_dir()`, where everything the app writes goes. In the built app the data folder is `%LOCALAPPDATA%\Tf2SkinGenerator`; from source both are the current folder. New code that writes files must go through `data_dir()`.

**The build pipeline.** A skin build decompiles the item with Crowbar (the result is cached in `%USERPROFILE%\.tf2skingen_cache`), patches the QC so its materials point into the sv_pure bypass folder, converts images to VTF with VTFCmd, writes the VMTs, compiles the model with `studiomdl` and packs the folder with `vpk.exe`. `BuildRequest` describes a build, `BuildWorker` runs it in a thread, `VPKService` does the work.

**Translations.** The interface is written in Russian, and Russian strings are the keys. The English dictionary is `frontend/mockup/strings.js`. A string with a value inside is one template with `{}` (`Built: {}`), never glued from pieces, otherwise the dictionary can't find it. Item names come from Python already in the right language. Messages from Python live in `src/data/translations.py`, and `src/shared/error_classifier.py` turns raw errors into explanations in the interface language. Debug and info log entries stay in Russian on purpose: they're read by the developer.

Code comments are in Russian as well.

## Tests and checks

| Command | What it checks |
|---|---|
| `python -m ruff check src main.py tests` | Undefined names, unused imports, redefinitions (the `F` rule set, see `ruff.toml`). |
| `python -m pytest tests -q` | The test suite, with the fixtures from `conftest.py`. |
| `coverage run -m unittest discover -s tests` | The same suite as CI runs it. |
| `python scripts/check_coverage.py coverage.json 40 28` | The coverage gate: 40 % of lines and 28 % of branches. Run `coverage json -o coverage.json` first. |
| `python -m vulture src main.py --min-confidence 80` | Dead code. Lower the confidence to 60 locally for a deeper look. |
| `python scripts/check_frontend.py` | The page against itself: every element id the code looks up exists in `index.html`, every API method is exported by `api.js`, allowed by the dev server and defined in `api.py`, every event Python sends has a handler. |
| `npm install`, then `npm run check` in `frontend/` | TypeScript checks the JavaScript modules for broken imports and names. Known DOM narrowing noise is filtered out. |

GitHub Actions (`.github/workflows/ci.yml`) runs ruff, the test suite with coverage and the coverage gate, and vulture on every push and pull request, on Windows with Python 3.12.

## Building a release

A release is two files from one build:

- `Tf2SkinGenerator-Setup.exe`: an Inno Setup installer with the app inside. In-app updates look for exactly this file name.
- `Tf2SkinGenerator-portable.zip`: the same folder for those who don't want to install, with a `PORTABLE` marker file inside.

`build-release.ps1` makes both:

```powershell
powershell -ExecutionPolicy Bypass -File build-release.ps1 -Version 1.0.7
```

Without `-Version` it asks for one (Enter keeps the current version); `-SkipDeps` skips reinstalling packages. The script:

1. Writes the version into `src/shared/version.py`, the single source of the version for the app, the update check and the installer.
2. Installs the dependencies and PyInstaller into `.venv` and checks that pywebview is importable.
3. Builds the app with PyInstaller from `Tf2SkinGenerator.spec` (one folder, no console) into `build\release\`.
4. Copies `tools\` next to the executable, leaving out scratch folders and the game content that must not be redistributed.
5. Refuses to continue if a personal `app_config.json` slipped into the build.
6. Builds the installer with Inno Setup, then the zip, and prints the SHA-256 of the installer.

Both files end up in `installer\Output\`.

> [!IMPORTANT]
> The Inno Setup script (`installer\Tf2SkinGenerator-bundle.iss`) and the app icon (`installer\assets\icon.ico`) live in the `installer/` folder, which is excluded from the repository by `.gitignore`. A fresh clone doesn't have them, and both the release script and the PyInstaller spec need them.

After the script:

1. Run the new `Setup.exe` yourself and make sure the app installs and starts.
2. Commit the version change.
3. Create a GitHub release with the tag `v1.0.7`. It must be a regular release: the update check ignores drafts and pre-releases.
4. Attach both files with their names unchanged.

### How in-app updates use the release

The app asks the GitHub API for the latest release and compares its tag with its own version. It finds the asset named `Tf2SkinGenerator-Setup.exe` (`ASSET_NAME` in `src/services/update_checker.py`), downloads it, checks the size and the SHA-256 that GitHub computes for every asset, and runs it silently. The installer waits for the app to close (it knows the app's mutex), replaces the files and starts the new version.

A portable copy is updated by the same installer. The `PORTABLE` file next to the executable makes the updater run `Setup.exe /PORTABLE=1 /DIR="<that folder>"`, which replaces the files in place and creates no shortcuts, no uninstaller and no entry in the list of installed programs. The folder has to be writable without administrator rights.

When the app runs from source, the update check only offers a link to the release page.

## Licenses

The project's own code is under the MIT license. The bundled tools keep their licenses: Crowbar (CC BY-SA 3.0), VTFLib, HLLib and DevIL (LGPL), VTFCmd (GPL, used as a separate program), meshoptimizer (MIT), three.js (MIT). The particle engine follows the logic of noclip.website (MIT). Details are in [THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md).
