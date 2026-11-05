"""Learned PvE skill reset: version-bound defaults, points, snapshots and audit."""
from contextlib import closing
import hashlib
import hmac
import json
import sqlite3
from typing import Literal
from fastapi import HTTPException
from pydantic import Field,StrictInt,model_validator
from .models import Model
from .inventory_operations import InventoryOperations
from .character_skills import CharacterSkills
from .inventory_fence import Refused
from .inventory_codec import digest
from .catalog import Catalog
from .service import one,dump
from . import skill_rules as rules

TREES=('skill_slot','skill_slot_2nd')
BACKUPS=('skill_slot_lethe','skill_slot_lethe_2nd')
SP=('remain_sp','remain_sp_2nd')
TP=('remain_sfp_1st','remain_sfp_2nd')
FLAGS=('lethe_flag','lethe_flag_2nd')
NOTE='重置选中的PvE技能树：重建初始／转职／当前觉醒／副职业赠送技能，并重算SP／TP；选中树的有效临时洗点备份同步重置，保留付费权益标记、指令和公平决斗存档。不恢复过去人工赠送的额外点数，不是在线热更新。'


class SkillResetPreview(Model):
    action:Literal['char-skill-reset']='char-skill-reset'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_skill_reset']='character_skill_reset'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    trees:list[StrictInt]=Field(min_length=1,max_length=2)
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        if len(set(self.trees))!=len(self.trees) or set(self.trees)-{0,1}:raise ValueError('请选择不重复的PvE技能树一／二')
        self.trees=sorted(self.trees)
        return self


class CharacterSkillReset(CharacterSkills):
    actions=('char-skill-reset',)
    preview_model=SkillResetPreview

    def engines(self,q,data):
        super().engines(q,data)
        row=one(q,"SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME='charac_stat'")
        if not row or row['ENGINE']!='InnoDB':raise HTTPException(409,'副职业关联存档必须为InnoDB')

    @staticmethod
    def archive(q,charac_no,lock=False):
        suffix=' FOR UPDATE' if lock else ''
        points=json.loads(CharacterSkills.archive(q,charac_no,lock))
        expert=one(q,'SELECT i.expert_job AS kind,s.expert_job_exp AS experience FROM taiwan_cain.charac_info i JOIN taiwan_cain.charac_stat s ON s.charac_no=i.charac_no WHERE i.charac_no=%s'+suffix,(charac_no,))
        if not expert or any(type(n) is not int for n in expert.values()):raise HTTPException(409,'副职业关联存档缺失或类型异常')
        row=one(q,'SELECT '+','.join((*TREES,*BACKUPS))+' FROM taiwan_cain_2nd.skill WHERE charac_no=%s'+suffix,(charac_no,))
        for key,value in row.items():
            if not isinstance(value,bytes) or len(value)>1024:raise HTTPException(409,'技能存档长度或类型异常')
        return dump({'format':'qf1031-skill-reset-1','points':points,'expert':expert,'blobs':{k:v.hex() for k,v in row.items()}}).encode()

    def metadata(self,job):
        try:
            with closing(Catalog(self.settings).connect()) as c:
                meta=dict((r['key'],r['value']) for r in c.execute('SELECT key,value FROM metadata'))
                if (self.settings.inventory_program_sha256!=rules.PROGRAM_SHA or meta.get('pvf_sha256')!=self.settings.pvf_sha256 or
                    meta.get('skill_rules_version')!=rules.RULE_VERSION or meta.get('skill_rules_program_sha256')!=rules.PROGRAM_SHA):
                    raise ValueError('version mismatch')
                row=c.execute('SELECT payload_json FROM skill_rules WHERE job=?',(job,)).fetchone()
                if not row or len(row[0])>100000:raise ValueError('missing skill metadata')
                payload=json.loads(row[0]);expert=json.loads(meta['skill_expert_rules'])
                sp=dict(c.execute('SELECT level,points FROM progression_sp ORDER BY level LIMIT 201'))
                material={'payload':payload,'expert':expert,'sp':sp,'version':rules.RULE_VERSION}
                return payload,expert,sp,digest(dump(material).encode())
        except (OSError,sqlite3.Error,KeyError,ValueError,TypeError):
            raise HTTPException(409,'技能索引缺失、损坏或与当前PVF／程序不匹配，请重新生成并安装匹配索引') from None

    def reference(self,data,blob,rule_sha):
        body=dump({'uid':data['uid'],'charac_no':data['charac_no'],'container':'character_skill_reset','versions':self.versions(),
            'sha256':digest(blob),'skill_rules_sha256':rule_sha}).encode()
        return hmac.new(self.settings.secret.encode(),body,hashlib.sha256).hexdigest()

    @staticmethod
    def proposal(archive,payload,expert,sp,trees,*,allow_unchanged=False):
        points=archive['points'];context=points['context']
        defaults,skipped=rules.rebuild(payload,context['grow_type'],rules.expert_skills(archive['expert']['kind'],archive['expert']['experience'],context['lev'],expert))
        after=json.loads(dump(archive));new_blob=rules.pack(defaults);totals=rules.reset_points(context['lev'],sp);changes={}
        for tree in trees:
            key=TREES[tree];old=bytes.fromhex(archive['blobs'][key]);raw=rules.unpack(old)
            # Any active Lethe backup will otherwise restore old learned skills.
            fields=[key]
            if points[FLAGS[tree]]!=0:
                rules.unpack(bytes.fromhex(archive['blobs'][BACKUPS[tree]]));fields.append(BACKUPS[tree])
            for field in fields:
                after['blobs'][field]=new_blob.hex()
                after['points'][field+'_sha256']=digest(new_blob)
                after['points'][field+'_bytes']=len(new_blob)
            after['points'][SP[tree]]=totals['sp'];after['points'][TP[tree]]=totals['tp']
            changes[f'tree_{tree}']={'tree':tree,'before':{'skills':rules.learned(raw,payload['definitions']),'sp':points[SP[tree]],'tp':points[TP[tree]]},
                'after':{'skills':rules.learned(defaults,payload['definitions']),**totals},'temporary_backup_reset':len(fields)>1,'skipped_defaults':skipped}
        if after==archive and not allow_unchanged:raise ValueError('选中技能树已是重置后的状态，无需提交')
        return after,changes

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);self.engines(q,{});blob=self.archive(q,charac_no)
        archive=json.loads(blob);payload,expert,sp,sha=self.metadata(archive['points']['context']['job'])
        try:
            trees=[{'tree':i,'skills':rules.learned(rules.unpack(bytes.fromhex(archive['blobs'][key])),payload['definitions']),
                'sp':archive['points'][SP[i]],'tp':archive['points'][TP[i]],'temporary_reset_active':archive['points'][FLAGS[i]]!=0} for i,key in enumerate(TREES)]
            totals=rules.reset_points(archive['points']['context']['lev'],sp)
            default,skipped=rules.rebuild(payload,archive['points']['context']['grow_type'],rules.expert_skills(archive['expert']['kind'],archive['expert']['experience'],archive['points']['context']['lev'],expert))
        except (ValueError,KeyError,TypeError) as e:raise HTTPException(409,str(e)) from None
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；本页不会自动停止游戏。'}
        return {'target':target,'context':archive['points']['context'],'trees':trees,'reset_defaults':rules.learned(default,payload['definitions']),
            'reset_points':totals,'skipped_defaults':skipped,'reference':self.reference({'uid':target['uid'],'charac_no':charac_no},blob,sha),
            'versions':self.versions(),'skill_rules_sha256':sha,'enabled':self.enabled('char-skill-reset'),'maintenance':window,'note':NOTE}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid']);target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock);old=json.loads(before)
        payload,expert,sp,sha=self.metadata(old['points']['context']['job'])
        if not hmac.compare_digest(self.reference(data,before,sha),data['reference']):raise HTTPException(409,'技能、点数、职业、副职业或索引发生变化，请刷新重新预览')
        try:new,changes=self.proposal(old,payload,expert,sp,data['trees'])
        except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e)) from None
        after=dump(new).encode()
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],'before':old,'after':new,'changes':changes,
            'before_sha256':digest(before),'after_sha256':digest(after),'versions':self.versions(),'skill_rules_sha256':sha,'reason':data['reason'],'note':NOTE}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after);values={};original={}
        for field in (*TREES,*BACKUPS):
            if old['blobs'][field]!=new['blobs'][field]:values[field]=bytes.fromhex(new['blobs'][field]);original[field]=bytes.fromhex(old['blobs'][field])
        for field in (*SP,*TP):
            if old['points'][field]!=new['points'][field]:values[field]=new['points'][field];original[field]=old['points'][field]
        if not values:raise HTTPException(409,'技能重置没有存档变化')
        q.execute('UPDATE taiwan_cain_2nd.skill SET '+','.join(f'`{k}`=%s' for k in values)+' WHERE charac_no=%s AND '+
            ' AND '.join(f'`{k}`=%s' for k in values),[*values.values(),data['charac_no'],*original.values()])
        if q.rowcount!=1:raise HTTPException(409,'技能重置条件更新未命中，事务未提交')
        if self.archive(q,data['charac_no'],True)!=after:raise HTTPException(409,'技能重置关联存档回读不符，事务未提交')
