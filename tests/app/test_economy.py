"""Isolated MySQL5.7 evidence. Does not assert any in-game receipt/economy."""
from datetime import datetime,timedelta,timezone
import json
import uuid
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pymysql
import pytest
from dnfgm.economy import Economy,normalize
from test_combined_rewards import enable,read,write
from test_mail_gold import preview,confirm,rows
from test_reward_jobs import job_preview,start,extra_role
from test_support_desk import create as case_create,confirm as case_confirm,reward as case_reward

P='/dnf-gm/api/v1';E=P+'/economy'
def dates():
    d=datetime.now(timezone(timedelta(hours=8))).date().isoformat();return {'start':d,'end':d}
def summary(c,**kw):
    r=c.get(E+'/summary',params={**dates(),**kw});assert r.status_code==200,r.text;return r.json()
def currency(c,delta,currency='cera'):
    p=c.post(P+'/operations/preview',json={'action':'currency','uid':900001,'currency':currency,'delta':delta,'reason':'统计测试'});assert p.status_code==200,p.text
    r=confirm(c,p.json()['operation_id'],uuid.uuid4().hex);assert r.status_code==200,r.text;return r.json()
def totals(data):return {r['metric']:r for r in data['totals']}
def raw_audit(db,action='currency',req=None,result=None,created='2026-11-04 16:00:00',uid=900001):
    op=uuid.uuid4().hex;req=req or {'uid':uid,'currency':'cera','delta':999999};result=result or {'uid':uid,'currency':'cera','before':1000,'after':1010}
    write(db,'INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json,created_at) VALUES(%s,\'owner\',%s,%s,\'fixture\',%s,%s,%s)',(op,action,uid,json.dumps(req),json.dumps(result),created));return op


def test_current_currency_issued_deducted_net_and_idempotency(env):
    c,s,db,app=env;currency(c,100);currency(c,-30)
    d=summary(c);assert d['coverage']=={'reward_audits':2,'projected':2,'complete':2,'incomplete':0,'unprojected':0,'state':'complete'}
    assert totals(d)['cera']=={'metric':'cera','issued':'100','deducted':'30','net':'70'}
    assert len(d['daily'])==1 and d['targets'][0]['target_uid']==900001
    assert len(read(db,'SELECT * FROM dnf_gm.economy_values'))==2
    assert summary(c,uid=900002)['coverage']['reward_audits']==0


def test_combined_reward_uses_results_and_mail_gold_only_once(env):
    c,s,db,app=env;enable(s)
    p=preview(c,action='reward',currency_rewards={'cera':50,'cera_point':20,'mileage':30},items=[{'id':990002,'quantity':2147483647},{'id':990002,'quantity':2147483647}],gold=1000000000).json()
    r=confirm(c,p['operation_id']);assert r.status_code==200,r.text
    assert confirm(c,p['operation_id']).json()==r.json()
    d=summary(c);t=totals(d)
    assert t['cera']['net']=='50' and t['mileage']['net']=='30' and t['gold']['issued']=='1000000000'
    assert t['item']['issued']=='4294967294' and d['items'][0]['quantity']=='4294967294'
    assert len(read(db,'SELECT * FROM dnf_gm.economy_operations'))==1


def test_statistics_failure_rolls_back_currency_mail_and_audit(env,monkeypatch):
    c,s,db,app=env;enable(s);original=app.state.service.economy.record
    def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('after projection')
    monkeypatch.setattr(app.state.service.economy,'record',fail)
    p=preview(c,action='reward',currency_rewards={'cera':50},gold=100).json();assert confirm(c,p['operation_id']).status_code==500
    assert not rows(db) and not read(db,'SELECT * FROM dnf_gm.economy_operations')
    assert not read(db,'SELECT * FROM dnf_gm.economy_values')
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(db,'SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(p['operation_id'],))


def test_nontransactional_projection_rejects_before_projection_inserts(env):
    c,s,db,app=env;write(db,'ALTER TABLE dnf_gm.economy_values ENGINE=MyISAM')
    p=preview(c,gold=100).json();assert confirm(c,p['operation_id']).status_code==503
    assert not rows(db) and not read(db,'SELECT * FROM dnf_gm.economy_operations')


def test_batch_once_per_account_does_not_double_count_currency(env):
    c,s,db,app=env;enable(s);extra_role(db)
    job=job_preview(c,targets={'mode':'selected','charac_nos':[900001,900003]});assert start(c,job).status_code==200
    for _ in range(3):app.state.reward_jobs.step()
    d=summary(c);assert totals(d)['cera']['issued']=='100';assert totals(d)['gold']['issued']=='246'
    assert d['sources']==[{'source':'batch','operations':2}]


def test_historical_import_coverage_exact_results_and_no_game_writes(env):
    c,s,db,app=env;op=raw_audit(db)
    d=summary(c,start='2026-11-05',end='2026-11-05');assert d['coverage']['state']=='partial' and d['coverage']['unprojected']==1
    result=app.state.service.economy.import_history();assert result['imported']==1
    d=summary(c,start='2026-11-05',end='2026-11-05');assert totals(d)['cera']['net']=='10'  # request falsely said 999999
    assert app.state.service.economy.import_history()['imported']==0
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not rows(db)
    write(db,"UPDATE dnf_gm.audit SET reason='changed evidence' WHERE operation_id=%s",(op,))
    with pytest.raises(HTTPException):app.state.service.economy.import_history()


def test_malformed_history_is_incomplete_not_zero_success(env):
    c,s,db,app=env;raw_audit(db,result={'broken':True})
    app.state.service.economy.import_history();d=summary(c,start='2026-11-05',end='2026-11-05')
    assert d['coverage']['incomplete']==1 and d['coverage']['state']=='partial' and not d['totals']
    r=c.get(E+'/operations',params={'start':'2026-11-05','end':'2026-11-05'}).json();assert r['items'][0]['complete']==0 and r['items'][0]['issue']


def test_beijing_midnight_filter_and_days(env):
    c,s,db,app=env
    raw_audit(db,created='2026-11-04 15:59:59');raw_audit(db,created='2026-11-04 16:00:00');raw_audit(db,created='2026-11-05 15:59:59');raw_audit(db,created='2026-11-05 16:00:00')
    app.state.service.economy.import_history();d=summary(c,start='2026-11-05',end='2026-11-05')
    assert d['coverage']['complete']==2 and totals(d)['cera']['net']=='20' and d['daily'][0]['day']=='2026-11-05'


def test_amounts_above_js_safe_integer_are_exact_strings(env):
    c,s,db,app=env;op=raw_audit(db);app.state.service.economy.import_history()
    # Root fixture represents a large historical aggregate; public writes have no such API.
    write(db,"UPDATE dnf_gm.economy_values SET amount=9007199254740993 WHERE operation_id=%s",(op,))
    d=summary(c,start='2026-11-05',end='2026-11-05');assert totals(d)['cera']['net']=='9007199254740993'


def test_backlog_unknown_claimed_deleted_and_gold_are_not_confused(env):
    c,s,db,app=env
    p=preview(c,items=[{'id':990002,'quantity':2}]*4,gold=123).json();assert confirm(c,p['operation_id']).status_code==200
    mail=rows(db)
    write(db,'UPDATE taiwan_cain_2nd.postal SET receive_time=UTC_TIMESTAMP() WHERE postal_id=%s',(mail[0]['postal_id'],))
    write(db,'UPDATE taiwan_cain_2nd.postal SET delete_flag=1 WHERE postal_id=%s',(mail[1]['postal_id'],))
    write(db,'DELETE FROM taiwan_cain_2nd.postal WHERE postal_id=%s',(mail[2]['postal_id'],))
    r=c.get(E+'/backlog',params=dates());assert r.status_code==200,r.text
    d=r.json();states={x['receipt_state']:x for x in d['states']};assert set(states)=={'claimed_marker','deleted_marker','record_missing','unclaimed_marker'}
    assert states['claimed_marker']['gold']=='123' and len(d['oldest'])==1 and d['client_verified'] is False
    write(db,'UPDATE dnf_gm.mail_batches SET history_complete=0,postal_count=postal_count+2')
    d=c.get(E+'/backlog',params=dates()).json();assert d['coverage']['unrecorded']=='2' and d['coverage']['incomplete_batches']==1


def test_large_operations_and_repeated_case_compensation_are_hints_only(env):
    c,s,db,app=env;cid=case_create(env)['case_id']
    for _ in range(2):assert case_confirm(env,case_reward(env,cid)['operation_id']).status_code==200
    params={**dates(),'large':'true','currency_threshold':101}
    assert not c.get(E+'/operations',params=params).json()['items']
    params['currency_threshold']=100;assert len(c.get(E+'/operations',params=params).json()['items'])==2
    r=c.get(E+'/compensation',params=dates()).json();assert r['items'][0]['case_id']==cid and r['items'][0]['compensation_count']==2
    assert r['items'][0]['status']=='open'


def test_pagination_export_frozen_upper_and_completed_marker(env):
    c,s,db,app=env
    for _ in range(53):raw_audit(db)
    app.state.service.economy.import_history()
    params={'start':'2026-11-05','end':'2026-11-05'}
    first=c.get(E+'/operations',params=params).json();assert len(first['items'])==50 and first['next_before']
    raw_audit(db);app.state.service.economy.import_history()
    second=c.get(E+'/operations',params={**params,'upper':first['upper'],'before':first['next_before']}).json();assert len(second['items'])==3
    response=c.get(E+'/export',params=params);assert response.status_code==200
    lines=[json.loads(x) for x in response.text.splitlines()];assert lines[0]['type']=='metadata' and lines[-1]=={'type':'complete','count':54,'scope':'projected_operations_only'}
    assert len({x['operation_id'] for x in lines if x['type']=='operation'})==54


def test_export_interrupt_is_not_complete(env,monkeypatch):
    c,s,db,app=env
    for _ in range(51):raw_audit(db)
    service=app.state.service.economy;service.import_history();stream=service.export('2026-11-05','2026-11-05')
    first=json.loads(next(stream));original=service.operation_page
    monkeypatch.setattr(service,'operation_page',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('private-details')))
    lines=[first,*[json.loads(x) for x in stream]];assert lines[-1]['type']=='incomplete' and lines[-1]['count']==50
    assert 'private-details' not in json.dumps(lines)


@pytest.mark.parametrize('params',[{'start':'bad','end':'2026-11-05'},{'start':'2026-10-01','end':'2026-11-05'},{'start':'2026-11-06','end':'2026-11-05'},{**dates(),'uid':"1 OR 1=1"}])
def test_report_filters_are_validated(env,params):assert env[0].get(E+'/summary',params=params).status_code==422


def test_auth_readonly_and_timeout_does_not_return_fake_totals(env,monkeypatch):
    c,s,db,app=env
    with TestClient(app) as anonymous:
        for path in ('summary','operations','backlog','compensation','export'):assert anonymous.get(E+'/'+path,params=dates()).status_code==401
    assert c.post(E+'/summary',json={'sql':'DROP DATABASE'}).status_code==405
    class TimedOut:
        def execute(self,*a):raise pymysql.OperationalError(3024,'private sql')
    with pytest.raises(HTTPException) as failure:Economy.query(TimedOut(),'x')
    assert failure.value.status_code==503 and 'private sql' not in failure.value.detail


def test_export_snapshot_excludes_late_import_of_older_audits(env):
    c,s,db,app=env;ops=[raw_audit(db) for _ in range(53)];service=app.state.service.economy
    for op in ops[2:]:
        with db.connect() as conn,conn.cursor() as q:service.record(q,op,historical=True);conn.commit()
    first=service.operations('2026-11-05','2026-11-05');assert len(first['items'])==50
    service.import_history()
    second=service.operations('2026-11-05','2026-11-05',before=first['next_before'],upper=first['upper'])
    assert len(second['items'])==1 and second['next_before'] is None
    assert not set(ops[:2]) & {r['operation_id'] for r in first['items']+second['items']}


def test_null_historical_target_is_visible_as_unknown_not_skipped(env):
    c,s,db,app=env;raw_audit(db,uid=None);app.state.service.economy.import_history()
    r=app.state.service.economy.operations('2026-11-05','2026-11-05')['items'][0]
    assert r['target_uid']==0 and r['complete']==0 and not r['values']


def test_missing_historical_mail_ledger_is_reported(env):
    c,s,db,app=env;p=preview(c,gold=123).json();assert confirm(c,p['operation_id']).status_code==200
    write(db,'DELETE FROM dnf_gm.mail_deliveries');write(db,'DELETE FROM dnf_gm.mail_batches')
    d=c.get(E+'/backlog',params=dates()).json();assert d['coverage']['missing_mail_ledgers']==1 and not d['states']


def test_commit_response_loss_does_not_duplicate_statistics(env,monkeypatch):
    from test_inventory_operations import Conn
    from dnfgm.security import COOKIE,digest
    c,s,db,app=env;service=app.state.service;p=preview(c,gold=100).json();factory=db.factory;key=uuid.uuid4().hex;session=digest(c.cookies.get(COOKIE))
    def lost(connection):connection.commit();raise pymysql.OperationalError(2013,'synthetic acknowledgement loss')
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),commit=lost))
    with pytest.raises(HTTPException) as error:service.confirm(session,p['operation_id'],key)
    assert error.value.status_code==503
    monkeypatch.setattr(db,'factory',factory);service.confirm(session,p['operation_id'],key)
    assert len(read(db,'SELECT * FROM dnf_gm.economy_operations'))==1
    assert totals(summary(c))['gold']['issued']=='100'


def test_projection_minimal_permissions_append_only_and_reports(env):
    from pathlib import Path
    import importlib.util,os
    from dnfgm.db import Database
    from dnfgm.security import PASSWORDS
    from dnfgm.service import Service
    c,s,root,app=env
    spec=importlib.util.spec_from_file_location('economy_grants',Path(__file__).resolve().parents[2]/'deploy/grants.py');grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    sql=grants.bootstrap_sql({'db_user':'economy_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with root.connect() as conn,conn.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'economy_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='economy_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    db=Database(s,factory);service=Service(db,s)
    try:
        p=service.preview('f'*64,{'action':'currency','uid':900001,'currency':'cera','delta':100,'reason':'fixture'})
        service.confirm('f'*64,p['operation_id'],uuid.uuid4().hex)
        d=service.economy.summary(**dates());assert totals(d)['cera']['issued']=='100'
        assert not service.economy.backlog(**dates())['states']
        assert service.economy.import_history()['imported']==0
        for sql in ('DELETE FROM dnf_gm.economy_values','UPDATE dnf_gm.economy_operations SET complete=0','DROP TABLE dnf_gm.economy_values','SELECT password FROM d_taiwan.accounts'):
            with db.connect() as conn,conn.cursor() as q:
                with pytest.raises(pymysql.OperationalError):q.execute(sql)
    finally:
        with root.connect() as conn,conn.cursor() as q:q.execute("DROP USER IF EXISTS 'economy_minimal'@'localhost'");conn.commit()



def test_export_snapshot_does_not_include_earlier_inflight_projection(env):
    c,s,db,app=env;service=app.state.service.economy
    first_op=raw_audit(db)
    with db.connect() as held,held.cursor() as q:
        service.record(q,first_op,historical=True)  # reserve the smallest projection ID, not yet committed
        for _ in range(51):
            op=raw_audit(db)
            with db.connect() as conn,conn.cursor() as other:service.record(other,op,historical=True);conn.commit()
        stream=service.export('2026-11-05','2026-11-05');metadata=json.loads(next(stream));assert metadata['snapshot']=='repeatable_read'
        held.commit()
        lines=[json.loads(x) for x in stream]
    assert lines[-1]['count']==51 and all(r.get('operation_id')!=first_op for r in lines)


def test_export_early_close_releases_connection_and_slot(env):
    c,s,db,app=env;raw_audit(db);service=app.state.service.economy;service.import_history()
    stream=service.export('2026-11-05','2026-11-05')
    assert json.loads(next(stream))['type']=='metadata'
    acquired=[]
    try:
        for _ in range(2):
            assert db.slots.acquire(blocking=False);acquired.append(True)
        assert not db.slots.acquire(blocking=False)
        stream.close()
        assert db.slots.acquire(blocking=False);acquired.append(True)
    finally:
        stream.close()
        for _ in acquired:db.slots.release()
    assert len(service.operations('2026-11-05','2026-11-05')['items'])==1


def test_scheduled_reward_source_uses_committed_child_results(env):
    import time
    from test_schedules import definition,activate
    c,s,db,app=env;enable(s);s.schedule_worker_enabled=True
    engine=app.state.schedules;now=[int(time.time())];engine.clock=lambda:now[0]
    r=c.post(P+'/schedules/preview',json=definition(now[0]));assert r.status_code==200,r.text
    plan=r.json();assert activate(c,plan).status_code==200
    now[0]=plan['request']['first_due'];assert engine.step()
    for _ in range(2):app.state.reward_jobs.step()
    d=summary(c)
    assert d['sources']==[{'source':'schedule','operations':1}]
    assert totals(d)['cera']['issued']=='100' and totals(d)['gold']['issued']=='123'
    assert activate(c,plan).status_code==200
    assert summary(c)['coverage']['complete']==1


def test_template_versions_report_separately_without_double_counting(env):
    c,s,db,app=env;enable(s)
    data={'name':'版本统计测试','expected_version':0,'currency_rewards':{'cera':10}}
    r=c.post(P+'/gift-templates',json=data);assert r.status_code==200,r.text
    tid=r.json()['id']
    for version,amount in ((1,10),(2,20)):
        if version==2:
            r=c.put(P+f'/gift-templates/{tid}',json={**data,'expected_version':1,'currency_rewards':{'cera':amount}})
            assert r.status_code==200,r.text
        p=preview(c,action='reward',gold=0,charac_no=None,template_id=tid,template_version=version)
        assert p.status_code==200,p.text
        assert confirm(c,p.json()['operation_id'],uuid.uuid4().hex).status_code==200
    d=summary(c)
    assert d['templates']==[{'template_id':tid,'template_version':v,'operations':1} for v in (1,2)]
    assert totals(d)['cera']['issued']=='30'
