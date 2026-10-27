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

Download the standalone **CyclopWindows.exe** or portable **CyclopWindows-win-x64.zip** from [Releases](https://github.com/MainTechAI/win_cyclop/releases). No Python installation is needed. Quit the running copy from its tray menu before updating.

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
