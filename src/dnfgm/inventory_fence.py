"""Root-issued maintenance fence. No database, service or game mutations.

Application holds a shared lock THROUGH database commit, rechecking the original
permit immediately before commit. The operator must close (exclusive lock) before
manually restarting writers. This cannot prevent out-of-band privileged restarts.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import math
import os
import re
import stat
import time

from .release_files import Refused

ROOT_UID = 0
MAX_WINDOW = 3600
MAX_AGE = 30
MAX_CLOSE_BYTES = 16384
HEX = re.compile(r'[a-f0-9]{64}\Z')
BOUND_FIELDS = ('container_id', 'container_started_at', 'image_digest', 'pvf_sha256', 'program_sha256', 'components', 'boot_id', 'policy_sha256')


def directory(path, owner=ROOT_UID):
    """Reject symlinks and untrusted ancestors (root sticky parents are safe)."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise Refused('maintenance_directory_untrusted')
    for part in (*reversed(path.parents), path):
        st = part.lstat()
        # A root-owned sticky ancestor (e.g. /tmp) cannot have its root-owned
        # child renamed by another user. The leaf itself may never be writable.
        unsafe_write = st.st_mode & 0o022 and not (part != path and st.st_mode & stat.S_ISVTX)
        if not stat.S_ISDIR(st.st_mode) or (owner == 0 and (st.st_uid != 0 or unsafe_write)):
            raise Refused('maintenance_directory_untrusted')
    st = path.lstat()
    if st.st_uid != owner or st.st_mode & 0o022:
        raise Refused('maintenance_directory_untrusted')
    return path


def _identity(st):
    return st.st_dev, st.st_ino


def _regular(st, owner, limit=None):
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != owner
            or st.st_mode & 0o022 or (limit is not None and st.st_size > limit)):
        raise Refused('maintenance_file_untrusted')


def _dirfd(root, owner):
    path = directory(root, owner)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    if _identity(os.fstat(fd)) != _identity(path.lstat()):
        os.close(fd)
        raise Refused('maintenance_directory_changed')
    return fd


def open_lock(root, owner=ROOT_UID):
    d = _dirfd(root, owner)
    try:
        fd = os.open('fence.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=d)
        try:
            _regular(os.fstat(fd), owner)
            if _identity(os.fstat(fd)) != _identity(os.stat('fence.lock', dir_fd=d, follow_symlinks=False)):
                raise Refused('maintenance_lock_changed')
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(d)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused('maintenance_duplicate_json_key')
        result[key] = value
    return result


def _invalid(value):
    raise Refused('maintenance_invalid_json')


def _read(root, name, owner, limit):
    """Descriptor-relative reads; reject malformed, replaced or linked files."""
    d = _dirfd(root, owner)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=d)
        try:
            before = os.fstat(fd)
            _regular(before, owner, limit)
            raw = os.read(fd, limit + 1)
            after = os.fstat(fd)
            if (len(raw) > limit or len(raw) != before.st_size
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or _identity(after) != _identity(os.stat(name, dir_fd=d, follow_symlinks=False))):
                raise Refused('maintenance_file_changed')
            try:
                return json.loads(raw, parse_constant=_invalid, object_pairs_hook=_pairs)
            except (ValueError, UnicodeError) as error:
                raise Refused('maintenance_invalid_json') from error
        finally:
            os.close(fd)
    finally:
        os.close(d)


def validate_permit(permit, now, monotonic_now=None):
    monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
    required = {'version', 'id', 'created_at', 'expires_at', 'created_monotonic', 'expires_monotonic', 'reason', *BOUND_FIELDS}
    if (not isinstance(permit, dict) or set(permit) != required
            or type(permit['version']) is not int or permit['version'] != 1):
        raise Refused('maintenance_permit_invalid')
    if not isinstance(permit['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', permit['id']):
        raise Refused('maintenance_permit_invalid')
    if (type(now) not in (int, float) or not math.isfinite(now)
            or type(permit['created_at']) is not int or type(permit['expires_at']) is not int
            or not permit['created_at'] <= now < permit['expires_at']
            or not 0 < permit['expires_at'] - permit['created_at'] <= MAX_WINDOW):
        raise Refused('maintenance_permit_expired')
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in
            (permit['created_monotonic'], permit['expires_monotonic'], monotonic_now))
            or not permit['created_monotonic'] <= monotonic_now < permit['expires_monotonic']
            or not 0 < permit['expires_monotonic'] - permit['created_monotonic'] <= MAX_WINDOW):
        raise Refused('maintenance_permit_expired')
    if any(not isinstance(permit[k], str) or not HEX.fullmatch(permit[k]) for k in ('pvf_sha256', 'program_sha256', 'container_id', 'policy_sha256')):
        raise Refused('maintenance_permit_invalid')
    if (not isinstance(permit['image_digest'], str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', permit['image_digest'])
            or not isinstance(permit['boot_id'], str) or not re.fullmatch(r'[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', permit['boot_id'])
            or not isinstance(permit['container_started_at'], str) or not 1 <= len(permit['container_started_at']) <= 64
            or not isinstance(permit['reason'], str) or not 1 <= len(permit['reason'].strip()) <= 200):
        raise Refused('maintenance_permit_invalid')
    names = permit['components']
    if (not isinstance(names, list) or not 2 <= len(names) <= 64
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name) for name in names)
            or len(set(names)) != len(names) or 'mysql' not in names):
        raise Refused('maintenance_permit_invalid')
    return permit


def read_permit(root, owner=ROOT_UID, now=None, monotonic_now=None):
    return validate_permit(_read(root, 'permit.json', owner, 4096), time.time() if now is None else now, monotonic_now)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


class MaintenanceFence:
    def __init__(self, root, *, image_digest, pvf_sha256, program_sha256, owner=ROOT_UID, clock=None, boot=None, monotonic=None):
        self.root = Path(root)
        self.expected = {'image_digest': image_digest, 'pvf_sha256': pvf_sha256, 'program_sha256': program_sha256}
        self.owner, self.clock, self.boot = owner, clock or time.time, boot or boot_id
        self.monotonic = monotonic or time.monotonic

    def check(self, permit_id=None):
        now = self.clock()
        mono = self.monotonic()
        permit = read_permit(self.root, self.owner, now, mono)
        if permit_id is not None and permit['id'] != permit_id:
            raise Refused('maintenance_window_changed')
        if any(permit.get(k) != v for k, v in self.expected.items()) or permit['boot_id'] != self.boot():
            raise Refused('maintenance_version_changed')
        evidence = _read(self.root, 'evidence.json', self.owner, 16384)
        if not isinstance(evidence, dict) or evidence.get('permit_id') != permit['id'] or evidence.get('safe') is not True:
            raise Refused('maintenance_not_proven')
        at = evidence.get('collected_at')
        if (type(at) not in (int, float) or not math.isfinite(at)
                or not permit['created_at'] <= at <= now or now - at > MAX_AGE):
            raise Refused('maintenance_evidence_stale')
        collected_mono = evidence.get('collected_monotonic')
        if (type(collected_mono) not in (int, float) or not math.isfinite(collected_mono)
                or not permit['created_monotonic'] <= collected_mono <= mono or mono - collected_mono > MAX_AGE):
            raise Refused('maintenance_evidence_stale')
        if any(evidence.get(key) != permit[key] for key in BOUND_FIELDS):
            raise Refused('maintenance_evidence_mismatch')
        if any(evidence.get(key) is not True for key in ('all_writers_down', 'mysql_up', 'non_game_core_ok', 'no_unmanaged_processes')):
            raise Refused('maintenance_not_proven')
        for key, floor in (('mem_available_mib', 256), ('swap_free_mib', 1536)):
            value = evidence.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < floor:
                raise Refused('maintenance_resources_low')
        return {'id': permit['id'], 'expires_at': permit['expires_at'], 'reason': permit['reason'], 'collected_at': at}

    @contextmanager
    def hold(self):
        fd = open_lock(self.root, self.owner)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('maintenance_closing') from None
            if _identity(os.fstat(fd)) != _identity((self.root / 'fence.lock').lstat()):
                raise Refused('maintenance_lock_changed')
            lease = FenceLease(self, fd, self.check())
            try:
                yield lease
            finally:
                lease.active = False
        finally:
            os.close(fd)


class FenceLease:
    """Check this held lease immediately before committing; not a reusable token."""
    def __init__(self, fence, fd, state):
        self.fence, self.fd, self.state, self.active = fence, fd, state, True
        self.root_identity = _identity(fence.root.lstat())

    def check(self):
        if not self.active:
            raise Refused('maintenance_lease_released')
        directory(self.fence.root, self.fence.owner)
        st = (self.fence.root / 'fence.lock').lstat()
        _regular(st, self.fence.owner)
        if (_identity(st) != _identity(os.fstat(self.fd))
                or _identity(self.fence.root.lstat()) != self.root_identity):
            raise Refused('maintenance_lock_changed')
        return self.fence.check(self.state['id'])
