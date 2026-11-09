"""Durable Shanghai-time schedules, with no catch-up rewards or native replay.

An occurrence and its frozen child are created in ONE transaction. Reward jobs
are queued atomically. Native sends happen only after that commit is confirmed,
using NativeOperations' own durable at-most-once claim. A lost preparation commit
is reconciled read-only (unclaimed native previews are cancelled, never retried).
"""
import copy
import hashlib
import hmac
import json
import logging
import time
import uuid

from .write_gate import WriteGateClosed
from fastapi import HTTPException
from pymysql.err import IntegrityError, OperationalError

from .models import SchedulePreview
from .reward_jobs import NoRewardTargets
from .service import dump, one

INTERVALS = {'once': 0, 'daily': 86400, 'weekly': 604800}
LATE_WINDOW = 300
RECOVERY_GRACE = 60


def next_due(definition, due):
    interval = INTERVALS[definition['recurrence']]
    candidate = due + interval if interval else None
    end = definition.get('end_at')
    return candidate if candidate is not None and (end is None or candidate <= end) else None


def missed(definition, due, now):
    """Aggregate expired occurrences in constant time; never iterate downtime."""
    interval = INTERVALS[definition['recurrence']]
    bound = now - LATE_WINDOW - 1
    if definition.get('end_at') is not None:
        bound = min(bound, definition['end_at'])
    count = (bound - due) // interval + 1 if interval else 1
    last = due + (count - 1) * interval
    return count, last, next_due(definition, last)


class Schedules:
    def __init__(self, db, settings, jobs, native, clock=None):
        self.db, self.settings, self.jobs, self.native = db, settings, jobs, native
        self.clock = clock or time.time

    @staticmethod
    def engines(q):
        q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('schedules','schedule_runs','audit')")
        rows = q.fetchall()
        if len(rows) != 3 or any(r['ENGINE'] != 'InnoDB' for r in rows):
            raise HTTPException(409, '定时计划或审计事务表未就绪')

    def principal(self, schedule_id):
        return hmac.new(self.settings.secret.encode(), ('schedule:' + schedule_id).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def fingerprint(request, preview):
        return hashlib.sha256(dump({'request': request, 'preview': preview}).encode()).hexdigest()

    @staticmethod
    def row(q, sid, lock=False):
        row = one(q, 'SELECT * FROM dnf_gm.schedules WHERE id=%s' + (' FOR UPDATE' if lock else ''), (sid,))
        if not row:
            raise HTTPException(404, '定时计划不存在')
        return row

    @staticmethod
    def audit(q, sid, action, result, scheduler=False):
        q.execute('INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,%s,%s,%s,%s,%s)',
                  ('schedule-' + uuid.uuid4().hex, 'scheduler' if scheduler else 'owner', 'schedule-' + action,
                   '定时运营', dump({'schedule_id': sid}), dump(result)))

    def binding(self, q, data):
        result = {'image_digest': self.settings.image_digest, 'pvf_sha256': self.settings.pvf_sha256}
        if data['kind'] == 'reward':
            self.jobs.service.campaigns.bind_job(q,data['reward_job'])
            reward = data['reward_job']['reward']
            reward['action'] = 'reward'
            result['reward'] = self.jobs.service.reward_snapshot(q, reward)
        else:
            self.native.ready('native-notice', None)
        return result

    def check(self, q, row):
        if not self.settings.schedule_worker_enabled:
            raise HTTPException(409, '定时执行器未启用')
        request, preview = json.loads(row['request_json']), json.loads(row['preview_json'])
        if self.fingerprint(request, preview) != row['fingerprint']:
            raise HTTPException(409, '计划定义校验失败，禁止执行')
        if self.binding(q, copy.deepcopy(request)) != preview['binding']:
            raise HTTPException(409, '奖励、物品策略、PVF或镜像已变化；请重新建立计划')
        if request['kind'] == 'reward':
            if not self.settings.batch_worker_enabled or 'batch-reward' not in self.settings.writes:
                raise HTTPException(409, '奖励执行器或批量奖励未启用')
            if not self.jobs.service.write_enabled(request['reward_job']['reward'], preview['binding']['reward']):
                raise HTTPException(403, '该奖励写入功能未启用')
        self.engines(q)
        return request

    def preview(self, session_hash, data):
        data = SchedulePreview(**data).model_dump()
        now = int(self.clock())
        if data['first_due'] <= now:
            raise HTTPException(422, '首次执行时间必须在未来（北京时间）')
        sid = uuid.uuid4().hex
        with self.db.connect() as c, c.cursor() as q:
            self.engines(q)
            binding = self.binding(q, data)
            estimate = None
            account_selection = None
            if data['kind'] == 'reward':
                selected, _, account_selection = self.jobs.resolve_accounts(q,data['reward_job']['targets'])
                data['reward_job']['targets']=selected
                clause, args, _ = self.jobs.selector(selected)
                estimate = one(q, 'SELECT COUNT(*) target_count,COUNT(DISTINCT c.m_id) account_count '
                               'FROM taiwan_cain.charac_info c JOIN d_taiwan.accounts a ON a.UID=c.m_id '
                               'LEFT JOIN taiwan_login.login_account_3 l ON l.m_id=c.m_id WHERE ' + clause, args)
            preview = {'binding': binding, 'estimate': estimate, 'account_selection':account_selection, 'timezone': 'Asia/Shanghai',
                       'late_window_seconds': LATE_WINDOW,
                       'note': '当前人数仅为估算；到期实际触发时冻结名单。超过5分钟的错过期次记为跳过，不补发。取消计划不撤销已创建的子任务。'}
            q.execute("INSERT INTO dnf_gm.schedules(id,session_hash,fingerprint,title,kind,request_json,preview_json,status,next_due,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,'preview',%s,%s,%s)",
                      (sid, session_hash, self.fingerprint(data, preview), data['title'], data['kind'], dump(data), dump(preview), data['first_due'], now, now + 300))
            self.audit(q, sid, 'preview', {'kind': data['kind'], 'first_due': data['first_due']})
            if data['kind']=='reward' and data['reward_job'].get('campaign_id'):
                self.jobs.service.campaigns.link(q,data['reward_job']['campaign_id'],'schedule',sid)
            c.commit()
        return self.detail(sid)

    @staticmethod
    def view(row):
        result = {k: v for k, v in row.items() if k not in ('session_hash', 'idempotency_key', 'request_json', 'preview_json')}
        result['request'] = json.loads(row['request_json'])
        result['preview'] = json.loads(row['preview_json'])
        return result

    def detail(self, sid):
        with self.db.connect() as c, c.cursor() as q:
            result = self.view(self.row(q, sid))
            result['worker_enabled'] = self.settings.schedule_worker_enabled
            return result

    def list(self, page=1):
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT id,title,kind,status,next_due,created_at,last_error FROM dnf_gm.schedules ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET %s', ((page - 1) * 50,))
            return {'items': q.fetchall(), 'page': page, 'worker_enabled': self.settings.schedule_worker_enabled}

    def runs(self, sid, page=1):
        with self.db.connect() as c, c.cursor() as q:
            self.row(q, sid)
            q.execute('SELECT * FROM dnf_gm.schedule_runs WHERE schedule_id=%s ORDER BY due_at DESC,id DESC LIMIT 50 OFFSET %s', (sid, (page - 1) * 50))
            return {'items': q.fetchall(), 'page': page}

    def activate(self, session_hash, sid, data):
        committing = False
        try:
            with self.db.connect() as c, c.cursor() as q:
                row = self.row(q, sid, True)
                if row['session_hash'] != session_hash:
                    raise HTTPException(404, '预览不存在于当前会话')
                if row['fingerprint'] != data['fingerprint']:
                    raise HTTPException(409, '预览内容不一致')
                other = one(q, 'SELECT id FROM dnf_gm.schedules WHERE idempotency_key=%s', (data['idempotency_key'],))
                if other and other['id'] != sid:
                    raise HTTPException(409, '幂等键已用于其他计划')
                if row['idempotency_key']:
                    if row['idempotency_key'] != data['idempotency_key']:
                        raise HTTPException(409, '计划已用其他幂等键确认')
                else:
                    now = int(self.clock())
                    if row['status'] != 'preview' or row['expires_at'] < now or row['next_due'] <= now:
                        raise HTTPException(409, '预览过期或首次时间已到，请重新预览')
                    request = self.check(q, row)
                    if request['recurrence'] != 'once' and not data['acknowledge_recurring']:
                        raise HTTPException(422, '请明确确认周期性执行')
                    expected = '全服公告' if request['kind'] == 'notice' else '全服发放'
                    job = request['reward_job']
                    if (request['kind'] == 'notice' or job['targets']['mode'] == 'all') and data['all_server_confirmation'] != expected:
                        raise HTTPException(422, '请输入“' + expected + '”确认范围')
                    if job and job['account_reward_mode'] == 'per_character' and job['reward']['currency_rewards'] and not data['acknowledge_repeat']:
                        raise HTTPException(422, '请确认同一账号按角色重复获得货币')
                    q.execute("UPDATE dnf_gm.schedules SET status='active',idempotency_key=%s,activated_at=%s WHERE id=%s", (data['idempotency_key'], now, sid))
                    self.audit(q, sid, 'activate', {'first_due': row['next_due'], 'recurrence': request['recurrence']})
                    committing = True
                    c.commit()
        except IntegrityError as error:
            if error.args[0] == 1062:
                raise HTTPException(409, '幂等键已用于其他计划') from None
            raise
        except Exception:
            if committing:
                raise HTTPException(503, '计划激活结果待确认；请查询原计划，不要另建或重复激活') from None
            raise
        return self.detail(sid)

    def control(self, sid, action, acknowledge_attention=False):
        with self.db.connect() as c, c.cursor() as q:
            row = self.row(q, sid, True)
            self.engines(q)
            desired = {'pause': 'paused', 'resume': 'active', 'cancel': 'cancelled'}[action]
            if row['status'] == desired:
                return self.view(row)
            if row['status'] in ('cancelled', 'completed'):
                raise HTTPException(409, '终态计划不可重新执行；需要新计划时请复制并预览')
            if action == 'resume':
                if row['status'] not in ('paused', 'needs_attention') or row['next_due'] is None:
                    raise HTTPException(409, '没有可继续的后续期次；请查看原执行记录')
                if row['last_error'] and not acknowledge_attention:
                    raise HTTPException(422, '请确认已核对异常期次；继续只影响后续期次，不会补发')
                self.check(q, row)
            elif action == 'pause' and row['status'] not in ('active', 'needs_attention'):
                raise HTTPException(409, '当前计划不能暂停')
            q.execute('UPDATE dnf_gm.schedules SET status=%s,last_error=%s WHERE id=%s', (desired, '' if desired == 'active' else row['last_error'], sid))
            self.audit(q, sid, action, {'previous': row['status'], 'next_due': row['next_due'], 'children_unchanged': True})
            c.commit()
        return self.detail(sid)

    def insert_run(self, q, row, now, status, reference=None, skipped_count=0, last_due=None, message=''):
        rid = hashlib.sha256((row['id'] + ':' + str(row['next_due'])).encode()).hexdigest()[:32]
        q.execute('INSERT INTO dnf_gm.schedule_runs(id,schedule_id,due_at,started_at,checked_at,status,reference_kind,reference_id,skipped_count,last_due_at,error_message,finished_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (rid, row['id'], row['next_due'], now, now, status, row['kind'] if reference else None, reference, skipped_count, last_due, message, now if status in ('skipped','needs_attention') else None))
        return rid

    def finish_run(self, rid, status, message=''):
        with self.db.connect() as c, c.cursor() as q:
            # Always lock schedule before run; controls and preparation use this order.
            found = one(q, 'SELECT schedule_id FROM dnf_gm.schedule_runs WHERE id=%s', (rid,))
            if not found:
                return
            row = self.row(q, found['schedule_id'], True)
            run = one(q, 'SELECT * FROM dnf_gm.schedule_runs WHERE id=%s FOR UPDATE', (rid,))
            if run['status'] not in ('awaiting', 'running'):
                return
            q.execute('UPDATE dnf_gm.schedule_runs SET status=%s,checked_at=%s,finished_at=%s,error_message=%s WHERE id=%s',
                      (status, int(self.clock()), int(self.clock()), message, rid))
            if row['status'] == 'active':
                state = 'needs_attention' if status == 'needs_attention' else ('completed' if row['next_due'] is None else 'active')
                q.execute('UPDATE dnf_gm.schedules SET status=%s,last_error=%s WHERE id=%s', (state, message if status == 'needs_attention' else '', row['id']))
            elif row['status'] == 'paused' and status == 'needs_attention':
                q.execute('UPDATE dnf_gm.schedules SET last_error=%s WHERE id=%s', (message, row['id']))
            self.audit(q, row['id'], 'result', {'run_id': rid, 'status': status, 'reference_id': run['reference_id'], 'message': message}, True)
            c.commit()

    def reconcile_one(self, now):
        with self.db.connect() as c, c.cursor() as q:
            q.execute("SELECT * FROM dnf_gm.schedule_runs WHERE status IN ('awaiting','running') AND checked_at<=%s ORDER BY checked_at,id LIMIT 1", (now - 5,))
            run = q.fetchone()
            if not run:
                return False
            # Scheduling this next read is not a business write or a send claim.
            q.execute('UPDATE dnf_gm.schedule_runs SET checked_at=%s WHERE id=%s', (now, run['id']))
            c.commit()
        if run['reference_kind'] == 'reward':
            child = self.jobs.detail(run['reference_id'])
            if child['status'] == 'finished':
                self.finish_run(run['id'], 'finished')
            elif child['status'] in ('paused', 'cancelled', 'needs_attention'):
                self.finish_run(run['id'], 'needs_attention', '奖励子任务已暂停或异常；请处理原任务，不要重建整个期次')
        else:
            child = self.native.detail(run['reference_id'])
            if child['status'] in ('preview', 'dispatching') and now - run['started_at'] < RECOVERY_GRACE:
                return True
            if child['status'] == 'preview':
                # The previous sender may still be alive. Cancellation locks the
                # same operation row as confirm; only one may win. Never resend.
                try:
                    self.native.cancel('', run['reference_id'], actor='scheduler')
                except HTTPException as error:
                    if error.status_code != 409:
                        raise
                child = self.native.detail(run['reference_id'])
            self.finish_run(run['id'], 'sent' if child['status'] == 'sent' else 'needs_attention',
                            '指令已发送，游戏效果未知' if child['status'] == 'sent' else '公告结果需要核对；不会自动重发原指令')
        return True

    def step(self):
        if not self.settings.schedule_worker_enabled:
            return False
        now = int(self.clock())
        reconciled = self.reconcile_one(now)
        try:
            with self.jobs.service.write_gate.writer() as lease:
                return self._dispatch_due(now,reconciled,lease)
        except WriteGateClosed:
            return reconciled

    def _dispatch_due(self,now,reconciled,lease):
        dispatch = None
        committing = False
        try:
            with self.db.connect() as c, c.cursor() as q:
                lease.protect_transaction(q)
                self.engines(q)
                candidate = one(q, "SELECT id FROM dnf_gm.schedules WHERE status='active' AND next_due<=%s ORDER BY next_due,id LIMIT 1", (now,))
                if not candidate:
                    return reconciled
                # Lock by PK rather than locking the due-time index gap. A second
                # scanner must recheck the CURRENT row after acquiring the lock.
                row = self.row(q, candidate['id'], True)
                if row['status'] != 'active' or row['next_due'] is None or row['next_due'] > now:
                    return reconciled
                data = json.loads(row['request_json'])
                # Advance every occurrence, even on failure. Never replay an old due time.
                following = next_due(data, row['next_due'])
                if now - row['next_due'] > LATE_WINDOW:
                    count, last, following = missed(data, row['next_due'], now)
                    rid = self.insert_run(q, row, now, 'skipped', skipped_count=count, last_due=last, message='错过超过5分钟的期次；未发放也未广播')
                    pending = one(q, "SELECT id FROM dnf_gm.schedule_runs WHERE schedule_id=%s AND status IN ('awaiting','running') LIMIT 1", (row['id'],))
                    state = 'active' if following is not None or pending else 'completed'
                    q.execute('UPDATE dnf_gm.schedules SET next_due=%s,status=%s WHERE id=%s', (following, state, row['id']))
                else:
                    # Savepoint rolls back any partially created child, retaining
                    # the original schedule lock for a durable failure record.
                    q.execute('SAVEPOINT schedule_child')
                    try:
                        data = self.check(q, row)
                        outstanding = one(q, "SELECT id FROM dnf_gm.schedule_runs WHERE schedule_id=%s AND status IN ('awaiting','running') LIMIT 1", (row['id'],))
                        if not outstanding:
                            outstanding = one(q, "SELECT r.id FROM dnf_gm.schedule_runs r JOIN dnf_gm.reward_jobs j ON j.id=r.reference_id WHERE r.schedule_id=%s AND r.reference_kind='reward' AND j.status NOT IN ('finished','cancelled') LIMIT 1", (row['id'],))
                        if outstanding:
                            raise HTTPException(409, '上一期子任务尚未结束，暂停新一期避免叠加')
                        child_id = uuid.uuid4().hex
                        principal = self.principal(row['id'])
                        if data['kind'] == 'reward':
                            job = self.jobs.create_in_transaction(q, principal, {**data['reward_job'], 'schedule_id': row['id']}, child_id, now)
                            frozen = json.loads(job['preview_json'])
                            authorized = json.loads(row['preview_json'])['binding']['reward']
                            if {k: frozen.get(k) for k in authorized} != authorized:
                                raise HTTPException(409, '冻结名单期间物品索引发生变化；本期没有创建奖励任务')
                            if json.loads(job['request_json'])['reward'] != data['reward_job']['reward']:
                                raise HTTPException(409, '冻结名单期间奖励定义发生变化；本期没有创建奖励任务')
                            self.jobs.check_start(q, job)
                            q.execute("UPDATE dnf_gm.reward_jobs SET status='running',idempotency_key=%s,confirmed_at=%s WHERE id=%s", ('schedule-' + child_id, now, child_id))
                            self.jobs.audit(q, job, 'scheduled-start', {'schedule_id': row['id'], 'due_at': row['next_due']}, actor='scheduler')
                            status = 'running'
                        else:
                            self.native.create_in_transaction(q, principal, data['notice'], child_id, now)
                            status = 'awaiting'
                        rid = self.insert_run(q, row, now, status, child_id)
                        q.execute('UPDATE dnf_gm.schedules SET next_due=%s,last_error=\'\' WHERE id=%s', (following, row['id']))
                        if data['kind'] == 'notice':
                            dispatch = (rid, principal, child_id)
                    except Exception as error:
                        q.execute('ROLLBACK TO SAVEPOINT schedule_child')
                        empty_dynamic = isinstance(error, NoRewardTargets) and data['reward_job']['targets']['mode'] != 'selected'
                        if empty_dynamic:
                            message = '到期没有符合条件的角色；本期未发放，后续期次继续'
                            rid = self.insert_run(q, row, now, 'skipped', skipped_count=1, last_due=row['next_due'], message=message)
                            q.execute('UPDATE dnf_gm.schedules SET next_due=%s,status=%s WHERE id=%s', (following, 'active' if following is not None else 'completed', row['id']))
                        else:
                            message = str(error.detail)[:200] if isinstance(error, HTTPException) else '执行准备失败；没有创建奖励或公告子任务（' + type(error).__name__ + '）'
                            rid = self.insert_run(q, row, now, 'needs_attention', message=message)
                            q.execute("UPDATE dnf_gm.schedules SET next_due=%s,status='needs_attention',last_error=%s WHERE id=%s", (following, message, row['id']))
                        dispatch = None
                self.audit(q, row['id'], 'trigger', {'run_id': rid, 'due_at': row['next_due'], 'triggered_at': now}, True)
                lease.check()
                committing = True
                c.commit()
        except Exception as error:
            if not committing and isinstance(error, OperationalError) and error.args[0] in (1205, 1213):
                # No claim was committed and no network call made. Closing the
                # connection rolls back; a later scan may select the due row.
                return reconciled
            if committing:
                # No native send if the preparation transaction outcome is unknown.
                logging.getLogger('dnfgm.schedules').warning('Schedule preparation commit uncertain; reconcile original occurrence only')
                return True
            raise
        # No database connection survives into UDP dispatch.
        if dispatch:
            rid, principal, child_id = dispatch
            try:
                result = self.native.confirm(principal, child_id, 'schedule-' + child_id, actor='scheduler')
            except Exception:
                # Keep durable awaiting record. Recovery reads/cancels, never sends.
                return True
            self.finish_run(rid, 'sent' if result['status'] == 'sent' else 'needs_attention',
                            '指令已发送，游戏效果未知' if result['status'] == 'sent' else '公告未发送或发送结果不确定；请查询原操作')
        return True


class OperationsWorker:
    """One thread for scheduled triggers and existing per-target reward work."""
    def __init__(self, schedules, jobs, settings, pulse=None):
        self.schedules, self.jobs, self.settings = schedules, jobs, settings
        from .task_health import WorkerPulse
        self.pulse = pulse or WorkerPulse()
        self.last_scan = float('-inf')

    def step(self):
        now = time.monotonic()
        if self.settings.schedule_worker_enabled and now - self.last_scan >= 5:
            self.last_scan = now
            try:
                self.pulse.call("schedules", self.schedules.step)
            except Exception as error:
                logging.getLogger('dnfgm.schedules').warning('Schedule scan failed: %s; durable state retained', type(error).__name__)
        # A scheduler failure must not starve already-authorized reward jobs.
        if self.settings.batch_worker_enabled:
            self.pulse.call("rewards", self.jobs.step)
