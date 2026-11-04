"""Authenticated cleanup outbox: audit first, fixed signed requests second."""
from pathlib import Path
import hashlib
import json
import os
import time
import uuid
import pymysql
from fastapi import HTTPException
from .catalog import snapshot
from .release_files import NAME, Refused, canonical, read_json, atomic_json

ROOT_UID=0
ACTION='cleanup-release'


class ReleaseCleanup:
    def __init__(self,db,settings):self.db,self.settings=db,settings

    def enabled(self):
        if not self.settings.cleanup_enabled:raise HTTPException(403,'旧GM产物清理尚未由维护人员启用')

    def candidates(self):
        if not self.settings.cleanup_enabled:
            return {'state':'disabled','items':[],'enabled':False,'message':'受控清理未启用；不影响只读运维诊断。'}
        try:
            d=read_json(self.settings.cleanup_manifest,owner=ROOT_UID)
            if not isinstance(d,dict) or d.get('state')!='ok' or not 0<=time.time()-d['collected_at']<90:raise Refused('stale')
            if not isinstance(d.get('items'),list) or len(d['items'])>100:raise Refused('invalid')
            # Tickets are passed only via frozen server-side previews, not browser inputs.
            return {'state':'ok','enabled':True,'collected_at':d['collected_at'],'note':d.get('note',''),
                    'items':[{'name':r['name'],'eligible':r.get('eligible') is True,
                              'reason':r.get('reason'), 'allocated_bytes':r.get('descriptor',{}).get('allocated_bytes'),
                              'entries':r.get('descriptor',{}).get('entries')} for r in d['items']]}
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            return {'state':'unavailable','items':[],'enabled':True,'message':'清理清单不可用或已过期；检查专用执行器，不依据旧目录列表删除。'}

    def readiness(self):
        self.enabled();live=snapshot(self.settings)
        if not live.get('fresh') or not live.get('core_ok') or live.get('mem_available_mib',0)<256 or live.get('swap_free_mib',0)<1536:
            raise HTTPException(409,'监控或资源状态未就绪，暂不发起清理')

    def preview(self,session_hash,names,reason):
        self.readiness()
        if not reason.strip() or not 1<=len(names)<=5 or len(names)!=len(set(names)) or any(not NAME.fullmatch(n) for n in names):raise HTTPException(422,'选择1至5个不同旧版本并填写原因')
        if self.candidates()['state']!='ok':raise HTTPException(409,'签名清理清单已失效，请刷新')
        try:
            source=read_json(self.settings.cleanup_manifest,owner=ROOT_UID)
            if source.get('state')!='ok' or not 0<=time.time()-source['collected_at']<90:raise Refused('stale')
            by_name={r['name']:r for r in source['items']}
            selected=[by_name[name] for name in sorted(names)]
            if any(r.get('eligible') is not True for r in selected):raise Refused('protected')
            frozen=[{'descriptor':r['descriptor'],'ticket':r['ticket']} for r in selected]
            expires=min(int(time.time())+300,*(r['descriptor']['expires_at'] for r in selected))
            if expires<time.time()+15:raise Refused('expiring')
        except (OSError,ValueError,KeyError,TypeError,AttributeError):raise HTTPException(409,'部分版本受保护、已变化或票据即将过期，请刷新清单') from None
        request={'action':ACTION,'items':frozen,'reason':reason.strip()}
        preview={'action':ACTION,'items':[{'name':r['name'],'allocated_bytes':r['descriptor']['allocated_bytes'],'entries':r['descriptor']['entries']} for r in selected],
                 'reason':reason.strip(),'atomic':False,'note':'仅删除所选旧GM产物。多目录不是原子事务；失败可能部分完成。占用是估算，不保证等量释放；不删除当前/回滚、最新两个版本、游戏、备份或日志。'}
        op=uuid.uuid4().hex
        with self.db.connect() as c,c.cursor() as q:
            q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,'preview',%s,%s)",
                      (op,session_hash,hashlib.sha256(canonical({'request':request,'preview':preview})).hexdigest(),ACTION,canonical(request).decode(),canonical(preview).decode(),int(time.time()),expires));c.commit()
        return {'operation_id':op,'preview':preview,'expires_at':expires}

    def row(self,q,op,lock=False):
        q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s'+(' FOR UPDATE' if lock else ''),(op,));r=q.fetchone()
        if not r or r['action']!=ACTION:raise HTTPException(404,'清理操作不存在')
        return r

    def request(self,r):
        d=json.loads(r['request_json'])
        return {'operation_id':r['operation_id'],'items':d['items']}

    def detail(self,op):
        with self.db.connect() as c,c.cursor() as q:r=self.row(q,op)
        result={'operation_id':op,'action':ACTION,'status':r['status'],'preview':json.loads(r['preview_json']),
                'expires_at':r['expires_at'],'result':None,'dispatch_present':False,'retry_dispatch_allowed':False}
        if r['status']=='queued':
            path=Path(self.settings.cleanup_dir)/'results'/(op+'.json')
            try:
                receipt=read_json(path,owner=ROOT_UID)
                if not isinstance(receipt,dict) or receipt.get('operation_id')!=op or receipt.get('state') not in ('completed','rejected','executing','needs_review'):raise Refused('receipt_mismatch')
                if receipt.get('request_sha256') and receipt['request_sha256']!=hashlib.sha256(canonical(self.request(r))).hexdigest():raise Refused('receipt_mismatch')
                result['result']=receipt
            except FileNotFoundError:
                result['dispatch_present']=(Path(self.settings.cleanup_dir)/'inbox'/(op+'.json')).exists()
                result['retry_dispatch_allowed']=not result['dispatch_present']
            except (OSError,ValueError,TypeError):result['receipt_error']='结果文件不可读或不匹配；不要重复新建清理任务'
        return result

    def dispatch(self,op):
        self.enabled()
        with self.db.connect() as c,c.cursor() as q:r=self.row(q,op)
        if r['status']!='queued':raise HTTPException(409,'只有已审计入队的原操作可以投递')
        state=self.detail(op)
        if state['result'] is not None or state.get('receipt_error'):return state
        request=self.request(r);inbox=Path(self.settings.cleanup_dir)/'inbox';path=inbox/(op+'.json')
        try:
            if path.exists():
                if read_json(path,owner=os.getuid())!=request:raise Refused('conflicting_request')
            else:
                if sum(1 for _ in inbox.iterdir())>=32:raise Refused('queue_full')
                atomic_json(path,request,0o600)
        except (OSError,ValueError,TypeError):raise HTTPException(503,'原操作已审计入队，但投递未确认；保留编号查询，只重试投递这个编号') from None
        return self.detail(op)

    def confirm(self,session_hash,op,key):
        self.enabled();commit_attempted=False
        try:
            with self.db.connect() as c,c.cursor() as q:
                r=self.row(q,op,True)
                if r['session_hash']!=session_hash:raise HTTPException(404,'此预览不属于当前会话')
                if r['idempotency_key'] and r['idempotency_key']!=key:raise HTTPException(409,'操作已使用不同幂等键')
                if r['status']=='preview':
                    self.readiness()
                    if r['expires_at']<time.time():raise HTTPException(409,'清理预览已过期，请重新预览')
                    d=json.loads(r['request_json']);p=json.loads(r['preview_json'])
                    if hashlib.sha256(canonical({'request':d,'preview':p})).hexdigest()!=r['fingerprint']:raise HTTPException(409,'预览指纹不匹配')
                    q.execute("UPDATE dnf_gm.operations SET status='queued',idempotency_key=%s,result_json=%s WHERE operation_id=%s",(key,json.dumps({'state':'queued','note':'审计已入队，不代表目录已经删除'}),op))
                    # Store signed frozen selections in the operation, only public selection in audit.
                    q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner',%s,%s,%s,%s)",(op,ACTION,d['reason'],canonical(p).decode(),json.dumps({'state':'queued','operation_id':op})))
                    commit_attempted=True;c.commit()
                elif r['status']!='queued':raise HTTPException(409,'操作状态不允许确认')
        except Exception as error:
            if not commit_attempted:
                try:
                    with self.db.connect() as c,c.cursor() as q:
                        q.execute('INSERT INTO dnf_gm.failures(operation_id,error_type) VALUES(%s,%s)',(op,type(error).__name__));c.commit()
                except Exception:
                    pass
            if commit_attempted:raise HTTPException(503,'入队提交结果待确认；查询原编号，不要重新创建任务') from None
            if isinstance(error,pymysql.IntegrityError):raise HTTPException(409,'幂等键已被其他操作使用') from None
            raise
        return self.dispatch(op)

    def cancel_preview(self,op):
        # Row lock serializes cancellation with any in-flight confirm. A GET of
        # 'preview' alone is not proof a lost confirmation cannot still commit.
        with self.db.connect() as c,c.cursor() as q:
            r=self.row(q,op,True)
            if r['status'] not in ('preview','cancelled'):raise HTTPException(409,'原操作已经入队，不能取消或重新建立任务，请查询原结果')
            if r['status']=='preview':
                p=json.loads(r['preview_json'])
                q.execute("UPDATE dnf_gm.operations SET status='cancelled',result_json=%s WHERE operation_id=%s",(json.dumps({'state':'cancelled'}),op))
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner',%s,%s,%s,%s)",(op,ACTION,p['reason'],canonical(p).decode(),json.dumps({'state':'cancelled'})))
                try:c.commit()
                except Exception:raise HTTPException(503,'取消结果待确认，请继续查询原编号') from None
        return self.detail(op)
