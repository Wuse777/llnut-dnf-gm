"""Two focused level transactions against synthetic socket-only MySQL5.7."""
import json
import sqlite3
import pytest
from test_character_skills import skills
from test_inventory_operations import P,inv
from dnfgm.progression_rules import TAGS,RULE_VERSION,STATS
from dnfgm.character_levels import LevelPreview
from pydantic import ValidationError

BASE=P+'/character-levels'

@pytest.fixture
def levels(skills,monkeypatch):
    client,s,db,app,root=skills
    monkeypatch.setattr('dnfgm.character_levels.PROGRAM_SHA',s.inventory_program_sha256)
    s.writes=(*s.writes,'char-level');s.write_approvals['char-level']=True
    app.state.character_levels.fence=app.state.inventory_operations.fence
    with sqlite3.connect(s.catalog_file) as c:
        c.execute('CREATE TABLE progression_growth(job INTEGER,first_growth INTEGER,second_growth INTEGER,values_json TEXT)')
        c.execute('CREATE TABLE progression_sp(level INTEGER,points INTEGER)')
        c.execute('CREATE TABLE progression_thresholds(level INTEGER,total_exp INTEGER)')
        c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[
            ('progression_growth_version',RULE_VERSION),('progression_growth_program_sha256',s.inventory_program_sha256)])
        values={k:10 for k in TAGS.values()}
        c.executemany('INSERT INTO progression_growth VALUES(0,?,0,?)',[(k,json.dumps(values)) for k in (-1,0)])
        c.executemany('INSERT INTO progression_thresholds VALUES(?,?)',[(2,100),(3,200),(4,300)])
        c.executemany('INSERT INTO progression_sp VALUES(?,?)',[(n,30) for n in range(1,5)])
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET lev=2,exp=100,job=0,grow_type=0,element_resist=%s,'+','.join(f'`{k}`=100' for k in STATS)+' WHERE charac_no=900001',(b'\0'*8,))
        q.execute('INSERT INTO taiwan_cain.charac_stat(charac_no,exp) VALUES(900001,90) ON DUPLICATE KEY UPDATE exp=90')
        c.commit()
    return skills


def draft(rig):
    client=rig[0];r=client.get(BASE+'/characters/900001');assert r.status_code==200,r.text
    body={'uid':900001,'charac_no':900001,'reference':r.json()['reference'],'level':3,'reason':'合成等级关联维护'}
    r=client.post(BASE+'/preview',json=body);assert r.status_code==200,r.text
    return r.json()['operation_id']


def test_level_linked_commit_preserves_skill_blobs_and_result(levels):
    client,s,db,app,root=levels
    before=client.get(BASE+'/characters/900001').json()['archive'];op=draft(levels)
    key={'idempotency_key':'level-linked-synthetic-success'};route=BASE+'/operations/'+op+'/confirm'
    r=client.post(route,json=key);assert r.status_code==200,r.text
    assert r.json()['status']=='committed' and client.post(route,json=key).json()==r.json()
    after=client.get(BASE+'/characters/900001').json()['archive']
    assert after['info']['lev']==3 and after['info']['exp']==after['stat']['exp']==200
    assert after['info']['maxHP']==110 and after['skills']['remain_sp']==130 and after['skills']['remain_sp_2nd']==230
    assert after['skills']['skill_slot_sha256']==before['skills']['skill_slot_sha256']
    assert after['info']['spec_property_sha256']==before['info']['spec_property_sha256']
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
    assert client.post(P+'/operations/'+op+'/confirm',json=key).status_code==409
    assert client.get(P+'/character-skills/operations/'+op).status_code==404


def test_level_stale_and_interrupted_transaction_roll_back(levels,monkeypatch):
    client,s,db,app,root=levels;op=draft(levels)
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_stat SET exp=91 WHERE charac_no=900001');c.commit()
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'level-stale-synthetic'}).status_code==409
    op=draft(levels);before=client.get(BASE+'/characters/900001').json()['archive']
    apply=app.state.character_levels.apply_archive
    def fail(*args):apply(*args);raise RuntimeError('synthetic failure after linked writes, before commit')
    monkeypatch.setattr(app.state.character_levels,'apply_archive',fail)
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'level-rollback-synthetic'}).status_code==500
    assert client.get(BASE+'/characters/900001').json()['archive']==before
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0
    body={'uid':1,'charac_no':1,'reference':'a'*64,'level':2,'reason':'合成参数'}
    with pytest.raises(ValidationError):LevelPreview(**{**body,'level':True})
    with pytest.raises(ValidationError):LevelPreview(**{**body,'experience':-1})
    import grants
    sql=grants.character_levels_sql();assert 'UPDATE(exp) ON taiwan_cain.charac_stat' in sql
    assert 'GRANT ALL' not in sql and 'UPDATE(job' not in sql
