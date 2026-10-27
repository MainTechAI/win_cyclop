"""Scan trusted build/release binaries and publish factual VirusTotal reports.

Uses only the standard library and the runner's gh CLI. Never executes downloads.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import uuid

START = '<!-- virustotal:start -->'
END = '<!-- virustotal:end -->'
FILES = ('CyclopWindows.exe', 'CyclopWindows-win-x64.zip')
CATEGORIES = ('malicious', 'suspicious', 'undetected', 'harmless', 'timeout', 'confirmed-timeout', 'failure', 'type-unsupported')


def gh(*args, payload=None):
    result = subprocess.run(['gh', *args], input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        # Never echo command environments or authentication values.
        raise RuntimeError('GitHub operation failed: ' + result.stderr.strip()[:500])
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()


def api(path, payload=None, method=None):
    args = ['api', path]
    if method:
        args += ['--method', method]
    if payload is not None:
        args += ['--input', '-']
    return gh(*args, payload=payload)


def replace_block(text, block):
    wrapped = f'{START}\n{block.strip()}\n{END}'
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1 or text.index(END) < text.index(START):
            raise ValueError('Malformed VirusTotal report markers; refusing to overwrite text')
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        return before + wrapped + after
    return text.rstrip() + '\n\n' + wrapped + '\n'


def select_source(event_name, event, repo):
    if event_name == 'workflow_run':
        run = event['workflow_run']
        if (run['conclusion'] != 'success' or run['head_branch'] != 'main'
                or run['event'] not in ('push', 'workflow_dispatch')
                or run['head_repository']['full_name'] != repo):
            raise ValueError('Only successful main-branch builds from this repository may be scanned')
        if run['name'] == 'Windows build':
            return {'kind': 'build', 'run_id': run['id'], 'commit': run['head_sha']}
        if run['name'] == 'Windows release':
            return {'kind': 'release', 'commit': run['head_sha']}
        raise ValueError('Unrecognized source workflow')
    if event_name == 'release':
        return {'kind': 'release', 'tag': event['release']['tag_name']}
    if event_name == 'workflow_dispatch':
        inputs = event.get('inputs') or {}
        if inputs.get('build_run_id'):
            return {'kind': 'build', 'run_id': int(inputs['build_run_id'])}
        return {'kind': 'release', 'tag': inputs.get('release_tag') or 'latest'}
    if event_name == 'push' and event.get('ref') == 'refs/heads/main':
        # Installing/updating this workflow also backfills the current release.
        return {'kind': 'release', 'tag': 'latest'}
    raise ValueError('Unsupported scan trigger')


def prepare():
    repo = os.environ['GITHUB_REPOSITORY']
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    context = select_source(os.environ['GITHUB_EVENT_NAME'], event, repo)
    context['repo'] = repo
    root = Path('scan-inputs')
    root.mkdir(exist_ok=True)
    if context['kind'] == 'build':
        run = api(f'repos/{repo}/actions/runs/{context["run_id"]}')
        # Revalidate manually requested run IDs as well as webhook runs.
        select_source('workflow_run', {'workflow_run': run}, repo)
        if run['name'] != 'Windows build':
            raise ValueError('Build run must be a Windows build')
        context['commit'] = run['head_sha']
        gh('run', 'download', str(run['id']), '--repo', repo, '--name', 'CyclopWindows-win-x64', '--dir', str(root))
        exe = root / 'standalone' / FILES[0]
        if exe.exists():
            exe.rename(root / FILES[0])
    else:
        tag = context.get('tag')
        if not tag:
            releases = api(f'repos/{repo}/releases?per_page=100')
            matches = [r for r in releases if r['target_commitish'] == context['commit'] and r['tag_name'].startswith('windows-v') and not r['draft']]
            if len(matches) != 1:
                raise ValueError('Cannot identify the release published by this workflow')
            release = matches[0]
        else:
            suffix = 'latest' if tag == 'latest' else 'tags/' + quote(tag, safe='')
            release = api(f'repos/{repo}/releases/{suffix}')
        if release['draft'] or not re.fullmatch(r'windows-v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?', release['tag_name']):
            raise ValueError('Expected a published Windows release')
        context.update(tag=release['tag_name'], release_id=release['id'], commit=release['target_commitish'])
        for name in FILES:
            gh('release', 'download', context['tag'], '--repo', repo, '--pattern', name, '--dir', str(root))
        # Bind scan results to the uploaded release assets, not a rebuild.
        for name in FILES:
            asset = next(a for a in release['assets'] if a['name'] == name)
            with (root / name).open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if asset.get('digest') != 'sha256:' + digest:
                raise ValueError('Release asset digest is missing or does not match: ' + name)
    if not all((root / name).is_file() for name in FILES):
        raise ValueError('Both the EXE and portable ZIP are required')
    Path('scan-context.json').write_text(json.dumps(context))


class VTClient:
    def __init__(self, key, timeout=900):
        self.key = key
        self.next_request = 0.0
        self.deadline = time.monotonic() + timeout

    def request(self, path, data=None, content_type=None):
        url = path if path.startswith('https://') else 'https://www.virustotal.com/api/v3/' + path
        parsed = urlsplit(url)
        # VirusTotal's large-file API returns bigfiles.virustotal.com, not
        # necessarily the hostname used for API metadata requests.
        if parsed.scheme != 'https' or parsed.hostname not in ('www.virustotal.com', 'bigfiles.virustotal.com') or parsed.username or parsed.port not in (None, 443):
            raise ValueError('Unexpected VirusTotal upload URL')
        while True:
            time.sleep(max(0, self.next_request - time.monotonic()))
            if time.monotonic() >= self.deadline:
                raise TimeoutError('VirusTotal scan did not complete within the time limit')
            self.next_request = time.monotonic() + 16
            headers = {'x-apikey': self.key, 'Accept': 'application/json'}
            if content_type:
                headers['Content-Type'] = content_type
            try:
                with urlopen(Request(url, data=data, headers=headers), timeout=120) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 404:
                    return None
                if error.code in (429, 500, 502, 503, 504):
                    # Shared-key runs may overlap; respect rate limits rather than
                    # dropping older pending commit scans through concurrency cancellation.
                    self.next_request = time.monotonic() + 60
                    continue
                raise RuntimeError(f'VirusTotal API returned HTTP {error.code}') from None

    def scan(self, path, digest):
        existing = self.request('files/' + digest)
        if existing:
            attrs = existing['data']['attributes']
            if attrs.get('last_analysis_date') and attrs.get('last_analysis_stats'):
                if existing['data']['id'] != digest:
                    raise ValueError('VirusTotal report hash mismatch')
                return completed(attrs['last_analysis_stats'], attrs['last_analysis_date'], 'Existing report')
        if path.stat().st_size > 650_000_000:
            raise ValueError('File exceeds VirusTotal upload limit')
        url = 'files'
        if path.stat().st_size > 32_000_000:
            url = self.request('files/upload_url')['data']
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        uploaded = self.request(url, body, 'multipart/form-data; boundary=' + boundary)
        analysis_id = uploaded['data']['id']
        del body
        while True:
            analysis = self.request('analyses/' + quote(analysis_id, safe=''))
            if not analysis:
                raise ValueError('VirusTotal analysis not found')
            attrs = analysis['data']['attributes']
            if attrs['status'] == 'completed':
                if analysis.get('meta', {}).get('file_info', {}).get('sha256') != digest:
                    raise ValueError('Completed analysis does not match the uploaded file hash')
                return completed(attrs['stats'], attrs['date'], 'New analysis')
            self.next_request = time.monotonic() + 30


def completed(stats, date, source):
    if not isinstance(stats, dict) or not all(k in stats for k in ('malicious', 'suspicious', 'undetected', 'harmless')):
        raise ValueError('Incomplete VirusTotal statistics')
    if any(type(value) is not int or value < 0 for value in stats.values()) or not sum(stats.values()):
        raise ValueError('Invalid or empty VirusTotal statistics')
    stamp = datetime.fromtimestamp(date, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return {'status': 'Completed', 'stats': stats, 'scanned_at': stamp, 'source': source}


def markdown(context, records):
    target = context.get('tag') or context['commit']
    lines = ['## VirusTotal scans', '', f'Scan target: `{target}`. Results refer to these exact file hashes.', '',
             '| File / report | Status | Malicious | Suspicious | Undetected | Harmless | Other* | Analysis time |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for item in records:
        stats = item.get('stats')
        values = [str(stats.get(k, 0)) for k in CATEGORIES[:4]] if stats else ['—'] * 4
        other = str(sum(stats.get(k, 0) for k in CATEGORIES[4:])) if stats else '—'
        lines.append(f'| [{item["name"]}]({item["url"]}) | {item["status"]} | ' + ' | '.join(values) + f' | {other} | {item.get("scanned_at", "—")} |')
    lines += ['', '*Other includes timeouts, failures and unsupported file types. Undetected means no detection; it is not a safety guarantee.', '', 'SHA-256:', '']
    for item in records:
        lines.append(f'- `{item["name"]}`: `{item["sha256"]}`')
        if item.get('error'):
            lines.append('  - ' + item['error'])
    lines += ['', 'Reports may change as engines update. Known hashes reuse their existing report; the table shows that report’s analysis time.']
    return '\n'.join(lines) + '\n'


def scan_files():
    context = json.loads(Path('scan-context.json').read_text())
    key = os.environ.get('VT_API_KEY')
    client = VTClient(key) if key else None
    records = []
    for name in FILES:
        path = Path('scan-inputs') / name
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        item = {'name': name, 'sha256': digest, 'url': 'https://www.virustotal.com/gui/file/' + digest}
        try:
            if not client:
                raise RuntimeError('VT_API_KEY is not configured; no scan was submitted')
            item.update(client.scan(path, digest))
        except Exception as error:
            # Only publish known messages, never responses that could contain credentials.
            item.update(status='Not completed', error=str(error) if isinstance(error, (ValueError, RuntimeError, TimeoutError)) else 'VirusTotal request failed')
        records.append(item)
    output = Path('scan-report')
    output.mkdir(exist_ok=True)
    (output / 'VIRUSTOTAL.json').write_text(json.dumps({'context': context, 'files': records}, indent=2))
    report = markdown(context, records)
    (output / 'VIRUSTOTAL.md').write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as stream:
            stream.write(report)
    return 0 if all(r['status'] == 'Completed' and not (r['stats']['malicious'] or r['stats']['suspicious']) for r in records) else 1


def publish():
    report = json.loads(Path('scan-report/VIRUSTOTAL.json').read_text())
    context = report['context']
    if context['kind'] != 'release':
        return
    repo, release_id = context['repo'], context['release_id']
    block = Path('scan-report/VIRUSTOTAL.md').read_text()
    # Read current notes so manually edited text outside our markers survives.
    release = api(f'repos/{repo}/releases/{release_id}')
    if release['tag_name'] != context['tag']:
        raise ValueError('Release identity changed')
    for item in report['files']:
        asset = next(a for a in release['assets'] if a['name'] == item['name'])
        if asset.get('digest') != 'sha256:' + item['sha256']:
            raise ValueError('Release asset changed during the scan; rerun for the new file')
    api(f'repos/{repo}/releases/{release_id}', {'body': replace_block(release.get('body') or '', block)}, 'PATCH')
    gh('release', 'upload', context['tag'], '--repo', repo, '--clobber', 'scan-report/VIRUSTOTAL.json', 'scan-report/VIRUSTOTAL.md')
    latest = api(f'repos/{repo}/releases/latest')
    if latest['id'] != release_id:
        return  # An older release scan must not replace the latest README results.
    for path in ('README.md', 'windows/README.md'):
        for attempt in range(3):
            current = api(f'repos/{repo}/contents/{path}?ref=main')
            text = base64.b64decode(current['content']).decode()
            updated = replace_block(text, block)
            if text == updated:
                break
            try:
                api(f'repos/{repo}/contents/{path}', {'message': f'Update VirusTotal results for {context["tag"]} [skip ci]',
                    'branch': 'main', 'sha': current['sha'], 'content': base64.b64encode(updated.encode()).decode()}, 'PUT')
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'scan', 'publish'))
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'scan':
        raise SystemExit(scan_files())
    else:
        publish()
