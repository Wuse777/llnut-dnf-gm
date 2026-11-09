"""Targeted synthetic MySQL5.7 transaction and task lookup checks only."""
import json
import sqlite3
import struct
import zlib
import pytest
from test_inventory_operations import inv,P
from dnfgm.character_quests import QUEST_COLUMNS,PROGRAM_SHA
from dnfgm.inventory_fence import MaintenanceFence
from dnfgm.release_files import atomic_json

BASE=P+'/quest-repairs'

@pytest.fixture
def quests(inv):
    client,s,db,app,root=inv
    s.inventory_program_sha256=PROGRAM_SHA
    s.writes=(*s.writes,'quest-clear');s.write_approvals['quest-clear']=True
    for name in ('permit.json','evidence.json'):
        state=json.loads((root/name).read_text());state['program_sha256']=PROGRAM_SHA;atomic_json(root/name,state)
    app.state.quest_operations.fence=MaintenanceFence(root,**app.state.quest_operations.versions(),owner=__import__('os').geteuid())
    clear=struct.pack('<I',30000)+zlib.compress(bytes([0,1,0,1])+bytes(29996))
    with db.connect() as c,c.cursor() as q:
        q.execute("INSERT INTO taiwan_cain.new_charac_quest(charac_no,clear_quest,quest_notify,play_1,play_1_trigger,play_2,play_2_trigger,play_3_trigger) VALUES(900001,%s,%s,2,4294967295,2,7,8)",(clear,b'\x00notify\xff'));c.commit()
    with sqlite3.connect(s.catalog_file) as c:
        c.execute("INSERT INTO metadata VALUES('quest_index_version','1')")
        c.execute('CREATE TABLE quests(id INTEGER PRIMARY KEY,name TEXT,grade TEXT,kind TEXT,min_level INTEGER,max_level INTEGER,prerequisites TEXT,condition TEXT)')
        c.executemany('INSERT INTO quests VALUES(?,?,?,?,?,?,?,?)',[(1,'前置任务','史诗','',1,99,'[]',''),(2,'测试觉醒任务','史诗','',1,99,'[1,3]','任务条件'),(3,'另一前置','史诗','',1,99,'[]','')])
    return inv


def draft(rig,slot=1):
    client=rig[0];r=client.get(BASE+'/characters/900001');assert r.status_code==200,r.text
    data={'uid':900001,'charac_no':900001,'slot':slot,'reference':r.json()['reference'],'reason':'合成测试：只清理一个槽'}
    r=client.post(BASE+'/preview',json=data);assert r.status_code==200,r.text
    return r.json(),data


def stored(db):
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT * FROM taiwan_cain.new_charac_quest WHERE charac_no=900001');return q.fetchone()


def test_quest_slot_clear_is_atomic_preserves_other_data_and_recovers_idempotently(quests):
    client,s,db,app,root=quests;before=stored(db);preview,data=draft(quests)
    assert preview['preview']['before']['trigger_raw']==4294967295
    assert preview['preview']['quest_name']=='测试觉醒任务'
    op=preview['operation_id'];key={'idempotency_key':'quest-synthetic-success'}
    r=client.post(BASE+'/operations/'+op+'/confirm',json=key);assert r.status_code==200,r.text
    assert r.json()['status']=='committed' and r.json()['result']['client_verified'] is False
    assert client.post(BASE+'/operations/'+op+'/confirm',json=key).json()==r.json()
    after=stored(db);expected={**before,'play_1':0,'play_1_trigger':0};assert after==expected
    assert client.get(BASE+'/operations?charac_no=900001').json()['items'][0]['operation_id']==op
    assert client.post(P+'/operations/'+op+'/confirm',json=key).status_code==409
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT before_blob,after_blob FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));snap=q.fetchone()
        assert json.loads(snap['before_blob'])['slots'][0]['id']==2
        assert json.loads(snap['after_blob'])['slots'][0]['id']==0
        q.execute("SELECT COUNT(*) n FROM dnf_gm.audit WHERE action='quest-clear'");assert q.fetchone()['n']==1
    assert client.post(BASE+'/preview',json=data).status_code==409
    _,newdata=draft(quests,slot=3)  # empty ID with residual progress is repairable
    s.writes=tuple(a for a in s.writes if a!='quest-clear')
    assert client.post(BASE+'/preview',json=newdata).status_code==403


def test_quest_slot_failed_commit_leaves_all_game_fields_unchanged(quests,monkeypatch):
    client,s,db,app,root=quests;before=stored(db);preview,_=draft(quests)
    apply=app.state.quest_operations.apply_archive
    def fail(*args):apply(*args);raise RuntimeError('synthetic before commit')
    monkeypatch.setattr(app.state.quest_operations,'apply_archive',fail)
    r=client.post(BASE+'/operations/'+preview['operation_id']+'/confirm',json={'idempotency_key':'quest-synthetic-failure'})
    assert r.status_code==500 and stored(db)==before
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0
    assert client.get(BASE+'/operations/'+preview['operation_id']).json()['status']=='executing'


def test_literal_quest_name_search_and_prerequisite_flags(quests):
    client,s,db,app,root=quests
    r=client.get(P+'/characters/900001/quests/search',params={'q':'觉醒'});assert r.status_code==200,r.text
    assert [(x['id'],x['clear_flag'],x['active_slots']) for x in r.json()['items']]==[(2,0,[1,2])]
    d=client.get(P+'/characters/900001/quests?quest_id=2').json()['lookup']['prerequisites']
    assert [(x['id'],x['name'],x['clear_flag']) for x in d['items']]==[(1,'前置任务',1),(3,'另一前置',1)]
    assert client.get(P+'/characters/900001/quests/search',params={'q':"%' OR 1=1 --"}).json()['items']==[]
    with sqlite3.connect(s.catalog_file) as c:c.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('b'*64,))
    d=client.get(P+'/characters/900001/quests/search',params={'q':'觉醒'}).json()
    assert d['catalog']['state']=='mismatch' and d['items']==[]
