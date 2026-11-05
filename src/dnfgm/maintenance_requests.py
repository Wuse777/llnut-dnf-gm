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
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .write_gate import GameplayWriteGate
from .catalog import snapshot
from .release_files import Refused, canonical, read_json, atomic_json

ACTION = 'maintenance'
CLOSE_ACTION = 'maint-close'
ROOT_UID = 0
ID = re.compile(r'^[a-f0-9]{32}$')
SHA = re.compile(r'^[a-f0-9]{64}$')
PHASES = ('prepare', 'confirm', 'cancel', 'observe', 'close', 'recover')
STATES = {'prepared','running','needs_review','game_drained','writers_stopped','cancelled','expired','rejected',
          'maintenance_open','resuming','completed'}
PUBLIC_FIELDS = {'state','fingerprint','created_at','expires_at','updated_at','revision','phase',
                 'games','events','command_may_have_run','error','maintenance_permit',
                 'can_confirm','can_cancel','can_replay','can_resume','client_verified',
                 'recovery_available','preview_expired','observation','window_requires_live_check','ordinary_outcomes'}


class MaintenancePrepare(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(min_length=2, max_length=200)


class MaintenanceConfirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledge_disconnect: StrictBool


class MaintenanceClose(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledge_restore: StrictBool


class MaintenanceRecover(MaintenanceClose):
    revision: StrictInt = Field(ge=1, le=2048)


def recovery_id(op, key):
    return hashlib.sha256(('maintenance-recover:'+op+':'+key).encode()).hexdigest()[:32]


def close_id(op):
    return hashlib.sha256(('maintenance-close:'+op).encode('ascii')).hexdigest()[:32]


def request_hash(request):
    return hashlib.sha256(canonical(request)).hexdigest()


def packet(request, phase, *, fingerprint=None, recovery=None):
    if phase not in PHASES:
        raise Refused('maintenance_phase_invalid')
    data = {'version':1, 'operation_id':request['operation_id'], 'phase':phase,
            'request':request, 'request_sha256':request_hash(request)}
    if phase in ('confirm','close','recover'):
        data['fingerprint'] = fingerprint
    if phase=='recover':data.update(recovery)
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
                result['message']=('完整执行器暂未通过监控、版本或资源核验；保留原申请，不会发送新命令。'
                    if doc.get('executor_protocol')==1 else
                    '可生成只读维护计划；完整退出、关窗与恢复执行器尚未接通，不能确认停服。')
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
                'retry_dispatch_allowed':False,'can_close':False,'close_requested':False}
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
        close = self.close_record(row)
        result['close_requested'] = close is not None
        if close: result['close_operation_id'] = close['operation_id']
        result['can_close'] = bool(not close and row['status']=='queued' and receipt
            and receipt['state']=='maintenance_open' and current['state']=='ok'
            and current['execute_supported']
            and receipt.get('fingerprint')==json.loads(row['preview_json']).get('fingerprint'))
        result['can_recover'] = bool(row['status']=='queued' and receipt
            and receipt.get('recovery_available') is True and current['state']=='ok'
            and current['execute_supported'] and receipt.get('fingerprint')==json.loads(row['preview_json']).get('fingerprint'))
        phase='close' if close else 'cancel' if row['status']=='cancelled' else 'confirm' if row['status']=='queued' else 'prepare'
        result['dispatch_phase']=phase
        needs_dispatch=(receipt is None or phase=='confirm' and receipt['state']=='prepared'
                        or phase=='cancel' and receipt['state']!='cancelled'
                        or phase=='close' and receipt['state']=='maintenance_open')
        if phase=='close': needs_dispatch=bool(receipt and receipt['state']=='maintenance_open' and current['state']=='ok' and current['execute_supported'])
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

    @staticmethod
    def close_payload(row):
        return {'operation_id':row['operation_id'], 'request_sha256':row['fingerprint'],
                'fingerprint':json.loads(row['preview_json']).get('fingerprint'),
                'acknowledge_restore':True}

    def close_record(self, row):
        """A parent link alone is not authority: verify its atomic child/audit."""
        linked=json.loads(row['result_json'] or '{}').get('close_operation_id')
        if not linked:return None
        expected=self.close_payload(row)
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s',(close_id(row['operation_id']),))
            child=q.fetchone()
            q.execute('SELECT action,request_json FROM dnf_gm.audit WHERE operation_id=%s',(linked,))
            audit=q.fetchone()
        if (linked!=close_id(row['operation_id']) or not child or not audit
                or child['action']!=CLOSE_ACTION or child['status']!='queued'
                or child['fingerprint']!=request_hash(expected) or not child['idempotency_key']
                or json.loads(child['request_json'])!=expected or audit['action']!='maintenance-close'
                or json.loads(audit['request_json'])!=expected):
            raise HTTPException(409,'结束维护申请绑定不一致，请查询原编号；不会投递恢复命令')
        return child

    def close(self, session, op, data):
        d=MaintenanceClose(**data).model_dump()
        if d['acknowledge_restore'] is not True:
            raise HTTPException(422,'请明确确认关闭装备维护窗口并恢复原游戏组件')
        attempted=False
        try:
            with self.db.connect() as c,c.cursor() as q:
                self.engines(q);row=self.row(q,op,True)
                # Sole owner may recover from a new authenticated session; the
                # original eight-hour preview session must not strand recovery.
                expected=self.close_payload(row);child_id=close_id(op)
                if row['status']!='queued' or expected['fingerprint']!=d['fingerprint']:
                    raise HTTPException(409,'原维护状态或计划指纹不匹配，不能结束维护')
                q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE',(child_id,))
                child=q.fetchone()
                if child:
                    if (child['action']!=CLOSE_ACTION or child['idempotency_key']!=d['idempotency_key']
                            or child['fingerprint']!=request_hash(expected)
                            or json.loads(child['request_json'])!=expected):
                        raise HTTPException(409,'结束维护已使用其他编号或内容，请查询原申请')
                else:
                    current=self.status()
                    try:r=self.receipt(row)
                    except (OSError,ValueError,TypeError,KeyError):r=None
                    if (not r or r['state']!='maintenance_open' or r.get('fingerprint')!=d['fingerprint']
                            or current['state']!='ok' or not current['execute_supported']):
                        raise HTTPException(409,'当前维护窗口或执行器不可核验，请查询原申请；不会恢复服务')
                    now=int(time.time());payload=canonical(expected).decode()
                    q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,idempotency_key,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,'{}','queued',%s,%s)",
                              (child_id,session,d['idempotency_key'],request_hash(expected),CLOSE_ACTION,payload,now,now))
                    q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','maintenance-close',%s,%s,%s)",
                              (child_id,self.request(row)['reason'],payload,json.dumps({'state':'queued','operation_id':op,'close_operation_id':child_id})))
                    result=json.loads(row['result_json'] or '{}');result['close_operation_id']=child_id
                    q.execute('UPDATE dnf_gm.operations SET result_json=%s WHERE operation_id=%s',(json.dumps(result),op))
                    attempted=True;c.commit()
        except Exception as error:
            if attempted:raise HTTPException(503,'结束维护保存结果待确认，请查询原申请编号；不会自动重发') from None
            if isinstance(error,pymysql.IntegrityError):raise HTTPException(409,'确认编号已用于其他操作') from None
            raise
        return self.dispatch(op)

    def recover(self, session, op, data):
        d=MaintenanceRecover(**data).model_dump()
        if d['acknowledge_restore'] is not True:
            raise HTTPException(422,'请确认核对中断状态并继续恢复原游戏组件')
        rid=recovery_id(op,d['idempotency_key']);attempted=False
        expected={'operation_id':op,'fingerprint':d['fingerprint'],'revision':d['revision'],
                  'acknowledge_restore':True}
        try:
            with self.db.connect() as c,c.cursor() as q:
                self.engines(q);row=self.row(q,op,True)
                q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE',(rid,));prior=q.fetchone()
                if prior:
                    if (prior['action']!='maint-recover' or prior['idempotency_key']!=d['idempotency_key']
                            or json.loads(prior['request_json'])!=expected):
                        raise HTTPException(409,'恢复确认编号已绑定其他内容，请查询原申请')
                else:
                    current=self.status();receipt=self.receipt(row)
                    if (row['status']!='queued' or current['state']!='ok' or not current['execute_supported']
                            or not receipt or not receipt.get('recovery_available')
                            or receipt.get('revision')!=d['revision'] or receipt.get('fingerprint')!=d['fingerprint']
                            or json.loads(row['preview_json']).get('fingerprint')!=d['fingerprint']):
                        raise HTTPException(409,'恢复状态已经变化或不可核验，请刷新原申请')
                    now=int(time.time());payload=canonical(expected).decode()
                    q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,idempotency_key,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,'maint-recover',%s,'{}','queued',%s,%s)",
                              (rid,session,d['idempotency_key'],request_hash(expected),payload,now,now))
                    q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','maintenance-recover',%s,%s,%s)",
                              (rid,self.request(row)['reason'],payload,json.dumps({'state':'queued','operation_id':op,'recovery_operation_id':rid})))
                    attempted=True;c.commit()
        except Exception as error:
            if attempted:raise HTTPException(503,'恢复确认保存结果待核对，请查询原申请；不会自动重发') from None
            if isinstance(error,pymysql.IntegrityError):raise HTTPException(409,'确认编号已用于其他操作') from None
            raise
        self.enqueue(op,'recover',packet(self.request(row),'recover',fingerprint=d['fingerprint'],
            recovery={'recovery_id':rid,'revision':d['revision']}))
        return {**self.detail(op),'recovery_operation_id':rid}

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
                        or (phase=='cancel' and receipt['state']=='cancelled')
                        or (phase=='close' and receipt['state']!='maintenance_open')):
            return state
        # Disabling new control prevents an undispatched confirmation from being
        # issued, but never prevents cancelling or reading an old request.
        if phase=='close':
            if not self.close_record(row) or not receipt or receipt['state']!='maintenance_open':
                raise HTTPException(409,'未找到可恢复的原维护申请')
            current=self.status()
            if current['state']!='ok' or not current['execute_supported']:
                raise HTTPException(409,'执行器状态不可核验，请保留原结束维护编号')
        elif phase!='cancel':self.require_enabled()
        request=self.request(row)
        fingerprint=json.loads(row['preview_json']).get('fingerprint') if phase in ('confirm','close') else None
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
