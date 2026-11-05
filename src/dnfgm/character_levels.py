"""Maintenance-only level/experience edits with linked growth and point updates."""
from contextlib import closing
import hashlib
import hmac
import json
import sqlite3
from typing import Literal
from fastapi import HTTPException
from pydantic import Field,StrictInt,model_validator
from .models import Model
from .catalog import Catalog
from .character_skills import CharacterSkills
from .inventory_operations import InventoryOperations
from .inventory_fence import Refused
from .inventory_codec import digest
from .service import one,dump
from .progression_rules import PROGRAM_SHA,RULE_VERSION,STATS,POINTS,TAGS,decode_grow_type,level_plan

INFO=('lev','exp','job','grow_type','skill_tree_index',*STATS)
WRITABLE=('lev','exp',*STATS,'element_resist')
LABELS={'lev':'等级','exp':'选角经验原值','saved_exp':'存档经验原值','maxHP':'基础生命存档','maxMP':'基础魔力存档',
 'phy_attack':'基础物攻','phy_defense':'基础物防','mag_attack':'基础魔攻','mag_defense':'基础魔防',
 'inven_weight':'背包负重存档','hp_regen':'生命恢复存档','mp_regen':'魔力恢复存档','move_speed':'移动速度存档',
 'attack_speed':'攻击速度存档','cast_speed':'施放速度存档','hit_recovery':'硬直恢复存档','jump':'跳跃存档','charac_weight':'角色重量存档',
 'element_resist':'火／水／暗／光抗性存档','remain_sp':'技能树一剩余SP','remain_sp_2nd':'技能树二剩余SP',
 'remain_sfp_1st':'技能树一剩余TP','remain_sfp_2nd':'技能树二剩余TP'}
NOTE='离线存档维护：同步两处经验、等级成长差额和两套剩余技能点，保留已学技能、任务与额外属性。不是在线升级，不模拟升级活动奖励、任务完成或原生通知。'


class LevelPreview(Model):
    action:Literal['char-level']='char-level'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_level']='character_level'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    level:StrictInt=Field(ge=1,le=127)
    experience:StrictInt|None=Field(default=None,ge=0,le=4294967295)
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_reason(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        return self


class CharacterLevels(InventoryOperations):
    actions=('char-level',)
    preview_model=LevelPreview

    def engines(self,q,data):
        if self.settings.inventory_program_sha256!=PROGRAM_SHA:raise HTTPException(409,'等级维护未适配当前原生程序')
        expected={('dnf_gm',n) for n in ('operations','audit','inventory_operations','inventory_snapshots')}|{
            ('taiwan_cain','charac_info'),('taiwan_cain','charac_stat'),('taiwan_cain_2nd','skill')}
        q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','inventory_operations','inventory_snapshots')) OR (TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME IN ('charac_info','charac_stat')) OR (TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME='skill')")
        rows=q.fetchall()
        if {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in rows}!=expected or any(r['ENGINE']!='InnoDB' for r in rows):
            raise HTTPException(409,'等级维护关联表须完整且均为InnoDB')

    @staticmethod
    def archive(q,charac_no,lock=False):
        suffix=' FOR UPDATE' if lock else ''
        info=one(q,'SELECT '+','.join(f'`{k}`' for k in INFO)+',HEX(element_resist) AS element_resist,SHA2(spec_property,256) AS spec_property_sha256 FROM taiwan_cain.charac_info WHERE charac_no=%s'+suffix,(charac_no,))
        stat=one(q,'SELECT exp FROM taiwan_cain.charac_stat WHERE charac_no=%s'+suffix,(charac_no,))
        skills=json.loads(CharacterSkills.archive(q,charac_no,lock))
        if not info or not stat:raise HTTPException(409,'等级关联存档缺失；本页不补造存档')
        if any(type(info[k]) is not int for k in INFO) or type(stat['exp']) is not int:raise HTTPException(409,'等级存档字段类型异常')
        info['element_resist']=info['element_resist'].lower()
        return dump({'format':'qf1031-level-1','info':info,'stat':stat,'skills':skills}).encode()

    def rules(self,job):
        try:
            with closing(Catalog(self.settings).connect()) as c:
                meta=dict((r['key'],r['value']) for r in c.execute('SELECT key,value FROM metadata'))
                if (meta.get('pvf_sha256')!=self.settings.pvf_sha256 or meta.get('progression_growth_version')!=RULE_VERSION or
                    meta.get('progression_growth_program_sha256')!=self.settings.inventory_program_sha256 or self.settings.inventory_program_sha256!=PROGRAM_SHA):
                    raise ValueError('index mismatch')
                profiles={(r['first_growth'],r['second_growth']):json.loads(r['values_json']) for r in c.execute('SELECT * FROM progression_growth WHERE job=? ORDER BY first_growth,second_growth',(job,))}
                thresholds={r['level']:r['total_exp'] for r in c.execute('SELECT level,total_exp FROM progression_thresholds ORDER BY level')}
                sp={r['level']:r['points'] for r in c.execute('SELECT level,points FROM progression_sp ORDER BY level')}
            if not profiles or len(profiles)>19 or not thresholds or not sp:raise ValueError('missing rules')
            if any(set(v)!=set(TAGS.values()) or any(type(n) is not int for n in v.values()) for v in profiles.values()):raise ValueError('invalid growth')
            material={'version':RULE_VERSION,'job':job,'profiles':[(a,b,v) for (a,b),v in sorted(profiles.items())],
                      'thresholds':sorted(thresholds.items()),'sp':sorted(sp.items())}
            return profiles,thresholds,sp,hashlib.sha256(dump(material).encode()).hexdigest()
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,HTTPException):
            raise HTTPException(409,'匹配当前程序与PVF的成长索引尚未安装或不可用') from None

    def reference(self,data,blob,rule_sha):
        material=dump({'uid':data['uid'],'charac_no':data['charac_no'],'versions':self.versions(),
                       'archive_sha256':digest(blob),'growth_rules_sha256':rule_sha}).encode()
        return hmac.new(self.settings.secret.encode(),material,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);self.engines(q,{});blob=self.archive(q,charac_no)
        archive=json.loads(blob);profiles,thresholds,sp,rule_sha=self.rules(archive['info']['job'])
        try:first,second=decode_grow_type(archive['info']['grow_type'])
        except ValueError as e:raise HTTPException(409,str(e)) from None
        if (first,second) not in profiles:raise HTTPException(409,'当前职业／觉醒组合缺少成长数据')
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请先在维护中心显式开启维护窗口；本页不会自动停止游戏。'}
        levels=[{'level':1,'experience':0}]+[{'level':k,'experience':v} for k,v in sorted(thresholds.items()) if k<=127]
        return {'target':target,'archive':archive,'reference':self.reference({'uid':target['uid'],'charac_no':charac_no},blob,rule_sha),
                'versions':self.versions(),'growth_rules_sha256':rule_sha,'levels':levels,'labels':LABELS,
                'enabled':self.enabled('char-level'),'maintenance':window,'note':NOTE,
                'point_rule':'剩余SP／TP按已核对的原生管理员改级公式调整，不是逐级升级奖励；超过原生SP查询范围95级时，该公式的SP增量为0。请核对预览，也可另用SP／TP维护页调整。'}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid']);target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock);old=json.loads(before)
        profiles,thresholds,sp,rule_sha=self.rules(old['info']['job'])
        if not hmac.compare_digest(self.reference(data,before,rule_sha),data['reference']):
            raise HTTPException(409,'等级、属性、技能存档或成长索引已变化，请刷新并重新预览')
        exp=data['experience']
        if exp is None:exp=0 if data['level']==1 else thresholds.get(data['level'])
        try:info,points=level_plan(old['info'],{k:old['skills'][k] for k in POINTS},data['level'],exp,profiles,thresholds,sp)
        except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e)) from None
        new={'format':old['format'],'info':info,'stat':{'exp':info['exp']},
             'skills':{**old['skills'],**points,'context':{**old['skills']['context'],'lev':info['lev']}}}
        changes={k:{'before':old['info'][k],'after':info[k]} for k in WRITABLE if old['info'][k]!=info[k]}
        if old['stat']['exp']!=info['exp']:changes['saved_exp']={'before':old['stat']['exp'],'after':info['exp']}
        changes.update({k:{'before':old['skills'][k],'after':points[k]} for k in POINTS if old['skills'][k]!=points[k]})
        if not changes:raise HTTPException(422,'等级、经验及关联字段没有变化，无需提交')
        after=dump(new).encode()
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],
            'before':old,'after':new,'changes':changes,'before_sha256':digest(before),'after_sha256':digest(after),
            'versions':self.versions(),'growth_rules_sha256':rule_sha,'reason':data['reason'],'note':NOTE}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after)
        fields=[k for k in WRITABLE if old['info'][k]!=new['info'][k]]
        def stored(key,value):return bytes.fromhex(value) if key=='element_resist' else value
        if fields:
            q.execute('UPDATE taiwan_cain.charac_info SET '+','.join(f'`{k}`=%s' for k in fields)+' WHERE charac_no=%s AND '+
                ' AND '.join(f'`{k}`=%s' for k in fields),[*(stored(k,new['info'][k]) for k in fields),data['charac_no'],*(stored(k,old['info'][k]) for k in fields)])
            if q.rowcount!=1:raise HTTPException(409,'等级／成长条件更新未命中，事务未提交')
        if old['stat']!=new['stat']:
            q.execute('UPDATE taiwan_cain.charac_stat SET exp=%s WHERE charac_no=%s AND exp=%s',(new['stat']['exp'],data['charac_no'],old['stat']['exp']))
            if q.rowcount!=1:raise HTTPException(409,'角色经验条件更新未命中，事务未提交')
        fields=[k for k in POINTS if old['skills'][k]!=new['skills'][k]]
        if fields:
            q.execute('UPDATE taiwan_cain_2nd.skill SET '+','.join(f'`{k}`=%s' for k in fields)+' WHERE charac_no=%s AND '+
                ' AND '.join(f'`{k}`=%s' for k in fields),[*(new['skills'][k] for k in fields),data['charac_no'],*(old['skills'][k] for k in fields)])
            if q.rowcount!=1:raise HTTPException(409,'关联技能点条件更新未命中，事务未提交')
        if self.archive(q,data['charac_no'],True)!=after:raise HTTPException(409,'等级关联存档回读不符，事务未提交')
