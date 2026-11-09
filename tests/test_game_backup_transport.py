"""Fixed transport protocol; synthetic age/SSH helpers never contact a host."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import pytest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'deploy' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


copy = module('game_backup_copy_tests', 'game_backup_copy.py')
receiver = module('game_backup_receive_tests', 'game_backup_receive.py')
BID = 'a' * 32
REMOTE = 'b' * 64
CONFIG = {'age_recipient': 'age1' + 'q' * 58, 'ssh_config': str(Path.cwd() / 'fixed-ssh'),
          'ssh_host': 'game-backup', 'remote_machine_sha256': REMOTE}


def artifact(tmp_path):
    path = tmp_path / 'game.ndjson'
    path.write_bytes(b'private synthetic restore-point bytes\n')
    path.chmod(0o600)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def helper_calls(calls, *, wrong_receipt=False, mutate=None):
    def run(argv, *, stdin, output, timeout, max_output):
        calls.append(argv)
        data = stdin.read()
        if argv[0] == 'age':
            output.write(b'age-encryption.org/v1\n' + data)
            if mutate: mutate()
        else:
            assert argv[0] == 'ssh' and argv[-4] == 'dnf-gm-game-backup-receive'
            assert 'BatchMode=yes' in ' '.join(argv) and 'StrictHostKeyChecking=yes' in ' '.join(argv)
            receipt = {'version': 1, 'state': 'stored', 'backup_id': BID,
                       'cipher_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                       'machine_sha256': '0' * 64 if wrong_receipt else REMOTE}
            output.write(json.dumps(receipt).encode())
    return run


def test_copy_binds_plaintext_ciphertext_and_exact_remote_receipt(tmp_path, monkeypatch):
    path, sha = artifact(tmp_path); calls = []
    monkeypatch.setattr(copy, 'machine_sha256', lambda: 'c' * 64)
    result = copy.encrypted_copy(path, BID, sha, CONFIG, run=helper_calls(calls))
    assert [c[0] for c in calls] == ['age', 'ssh']
    assert result['artifact_sha256'] == sha and result['remote_machine_sha256'] == REMOTE
    assert result['encrypted'] and result['remote_received_and_hashed']
    assert result['remote_restore_verified'] is False
    binding = json.loads((tmp_path / (BID + '.ndjson.age.binding.json')).read_text())
    assert binding['artifact_sha256'] == sha
    assert binding['encrypted_sha256'] == result['encrypted_sha256']


def test_same_machine_and_changed_source_are_rejected_before_transport(tmp_path, monkeypatch):
    path, sha = artifact(tmp_path); calls = []
    monkeypatch.setattr(copy, 'machine_sha256', lambda: REMOTE)
    with pytest.raises(ValueError, match='Same-machine'):
        copy.encrypted_copy(path, BID, sha, CONFIG, run=helper_calls(calls))
    monkeypatch.setattr(copy, 'machine_sha256', lambda: 'c' * 64)
    with pytest.raises(ValueError, match='checksum mismatch'):
        copy.encrypted_copy(path, BID, 'd' * 64, CONFIG, run=helper_calls(calls))
    assert not calls


def test_wrong_remote_machine_receipt_never_claims_copy_verified(tmp_path, monkeypatch):
    path, sha = artifact(tmp_path)
    monkeypatch.setattr(copy, 'machine_sha256', lambda: 'c' * 64)
    with pytest.raises(ValueError, match='receipt did not match'):
        copy.encrypted_copy(path, BID, sha, CONFIG, run=helper_calls([], wrong_receipt=True))


def test_source_mutation_during_encryption_never_sends_ciphertext(tmp_path, monkeypatch):
    path, sha = artifact(tmp_path); calls = []
    monkeypatch.setattr(copy, 'machine_sha256', lambda: 'c' * 64)
    with pytest.raises(ValueError, match='changed during encryption'):
        copy.encrypted_copy(path, BID, sha, CONFIG,
                            run=helper_calls(calls, mutate=lambda: path.write_bytes(b'changed')))
    assert [c[0] for c in calls] == ['age']


@pytest.mark.parametrize('changes', [{'ssh_host': 'host;evil'}, {'ssh_config': 'relative'},
                                   {'age_recipient': 'not-an-age-key'}, {'remote_machine_sha256': 'unknown'}])
def test_copy_requires_an_explicit_reviewed_fixed_destination(changes):
    with pytest.raises(ValueError): copy.validate_copy({**CONFIG, **changes})


def test_fast_exiting_helper_cannot_bypass_output_budget():
    with tempfile.TemporaryFile() as output:
        with pytest.raises(ValueError, match='excess output'):
            copy.checked_process([sys.executable, '-c', 'import sys;sys.stdout.write("x"*100000)'],
                                 output=output, timeout=5, max_output=8)


def test_stalled_helper_is_killed_within_fixed_budget():
    began = time.monotonic()
    with tempfile.TemporaryFile() as output:
        with pytest.raises(TimeoutError):
            copy.checked_process([sys.executable, '-c', 'import time;time.sleep(30)'], output=output, timeout=0.02)
    assert time.monotonic() - began < 5


@pytest.mark.skipif(os.name == 'nt', reason='Receiver requires real POSIX ownership, modes and directory fsync')
def test_receiver_validates_and_replays_without_replacing_snapshot(tmp_path):
    tmp_path.chmod(0o700)
    data = b'age-encryption.org/v1\n' + b'opaque encrypted bytes'
    sha = hashlib.sha256(data).hexdigest()
    command = f'dnf-gm-game-backup-receive {BID} {sha} {len(data)}'
    first = receiver.receive(command, io.BytesIO(data), root=tmp_path)
    target = tmp_path / (BID + '.ndjson.age')
    inode = target.stat().st_ino
    assert receiver.receive(command, io.BytesIO(data), root=tmp_path) == first
    assert target.stat().st_ino == inode and target.read_bytes() == data
    other = data + b'changed'
    with pytest.raises(ValueError, match='different content'):
        receiver.receive(f'dnf-gm-game-backup-receive {BID} {hashlib.sha256(other).hexdigest()} {len(other)}',
                         io.BytesIO(other), root=tmp_path)
    assert target.read_bytes() == data


@pytest.mark.skipif(os.name == 'nt', reason='Receiver requires real POSIX ownership, modes and directory fsync')
@pytest.mark.parametrize('data', [b'plaintext is forbidden', b'age-encryption.org/v1\ntruncated'])
def test_receiver_never_publishes_plaintext_or_truncated_content(tmp_path, data):
    tmp_path.chmod(0o700)
    with pytest.raises(ValueError):
        receiver.receive(f'dnf-gm-game-backup-receive {BID} {"c" * 64} {len(data) + 1}', io.BytesIO(data), root=tmp_path)
    assert not (tmp_path / (BID + '.ndjson.age')).exists()
