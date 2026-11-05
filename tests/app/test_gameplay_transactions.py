"""Real isolated MySQL5.7 lock/connection-loss tests. No production commands."""
import os
from pathlib import Path
import sys

import pymysql
import pytest

from dnfgm.db import Database
from dnfgm.gameplay_transactions import lock_transactions
from dnfgm.release_files import Refused
from dnfgm.write_gate import GameplayWriteGate
from test_write_gate import gate, OP, IDENTITY
from test_combined_rewards import read, write, enable
from test_application import preview, confirm, P
from test_reward_jobs import job_preview,start
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
from grants import gameplay_fence_sql


@pytest.fixture
def server_uuid(env):
    # Capture the planned database BEFORE freezing admission.
    return read(env[2],'SELECT @@server_uuid AS identity')[0]['identity']


@pytest.mark.parametrize('finish',['commit','rollback'])
def test_filesystem_freeze_does_not_mistake_live_mysql_transaction_for_settled(env,gate,finish,server_uuid):
    c,s,db,app=env
    held=db.factory()
    try:
        with held.cursor() as q:
            # The file lease can vanish after a crash while the remote server
            # still owns this transaction. Keep that real transaction alive.
            with app.state.service.write_gate.writer() as lease:
                lease.protect_transaction(q)
                q.execute('UPDATE taiwan_billing.cash_cera SET cera=1100 WHERE account=900001')
        token=gate.freeze(OP,IDENTITY)
        with pytest.raises(pymysql.OperationalError) as error:gate.drain_database(token,db,expected_server_uuid=server_uuid)
        assert error.value.args[0] in (1205,3024)
        assert gate.read()==token
        getattr(held,finish)()
        proof=gate.drain_database(token,db,expected_server_uuid=server_uuid)
        assert proof['ordinary_transactions_drained'] is True
        assert proof['operation_id']==OP and proof['binding_sha256']==token['binding_sha256']
        assert proof['game_writes'] is False and proof['maintenance_permit'] is False
        assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==(1100 if finish=='commit' else 1000)
        assert gate.drain_database(token,db,expected_server_uuid=server_uuid)['ordinary_transactions_drained'] is True
    finally:held.close()


def test_database_locks_allow_multiple_ordinary_writers(env,gate,server_uuid):
    c,s,db,app=env
    with db.connect() as a,db.connect() as b,a.cursor() as qa,b.cursor() as qb:
        with app.state.service.write_gate.writer() as first,app.state.service.write_gate.writer() as second:
            first.protect_transaction(qa)
            # Must not serialize all app work with an exclusive locking read.
            second.protect_transaction(qb)
            qa.execute('SELECT 1');qb.execute('SELECT 1')
        token=gate.freeze(OP,IDENTITY)
        with pytest.raises(pymysql.OperationalError):gate.drain_database(token,db,expected_server_uuid=server_uuid)
        a.commit()
        with pytest.raises(pymysql.OperationalError):gate.drain_database(token,db,expected_server_uuid=server_uuid)
        b.rollback()
    assert gate.drain_database(token,db,expected_server_uuid=server_uuid)['ordinary_transactions_drained']


@pytest.mark.parametrize('change',['missing','protocol','engine'])
def test_broken_protocol_blocks_both_game_mutation_and_root_proof(env,gate,change,server_uuid):
    c,s,db,app=env;op=preview(c).json()['operation_id']
    if change=='missing':sql='DELETE FROM dnf_gm.gameplay_fence'
    elif change=='protocol':sql='UPDATE dnf_gm.gameplay_fence SET protocol_version=2'
    else:sql='ALTER TABLE dnf_gm.gameplay_fence ENGINE=MyISAM'
    write(db,sql)
    response=confirm(c,op);assert response.status_code==409,response.text
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    token=gate.freeze(OP,IDENTITY)
    with pytest.raises(Refused):gate.drain_database(token,db,expected_server_uuid=server_uuid)
    assert gate.read()['state']=='frozen'


def test_fence_uses_only_select_privilege_and_does_not_grant_mutation(env,gate,server_uuid):
    c,s,db,app=env
    with db.connect() as conn,conn.cursor() as q:
        q.execute("DROP USER IF EXISTS 'fence_fixture'@'localhost'")
        q.execute("CREATE USER 'fence_fixture'@'localhost' IDENTIFIED BY 'fixture-password'")
        q.execute(gameplay_fence_sql("'fence_fixture'@'localhost'"));conn.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='fence_fixture',password='fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    minimum=Database(s,factory)
    with minimum.connect() as conn,conn.cursor() as q:
        with GameplayWriteGate(s).writer() as lease:lease.protect_transaction(q)
        conn.commit()
        for sql in ('UPDATE dnf_gm.gameplay_fence SET protocol_version=2','DELETE FROM dnf_gm.gameplay_fence','INSERT INTO dnf_gm.gameplay_fence VALUES(2,1)','SELECT password FROM d_taiwan.accounts'):
            with pytest.raises(pymysql.OperationalError):q.execute(sql)
    token=gate.freeze(OP,IDENTITY)
    assert gate.drain_database(token,minimum,expected_server_uuid=server_uuid)['ordinary_transactions_drained']


def test_root_requires_original_frozen_token_and_configured_database_binding(env,gate,server_uuid):
    c,s,db,app=env
    with pytest.raises(Refused):gate.drain_database(gate.read(),db,expected_server_uuid=server_uuid)
    token=gate.freeze(OP,IDENTITY)
    with pytest.raises(Refused):gate.drain_database({**token,'generation':token['generation']+1},db,expected_server_uuid=server_uuid)
    s.gameplay_gate_dir=''
    with pytest.raises(Refused):gate.drain_database(token,db,expected_server_uuid=server_uuid)
    assert gate.read()==token


def test_root_read_commit_loss_yields_no_proof_but_can_be_rechecked(env,gate,server_uuid):
    c,s,db,app=env;token=gate.freeze(OP,IDENTITY)
    class LoseResponse:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,name):return getattr(self.conn,name)
        def commit(self):self.conn.commit();raise OSError('synthetic response loss')
    broken=Database(s,lambda:LoseResponse(db.factory()))
    with pytest.raises(OSError):gate.drain_database(token,broken,expected_server_uuid=server_uuid)
    assert gate.read()==token
    assert gate.drain_database(token,db,expected_server_uuid=server_uuid)['ordinary_transactions_drained']
    assert not read(db,'SELECT * FROM dnf_gm.audit')


def test_root_probe_holds_freeze_until_connection_closed(env,gate,server_uuid):
    c,s,db,app=env;token=gate.freeze(OP,IDENTITY);seen=[]
    class Connection:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,name):return getattr(self.conn,name)
        def close(self):
            with pytest.raises(Refused,match='busy'):gate.release(token,lambda:True)
            self.conn.close();seen.append(True)
    assert gate.drain_database(token,Database(s,lambda:Connection(db.factory())),expected_server_uuid=server_uuid)['ordinary_transactions_drained']
    assert seen==[True]


def test_batch_reacquires_transaction_lock_after_durable_dispatch_marker(env,gate,monkeypatch):
    c,s,db,app=env;enable(s);job=job_preview(c);assert start(c,job).status_code==200
    old=app.state.reward_jobs.service.apply_reward;observed=[]
    def apply(*args,**kw):
        with db.connect() as conn,conn.cursor() as q:
            q.execute('SET SESSION innodb_lock_wait_timeout=1')
            with pytest.raises(pymysql.OperationalError) as error:lock_transactions(q,exclusive=True)
            assert error.value.args[0] in (1205,3024);observed.append(True)
        return old(*args,**kw)
    monkeypatch.setattr(app.state.reward_jobs.service,'apply_reward',apply)
    assert app.state.reward_jobs.step()
    assert observed==[True],read(db,'SELECT status,error_type,error_message FROM dnf_gm.reward_targets')
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100


def test_health_requires_new_migration(env):
    c,s,db,app=env;assert c.get(P+'/health').status_code==200
    write(db,'DELETE FROM dnf_gm.schema_versions WHERE version=13')
    response=c.get(P+'/health');assert response.status_code==503 and '013' in response.text


@pytest.mark.parametrize('sql',['DELETE FROM dnf_gm.gameplay_fence','UPDATE dnf_gm.gameplay_fence SET protocol_version=2','DROP TABLE dnf_gm.gameplay_fence'])
def test_health_rejects_corrupt_fence_even_when_migration_number_exists(env,sql):
    c,s,db,app=env;write(db,sql)
    response=c.get(P+'/health');assert response.status_code==503 and '屏障' in response.text


def test_health_is_read_only_and_does_not_wait_on_root_exclusive_fence(env,gate):
    c,s,db,app=env
    with db.connect() as held,held.cursor() as q:
        lock_transactions(q,exclusive=True)
        response=c.get(P+'/health');assert response.status_code==200,response.text
    assert not read(db,'SELECT * FROM dnf_gm.audit')


def test_migration_rerun_preserves_existing_protocol_instead_of_reopening_or_overwriting(env):
    c,s,db,app=env
    script=(Path(__file__).parents[2]/'migrations/013-gameplay-fence.sql').read_text()
    write(db,'UPDATE dnf_gm.gameplay_fence SET protocol_version=2')
    with db.connect() as conn,conn.cursor() as q:
        for sql in script.split(';'):
            if sql.strip():q.execute(sql)
        conn.commit()
    assert read(db,'SELECT * FROM dnf_gm.gameplay_fence')==[{'id':1,'protocol_version':2}]
    assert c.get(P+'/health').status_code==503


def test_installer_verifies_real_protocol_and_preserves_app_settings(env,tmp_path):
    import json
    from dataclasses import asdict
    from configure_write_gate import configure
    c,s,db,app=env
    config=tmp_path/'app-config.json';value=asdict(s)
    config.write_text(json.dumps(value));config.chmod(0o600)
    root=tmp_path/'installed-gate'
    result=configure(config=config,root=root,owner=os.geteuid(),app_uid=os.geteuid(),app_gid=os.getegid(),db_factory=lambda settings:Database(settings,db.factory))
    assert result['configured'] and result['protocol_version']==1
    assert json.loads(config.read_text())=={**json.loads(json.dumps(value)),'gameplay_gate_dir':str(root)}
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(db,'SELECT * FROM dnf_gm.audit')


@pytest.mark.parametrize('identity',['','not-a-database','00000000-0000-0000-0000-000000000000'])
def test_root_cannot_drain_a_replacement_or_unidentified_database(env,gate,identity):
    c,s,db,app=env;token=gate.freeze(OP,IDENTITY)
    with pytest.raises(Refused,match='database_identity'):
        gate.drain_database(token,db,expected_server_uuid=identity)
    assert gate.read()==token
    assert not read(db,'SELECT * FROM dnf_gm.audit')
