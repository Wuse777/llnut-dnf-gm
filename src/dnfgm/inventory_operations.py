"""Maintenance-fenced, same-connection inventory edits and immutable snapshots.

No online/offline inference, generic SQL, shell or implicit game service control.
The only accepted containers map to fixed, column-scoped game archive updates.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import time
import uuid

import pymysql
from fastapi import HTTPException
from . import inventory_codec as codec
from .inventory_fence import MaintenanceFence, Refused
from .models import InventoryPreview
from .equipment_metadata import enchantment
from .character_detail import EQUIP_SLOTS, TYPES
from .service import one, dump, character

ACTIONS=('item-edit','item-reclaim','item-restore')
CONTAINERS={
    'inventory':('taiwan_cain_2nd','inventory','charac_no','inventory'),
    'equipment':('taiwan_cain_2nd','inventory','charac_no','equipslot'),
    'warehouse':('taiwan_cain_2nd','charac_inven_expand','charac_no','cargo'),
    'account_warehouse':('taiwan_cain','account_cargo','m_id','cargo'),
}


class InventoryOperations:
    actions=ACTIONS
    preview_model=InventoryPreview
    def __init__(self,service,fence=None):
        self.service=service;self.db=service.db;self.settings=service.settings
        self.fence=fence or MaintenanceFence('/run/dnf-gm/maintenance',**self.versions())

    def versions(self):
        return dict(image_digest=self.settings.image_digest,pvf_sha256=self.settings.pvf_sha256,
                    program_sha256=self.settings.inventory_program_sha256)

    @staticmethod
    def target(q,charac_no,uid=None,lock=False):
        row=one(q,'SELECT m_id AS uid,charac_no,charac_name,delete_flag,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes FROM taiwan_cain.charac_info WHERE charac_no=%s'+(' FOR UPDATE' if lock else ''),(charac_no,))
        if not row:raise HTTPException(404,'角色不存在')
        if row['delete_flag'] or uid is not None and row['uid']!=uid:
            raise HTTPException(409,'角色已删除或不属于目标账号')
        row=character(row)
        account=one(q,'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s',(row['uid'],))
        if not account:raise HTTPException(409,'角色所属账号不存在')
        return {**account,'character':row}

    @staticmethod
    def coordinate(data):
        spec=CONTAINERS.get(data['container'])
        if spec is None:raise HTTPException(422,'未知存档容器')
        schema,table,key,column=spec
        return schema,table,key,column,data['uid'] if key=='m_id' else data['charac_no']

    def blob(self,q,data,lock=False):
        schema,table,key,col,value=self.coordinate(data)
        row=one(q,f'SELECT `{col}` AS archive FROM `{schema}`.`{table}` WHERE `{key}`=%s'+(' FOR UPDATE' if lock else ''),(value,))
        if not row:raise HTTPException(409,'容器没有存档记录，不能自动创建')
        codec.unpack(row['archive'])
        return row['archive']

    def reference(self,data,blob):
        return codec.identity(self.settings.secret,uid=data['uid'],charac_no=data['charac_no'],
            container=data['container'],slot=data['slot'],blob=blob,**self.versions())

    def enabled(self,action):
        return action in self.settings.writes and self.settings.write_approvals.get(action) is True

    def require_enabled(self,action,uid):
        if action not in self.actions or not self.enabled(action):raise HTTPException(403,'存档写入功能未激活')
        if self.settings.test_uids and uid not in self.settings.test_uids:
            raise HTTPException(403,'当前仅允许专用测试账号写入')
        v=self.versions()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',v['image_digest']) or any(not re.fullmatch(r'[a-f0-9]{64}',v[k]) for k in ('pvf_sha256','program_sha256')):
            raise HTTPException(409,'存档写入版本指纹未配置')

    @contextmanager
    def fenced(self):
        try:
            with self.fence.hold() as lease:yield lease
        except (Refused,OSError):
            raise HTTPException(409,'维护窗口不可用、过期或发生变化；请由维护者核对，不要重复提交') from None

    def engines(self,q,data):
        schema,table,_,_,_=self.coordinate(data)
        q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','inventory_operations','inventory_snapshots')) OR (TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME='charac_info') OR (TABLE_SCHEMA=%s AND TABLE_NAME=%s)",(schema,table))
        rows=q.fetchall()
        expected={('dnf_gm',n) for n in ('operations','audit','inventory_operations','inventory_snapshots')}|{('taiwan_cain','charac_info'),(schema,table)}
        if {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in rows}!=expected or any(r['ENGINE']!='InnoDB' for r in rows):
            raise HTTPException(409,'装备事务涉及的表未满足InnoDB基线')

    def item(self,charac_no,container,slot):
        try:
            with self.db.connect() as c,c.cursor() as q:
                target=self.target(q,charac_no)
                data=dict(uid=target['uid'],charac_no=charac_no,container=container,slot=slot)
                blob=self.blob(q,data)
            raw=codec.unpack(blob);codec.integer(slot,0,len(raw)//61-1)
            view=codec.slot_view(raw[slot*61:(slot+1)*61])
            labels=self.service.catalog.read_labels([view['id'],view.get('orb_id',0)])
            meta=labels['items'].get(view['id'])
            view.update(name=meta['name'] if meta else '空槽位' if view['empty'] else f"未知物品 #{view['id']}")
            if meta:view.update(meta)
            view.update(slot=slot,slot_label=EQUIP_SLOTS[slot] if container=='equipment' and slot<len(EQUIP_SLOTS) else f'槽位 {slot}',type_name=TYPES.get(view.get('type'),'未知类型'))
            if 'orb_id' in view:view['enchantment']=enchantment(labels['items'],view['orb_id'])
            self.service.catalog.assets.decorate(self.settings.pvf_sha256 if labels['state']=='ok' else '',[view])
            try:reference=self.reference(data,blob)
            except codec.InventoryFormatError:reference=None
            try:window={**self.fence.check(),'available':True}
            except (Refused,OSError):window={'available':False,'note':'没有可验证的显式维护窗口'}
            return {'target':target,**data,'item':view,'reference':reference,'versions':self.versions(),
                    'enabled_actions':[a for a in ACTIONS if self.enabled(a)],'maintenance':window,
                    'catalog_state':labels['state'],'client_verified':False,
                    'note':'存档快照；维护窗口通过才可修改。原始品级不是百分比，数据库成功不代表游戏效果。'}
        except codec.InventoryFormatError as error:raise HTTPException(409,str(error)) from None

    def make_change(self,q,data,before):
        if data['action']=='item-restore':
            saved=one(q,'SELECT * FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(data['source_operation_id'],))
            if not saved or any(saved[k]!=data[k] for k in ('uid','charac_no','container','slot')):
                raise HTTPException(409,'历史快照不存在或不属于该账号、角色和槽位')
            if any(saved[k]!=v for k,v in self.versions().items()):raise HTTPException(409,'历史快照版本不匹配')
            if codec.digest(saved['after_blob'])!=saved['after_sha256']:raise HTTPException(409,'历史after-image校验失败')
            after=codec.restore(before,expected_after_sha256=saved['after_sha256'],saved_before=saved['before_blob'],saved_before_sha256=saved['before_sha256'])
            start=data['slot']*61
            return after,{'restore_source':data['source_operation_id']},codec.slot_view(codec.unpack(before)[start:start+61]),codec.slot_view(codec.unpack(after)[start:start+61])
        result=codec.patch(before,data['slot'],data['changes'],reclaim=data['action']=='item-reclaim')
        return result.after_blob,result.changed_fields,result.before_slot,result.after_slot

    def build(self,q,data,lock=False):
        target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.blob(q,data,lock)
        if not hmac.compare_digest(self.reference(data,before),data['reference']):
            raise HTTPException(409,'容器或目标版本已变化，请重新读取物品并预览')
        after,changes,before_slot,after_slot=self.make_change(q,data,before)
        # Require matching index metadata; never apply PVF quantity caps. Metadata
        # gives names, not an assertion that an arbitrary enchant fits this item.
        ids=[before_slot['id'],after_slot['id'],before_slot.get('orb_id',0),after_slot.get('orb_id',0)]
        if data['changes'].get('orb_id'):ids.append(data['changes']['orb_id'])
        labels=self.service.catalog.read_labels(ids)
        if labels['state']!='ok':raise HTTPException(409,'物品索引PVF不匹配或不可读')
        if data['action']=='item-edit' and before_slot['id'] not in labels['items']:
            raise HTTPException(409,'物品尚未被当前索引识别，无法编辑属性')
        if data['changes'].get('orb_id') and data['changes']['orb_id'] not in labels['items']:
            raise HTTPException(409,'附魔ID未被当前索引识别')
        preview={'target':target,'container':data['container'],'slot':data['slot'],'action':data['action'],
            'before':before_slot,'after':after_slot,'changes':changes,'before_sha256':codec.digest(before),
            'after_sha256':codec.digest(after),'versions':self.versions(),'reason':data['reason'],
            'item_name':labels['items'].get(before_slot['id'],{}).get('name','未知物品 / 空槽位'),
            'item_info':labels['items'].get(before_slot['id'],{}),
            'before_item_info':labels['items'].get(before_slot['id'],{}),
            'after_item_info':labels['items'].get(after_slot['id'],{}),
            'before_enchantment':enchantment(labels['items'],before_slot.get('orb_id',0)),
            'after_enchantment':enchantment(labels['items'],after_slot.get('orb_id',0)),
            'note':'维护存档操作；原始品级不是百分比，附魔适用性及游戏效果未由数据库提交证明。'}
        return before,after,preview

    def preview(self,session_hash,data):
        data=self.preview_model(**data).model_dump();self.require_enabled(data['action'],data['uid'])
        op=uuid.uuid4().hex;now=int(time.time())
        try:
            with self.fenced() as lease,self.db.connect() as c,c.cursor() as q:
                self.engines(q,data)
                _,_,preview=self.build(q,data,lock=True)
                preview['maintenance_id']=lease.state['id']
                fingerprint=hashlib.sha256(dump({'request':data,'preview':preview}).encode()).hexdigest()
                q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,'preview',%s,%s)",(op,session_hash,fingerprint,data['action'],dump(data),dump(preview),now,now+300))
                q.execute('INSERT INTO dnf_gm.inventory_operations(operation_id,uid,charac_no,container,slot,created_at,maintenance_id) VALUES(%s,%s,%s,%s,%s,%s,%s)',(op,data['uid'],data['charac_no'],data['container'],data['slot'],now,lease.state['id']))
                lease.check();c.commit()
            return self.detail(op)
        except codec.InventoryFormatError as error:raise HTTPException(409,str(error)) from None

    @classmethod
    def row(cls,q,op,lock=False):
        row=one(q,'SELECT * FROM dnf_gm.operations WHERE operation_id=%s'+(' FOR UPDATE' if lock else ''),(op,))
        if not row or row['action'] not in cls.actions:raise HTTPException(404,'存档操作不存在')
        return row

    def expected_target(self,data,saved,after):
        return saved['target']

    def apply_archive(self,q,data,before,after):
        schema,table,colkey,column,value=self.coordinate(data)
        q.execute(f'UPDATE `{schema}`.`{table}` SET `{column}`=%s WHERE `{colkey}`=%s AND `{column}`=%s',(after,value,before))
        if q.rowcount!=1:raise HTTPException(409,'存档条件更新未命中，未修改目标')

    def confirm(self,session_hash,op,key):
        from .models import Confirm
        key=Confirm(idempotency_key=key).idempotency_key
        committing=False
        try:
            # Committed reads remain available after the maintenance window closes.
            with self.db.connect() as c,c.cursor() as q:
                previous=self.row(q,op)
                if previous['session_hash']!=session_hash:raise HTTPException(403,'预览属于另一会话')
                if previous['status'] in ('committed','executing','aborted'):
                    if previous['idempotency_key']!=key:raise HTTPException(409,'操作已绑定其他幂等键')
                    return self.public(previous)
            with self.fenced() as lease,self.db.connect() as c,c.cursor() as q:
                row=self.row(q,op,True)
                if row['session_hash']!=session_hash:raise HTTPException(403,'预览属于另一会话，请重新读取目标')
                old=one(q,'SELECT operation_id FROM dnf_gm.operations WHERE idempotency_key=%s',(key,))
                if old and old['operation_id']!=op:raise HTTPException(409,'幂等键已用于其他操作')
                if row['status'] in ('committed','executing','aborted'):
                    if row['idempotency_key']!=key:raise HTTPException(409,'操作已由其他幂等键完成')
                    return self.public(row)
                if row['status']!='preview' or row['expires_at']<=int(time.time()):raise HTTPException(409,'预览已取消或过期')
                data=json.loads(row['request_json']);saved=json.loads(row['preview_json'])
                self.require_enabled(data['action'],data['uid'])
                if saved['maintenance_id']!=lease.state['id']:raise HTTPException(409,'维护窗口已经改变，请重新预览')
                self.engines(q,data)
                before,after,preview=self.build(q,data,True)
                preview['maintenance_id']=lease.state['id']
                if preview!=saved:raise HTTPException(409,'目标、存档或版本发生变化，请重新预览')
                # Durable intent precedes the game transaction. Interrupted attempts
                # are NOT replayed. Root close resolves them under an exclusive fence.
                q.execute("UPDATE dnf_gm.operations SET status='executing',idempotency_key=%s WHERE operation_id=%s",(key,op))
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','item-intent',%s,%s,%s,%s)",
                    ('intent:'+op,data['uid'],data['reason'],dump(data),dump({'stage':'intent_only','maintenance_id':lease.state['id']})))
                lease.check();committing=True;c.commit();committing=False
                # A new transaction and current reads after the intent commit.
                row=self.row(q,op,True)
                if row['status']!='executing' or row['idempotency_key']!=key:raise HTTPException(409,'执行意向发生变化')
                self.engines(q,data)
                before,after,again=self.build(q,data,True)
                again['maintenance_id']=lease.state['id']
                if again!=saved:raise HTTPException(409,'意向建立后存档变化；本次未修改存档，请查询原编号')
                self.apply_archive(q,data,before,after)
                v=self.versions()
                q.execute('INSERT INTO dnf_gm.inventory_snapshots(operation_id,uid,charac_no,container,slot,source_operation_id,before_blob,after_blob,before_sha256,after_sha256,image_digest,pvf_sha256,program_sha256,maintenance_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (op,data['uid'],data['charac_no'],data['container'],data['slot'],data['source_operation_id'],before,after,codec.digest(before),codec.digest(after),v['image_digest'],v['pvf_sha256'],v['program_sha256'],lease.state['id']))
                result={'operation_id':op,'uid':data['uid'],'charac_no':data['charac_no'],'container':data['container'],
                    'slot':data['slot'],'action':data['action'],'before':preview['before'],'after':preview['after'],
                    'changes':preview['changes'],'snapshot_id':op,'source_operation_id':data['source_operation_id'],
                    'before_sha256':codec.digest(before),'after_sha256':codec.digest(after),'maintenance_id':lease.state['id'],
                    'client_verified':False,'state':'database_committed_game_verification_pending'}
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner',%s,%s,%s,%s,%s)",(op,data['action'],data['uid'],data['reason'],dump(data),dump(result)))
                q.execute("UPDATE dnf_gm.operations SET status='committed',idempotency_key=%s,result_json=%s WHERE operation_id=%s",(key,dump(result),op))
                self.require_enabled(data['action'],data['uid'])
                if self.target(q,data['charac_no'],data['uid'],True)!=self.expected_target(data,saved,after):
                    raise HTTPException(409,'目标身份在提交前发生变化')
                lease.check()
                committing=True;c.commit()
                row.update(status='committed',result_json=dump(result))
                return self.public(row)
        except Exception as error:
            if committing:raise HTTPException(503,'存档事务提交结果待确认，请只查询原操作编号，禁止自动重放') from None
            try:
                with self.db.connect() as c,c.cursor() as q:
                    q.execute('INSERT INTO dnf_gm.failures(operation_id,error_type) VALUES(%s,%s)',(op,type(error).__name__));c.commit()
            except Exception:pass
            if isinstance(error,codec.InventoryFormatError):raise HTTPException(409,str(error)) from None
            if isinstance(error,pymysql.IntegrityError):raise HTTPException(409,'幂等键或快照冲突，请查询原操作编号') from None
            raise

    @staticmethod
    def public(row):
        return {k:row[k] for k in ('operation_id','action','status','created_at','expires_at')}|{
            'request':json.loads(row['request_json']),'preview':json.loads(row['preview_json']),
            'result':json.loads(row['result_json']) if row.get('result_json') else None}

    def detail(self,op):
        with self.db.connect() as c,c.cursor() as q:return self.public(self.row(q,op))

    def history(self,uid=0,charac_no=0,page=1):
        terms=['o.action IN ('+','.join(['%s']*len(self.actions))+')'];args=list(self.actions)
        if uid:terms.append('i.uid=%s');args.append(uid)
        if charac_no:terms.append('i.charac_no=%s');args.append(charac_no)
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT o.* FROM dnf_gm.inventory_operations i JOIN dnf_gm.operations o ON o.operation_id=i.operation_id'+(' WHERE '+' AND '.join(terms) if terms else '')+' ORDER BY i.created_at DESC,i.operation_id DESC LIMIT 21 OFFSET %s',(*args,(page-1)*20))
            rows=q.fetchall()
        return {'items':[self.public(r) for r in rows[:20]],'has_more':len(rows)>20,'page':page}

    def cancel(self,op):
        with self.db.connect() as c,c.cursor() as q:
            row=self.row(q,op,True)
            if row['status']=='cancelled':return self.public(row)
            if row['status']!='preview':raise HTTPException(409,'已提交的存档操作不能取消')
            data=json.loads(row['request_json'])
            q.execute("UPDATE dnf_gm.operations SET status='cancelled' WHERE operation_id=%s",(op,))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','item-cancel',%s,%s,%s,%s)",('cancel:'+op,data['uid'],data['reason'],dump(data),dump({'status':'cancelled'})))
            c.commit();row['status']='cancelled';return self.public(row)
