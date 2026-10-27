# Contributing

Thanks for helping with Cyclop for Windows 11. The app lives in [`windows/`](windows/); see [windows/README.md](windows/README.md#run-from-source-developers) to run it from source.

## Before you write code

- **One pull request, one change.** For a large feature, open an issue first so we can agree on the approach before you build it.
- **Branch from a fresh `main`**, not from your previous branch.
- **Privacy is a feature.** Anything that adds a network request, camera, microphone or screen access must be opt-in, explained in the README's "Data and privacy" section, and switchable off in Settings.
- **Every feature can be turned off.** New tabs, shortcuts and background work need a Settings toggle, and hidden or disabled features must stop their background work.

## Check before you open a pull request

```powershell
cd windows
.\.venv\Scripts\python.exe -m pip install -e ".[dev,speech]"
.\.venv\Scripts\python.exe scripts\fetch-face-model.py
.\.venv\Scripts\python.exe -m pytest -q
```

Every pull request is built and tested on Windows by **Actions → Windows build**: unit tests, native desktop interaction tests, both executables and their startup self-check. Download the `CyclopWindows-win-x64` artifact from that run to try the change.

## Releases

Bump `version` in `windows/pyproject.toml` and `windows/cyclop_windows/__init__.py`, and add `windows/releases/<version>.md`. Merging that note into `main` runs **Windows release**, which publishes the `.exe`, the zip and checksums only after the full Windows build passes.

## If a pull request goes quiet

When a requested change gets no reply for a week, the pull request is closed automatically (label `waiting-for-author`; a reminder comes on day five, and any comment or commit resets the count). It is not a rejection: reopen it with the same code at any time.
