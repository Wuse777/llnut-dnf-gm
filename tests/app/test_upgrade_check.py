"""Private local candidate indexes + isolated MySQL. No deployment or game writes."""
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from dnfgm.upgrade_check import UpgradeCheck
from test_combined_rewards import read,write,enable
from test_reward_jobs import job_preview,start
from test_schedules import definition,activate

P='/dnf-gm/api/v1'; U=P+'/compatibility'; NEW='b'*64


@pytest.fixture
def candidate(env,tmp_path):
    c,s,db,app=env
    path=tmp_path/'candidate.sqlite';shutil.copyfile(s.catalog_file,path)
    with sqlite3.connect(path) as q:
        q.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",(NEW,))
        q.execute("UPDATE items SET name='候选新材料',level=70,stack_limit=0 WHERE id=990002")
        q.execute('DELETE FROM items WHERE id=990001')
    s.upgrade_catalog_file=str(path)
    return env


def checker(env):return UpgradeCheck(env[1],env[2])
def header(env):
    r=env[0].get(U);assert r.status_code==200,r.text;return r.json()
def refs(env,kind,**kw):
    r=env[0].get(U+'/references',params={'kind':kind,'fingerprint':header(env)['fingerprint'],**kw});assert r.status_code==200,r.text;return r.json()
def gift(env,items=None):
    r=env[0].post(P+'/gift-templates',json={'name':'升级夹具','expected_version':0,'items':items or [{'id':990001,'quantity':1},{'id':990002,'quantity':2147483647}]});assert r.status_code==200,r.text;return r.json()['id']


def test_candidate_is_optional_and_missing_is_not_compatible(env):
    d=header(env);assert d['state']=='not_configured' and d['can_deploy'] is False and d['sources']==[]
    env[1].upgrade_catalog_file='/nonexistent/private-example/index.sqlite'
    r=env[0].get(U);assert r.status_code==503 and '/nonexistent' not in r.text


def test_compare_candidate_does_not_activate_or_mutate(candidate):
    env=candidate;c,s,db,app=env;tid=gift(env)
    baseline=read(db,'SELECT * FROM dnf_gm.gift_versions');balance=read(db,'SELECT cera FROM taiwan_billing.cash_cera')
    d=header(env);assert d['current']['live_aligned'] and d['pvf_changed'] and not d['can_deploy']
    row=refs(env,'templates')['items'][0];assert row['id']==str(tid)+':1'
    byid={i['id']:i for i in row['items']}
    assert 'candidate_item_missing' in byid[990001]['changes']
    assert 'name_changed' in byid[990002]['changes'] and 'stack_limit_changed' in byid[990002]['changes']
    assert byid[990002]['after']['stack_limit']==0
    assert s.pvf_sha256=='a'*64 and read(db,'SELECT * FROM dnf_gm.gift_versions')==baseline
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')==balance and not read(db,'SELECT * FROM taiwan_cain_2nd.postal')


def test_historical_policy_and_preferences_dont_borrow_current_name(candidate):
    c,s,db,app=candidate
    write(db,"INSERT INTO dnf_gm.item_preferences(pvf_sha256,item_id,favorite) VALUES(%s,990002,1)",('c'*64,))
    write(db,"INSERT INTO dnf_gm.catalog_policy_items(pvf_sha256,item_id,enabled,reason,revision,verification_evidence) VALUES(%s,990002,0,'私有停用理由',1,'旧版本验证')",('a'*64,))
    row=refs(candidate,'preferences')['items'][0]
    assert 'historical_pvf_unknown' in row['issues'] and row['items'][0]['before'] is None
    row=refs(candidate,'policies')['items'][0];assert row['status']=='disabled' and 'pvf_bound_reference' in row['issues']
    assert '私有停用理由' not in json.dumps(row,ensure_ascii=False)  # not needed by static report
    assert read(db,'SELECT enabled FROM dnf_gm.catalog_policy_items')[0]['enabled']==0


def test_template_reference_in_saved_schedule_is_resolved(candidate):
    c,s,db,app=candidate;enable(s);s.schedule_worker_enabled=True;tid=gift(candidate)
    data=definition(int(time.time()));data['reward_job']['reward']={'template_id':tid,'template_version':1}
    r=c.post(P+'/schedules/preview',json=data);assert r.status_code==200,r.text
    plan=r.json();assert activate(c,plan).status_code==200
    row=refs(candidate,'schedules')['items'][0];assert row['template']=={'id':str(tid),'version':1}
    assert len(row['items'])==2 and 'recreate_bound_operation' in row['issues']
    assert read(db,'SELECT status FROM dnf_gm.schedules')[0]['status']=='active'
    assert not read(db,'SELECT * FROM dnf_gm.reward_jobs')


def test_jobs_and_pending_previews_are_only_read(candidate):
    c,s,db,app=candidate;enable(s)
    job=job_preview(c,reward={'items':[{'id':990002,'quantity':2}]});assert start(c,job).status_code==200
    p=c.post(P+'/operations/preview',json={'action':'mail','uid':900001,'charac_no':900001,'items':[{'id':990002,'quantity':3}],'reason':'检查保留预览'});assert p.status_code==200,p.text
    assert refs(candidate,'jobs')['items'][0]['items'][0]['id']==990002
    row=refs(candidate,'previews')['items'][0];assert row['id']==p.json()['operation_id'] and 'recreate_bound_operation' in row['issues']
    assert not read(db,'SELECT * FROM taiwan_cain_2nd.postal')
    assert read(db,'SELECT status FROM dnf_gm.reward_jobs')[0]['status']=='running'


def test_bad_or_oversized_reference_is_not_a_clean_report(candidate):
    tid=gift(candidate);db=candidate[2]
    for value in ('broken','"'+('x'*70000)+'"',json.dumps({'items':[{'id':'invalid'}]})):
        write(db,'UPDATE dnf_gm.gift_versions SET payload_json=%s WHERE template_id=%s',(value,tid))
        row=refs(candidate,'templates')['items'][0];assert row['needs_review'] and 'unreadable_reference' in row['issues']


def test_same_id_mail_kind_change_is_reported(candidate):
    tid=gift(candidate,items=[{'id':990002,'quantity':2}])
    with sqlite3.connect(candidate[1].upgrade_catalog_file) as q:q.execute("UPDATE items SET category='equipment',source_path='equipment/avatar/test' WHERE id=990002")
    item=refs(candidate,'templates')['items'][0]['items'][0];assert 'mail_kind_changed' in item['changes']


def test_candidate_change_invalidates_old_cursor_and_header(candidate):
    c,s,db,app=candidate;fp=header(candidate)['fingerprint']
    with sqlite3.connect(s.upgrade_catalog_file) as q:q.execute("UPDATE items SET level=80 WHERE id=990002")
    r=c.get(U+'/references',params={'kind':'templates','fingerprint':fp});assert r.status_code==409
    assert c.get(U+'/export',params={'fingerprint':fp}).status_code==409


def test_pagination_signed_cursor_and_complete_export(candidate):
    c,s,db,app=candidate
    with db.connect() as con,con.cursor() as q:
        q.executemany('INSERT INTO dnf_gm.item_preferences(pvf_sha256,item_id,favorite) VALUES(%s,%s,1)',[('a'*64,i) for i in range(1,54)]);con.commit()
    first=refs(candidate,'preferences');assert len(first['items'])==50 and first['next_cursor']
    second=refs(candidate,'preferences',cursor=first['next_cursor']);assert len(second['items'])==3 and second['next_cursor'] is None
    for token in (first['next_cursor']+'x',checker(candidate).cursor('images',[50],first['fingerprint'])):
        assert c.get(U+'/references',params={'kind':'preferences','fingerprint':first['fingerprint'],'cursor':token}).status_code==422
    r=c.get(U+'/export',params={'fingerprint':first['fingerprint']});assert r.status_code==200
    lines=[json.loads(x) for x in r.text.splitlines()]
    assert lines[-1]['type']=='complete' and lines[-1]['sources']['preferences']['checked']==53 and not lines[-1]['can_deploy']
    assert lines[0]['snapshot']=='repeatable_read' and len({r['id'] for r in lines if r['type']=='reference'})==53


def test_export_late_db_changes_are_not_mixed(candidate):
    c,s,db,app=candidate;tid=gift(candidate);service=checker(candidate)
    stream=service.export(header(candidate)['fingerprint']);assert json.loads(next(stream))['type']=='metadata'
    write(db,"UPDATE dnf_gm.gift_versions SET payload_json='broken' WHERE template_id=%s",(tid,))
    rows=[json.loads(x) for x in stream];assert rows[-1]['type']=='complete'
    assert 'unreadable_reference' not in rows[0]['issues']


def test_export_file_change_is_incomplete_and_releases_connection(candidate):
    c,s,db,app=candidate;gift(candidate);stream=checker(candidate).export(header(candidate)['fingerprint'])
    next(stream)
    # Replace atomically: open SQLite snapshots stay valid but final identity guard rejects completion.
    path=Path(s.upgrade_catalog_file);replacement=path.with_suffix('.replacement');shutil.copyfile(path,replacement);replacement.replace(path)
    rows=[json.loads(x) for x in stream];assert rows[-1]['type']=='incomplete'
    acquired=[]
    try:
        for _ in range(3):assert db.slots.acquire(blocking=False);acquired.append(True)
    finally:
        for _ in acquired:db.slots.release()


def assets(path,sha,items):
    path.mkdir();db=sqlite3.connect(path/'manifest.sqlite')
    db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE item_images(item_id INTEGER PRIMARY KEY,sha256 TEXT,state TEXT); CREATE TABLE portraits(job INTEGER,grow_type INTEGER,sex INTEGER,sha256 TEXT,PRIMARY KEY(job,grow_type,sex));')
    db.executemany('INSERT INTO metadata VALUES(?,?)',[('format','dnfgm-assets-v1'),('state','ready'),('pvf_sha256',sha)])
    db.executemany('INSERT INTO item_images VALUES(?,?,?)',[(i,'d'*64,state) for i,state in items]);db.commit();db.close()


def test_image_mapping_missing_and_wrong_pvf_are_explicit(candidate,tmp_path):
    c,s,db,app=candidate;old=tmp_path/'old-art';new=tmp_path/'new-art'
    assets(old,'a'*64,[(990002,'ready')]);assets(new,NEW,[]);s.assets_dir=str(old);s.upgrade_assets_dir=str(new)
    row=refs(candidate,'images')['items'][0];assert row['items'][0]['candidate_image_state']=='missing' and row['needs_review']
    with sqlite3.connect(new/'manifest.sqlite') as q:q.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('c'*64,))
    assert header(candidate)['assets']['candidate']['state']=='mismatch'
    assert refs(candidate,'images')['items'][0]['items'][0]['candidate_image_state']=='mismatch'


def test_live_unknown_and_declared_image_are_not_verified(candidate):
    c,s,db,app=candidate;s.upgrade_image_digest='sha256:'+'f'*64;Path(s.status_file).unlink()
    d=header(candidate);assert not d['current']['live_aligned'] and d['image_changed']
    assert not d['candidate']['image_verified'] and {r['capability'] for r in d['recheck']} >= {'baseline','native','currency','inventory','unlock'}


def test_authenticated_readonly_and_no_paths_or_credentials(candidate):
    c,s,db,app=candidate
    with TestClient(app) as anon:
        for path in ('','/references','/export'):
            r=anon.get(U+path,params={'kind':'templates','fingerprint':'a'*64});assert r.status_code==401
    assert c.post(U,json={'path':'/etc/shadow'}).status_code==405
    raw=c.get(U).text;assert s.db_password not in raw and s.secret not in raw and s.upgrade_catalog_file not in raw
    assert c.get(U+'/references',params={'kind':"templates;DROP TABLE",'fingerprint':header(candidate)['fingerprint']}).status_code==422


@pytest.mark.parametrize('field,value',[('upgrade_catalog_file','relative'),('upgrade_assets_dir','../bad'),('upgrade_image_digest','latest'),('upgrade_image_digest',None)])
def test_candidate_configuration_validation(env,field,value):
    setattr(env[1],field,value)
    with pytest.raises(ValueError):env[1].check()


def test_portrait_exact_mapping_diff_is_not_silently_replaced_with_wildcard(candidate,tmp_path):
    c,s,db,app=candidate;old=tmp_path/'old-portrait';new=tmp_path/'new-portrait'
    assets(old,'a'*64,[]);assets(new,NEW,[]);s.assets_dir=str(old);s.upgrade_assets_dir=str(new)
    with sqlite3.connect(old/'manifest.sqlite') as q:q.execute('INSERT INTO portraits VALUES(0,1,0,?)',('d'*64,))
    with sqlite3.connect(new/'manifest.sqlite') as q:q.execute('INSERT INTO portraits VALUES(0,-1,-1,?)',('d'*64,))
    row=refs(candidate,'portraits')['items'][0];assert 'portrait_mapping_missing' in row['issues']
    with sqlite3.connect(new/'manifest.sqlite') as q:q.execute('INSERT INTO portraits VALUES(0,1,0,?)',('e'*64,))
    row=refs(candidate,'portraits')['items'][0];assert 'portrait_mapping_changed' in row['issues']


def test_saved_binding_checked_even_if_candidate_equals_current(candidate):
    c,s,db,app=candidate;enable(s);s.schedule_worker_enabled=True
    plan=c.post(P+'/schedules/preview',json=definition(int(time.time()))).json()
    frozen=read(db,'SELECT preview_json FROM dnf_gm.schedules')[0]['preview_json'];frozen=json.loads(frozen)
    frozen['binding']['pvf_sha256']='c'*64;frozen['binding']['image_digest']='previous-image'
    write(db,'UPDATE dnf_gm.schedules SET preview_json=%s WHERE id=%s',(json.dumps(frozen),plan['id']))
    s.upgrade_catalog_file=s.catalog_file
    row=refs(candidate,'schedules')['items'][0]
    assert 'saved_pvf_mismatch' in row['issues'] and 'saved_image_mismatch' in row['issues']
    assert row['needs_review']


def test_candidate_manual_disable_is_reported_not_changed(candidate):
    c,s,db,app=candidate;gift(candidate,items=[{'id':990002,'quantity':2}])
    write(db,"INSERT INTO dnf_gm.catalog_policy_items(pvf_sha256,item_id,enabled,reason,revision) VALUES(%s,990002,0,'fixture',1)",(NEW,))
    item=refs(candidate,'templates')['items'][0]['items'][0]
    assert 'candidate_policy_disabled' in item['changes']
    assert read(db,'SELECT enabled FROM dnf_gm.catalog_policy_items')[0]['enabled']==0


def test_cli_exports_private_file_without_overwrite(candidate,tmp_path,monkeypatch,capsys):
    import importlib.util,os,sys
    tool=Path(__file__).resolve().parents[2]/'tools/check_upgrade.py'
    spec=importlib.util.spec_from_file_location('upgrade_cli_fixture',tool);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    monkeypatch.setattr(m,'load_settings',lambda:candidate[1]);monkeypatch.setattr(m,'Database',lambda s:candidate[2])
    destination=tmp_path/'private.ndjson';monkeypatch.setattr(sys,'argv',['check_upgrade','--output',str(destination)])
    m.main();assert json.loads(capsys.readouterr().out)['complete']
    assert destination.stat().st_mode&0o777==0o600
    assert json.loads(destination.read_text().splitlines()[-1])['type']=='complete'
    original=destination.read_bytes()
    with pytest.raises(FileExistsError):m.main()
    assert destination.read_bytes()==original


@pytest.mark.parametrize('document',[{'reward_job':None},{'reward_job':{'reward':[]}}])
def test_malformed_nested_schedule_is_visible_not_http_500(candidate,document):
    c,s,db,app=candidate;enable(s);s.schedule_worker_enabled=True
    r=c.post(P+'/schedules/preview',json=definition(int(time.time())));assert r.status_code==200,r.text
    write(db,'UPDATE dnf_gm.schedules SET request_json=%s',(json.dumps(document),))
    row=refs(candidate,'schedules')['items'][0];assert row['needs_review'] and 'unreadable_reference' in row['issues']


def test_oversized_candidate_item_text_is_unknown_not_truncated_clean(candidate):
    gift(candidate,items=[{'id':990002,'quantity':1}])
    with sqlite3.connect(candidate[1].upgrade_catalog_file) as q:q.execute('UPDATE items SET name=? WHERE id=990002',('x'*10000,))
    row=refs(candidate,'templates')['items'][0];assert 'unreadable_reference' in row['issues'] and row['needs_review']
    assert 'x'*1000 not in json.dumps(row)


def test_existing_minimal_runtime_grants_are_sufficient(candidate):
    import importlib.util,os,pymysql
    from dnfgm.db import Database
    from dnfgm.security import PASSWORDS
    c,s,root,app=candidate
    spec=importlib.util.spec_from_file_location('upgrade_grants',Path(__file__).resolve().parents[2]/'deploy/grants.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    sql=g.bootstrap_sql({'db_user':'upgrade_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-only-admin'))
    with root.connect() as con,con.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'upgrade_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        con.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='upgrade_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    db=Database(s,factory);check=UpgradeCheck(s,db)
    try:
        overview=check.overview()
        for kind in overview['sources']:assert check.references(kind,overview['fingerprint'])['items']==[]
        rows=[json.loads(x) for x in check.export(overview['fingerprint'])];assert rows[-1]['type']=='complete'
        with db.connect() as con,con.cursor() as q:
            with pytest.raises(pymysql.OperationalError):q.execute('SELECT password FROM d_taiwan.accounts')
            with pytest.raises(pymysql.OperationalError):q.execute('DROP TABLE dnf_gm.gift_versions')
    finally:
        with root.connect() as con,con.cursor() as q:q.execute("DROP USER IF EXISTS 'upgrade_minimal'@'localhost'");con.commit()


def test_historical_template_label_comes_from_immutable_version(candidate):
    c,s,db,app=candidate;tid=gift(candidate)
    r=c.put(P+f'/gift-templates/{tid}',json={'name':'新名称','expected_version':1,'items':[{'id':990002,'quantity':1}]});assert r.status_code==200,r.text
    rows=refs(candidate,'templates')['items'];assert [r['label'] for r in rows]==['升级夹具','新名称']
    assert rows[0]['status']=='historical' and rows[1]['status']=='active'
    assert '不是建立引用时的历史快照' in rows[0]['note']
