"""Monitor-owned bounded diagnostic history; never accepts web commands or paths."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import json
import math
import os
import re
import sqlite3
import stat
import subprocess
import time

METRICS = ('cpu_percent', 'mem_available_mib', 'mem_total_mib', 'swap_free_mib',
           'swap_total_mib', 'disk_free_gib', 'disk_total_gib')
EVENTS = {'probe_timeout', 'probe_slow', 'protection_stop', 'auto_recovery',
          'auto_recovery_cancelled', 'collection_failed', 'collection_recovered', 'monitor_failed'}
FIELDS = {'reason', 'probe', 'error_type', 'timeout_seconds', 'elapsed_seconds',
          'auto_recovery_pending', 'success', 'core_ok', *METRICS}
SAFE_NAME = re.compile(r'[a-zA-Z0-9_.-]{1,96}\Z')


def numeric(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def small_file(path, limit=1024):
    if path.is_symlink():
        raise ValueError('Symlink metadata')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized metadata')
    return raw.decode().strip()


def inventory(root, current, previous):
    """Metadata only, no recursive scan and no deletion. Bound filesystem entries."""
    root = Path(root)
    protected = {Path(current).resolve(), Path(previous).resolve()}
    rows, truncated = [], False
    if not root.exists():
        return {'state': 'missing', 'items': [], 'truncated': False}
    if root.is_symlink():
        return {'state': 'unavailable', 'items': [], 'truncated': False}
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= 100:
                truncated = True
                break
            if not SAFE_NAME.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path)
            revision = None
            try:
                text = small_file(path / 'SOURCE_REVISION')
                if SAFE_NAME.fullmatch(text):
                    revision = text
            except (OSError, ValueError, UnicodeError):
                pass
            rows.append({'name': entry.name, 'modified_at': entry.stat(follow_symlinks=False).st_mtime,
                         'protected': path.resolve() in protected, 'source_revision': revision})
    return {'state': 'ok', 'items': sorted(rows, key=lambda r: r['modified_at'], reverse=True),
            'truncated': truncated, 'note': '只读发布目录；受保护项为current/previous，其他项不是自动清理许可。目录时间不是部署时间。'}


def scan_storage(paths, *, runner=subprocess.run):
    """One fixed local du per root; no symlink following or shell; errors sanitized."""
    rows = []
    for item in paths:
        row = {'id': item['id'], 'label': item['label'], 'bytes': None, 'state': 'unavailable'}
        path = Path(item['path'])
        try:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                row['state'] = 'symlink_refused'
            elif not stat.S_ISDIR(mode):
                row['state'] = 'unavailable'
            else:
                response = runner(['du', '-sx', '-B1', '--', str(path)], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=5, check=False)
                if response.returncode == 0:
                    # GNU du prints one summary; reject partial or unexpected results.
                    text = response.stdout.decode()
                    if len(text) < 4096 and len(text.splitlines()) == 1:
                        row['bytes'] = int(text.split('\t', 1)[0])
                        if row['bytes'] < 0:
                            raise ValueError('Negative usage')
                        row['state'] = 'ok'
                else:
                    row['state'] = 'unavailable'
        except FileNotFoundError:
            row['state'] = 'missing'
        except subprocess.TimeoutExpired:
            row['state'] = 'timeout'
        except (OSError, ValueError, UnicodeError):
            row['state'] = 'unavailable'
        row['collected_at'] = time.time()
        rows.append(row)
    return {'items': rows, 'collected_at': time.time(),
            'note': '目录实际分配空间；不跨文件系统。目录可能嵌套，Docker卷可能与游戏数据重叠，不可相加当磁盘总量。超时/不可读不是0字节。'}


class Recorder:
    def __init__(self, path, *, storage_paths=(), releases='/opt/dnf-gm/releases',
                 current='/opt/dnf-gm/current', previous='/opt/dnf-gm/previous',
                 protection='/var/lib/dnf-gm/protection.json'):
        self.path = Path(path)
        self.storage_paths = storage_paths
        self.releases, self.current, self.previous = releases, current, previous
        self.protection = Path(protection)
        self.last_minute = None
        self.next_storage = 0
        self.future = None
        self.executor = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError('Telemetry path is a symlink')
        with self.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS samples (
                minute INTEGER PRIMARY KEY, sampled_at REAL NOT NULL,
                cpu_percent REAL,mem_available_mib REAL,mem_total_mib REAL,
                swap_free_mib REAL,swap_total_mib REAL,disk_free_gib REAL,disk_total_gib REAL,
                state TEXT NOT NULL,core_ok INTEGER);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,occurred_at REAL,name TEXT,details TEXT);
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);''')
        os.chmod(self.path, 0o644)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=0.2)
        db.execute('PRAGMA cache_size=-256')
        db.execute('PRAGMA busy_timeout=200')
        try:
            with db:
                yield db
        finally:
            db.close()

    def meta(self, db, key, value):
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def record_event(self, name, fields):
        if name not in EVENTS:
            return
        safe = {k: v for k, v in fields.items() if k in FIELDS and
                (type(v) is bool or numeric(v) is not None or (isinstance(v, str) and SAFE_NAME.fullmatch(v)))}
        with self.connection() as db:
            db.execute('INSERT INTO events(occurred_at,name,details) VALUES(?,?,?)', (time.time(), name, json.dumps(safe)))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 256)')

    def observe(self, status):
        now = time.time()
        minute = int(now // 60)
        with self.connection() as db:
            # Every fresh sample replaces its minute; retain worst observed resource
            # values and failed/unknown health instead of masking short incidents.
            core = int(status['core_ok']) if type(status.get('core_ok')) is bool else None
            state = status.get('state', 'ok' if core == 1 else 'unknown')
            if state not in ('ok', 'unknown', 'resource_protection'):
                state = 'unknown'
            values = [numeric(status.get(k)) for k in METRICS]
            old = db.execute('SELECT cpu_percent,mem_available_mib,mem_total_mib,swap_free_mib,swap_total_mib,disk_free_gib,disk_total_gib,state,core_ok FROM samples WHERE minute=?', (minute,)).fetchone()
            if old:
                for i in (0, 1, 3, 5):
                    if old[i] is not None and values[i] is not None:
                        values[i] = (max if i == 0 else min)(old[i], values[i])
                core = None if core is None or old[8] is None else min(core, old[8])
                if old[7] != 'ok':
                    state = old[7]
            db.execute('INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)', (minute, now, *values, state, core))
            db.execute('DELETE FROM samples WHERE minute<? OR minute>?', (minute - 10079, minute))
            self.meta(db, 'updated_at', now)
            try:
                p = json.loads(small_file(self.protection, 4096))
                safe = {k: p[k] for k in ('stopped_at', 'recovered_at') if numeric(p.get(k)) is not None}
                safe.update({k: p[k] for k in ('manual_restart_required', 'auto_recovery_pending') if type(p.get(k)) is bool})
                safe.update({k: p[k] for k in ('reason', 'recovery_result') if isinstance(p.get(k), str) and SAFE_NAME.fullmatch(p[k])})
                self.meta(db, 'protection', safe)
            except (OSError, ValueError, TypeError, UnicodeError):
                self.meta(db, 'protection', None)
            if self.last_minute != minute:
                try:
                    releases = inventory(self.releases, self.current, self.previous)
                except OSError:
                    releases = {'state': 'unavailable', 'items': [], 'truncated': False}
                self.meta(db, 'releases', releases)
                self.last_minute = minute
            if self.future is not None and self.future.done():
                try:
                    storage = self.future.result()
                except Exception:
                    storage = {'state': 'unavailable', 'items': [], 'collected_at': now, 'note': '固定目录扫描失败，未取得空间数据；不代表目录为空。'}
                self.meta(db, 'storage', storage)
                self.future = None
            if self.storage_paths and self.future is None and time.monotonic() >= self.next_storage:
                if self.executor is None:
                    self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gm-storage')
                self.future = self.executor.submit(scan_storage, self.storage_paths)
                self.next_storage = time.monotonic() + 3600

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=True, cancel_futures=True)
