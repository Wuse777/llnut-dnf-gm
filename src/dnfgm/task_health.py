"""Bounded, read-only operational evidence; never retries or acknowledges rewards."""
import threading
import time


class WorkerPulse:
    """Monotonic observations of the existing worker, not a second executor."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.values = {}

    def call(self, name, fn):
        with self.lock:
            row = self.values.setdefault(name, {'failures': 0, 'success': None})
            row['started'] = self.clock()
            row['active'] = True
        try:
            result = fn()
        except Exception:
            with self.lock:
                row['failures'] += 1
            raise
        else:
            with self.lock:
                row['success'] = self.clock()
                row['failures'] = 0
            return result
        finally:
            with self.lock:
                row['active'] = False

    def snapshot(self, name, enabled, alive):
        with self.lock:
            row = dict(self.values.get(name, {}))
        now = self.clock()
        if not enabled:
            state = 'disabled'
        elif not alive:
            state = 'stopped'
        elif row.get('active') and now - row['started'] >= 120:
            state = 'stalled'
        elif row.get('failures', 0):
            state = 'failing'
        elif row.get('success') is None:
            state = 'observing'
        elif not row.get('active') and now - row['success'] >= 120:
            state = 'stalled'
        else:
            state = 'responding'
        return {'state': state, 'failures': row.get('failures', 0)}


class TaskHealth:
    def __init__(self, db, settings, pulse, alive=lambda: False, clock=time.monotonic, wall=time.time):
        self.db, self.settings, self.pulse, self.alive = db, settings, pulse, alive
        self.clock, self.wall = clock, wall
        self.lock = threading.Lock()
        self.head = None
        self.since = self.last = None

    def observe_head(self, signature):
        now = self.clock()
        if signature is None:
            self.head = self.since = self.last = None
            return 'idle'
        if signature != self.head or self.last is None or now - self.last > 90:
            self.head, self.since = signature, now
        self.last = now
        return 'stalled' if now - self.since >= 120 else 'observing'

    def read(self):
        # No parallel snapshot queries from multiple tabs; no cached all-clear.
        if not self.lock.acquire(blocking=False):
            return {'state': 'unknown', 'checked_at': int(self.wall()), 'reason': 'busy', 'issues': []}
        try:
            return self._read()
        except Exception:
            self.head = self.since = self.last = None
            return {'state': 'unknown', 'checked_at': int(self.wall()), 'reason': 'query_failed', 'issues': []}
        finally:
            self.lock.release()

    def _read(self):
        now, began = int(self.wall()), self.clock()
        issues, truncated = [], False
        workers = {
            'rewards': self.pulse.snapshot('rewards', self.settings.batch_worker_enabled, self.alive()),
            'schedules': self.pulse.snapshot('schedules', self.settings.schedule_worker_enabled, self.alive()),
        }
        def query(q, sql, args=()):
            if self.clock() - began > .75:
                raise TimeoutError('health budget')
            q.execute('SELECT /*+ MAX_EXECUTION_TIME(150) */ ' + sql, args)
            return q.fetchall()
        def bounded(q, sql, args=()):
            nonlocal truncated
            rows = query(q, sql + ' LIMIT 51', args)
            truncated |= len(rows) > 50
            return rows[:50]
        def issue(kind, identifier, code, ordinal=None):
            item = {'kind': kind, 'id': identifier, 'code': code}
            if ordinal is not None: item['ordinal'] = ordinal
            issues.append(item)
        with self.db.connect() as c, c.cursor() as q:
            # Read only the management state. No player names, payloads or reward data.
            q.execute('SET TRANSACTION READ ONLY')
            for status in ('uncertain', 'executing', 'failed'):
                # Bound before filtering cancelled jobs. Truncation explicitly means
                # incomplete coverage, even if all 50 candidates were acknowledged.
                rows = bounded(q, "t.job_id,t.ordinal,t.last_attempt,j.status AS job_status FROM dnf_gm.reward_targets t JOIN dnf_gm.reward_jobs j ON j.id=t.job_id WHERE t.status=%s ORDER BY t.job_id,t.ordinal", (status,))
                for row in rows:
                    if status == 'failed' and row['job_status'] == 'cancelled': continue
                    if status == 'executing' and row['last_attempt'] is not None and now - row['last_attempt'] < 120: continue
                    issue('reward', row['job_id'], status, row['ordinal'])
            for status in ('needs_attention', 'paused'):
                rows = bounded(q, "id,last_error FROM dnf_gm.schedules WHERE status=%s ORDER BY next_due,id", (status,))
                for row in rows:
                    if status == 'needs_attention' or row['last_error']:
                        issue('schedule', row['id'], 'schedule_error')
            rows = bounded(q, "id FROM dnf_gm.schedules WHERE status='active' AND next_due<=%s ORDER BY next_due,id", (now-120,))
            for row in rows: issue('schedule', row['id'], 'overdue')
            for status in ('awaiting', 'running'):
                rows = bounded(q, "schedule_id,id FROM dnf_gm.schedule_runs WHERE status=%s AND checked_at<=%s ORDER BY checked_at,id", (status, now-120))
                for row in rows: issue('schedule', row['schedule_id'], 'unreconciled')
            head = query(q, "id FROM dnf_gm.reward_jobs WHERE status='running' ORDER BY created_at,id LIMIT 1")
            signature = None
            if head:
                jid = head[0]['id']
                target = query(q, "ordinal FROM dnf_gm.reward_targets WHERE job_id=%s AND status='pending' ORDER BY ordinal LIMIT 1", (jid,))
                signature = (jid, target[0]['ordinal'] if target else None)
            progress = self.observe_head(signature)
            if head:
                if progress == 'stalled': issue('reward', jid, 'no_progress')
                if workers['rewards']['state'] in ('disabled','stopped','failing','stalled'):
                    issue('reward', jid, 'worker_' + workers['rewards']['state'])
            active = query(q, "id FROM dnf_gm.schedules WHERE status='active' ORDER BY next_due,id LIMIT 1")
            outstanding = query(q, "schedule_id FROM dnf_gm.schedule_runs WHERE status IN ('awaiting','running') ORDER BY status,checked_at,id LIMIT 1")
            schedule_id = active[0]['id'] if active else outstanding[0]['schedule_id'] if outstanding else None
            if schedule_id and workers['schedules']['state'] in ('disabled','stopped','failing','stalled'):
                issue('schedule', schedule_id, 'worker_' + workers['schedules']['state'])
            c.rollback()
        return {'state': 'attention' if issues else 'unknown' if truncated else 'observing' if head or (schedule_id and workers['schedules']['state']=='observing') else 'clear',
                'checked_at': now, 'issues': issues, 'truncated': truncated, 'workers': workers,
                'progress': progress, 'head_job_id': head[0]['id'] if head else None,
                'note': '管理任务状态，不代表游戏内效果；无自动重发。停滞判断需要连续观察120秒，超过90秒观察间隔重新计时。'}
