"""Scan/report orchestration tests use fixtures, never a real key or upload."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('virustotal', Path(__file__).parents[1] / 'scripts' / 'virustotal.py')
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)

STATS = {'malicious': 1, 'suspicious': 2, 'undetected': 60, 'harmless': 0, 'type-unsupported': 4, 'timeout': 1}


def test_report_update_preserves_notes_and_is_idempotent():
    text = 'Original release notes\n\n' + vt.START + '\nOld report\n' + vt.END + '\nOther notes\n'
    updated = vt.replace_block(text, 'New report')
    assert updated.startswith('Original release notes') and updated.endswith('Other notes\n')
    assert updated.count(vt.START) == 1
    assert vt.replace_block(updated, 'New report') == updated
    with pytest.raises(ValueError):
        vt.replace_block('User notes ' + vt.START, 'Report')


@pytest.mark.parametrize('event,branch,repo,status', [
    ('pull_request', 'main', 'owner/repo', 'success'),
    ('push', 'feature', 'owner/repo', 'success'),
    ('push', 'main', 'fork/repo', 'success'),
    ('push', 'main', 'owner/repo', 'failure'),
])
def test_untrusted_or_failed_builds_cannot_use_scanner(event, branch, repo, status):
    run = {'event': event, 'head_branch': branch, 'head_repository': {'full_name': repo}, 'conclusion': status}
    with pytest.raises(ValueError):
        vt.select_source('workflow_run', {'workflow_run': run}, 'owner/repo')


def test_hash_matched_cached_report_and_mismatch(tmp_path, monkeypatch):
    path = tmp_path / 'app.exe'
    path.write_bytes(b'fixture')
    client = vt.VTClient('test-only')
    data = {'data': {'id': 'a' * 64, 'attributes': {'last_analysis_date': 1793110000, 'last_analysis_stats': STATS}}}
    monkeypatch.setattr(client, 'request', lambda *_: data)
    assert client.scan(path, 'a' * 64)['stats']['malicious'] == 1
    with pytest.raises(ValueError, match='hash mismatch'):
        client.scan(path, 'b' * 64)


def test_new_upload_waits_for_completed_analysis(tmp_path, monkeypatch):
    path = tmp_path / 'app.exe'
    path.write_bytes(b'fixture')
    client = vt.VTClient('test-only')
    calls = []
    responses = iter([None, {'data': {'id': 'analysis'}},
                      {'data': {'attributes': {'status': 'queued', 'stats': {}}}},
                      {'data': {'attributes': {'status': 'completed', 'stats': STATS, 'date': 1793110000}},
                       'meta': {'file_info': {'sha256': 'a' * 64}}}])
    def request(*args):
        calls.append(args)
        return next(responses)
    monkeypatch.setattr(client, 'request', request)
    result = client.scan(path, 'a' * 64)
    assert result['status'] == 'Completed' and result['source'] == 'New analysis'
    assert len(calls) == 4 and calls[1][0] == 'files'


def test_large_upload_uses_one_time_url(tmp_path, monkeypatch):
    class LargeFile:
        name = 'app.exe'
        def stat(self):
            return type('Stat', (), {'st_size': 44_000_000})()
        def read_bytes(self):
            return b'fixture'
    client = vt.VTClient('test-only')
    calls = []
    responses = iter([None, {'data': 'https://bigfiles.virustotal.com/upload/fixture'}, {'data': {'id': 'analysis'}},
                      {'data': {'attributes': {'status': 'completed', 'stats': STATS, 'date': 1793110000}},
                       'meta': {'file_info': {'sha256': 'a' * 64}}}])
    def request(*args):
        calls.append(args)
        return next(responses)
    monkeypatch.setattr(client, 'request', request)
    client.scan(LargeFile(), 'a' * 64)
    assert calls[1][0] == 'files/upload_url'
    assert calls[2][0] == 'https://bigfiles.virustotal.com/upload/fixture'


def test_empty_statistics_never_become_zero_detections():
    with pytest.raises(ValueError):
        vt.completed({}, 1793110000, 'New analysis')
    with pytest.raises(ValueError):
        vt.completed({k: 0 for k in vt.CATEGORIES}, 1793110000, 'New analysis')


def test_missing_key_publishes_explicit_incomplete_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('VT_API_KEY', raising=False)
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    Path('scan-context.json').write_text(json.dumps({'kind': 'release', 'tag': 'windows-v0.1.0'}))
    Path('scan-inputs').mkdir()
    for name in vt.FILES:
        (Path('scan-inputs') / name).write_bytes(b'fixture')
    assert vt.scan_files() == 1
    text = Path('scan-report/VIRUSTOTAL.md').read_text()
    assert 'Not completed' in text and 'VT_API_KEY is not configured' in text
    assert '| 0 |' not in text


def test_detections_and_unsupported_engines_are_reported():
    record = {'name': 'app.exe', 'sha256': 'a' * 64, 'url': 'https://www.virustotal.com/gui/file/' + 'a' * 64}
    record.update(vt.completed(STATS, 1793110000, 'New analysis'))
    text = vt.markdown({'commit': 'commit'}, [record])
    assert '| 1 | 2 | 60 | 0 | 5 |' in text
    assert 'not a safety guarantee' in text


def test_throttle_is_retried_without_logging_key(monkeypatch):
    client = vt.VTClient('test-only')
    calls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"data": {"id": "result"}}'
    def request(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise vt.HTTPError('https://www.virustotal.com/', 429, 'Quota', {}, None)
        return Response()
    monkeypatch.setattr(vt, 'urlopen', request)
    monkeypatch.setattr(vt.time, 'sleep', lambda _: None)
    assert client.request('files/hash')['data']['id'] == 'result'
    assert len(calls) == 2


def test_upload_cannot_send_key_to_another_host():
    with pytest.raises(ValueError, match='Unexpected'):
        vt.VTClient('test-only').request('https://example.com/upload', b'fixture')


def test_official_large_file_host_is_accepted(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"data": {"id": "analysis"}}'
    def request(req, **kwargs):
        assert req.full_url == 'https://bigfiles.virustotal.com/upload/fixture'
        return Response()
    monkeypatch.setattr(vt, 'urlopen', request)
    assert vt.VTClient('test-only').request('https://bigfiles.virustotal.com/upload/fixture', b'fixture')['data']['id'] == 'analysis'
