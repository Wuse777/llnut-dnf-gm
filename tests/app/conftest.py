import hashlib
import json
from pathlib import Path
import sqlite3
import time
import pymysql
import pytest
from fastapi.testclient import TestClient
from dnfgm.config import Settings
from dnfgm.db import Database
from dnfgm.app import create_app
from dnfgm.security import PASSWORDS
from dnfgm_m0.lab import connect


@pytest.fixture
def env(lab,tmp_path):
    def factory():
        c=connect(lab.socket);c.cursorclass=pymysql.cursors.DictCursor;return c
    c=factory()
    with c.cursor() as q:
        q.execute('DROP DATABASE dnf_gm')
        for migration in sorted((Path(__file__).resolve().parents[2]/'migrations').glob('*.sql')):
            for sql in migration.read_text().split(';'):
                if sql.strip():q.execute(sql)
        q.execute("INSERT INTO dnf_gm.admins VALUES(1,'admin',%s,'',-1)",(PASSWORDS.hash('fixture-password-no-production'),))
        q.execute('INSERT INTO taiwan_login.login_account_3(m_id,m_channel_no,login_status) VALUES(900001,3011,1)')
    c.commit();c.close()
    pvf='a'*64
    status=tmp_path/'status.json'
    status.write_text(json.dumps({'collected_at':time.time(),'pvf_sha256':pvf,'image_digest':'test-image','core_ok':True,'mem_available_mib':512,'swap_free_mib':4096,'services':{'dnf':True}}))
    index=tmp_path/'catalog.sqlite';sc=sqlite3.connect(index)
    sc.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE items(id INTEGER PRIMARY KEY,name TEXT,category TEXT,level INTEGER,stack_limit INTEGER,durability INTEGER,allowed INTEGER,reviewed INTEGER,source_path TEXT);')
    sc.execute('INSERT INTO metadata VALUES(?,?)',('pvf_sha256',pvf))
    sc.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',[(990001,'测试装备','equipment',1,1,20,1,1,'fixture/equipment'),(990002,'测试材料','material',1,99,0,1,1,'fixture/material'),(990003,'特殊宠物','special',1,1,0,0,0,'fixture/pet')]);sc.commit();sc.close()
    s=Settings(db_password='fixture-only',secret='s'*48,origins=('http://testserver',),writes=('currency','mail','ban','unban','equipment-unlock'),test_uids=(900001,),status_file=str(status),catalog_file=str(index),image_digest='test-image',pvf_sha256=pvf,write_approvals={x:True for x in ('currency','mail','ban','unban','equipment-unlock')})
    db=Database(s,factory)
    app=create_app(s,db)
    client=TestClient(app,raise_server_exceptions=False)
    r=client.post('/dnf-gm/api/v1/auth/login',headers={'Origin':'http://testserver'},json={'username':'admin','password':'fixture-password-no-production'})
    assert r.status_code==200,r.text
    client.headers.update({'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf']})
    yield client,s,db,app
    client.close()
