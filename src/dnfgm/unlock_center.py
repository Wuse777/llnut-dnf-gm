"""Bounded QF1031 unlock workflows. Expire requests, never remove item locks."""
import hashlib
import json
import time
import uuid
from fastapi import HTTPException
from . import equipment_unlock as locks
from .character_detail import decode_container
from .encoding import mysql_latin1_text

CONTAINERS={'equipment':'穿戴装备','backpack':'角色背包','warehouse':'角色仓库'}
NOTE='仅将选中申请设为到期；下次登录加载角色后由游戏处理，不代表装备已解锁'


def storage(q,cid,lock=False):
    suffix=' FOR UPDATE' if lock else ''
    q.execute('SELECT equipslot,inventory FROM taiwan_cain_2nd.inventory WHERE charac_no=%s'+suffix,(cid,));inventory=q.fetchone() or {}
    q.execute('SELECT cargo FROM taiwan_cain_2nd.charac_inven_expand WHERE charac_no=%s'+suffix,(cid,));warehouse=q.fetchone() or {}
    raw={'equipment':inventory.get('equipslot'),'backpack':inventory.get('inventory'),'warehouse':warehouse.get('cargo')}
    digest=hashlib.sha256()
    for name,blob in raw.items():
        digest.update(name.encode()+b'\0')
        digest.update(b'-' if blob is None else len(blob).to_bytes(4,'big')+blob)
    return {'fingerprint':digest.hexdigest(),'containers':{k:decode_container(v,k=='equipment') for k,v in raw.items()}}


def decorate(service,records,saved):
    candidates={}
    for name,container in saved['containers'].items():
        for item in container['items']:
            key=item.get('lock_key',0)
            if not 1<=key<=100:continue
            candidates.setdefault(key,[]).append({**item,'container':name,'container_name':CONTAINERS[name]})
    all_items=[i for group in candidates.values() for i in group]
    labels=service.catalog.read_labels([i['id'] for i in all_items])
    for item in all_items:
        meta=labels['items'].get(item['id'])
        item.update(name=meta['name'] if meta else f"未知物品 #{item['id']}",level=meta['level'] if meta else None)
    service.catalog.assets.decorate(service.settings.pvf_sha256 if labels['state']=='ok' else '',all_items)
    partial=any(c['state']!='ok' for c in saved['containers'].values())
    for r in records:
        matches=candidates.get(r['lock_key'],[])
        state='ambiguous' if len(matches)>1 else 'partial' if partial else 'matched' if matches else 'unmapped'
        r.update(mapping_state=state,item=matches[0] if len(matches)==1 else None,candidates=matches if len(matches)>1 else [])
    return records


def verify_engines(q):
    q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME IN ('charac_item_lock_info','inventory','charac_inven_expand')) OR (TABLE_SCHEMA='taiwan_login' AND TABLE_NAME='login_account_3') OR (TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME='charac_info')")
    rows=q.fetchall()
    if len(rows)!=5 or any(r['ENGINE']!='InnoDB' for r in rows):raise HTTPException(409,'解锁事务表引擎不满足')


def lock_accounts(q,targets):
    for uid in sorted({t['uid'] for t in targets}):
        q.execute('SELECT login_status FROM taiwan_login.login_account_3 WHERE m_id=%s FOR UPDATE',(uid,));row=q.fetchone()
        if not row or row['login_status']!=0:raise HTTPException(409,f'UID {uid} 在线或状态未知，请完全退出账号')


def prepare(service,q,data):
    blob=service.unlock_blob(q,data)
    try:_,selected=locks.expire(blob,data['lock_keys'],int(time.time()))
    except ValueError as e:raise HTTPException(409,str(e)) from None
    saved=storage(q,data['charac_no'])
    return {'lock_fingerprint':locks.fingerprint(blob),'inventory_fingerprint':saved['fingerprint'],
            'requests':decorate(service,selected,saved),'note':NOTE}


def apply(service,q,data,preview):
    verify_engines(q)
    blob=service.unlock_blob(q,data,lock=True)
    if locks.fingerprint(blob)!=preview['lock_fingerprint']:raise HTTPException(409,'锁定存档变化，请重新预览')
    saved=storage(q,data['charac_no'],lock=True)
    if saved['fingerprint']!=preview.get('inventory_fingerprint'):raise HTTPException(409,'装备、背包或仓库存档变化，请重新预览')
    try:updated,selected=locks.expire(blob,data['lock_keys'],int(time.time()))
    except ValueError as e:raise HTTPException(409,str(e)) from None
    q.execute('UPDATE taiwan_cain_2nd.charac_item_lock_info SET item_lock_info=%s WHERE charac_no=%s AND item_lock_info=%s',(updated,data['charac_no'],blob))
    if q.rowcount!=1:raise HTTPException(409,'锁定存档条件更新未命中')
    _,after=locks.decode(updated)
    return dict(charac_no=data['charac_no'],lock_keys=data['lock_keys'],requests_before=preview['requests'],
                requests_after=[r for r in after if r['lock_key'] in data['lock_keys']],before_fingerprint=preview['lock_fingerprint'],
                after_fingerprint=locks.fingerprint(updated),state='requests_expired_pending_game_load',note=NOTE)


class UnlockCenter:
    def __init__(self,service):self.service=service;self.db=service.db

    def list(self,text='',uid=0,after=0,state='pending'):
        from .service import character
        escaped=text.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        term='%'+escaped+'%'
        encoded='%'+mysql_latin1_text(text.strip().encode('utf-8')).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        number=int(text) if text.isascii() and text.isdigit() and len(text)<11 else 0
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT c.charac_no,c.m_id AS uid,c.charac_name,CAST(CONVERT(c.charac_name USING latin1) AS BINARY) AS client_name_bytes,c.delete_flag,a.accountname,l.item_lock_info,n.login_status FROM taiwan_cain_2nd.charac_item_lock_info l JOIN taiwan_cain.charac_info c ON c.charac_no=l.charac_no LEFT JOIN d_taiwan.accounts a ON a.UID=c.m_id LEFT JOIN taiwan_login.login_account_3 n ON n.m_id=c.m_id WHERE c.charac_no>%s AND (%s=0 OR c.m_id=%s) AND (%s=\'\' OR c.charac_no=%s OR c.m_id=%s OR a.accountname LIKE %s OR c.charac_name LIKE %s OR c.charac_name LIKE %s) ORDER BY c.charac_no LIMIT 26',(after,uid,uid,text,number,number,term,term,encoded))
            rows=q.fetchall()
        now=int(time.time());result=[]
        for row in rows[:25]:
            blob=row.pop('item_lock_info');row=character(row)
            try:
                _,records=locks.decode(blob)
                pending=sum(r['state']==2 and r['due_at']>now for r in records)
                expired=sum(r['state']==2 and r['due_at']<=now for r in records)
                row.update(state='ok',pending=pending,expired=expired,locked=sum(r['state']==1 for r in records),next_due_at=min((r['due_at'] for r in records if r['state']==2 and r['due_at']>now),default=None))
            except ValueError as e:row.update(state='unsupported',message=str(e),pending=None,expired=None,locked=None,next_due_at=None)
            if state=='all' or (state=='unsupported' and row['state']=='unsupported') or (state in ('pending','expired') and (row[state] or 0)>0):result.append(row)
        return {'items':result,'next_after':rows[24]['charac_no'] if len(rows)>25 else None,'scanned':min(len(rows),25),'collected_at':now,
                'note':'按保存锁定存档的角色分页；状态筛选在本页扫描后应用，空页仍可能有下一页。在线数据可能尚未保存。'}

    def preview(self,session_hash,data):
        from .service import dump
        targets=data['targets'];reason=data['reason'].strip()
        if not reason or not 1<=len(targets)<=20 or len({t['charac_no'] for t in targets})!=len(targets):raise HTTPException(422,'请选择1至20个不同角色，并填写原因')
        for t in targets:
            keys=t['lock_keys']
            if not keys or len(keys)!=len(set(keys)) or any(type(k) is not int or not 1<=k<=100 for k in keys):raise HTTPException(422,'申请编号必须有效且不重复')
        data={'action':'unlock-batch','reason':reason,'targets':sorted(targets,key=lambda t:(t['uid'],t['charac_no']))}
        with self.db.connect() as c,c.cursor() as q:
            previews=[]
            for t in data['targets']:
                request={'action':'equipment-unlock',**t,'reason':reason}
                a=self.service.target(q,request)
                previews.append({'target':a,**prepare(self.service,q,request)})
            p={'action':'unlock-batch','reason':reason,'targets':previews,'role_count':len(previews),'request_count':sum(len(t['lock_keys']) for t in targets),'note':NOTE,'atomic':True,'client_verified':False}
            op=uuid.uuid4().hex;now=int(time.time())
            q.execute('INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,\'preview\',%s,%s)',(op,session_hash,hashlib.sha256(dump({'request':data,'preview':p}).encode()).hexdigest(),'unlock-batch',dump(data),dump(p),now,now+300));c.commit()
        return {'operation_id':op,'preview':p,'expires_at':now+300,'write_enabled':'equipment-unlock' in self.service.settings.writes}

    def confirm(self,q,row,data,preview,key):
        from .service import dump
        verify_engines(q)
        for t,p in zip(data['targets'],preview['targets']):self.service.check_write(q,{'action':'equipment-unlock',**t},p)
        lock_accounts(q,data['targets'])
        q.execute('UPDATE dnf_gm.operations SET idempotency_key=%s WHERE operation_id=%s',(key,row['operation_id']))
        results=[]
        for t,p in zip(data['targets'],preview['targets']):
            request={'action':'equipment-unlock',**t,'reason':data['reason']}
            a=self.service.target(q,request,lock=True)
            if a['accountname']!=p['target']['accountname'] or a['character']['charac_name']!=p['target']['character']['charac_name']:raise HTTPException(409,'目标身份变化，重新预览')
            result={'uid':t['uid'],'action':'equipment-unlock','operation_id':row['operation_id'],'client_verified':False,**apply(self.service,q,request,p)}
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','equipment-unlock',%s,%s,%s,%s)",(row['operation_id']+':'+str(t['charac_no']),t['uid'],data['reason'],dump(request),dump(result)))
            results.append(result)
        result={'operation_id':row['operation_id'],'action':'unlock-batch','targets':results,'atomic':True,'client_verified':False,'state':'requests_expired_pending_game_load','note':NOTE}
        q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','unlock-batch',NULL,%s,%s,%s)",(row['operation_id'],data['reason'],dump(data),dump(result)))
        q.execute("UPDATE dnf_gm.operations SET status='committed',result_json=%s WHERE operation_id=%s",(dump(result),row['operation_id']))
        return result
