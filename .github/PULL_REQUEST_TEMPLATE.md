<!-- Title: what changed for the user, e.g. "Clicking the eye opens the panel" rather than "Fix bug". -->

## What changed and why

<!-- Symptom, cause, fix. "Closes #N" if it fixes an issue. -->

## Checked

- [ ] `python -m pytest -q` passes in `windows/`
- [ ] The **Windows build** check on this PR is green (it also builds and smoke-tests the `.exe`)
- [ ] New features have a Settings toggle; any new network, camera or microphone use is opt-in and documented
- [ ] Branched from a fresh `main`; this PR does one thing
