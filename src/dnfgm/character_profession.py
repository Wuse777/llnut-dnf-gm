"""Maintenance-only same-base-job advancement and awakening, with linked skills."""
from contextlib import closing
import hashlib
import hmac
import json
import sqlite3
from typing import Literal
from fastapi import HTTPException
from pydantic import Field,StrictInt,model_validator
from .models import Model
from .character_levels import CharacterLevels,LABELS as LEVEL_LABELS
from .character_skill_reset import CharacterSkillReset,TREES,BACKUPS,SP,TP
from .inventory_fence import Refused
from .inventory_codec import digest
from .catalog import Catalog
from .service import dump
from . import profession_rules as rules

WRITABLE=('grow_type',*rules.STATS,'element_resist')
NOTE='同基础职业内调整转职／觉醒，按成长差额关联调整基础属性，并重建两套PvE技能及基础SP／TP。保留额外属性、任务／QP、装备、技能指令和付费权益；不是在线原生转职，不补发任务／活动奖励，也不伪造公会或网络事件。'


class ProfessionPreview(Model):
    action:Literal['char-profession']='char-profession'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_profession']='character_profession'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    first:StrictInt=Field(ge=0,le=5)
    second:StrictInt=Field(ge=0,le=2)
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_reason(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        return self


class CharacterProfession(CharacterLevels):
    actions=('char-profession',)
    preview_model=ProfessionPreview

    @staticmethod
    def archive(q,charac_no,lock=False):
        level=json.loads(CharacterLevels.archive(q,charac_no,lock));skills=json.loads(CharacterSkillReset.archive(q,charac_no,lock))
        if level['skills']!=skills['points']:raise HTTPException(409,'职业关联技能快照不一致，请刷新')
        return dump({'format':'qf1031-profession-1','info':level['info'],'stat':level['stat'],'skills':skills}).encode()

    def metadata(self,job):
        profiles,_,_,growth_sha=CharacterLevels.rules(self,job)
        skill,expert,sp,skill_sha=CharacterSkillReset.metadata(self,job)
        try:
            with closing(Catalog(self.settings).connect()) as c:
                meta=dict(c.execute('SELECT key,value FROM metadata'))
                if meta.get('profession_rules_version')!=rules.RULE_VERSION or meta.get('profession_rules_program_sha256')!=rules.PROGRAM_SHA:raise ValueError()
                row=c.execute('SELECT payload_json FROM profession_rules WHERE job=?',(job,)).fetchone()
                if not row or len(row[0])>20000:raise ValueError()
                display=json.loads(row[0]);options=display['choices']
                if not options or len(options)>18 or len({(o['first'],o['second']) for o in options})!=len(options):raise ValueError()
                if any((o['first'],o['second']) not in profiles for o in options):raise ValueError()
            binding=digest(dump({'display':display,'growth':growth_sha,'skills':skill_sha,'version':rules.RULE_VERSION}).encode())
            return profiles,skill,expert,sp,display,binding
        except (OSError,sqlite3.Error,KeyError,ValueError,TypeError):raise HTTPException(409,'匹配当前PVF／程序的转职／觉醒索引缺失或损坏') from None

    def reference(self,data,blob,binding):
        body=dump({'uid':data['uid'],'charac_no':data['charac_no'],'versions':self.versions(),'archive_sha256':digest(blob),'profession_rules_sha256':binding}).encode()
        return hmac.new(self.settings.secret.encode(),body,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);self.engines(q,{});blob=self.archive(q,charac_no)
        old=json.loads(blob);profiles,skill,expert,sp,display,binding=self.metadata(old['info']['job'])
        try:first,second=rules.decode_grow_type(old['info']['grow_type'])
        except ValueError as e:raise HTTPException(409,str(e)) from None
        current=next((o for o in display['choices'] if (o['first'],o['second'])==(first,second)),None)
        if current is None:raise HTTPException(409,'当前转职／觉醒组合不在已匹配索引中')
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；本页不会自动停止游戏。'}
        return {'target':target,'current':current,'base_name':display['base_name'],'job':old['info']['job'],'level':old['info']['lev'],'choices':display['choices'],
            'reference':self.reference({'uid':target['uid'],'charac_no':charac_no},blob,binding),'versions':self.versions(),
            'enabled':self.enabled('char-profession'),'maintenance':window,'note':NOTE}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid']);target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock);old=json.loads(before)
        profiles,skill,expert,sp,display,binding=self.metadata(old['info']['job'])
        if not hmac.compare_digest(self.reference(data,before,binding),data['reference']):raise HTTPException(409,'职业、属性、技能、副职业或索引已变化，请刷新重新预览')
        choice=next((o for o in display['choices'] if (o['first'],o['second'])==(data['first'],data['second'])),None)
        if choice is None:raise HTTPException(422,'目标职业阶段不在当前基础职业的PVF列表中')
        try:
            info=rules.plan(old['info'],data['first'],data['second'],profiles)
            skills=json.loads(dump(old['skills']));skills['points']['context']['grow_type']=info['grow_type']
            skills,skill_changes=CharacterSkillReset.proposal(skills,skill,expert,sp,[0,1],allow_unchanged=True)
        except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e)) from None
        new={'format':old['format'],'info':info,'stat':old['stat'],'skills':skills};after=dump(new).encode()
        current=next((o for o in display['choices'] if o['code']==(old['info']['grow_type']&127)),None)
        changes={k:{'label':LEVEL_LABELS.get(k,'转职／觉醒代码' if k=='grow_type' else k),'before':old['info'][k],'after':info[k]} for k in WRITABLE if old['info'][k]!=info[k]}
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],'before':old,'after':new,'changes':changes,
            'profession_before':current,'profession_after':choice,'skill_changes':skill_changes,'base_name':display['base_name'],
            'before_sha256':digest(before),'after_sha256':digest(after),'versions':self.versions(),'profession_rules_sha256':binding,'reason':data['reason'],'note':NOTE}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after);fields=[k for k in WRITABLE if old['info'][k]!=new['info'][k]]
        def stored(k,v):return bytes.fromhex(v) if k=='element_resist' else v
        q.execute('UPDATE taiwan_cain.charac_info SET '+','.join(f'`{k}`=%s' for k in fields)+' WHERE charac_no=%s AND '+
            ' AND '.join(f'`{k}`=%s' for k in fields),[*(stored(k,new['info'][k]) for k in fields),data['charac_no'],*(stored(k,old['info'][k]) for k in fields)])
        if q.rowcount!=1:raise HTTPException(409,'职业／成长条件更新未命中，事务未提交')
        values={};original={}
        for key in (*TREES,*BACKUPS):
            if old['skills']['blobs'][key]!=new['skills']['blobs'][key]:values[key]=bytes.fromhex(new['skills']['blobs'][key]);original[key]=bytes.fromhex(old['skills']['blobs'][key])
        for key in (*SP,*TP):
            if old['skills']['points'][key]!=new['skills']['points'][key]:values[key]=new['skills']['points'][key];original[key]=old['skills']['points'][key]
        if values:
            q.execute('UPDATE taiwan_cain_2nd.skill SET '+','.join(f'`{k}`=%s' for k in values)+' WHERE charac_no=%s AND '+
                ' AND '.join(f'`{k}`=%s' for k in values),[*values.values(),data['charac_no'],*original.values()])
            if q.rowcount!=1:raise HTTPException(409,'职业关联技能条件更新未命中，事务未提交')
        if self.archive(q,data['charac_no'],True)!=after:raise HTTPException(409,'职业／成长／技能回读不符，事务未提交')
