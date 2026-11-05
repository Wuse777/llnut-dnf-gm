"""Authenticated, audited maintenance outbox; no process or Docker access.

The web app can submit only fixed lifecycle requests. Root-owned receipts are
observations, not proof of gameplay effects. Queued is never displayed as done.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time

from fastapi import HTTPException
import pymysql
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .write_gate import GameplayWriteGate
from .catalog import snapshot
from .release_files import Refused, canonical, read_json, atomic_json

ACTION = 'maintenance'
ROOT_UID = 0
ID = re.compile(r'^[a-f0-9]{32}$')
SHA = re.compile(r'^[a-f0-9]{64}$')
PHASES = ('prepare', 'confirm', 'cancel', 'observe')
STATES = {'prepared','running','needs_review','game_drained','writers_stopped','cancelled','expired','rejected',
          'maintenance_open','resuming','completed'}
PUBLIC_FIELDS = {'state','fingerprint','created_at','expires_at','updated_at','revision','phase',
                 'games','events','command_may_have_run','error','maintenance_permit',
                 'can_confirm','can_cancel','can_replay','can_resume','client_verified',
                 'preview_expired','observation','window_requires_live_check'}


class MaintenancePrepare(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(min_length=2, max_length=200)


class MaintenanceConfirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledge_disconnect: StrictBool


def request_hash(request):
    return hashlib.sha256(canonical(request)).hexdigest()


def packet(request, phase, *, fingerprint=None):
    if phase not in PHASES:
        raise Refused('maintenance_phase_invalid')
    data = {'version':1, 'operation_id':request['operation_id'], 'phase':phase,
            'request':request, 'request_sha256':request_hash(request)}
    if phase == 'confirm':
        data['fingerprint'] = fingerprint
    return data


class MaintenanceRequests:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def enabled(self):
        return (ACTION in self.settings.writes and self.settings.write_approvals.get(ACTION) is True)

    def require_enabled(self):
        if not self.enabled():
            raise HTTPException(403,'维护申请开关已关闭，可在“功能与版本”网页开启；历史与结果仍可查询')

    def status(self):
        result = {'enabled':self.enabled(), 'state':'unavailable', 'prepare_supported':False,
                  'execute_supported':False, 'message':'维护执行器尚未安装或状态不可用，不代表权限未开放。'}
        try:
            doc = read_json(Path(self.settings.maintenance_dir)/'status.json', owner=ROOT_UID, limit=16384)
            if (doc.get('version') != 1 or type(doc.get('collected_at')) not in (int,float)
                    or not 0 <= time.time()-doc['collected_at'] <= 45
                    or doc.get('image_digest') != self.settings.image_digest
                    or doc.get('pvf_sha256') != self.settings.pvf_sha256
                    or doc.get('program_sha256') != self.settings.inventory_program_sha256):
                raise Refused('stale_or_changed')
            result.update(state='ok',collected_at=doc['collected_at'],
                          prepare_supported=doc.get('prepare_supported') is True,
                          execute_supported=doc.get('execute_supported') is True,
                          message='退出会影响当前游戏玩家；入队与进程退出均不等于装备维护已完成。')
            if not result['execute_supported']:
                result['message']='可生成只读维护计划；完整退出、关窗与恢复执行器尚未接通，不能确认停服。'
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            pass
        result['write_gate']=GameplayWriteGate(self.settings).status()
        return result

    def ready(self, execute=False):
        self.require_enabled()
        state = self.status()
        if not state['prepare_supported'] or execute and not state['execute_supported']:
            raise HTTPException(409,state['message'])
        if execute and state['write_gate']['state']!='open':
            raise HTTPException(409,'完整维护需要已安装且开放的写入屏障；当前不可核验或已有维护冻结，请核对原申请')
        live = snapshot(self.settings)
        if (not live.get('fresh') or live.get('core_ok') is not True
                or live.get('mem_available_mib',0)<256 or live.get('swap_free_mib',0)<1536
                or live.get('image_digest')!=self.settings.image_digest or live.get('pvf_sha256')!=self.settings.pvf_sha256):
            raise HTTPException(409,'当前游戏状态或资源未就绪，请先检查概览；不会发送退出命令')

    @staticmethod
    def engines(q):
        q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit')")
        rows=q.fetchall()
        if len(rows)!=2 or any(r['ENGINE']!='InnoDB' for r in rows):
            raise HTTPException(409,'维护请求与审计事务表未就绪')

    @staticmethod
    def row(q, op, lock=False):
        q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s'+(' FOR UPDATE' if lock else ''),(op,))
        row=q.fetchone()
        if not row or row['action']!=ACTION:
            raise HTTPException(404,'未找到该维护申请；不要换编号重复提交')
        return row

    @staticmethod
    def request(row):
        request=json.loads(row['request_json'])
        if request_hash(request)!=row['fingerprint'] or request['operation_id']!=row['operation_id']:
            raise HTTPException(409,'维护请求绑定不一致，请保留原编号核对')
        return request

    def receipt(self, row):
        path=Path(self.settings.maintenance_dir)/'results'/(row['operation_id']+'.json')
        try:
            result=read_json(path,owner=ROOT_UID,limit=65536)
        except FileNotFoundError:
            return None
        if (not isinstance(result,dict) or result.get('operation_id')!=row['operation_id']
                or result.get('request_sha256')!=row['fingerprint'] or result.get('version')!=1
                or result.get('state') not in STATES):
            raise Refused('maintenance_receipt_mismatch')
        # Root projection is already sanitized; never reflect arbitrary extra keys.
        return {k:result[k] for k in PUBLIC_FIELDS if k in result}

    def detail_row(self, row):
        request=self.request(row)
        result={'operation_id':row['operation_id'],'action':ACTION,'status':row['status'],
                'reason':request['reason'],'created_at':row['created_at'],'result':None,
                'can_confirm':False,'can_cancel':row['status']=='preparing',
                'retry_dispatch_allowed':False}
        try:
            result['result']=self.receipt(row)
        except (OSError,ValueError,TypeError,KeyError):
            result['receipt_error']='执行记录不可读或与原申请不匹配；请保留编号，不要重复申请'
            result['can_cancel']=False
            return result
        receipt=result['result']
        current=self.status()
        if receipt:
            if (row['status']=='preparing' and receipt['state']=='prepared'
                    and type(receipt.get('expires_at')) in (int,float) and receipt['expires_at']>time.time()
                    and receipt.get('can_confirm') is True and self.enabled() and current['execute_supported']
                    and current['write_gate']['state']=='open'):
                result['can_confirm']=True
            if receipt['state'] != 'prepared':
                result['can_cancel']=False
        # An expired root heartbeat never turns a stale "running" receipt into
        # a claim that the worker remains alive.
        result['observation_pending']=(Path(self.settings.maintenance_dir)/'inbox'/(row['operation_id']+'.observe.json')).exists()
        result['can_observe']=bool(receipt and receipt['state'] not in ('cancelled','expired','rejected','completed') and current['state']=='ok')
        result['worker_fresh']=current['state']=='ok'
        result['executor_message']=current['message']
        phase='cancel' if row['status']=='cancelled' else 'confirm' if row['status']=='queued' else 'prepare'
        result['dispatch_phase']=phase
        needs_dispatch=(receipt is None or phase=='confirm' and receipt['state']=='prepared'
                        or phase=='cancel' and receipt['state']!='cancelled')
        result['retry_dispatch_allowed']=needs_dispatch and not (Path(self.settings.maintenance_dir)/'inbox'/(row['operation_id']+'.'+phase+'.json')).exists()
        return result

    def detail(self, op):
        with self.db.connect() as c,c.cursor() as q:
            row=self.row(q,op)
        return self.detail_row(row)

    def history(self, cursor=''):
        before, before_id = 0, ''
        if cursor:
            match=re.fullmatch(r'([0-9]{1,12}):([a-f0-9]{32})',cursor)
            if not match:raise HTTPException(422,'维护历史游标不正确')
            before,before_id=int(match[1]),match[2]
        with self.db.connect() as c,c.cursor() as q:
            q.execute("SELECT operation_id,status,created_at,request_json FROM dnf_gm.operations WHERE action=%s AND (%s=0 OR created_at<%s OR (created_at=%s AND operation_id<%s)) ORDER BY created_at DESC,operation_id DESC LIMIT 31",(ACTION,before,before,before,before_id))
            rows=q.fetchall()
        page=rows[:30]
        return {'items':[{'operation_id':r['operation_id'],'status':r['status'],
                           'created_at':r['created_at'],'reason':json.loads(r['request_json'])['reason']} for r in page],
                'next_cursor':str(page[-1]['created_at'])+':'+page[-1]['operation_id'] if len(rows)>30 else None}

    def prepare(self, session, data):
        d=MaintenancePrepare(**data).model_dump();op=d['request_id'];reason=d['reason'].strip()
        if len(reason)<2:
            raise HTTPException(422,'请填写至少两个字的维护原因')
        # A duplicate response-loss lookup remains possible if the worker is now
        # unavailable or the admin disabled new requests.
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s',(op,));prior=q.fetchone()
        if prior:
            if prior['action']!=ACTION or prior['session_hash']!=session or self.request(prior)['reason']!=reason:
                raise HTTPException(409,'相同请求编号不能用于其他会话或不同内容')
            return self.detail_row(prior)
        self.ready()
        now=int(time.time())
        request={'operation_id':op,'reason':reason,'created_at':now,
                 'image_digest':self.settings.image_digest,'pvf_sha256':self.settings.pvf_sha256,
                 'program_sha256':self.settings.inventory_program_sha256}
        with self.db.connect() as c,c.cursor() as q:
            self.engines(q)
            try:
                q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,'{}','preparing',%s,%s)",
                          (op,session,request_hash(request),ACTION,canonical(request).decode(),now,now+300))
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','maintenance-prepare',%s,%s,%s)",
                          (op+':prepare',reason,canonical(request).decode(),json.dumps({'state':'preparing','operation_id':op})))
            except pymysql.IntegrityError:
                raise HTTPException(409,'请求编号已存在，请查询原申请') from None
            try:c.commit()
            except Exception:raise HTTPException(503,'维护申请保存结果待确认，请查询原编号；不会自动重发') from None
        return self.dispatch(op)

    def confirm(self, session, op, data):
        d=MaintenanceConfirm(**data).model_dump()
        if d['acknowledge_disconnect'] is not True:
            raise HTTPException(422,'请明确确认会断开当前游戏玩家')
        attempted=False
        try:
            with self.db.connect() as c,c.cursor() as q:
                self.engines(q);row=self.row(q,op,True)
                if row['session_hash']!=session:
                    raise HTTPException(404,'此维护预览不属于当前会话；可查询原结果')
                if row['idempotency_key'] and row['idempotency_key']!=d['idempotency_key']:
                    raise HTTPException(409,'该申请已使用其他确认编号')
                if row['status']=='preparing':
                    self.ready(True)
                    try:r=self.receipt(row)
                    except (OSError,ValueError,TypeError):r=None
                    if (not r or r['state']!='prepared' or r.get('fingerprint')!=d['fingerprint']
                            or r.get('can_confirm') is not True or type(r.get('expires_at')) not in (int,float)
                            or not time.time()<r['expires_at']):
                        raise HTTPException(409,'维护计划已过期、变化或不可确认，请核对原申请')
                    frozen={'fingerprint':d['fingerprint'],'acknowledge_disconnect':True}
                    q.execute("UPDATE dnf_gm.operations SET status='queued',idempotency_key=%s,preview_json=%s,result_json=%s WHERE operation_id=%s",(d['idempotency_key'],canonical(frozen).decode(),json.dumps({'state':'queued'}),op))
                    q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','maintenance-confirm',%s,%s,%s)",
                              (op,self.request(row)['reason'],canonical(frozen).decode(),json.dumps({'state':'queued','operation_id':op})))
                    attempted=True;c.commit()
                elif row['status']!='queued' or json.loads(row['preview_json']).get('fingerprint')!=d['fingerprint']:
                    raise HTTPException(409,'该申请状态或原确认内容不允许执行')
        except Exception as error:
            if attempted:raise HTTPException(503,'确认提交结果待核对，请查询原编号，禁止重新申请') from None
            if isinstance(error,pymysql.IntegrityError):raise HTTPException(409,'确认编号已用于其他操作') from None
            raise
        return self.dispatch(op)

    def cancel(self, op):
        # Safety cancellation stays available when the capability is switched off.
        with self.db.connect() as c,c.cursor() as q:
            self.engines(q);row=self.row(q,op,True)
            if row['status'] not in ('preparing','cancelled'):
                raise HTTPException(409,'申请已经确认，不能用取消预览代替退出后的恢复')
            if row['status']=='preparing':
                q.execute("UPDATE dnf_gm.operations SET status='cancelled' WHERE operation_id=%s",(op,))
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','maintenance-cancel',%s,%s,%s)",
                          (op+':cancel',self.request(row)['reason'],json.dumps({'operation_id':op}),json.dumps({'state':'cancelled'})))
                try:c.commit()
                except Exception:raise HTTPException(503,'取消保存结果待确认，请查询原编号') from None
        return self.dispatch(op)

    def dispatch(self, op):
        with self.db.connect() as c,c.cursor() as q:
            row=self.row(q,op)
        if row['status'] not in ('preparing','queued','cancelled'):
            raise HTTPException(409,'此状态不能投递维护请求')
        state=self.detail_row(row)
        if state.get('receipt_error'):
            raise HTTPException(409,state['receipt_error'])
        phase=state['dispatch_phase']
        receipt=state['result']
        if receipt and ((phase=='prepare') or (phase=='confirm' and receipt['state']!='prepared')
                        or (phase=='cancel' and receipt['state']=='cancelled')):
            return state
        # Disabling new control prevents an undispatched confirmation from being
        # issued, but never prevents cancelling or reading an old request.
        if phase!='cancel':self.require_enabled()
        request=self.request(row)
        fingerprint=json.loads(row['preview_json']).get('fingerprint') if phase=='confirm' else None
        value=packet(request,phase,fingerprint=fingerprint)
        self.enqueue(op,phase,value)
        return self.detail(op)

    def observe(self, op):
        # Read-only host reconciliation is available even when new maintenance
        # commands are disabled. It never confirms, resumes or replays a request.
        with self.db.connect() as c,c.cursor() as q:
            row=self.row(q,op)
        detail=self.detail_row(row)
        if detail.get('receipt_error') or not detail.get('can_observe'):
            raise HTTPException(409,'当前申请不能核对实际状态；请保留原编号并检查执行器状态')
        self.enqueue(op,'observe',packet(self.request(row),'observe'))
        return self.detail(op)

    def enqueue(self, op, phase, value):
        inbox=Path(self.settings.maintenance_dir)/'inbox';path=inbox/(op+'.'+phase+'.json')
        try:
            if os.path.lexists(path):
                if read_json(path,owner=os.getuid())!=value:raise Refused('maintenance_outbox_conflict')
            else:
                # Bound the queue scan even under a compromised application account.
                with os.scandir(inbox) as entries:
                    for index,_ in enumerate(entries):
                        if index>=95:raise Refused('maintenance_queue_full')
                atomic_json(path,value,mode=0o600)
        except (OSError,ValueError,TypeError):
            raise HTTPException(503,'原申请已保存，但投递尚未确认；保留编号，只重试投递原申请') from None
