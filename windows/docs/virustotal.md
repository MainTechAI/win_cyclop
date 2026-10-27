# VirusTotal scans

The workflow submits the standalone EXE and portable ZIP to VirusTotal, then waits for completed results. These files are public software distributions; VirusTotal submissions are shared with its community. Do not use this workflow for private files.

## One-time setup

1. Copy your key from [VirusTotal](https://www.virustotal.com/gui/my-apikey).
2. Open [repository Actions secrets](https://github.com/MainTechAI/win_cyclop/settings/secrets/actions).
3. Click **New repository secret**. Set **Name** to `VT_API_KEY`, paste the key into **Secret**, and click **Add secret**. Do not put the key in YAML, source code, issues or chat.
4. Open [Actions → VirusTotal](https://github.com/MainTechAI/win_cyclop/actions/workflows/virustotal.yml), click **Run workflow**, select `main`, and leave both inputs empty to scan the latest release. To scan version 0.1.0 explicitly, enter `windows-v0.1.0` as `release_tag`.

The workflow is already installed in `.github/workflows/virustotal.yml`; no Marketplace snippet needs to be pasted. It uses VirusTotal's API directly to verify completed results, rather than treating a successful upload as a completed review.

## Automatic triggers and reports

- Each push to `main` builds Windows binaries. After a successful build, VirusTotal scans the actual EXE and ZIP artifacts and retains `VIRUSTOTAL.md` and `VIRUSTOTAL.json` in that scan's Actions artifacts and summary.
- A completed Windows release workflow scans the uploaded release assets. This also works when the release is created with GitHub's workflow token, which does not fire another `release` workflow. Manually published Windows releases are supported too.
- The release note and both READMEs receive a table with per-file SHA-256 report links, engine counts and analysis times. Only the latest release updates the README. Other notes outside the marked block are preserved.
- Updating the scanner workflow backfills the current release. A manual run can scan any published Windows release or a successful `main` Windows build by run ID.
- Pull requests and fork artifacts never run with the VirusTotal secret. Failed builds have no release binary to scan. Automatic README result commits use `[skip ci]` to avoid an endless scan/build loop.

Known hashes reuse existing VirusTotal reports and retain their original analysis timestamp. New hashes are uploaded using the large-file endpoint when needed. Requests are spaced at least 16 seconds apart, with backoff for throttling. Concurrent runs share your account quota, so frequent commits can exhaust it. The [public API](https://docs.virustotal.com/reference/public-vs-premium-api) has rate/usage limits; use an API plan appropriate to your usage.

The workflow fails visibly for missing credentials, unfinished scans, or malicious/suspicious engine verdicts, and publishes the factual status rather than a green “clean” label. Undetected results are not a safety guarantee; unsupported engines and timeouts are counted separately. It does not delete or replace published binaries, and it does not label detections as false positives automatically.

If a report remains pending, add/fix `VT_API_KEY` or wait for the account quota to reset, then rerun the workflow. Results are tied to the downloaded asset hashes, not newly rebuilt files.
