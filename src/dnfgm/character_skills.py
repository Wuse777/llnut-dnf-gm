"""QF1031 PvE unspent SP/TP archive maintenance; not a learned-skill reset.

Native load/save SQL maps both SP trees and SFP (TP) columns. Learned skills,
commands, Lethe, used/requested points and fair-PvP trees are never modified.
"""
import hashlib
import hmac
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import Field, StrictInt, model_validator
from .models import Model
from .inventory_operations import InventoryOperations
from .inventory_fence import Refused
from .inventory_codec import digest
from .service import one, dump
from .character_progression import PROGRAM_SHA

POINTS=('remain_sp','remain_sp_2nd','remain_sfp_1st','remain_sfp_2nd')
LIMITS={key:1073741823 if key.startswith('remain_sp') else 2147483647 for key in POINTS}
SCALARS=(*POINTS,'sp_garbage','used_sp','lethe_flag','lethe_flag_2nd','script_version')
BLOBS=('skill_slot','request_sp','skill_slot_2nd','request_sp_2nd','skill_slot_lethe','skill_slot_lethe_2nd','skill_command')
CONTEXT=('lev','job','grow_type','skill_tree_index')


class SkillPointsPreview(Model):
    action:Literal['char-sp-tp']='char-sp-tp'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_skill_points']='character_skill_points'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    changes:dict[str,StrictInt]=Field(min_length=1,max_length=4)
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_changes(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        if set(self.changes)-set(POINTS):raise ValueError('仅支持两套PvE技能树的剩余SP／TP')
        if any(not 0<=v<=LIMITS[k] for k,v in self.changes.items()):
            raise ValueError('剩余SP须为0至1073741823，TP须为0至2147483647整数')
        return self


class CharacterSkills(InventoryOperations):
    actions=('char-sp-tp',)
    preview_model=SkillPointsPreview

    def engines(self,q,data):
        if self.settings.inventory_program_sha256!=PROGRAM_SHA:
            raise HTTPException(409,'技能存档尚未适配当前原生程序版本')
        q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','inventory_operations','inventory_snapshots')) OR (TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME='charac_info') OR (TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME='skill')")
        rows=q.fetchall();expected={('dnf_gm',n) for n in ('operations','audit','inventory_operations','inventory_snapshots')}|{('taiwan_cain','charac_info'),('taiwan_cain_2nd','skill')}
        if {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in rows}!=expected or any(r['ENGINE']!='InnoDB' for r in rows):
            raise HTTPException(409,'技能维护事务表必须完整且为InnoDB')

    @staticmethod
    def archive(q,charac_no,lock=False):
        suffix=' FOR UPDATE' if lock else ''
        info=one(q,'SELECT '+','.join(CONTEXT)+' FROM taiwan_cain.charac_info WHERE charac_no=%s'+suffix,(charac_no,))
        fields=','.join(SCALARS)+','+','.join(f'SHA2(`{k}`,256) AS `{k}_sha256`,OCTET_LENGTH(`{k}`) AS `{k}_bytes`' for k in BLOBS)
        row=one(q,'SELECT '+fields+' FROM taiwan_cain_2nd.skill WHERE charac_no=%s'+suffix,(charac_no,))
        if not info or not row:raise HTTPException(409,'角色技能存档不存在；请先由游戏创建角色存档，本页不会补造技能记录')
        if any(type(info[k]) is not int for k in CONTEXT) or any(type(row[k]) is not int for k in SCALARS):
            raise HTTPException(409,'技能存档字段类型异常')
        return dump({'format':'qf1031-skill-points-1','context':info,**row}).encode()

    def reference(self,data,blob):
        body=dump({'uid':data['uid'],'charac_no':data['charac_no'],'container':'character_skill_points','versions':self.versions(),'sha256':digest(blob)}).encode()
        return hmac.new(self.settings.secret.encode(),body,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);data={'uid':target['uid'],'charac_no':charac_no}
            self.engines(q,data);blob=self.archive(q,charac_no)
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；本页不会自动停止游戏。'}
        return {'target':target,'archive':json.loads(blob),'reference':self.reference(data,blob),'versions':self.versions(),
            'limits':LIMITS,'enabled':self.enabled('char-sp-tp'),'maintenance':window,
            'note':'只调整两套PvE技能树的未使用SP／TP，TP对应原生SFP字段。保留已学技能、已用点数、指令、洗点与公平决斗存档；不是技能重置或在线热更新。'}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid'])
        target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock)
        if not hmac.compare_digest(self.reference(data,before),data['reference']):
            raise HTTPException(409,'技能、点数、角色职业或版本已变化，请刷新并重新预览')
        old=json.loads(before);new={**old,**data['changes']}
        changes={k:{'before':old[k],'after':v} for k,v in data['changes'].items() if old[k]!=v}
        if not changes:raise HTTPException(422,'剩余SP／TP没有变化，无需提交')
        after=dump(new).encode()
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],
            'before':old,'after':new,'changes':changes,'before_sha256':digest(before),'after_sha256':digest(after),
            'versions':self.versions(),'reason':data['reason'],
            'note':'仅设置剩余技能点，不退还已学技能点、不修改技能等级。结束维护后由游戏加载；不等同于客户端效果已验证。'}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after)
        # Fixed identifiers only. Locked full-archive revalidation also covers the
        # learned-skill fingerprints, active tree and profession before this write.
        q.execute('UPDATE taiwan_cain_2nd.skill SET '+','.join(f'`{k}`=%s' for k in POINTS)+
            ' WHERE charac_no=%s AND '+' AND '.join(f'`{k}`=%s' for k in POINTS),
            [*(new[k] for k in POINTS),data['charac_no'],*(old[k] for k in POINTS)])
        if q.rowcount!=1:raise HTTPException(409,'技能点条件更新未命中，事务未提交')
        if self.archive(q,data['charac_no'],True)!=after:raise HTTPException(409,'技能存档与预期不一致，事务未提交')
