"""Single-owner management-backup control, not game backup or SQL execution."""
from datetime import datetime,timedelta,timezone
import json
import re
import time
from fastapi import HTTPException
from pydantic import Field,StrictInt
from .models import Model
from .alerts import read_json
from .service import dump,one

ZONE=timezone(timedelta(hours=8))
STATES={'queued','running','succeeded','failed','cancelled'}

class BackupPolicy(Model):
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    expected_revision:StrictInt=Field(ge=1)
    enabled:bool
    hour:StrictInt=Field(ge=0,le=23)
    minute:StrictInt=Field(ge=0,le=59)
    retention_days:StrictInt=Field(ge=1,le=30)
    failure_alerts:bool=True
    reason:str=Field(min_length=1,max_length=200)

class BackupRequest(Model):
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    reason:str=Field(min_length=1,max_length=200)


def policy_view(row):
    return {k:(bool(row[k]) if k in ('enabled','failure_alerts') else row[k]) for k in ('revision','enabled','hour','minute','retention_days','failure_alerts','updated_at')}|{'timezone':'Asia/Shanghai'}


def run_view(row):
    return {k:row.get(k) for k in ('run_id','origin','state','reason','created_at','started_at','finished_at','error_code')}|{'result':json.loads(row['result_json']) if row.get('result_json') else None}


def scheduler_status(path,now=None):
    now=time.time() if now is None else now
    try:
        d=read_json(path)
        if d.get('version')!=1 or type(d.get('checked_at')) not in (int,float) or not 0<=now-d['checked_at']<=90:raise ValueError('Stale')
        if d.get('state') not in ('ready','running','deferred','unconfigured','error'):raise ValueError('Unknown status')
        return {'state':d['state'],'checked_at':d['checked_at'],'configured':d.get('configured') is True,
            'alerts_enabled':d.get('alerts_enabled') is True,'failure':d.get('failure') is True,
            'reason':d.get('reason') if d.get('reason') in ('maintenance_busy','resources_low','backup_configuration_missing','backup_worker_failed','backup_interrupted') else None}
    except (OSError,ValueError,TypeError,KeyError):
        return {'state':'unknown','checked_at':None,'configured':False,'alerts_enabled':True,'failure':True,'reason':None}


def daily_key(policy,now):
    if not policy['enabled']:return None
    local=datetime.fromtimestamp(now,ZONE)
    if (local.hour,local.minute)<(policy['hour'],policy['minute']):return None
    # At most one run per local day, including changes to the time or re-enabling.
    return 'daily:'+local.strftime('%Y-%m-%d')


def next_due(policy,now):
    if not policy['enabled']:return None
    local=datetime.fromtimestamp(now,ZONE)
    due=local.replace(hour=policy['hour'],minute=policy['minute'],second=0,microsecond=0)
    if due<=local:due+=timedelta(days=1)
    return due.timestamp()


class BackupSchedule:
    def __init__(self,db,settings):self.db,self.settings=db,settings

    @property
    def status_path(self):
        from pathlib import Path
        return Path(self.settings.maintenance_dir)/'backup-scheduler.json'

    @staticmethod
    def policy(q,lock=False):
        row=one(q,'SELECT * FROM dnf_gm.backup_schedule WHERE id=1'+(' FOR UPDATE' if lock else ''))
        if row is None:raise HTTPException(503,'备份计划迁移尚未完成')
        return row

    def view(self,page=1):
        now=time.time()
        with self.db.connect() as c,c.cursor() as q:
            policy=self.policy(q)
            q.execute('SELECT * FROM dnf_gm.backup_runs ORDER BY created_at DESC,run_id DESC LIMIT 11 OFFSET %s',((page-1)*10,));rows=q.fetchall()
            today=daily_key(policy,now)
            due_today=one(q,'SELECT state FROM dnf_gm.backup_runs WHERE run_key=%s',(today,)) if today else None
        return {'policy':policy_view(policy),'worker':scheduler_status(self.status_path,now),
            'next_due_at':next_due(policy,now),'today_pending':bool(today and not due_today),
            'items':[run_view(r) for r in rows[:10]],'page':page,'has_more':len(rows)>10,
            'scope':'management_only','online_snapshot':True,'game_services_touched':False,
            'note':'只备份GM管理库；单工作器内使用一致性快照，不停止GM或游戏。当天过点补一次，不补历史日期。'}

    def update(self,data):
        data=BackupPolicy(**data).model_dump();data['reason']=data['reason'].strip()
        if not data['reason']:raise HTTPException(422,'请填写备份计划修改原因')
        op='backup-policy:'+data['request_id']
        with self.db.connect() as c,c.cursor() as q:
            row=self.policy(q,True)
            saved=one(q,'SELECT request_json,result_json FROM dnf_gm.audit WHERE operation_id=%s',(op,))
            if saved:
                if json.loads(saved['request_json'])!=data:raise HTTPException(409,'请求编号已用于不同的备份设置')
                return json.loads(saved['result_json'])
            if row['revision']!=data['expected_revision']:raise HTTPException(409,'备份设置已变化，请刷新后再保存')
            now=time.time()
            q.execute('UPDATE dnf_gm.backup_schedule SET revision=revision+1,enabled=%s,hour=%s,minute=%s,retention_days=%s,failure_alerts=%s,updated_at=%s WHERE id=1',
                (data['enabled'],data['hour'],data['minute'],data['retention_days'],data['failure_alerts'],now))
            result={'status':'committed','policy':policy_view(self.policy(q)),'request_id':data['request_id']}
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','backup-policy',%s,%s,%s)",(op,data['reason'],dump(data),dump(result)))
            c.commit();return result

    def request(self,data):
        data=BackupRequest(**data).model_dump();data['reason']=data['reason'].strip()
        if not data['reason']:raise HTTPException(422,'请填写备份原因')
        with self.db.connect() as c,c.cursor() as q:
            policy=self.policy(q,True)
            saved=one(q,'SELECT * FROM dnf_gm.backup_runs WHERE run_id=%s',(data['request_id'],))
            if saved:
                if saved['origin']!='manual' or saved['reason']!=data['reason']:raise HTTPException(409,'备份编号已用于不同请求')
                return run_view(saved)
            queued=one(q,"SELECT run_id FROM dnf_gm.backup_runs WHERE state IN ('queued','running') LIMIT 1")
            if queued:raise HTTPException(409,'已有等待或执行中的备份，请先查询原编号')
            now=time.time();spec=policy_view(policy)
            q.execute("INSERT INTO dnf_gm.backup_runs(run_id,run_key,origin,state,reason,spec_json,created_at) VALUES(%s,%s,'manual','queued',%s,%s,%s)",(data['request_id'],'manual:'+data['request_id'],data['reason'],dump(spec),now))
            result=run_view(one(q,'SELECT * FROM dnf_gm.backup_runs WHERE run_id=%s',(data['request_id'],)))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','backup-request',%s,%s,%s)",('backup-request:'+data['request_id'],data['reason'],dump(data),dump(result)))
            c.commit();return result

    def policy_result(self,request_id):
        with self.db.connect() as c,c.cursor() as q:
            row=one(q,"SELECT result_json FROM dnf_gm.audit WHERE operation_id=%s AND action='backup-policy'",('backup-policy:'+request_id,))
        if not row:raise HTTPException(404,'尚未查询到本次设置记录，请保留请求编号再核对')
        return json.loads(row['result_json'])

    def detail(self,run_id):
        with self.db.connect() as c,c.cursor() as q:row=one(q,'SELECT * FROM dnf_gm.backup_runs WHERE run_id=%s',(run_id,))
        if not row:raise HTTPException(404,'备份编号不存在')
        return run_view(row)
