"""QF1031 namespace-3 rename with canonical-name caches in one fenced transaction.

No live injection: all writers/caches must have exited under the existing
maintenance fence. Historical mail/audit/event payloads are deliberately kept.
"""
import copy
import hashlib
import hmac
import json
import unicodedata

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from typing import Literal

from .encoding import mysql_latin1_text
from .inventory_codec import digest
from .inventory_operations import InventoryOperations
from .inventory_fence import Refused
from .service import dump, one

from .character_name_schema import LINKS, SERVER_ID


def encoded_name(value):
    if not value or any(unicodedata.category(c)[0] in ('C','Z') for c in value):
        raise ValueError('角色名不能为空或包含空白、控制字符')
    raw=value.encode('utf-8')
    if len(raw)>20:raise ValueError('当前角色名字段最多20个UTF-8字节，中文通常每字3个字节')
    return mysql_latin1_text(raw)


class RenamePreview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['char-rename']='char-rename'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_name']='character_name'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    new_name:str=Field(min_length=1,max_length=20)
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def validate_name(self):
        encoded_name(self.new_name)
        if not self.reason.strip():raise ValueError('请填写操作原因')
        return self


class CharacterRename(InventoryOperations):
    actions=('char-rename',)
    preview_model=RenamePreview

    def engines(self,q,data):
        expected={('dnf_gm',n) for n in ('operations','audit','inventory_operations','inventory_snapshots')}
        expected.add(('taiwan_cain','charac_info'))
        expected.update((v[0],v[1]) for v in LINKS.values())
        pairs=sorted(expected)
        q.execute('SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA,TABLE_NAME) IN ('+','.join(['(%s,%s)']*len(pairs))+')',[x for pair in pairs for x in pair])
        rows=q.fetchall()
        if {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in rows}!=expected or any(r['ENGINE']!='InnoDB' for r in rows):
            raise HTTPException(409,'角色改名及关联表必须完整且为InnoDB，当前结构未就绪')

    def archive(self,q,uid,charac_no,lock=False):
        suffix=' FOR UPDATE' if lock else ''
        row=one(q,'SELECT charac_name FROM taiwan_cain.charac_info WHERE charac_no=%s AND m_id=%s'+suffix,(charac_no,uid))
        if not row:raise HTTPException(409,'角色归属已变化')
        links={}
        for label,(schema,table,column,keys,owner) in LINKS.items():
            character_key='master_no' if label=='guild_master' else 'charac_no'
            where=f'`{character_key}`=%s';args=[charac_no]
            if 'server_id' in keys:where+=' AND server_id=%s';args.append(SERVER_ID)
            fields=','.join('`'+k+'`' for k in (*keys,column))
            order=','.join('`'+k+'`' for k in keys)
            q.execute(f'SELECT {fields} FROM `{schema}`.`{table}` WHERE {where} ORDER BY {order} LIMIT 10001'+suffix,args)
            rows=q.fetchall()
            if len(rows)>10000:raise HTTPException(409,'关联记录过多，无法在轻量事务内完整处理；本次没有修改')
            if owner and any(r[owner]!=uid for r in rows):raise HTTPException(409,'关联记录的账号归属不一致，请先核对角色数据')
            links[label]=rows
        return dump({'format':'qf1031-character-name-1','server_id':SERVER_ID,'name':row['charac_name'],'links':links}).encode()

    def reference(self,data,blob):
        value=dump({'uid':data['uid'],'charac_no':data['charac_no'],'versions':self.versions(),'sha256':digest(blob)}).encode()
        return hmac.new(self.settings.secret.encode(),value,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);data={'uid':target['uid'],'charac_no':charac_no}
            self.engines(q,data);blob=self.archive(q,target['uid'],charac_no)
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；改名会随游戏组件恢复重新加载。'}
        archive=json.loads(blob)
        return {'target':target,'reference':self.reference(data,blob),'versions':self.versions(),
            'enabled':self.enabled('char-rename'),'maintenance':window,'server_id':SERVER_ID,
            'linked_counts':{k:len(v) for k,v in archive['links'].items()},
            'note':'同步角色名、公会成员／会长、推荐、代表角色及黑名单名称缓存；历史邮件、审计和活动文字保留原样。不是在线改名。'}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid'])
        target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['uid'],data['charac_no'],lock)
        if not hmac.compare_digest(self.reference(data,before),data['reference']):
            raise HTTPException(409,'角色名、关联记录或版本已变化，请刷新后重新预览')
        old=json.loads(before);new=encoded_name(data['new_name'])
        if old['name']==new:raise HTTPException(422,'角色名没有变化')
        # Use the database's real uniqueness collation, including deleted rows;
        # also exclude a second visible spelling stored in plain Unicode.
        collision=one(q,'SELECT charac_no FROM taiwan_cain.charac_info WHERE charac_no<>%s AND charac_name IN (%s,%s) LIMIT 1'+(' FOR UPDATE' if lock else ''),(data['charac_no'],new,data['new_name']))
        if collision:raise HTTPException(409,'该角色名已被占用（包括已删除角色保留的名称）')
        modified=copy.deepcopy(old);modified['name']=new
        for label,rows in modified['links'].items():
            column=LINKS[label][2]
            for r in rows:r[column]=new
        after=dump(modified).encode()
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],
            'before':{'name':target['character']['charac_name']},'after':{'name':data['new_name']},
            'changes':{'name':{'before':target['character']['charac_name'],'after':data['new_name']}},
            'linked_counts':{k:len(v) for k,v in old['links'].items()},'server_id':SERVER_ID,
            'before_sha256':digest(before),'after_sha256':digest(after),'versions':self.versions(),
            'reason':data['reason'],'note':'维护期间同事务修改关联名称；UID、角色编号、道具、金币及历史文字不变。'}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after)
        q.execute('UPDATE taiwan_cain.charac_info SET charac_name=%s WHERE charac_no=%s AND m_id=%s AND BINARY charac_name=BINARY %s',
                  (new['name'],data['charac_no'],data['uid'],old['name']))
        if q.rowcount!=1:raise HTTPException(409,'角色名条件更新未命中，事务未提交')
        for label,rows in old['links'].items():
            schema,table,column,keys,_=LINKS[label]
            for row in rows:
                if row[column]==new['name']:continue
                where=' AND '.join('`'+k+'`=%s' for k in keys)
                q.execute(f'UPDATE `{schema}`.`{table}` SET `{column}`=%s WHERE {where} AND BINARY `{column}`=BINARY %s',
                    [new['name'],*(row[k] for k in keys),row[column]])
                if q.rowcount!=1:raise HTTPException(409,'关联名称条件更新未命中，整笔改名未提交')

        if self.archive(q,data['uid'],data['charac_no'],True)!=after:
            raise HTTPException(409,'改名后的关联存档与预期不一致，事务未提交')

    def expected_target(self,data,saved,after):
        expected=copy.deepcopy(saved['target']);stored=json.loads(after)['name']
        expected['character'].update(charac_name=data['new_name'],stored_name=stored,
            encoding_state='ascii' if stored.isascii() else 'utf8_via_latin1_candidate')
        return expected
