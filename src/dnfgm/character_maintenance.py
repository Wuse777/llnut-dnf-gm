"""QF1031 consumed-fatigue editing under the existing exclusive maintenance plan.

The legacy-named inventory ledger is a typed archive ledger: character_fatigue
snapshots contain versioned JSON, NEVER 61-byte item storage. Window settlement
checks atomic intent/snapshot/audit commits without decoding either format.
"""
import hashlib
import hmac
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import Field,StrictInt,model_validator
from .models import Model
from .inventory_operations import InventoryOperations
from .inventory_fence import Refused
from .inventory_codec import digest
from .service import one,dump


class CharacterMaintenancePreview(Model):
    action:Literal['char-fatigue']='char-fatigue'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_fatigue']='character_fatigue'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    changes:dict[str,StrictInt]=Field(min_length=1,max_length=2)
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_changes(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        if set(self.changes)-{'fatigue','premium_fatigue'}:raise ValueError('仅支持普通／额外已消耗疲劳存档')
        if any(not 0<=v<=32767 for v in self.changes.values()):raise ValueError('疲劳字段须为0至32767整数')
        return self


class CharacterMaintenance(InventoryOperations):
    actions=('char-fatigue',)
    preview_model=CharacterMaintenancePreview

    def engines(self,q,data):
        q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','inventory_operations','inventory_snapshots')) OR (TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME IN ('charac_info','charac_stat'))")
        rows=q.fetchall();expected={('dnf_gm',n) for n in ('operations','audit','inventory_operations','inventory_snapshots')}|{('taiwan_cain',n) for n in ('charac_info','charac_stat')}
        if {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in rows}!=expected or any(r['ENGINE']!='InnoDB' for r in rows):raise HTTPException(409,'角色维护事务表必须完整且为InnoDB')

    @staticmethod
    def archive(q,charac_no,lock=False):
        suffix=' FOR UPDATE' if lock else ''
        info=one(q,'SELECT max_fatigue,max_premium_fatigue FROM taiwan_cain.charac_info WHERE charac_no=%s'+suffix,(charac_no,))
        stat=one(q,'SELECT fatigue,premium_fatigue,used_fatigue FROM taiwan_cain.charac_stat WHERE charac_no=%s'+suffix,(charac_no,))
        if not info or not stat:raise HTTPException(409,'角色疲劳存档不完整，不能自动创建记录')
        if any(type(v) is not int for v in (*info.values(),*stat.values())):raise HTTPException(409,'疲劳存档类型异常')
        return dump({'format':'qf1031-fatigue-1',**info,**stat}).encode()

    def reference(self,data,blob):
        body=dump({'uid':data['uid'],'charac_no':data['charac_no'],'container':'character_fatigue','versions':self.versions(),'sha256':digest(blob)}).encode()
        return hmac.new(self.settings.secret.encode(),body,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);data={'uid':target['uid'],'charac_no':charac_no}
            self.engines(q,data);blob=self.archive(q,charac_no)
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；本页不会自动停止游戏'}
        return {'target':target,'archive':json.loads(blob),'reference':self.reference(data,blob),'versions':self.versions(),
                'enabled':self.enabled('char-fatigue'),'maintenance':window,
                'note':'fatigue是已消耗值，填0恢复该项；保留used_fatigue历史计数、疲劳上限、疲劳电池与活动加成。不是在线热更新。'}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid'])
        target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock)
        if not hmac.compare_digest(self.reference(data,before),data['reference']):raise HTTPException(409,'角色疲劳、上限或版本已变化，请刷新并重新预览')
        original=json.loads(before);modified={**original,**data['changes']}
        changes={k:{'before':original[k],'after':v} for k,v in data['changes'].items() if original[k]!=v}
        if not changes:raise HTTPException(422,'没有需要修改的疲劳值；当前存档已经符合设置')
        after=dump(modified).encode()
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],
            'before':original,'after':modified,'changes':changes,'before_sha256':digest(before),'after_sha256':digest(after),
            'versions':self.versions(),'reason':data['reason'],'note':'仅修改charac_stat普通／额外已消耗疲劳；保留历史计数与上限。结束维护后由游戏重新加载。'}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after)
        q.execute('UPDATE taiwan_cain.charac_stat SET fatigue=%s,premium_fatigue=%s WHERE charac_no=%s AND fatigue=%s AND premium_fatigue=%s AND used_fatigue=%s',
            (new['fatigue'],new['premium_fatigue'],data['charac_no'],old['fatigue'],old['premium_fatigue'],old['used_fatigue']))
        if q.rowcount!=1:raise HTTPException(409,'角色疲劳条件更新未命中，未修改目标')
