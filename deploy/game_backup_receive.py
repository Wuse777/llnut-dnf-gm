#!/usr/bin/env python3
"""Forced SSH command for an explicitly provisioned offsite backup account.

authorized_keys command="/usr/local/bin/dnf-gm-game-backup-receive",restrict ...
The account has write access only to /var/backups/dnf-gm-offsite. No shell,
arbitrary destination, plaintext content, overwrites or remote restore operation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import signal
import shutil
import sys
import time

ROOT = Path('/var/backups/dnf-gm-offsite')
MAX_BYTES = 9 * 1024 ** 3


def existing_hash(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid()
                or st.st_mode & 0o077 or not 0 < st.st_size <= MAX_BYTES):
            raise ValueError('Existing encrypted artifact is untrusted')
        digest = hashlib.sha256(); total = 0
        while part := f.read(65536):
            total += len(part)
            if total > MAX_BYTES:
                raise ValueError('Existing artifact grew beyond fixed budget')
            digest.update(part)
        return digest.hexdigest(), st.st_size


def receive(command, source, *, root=ROOT, budget=900):
    match = re.fullmatch(r'dnf-gm-game-backup-receive ([a-f0-9]{32}) ([a-f0-9]{64}) ([1-9][0-9]{0,10})', command)
    if match is None:
        raise ValueError('Only the fixed encrypted-copy protocol is accepted')
    backup_id, expected_sha, count = match.groups(); count = int(count)
    if not 1 <= count <= MAX_BYTES:
        raise ValueError('Encrypted snapshot outside fixed size budget')
    root = Path(root)
    st = root.lstat()
    if not root.is_absolute() or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise ValueError('Private destination root required')
    machine = Path('/etc/machine-id').read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{32}', machine):
        raise ValueError('Offsite machine identity unavailable')
    target = root / (backup_id + '.ndjson.age')
    partial = root / (backup_id + '.ndjson.age.partial')
    # An idempotent transport replay validates and drains the same ciphertext;
    # an existing snapshot is never replaced or accepted merely by its filename.
    old = None
    if target.exists() or target.is_symlink():
        old = existing_hash(target)
        if old != (expected_sha, count):
            raise ValueError('Offsite backup id already has different content')
    if old is None and shutil.disk_usage(root).free < count + 64 * 1024 ** 2:
        raise ValueError('Offsite private disk reserve insufficient')
    fd = None if old else os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    digest = hashlib.sha256(); size = 0; deadline = time.monotonic() + budget
    # systemd/sshd external time limits also apply if a sender stalls in read().
    output = os.fdopen(fd, 'wb') if fd is not None else None
    try:
        first = True
        while chunk := source.read(65536):
            if time.monotonic() > deadline:
                raise TimeoutError('Offsite receive deadline exceeded')
            if first:
                if not chunk.startswith(b'age-encryption.org/v1\n'):
                    raise ValueError('Only age-encrypted artifacts are accepted')
                first = False
            size += len(chunk)
            if size > count:
                raise ValueError('Offsite copy exceeded declared bytes')
            digest.update(chunk)
            if output:
                output.write(chunk)
        if size != count or digest.hexdigest() != expected_sha:
            raise ValueError('Offsite copy checksum or size mismatch')
        if output:
            output.flush(); os.fsync(output.fileno()); output.close(); output = None
            os.link(partial, target); partial.unlink()
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return {'version': 1, 'state': 'stored', 'backup_id': backup_id, 'cipher_sha256': expected_sha,
                'bytes': size, 'machine_sha256': hashlib.sha256(machine.encode()).hexdigest()}
    finally:
        if output:
            output.close()


if __name__ == '__main__':
    try:
        def timed_out(*_):raise TimeoutError('Offsite receive deadline exceeded')
        signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(900)
        print(json.dumps(receive(os.environ.get('SSH_ORIGINAL_COMMAND', ''), sys.stdin.buffer), sort_keys=True))
    except Exception:
        print('Encrypted backup was not accepted; partial private evidence retained.', file=sys.stderr)
        raise SystemExit(1) from None
