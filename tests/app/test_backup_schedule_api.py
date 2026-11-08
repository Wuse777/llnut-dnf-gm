import json
import os
from pathlib import Path
import uuid
import sys
import pymysql
from dnfgm.backup import restore_drill
from dnfgm_m0.lab import connect
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
from backup_worker import BackupWorker

P='/dnf-gm/api/v1'


def policy(client,**changes):
    row=client.get(P+'/backups').json()['policy']
    return dict(request_id=uuid.uuid4().hex,expected_revision=row['revision'],enabled=False,hour=4,minute=0,retention_days=7,failure_alerts=True,reason='隔离测试自动备份',**changes)


def test_backup_controls_idempotence_online_snapshot_and_interrupted_reconcile(env,tmp_path,lab):
    client,s,db,app=env
    s.maintenance_dir=str(tmp_path/'mailbox');Path(s.maintenance_dir).mkdir()
    s.backup_health_file=str(tmp_path/'health.json')
    settings=policy(client);r=client.post(P+'/backups/policy',json=settings);assert r.status_code==200,r.text
    assert r.json()['policy']['enabled'] is False
    assert client.post(P+'/backups/policy',json=settings).json()==r.json()
    assert client.get(P+'/backups/policy/requests/'+settings['request_id']).json()==r.json()
    bad={**settings,'reason':'不同参数'};assert client.post(P+'/backups/policy',json=bad).status_code==409
    request={'request_id':uuid.uuid4().hex,'reason':'合成管理库快照'}
    queued=client.post(P+'/backups/runs',json=request);assert queued.status_code==200,queued.text
    assert queued.json()['state']=='queued'
    assert client.post(P+'/backups/runs',json=request).json()==queued.json()
    root=tmp_path/'private';root.mkdir(mode=0o700)
    config=tmp_path/'source.json';config.write_text(json.dumps(dict(version=1,host=s.db_host,port=s.db_port,user='root',password='synthetic-not-production')));config.chmod(0o600)
    lock=tmp_path/'shared.lock';lock.touch(mode=0o600);calls=[]
    def source():calls.append(True);return connect(lab.socket)
    worker=BackupWorker(db,s,root=root,config=config,lock=lock,owner=os.getuid(),guard=lambda:None,connect=source)
    finish=worker.finish
    worker.finish=lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError('lost finish response'))
    worker.tick(force=True)
    assert client.get(P+'/backups/runs/'+request['request_id']).json()['state']=='running'
    assert len(calls)==1
    worker.finish=finish;worker.tick(force=True)
    result=client.get(P+'/backups/runs/'+request['request_id']).json()
    assert result['state']=='succeeded' and result['result']['tables']>=30
    assert result['result']['restore_verified'] is False
    assert len(calls)==1  # A durable receipt is reconciled, not exported again.
    health=client.get(P+'/backup-health').json();assert health['state']=='ok'
    assert health['restore']['state']=='not_recorded'
    assert client.get(P+'/backups').json()['worker']['state']=='ready'
    artifact=root/('management-'+request['request_id'])/'management.ndjson'
    with connect(lab.socket) as local,local.cursor() as q:
        q.execute('SELECT @@datadir');datadir=q.fetchone()[0]
    restored=restore_drill(artifact,result['result']['artifact_sha256'],socket=lab.socket,datadir=datadir)
    assert restored['state']=='verified'
    # An intent without a committed receipt is failed, never automatically replayed.
    other={'request_id':uuid.uuid4().hex,'reason':'中断合成任务'}
    assert client.post(P+'/backups/runs',json=other).status_code==200
    with db.connect() as c,c.cursor() as q:
        q.execute("UPDATE dnf_gm.backup_runs SET state='running',started_at=UNIX_TIMESTAMP() WHERE run_id=%s",(other['request_id'],));c.commit()
    worker.tick(force=True)
    assert client.get(P+'/backups/runs/'+other['request_id']).json()['error_code']=='backup_interrupted'
    assert len(calls)==1
    client.cookies.clear();assert client.get(P+'/backups').status_code==401
