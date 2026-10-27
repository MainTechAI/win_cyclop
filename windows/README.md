# Cyclop for Windows 11

A native Qt desktop adaptation of [akalikbergenov/cyclop](https://github.com/akalikbergenov/cyclop). A small black notch at the top of your display unfolds into a toolbox when you hover over it. The silhouette, black surfaces, typography hierarchy and two icon rails follow the original MIT-licensed design.

**Version 0.2 adds features of its own but is not full macOS feature parity.** It uses Python 3.12, PySide6 and Windows Runtime APIs, bundled into the release executable. It does not use Electron or a browser window. Its footprint will be larger than the original Swift app.

## Install

Download **[CyclopWindows.exe](https://github.com/MainTechAI/win_cyclop/releases/latest)** from the latest release and run it. No Python, installer or administrator rights are needed: Python, Qt and the speech engine are bundled.

- Windows may show **"Windows protected your PC"** because the build is unsigned. Choose **More info → Run anyway**.
- For faster start-up, download **CyclopWindows-win-x64.zip** instead, extract it and run `CyclopWindows\CyclopWindows.exe`, keeping the `_internal` folder alongside it. The single `.exe` unpacks its libraries at every launch, so it starts more slowly.
- To update, quit Cyclop from its tray menu, then run the new download. Both builds use the same data folder, so notes, snippets and settings are kept.
- If the tray icon is hidden, find Cyclop in the notification-area overflow (^).
- To start Cyclop at sign-in, put a shortcut to the executable in your Startup folder (Win+R → `shell:startup`).

## Interaction

- Hover over the top-center notch for approximately 100 ms to expand. Move away for approximately 250 ms to collapse.
- Hover over a rail icon for 100 ms, or click it, to change tools. Open dialogs and dropdowns suspend hover switching.
- **Ctrl+Alt+Space** toggles the panel; **Escape** collapses it. Opening from the tray icon, the notch, Cyclop or a shortcut keeps the panel open until you visit it and leave, click into another app, or press Escape.
- **Tabs cycle in a loop**: Ctrl+Tab / Ctrl+Shift+Tab (or Ctrl+PgDown / PgUp), the mouse wheel over either icon rail or the title, or a click on the title (`MUSIC ›`) moves to the next tab; past the last tab it wraps to the first.
- The quick-settings button (four squares) opens a Windows 11-style flyout with **Keep awake**, **Text capture**, **Voice**, **Record**, **Hide contents**, **Keep open** tiles and an output-volume slider.
- The pin holds the panel open; the eye hides the current contents.
- Typing keeps the panel open while it retains keyboard focus. A running teleprompter also keeps it open.
- Drag files to the notch to open the shelf. Ctrl-click selects multiple cards; dragging out copies files.
- The tray menu opens quick settings and settings, toggles keep-awake, starts text capture or a voice command, toggles clipboard capture and the mascot, hides contents, or quits.
- Select a monitor in Settings. Placement uses the monitor's work area, leaving a top-mounted taskbar accessible. Qt handles logical coordinates at different DPI settings.
- No automatic startup is installed. To start at sign-in, create a shortcut to the portable executable in your Windows Startup folder.

## Cyclop mascot

A 3D floating eye orb sits beside the notch (red by default; other eye colours in Settings). It is ray-traced per pixel: a glossy sphere with key and fill lights, studio reflections, a rim light, a glowing fibred iris that looks around, follows the pointer and blinks, and eyelids that close over it. After an idle period (8 s by default) it slides up so only a sliver stays visible; hover the sliver to bring it back.

- It is alive: it breathes and floats, tilts its head, hops, looks around while **scanning with red sonar** (pulses and a radar sweep), perks up when the pointer comes near, bounces when clicked, shakes on errors and dozes off when left alone for a while.
- **Text capture** shows a red sonar sweep over the selected area while Cyclop stares at it and reads.
- **Click** Cyclop to give a voice command (when voice commands are on) or to open/close the panel. **Right-click** for the tray menu.
- **System stats** (on by default; turn off in Settings): CPU, RAM, GPU and temperature appear under Cyclop as coloured numbers and stay visible when it tucks away — green, yellow at 50/60, red at 80. Hover for details. GPU uses the Windows 3D-engine counter (any GPU) with NVIDIA NVML as fallback; temperature uses ACPI thermal zones or the NVIDIA GPU sensor. Some PCs expose no temperature to normal apps; then it shows `Temp –`.
- The `.exe`, tray and window icons are a flat 2D version of the same eye.

## Shortcuts

All global shortcuts can be changed or reset in **Settings → Shortcuts**, and each feature can be switched off in **Settings → Features**.

| Shortcut | Action |
|---|---|
| Ctrl+Alt+Space | Show or hide the panel |
| Ctrl+Shift+X | **Image → text**: drag a rectangle on a frozen screenshot; Windows OCR reads it offline and copies the text |
| Ctrl+Alt+D | **Define** the selected word in a popup (Wiktionary) |
| Ctrl+Alt+T | **Translate** the selected text in its own popup (offline Argos); edit the text there to retranslate |
| Ctrl+Alt+V | **Voice command** (when enabled); press again to stop early |

Ctrl+N was not used for text capture because it is "New" in almost every Windows app.

### Voice commands

Voice commands run offline with Whisper and only perform allow-listed actions through Windows APIs. English and Russian phrases work, for example: "open Notepad / calculator / explorer / settings / task manager / terminal / browser / YouTube", "открой калькулятор", "search for …" / "найди …", "volume up/down", "громче/тише", "mute", "next / previous track", "pause", "lock the computer", "capture text", "keep awake" / "не засыпай", "allow sleep", "what time is it", "start recording", "show notes" (any Cyclop tab), "hide". Unrecognised speech is shown, never executed.

## Tools

| Tool | Implemented behavior | Windows differences |
|---|---|---|
| Music | Current session metadata/artwork, previous, play/pause, next and seek; **app volume** slider (follows the playing app, e.g. the browser playing YouTube, or pick any app) and **output volume** | Uses Windows Global System Media Transport Controls. Only apps exposing a media session are available, and controls depend on each player's capabilities. |
| Shelf | Persistent file references, image previews, multi-file drag in/out, clipboard-image capture when enabled | Double-click reveals the containing folder. Removing a card never deletes the original. No Apple Universal Clipboard or AirDrop. |
| Clipboard | Opt-in text capture, 40 deduplicated entries, click to copy, clear/pause | Session-only. Honors Windows exclusion formats where apps supply them; cannot reliably identify all passwords. |
| Snippets | Add/edit/remove reusable text; click to copy; JSON persistence | Local plain text. |
| Calendar | Import a local `.ics` file; next seven days; recurring events, exceptions, time zones; supported call links | No Microsoft/Google account sync. Refresh rereads the chosen local file. Export a fresh file when your calendar changes. |
| Translate | Automatic English/Russian direction, debounced local inference | Optional Argos engine and downloaded models replace Apple's Translation.framework. |
| Currency | Daily rates, local cache, conversion in either field, swap currencies | Explicit Fetch rates button contacts Frankfurter v2. Cached rate date remains visible; no live-market claim. |
| Notes | Multiple auto-saved scratch notes, create/delete/copy | Local plain text. |
| Teleprompter | Editable script, start/pause/reset, speed in pixels per second | Scrolls near the top-center camera position. |
| Text capture | Capture area button and Ctrl+Shift+X; preview, editable result, Copy, Translate | Windows.Media.Ocr, offline. Recognises the OCR languages installed in Windows (Settings → Time & language). |
| Recorder | Record the default microphone to WAV, play, move to Recycle Bin, offline Whisper transcription saved as `.txt` beside the recording | Speech model (tiny/base/small) is downloaded on first transcription. |
| Settings | Panel, mascot, stats, feature toggles, speech model/language, editable shortcuts, tab visibility, monitor, data folder | One panel on a selected monitor, not one on every monitor. |

Not implemented: the upstream keyboard-cleaning lock, per-section privacy rules, screen-capture folder watcher, cloud calendar authentication, mirrored panels across monitors, automatic updates, macOS integrations, native Windows installer and code signing. Hidden tabs stop their active services. Removing/hiding the shelf does not remove captured screenshots from disk.

## Translation setup

Offline translation of whole texts needs a [source installation](#run-from-source-developers). Then run:

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
- Define (Ctrl+Alt+D) sends only the selected word to Wiktionary, and only while "Allow online dictionary lookups" is on.
- Recordings (`recordings\*.wav` and transcripts) stay in the data folder. Speech models download once from Hugging Face into `models\`; recognition then runs offline. The microphone is opened only while recording or listening for a command.
- Text capture keeps the frozen screenshot in memory only; recognition is local.
- Define/translate read your selection with a synthetic Ctrl+C and then restore the previous clipboard; that copy is not added to clipboard history.
- Keep awake blocks sleep and screen-off only while it is on and Cyclop is running.
- Translation installation and Python dependency installation use their respective package servers.
- There is no analytics, credential collection, automatic calendar upload, or arbitrary command execution from copied text or speech.

Set `CYCLOP_DATA_DIR` to an alternate directory for testing. Do not commit that directory to Git.

## Run from source (developers)

Only needed to change the code. Install **Python 3.12 x64** from [python.org](https://www.python.org/downloads/windows/) with the Python Launcher, clone the repository, then double-click `windows\run.cmd`. It creates a `.venv`, installs dependencies and starts the app. Later launches can skip the install step:

```powershell
cd windows
.\.venv\Scripts\python.exe -m cyclop_windows
```

Manual setup, including the optional speech engine (voice commands and transcription):

```powershell
cd windows
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[speech]"
.\.venv\Scripts\python.exe -m cyclop_windows
```

To build the executables locally (runs the tests first and creates `dist\CyclopWindows-win-x64.zip`):

```powershell
cd windows
powershell -File .\scripts\build.ps1
```

Every pull request also builds both executables in **Actions → Windows build**; download **CyclopWindows-win-x64** from a run's Artifacts to test a change before release. The builds are unsigned and do not include Argos Translate (see Translation setup).

## Development and testing

```powershell
cd windows
.\.venv\Scripts\python.exe -m pip install -e ".[dev,speech]"
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
- Single-click the tray icon: the panel stays open; click another app to dismiss it.
- Ctrl+Shift+X on English and Russian text; Ctrl+Alt+D / Ctrl+Alt+T on a selection in a browser and Word.
- Toggle Keep awake and confirm with `powercfg /requests`.
- Move the app-volume slider while YouTube plays in a browser; move the output slider.
- Record, transcribe, and give voice commands with the speech model installed.
- Watch Cyclop slide up after the idle time, then hover to reveal; enable stats and compare with Task Manager.

## Architecture

- `app.py`: window geometry, animation, hover state, rails and tab cycling; the `Cyclop` controller wires tray, shortcuts, mascot, voice, text capture, lookups and keep-awake.
- `mascot.py`: ray-traced 3D eye renderer, animated mascot window and the 2D icon/`.ico` writer.
- `features.py`: text capture, recorder, volume, quick-settings flyout and settings panes.
- `capture.py`: freeze-frame region selector; `popups.py`: selection grabber and define/translate popup.
- `speech.py`: microphone recorder and faster-whisper transcription; `system.py`: stats sampler and Core Audio volume.
- `panes.py`: native Qt tool widgets.
- `model.py`: shared state, persistence, clipboard handling and background-job coordination.
- `services.py`: WinRT media worker, public rate retrieval and optional offline translation.
- `windows.py`: Windows clipboard exclusions, global hotkeys, keep-awake, media keys, PDH performance counters.
- `core.py`: platform-independent persistence, conversion, calendar, config, hotkey parsing, voice-command and dictionary logic.
- `theme.py`: styling and original vector icons.

## Credits and license

Original Cyclop by **akalikbergenov**, MIT, source baseline `125eb02fbd28b443fe922334ae09823d4ad38df6`. The notch path is adapted from `Sources/Cyclop/UI/NotchShape.swift`, and the layout/interaction design follows its SwiftUI implementation. The upstream copyright notice and MIT license are retained at the repository root. This is an independent Windows adaptation, not an official Windows release by the original author.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for runtime dependency licensing.

## Automated file scans

[VirusTotal workflow](https://github.com/MainTechAI/win_cyclop/actions/workflows/virustotal.yml) scans the EXE and ZIP after successful `main` builds and Windows releases. Commit reports are retained in Actions; release reports appear below and in the release notes. [Setup and rescan instructions](https://github.com/MainTechAI/win_cyclop/blob/main/windows/docs/virustotal.md).

<!-- virustotal:start -->
## VirusTotal scans

Scan target: `windows-v0.1.0`. Results refer to these exact file hashes.

| File / report | Status | Malicious | Suspicious | Undetected | Harmless | Other* | Analysis time |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| [CyclopWindows.exe](https://www.virustotal.com/gui/file/fedd8cd0150ec333824a321e6e056923f890c814b4f510c4cfb0b909267206ef) | Completed | 2 | 0 | 66 | 0 | 7 | 2026-10-27 18:26 UTC |
| [CyclopWindows-win-x64.zip](https://www.virustotal.com/gui/file/bf3e07832498ca491073ccffe7781e8df0fa48d424f55f86f78fd081a079751a) | Completed | 0 | 0 | 66 | 0 | 9 | 2026-10-27 18:28 UTC |

*Other includes timeouts, failures and unsupported file types. Undetected means no detection; it is not a safety guarantee.

SHA-256:

- `CyclopWindows.exe`: `fedd8cd0150ec333824a321e6e056923f890c814b4f510c4cfb0b909267206ef`
- `CyclopWindows-win-x64.zip`: `bf3e07832498ca491073ccffe7781e8df0fa48d424f55f86f78fd081a079751a`

Reports may change as engines update. Known hashes reuse their existing report; the table shows that report’s analysis time.
<!-- virustotal:end -->
