"""Restore-point evidence remains accurate across failures and pagination."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dnfgm.game_backup_requests import GameBackups, GameBackupConfirm, GameBackupPreview
from pydantic import ValidationError


SHA = 'a' * 64
BID = 'b' * 32


def row(number, action='copy', state='failed', sha=SHA, backup_id=BID):
    return {'run_id': f'{number:032x}', 'backup_id': backup_id, 'action': action,
            'window_id': 'c' * 32, 'reason': '核对恢复点', 'state': state, 'fingerprint': 'd' * 64,
            'created_at': number, 'expires_at': number + 300, 'started_at': number,
            'finished_at': number + 1, 'error_code': None,
            'result_json': json.dumps({'artifact_sha256': sha, 'state': 'verified'}) if state == 'succeeded' else None}


class Cursor:
    def __init__(self, rows): self.rows, self.result = rows, []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def fetchone(self): return self.result[0] if self.result else None
    def fetchall(self): return self.result
    def execute(self, query, args=()):
        rows = list(self.rows)
        if 'WHERE run_id=%s' in query:
            rows = [r for r in rows if r['run_id'] == args[0]]
        elif 'WHERE backup_id=%s' in query:
            rows = [r for r in rows if r['backup_id'] == args[0]]
        if "action='backup'" in query: rows = [r for r in rows if r['action'] == 'backup']
        if 'action=%s' in query: rows = [r for r in rows if r['action'] == args[1]]
        if "state='succeeded'" in query: rows = [r for r in rows if r['state'] == 'succeeded']
        if 'JSON_EXTRACT' in query:
            rows = [r for r in rows if json.loads(r['result_json'])['artifact_sha256'] == args[2]]
        rows.sort(key=lambda r: (r['created_at'], r['run_id']), reverse=True)
        if 'LIMIT 1' in query: rows = rows[:1]
        elif 'LIMIT 21' in query: rows = rows[args[0]:args[0] + 21]
        elif 'LIMIT 20' in query: rows = rows[:20]
        self.result = rows


class Connection:
    def __init__(self, rows): self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def cursor(self): return Cursor(self.rows)


def service(rows):
    db = SimpleNamespace(connect=lambda: Connection(rows))
    instance = GameBackups(db, SimpleNamespace(game_backup_status_file='/unused'))
    instance.installed = lambda: {'configured': True}
    return instance


def original():
    return {**row(1, 'backup', 'succeeded'), 'run_id': BID}


def test_detail_has_original_and_independent_success_beyond_twenty_recent_failures():
    rows = [original(), row(2, 'copy', 'succeeded'), row(3, 'rehearse', 'succeeded')]
    rows += [row(n) for n in range(4, 35)]
    result = service(rows).detail(f'{34:032x}')
    assert result['original_backup']['run_id'] == BID
    assert len(result['related_runs']) == 20
    assert result['evidence']['copy']['latest_attempt']['state'] == 'failed'
    assert result['evidence']['copy']['verified_run']['run_id'] == f'{2:032x}'
    assert result['evidence']['rehearse']['verified_run']['run_id'] == f'{3:032x}'
    assert result['evidence']['artifact_sha256'] == SHA


def test_success_for_another_artifact_is_never_reused():
    result = service([original(), row(2, 'copy', 'succeeded', sha='e' * 64)]).detail(BID)
    assert result['evidence']['copy']['latest_attempt']['state'] == 'succeeded'
    assert result['evidence']['copy']['verified_run'] is None
    assert result['evidence']['rehearse']['verified_run'] is None


def test_latest_successful_backup_and_evidence_are_independent_of_current_page():
    rows = [original(), row(2, 'copy', 'succeeded')] + [row(n) for n in range(3, 50)]
    result = service(rows).view(page=3)
    assert result['latest_backup']['run_id'] == BID
    assert result['latest_backup']['evidence']['copy']['verified_run']['run_id'] == f'{2:032x}'
    assert result['page'] == 3


def test_failed_backup_does_not_advertise_followup_verification():
    source = {**original(), 'state': 'failed', 'result_json': None}
    result = service([source, row(2, 'copy', 'succeeded')]).detail(BID)
    assert result['evidence']['copy']['verified_run'] is None
    assert service([source]).view()['latest_backup'] is None


def test_missing_request_is_explicit_and_browser_cannot_supply_backup_path_or_sql():
    with pytest.raises(HTTPException, match='404'): service([]).detail('f' * 32)
    with pytest.raises(ValidationError):
        GameBackupPreview(request_id='a' * 32, window_id='b' * 32, reason='备份', path='/tmp/other')
    with pytest.raises(ValidationError):
        GameBackupConfirm(fingerprint='a' * 64, acknowledge_game_scope=True, sql='DROP DATABASE game')
