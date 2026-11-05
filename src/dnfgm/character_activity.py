"""Bounded player audit traversal; never labels another character's writes as this one."""
import json
from fastapi import HTTPException
from .ordinary_reconcile import public_audit
from .service import one,character


def references(row):
    ids=set()
    for key in ('request_json','result_json'):
        try:value=json.loads(row[key] or '{}')
        except (TypeError,ValueError):continue
        if not isinstance(value,dict):continue
        candidates=[value]
        for name in ('targets','characters'):
            if isinstance(value.get(name),list):candidates.extend(value[name])
        target=value.get('target')
        if isinstance(target,dict):candidates.extend([target,target.get('character')])
        for item in candidates:
            if isinstance(item,dict) and type(item.get('charac_no')) is int and item['charac_no']>0:ids.add(item['charac_no'])
    return ids


def activity(db,charac_no,before=0,include_account=True):
    with db.connect() as c,c.cursor() as q:
        target=one(q,'SELECT m_id AS uid,charac_no,charac_name,delete_flag,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes FROM taiwan_cain.charac_info WHERE charac_no=%s',(charac_no,))
        if not target:raise HTTPException(404,'角色不存在')
        target=character(target)
        where='target_uid=%s';args=[target['uid']]
        if before:where+=' AND id<%s';args.append(before)
        # Fixed scan budget, target_uid index; sparse matches retain a cursor.
        q.execute('SELECT id,operation_id,actor,action,target_uid,reason,request_json,result_json,created_at FROM dnf_gm.audit WHERE '+where+' ORDER BY id DESC LIMIT 101',args)
        rows=q.fetchall()
    items=[];last=None;scanned=0
    for row in rows[:100]:
        last=row['id'];scanned+=1;ids=references(row)
        if charac_no in ids:scope='character'
        elif not ids and include_account:scope='account'
        else:continue
        items.append({**public_audit(row),'scope':scope})
        if len(items)==20:break
    more=scanned<len(rows)
    return {'target':target,'items':items,'scanned':scanned,'next_before':last if more else None,
            'note':'角色记录按明确角色编号关联；账号记录未绑定具体角色。每次最多检查100条账号记录，空页也可能有后续记录。'}
