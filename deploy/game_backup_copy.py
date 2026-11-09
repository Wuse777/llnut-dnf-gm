"""Fixed, explicitly configured age-encrypted SSH copy; no browser destinations."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from dnfgm.game_backup import file_hash, fsync_directory, ID, HEX, MAX_ENCRYPTED_BYTES


def machine_sha256():
    value = Path('/etc/machine-id').read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Local machine identity unavailable')
    return hashlib.sha256(value.encode()).hexdigest()


def validate_copy(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'age_recipient', 'ssh_config', 'ssh_host', 'remote_machine_sha256'}
            or not re.fullmatch(r'age1[023456789acdefghjklmnpqrstuvwxyz]{58}', value['age_recipient'])
            or not Path(value['ssh_config']).is_absolute()
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}', value['ssh_host'])
            or not HEX.fullmatch(value['remote_machine_sha256'])):
        raise ValueError('Explicit reviewed age recipient/SSH destination required')
    return value


def checked_process(argv, *, stdin=None, output, timeout, max_output=None):
    # No shell. Both outputs are private bounded files, preventing a remote peer
    # from growing a PIPE buffer or filling the application's memory.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                                   stdout=output, stderr=errors, close_fds=True)
        began = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() - began > timeout:
                    raise TimeoutError('Fixed backup copy exceeded time budget')
                if errors.tell() > 65536:
                    raise ValueError('Fixed backup helper produced excess diagnostics')
                if max_output is not None and output.tell() > max_output:
                    raise ValueError('Fixed backup helper produced excess output')
                time.sleep(0.05)
            if (errors.tell() > 65536 or (max_output is not None and output.tell() > max_output)):
                raise ValueError('Fixed backup helper produced excess output')
            if process.returncode != 0:
                raise ValueError('Fixed backup helper did not complete')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def encrypted_copy(artifact, backup_id, expected_sha256, config, *, budget=900, run=checked_process):
    config = validate_copy(config)
    if config is None or not ID.fullmatch(backup_id) or not HEX.fullmatch(expected_sha256):
        raise ValueError('Configured copy and explicit original backup required')
    if config['remote_machine_sha256'] == machine_sha256():
        raise ValueError('Same-machine destination is not an offsite copy')
    if file_hash(artifact)[0] != expected_sha256:
        raise ValueError('Original restore point checksum mismatch')
    cipher = Path(artifact).with_name(backup_id + '.ndjson.age')
    partial = cipher.with_name(cipher.name + '.partial')
    started = time.time()
    if cipher.exists():
        # An encrypted file is reusable only with a previously recorded binding;
        # never assume an arbitrary existing ciphertext belongs to this artifact.
        binding_path = cipher.with_name(cipher.name + '.binding.json')
        from dnfgm.release_files import read_json
        binding = read_json(binding_path, owner=0)
        if (binding.get('artifact_sha256') != expected_sha256 or binding.get('recipient') != config['age_recipient']
                or file_hash(cipher, max_bytes=MAX_ENCRYPTED_BYTES) != (binding.get('encrypted_sha256'), binding.get('encrypted_bytes'))):
            raise ValueError('Encrypted restore point binding changed')
    else:
        source_bytes = Path(artifact).stat().st_size
        required = source_bytes + max(1024 ** 2, source_bytes // 100) + 2 * 1024 ** 3
        if shutil.disk_usage(Path(artifact).parent).free < required:
            raise ValueError('Insufficient private disk reserve for encryption')
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as output, open(artifact, 'rb') as source:
            run(['age', '-r', config['age_recipient']], stdin=source, output=output, timeout=budget, max_output=MAX_ENCRYPTED_BYTES)
            output.flush(); os.fsync(output.fileno())
        if file_hash(artifact)[0] != expected_sha256:
            raise ValueError('Original restore point changed during encryption')
        from dnfgm.game_backup import write_new
        encrypted_sha, encrypted_bytes = file_hash(partial, max_bytes=MAX_ENCRYPTED_BYTES)
        write_new(cipher.with_name(cipher.name + '.binding.json'),
                  {'artifact_sha256': expected_sha256, 'recipient': config['age_recipient'],
                   'encrypted_sha256': encrypted_sha, 'encrypted_bytes': encrypted_bytes})
        os.link(partial, cipher); partial.unlink(); fsync_directory(cipher.parent)
    encrypted_sha, encrypted_bytes = file_hash(cipher, max_bytes=MAX_ENCRYPTED_BYTES)
    with tempfile.TemporaryFile() as response, open(cipher, 'rb') as source:
        run(['ssh', '-F', config['ssh_config'], '-T', '-oBatchMode=yes', '-oStrictHostKeyChecking=yes',
             '-oIdentitiesOnly=yes', '-oClearAllForwardings=yes', '-oForwardAgent=no',
             config['ssh_host'], 'dnf-gm-game-backup-receive', backup_id, encrypted_sha, str(encrypted_bytes)],
            stdin=source, output=response, timeout=max(1, budget - (time.time() - started)), max_output=65536)
        response.seek(0)
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Oversized offsite receiver receipt')
    result = json.loads(raw)
    expected = {'version': 1, 'state': 'stored', 'backup_id': backup_id, 'cipher_sha256': encrypted_sha,
                'bytes': encrypted_bytes, 'machine_sha256': config['remote_machine_sha256']}
    if result != expected:
        raise ValueError('Offsite receipt did not match the encrypted restore point')
    return {'kind': 'copy', 'scope': 'game_databases', 'state': 'verified', 'backup_id': backup_id,
            'artifact_sha256': expected_sha256, 'encrypted_sha256': encrypted_sha, 'encrypted_bytes': encrypted_bytes,
            'remote_machine_sha256': result['machine_sha256'], 'started_at': started, 'completed_at': time.time(),
            'encrypted': True, 'remote_received_and_hashed': True, 'remote_restore_verified': False}
