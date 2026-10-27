# Cyclop for Windows 11

A native Qt desktop adaptation of [akalikbergenov/cyclop](https://github.com/akalikbergenov/cyclop). A small black notch at the top of your display unfolds into a toolbox when you hover over it. The silhouette, black surfaces, typography hierarchy and two icon rails follow the original MIT-licensed design.

**Version 0.1.0 is an initial Windows port, not full macOS feature parity.** It uses Python 3.12, PySide6 and Windows Runtime media APIs. It does not use Electron or a browser window. Its footprint will be larger than the original Swift app.

## Run on Windows 11

1. Install **Python 3.12 x64** from [python.org](https://www.python.org/downloads/windows/), with the Python Launcher enabled.
2. Clone or download this repository.
3. Open the `windows` folder and double-click **`run.cmd`**.

The launcher creates an isolated `.venv`, installs dependencies, and starts the app. Dependency installation needs internet access. Subsequent launches can avoid the install step with:

```powershell
cd windows
.\.venv\Scripts\python.exe -m cyclop_windows
```

For a manual first installation:

```powershell
cd windows
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m cyclop_windows
```

No administrator privileges are required. Find Cyclop in the notification-area overflow if its tray icon is hidden.

## Portable executable

Download **CyclopWindows.exe** from [Releases](https://github.com/MainTechAI/win_cyclop/releases) to run the standalone build, or download **CyclopWindows-win-x64.zip**, extract it, and run `CyclopWindows/CyclopWindows.exe`. The folder build starts faster because it does not unpack its libraries at every launch. Quit any running copy from the tray menu before updating. Both builds use the same local data directory.

Open the repository's **Actions → Windows build**, choose a successful run, and download **CyclopWindows-win-x64** from Artifacts. Extract the downloaded artifact, then the `CyclopWindows-win-x64.zip` inside it. Run `CyclopWindows.exe` from the extracted `CyclopWindows` directory. Keep the `_internal` directory alongside the executable.

The package includes Python and Qt, so a separate Python install is not needed. The initial build is unsigned; code signing and an installer are not configured. Do not treat a successful build as proof of all desktop integrations: see the smoke checklist below.

To build locally:

```powershell
cd windows
powershell -File .\scripts\build.ps1
```

This runs the test suite and creates `dist\CyclopWindows-win-x64.zip`. The standard portable build does **not** include Argos Translate; use the source installation for offline translation.

## Interaction

- Hover over the top-center notch for approximately 100 ms to expand. Move away for approximately 250 ms to collapse.
- Hover over a rail icon for 100 ms, or click it, to change tools. Open dialogs and dropdowns suspend hover switching.
- **Ctrl+Alt+Space** toggles the panel; **Escape** collapses it.
- The pin holds the panel open; the eye hides the current contents.
- Typing keeps the panel open while it retains keyboard focus. A running teleprompter also keeps it open.
- Drag files to the notch to open the shelf. Ctrl-click selects multiple cards; dragging out copies files.
- The tray menu opens settings, toggles text capture, hides contents, or quits.
- Select a monitor in Settings. Placement uses the monitor's work area, leaving a top-mounted taskbar accessible. Qt handles logical coordinates at different DPI settings.
- No automatic startup is installed. To start at sign-in, create a shortcut to the portable executable in your Windows Startup folder.

## Tools

| Tool | Implemented behavior | Windows differences |
|---|---|---|
| Music | Current session metadata/artwork, previous, play/pause, next and seek | Uses Windows Global System Media Transport Controls. Only apps exposing a media session are available, and controls depend on each player's capabilities. |
| Shelf | Persistent file references, image previews, multi-file drag in/out, clipboard-image capture when enabled | Double-click reveals the containing folder. Removing a card never deletes the original. No Apple Universal Clipboard or AirDrop. |
| Clipboard | Opt-in text capture, 40 deduplicated entries, click to copy, clear/pause | Session-only. Honors Windows exclusion formats where apps supply them; cannot reliably identify all passwords. |
| Snippets | Add/edit/remove reusable text; click to copy; JSON persistence | Local plain text. |
| Calendar | Import a local `.ics` file; next seven days; recurring events, exceptions, time zones; supported call links | No Microsoft/Google account sync. Refresh rereads the chosen local file. Export a fresh file when your calendar changes. |
| Translate | Automatic English/Russian direction, debounced local inference | Optional Argos engine and downloaded models replace Apple's Translation.framework. |
| Currency | Daily rates, local cache, conversion in either field, swap currencies | Explicit Fetch rates button contacts Frankfurter v2. Cached rate date remains visible; no live-market claim. |
| Notes | Multiple auto-saved scratch notes, create/delete/copy | Local plain text. |
| Teleprompter | Editable script, start/pause/reset, speed in pixels per second | Scrolls near the top-center camera position. |
| Settings | Hover options, monitor selection, tab visibility, optional image capture, data folder | One panel on a selected monitor, not one on every monitor. |

Not implemented: the upstream keyboard-cleaning lock, per-section privacy rules, screen-capture folder watcher, cloud calendar authentication, mirrored panels across monitors, automatic updates, macOS integrations, native Windows installer and code signing. Hidden tabs stop their active services. Removing/hiding the shelf does not remove captured screenshots from disk.

## Translation setup

From a **source installation**, run:

```powershell
cd windows
.\.venv\Scripts\python.exe -m pip install -e ".[translate]"
.\.venv\Scripts\python.exe .\scripts\setup-translation.py
```

The setup script asks before downloading English→Russian and Russian→English models from the Argos package index. Downloads can be hundreds of megabytes. Once installed, translation stays on your machine. No text is sent to a translation service. The UI explains missing dependencies/models instead of displaying invented translations. This optional path is separate from the standard portable build and must be tested with the chosen models on your machine.

## Data and privacy

Data directory: `%LOCALAPPDATA%\CyclopWindows`.

- `config.json`, `shelf.json`, `snippets.json`, `notes.json`, `prompter.json`, `rates.json`.
- `screenshots\` contains copied clipboard images only if you enable that option. They remain until you delete them yourself.
- Clipboard text stays in process memory and clears when Cyclop exits. Capture is disabled initially. Pause capture before copying credentials; exclusion metadata is not universal.
- Shelf cards reference original files. A moved/deleted file is removed on the next launch.
- Writes replace JSON files atomically. Invalid JSON is retained in an `*.invalid-*.json` recovery file.
- Rates are the only network request in normal operation, and only after pressing Fetch rates. That request contains a fixed EUR base; it does not contain your amount or other tool content.
- Joining a calendar call opens the event's HTTPS meeting URL in the default browser. Only recognized meeting-service domains are offered.
- Translation installation and Python dependency installation use their respective package servers.
- There is no analytics, credential collection, automatic calendar upload, or arbitrary command execution from copied text.

Set `CYCLOP_DATA_DIR` to an alternate directory for testing. Do not commit that directory to Git.

## Development and testing

```powershell
cd windows
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

The automated suite covers persistence/recovery, clipboard policy, file-reference safety, currency arithmetic, meeting URL checks, calendar recurrence, pane rendering and UI state. It can run offscreen on Linux for fast development. GitHub Actions runs it on Windows, verifies the WinRT imports/buffer projection, builds a portable executable, and checks that the packaged process starts.

Windows CI also runs `tests/test_interactions.py` with the native Windows Qt platform, including native hit-testing to check that dialog fields and dropdowns are above the panel. Publishing a `windows/releases/<version>.md` note on `main` runs the Windows release workflow; it publishes a `windows-v<version>` release only after tests and both executable smoke checks pass. Existing releases are not overwritten.

### Windows desktop smoke checklist

The hosted build does not replace these checks on a real Windows 11 desktop:

- Open, hover, dismiss, pin, Escape and Ctrl+Alt+Space; check that hover does not steal typing from another app.
- Move between monitors with 100%, 150% and 200% scaling; disconnect the selected monitor.
- Try media controls in Spotify and a browser, including track changes, artwork and seeking.
- Drop two Explorer files into the notch; Ctrl-select and drag them back out; remove cards and confirm originals remain.
- Enable clipboard capture, copy text, pause it, clear it and restart. Test your password manager's exclusion metadata.
- Enable screenshot capture, copy an image, then confirm its shelf preview and saved PNG.
- Import a calendar with recurring meetings, time zones, exceptions and a meeting URL.
- Edit notes and snippets, restart, and confirm persistence.
- Install translation models and test both language directions offline.
- Fetch rates, disconnect the network and use the dated cache.
- Run a long teleprompter script and verify speed, pause, reset and end-of-script behavior.

## Architecture

- `app.py`: window geometry, animation, hover state, rails, tray, hotkey and lifecycle.
- `panes.py`: native Qt tool widgets.
- `model.py`: shared state, persistence, clipboard handling and background-job coordination.
- `services.py`: WinRT media worker, public rate retrieval and optional offline translation.
- `windows.py`: Windows clipboard exclusions and system-wide hotkey.
- `core.py`: platform-independent persistence, conversion and calendar logic.
- `theme.py`: styling and original vector icons.

## Credits and license

Original Cyclop by **akalikbergenov**, MIT, source baseline `125eb02fbd28b443fe922334ae09823d4ad38df6`. The notch path is adapted from `Sources/Cyclop/UI/NotchShape.swift`, and the layout/interaction design follows its SwiftUI implementation. The upstream copyright notice and MIT license are retained at the repository root. This is an independent Windows adaptation, not an official Windows release by the original author.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for runtime dependency licensing.
