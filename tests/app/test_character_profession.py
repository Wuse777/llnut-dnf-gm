"""Bounded synthetic profession transactions; never a production role."""
import json
import sqlite3
import pytest
from test_inventory_operations import P,inv
from test_character_skill_reset import reset
from dnfgm import profession_rules as rules
from dnfgm.progression_rules import TAGS,STATS,RULE_VERSION
from dnfgm.character_profession import ProfessionPreview

BASE=P+'/character-profession'

@pytest.fixture
def profession_rig(reset,monkeypatch):
    client,s,db,app,root=reset
    monkeypatch.setattr('dnfgm.character_levels.PROGRAM_SHA',s.inventory_program_sha256)
    monkeypatch.setattr(rules,'PROGRAM_SHA',s.inventory_program_sha256)
    s.writes=(*s.writes,'char-profession');s.write_approvals['char-profession']=True
    app.state.character_profession.fence=app.state.inventory_operations.fence
    with sqlite3.connect(s.catalog_file) as c:
        c.executescript('CREATE TABLE profession_rules(job INTEGER PRIMARY KEY,payload_json TEXT);CREATE TABLE progression_growth(job INTEGER,first_growth INTEGER,second_growth INTEGER,values_json TEXT);CREATE TABLE progression_thresholds(level INTEGER,total_exp INTEGER);')
        c.executemany('INSERT INTO progression_growth VALUES(0,?,?,?)',[(a,b,json.dumps({k:v for k in TAGS.values()})) for (a,b),v in [((-1,0),100),((0,0),10),((1,0),20),((2,0),30)]])
        c.execute('INSERT INTO progression_thresholds VALUES(2,100)')
        c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('profession_rules_version',rules.RULE_VERSION),('profession_rules_program_sha256',rules.PROGRAM_SHA),('progression_growth_version',RULE_VERSION),('progression_growth_program_sha256',rules.PROGRAM_SHA)])
        c.execute('INSERT INTO profession_rules VALUES(0,?)',(json.dumps({'base_name':'合成基础','choices':[{'first':a,'second':0,'code':a,'name':'合成分支'+str(a),'branch':'合成分支'+str(a),'stage':'未觉醒'} for a in (1,2)]}),))
        payload=json.loads(c.execute('SELECT payload_json FROM skill_rules WHERE job=0').fetchone()[0]);payload['defaults']['2:0']=[[6,2]];c.execute('UPDATE skill_rules SET payload_json=?',(json.dumps(payload),))
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET grow_type=-127,element_resist=%s,'+','.join(f'`{k}`=10000' for k in STATS)+' WHERE charac_no=900001',(b'\0'*8,));c.commit()
    return reset


def draft(rig):
    client=rig[0];r=client.get(BASE+'/characters/900001');assert r.status_code==200,r.text
    body={'uid':900001,'charac_no':900001,'reference':r.json()['reference'],'first':2,'second':0,'reason':'合成职业维护'}
    r=client.post(BASE+'/preview',json=body);assert r.status_code==200,r.text
    return r.json()['operation_id']


def test_profession_growth_both_trees_snapshot_and_idempotency(profession_rig):
    client,s,db,app,root=profession_rig;op=draft(profession_rig);route=BASE+'/operations/'+op+'/confirm';key={'idempotency_key':'synthetic-profession-commit'}
    result=client.post(route,json=key);assert result.status_code==200,result.text
    assert result.json()['status']=='committed' and client.post(route,json=key).json()==result.json()
    assert client.get(BASE+'/characters/900001').json()['current']['code']==2
    tree=client.get(P+'/character-skill-reset/characters/900001').json();assert all(x['sp']==700 and x['tp']==21 for x in tree['trees'])
    assert all([(v['skill_id'],v['level']) for v in x['skills']]==[(5,1),(6,2)] for x in tree['trees'])
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT job,grow_type,lev,maxHP FROM taiwan_cain.charac_info WHERE charac_no=900001');row=q.fetchone();assert row=={'job':0,'grow_type':-126,'lev':70,'maxHP':10550}
        q.execute('SELECT skill_slot,skill_slot_lethe,skill_command,lethe_flag FROM taiwan_cain_2nd.skill WHERE charac_no=900001');row=q.fetchone();assert row['skill_slot']==row['skill_slot_lethe'] and row['skill_command']==b'commands' and row['lethe_flag']==1
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
    assert client.get(P+'/character-levels/operations/'+op).status_code==404


def test_stale_archive_and_postwrite_failure_roll_back(profession_rig,monkeypatch):
    client,s,db,app,root=profession_rig;op=draft(profession_rig)
    with db.connect() as c,c.cursor() as q:q.execute('UPDATE taiwan_cain.charac_info SET phy_attack=phy_attack+1 WHERE charac_no=900001');c.commit()
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'synthetic-profession-stale'}).status_code==409
    op=draft(profession_rig);before=client.get(BASE+'/characters/900001').json();apply=app.state.character_profession.apply_archive
    def fail(*args):apply(*args);raise RuntimeError('synthetic failure before commit')
    monkeypatch.setattr(app.state.character_profession,'apply_archive',fail)
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'synthetic-profession-rollback'}).status_code==500
    assert client.get(BASE+'/characters/900001').json()['reference']==before['reference']
    import grants
    assert 'UPDATE(grow_type)' in grants.character_profession_sql() and 'UPDATE(job' not in grants.character_profession_sql()
    with pytest.raises(ValueError):ProfessionPreview(uid=1,charac_no=1,reference='a'*64,first=True,second=0,reason='合成')
