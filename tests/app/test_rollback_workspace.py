"""Rollback checks use real MySQL JSON and the exact read columns they need."""
import importlib.util
import json
from pathlib import Path
import secrets

import pymysql
import pytest


spec=importlib.util.spec_from_file_location('rollback_workspace_mysql',Path(__file__).parents[2]/'deploy/check_rollback.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


@pytest.fixture
def rollback(env,tmp_path):
    db=env[2]
    (tmp_path/'deploy').mkdir()
    manifest={'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1,'maintenance_requests':1}
    (tmp_path/'deploy/release-features.json').write_text(json.dumps(manifest))
    user='rollback_'+secrets.token_hex(6);password=secrets.token_hex(20)
    connection=None
    with db.connect() as root,root.cursor() as q:
        q.execute("CREATE USER %s@'localhost' IDENTIFIED BY %s",(user,password))
        try:
            for table,column in (('reward_jobs','request_json'),('schedules','request_json'),
                                 ('operations','request_json'),('game_backup_runs','state')):
                q.execute(f"GRANT SELECT({column}) ON dnf_gm.{table} TO '{user}'@'localhost'")
            root.commit()
            connection=pymysql.connect(unix_socket=root.unix_socket,user=user,password=password,
                                       autocommit=True,cursorclass=pymysql.cursors.DictCursor)
            with connection.cursor() as restricted:
                guard.check(restricted,tmp_path)
                yield q,root,restricted,tmp_path
                with pytest.raises(pymysql.MySQLError):
                    restricted.execute('SELECT * FROM taiwan_cain.charac_info')
                with pytest.raises(pymysql.MySQLError):
                    restricted.execute("UPDATE dnf_gm.game_backup_runs SET state='failed'")
        finally:
            if connection is not None:connection.close()
            q.execute("DROP USER %s@'localhost'",(user,))


@pytest.mark.parametrize('table,payload',[
    ('reward_jobs',{'campaign_id':'a'*32}),
    ('reward_jobs',{'reward':{'campaign_id':'a'*32}}),
    ('schedules',{'reward_job':{'campaign_id':'a'*32}}),
    ('schedules',{'reward_job':{'reward':{'campaign_id':'a'*32}}}),
    ('operations',{'campaign_id':'a'*32}),
])
def test_old_release_refuses_campaign_records_including_copyable_history(rollback,table,payload):
    q,root,restricted,target=rollback
    common=('b'*32,'c'*64,'d'*64,json.dumps(payload),'{}','preview',0,300)
    if table=='reward_jobs':
        q.execute('INSERT INTO dnf_gm.reward_jobs(id,session_hash,fingerprint,request_json,preview_json,status,created_at,expires_at,reason) '
                  "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'rollback fixture')",common)
    elif table=='schedules':
        q.execute('INSERT INTO dnf_gm.schedules(id,session_hash,fingerprint,request_json,preview_json,status,created_at,expires_at,title,kind) '
                  "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'rollback fixture','reward')",common)
    else:
        q.execute('INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,request_json,preview_json,status,created_at,expires_at,action) '
                  "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'reward')",common)
    for state in ('preview','running','paused','needs_attention','cancelled','finished','completed','committed'):
        q.execute('UPDATE dnf_gm.'+table+' SET status=%s',(state,));root.commit()
        with pytest.raises(guard.IncompatibleRollback,match='campaign reward claims'):
            guard.check(restricted,target)


def test_old_release_accepts_null_campaign_fields_and_terminal_backup_history(rollback):
    q,root,restricted,target=rollback
    q.execute('INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,request_json,preview_json,status,created_at,expires_at,action) '
              "VALUES(%s,%s,%s,%s,'{}','preview',0,300,'reward')",('b'*32,'c'*64,'d'*64,json.dumps({'campaign_id':None})))
    q.execute('INSERT INTO dnf_gm.game_backup_runs(run_id,backup_id,action,window_id,reason,state,fingerprint,spec_json,created_at,expires_at) '
              "VALUES(%s,%s,'backup',%s,'rollback fixture','succeeded',%s,'{}',0,300)",('b'*32,'b'*32,'c'*32,'d'*64))
    for state in ('succeeded','failed'):
        q.execute('UPDATE dnf_gm.game_backup_runs SET state=%s',(state,));root.commit()
        guard.check(restricted,target)
    for state in ('preview','queued','running','needs_review','future_unknown_state'):
        q.execute('UPDATE dnf_gm.game_backup_runs SET state=%s',(state,));root.commit()
        with pytest.raises(guard.IncompatibleRollback,match='unfinished game backup'):
            guard.check(restricted,target)
