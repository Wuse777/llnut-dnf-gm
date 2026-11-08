#!/usr/bin/env python3
"""Opt-in root relay. Fixed Unix sockets and typed messages only; no game start.

Installed separately during a maintenance window, never by the normal updater.
The application cannot read the bridge token, game files or dispatch journal.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import sqlite3
import stat
import struct
import time

from dnfgm.private_message import BRIDGE_VERSION, GAME_SHA256, SOCKET, message_text, read_frame

CONFIG = Path('/etc/dnf-gm/private-message.json')
PLUGIN = '/var/lib/dnf/data/.dnfgm-private-message.sock'
SCRIPT = Path('/var/lib/dnf/data/frida.js')
JOURNAL = '/var/lib/dnf-gm/private-message/dispatch.sqlite'
REASONS = {'primitive_invoked', 'target_offline', 'character_changed', 'expired',
           'duplicate_operation', 'busy', 'invalid_request', 'primitive_failed'}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def credentials(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))


def configuration():
    fd = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1:
            raise ValueError('Private relay configuration required')
        raw = stream.read(4097)
    data = json.loads(raw)
    if (len(raw) > 4096 or set(data) != {'token', 'script_sha256'}
            or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v) for v in data.values())):
        raise ValueError('Invalid relay configuration')
    if digest(SCRIPT) != data['script_sha256']:
        raise ValueError('Installed script fingerprint mismatch')
    return data


def validate(request):
    if request == {'action': 'status'}:
        return request
    if (not isinstance(request, dict) or set(request) != {'action', 'operation_id', 'uid', 'charac_no', 'message'}
            or request['action'] != 'send'
            or not isinstance(request['operation_id'], str) or not re.fullmatch('[a-f0-9]{32}', request['operation_id'])
            or any(type(request[k]) is not int or not 1 <= request[k] <= 0x7fffffff for k in ('uid', 'charac_no'))):
        raise ValueError('Invalid typed request')
    message_text(request['message'])
    return request


class Relay:
    def __init__(self, config, journal=JOURNAL):
        self.config = config
        self.script_stat = SCRIPT.stat()
        self.journal = sqlite3.connect(journal)
        os.chmod(journal, 0o600)
        self.journal.execute('PRAGMA synchronous=FULL')
        self.journal.execute('CREATE TABLE IF NOT EXISTS claims(operation_id TEXT PRIMARY KEY,claimed_at INTEGER NOT NULL)')
        self.journal.commit()

    def claim(self, operation_id):
        # Commit before the first potentially effective byte; never replay a
        # claim after exceptions, service restart, game reload or client retry.
        if self.journal.execute('SELECT COUNT(*) FROM claims').fetchone()[0] >= 10000:
            return 'busy'
        try:
            self.journal.execute('INSERT INTO claims VALUES(?,?)', (operation_id, int(time.time())))
            self.journal.commit()
            return None
        except sqlite3.IntegrityError:
            self.journal.rollback()
            return 'duplicate_operation'

    def forward(self, request):
        st = SCRIPT.stat()
        if (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) != (
                self.script_stat.st_ino, self.script_stat.st_size, self.script_stat.st_mtime_ns, self.script_stat.st_ctime_ns):
            raise ValueError('Script changed; explicit relay restart required')
        target = os.lstat(PLUGIN)
        if not stat.S_ISSOCK(target.st_mode) or target.st_uid != 0 or stat.S_IMODE(target.st_mode) != 0o600:
            raise ValueError('Private game socket required')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.25)
            sock.connect(PLUGIN)
            pid, uid, _ = credentials(sock)
            if uid != 0 or digest('/proc/' + str(pid) + '/exe') != GAME_SHA256:
                raise ValueError('Running game fingerprint mismatch')
            envelope = {**request, 'token': self.config['token']}
            if request['action'] == 'send':
                envelope['expires_at'] = time.time() + 1.0
            sock.sendall(json.dumps(envelope, ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
            return read_frame(sock)

    def handle(self, request):
        validate(request)
        if request['action'] == 'status':
            try:
                data = self.forward(request)
                ready = data == {'ready': True, 'bridge_version': BRIDGE_VERSION, 'game_sha256': GAME_SHA256}
            except (OSError, ValueError, TypeError):
                ready = False
            return {'ready': ready, 'bridge_version': BRIDGE_VERSION, 'game_sha256': GAME_SHA256}
        op = request['operation_id']
        result = {'operation_id': op, 'transport_status': 'not_sent', 'reason_code': 'bridge_unavailable'}
        reason = self.claim(op)
        if reason:
            return {**result, 'reason_code': reason}
        # A forward failure may follow a successful primitive invocation. The
        # durable claim is deliberately retained even on pre-send failures.
        try:
            data = self.forward(request)
            if (set(data) != set(result) or data['operation_id'] != op
                    or data['transport_status'] not in ('sent', 'not_sent', 'uncertain')
                    or data['reason_code'] not in REASONS
                    or (data['transport_status'] == 'sent') != (data['reason_code'] == 'primitive_invoked')):
                raise ValueError('Invalid bridge response')
            return data
        except (OSError, ValueError, TypeError):
            return {**result, 'transport_status': 'uncertain'}


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root relay required')
    os.umask(0o077)
    account = pwd.getpwnam('dnfgm')
    config = configuration()
    relay = Relay(config)
    path = Path(SOCKET)
    if path.exists() or path.is_symlink():
        st = path.lstat()
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != 0:
            raise ValueError('Unsafe relay socket')
        path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(SOCKET)
        os.chown(SOCKET, 0, account.pw_gid)
        os.chmod(SOCKET, 0o660)
        server.listen(2)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2.0)
                try:
                    _, uid, _ = credentials(connection)
                    if uid != account.pw_uid:
                        continue
                    result = relay.handle(read_frame(connection))
                    connection.sendall(json.dumps(result, separators=(',', ':')).encode() + b'\n')
                except (OSError, ValueError, TypeError):
                    # No raw request, token, filesystem, native address or player
                    # message is emitted to stdout, journal or public health.
                    continue


if __name__ == '__main__':
    main()
