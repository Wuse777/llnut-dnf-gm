"""Clear exactly one QF1031 active quest slot in an explicit maintenance window.

No clear-flag changes, quest rewards, arbitrary field updates or online writes.
The typed ledger stores all slots plus hashes of preserved opaque blobs; it is
not a 61-byte item archive and does not expose a generic quest restore endpoint.
"""
import hashlib
import hmac
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import Field,StrictInt,model_validator
from .models import Model
from .character_quests import QUEST_COLUMNS,PROGRAM_SHA,CharacterQuests
from .character_maintenance import CharacterMaintenance
from .inventory_fence import Refused
from .inventory_codec import digest
from .service import one,dump


class QuestPreview(Model):
    action:Literal['quest-clear']='quest-clear'
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt=Field(ge=1,le=2147483647)
    container:Literal['character_quests']='character_quests'
    slot:StrictInt=Field(ge=1,le=20)
    source_operation_id:None=None
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    reason:str=Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_reason(self):
        if not self.reason.strip():raise ValueError('请填写操作原因')
        return self


class QuestOperations(CharacterMaintenance):
    actions=('quest-clear',)
    preview_model=QuestPreview

    def require_enabled(self,action,uid):
        super().require_enabled(action,uid)
        if self.settings.inventory_program_sha256!=PROGRAM_SHA:
            raise HTTPException(409,'当前程序不是已适配的任务存档版本')

    def engines(self,q,data):
        q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','inventory_operations','inventory_snapshots')) OR (TABLE_SCHEMA='taiwan_cain' AND TABLE_NAME IN ('charac_info','new_charac_quest'))")
        rows=q.fetchall();expected={('dnf_gm',n) for n in ('operations','audit','inventory_operations','inventory_snapshots')}|{('taiwan_cain',n) for n in ('charac_info','new_charac_quest')}
        if {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in rows}!=expected or any(r['ENGINE']!='InnoDB' for r in rows):
            raise HTTPException(409,'任务维护事务表必须完整且为InnoDB')

    @staticmethod
    def archive(q,charac_no,lock=False):
        columns=(*QUEST_COLUMNS,'quest_notify')
        row=one(q,'SELECT '+','.join('`'+k+'`' for k in columns)+' FROM taiwan_cain.new_charac_quest WHERE charac_no=%s'+(' FOR UPDATE' if lock else ''),(charac_no,))
        if row is None:raise HTTPException(409,'缺少任务存档，不能自动创建')
        for k,upper in (('clear_quest',65535),('quest_notify',65535)):
            if not isinstance(row[k],bytes) or len(row[k])>upper:raise HTTPException(409,'任务二进制存档类型或长度异常')
        if type(row['urgentQuestIndex']) is not int or not -32768<=row['urgentQuestIndex']<=32767:
            raise HTTPException(409,'紧急任务存档格式异常')
        slots=[]
        for i in range(1,21):
            quest_id,trigger=row[f'play_{i}'],row[f'play_{i}_trigger']
            if type(quest_id) is not int or type(trigger) is not int or not 0<=quest_id<=65535 or not 0<=trigger<=4294967295:
                raise HTTPException(409,'进行中任务槽不是当前版本的无符号格式')
            slots.append({'slot':i,'id':quest_id,'trigger_raw':trigger})
        return dump({'format':'qf1031-quest-slots-1','slots':slots,'urgentQuestIndex':row['urgentQuestIndex'],
            'clear_quest_sha256':digest(row['clear_quest']),'quest_notify_sha256':digest(row['quest_notify'])}).encode()

    def reference(self,data,blob):
        body=dump({'uid':data['uid'],'charac_no':data['charac_no'],'container':'character_quests',
            'versions':self.versions(),'sha256':digest(blob)}).encode()
        return hmac.new(self.settings.secret.encode(),body,hashlib.sha256).hexdigest()

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,charac_no);self.engines(q,{})
            blob=self.archive(q,charac_no)
        state=json.loads(blob)
        catalog,definitions=CharacterQuests(self.service).metadata({x['id'] for x in state['slots'] if x['id']})
        try:window={**self.fence.check(),'available':True}
        except (Refused,OSError):window={'available':False,'note':'请在维护中心显式开启维护窗口；本页不会自动停止游戏。'}
        return {'target':target,'slots':[{**s,'definition':definitions.get(s['id'])} for s in state['slots']],
            'reference':self.reference({'uid':target['uid'],'charac_no':charac_no},blob),'versions':self.versions(),
            'enabled':self.enabled('quest-clear'),'supported':self.settings.inventory_program_sha256==PROGRAM_SHA,
            'maintenance':window,'catalog':catalog,
            'note':'仅将选中槽的任务编号和原始进度清零，保留完成标记、紧急任务、通知存档及其他19槽。不补发或回收任务道具，不保证任务立即可重接。'}

    def build(self,q,data,lock=False):
        self.require_enabled(data['action'],data['uid'])
        target=self.target(q,data['charac_no'],data['uid'],lock)
        before=self.archive(q,data['charac_no'],lock)
        if not hmac.compare_digest(self.reference(data,before),data['reference']):
            raise HTTPException(409,'任务存档或版本已变化，请刷新并重新预览')
        original=json.loads(before);modified=json.loads(before)
        old=original['slots'][data['slot']-1];new={**old,'id':0,'trigger_raw':0}
        if old==new:raise HTTPException(422,'所选槽已经为空且无残留进度，无需重复清理')
        modified['slots'][data['slot']-1]=new
        after=dump(modified).encode()
        catalog,definitions=CharacterQuests(self.service).metadata({old['id']} if old['id'] else set())
        return before,after,{'target':target,'container':data['container'],'slot':data['slot'],'action':data['action'],
            'quest_name':definitions.get(old['id'],{}).get('name'),'catalog_state':catalog['state'],
            'before':old,'after':new,'changes':{k:{'before':old[k],'after':new[k]} for k in ('id','trigger_raw') if old[k]!=new[k]},
            'before_sha256':digest(before),'after_sha256':digest(after),'versions':self.versions(),'reason':data['reason'],
            'preserved':{'other_slots':19,'clear_quest_sha256':original['clear_quest_sha256'],
                'quest_notify_sha256':original['quest_notify_sha256'],'urgentQuestIndex':original['urgentQuestIndex']},
            'note':'只清理所选进行中槽。不修改任务完成标记，不触发奖励，不退款任务道具；结束维护后由游戏重新加载。'}

    def apply_archive(self,q,data,before,after):
        old=json.loads(before)['slots'][data['slot']-1];new=json.loads(after)['slots'][data['slot']-1]
        # Column identifiers come only from the validated integer slot, not SQL input.
        i=data['slot']
        q.execute(f'UPDATE taiwan_cain.new_charac_quest SET play_{i}=%s,play_{i}_trigger=%s WHERE charac_no=%s AND play_{i}=%s AND play_{i}_trigger=%s',
            (new['id'],new['trigger_raw'],data['charac_no'],old['id'],old['trigger_raw']))
        if q.rowcount!=1:raise HTTPException(409,'任务槽条件更新未命中，事务未提交')
        if self.archive(q,data['charac_no'],True)!=after:raise HTTPException(409,'清理后的完整任务槽或保留字段校验不一致，事务未提交')
