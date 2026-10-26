# Cyclop for Windows 11

A Windows adaptation of [akalikbergenov/cyclop](https://github.com/akalikbergenov/cyclop): an animated black notch that expands into a compact toolbox.

**The Windows application lives in [`windows/`](windows/).** The original macOS sources remain in this repository, with their original documentation in [README.macOS.md](README.macOS.md).

![Windows panel layout](windows/docs/panel-preview.png)

*Rendered Qt interface with simulated media metadata; this is a layout preview, not a Windows desktop capture.*

## Get started

Install **Python 3.12 x64**, download or clone this repository, then double-click **[`windows/run.cmd`](windows/run.cmd)**.

```powershell
git clone https://github.com/MainTechAI/win_cyclop.git
cd win_cyclop\windows
.\run.cmd
```

For a portable executable, download the **CyclopWindows-win-x64** artifact from a successful [Windows build](https://github.com/MainTechAI/win_cyclop/actions/workflows/windows.yml), extract both ZIP layers, and run `CyclopWindows.exe`. No Python installation is needed for the portable build.

## Included

- Hover expansion, concave notch shoulders, black panel and two icon rails.
- Windows media session controls and artwork.
- File shelf with drag-and-drop and optional clipboard screenshots.
- Opt-in, session-only clipboard history and persistent snippets.
- Calendar import with recurring events and meeting links.
- Notes, teleprompter and daily currency conversion.
- Optional offline English/Russian translation using Argos models.
- Tray menu, **Ctrl+Alt+Space**, pin, privacy cover and monitor selection.

This is **version 0.1.0**, an initial native Qt port. Calendar uses local `.ics` files rather than account sync. Offline translation requires an optional source installation and language models. The standard portable build is unsigned and excludes the translation engine. Other platform differences and a Windows desktop smoke checklist are documented in [the Windows README](windows/README.md).

Original Cyclop by **akalikbergenov**, MIT licensed. This independent adaptation retains the upstream license and attribution.
