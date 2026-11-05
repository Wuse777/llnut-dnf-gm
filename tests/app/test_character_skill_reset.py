"""Two bounded synthetic MySQL5.7 checks, never a production game account."""
import json
import sqlite3
import pytest
from test_inventory_operations import inv,P
from dnfgm import skill_rules as rules
from dnfgm.character_skill_reset import SkillResetPreview

BASE=P+'/character-skill-reset'

@pytest.fixture
def reset(inv,monkeypatch):
    client,s,db,app,root=inv
    monkeypatch.setattr('dnfgm.character_skills.PROGRAM_SHA',s.inventory_program_sha256)
    monkeypatch.setattr(rules,'PROGRAM_SHA',s.inventory_program_sha256)
    s.writes=(*s.writes,'char-skill-reset');s.write_approvals['char-skill-reset']=True
    app.state.character_skill_reset.fence=app.state.inventory_operations.fence
    definitions={str(k):{'name':f'合成技能{k}','group':1,'active':True} for k in (5,6,99)}
    with sqlite3.connect(s.catalog_file) as c:
        c.executescript('CREATE TABLE skill_rules(job INTEGER PRIMARY KEY,payload_json TEXT);CREATE TABLE progression_sp(level INTEGER PRIMARY KEY,points INTEGER);')
        c.execute('INSERT INTO skill_rules VALUES(0,?)',(json.dumps({'job':0,'definitions':definitions,'defaults':{'-1:0':[[5,1]],'1:0':[[6,1]]}}),))
        c.executemany('INSERT INTO progression_sp VALUES(?,?)',[(n,10) for n in range(1,96)])
        c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)', [('skill_rules_version',rules.RULE_VERSION),('skill_rules_program_sha256',rules.PROGRAM_SHA),('skill_expert_rules',json.dumps({'experts':{},'level_limits':{}}))])
    raw=bytes((5,3,99,7))+b'\0'*404;blob=rules.pack(raw)
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET lev=70,job=0,grow_type=1,expert_job=0 WHERE charac_no=900001')
        q.execute('INSERT INTO taiwan_cain.charac_stat(charac_no,expert_job_exp) VALUES(900001,0)')
        q.execute("INSERT INTO taiwan_cain_2nd.skill(charac_no,remain_sp,remain_sp_2nd,remain_sfp_1st,remain_sfp_2nd,skill_slot,skill_slot_2nd,skill_slot_lethe,skill_slot_lethe_2nd,request_sp,request_sp_2nd,skill_command,lethe_flag) VALUES(900001,10,20,1,2,%s,%s,%s,%s,'request1','request2','commands',1)",(blob,blob,blob,blob));c.commit()
    return inv


def draft(rig):
    client=rig[0];read=client.get(BASE+'/characters/900001');assert read.status_code==200,read.text
    r=client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'trees':[0],'reference':read.json()['reference'],'reason':'合成技能重置'})
    assert r.status_code==200,r.text
    return r.json()['operation_id']


def test_selected_reset_snapshot_idempotency_and_other_tree_preservation(reset):
    client,s,db,app,root=reset;before=client.get(BASE+'/characters/900001').json();op=draft(reset)
    key={'idempotency_key':'synthetic-skill-reset-confirm'};url=BASE+'/operations/'+op+'/confirm'
    r=client.post(url,json=key);assert r.status_code==200,r.text
    assert r.json()['status']=='committed' and client.post(url,json=key).json()==r.json()
    after=client.get(BASE+'/characters/900001').json()
    assert after['trees'][0]['sp']==700 and after['trees'][0]['tp']==21
    assert [v['skill_id'] for v in after['trees'][0]['skills']]==[5,6]
    assert after['trees'][1]==before['trees'][1]
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT skill_slot,skill_slot_lethe,skill_command,request_sp,lethe_flag FROM taiwan_cain_2nd.skill WHERE charac_no=900001');row=q.fetchone()
        assert row['skill_slot']==row['skill_slot_lethe'] and row['skill_command']==b'commands' and row['request_sp']==b'request1' and row['lethe_flag']==1
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
    assert client.get(P+'/character-skills/operations/'+op).status_code==404


def test_stale_expert_refused_and_failure_rolls_back(reset,monkeypatch):
    client,s,db,app,root=reset;op=draft(reset)
    with db.connect() as c,c.cursor() as q:q.execute('UPDATE taiwan_cain.charac_stat SET expert_job_exp=1 WHERE charac_no=900001');c.commit()
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'synthetic-skill-reset-stale'}).status_code==409
    op=draft(reset);before=client.get(BASE+'/characters/900001').json()['trees'];apply=app.state.character_skill_reset.apply_archive
    def fail(*args):apply(*args);raise RuntimeError('synthetic failure before commit')
    monkeypatch.setattr(app.state.character_skill_reset,'apply_archive',fail)
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'synthetic-skill-reset-rollback'}).status_code==500
    assert client.get(BASE+'/characters/900001').json()['trees']==before
    import grants
    assert 'UPDATE(skill_slot,skill_slot_2nd,skill_slot_lethe,skill_slot_lethe_2nd)' in grants.character_skill_reset_sql()
    body={'uid':1,'charac_no':1,'trees':[0],'reference':'a'*64,'reason':'合成参数'}
    assert SkillResetPreview(**body).trees==[0]
    with pytest.raises(ValueError):SkillResetPreview(**{**body,'trees':[False]})
