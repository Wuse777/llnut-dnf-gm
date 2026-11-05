"""Bounded independent health observations and durable transition notifications.

No SQL, shell, player data, service control or automatic remediation. A 2xx
webhook reply means acceptance, not human delivery. Unknown never means recovery.
"""
from pathlib import Path
import json
import math
import os
import stat
import tempfile
import uuid

LABELS = {'collector': '状态采集失效', 'gm': 'GM接口不可用', 'core': '游戏或核心服务异常',
          'memory': '可用内存不足', 'swap': 'Swap剩余不足', 'disk': '磁盘剩余不足',
          'backup': '管理库备份证据异常', 'restore': '当前备份缺少有效恢复核验',
          'tasks': '运营任务需要处理', 'task_probe': '运营任务检查不可用或不完整'}
MAX_BYTES = 256 * 1024


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def recent(value, now, age=90):
    return numeric(value) and 0 <= now - value <= age


def read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            raise ValueError('Invalid state file')
        body = stream.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('Oversized state')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('Invalid state document')
        return value


def atomic(path, value, mode=0o600):
    path = Path(path)
    body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(body) > MAX_BYTES:
        raise ValueError('Oversized state')
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), mode)
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def observations(status, gm_ok, now, thresholds, backup=None, tasks=None):
    fresh = isinstance(status, dict) and recent(status.get('collected_at'), now)
    result = {key: {'bad': None, 'sample': None} for key in LABELS}
    result['collector'] = {'bad': not fresh or status.get('state') == 'unknown' or type(status.get('core_ok')) is not bool, 'sample': now}
    result['gm'] = {'bad': not gm_ok, 'sample': now}
    if backup is None:
        for key in ('backup','restore'):result[key]['disabled']=True
    if backup is not None:
        result['backup'] = {'bad': backup.get('state')!='ok' or (backup.get('backup') or {}).get('state')!='recent', 'sample': now}
        if backup.get('state')=='ok':
            result['restore'] = {'bad': (backup.get('restore') or {}).get('state')!='recent', 'sample': now}
    if tasks is None:
        for key in ('tasks','task_probe'):result[key]['disabled']=True
    else:
        from .task_probe import validate_summary
        try:
            task = validate_summary(tasks, now)
        except (ValueError, TypeError, KeyError):
            result['task_probe']={'bad':True,'sample':now}
        else:
            result['task_probe']={'bad':task['state']=='unknown' or task['truncated'],'sample':now}
            result['tasks']={'bad':True if task['state']=='attention' else False if task['state']=='clear' else None,
                             'sample':task['checked_at']}
    if not fresh:
        return result
    sample = status['collected_at']
    window = status.get('maintenance')
    maintenance = (isinstance(window, dict) and window.get('active') is True
                   and window.get('verified') is True and recent(window.get('collected_at'), now, 30)
                   and numeric(window.get('expires_at')) and window['expires_at'] > now)
    if status.get('state') not in ('unknown', 'resource_protection') and not maintenance:
        if type(status.get('core_ok')) is bool:
            result['core'] = {'bad': not status['core_ok'], 'sample': sample}
    for key, field in [('memory', 'mem_available_mib'), ('swap', 'swap_free_mib'), ('disk', 'disk_free_gib')]:
        if numeric(status.get(field)) and status[field] >= 0:
            result[key] = {'bad': status[field] < thresholds[key], 'sample': sample}
    return result


def new_state():
    return {'version': 1, 'updated_at': None, 'rules': {}, 'history': [],
            'notification': {'state': 'disabled', 'last_attempt': None, 'last_accepted': None,
                             'next_attempt': 0, 'failures': 0}}


def validate_event(event):
    if (not isinstance(event, dict) or event.get('key') not in LABELS
            or event.get('state') not in ('firing', 'resolved') or not numeric(event.get('occurred_at'))
            or not isinstance(event.get('id'), str) or len(event['id']) != 32
            or any(c not in '0123456789abcdef' for c in event['id'])):
        raise ValueError('Invalid alert event')


def validate_state(state):
    """Fail rather than resetting deduplication after corruption."""
    if state.get('version') != 1 or not isinstance(state.get('rules'), dict) or set(state['rules']) - LABELS.keys():
        raise ValueError('Invalid notification state')
    if not isinstance(state.get('history'), list) or len(state['history']) > 100:
        raise ValueError('Invalid notification history')
    n = state.get('notification')
    if not isinstance(n, dict) or n.get('state') not in ('disabled', 'pending', 'accepted', 'retrying'):
        raise ValueError('Invalid notification status')
    if type(n.get('failures')) is not int or not 0 <= n['failures'] <= 20 or not numeric(n.get('next_attempt')):
        raise ValueError('Invalid notification retry')
    if state.get('updated_at') is not None and not numeric(state['updated_at']):
        raise ValueError('Invalid observation time')
    for name in ('last_attempt', 'last_accepted'):
        if n.get(name) is not None and not numeric(n[name]):
            raise ValueError('Invalid delivery time')
    for r in state['rules'].values():
        if (not isinstance(r, dict) or type(r.get('active')) is not bool or type(r.get('count')) is not int
                or not 0 <= r['count'] <= 2 or (r.get('candidate') is not None and type(r['candidate']) is not bool)
                or r.get('observed', 'unknown') not in ('unknown','bad','healthy','disabled')):
            raise ValueError('Invalid alert rule')
        for field in ('since', 'sample', 'started_at', 'changed_at'):
            if r.get(field) is not None and not numeric(r[field]):
                raise ValueError('Invalid rule timestamp')
        if r.get('pending') is not None:
            validate_event(r['pending'])
    for event in state['history']:
        validate_event(event)
    return state


def observe(state, values, now):
    validate_state(state)
    previous = state.get('updated_at')
    if numeric(previous) and now < previous:
        raise ValueError('Clock moved backwards; retain last state for investigation')
    for key in LABELS:
        r = state['rules'].setdefault(key, dict(active=False, candidate=None, count=0, since=None,
                                                sample=None, started_at=None, changed_at=None, pending=None))
        if numeric(previous) and now - previous > 90:
            r.update(candidate=None, count=0, since=None)
        bad, sample = values[key]['bad'], values[key]['sample']
        r['observed'] = 'disabled' if values[key].get('disabled') is True else 'unknown' if bad is None else ('bad' if bad else 'healthy')
        if bad is None:
            r.update(candidate=None, count=0, since=None)
            continue
        if r['sample'] is not None and sample <= r['sample']:
            continue
        r['sample'] = sample
        if bad == r['active']:
            r.update(candidate=None, count=0, since=None)
            continue
        if r['candidate'] != bad:
            r.update(candidate=bad, count=1, since=now)
            continue
        r['count'] = min(2, r['count'] + 1)
        if now - r['since'] < 15:
            continue
        event = dict(id=uuid.uuid4().hex, key=key, state='firing' if bad else 'resolved', occurred_at=now)
        r.update(active=bad, candidate=None, count=0, since=None, changed_at=now, pending=event,
                 started_at=now if bad else r['started_at'])
        state['history'].append(event)
    state['history'] = state['history'][-100:]
    state['updated_at'] = now
    return state


def pending(state):
    # Coalesce unaccepted transitions to the current state, retaining full
    # transition history separately. Never deliver an obsolete outage later.
    return [dict(r['pending'], label=LABELS[key]) for key, r in state['rules'].items() if r.get('pending') and r.get('observed')!='disabled']


def delivery(state, now, enabled, send, persist):
    """Save intent before sending; uncertain retries preserve event IDs."""
    n = state['notification']
    events = pending(state)
    if not enabled:
        n['state'] = 'disabled'
        persist(state)
        return
    if not events:
        persist(state)
        return
    if now < n['next_attempt']:
        n['state'] = 'retrying'
        persist(state)
        return
    n.update(state='pending', last_attempt=now, next_attempt=now + 60)
    persist(state)
    try:
        accepted = send({'source': 'dnf-gm', 'schema': 1, 'events': events}) is True
    except Exception:
        accepted = False
    if accepted:
        ids = {e['id'] for e in events}
        for r in state['rules'].values():
            if r.get('pending') and r['pending']['id'] in ids:
                r['pending'] = None
        n.update(state='accepted', last_accepted=now, failures=0, next_attempt=0)
    else:
        failures = min(n['failures'] + 1, 20)
        n.update(state='retrying', failures=failures, next_attempt=now + min(3600, 60 * 2 ** min(failures - 1, 6)))
    persist(state)


def public_view(state, now):
    validate_state(state)
    return {'state': 'ok' if recent(state.get('updated_at'), now) else 'stale',
            'updated_at': state.get('updated_at'), 'as_of': now,
            'rules': [{'key': key, 'label': LABELS[key], 'active': r['active'],
                       'observed': r.get('observed', 'unknown'), 'pending_confirmation': r['count'] > 0,
                       'started_at': r['started_at'], 'changed_at': r['changed_at']} for key, r in state['rules'].items()],
            'history': [{**{k: e[k] for k in ('id', 'key', 'state', 'occurred_at')}, 'label': LABELS[e['key']]} for e in reversed(state['history'])],
            'notification': {k: state['notification'].get(k) for k in ('state', 'last_attempt', 'last_accepted', 'next_attempt', 'failures')},
            'pending_count': len(pending(state))}


def unavailable(now):
    return {'state': 'unavailable', 'updated_at': None, 'as_of': now, 'rules': [], 'history': [],
            'notification': None, 'pending_count': None}


def read_report(path, now):
    """Only public fields; re-evaluate age at request time, not worker time."""
    try:
        report = read_json(path)
        n = report['notification']
        if (not isinstance(report['rules'], list) or len(report['rules']) != len(LABELS)
                or not isinstance(report['history'], list) or len(report['history']) > 100
                or not numeric(report['updated_at']) or not isinstance(n, dict)
                or n.get('state') not in ('disabled', 'pending', 'accepted', 'retrying')
                or type(report['pending_count']) is not int or not 0 <= report['pending_count'] <= len(LABELS)
                or type(n.get('failures')) is not int or not 0 <= n['failures'] <= 20):
            raise ValueError('Invalid public report')
        for name in ('last_attempt', 'last_accepted', 'next_attempt'):
            if n.get(name) is not None and not numeric(n[name]):
                raise ValueError('Invalid report timestamp')
        rules, seen = [], set()
        for r in report['rules']:
            key = r['key']
            if (key not in LABELS or key in seen or type(r['active']) is not bool
                    or type(r['pending_confirmation']) is not bool
                    or r['observed'] not in ('unknown', 'bad', 'healthy', 'disabled')):
                raise ValueError('Invalid public rule')
            for name in ('started_at', 'changed_at'):
                if r[name] is not None and not numeric(r[name]):
                    raise ValueError('Invalid public rule time')
            seen.add(key)
            rules.append({k: r[k] for k in ('key','active','pending_confirmation','observed','started_at','changed_at')})
            rules[-1]['label'] = LABELS[key]
        history = []
        for event in report['history']:
            validate_event(event)
            history.append({k: event[k] for k in ('id','key','state','occurred_at')})
            history[-1]['label'] = LABELS[event['key']]
        from .observer_policy import public as policy_public
        return {'state': 'ok' if recent(report['updated_at'], now) else 'stale',
                'updated_at': report['updated_at'], 'as_of': now, 'rules': rules, 'history': history,
                'notification': {k: n.get(k) for k in ('state','last_attempt','last_accepted','next_attempt','failures')},
                'pending_count': report['pending_count'], 'observer_policy':policy_public(report.get('observer_policy'))}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return unavailable(now)
