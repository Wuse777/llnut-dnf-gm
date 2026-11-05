"""QF1031 saved-town rescue; no live movement, coordinate injection or quest edits."""
import hashlib
import hmac
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .character_maintenance import CharacterMaintenance
from .inventory_codec import digest
from .inventory_fence import Refused
from .service import dump, one


class RescuePreview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['char-rescue']='char-rescue'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_location']='character_location'
    slot:Literal[0]=0
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_reason(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        return self


class CharacterRescue(CharacterMaintenance):
    actions=('char-rescue',)
    preview_model=RescuePreview
    destination=1  # Native Inter_LoadEtc::verifyCharacVillage's fallback town.

    @staticmethod
    def archive(q,charac_no,lock=False):
        suffix=' FOR UPDATE' if lock else ''
        info=one(q,'SELECT village AS selection_village FROM taiwan_cain.charac_info WHERE charac_no=%s'+suffix,(charac_no,))
        stat=one(q,'SELECT village AS saved_village,village_prev AS previous_village FROM taiwan_cain.charac_stat WHERE charac_no=%s'+suffix,(charac_no,))
        if not info or not stat:raise HTTPException(409,'角色位置存档不完整，不能自动创建记录')
        if any(type(v) is not int or not -128<=v<=127 for v in (*info.values(),*stat.values())):
            raise HTTPException(409,'位置存档不是当前镜像的有符号城镇编号')
        return dump({'format':'qf1031-location-1',**info,**stat}).encode()

    def reference(self,data,blob):
        body=dump({'uid':data['uid'],'charac_no':data['charac_no'],'container':'character_location',
            'destination':self.destination,'versions':self.versions(),'sha256':digest(blob)}).encode()
        return hmac.new(self.settings.secret.encode(),body,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);self.engines(q,{})
            blob=self.archive(q,charac_no)
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；本页不会自动停止游戏。'}
        return {'target':target,'archive':json.loads(blob),'reference':self.reference({'uid':target['uid'],'charac_no':charac_no},blob),
            'versions':self.versions(),'destination':self.destination,'enabled':self.enabled('char-rescue'),'maintenance':window,
            'note':'将选角城镇、登录城镇和返回城镇同步到原生默认城镇 #1。不是在线瞬移；不修改坐标、任务、地下城记录或物品，不保证修复非位置原因的掉线。'}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid'])
        target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock)
        if not hmac.compare_digest(self.reference(data,before),data['reference']):
            raise HTTPException(409,'角色位置或版本已变化，请刷新并重新预览')
        old=json.loads(before);new={**old,**{k:self.destination for k in ('selection_village','saved_village','previous_village')}}
        changes={k:{'before':old[k],'after':v} for k,v in new.items() if old[k]!=v}
        if not changes:raise HTTPException(422,'三个城镇存档已经是默认城镇 #1，无需重复写入；请排查其他卡死原因')
        after=dump(new).encode()
        return before,after,{'target':target,'container':data['container'],'slot':0,'action':data['action'],
            'before':old,'after':new,'changes':changes,'destination':self.destination,
            'before_sha256':digest(before),'after_sha256':digest(after),'versions':self.versions(),'reason':data['reason'],
            'note':'仅重置三个城镇字段；结束维护后重新登录加载。不执行在线传送或删除任务。'}

    def apply_archive(self,q,data,before,after):
        old,new=json.loads(before),json.loads(after)
        if old['selection_village']!=new['selection_village']:
            q.execute('UPDATE taiwan_cain.charac_info SET village=%s WHERE charac_no=%s AND m_id=%s AND village=%s',
                (new['selection_village'],data['charac_no'],data['uid'],old['selection_village']))
            if q.rowcount!=1:raise HTTPException(409,'选角城镇条件更新未命中，事务未提交')
        if (old['saved_village'],old['previous_village'])!=(new['saved_village'],new['previous_village']):
            q.execute('UPDATE taiwan_cain.charac_stat SET village=%s,village_prev=%s WHERE charac_no=%s AND village=%s AND village_prev=%s',
                (new['saved_village'],new['previous_village'],data['charac_no'],old['saved_village'],old['previous_village']))
            if q.rowcount!=1:raise HTTPException(409,'登录城镇条件更新未命中，整笔救援未提交')
        if self.archive(q,data['charac_no'],True)!=after:
            raise HTTPException(409,'救援后的完整位置存档不一致，事务未提交')
