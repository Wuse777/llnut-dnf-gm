from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import pymysql
import pytest
from fastapi import HTTPException
from dnfgm.catalog import Catalog
from dnfgm.db import Database
from dnfgm.ui_preferences import UiPreferences

P='/dnf-gm/api/v1'
SHA='a'*64


def save(client,version=0,payload=None,kind='catalog-filter',name='常用筛选',sha=SHA):
    return client.put(P+f'/ui-preferences/{kind}/{name}',json={
        'pvf_sha256':sha,'expected_version':version,'payload':payload if payload is not None else {'rarity':0,'sort':'level_desc'}})


def test_versioned_preferences_persist_and_reject_stale_updates_and_aba(env):
    c,s,db,app=env;path=P+'/ui-preferences/catalog-filter/常用筛选'
    assert c.get(path).json()['version']==0 and c.get(path).json()['payload'] is None
    first=save(c);assert first.status_code==200,first.text
    assert first.json()['version']==1 and first.json()['payload']['rarity']==0
    assert save(c,0).status_code==409
    assert save(c,1).json()['version']==1  # Same version and desired state is a no-op.
    deleted=c.request('DELETE',path,json={'pvf_sha256':SHA,'expected_version':1})
    assert deleted.status_code==200,deleted.text
    assert deleted.json()['version']==2 and deleted.json()['deleted']
    assert c.get(path).json()['version']==2 and c.get(path).json()['payload'] is None
    assert c.get(P+'/ui-preferences').json()['items']==[]
    assert save(c,0).status_code==409
    assert save(c,2).json()['version']==3
    fresh=UiPreferences(db,Catalog(s,db)).get('catalog-filter','常用筛选')
    assert fresh['version']==3 and fresh['ui_only']
    with db.connect() as conn,conn.cursor() as q:
        migration=Path(__file__).parents[2]/'migrations/017-ui-preferences.sql'
        for statement in migration.read_text().split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    assert c.get(path).json()['version']==3


def test_preferences_are_pvf_isolated_and_do_not_create_operations_or_game_writes(env):
    c,s,db,app=env
    assert save(c).status_code==200
    assert save(c,payload={'theme':'light','density':'compact'},kind='layout',name='default').status_code==200
    with sqlite3.connect(s.catalog_file) as index:
        index.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('b'*64,))
    assert c.get(P+'/ui-preferences').json()['items']==[]
    assert save(c,sha=SHA).status_code==409
    assert save(c,sha='b'*64).json()['version']==1
    with db.connect() as conn,conn.cursor() as q:
        for table in ('operations','audit','mail_batches','mail_deliveries'):
            q.execute('SELECT COUNT(*) n FROM dnf_gm.'+table);assert q.fetchone()['n']==0
        q.execute('SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001');assert q.fetchone()['cera']==1000
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.postal');assert q.fetchone()['n']==0


def test_preferences_validate_types_csrf_origin_and_session(env):
    c,s,db,app=env
    assert save(c,payload={'pendingId':'f'*32}).status_code==422
    assert save(c,kind='layout',payload={'password':'not permitted'}).status_code==422
    assert save(c,kind='appearance',payload={'job':3,'slots':[{'slot':'[hat avatar]','item_id':1}]*2}).status_code==422
    assert save(c,kind='unknown').status_code==422
    assert save(c,version=True).status_code==422
    c.headers['Origin']='https://attacker.invalid';assert save(c).status_code==403
    c.headers['Origin']='http://testserver';c.headers['X-CSRF-Token']='bad';assert save(c).status_code==403
    c.cookies.clear();assert c.get(P+'/ui-preferences').status_code==401 and save(c).status_code==401


def test_preference_quota_and_concurrent_updates_use_optimistic_versions(env):
    c,s,db,app=env;preferences=UiPreferences(db,Catalog(s,db))
    assert save(c).status_code==200
    def update(value):
        try:return preferences.write('catalog-filter','常用筛选',{'pvf_sha256':SHA,'expected_version':1,'payload':{'q':value}})['version']
        except HTTPException as error:return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(update,['first','second']))
    assert sorted(results)==[2,409]
    for i in range(29):
        preferences.write('layout',f'layout {i}',{'pvf_sha256':SHA,'expected_version':0,'payload':{}})
    assert preferences.write('layout','last',{'pvf_sha256':SHA,'expected_version':0,'payload':{}})['version']==1
    with pytest.raises(HTTPException) as error:
        preferences.write('layout','overflow',{'pvf_sha256':SHA,'expected_version':0,'payload':{}})
    assert error.value.status_code==409


def test_preference_grants_only_allow_dedicated_management_metadata(env):
    c,s,root,app=env
    spec=importlib.util.spec_from_file_location('ui_grants',Path(__file__).parents[2]/'deploy/grants.py')
    grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    with root.connect() as conn,conn.cursor() as q:
        q.execute("DROP USER IF EXISTS 'ui_preference_fixture'@'localhost'")
        q.execute("CREATE USER 'ui_preference_fixture'@'localhost' IDENTIFIED BY 'fixture-password'")
        for statement in grants.ui_preferences_sql("'ui_preference_fixture'@'localhost'").split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    def factory():
        return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='ui_preference_fixture',password='fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limited=Database(s,factory);preferences=UiPreferences(limited,Catalog(s))
    assert preferences.write('layout','default',{'pvf_sha256':SHA,'expected_version':0,'payload':{}})['version']==1
    assert preferences.get('layout','default')['version']==1
    assert preferences.write('layout','default',{'pvf_sha256':SHA,'expected_version':1},delete=True)['version']==2
    with limited.connect() as conn,conn.cursor() as q:
        for statement in ('DELETE FROM dnf_gm.ui_preferences','DROP TABLE dnf_gm.ui_preferences',
                'UPDATE dnf_gm.ui_preferences SET pvf_sha256="wrong"','SELECT * FROM taiwan_cain_2nd.user_items'):
            with pytest.raises(pymysql.OperationalError):q.execute(statement)


def test_local_appearance_preview_requires_pvf_csrf_and_only_returns_metadata(env,monkeypatch):
    c,s,db,app=env;seen=[]
    def preview(sha,body):
        seen.append((sha,body));return {'version':2,'scope':'local_fitting','source_kind':'local_fitting'}
    monkeypatch.setattr(app.state.service.catalog.assets,'preview_appearance',preview)
    body={'pvf_sha256':SHA,'job':3,'slots':[{'slot':'[hat avatar]','item_id':990001}]}
    result=c.post(P+'/appearance/preview',json=body)
    assert result.status_code==200,result.text
    assert result.json()['scope']=='local_fitting' and seen[0][0]==SHA and 'pvf_sha256' not in seen[0][1]
    assert c.post(P+'/appearance/preview',json={**body,'pvf_sha256':'b'*64}).status_code==409
    assert c.post(P+'/appearance/preview',json={**body,'path':'../../anything'}).status_code==422
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.operations');assert q.fetchone()['n']==0
    c.headers['X-CSRF-Token']='bad';assert c.post(P+'/appearance/preview',json=body).status_code==403


def test_atlas_route_cannot_be_intercepted_by_icon_route_and_requires_session(env,monkeypatch):
    c,s,db,app=env;seen=[]
    monkeypatch.setattr(app.state.service.catalog.assets,'atlas',lambda sha,digest:seen.append(('atlas',sha,digest)) or b'synthetic atlas')
    monkeypatch.setattr(app.state.service.catalog.assets,'png',lambda sha,digest:seen.append(('icon',sha,digest)) or b'synthetic icon')
    path=P+'/assets/'+SHA+'/'+'b'*64+'.atlas.png'
    result=c.get(path);assert result.status_code==200,result.text
    assert seen==[('atlas',SHA,'b'*64)] and result.headers['content-type']=='image/png'
    assert result.headers['cache-control']=='no-store'
    c.cookies.clear();assert c.get(path).status_code==401
