#!/usr/bin/env python3
"""Prepare new private candidate files. Never change/reload the active game script.

Run on a private copy of the current script, review, then install only while
the game is stopped in an explicitly approved maintenance window.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

MARKER = '// DNFGM_PRIVATE_MESSAGE_V1'


def private_source(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Private owned script copy required')
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or MARKER.encode() in raw:
        raise ValueError('Oversized or already adapted source')
    return raw


def create(path, body):
    path = Path(path)
    if not path.is_absolute() or path.resolve() in (Path('/var/lib/dnf/data/frida.js'), Path('/data/frida.js')):
        raise ValueError('New absolute candidate path required; active script forbidden')
    parent = path.parent.stat()
    if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise ValueError('Private owned candidate directory required')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())


def prepare(source, output, config_output, expected_source_sha256):
    if not re.fullmatch('[a-f0-9]{64}', expected_source_sha256):
        raise ValueError('Explicit source fingerprint required')
    raw = private_source(source)
    if hashlib.sha256(raw).hexdigest() != expected_source_sha256:
        raise ValueError('Source script fingerprint mismatch')
    text = raw.decode('utf-8')
    if 'function start(' not in text or 'api_scheduleOnMainThread' not in text or 'rpc.exports' not in text:
        raise ValueError('Current script requires manual adaptation')
    fragment = Path(__file__).with_name('private_message_bridge.js').read_bytes()
    token = secrets.token_hex(32)
    wrapper = ("\n" + MARKER + "\n(function () {\n"
        "  var originalStart = start;\n"
        "  start = function () {\n"
        "    originalStart.apply(this, arguments);\n"
        "    DnfGmPrivateMessage.start({token:" + json.dumps(token) + "}).catch(function () {\n"
        "      console.error('DNF GM private message bridge unavailable');\n"
        "    });\n"
        "  };\n"
        "  var originalDispose = rpc.exports.dispose;\n"
        "  rpc.exports.dispose = function () {\n"
        "    DnfGmPrivateMessage.stop();\n"
        "    if (originalDispose) return originalDispose.apply(this, arguments);\n"
        "  };\n"
        "})();\n").encode()
    candidate = raw + b'\n' + fragment + wrapper
    fingerprint = hashlib.sha256(candidate).hexdigest()
    create(output, candidate)
    create(config_output, json.dumps({'token': token, 'script_sha256': fingerprint}, separators=(',', ':')).encode() + b'\n')
    return fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'config-output', 'source-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    fingerprint = prepare(args.source, args.output, args.config_output, args.source_sha256)
    print(json.dumps({'state': 'candidate_prepared', 'script_sha256': fingerprint,
                      'activated': False, 'game_restarted': False}))


if __name__ == '__main__':
    main()
