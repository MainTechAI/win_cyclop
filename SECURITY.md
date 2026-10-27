# Security

## Reporting a vulnerability

Report it privately through [Security Advisories](https://github.com/MainTechAI/win_cyclop/security/advisories/new); please don't open a public issue. This is a personal project, so replies may take a few days.

## What Cyclop does and does not do

- **No telemetry or accounts.** Notes, snippets, settings and recordings stay in `%LOCALAPPDATA%\CyclopWindows`.
- **Network requests happen only for features you use:** currency rates (when you press Fetch rates), a dictionary lookup of the selected word (Ctrl+Alt+D, can be turned off), and one-time downloads of the speech and face-detection models, which are verified where a checksum is pinned.
- **Camera and microphone are opt-in.** The webcam is used only while "Look where I look" is on and Cyclop is visible; the microphone only while recording or listening for a voice command. Frames and audio for commands are processed in memory and not saved or sent.
- **Voice commands run only allow-listed actions** (open known apps, search, media keys, lock, and Cyclop's own features). Unrecognised speech is shown, never executed. Text you copy is never executed.
- **Builds are unsigned.** Releases include SHA-256 checksums and VirusTotal reports; compare the checksum before running a download.

Full details are in the "Data and privacy" section of [windows/README.md](windows/README.md#data-and-privacy).
