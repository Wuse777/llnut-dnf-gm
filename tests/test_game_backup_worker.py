"""Real POSIX maintenance fences/journals; all service/DB adapters synthetic."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

if os.name == 'nt':
    pytest.skip('Game worker requires genuine POSIX fences and private ownership', allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
from game_backup_worker import GameBackupWorker, request_spec
from dnfgm.game_backup import canonical, file_hash, new_private, write_new
from dnfgm.release_files import Refused, atomic_json
from test_maintenance_session import session, rig


def setup(session, tmp_path):
    s, c, h, plan = session
    s.open('a' * 32)
    root = tmp_path / 'game-backups';root.mkdir(mode=0o700)
    settings = SimpleNamespace(game_backup_status_file=str(tmp_path / 'game-backup-status.json'))
    worker = GameBackupWorker(SimpleNamespace(coordinator=c, session=s), settings,
                              root=root, owner=os.geteuid(), connect=lambda **_: SimpleNamespace(close=lambda: None))
    spec = {'request_id': 'b' * 32, 'window_id': 'a' * 32, 'reason': '真实屏障合成备份',
            **{k: plan['identity'][k] for k in ('image_digest', 'pvf_sha256', 'program_sha256')}}
    row = {'run_id': 'b' * 32, 'backup_id': 'b' * 32, 'window_id': 'a' * 32, 'action': 'backup',
           'reason': spec['reason'], 'state': 'running', 'fingerprint': hashlib.sha256(canonical(spec)).hexdigest(),
           'spec_json': json.dumps(spec), 'started_at': time.time() - 1}
    config = {'connection': {}, 'schemas': ['fixture'], 'relations': []}
    return worker, row, config, s, c, h


def saved_dump(source, output, *, binding, guard, **_):
    guard()
    with os.fdopen(new_private(output), 'wb') as f:f.write(b'private synthetic game artifact\n')
    source.close()
    sha, size = file_hash(output)
    return {'format': 'dnfgm-game-1', 'scope': 'game_databases', 'state': 'complete', 'kind': 'backup',
            'artifact_sha256': sha, 'bytes': size, 'binding': binding, 'started_at': time.time() - 0.1,
            'completed_at': time.time(), 'consistency': 'all_business_tables_read_locked', 'rows': 0, 'tables': 1}


def test_backup_holds_real_global_and_inventory_fences_without_service_commands(session, tmp_path, monkeypatch):
    worker, row, config, s, c, h = setup(session, tmp_path)
    before = copy.deepcopy(h.calls)
    def dump(source, output, **options):
        with pytest.raises(Refused, match='busy'):
            with c.locked():pass
        with pytest.raises(Refused, match='busy'):
            with s.window.locked(False):pass
        with pytest.raises(Refused, match='busy'):s.window.refresh()
        with pytest.raises(Refused, match='busy'):s.window.close(row['window_id'])
        with pytest.raises(Refused, match='busy'):s.close_restore(row['window_id'])
        return saved_dump(source, output, **options)
    monkeypatch.setattr('game_backup_worker.dump_game', dump)
    result = worker.backup(row, config)
    assert result['state'] == 'complete' and h.calls == before
    assert c.admission.gate.read()['state'] == 'frozen'
    assert s.window.status()['id'] == row['window_id']
    assert worker.durable_receipt(row)['evidence_reconciled'] is True


def test_reopened_writer_or_replaced_permit_aborts_live_guard(session, tmp_path, monkeypatch):
    worker, row, config, s, c, h = setup(session, tmp_path)
    def dump(source, output, *, guard, **_):
        permit = json.loads((s.window.root / 'permit.json').read_text())
        atomic_json(s.window.root / 'permit.json', {**permit, 'id': 'f' * 32})
        guard()
        raise AssertionError('Changed original permit must abort')
    monkeypatch.setattr('game_backup_worker.dump_game', dump)
    with pytest.raises(ValueError, match='permit changed'):worker.backup(row, config)
    assert not (worker.root / ('game-' + row['backup_id']) / 'manifest.json').exists()
    assert c.admission.gate.read()['state'] == 'frozen'


def test_changed_specification_cannot_open_a_source_connection(session, tmp_path):
    worker, row, config, s, c, h = setup(session, tmp_path)
    def unexpected(**_):raise AssertionError('Must validate spec before connecting')
    worker.connect = unexpected
    row['spec_json'] = row['spec_json'].replace('真实屏障合成备份', 'changed')
    # json.dumps escapes Chinese by default, so change a bound ASCII digest.
    spec = json.loads(row['spec_json']);spec['program_sha256'] = 'f' * 64
    row['spec_json'] = json.dumps(spec)
    with pytest.raises(ValueError, match='specification changed'):worker.backup(row, config)


def test_completed_manifest_reconciles_read_only_but_modified_file_does_not(session, tmp_path, monkeypatch):
    worker, row, config, s, c, h = setup(session, tmp_path)
    monkeypatch.setattr('game_backup_worker.dump_game', saved_dump)
    worker.backup(row, config)
    before = copy.deepcopy(h.calls)
    worker.connect = lambda **_: pytest.fail('Receipt recovery must never open a DB source')
    assert worker.durable_receipt(row)['evidence_reconciled']
    assert h.calls == before
    artifact = worker.root / ('game-' + row['backup_id']) / 'game.ndjson'
    with artifact.open('ab') as output:output.write(b'changed')
    with pytest.raises(ValueError, match='evidence incomplete'):worker.durable_receipt(row)


def test_copy_and_rehearsal_receipts_are_separate_and_match_original_artifact(session, tmp_path, monkeypatch):
    worker, row, config, s, c, h = setup(session, tmp_path)
    monkeypatch.setattr('game_backup_worker.dump_game', saved_dump)
    original = worker.backup(row, config)
    spec = {'request_id': 'd' * 32, 'reason': '核对异地副本', 'backup_id': row['backup_id'], 'action': 'copy',
            'artifact_sha256': original['artifact_sha256']}
    followup = {**row, 'run_id': spec['request_id'], 'action': 'copy', 'reason': spec['reason'],
                'spec_json': json.dumps(spec), 'fingerprint': hashlib.sha256(canonical(spec)).hexdigest()}
    folder = worker.root / ('game-' + row['backup_id'])
    receipt = {'scope': 'game_databases', 'kind': 'copy', 'state': 'verified', 'artifact_sha256': original['artifact_sha256'],
               'backup_id': row['backup_id'], 'encrypted': True, 'remote_received_and_hashed': True,
               'remote_restore_verified': False, 'encrypted_sha256': 'e' * 64,
               'started_at': time.time() - 0.1, 'completed_at': time.time()}
    write_new(folder / ('copy-' + followup['run_id'] + '.json'), receipt)
    assert worker.durable_receipt(followup)['remote_restore_verified'] is False
    # Copy evidence cannot act as a rehearsal receipt, nor prove another file.
    rehearse_spec = {**spec, 'action': 'rehearse'}
    rehearse = {**followup, 'action': 'rehearse', 'spec_json': json.dumps(rehearse_spec),
                'fingerprint': hashlib.sha256(canonical(rehearse_spec)).hexdigest()}
    with pytest.raises(FileNotFoundError):worker.durable_receipt(rehearse)
    (folder / ('copy-' + followup['run_id'] + '.json')).unlink()
    write_new(folder / ('copy-' + followup['run_id'] + '.json'), {**receipt, 'artifact_sha256': 'f' * 64})
    with pytest.raises(ValueError, match='identity/timing changed'):worker.durable_receipt(followup)
