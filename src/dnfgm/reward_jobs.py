"""Single-executor durable rewards. No HTTP request or browser owns a running job.

Game changes, operation/audit, deduplication and target completion share ONE
transaction. A durable executing marker precedes it. Abandoned executing targets
are reconciled under the target row lock and never automatically replayed.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
import logging
import threading
import time
import uuid
from pymysql.err import IntegrityError
from fastapi import HTTPException
from .service import Service, one, dump, character
from .encoding import mysql_latin1_text
from .write_gate import WriteGateClosed
from . import campaign_audience

WORKER_LOCK='dnf_gm_reward_jobs_executor'


def failed_message(error):
    return str(error.detail)[:200] if isinstance(error,HTTPException) else '服务异常；请核对原操作，不要另建重复任务'


class NoRewardTargets(HTTPException):
    def __init__(self):
        super().__init__(422, '没有符合条件的未删除角色')


class AttemptError(Exception):
    def __init__(self,target,error,uncertain):
        self.target,self.error,self.uncertain=target,error,uncertain


class RewardJobs:
    def __init__(self,db,settings,service=None):
        self.db,self.settings=db,settings
        self.service=service or Service(db,settings)

    @staticmethod
    def engines(q):
        q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('reward_jobs','reward_targets','reward_account_credits')")
        engines=q.fetchall()
        if len(engines)!=3 or any(e['ENGINE']!='InnoDB' for e in engines):
            raise HTTPException(409,'批量任务事务表未就绪')

    def audit(self,q,job,action,result,actor="owner"):
        q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,%s,%s,%s,%s,%s)",
                  ('job-'+uuid.uuid4().hex,actor,'batch-'+action,job['reason'],dump({'job_id':job['id']}),dump(result)))

    @staticmethod
    def definition(job):
        request,preview=json.loads(job['request_json']),json.loads(job['preview_json'])
        expected=hashlib.sha256(dump({'request':request,'preview':preview}).encode()).hexdigest()
        if expected!=job['fingerprint']:
            raise HTTPException(409,'批量任务定义校验失败，禁止执行')
        return request,preview

    @staticmethod
    def selector(filters):
        mode=filters['mode'];ids=sorted(set(filters['charac_nos']))
        uids=sorted(set(filters.get('account_uids',[])));names=sorted(set(filters.get('account_names',[])))
        if mode not in ('selected','accounts','filtered','online','all'):
            raise HTTPException(422,'未知目标模式')
        if filters['min_level']>filters['max_level']:
            raise HTTPException(422,'等级下限不能高于上限')
        changed=bool(filters['uid'] or filters['job'] is not None or filters['min_level'] or filters['max_level']!=255 or filters['q']
                     or filters.get('tags_all') or filters.get('created_from') or filters.get('created_to') or filters.get('inactive_before'))
        if mode=='accounts':
            if ids or changed or bool(uids)==bool(names):
                raise HTTPException(422,'账号名单只能填写UID或账号名其中一种，不能混合角色或筛选条件')
            if any(type(i) is not int or not 1<=i<=2147483647 for i in uids):
                raise HTTPException(422,'账号UID必须为有效正整数')
            if any(not isinstance(n,str) or not n.strip() or any(ord(c)<32 or ord(c)==127 for c in n) for n in names):
                raise HTTPException(422,'账号名不能为空或含控制字符')
        elif uids or names:
            raise HTTPException(422,'账号名单只能用于指定账号模式')
        if mode=='selected':
            if not ids or any(type(i) is not int or not 1<=i<=2147483647 for i in ids) or changed:
                raise HTTPException(422,'指定名单需要有效角色编号，不可混合筛选条件')
        elif ids or (mode=='all' and changed):
            raise HTTPException(422,'目标模式与名单/筛选参数不一致')
        if mode=='filtered' and not changed:
            raise HTTPException(422,'请填写筛选条件，或明确选择全服角色')
        conditions=['c.delete_flag=0'];args=[]
        if ids:conditions.append('c.charac_no IN ('+','.join(['%s']*len(ids))+')');args.extend(ids)
        if uids:conditions.append('a.UID IN ('+','.join(['%s']*len(uids))+')');args.extend(uids)
        if names:conditions.append('BINARY a.accountname IN ('+','.join(['%s']*len(names))+')');args.extend(names)
        if filters['uid']:conditions.append('c.m_id=%s');args.append(filters['uid'])
        if filters['job'] is not None:conditions.append('c.job=%s');args.append(filters['job'])
        conditions.append('c.lev BETWEEN %s AND %s');args.extend([filters['min_level'],filters['max_level']])
        if mode=='online':conditions.append('l.login_status=1')
        if filters['q']:
            def like(text):return '%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            conditions.append('(c.charac_name LIKE %s OR c.charac_name LIKE %s)')
            args.extend([like(filters['q']),like(mysql_latin1_text(filters['q'].encode('utf-8')))])
        extra, extra_args = campaign_audience.predicates(filters)
        conditions.extend(extra); args.extend(extra_args)
        return ' AND '.join(conditions),args,ids

    def resolve_accounts(self,q,filters):
        # Names identify an exact account now, not a dynamic future recipient.
        # Only SELECT UID/accountname; no passwords or other account attributes.
        self.selector(filters)
        campaign_audience.verify(q,filters)
        if filters['mode']!='accounts':return filters,[],None
        kind='account_uids' if filters.get('account_uids') else 'account_names'
        raw=filters[kind];wanted=sorted(set(raw))
        column='UID' if kind=='account_uids' else 'BINARY accountname'
        q.execute('SELECT UID,accountname FROM d_taiwan.accounts WHERE '+column+' IN ('+','.join(['%s']*len(wanted))+') ORDER BY UID LIMIT 5001',wanted)
        rows=q.fetchall()
        keys=[r['UID'] if kind=='account_uids' else r['accountname'] for r in rows]
        if len(rows)!=len(wanted) or set(keys)!=set(wanted):
            raise HTTPException(422,'名单包含不存在或名称不唯一的账号；请核对账号名单，没有创建任务')
        uids=[r['UID'] for r in rows]
        resolved={**filters,'account_uids':uids,'account_names':[]}
        return resolved,uids,{'input_kind':kind,'requested_accounts':len(wanted),'duplicates_removed':len(raw)-len(wanted)}

    def create_in_transaction(self,q,session_hash,data,job_id=None,now=None):
        data=copy.deepcopy(data)
        self.service.campaigns.bind_job(q,data)
        if not data['reason'].strip():raise HTTPException(422,'必须填写发放原因')
        selected,expected_accounts,account_selection=self.resolve_accounts(q,data['targets'])
        clause,args,ids=self.selector(selected)
        request=copy.deepcopy(data);reward=request['reward'];reward['action']='reward'
        job_id=job_id or uuid.uuid4().hex;now=int(time.time()) if now is None else now;digest=hashlib.sha256();ordinal=0
        self.engines(q)
        resolved=self.service.reward_snapshot(q,reward)
        # Streaming keyset selection: no all-server list in application RAM.
        upper=one(q,'SELECT COALESCE(MAX(charac_no),0) n FROM taiwan_cain.charac_info')['n']
        last=0
        while True:
            q.execute('SELECT c.charac_no,c.m_id AS uid,c.charac_name,CAST(CONVERT(c.charac_name USING latin1) AS BINARY) AS client_name_bytes,c.lev,c.job,c.delete_flag,a.accountname '
                      'FROM taiwan_cain.charac_info c JOIN d_taiwan.accounts a ON a.UID=c.m_id LEFT JOIN taiwan_login.login_account_3 l ON l.m_id=c.m_id '
                      'WHERE '+clause+' AND c.charac_no>%s AND c.charac_no<=%s ORDER BY c.charac_no LIMIT 250',(*args,last,upper))
            rows=q.fetchall()
            inserts=[]
            for row in rows:
                target=character(row);ordinal+=1
                digest.update(dump(target).encode());digest.update(b'\n')
                inserts.append((job_id,ordinal,target['uid'],target['charac_no'],dump(target),uuid.uuid4().hex))
            if inserts:q.executemany('INSERT INTO dnf_gm.reward_targets(job_id,ordinal,target_uid,charac_no,target_json,operation_id) VALUES(%s,%s,%s,%s,%s,%s)',inserts)
            if len(rows)<250:break
            last=rows[-1]['charac_no']
        if not ordinal:
            if expected_accounts:raise HTTPException(422,'账号名单中没有可发放的未删除角色；没有创建任务')
            raise NoRewardTargets()
        if expected_accounts:
            q.execute('SELECT DISTINCT target_uid FROM dnf_gm.reward_targets WHERE job_id=%s LIMIT 5001',(job_id,))
            if {r['target_uid'] for r in q.fetchall()}!=set(expected_accounts):
                raise HTTPException(422,'部分账号没有可发放的未删除角色；名单未被静默缩减，没有创建任务')
        if ids and len(ids)!=ordinal:raise HTTPException(422,'名单包含不存在、已删除或无所属账号的角色；没有创建任务')
        accounts=one(q,'SELECT COUNT(DISTINCT target_uid) n FROM dnf_gm.reward_targets WHERE job_id=%s',(job_id,))['n']
        multiplier=accounts if data['account_reward_mode']=='once_per_account' else ordinal
        campaign=resolved.get('campaign')
        if campaign and campaign['dedupe']=='account':multiplier=accounts
        summary={**resolved,'target_count':ordinal,'account_count':accounts,
                 'duplicates_removed':account_selection['duplicates_removed'] if account_selection else len(data['targets']['charac_nos'])-len(ids),
                 'account_selection':account_selection,
                 'account_reward_mode':data['account_reward_mode'],
                 'currency_totals':{key:str(value*multiplier) for key,value in reward['currency_rewards'].items()},
                 'gold_total':str(reward.get('gold',0)*(multiplier if campaign else ordinal)),
                 'target_digest':digest.hexdigest(),
                 'note':('活动奖励按活动去重口径发放整份礼包；已领取或并发先提交的目标跳过整份奖励，金额为未扣除既有领取的预估上界。' if campaign else '')+
                        '名单已固定；在线模式选择在线账号下所有符合条件的角色，不代表这些角色同时在线。账号奖励按执行时锁定余额增加；物品/金币逐角色发放。'}
        fingerprint=hashlib.sha256(dump({'request':request,'preview':summary}).encode()).hexdigest()
        q.execute("INSERT INTO dnf_gm.reward_jobs(id,session_hash,fingerprint,request_json,preview_json,status,reason,target_count,account_count,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,'preview',%s,%s,%s,%s,%s)",
                  (job_id,session_hash,fingerprint,dump(request),dump(summary),data['reason'],ordinal,accounts,now,now+300))
        self.audit(q,{'id':job_id,'reason':data['reason']},'preview',{'target_count':ordinal,'account_count':accounts,'fingerprint':fingerprint},actor='scheduler' if data.get('schedule_id') else 'owner')
        if campaign:self.service.campaigns.link(q,campaign['id'],'job',job_id)
        return one(q,'SELECT * FROM dnf_gm.reward_jobs WHERE id=%s',(job_id,))

    def preview(self,session_hash,data):
        with self.db.connect() as c,c.cursor() as q:
            job=self.create_in_transaction(q,session_hash,data)
            c.commit()
        return self.detail(job['id'])

    def detail(self,job_id):
        with self.db.connect() as c,c.cursor() as q:
            job=one(q,'SELECT id,fingerprint,status,reason,pause_reason,target_count,account_count,created_at,expires_at,confirmed_at,request_json,preview_json FROM dnf_gm.reward_jobs WHERE id=%s',(job_id,))
            if not job:raise HTTPException(404,'任务不存在')
            job['request']=json.loads(job.pop('request_json'));job['preview']=json.loads(job.pop('preview_json'))
            q.execute('SELECT status,COUNT(*) n FROM dnf_gm.reward_targets WHERE job_id=%s GROUP BY status',(job_id,))
            job['counts']={r['status']:r['n'] for r in q.fetchall()}
            job['worker_enabled']=self.settings.batch_worker_enabled
            job['write_enabled']='batch-reward' in self.settings.writes and self.service.write_enabled(job['request']['reward'],job['preview'])
            return job

    def list(self,page=1):
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT id,status,reason,pause_reason,target_count,account_count,created_at,confirmed_at FROM dnf_gm.reward_jobs ORDER BY created_at DESC,id DESC LIMIT 21 OFFSET %s',((page-1)*20,))
            rows=q.fetchall()
            for row in rows[:20]:
                q.execute('SELECT status,COUNT(*) n FROM dnf_gm.reward_targets WHERE job_id=%s GROUP BY status',(row['id'],))
                row['counts']={r['status']:r['n'] for r in q.fetchall()}
            return {'items':rows[:20],'has_more':len(rows)>20,'page':page,'worker_enabled':self.settings.batch_worker_enabled}

    def targets(self,job_id,after=0,status='',error_type=''):
        if status and status not in ('pending','executing','committed','uncertain','failed','cancelled'):
            raise HTTPException(422,'未知目标状态')
        if len(error_type)>64:raise HTTPException(422,'失败类型过长')
        with self.db.connect() as c,c.cursor() as q:
            if not one(q,'SELECT id FROM dnf_gm.reward_jobs WHERE id=%s',(job_id,)):raise HTTPException(404,'任务不存在')
            clauses=['job_id=%s','ordinal>%s'];args=[job_id,after]
            if status:clauses.append('status=%s');args.append(status)
            if error_type:clauses.append('error_type=%s');args.append(error_type)
            q.execute('SELECT ordinal,target_uid,charac_no,target_json,operation_id,status,attempts,error_type,error_message,last_attempt FROM dnf_gm.reward_targets WHERE '+
                      ' AND '.join(clauses)+' ORDER BY ordinal LIMIT 51',args)
            rows=q.fetchall()
            for row in rows:row['target']=json.loads(row.pop('target_json'))
            q.execute('SELECT status,COUNT(*) n FROM dnf_gm.reward_targets WHERE job_id=%s GROUP BY status',(job_id,))
            counts={r['status']:r['n'] for r in q.fetchall()}
            q.execute("SELECT error_type,COUNT(*) n FROM dnf_gm.reward_targets WHERE job_id=%s AND error_type<>'' GROUP BY error_type ORDER BY n DESC,error_type LIMIT 50",(job_id,))
            return {'items':rows[:50],'next_after':rows[49]['ordinal'] if len(rows)>50 else None,
                    'counts':counts,'errors':q.fetchall(),'filters':{'status':status,'error_type':error_type}}

    def check_start(self,q,job):
        if not self.settings.batch_worker_enabled:raise HTTPException(409,'批量执行器未启用，任务保持预览')
        if 'batch-reward' not in self.settings.writes:raise HTTPException(403,'批量奖励写入尚未激活')
        request,preview=self.definition(job)
        # All test-target restrictions apply to the full frozen set before starting.
        if self.settings.test_uids:
            denied=one(q,'SELECT target_uid FROM dnf_gm.reward_targets WHERE job_id=%s AND target_uid NOT IN ('+','.join(['%s']*len(self.settings.test_uids))+') LIMIT 1',(job['id'],*self.settings.test_uids))
            if denied:raise HTTPException(403,'名单包含非测试账号，当前不能启动此任务')
        first=one(q,'SELECT target_uid FROM dnf_gm.reward_targets WHERE job_id=%s ORDER BY ordinal LIMIT 1',(job['id'],))
        self.service.check_write(q,{**request['reward'],'uid':first['target_uid']},preview)
        self.engines(q)

    def start(self,session_hash,job_id,data):
        attempted=False
        try:
            with self.db.connect() as c,c.cursor() as q:
                job=one(q,'SELECT * FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE',(job_id,))
                if not job or job['session_hash']!=session_hash:raise HTTPException(404,'预览不存在于当前会话')
                if (job['fingerprint']!=data['fingerprint'] or job['target_count']!=data['target_count'] or job['account_count']!=data['account_count']):
                    raise HTTPException(409,'任务预览内容不一致')
                old=one(q,'SELECT id FROM dnf_gm.reward_jobs WHERE idempotency_key=%s',(data['idempotency_key'],))
                if old and old['id']!=job_id:raise HTTPException(409,'幂等键已用于另一个任务')
                if job['idempotency_key']:
                    if job['idempotency_key']!=data['idempotency_key']:raise HTTPException(409,'任务已用其他幂等键确认')
                else:
                    if job['status']!='preview' or job['expires_at']<int(time.time()):raise HTTPException(409,'预览已过期或状态变化，请重新预览')
                    request=json.loads(job['request_json'])
                    if request['targets']['mode']=='all' and data['all_server_confirmation']!='全服发放':raise HTTPException(422,'全服任务需明确输入“全服发放”')
                    if request['account_reward_mode']=='per_character' and request['reward']['currency_rewards'] and not data['acknowledge_repeat']:
                        raise HTTPException(422,'按角色重复账号奖励需要单独确认')
                    self.check_start(q,job)
                    q.execute("UPDATE dnf_gm.reward_jobs SET status='running',idempotency_key=%s,confirmed_at=%s WHERE id=%s",(data['idempotency_key'],int(time.time()),job_id))
                    self.audit(q,job,'start',{'target_count':job['target_count'],'account_count':job['account_count']})
                    attempted=True;c.commit()
        except IntegrityError as error:
            if error.args[0]==1062:raise HTTPException(409,'幂等键已被其他任务使用，请核对原任务') from None
            raise
        except Exception:
            if attempted:raise HTTPException(503,'启动结果待确认，请查询原任务，禁止重新创建任务') from None
            raise
        return self.detail(job_id)

    def reconcile_target(self,q,target):
        # This caller owns the target row lock: any in-flight reward transaction
        # must have finished before this negative evidence can be trusted.
        operation=one(q,'SELECT status FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE',(target['operation_id'],))
        audited=one(q,'SELECT id FROM dnf_gm.audit WHERE operation_id=%s FOR UPDATE',(target['operation_id'],))
        if operation and operation['status']=='committed' and audited:
            status,message='committed',''
        elif operation or audited:
            raise HTTPException(409,'操作与审计不一致，保留待核对状态')
        else:status,message='failed','已取得事务锁且无提交记录；未提交，可人工重试'
        q.execute('UPDATE dnf_gm.reward_targets SET status=%s,error_message=%s WHERE job_id=%s AND ordinal=%s',(status,message,target['job_id'],target['ordinal']))
        return status

    def control(self,job_id,action):
        with self.db.connect() as c,c.cursor() as q:
            job=one(q,'SELECT * FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE',(job_id,))
            if not job:raise HTTPException(404,'任务不存在')
            if job['status']=='preview':raise HTTPException(409,'预览尚未启动')
            if action=='pause':
                if job['status']=='running':q.execute("UPDATE dnf_gm.reward_jobs SET status='paused',pause_reason='管理员暂停；已开始的单目标事务仍可能完成' WHERE id=%s",(job_id,))
            elif action=='cancel':
                q.execute("UPDATE dnf_gm.reward_jobs SET status='cancelled',pause_reason='管理员取消未执行目标；不撤销已提交奖励' WHERE id=%s",(job_id,))
            elif action=='resume':
                if job['status'] not in ('paused','needs_attention','running'):raise HTTPException(409,'此状态不能继续')
                self.check_start(q,job)
                q.execute("UPDATE dnf_gm.reward_jobs SET status='running',pause_reason='' WHERE id=%s",(job_id,))
            elif action in ('reconcile','retry-failed'):
                if job['status']=='running':raise HTTPException(409,'请先暂停任务，再核对或重试')
                if job['status']=='cancelled' and action!='reconcile':raise HTTPException(409,'已取消任务不能重新发放，请保留记录')
                last=0
                states="('failed')" if action=='retry-failed' else "('executing','uncertain')"
                while True:
                    q.execute('SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s AND status IN '+states+' AND ordinal>%s ORDER BY ordinal LIMIT 100 FOR UPDATE',(job_id,last))
                    rows=q.fetchall()
                    for target in rows:
                        state=self.reconcile_target(q,target)
                        if job['status']=='cancelled' and state=='failed':
                            q.execute("UPDATE dnf_gm.reward_targets SET error_message='已确认未提交；任务已取消，不会重新发放' WHERE job_id=%s AND ordinal=%s",(job_id,target['ordinal']))
                        if action=='retry-failed' and state=='failed':
                            q.execute("UPDATE dnf_gm.reward_targets SET status='pending',error_type='',error_message='' WHERE job_id=%s AND ordinal=%s",(job_id,target['ordinal']))
                    if len(rows)<100:break
                    last=rows[-1]['ordinal']
                q.execute("UPDATE dnf_gm.reward_jobs SET status=IF(status='cancelled','cancelled','paused') WHERE id=%s",(job_id,))
            else:raise HTTPException(422,'未知任务操作')
            self.audit(q,job,action,{'action':action});c.commit()
        return self.detail(job_id)

    def step(self):
        """At most one target per call. No retries of unknown game writes."""
        try:
            with ExitStack() as gates,self.db.connect() as c,c.cursor() as q:
                if not one(q,'SELECT GET_LOCK(%s,0) locked',(WORKER_LOCK,))['locked']:return False
                try:
                    self.engines(q)
                    # Restart recovery is read/lock reconciliation, not another award.
                    target=one(q,"SELECT t.* FROM dnf_gm.reward_targets t JOIN dnf_gm.reward_jobs j ON j.id=t.job_id WHERE t.status='executing' OR (t.status='uncertain' AND j.status='running') ORDER BY t.job_id,t.ordinal LIMIT 1")
                    if target:
                        # Same lock order as control and execution: job -> target.
                        one(q,'SELECT id FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE',(target['job_id'],))
                        target=one(q,'SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s AND ordinal=%s FOR UPDATE',(target['job_id'],target['ordinal']))
                        if target['status'] not in ('executing','uncertain'):return False
                        try:
                            self.reconcile_target(q,target)
                            message='中断任务已核对；不会自动重放，请查看目标结果'
                        except HTTPException as error:
                            if error.status_code!=409:raise
                            message='操作与审计不一致；已隔离此目标，需人工核对，不会自动重发'
                            q.execute("UPDATE dnf_gm.reward_targets SET status='uncertain',error_type='ReconciliationConflict',error_message=%s WHERE job_id=%s AND ordinal=%s",(message,target['job_id'],target['ordinal']))
                        q.execute("UPDATE dnf_gm.reward_jobs SET status=IF(status='running','paused',status),pause_reason=%s WHERE id=%s",(message,target['job_id']))
                        c.commit();return True
                    job=one(q,"SELECT * FROM dnf_gm.reward_jobs WHERE status='running' ORDER BY created_at,id LIMIT 1")
                    if not job:return False
                    job=one(q,'SELECT * FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE',(job['id'],))
                    if job['status']!='running':return False
                    target=one(q,"SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s AND status='pending' ORDER BY ordinal LIMIT 1 FOR UPDATE",(job['id'],))
                    if not target:
                        failed=one(q,"SELECT COUNT(*) n FROM dnf_gm.reward_targets WHERE job_id=%s AND status<>'committed'",(job['id'],))['n']
                        q.execute("UPDATE dnf_gm.reward_jobs SET status=%s WHERE id=%s AND status='running'",('needs_attention' if failed else 'finished',job['id']))
                        c.commit();return True
                    lease=gates.enter_context(self.service.write_gate.writer())
                    lease.protect_transaction(q)
                    q.execute("UPDATE dnf_gm.reward_targets SET status='executing',attempts=attempts+1,last_attempt=%s WHERE job_id=%s AND ordinal=%s",(int(time.time()),job['id'],target['ordinal']))
                    lease.check()
                    c.commit()  # Durable dispatch marker BEFORE any game mutation.
                    self.execute_target(c,q,job,target,lease)
                    return True
                finally:
                    try:c.rollback();q.execute('SELECT RELEASE_LOCK(%s)',(WORKER_LOCK,))
                    except Exception:pass  # Closing a lost connection also releases it.
        except WriteGateClosed:
            # No new executing marker or retry count was committed. Keep queued
            # work intact while the maintenance controller owns admission.
            return False
        except AttemptError as error:
            self.record_failure(error)
            return True

    def execute_target(self,c,q,job,target,lease):
        attempted=False
        try:
            lease.protect_transaction(q)
            current=one(q,'SELECT status FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE',(job['id'],))
            if current['status']!='running':
                q.execute("UPDATE dnf_gm.reward_targets SET status='pending' WHERE job_id=%s AND ordinal=%s AND status='executing'",(job['id'],target['ordinal']))
                c.commit();return
            locked=one(q,'SELECT status FROM dnf_gm.reward_targets WHERE job_id=%s AND ordinal=%s FOR UPDATE',(job['id'],target['ordinal']))
            if not locked or locked['status']!='executing':return
            request,preview=self.definition(job);frozen=json.loads(target['target_json'])
            data={**request['reward'],'uid':target['target_uid'],'charac_no':target['charac_no'],'reason':job['reason'],'job_id':job['id']}
            if request.get('schedule_id'):data['schedule_id']=request['schedule_id']
            if 'batch-reward' not in self.settings.writes:raise HTTPException(403,'批量写入已停用')
            self.service.check_write(q,data,preview);self.engines(q)
            account=self.service.target(q,data,lock=True)
            if account['accountname']!=frozen['accountname'] or account['character']['stored_name']!=frozen['stored_name']:
                raise HTTPException(409,'目标身份或角色名称已变化，需重新核对')
            skipped=False
            if not data.get('campaign_id') and request['account_reward_mode']=='once_per_account' and data['currency_rewards']:
                previous=one(q,'SELECT operation_id FROM dnf_gm.reward_account_credits WHERE job_id=%s AND target_uid=%s FOR UPDATE',(job['id'],data['uid']))
                skipped=bool(previous)
                if skipped:data['currency_rewards']={}
            op=target['operation_id'];token=hashlib.sha256(('batch:'+job['id']+self.settings.secret).encode()).hexdigest()
            per_preview={**preview,'target':account,'action':'reward','reason':data['reason']}
            q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,idempotency_key,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,'reward',%s,%s,'preview',%s,%s)",
                      (op,token,'batch-'+op,hashlib.sha256(dump(data).encode()).hexdigest(),dump(data),dump(per_preview),int(time.time()),int(time.time())))
            result={'operation_id':op,'uid':data['uid'],'action':'reward','job_id':job['id'],'account_reward_skipped':skipped,
                    **self.service.apply_reward(q,op,data,per_preview,account)}
            if not data.get('campaign_id') and request['account_reward_mode']=='once_per_account' and data['currency_rewards']:
                q.execute('INSERT INTO dnf_gm.reward_account_credits(job_id,target_uid,operation_id) VALUES(%s,%s,%s)',(job['id'],data['uid'],op))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,%s,'reward',%s,%s,%s,%s)",(op,'scheduler' if request.get('schedule_id') else 'owner',data['uid'],data['reason'],dump(data),dump(result)))
            self.service.economy.record(q,op)
            q.execute("UPDATE dnf_gm.operations SET status='committed',result_json=%s WHERE operation_id=%s",(dump(result),op))
            q.execute("UPDATE dnf_gm.reward_targets SET status='committed',error_type='',error_message='' WHERE job_id=%s AND ordinal=%s",(job['id'],target['ordinal']))
            lease.check()
            attempted=True;c.commit()
        except Exception as error:
            raise AttemptError(target,error,attempted) from None

    def record_failure(self,attempt):
        target=attempt.target;error=attempt.error
        with self.db.connect() as c,c.cursor() as q:
            one(q,'SELECT id FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE',(target['job_id'],))
            locked=one(q,'SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s AND ordinal=%s FOR UPDATE',(target['job_id'],target['ordinal']))
            if not locked or locked['status']=='committed':return
            # No automatic replay even when a connection failure probably rolled back.
            status='uncertain' if attempt.uncertain else 'failed'
            message='提交结果待核对；先核对原目标，不要重新创建任务' if attempt.uncertain else failed_message(error)
            q.execute('UPDATE dnf_gm.reward_targets SET status=%s,error_type=%s,error_message=%s WHERE job_id=%s AND ordinal=%s',(status,type(error).__name__,message,target['job_id'],target['ordinal']))
            q.execute('INSERT INTO dnf_gm.failures(operation_id,error_type) VALUES(%s,%s)',(target['operation_id'],type(error).__name__))
            q.execute("UPDATE dnf_gm.reward_jobs SET status=IF(status='cancelled',status,'paused'),pause_reason=%s WHERE id=%s",(message,target['job_id']))
            c.commit()


class JobWorker:
    def __init__(self,jobs,interval=1):
        self.jobs,self.interval=jobs,interval
        self.stop_event=threading.Event()
        self.thread=threading.Thread(target=self.run,name='dnfgm-rewards',daemon=True)
    def start(self):self.thread.start()
    def stop(self):self.stop_event.set();self.thread.join(timeout=5)
    def run(self):
        while not self.stop_event.wait(self.interval):
            try:self.jobs.step()
            except Exception as error:
                # No raw SQL/config in logs, and no retry of an executing reward.
                logging.getLogger('dnfgm.jobs').warning('Reward worker step failed with %s; durable state retained',type(error).__name__)
