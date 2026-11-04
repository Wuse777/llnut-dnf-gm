"""Read-only, bounded view of monitor-owned telemetry; no shell or write APIs."""
from pathlib import Path
import json
import math
import sqlite3
import time
from . import __version__
from .catalog import snapshot

METRICS = ('cpu_percent', 'mem_available_mib', 'mem_total_mib', 'swap_free_mib',
           'swap_total_mib', 'disk_free_gib', 'disk_total_gib')


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None



def projection(value, fields):
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in fields if key in value and
            (value[key] is None or type(value[key]) is bool or number(value[key]) is not None or
             (isinstance(value[key], str) and len(value[key]) <= 256))}


def metadata_view(name, value):
    if name == 'protection':
        return projection(value, ('reason','recovery_result','stopped_at','recovered_at',
                                  'auto_recovery_pending','manual_restart_required'))
    if not isinstance(value, dict) or not isinstance(value.get('items'), list):
        return None
    fields = (('id','label','bytes','state','collected_at') if name == 'storage' else
              ('name','modified_at','protected','source_revision'))
    limit = 8 if name == 'storage' else 100
    result = projection(value, ('state','truncated','collected_at','note'))
    result['items'] = [item for row in value['items'][:limit] if (item := projection(row, fields)) is not None]
    return result

def read_telemetry(filename, window='24h', before=0):
    now = time.time()
    response = {'as_of': now, 'state': 'unavailable', 'fresh': False, 'updated_at': None,
                'window': window, 'points': [], 'events': [], 'next_before': None,
                'storage': None, 'releases': None, 'protection': None,
                'message': '尚无可读取的诊断历史；不代表服务器正常或磁盘为空。'}
    path = Path(filename)
    db = None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            return response
        # Do not use immutable=1: the monitor updates this database concurrently.
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA cache_size=-256')
        deadline = time.monotonic() + 0.5
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.execute('BEGIN')
        metadata = {}
        for row in db.execute('SELECT key,value FROM metadata WHERE key IN (\'updated_at\',\'protection\',\'storage\',\'releases\')'):
            if len(row['value']) > 65536:
                raise ValueError('Oversized metadata')
            metadata[row['key']] = json.loads(row['value'])
        updated = number(metadata.get('updated_at'))
        fresh = updated is not None and 0 <= now - updated <= 90
        response.update(state='ok' if fresh else 'stale', fresh=fresh, updated_at=updated,
                        message='历史窗口中的缺口不是0；分钟内取最差资源观测，曲线不代表逐秒值。' if fresh else '采集历史已过期；以下仅供回溯，不能作为当前健康状态。')
        minutes, bucket = (1440, 5) if window == '24h' else (10080, 30)
        start = int(now // 60) - minutes + 1
        rows = db.execute('''SELECT (minute / ?) * ? AS minute,COUNT(*) AS samples,
                    MAX(cpu_percent) AS cpu_percent, MIN(mem_available_mib) AS mem_available_mib,
                    MAX(mem_total_mib) AS mem_total_mib, MIN(swap_free_mib) AS swap_free_mib,
                    MAX(swap_total_mib) AS swap_total_mib, MIN(disk_free_gib) AS disk_free_gib,
                    MAX(disk_total_gib) AS disk_total_gib,
                    SUM(CASE WHEN core_ok=0 THEN 1 ELSE 0 END) AS failed_samples,
                    SUM(CASE WHEN core_ok IS NULL THEN 1 ELSE 0 END) AS unknown_samples
                    FROM samples WHERE minute>=? AND minute<=? GROUP BY (minute / ?) ORDER BY minute LIMIT 340''',
                          (bucket, bucket, start, int(now // 60), bucket)).fetchall()
        response['points'] = [dict(r) for r in rows]
        response['bucket_seconds'] = bucket * 60
        response['coverage_samples'] = sum(r['samples'] for r in rows)
        response['expected_samples'] = minutes
        events = db.execute('SELECT id,occurred_at,name,details FROM events WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT 51', (before, before)).fetchall()
        response['events'] = [{'id': r['id'], 'occurred_at': r['occurred_at'], 'name': r['name'],
                               'details': projection(json.loads(r['details']), ('reason','probe','error_type','timeout_seconds','elapsed_seconds','auto_recovery_pending','success','core_ok', *METRICS)) or {}} for r in events[:50]]
        response['next_before'] = events[49]['id'] if len(events) > 50 else None
        for name in ('storage', 'releases', 'protection'):
            response[name] = metadata_view(name, metadata.get(name))
        return response
    except (OSError, sqlite3.Error, ValueError, TypeError):
        # Never expose filesystem paths, SQL or exception text to the browser.
        return {**response, 'state': 'unavailable', 'fresh': False, 'points': [], 'events': [],
                'next_before': None, 'storage': None, 'releases': None, 'protection': None,
                'message': '诊断文件不可读、忙碌或格式异常；请查维护日志，不代表资源为0。'}
    finally:
        if db is not None:
            db.close()


def dashboard(settings, db, window='24h', before=0):
    live = snapshot(settings)
    result = read_telemetry(settings.telemetry_file, window, before)
    result['current'] = {'fresh': live.get('fresh', False), 'collected_at': live.get('collected_at'),
                         'core_ok': live.get('core_ok') if live.get('fresh') else None,
                         **{key: number(live.get(key)) if live.get('fresh') else None for key in METRICS}}
    result['application'] = {'version': __version__, 'schema_versions': [], 'schema_state': 'unknown'}
    try:
        with db.connect() as c, c.cursor() as q:
            q.execute('SELECT version,installed_at FROM dnf_gm.schema_versions ORDER BY version DESC LIMIT 32')
            result['application'].update(schema_versions=q.fetchall(), schema_state='ok')
    except Exception:
        pass  # Historical telemetry remains readable if a schema probe fails.
    return result
