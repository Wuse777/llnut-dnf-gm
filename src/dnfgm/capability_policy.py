"""Fixed owner capability switches, persisted atomically with audit and receipts.

No config/SQL/shell supplied by browsers. A live proxy changes one immutable
policy snapshot, so shared services and the single worker need no restart.
"""
import hashlib
import json
from threading import RLock
import time
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

WRITES=('currency','mail','ban','unban','equipment-unlock','reward','batch-reward','item-edit','item-reclaim','item-restore','char-fatigue','char-rename','char-rescue','quest-clear','char-sp-tp','char-skill-reset','char-level','maintenance')
SWITCHES=(*WRITES,'native-monitor','native-notice','native-kick','batch-worker','schedule-worker','release-cleanup','health-alerts','backup-alerts','task-alerts')
FLAGS={'native_monitor_enabled':'native-monitor','batch_worker_enabled':'batch-worker','schedule_worker_enabled':'schedule-worker','cleanup_enabled':'release-cleanup','health_alerts_enabled':'health-alerts','backup_alerts_enabled':'backup-alerts','task_alerts_enabled':'task-alerts'}
LABELS=dict(zip(SWITCHES,('余额调整','物品／金币邮件','封禁','解封','装备提前解锁','组合奖励','批量奖励','装备编辑','物品回收','快照恢复','角色疲劳恢复／调整','角色改名','卡死位置救援','单任务槽清理','SP／TP技能点维护','PvE技能重置','等级／经验维护','网页维护申请','原生会话查询','公告','踢下线','批量执行器','定时执行器','旧GM产物清理','核心与资源告警','备份与恢复证据告警','运营任务告警')))
Switch=Literal['currency','mail','ban','unban','equipment-unlock','reward','batch-reward','item-edit','item-reclaim','item-restore','char-fatigue','char-rename','char-rescue','quest-clear','char-sp-tp','char-skill-reset','char-level','maintenance','native-monitor','native-notice','native-kick','batch-worker','schedule-worker','release-cleanup','health-alerts','backup-alerts','task-alerts']


class PolicyUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    expected_revision:StrictInt=Field(ge=0,le=2147483647)
    enabled:list[Switch]=Field(max_length=len(SWITCHES))
    reason:str=Field(min_length=2,max_length=200)


def normalized(enabled):
    if not isinstance(enabled,list) or len(enabled)!=len(set(enabled)) or not set(enabled)<=set(SWITCHES):
        raise ValueError('Invalid fixed capability set')
    enabled=set(enabled)
    if enabled&{'native-notice','native-kick'}:enabled.add('native-monitor')
    if 'batch-worker' in enabled:enabled.add('batch-reward')
    return sorted(enabled)


def overrides(enabled):
    active=set(enabled)
    return {'writes':tuple(k for k in WRITES if k in active),
            'native_control_actions':tuple(k for k in ('native-notice','native-kick') if k in active),
            'write_approvals':{k:True for k in active},'test_uids':(),
            **{field:key in active for field,key in FLAGS.items()}}


class RuntimeSettings:
    def __init__(self,base):
        self.base=base;self.overlay={}
    def __getattr__(self,key):
        return self.overlay[key] if key in self.overlay else getattr(self.base,key)


class CapabilityPolicy:
    def __init__(self,db,settings,clock=time.monotonic):
        self.db=db;self.settings=settings;self.clock=clock;self.lock=RLock()
        self.last=float('-inf');self.state='unknown';self.revision=None;self.updated_at=None

    def legacy_enabled(self):
        s=self.settings.base
        return sorted(set(s.writes)|set(s.native_control_actions)|{key for field,key in FLAGS.items() if getattr(s,field)})

    def apply(self,row):
        revision=row['revision'];enabled=normalized(json.loads(row['enabled_json']))
        if type(revision) is not int or revision<0:raise ValueError()
        self.settings.overlay=overrides(enabled) if revision else {}
        self.revision=revision;self.updated_at=row['updated_at'];self.state='managed' if revision else 'legacy'

    def refresh(self,force=False):
        with self.lock:
            if not force and self.clock()-self.last<5:return
            try:
                with self.db.connect() as c,c.cursor() as q:
                    q.execute('SELECT revision,enabled_json,updated_at FROM dnf_gm.capability_policy WHERE id=1')
                    row=q.fetchone()
                    if row is None:raise ValueError()
                self.apply(row)
            except Exception:
                # Reads/login/recovery remain available; never execute against an
                # unknown permission policy. This is not a test-account lockout.
                self.settings.overlay=overrides([]);self.state='unknown';self.revision=None
            self.last=self.clock()

    def view(self):
        with self.lock:
            enabled=self.legacy_enabled() if self.state=='legacy' else sorted(set(self.settings.writes)|set(self.settings.native_control_actions)|{key for field,key in FLAGS.items() if getattr(self.settings,field)})
            return {'state':self.state,'revision':self.revision,'updated_at':self.updated_at,
                    'enabled':enabled,'choices':[{'id':k,'label':LABELS[k]} for k in SWITCHES],
                    'account_scope':'all' if self.state=='managed' else 'legacy' if self.state=='legacy' else 'unknown'}

    @staticmethod
    def engines(q):
        q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('capability_policy','capability_requests','audit')")
        rows=q.fetchall()
        if len(rows)!=3 or any(r['ENGINE']!='InnoDB' for r in rows):raise HTTPException(409,'权限设置、收据或审计事务表未就绪')

    def update(self,data):
        request=PolicyUpdate(**data).model_dump()
        try:enabled=normalized(request['enabled'])
        except ValueError:raise HTTPException(422,'能力列表不能包含重复或未知选项') from None
        if not request['reason'].strip():raise HTTPException(422,'请填写权限调整原因')
        text=json.dumps(request,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        fingerprint=hashlib.sha256(text.encode()).hexdigest();now=int(time.time())
        with self.lock:
            with self.db.connect() as c,c.cursor() as q:
                self.engines(q)
                q.execute('SELECT revision,enabled_json,updated_at FROM dnf_gm.capability_policy WHERE id=1 FOR UPDATE')
                row=q.fetchone()
                if not row:raise HTTPException(409,'权限迁移未完成')
                q.execute('SELECT fingerprint,result_json FROM dnf_gm.capability_requests WHERE request_id=%s FOR UPDATE',(request['request_id'],))
                receipt=q.fetchone()
                if receipt:
                    if receipt['fingerprint']!=fingerprint:raise HTTPException(409,'同一请求编号不能用于不同权限设置')
                    self.apply(row);self.last=self.clock()
                    return json.loads(receipt['result_json'])
                if row['revision']!=request['expected_revision']:raise HTTPException(409,'权限已变化，请刷新并重新核对')
                revision=row['revision']+1
                result={'request_id':request['request_id'],'revision':revision,'enabled':enabled,'account_scope':'all','updated_at':now,'status':'committed'}
                encoded=json.dumps(result,ensure_ascii=False,separators=(',',':'))
                q.execute('UPDATE dnf_gm.capability_policy SET revision=%s,enabled_json=%s,updated_at=%s WHERE id=1',(revision,json.dumps(enabled),now))
                q.execute('INSERT INTO dnf_gm.capability_requests VALUES(%s,%s,%s,%s)',(request['request_id'],fingerprint,encoded,now))
                before=self.legacy_enabled() if row['revision']==0 else json.loads(row['enabled_json'])
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','capability-policy',%s,%s,%s)",
                          (request['request_id'],request['reason'],json.dumps({'before':before,'enabled':enabled,'previous_revision':row['revision']}),encoded))
                # On uncertain commit, caller looks up this receipt; never replay.
                c.commit()
            self.apply({'revision':revision,'enabled_json':json.dumps(enabled),'updated_at':now});self.last=self.clock()
            return result

    def receipt(self,request_id):
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT result_json FROM dnf_gm.capability_requests WHERE request_id=%s',(request_id,))
            row=q.fetchone()
        if not row:raise HTTPException(404,'尚无该请求的已提交收据；不要换编号重复提交')
        return json.loads(row['result_json'])


class PolicyWorker:
    def __init__(self,policy,worker):self.policy=policy;self.worker=worker
    def step(self):
        self.policy.refresh()
        self.worker.step()
