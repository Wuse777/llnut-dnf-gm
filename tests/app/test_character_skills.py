"""Scoped SP/TP transactions on synthetic local MySQL5.7 only."""
import json
import pytest
from test_inventory_operations import inv, P
from dnfgm.character_skills import SkillPointsPreview, LIMITS
from pydantic import ValidationError

BASE=P+'/character-skills'

@pytest.fixture
def skills(inv,monkeypatch):
    client,s,db,app,root=inv
    monkeypatch.setattr('dnfgm.character_skills.PROGRAM_SHA',s.inventory_program_sha256)
    s.writes=(*s.writes,'char-sp-tp');s.write_approvals['char-sp-tp']=True
    app.state.character_skills.fence=app.state.inventory_operations.fence
    with db.connect() as c,c.cursor() as q:
        q.execute("INSERT INTO taiwan_cain_2nd.skill(charac_no,remain_sp,remain_sp_2nd,remain_sfp_1st,remain_sfp_2nd,used_sp,sp_garbage,skill_slot,request_sp,skill_slot_2nd,request_sp_2nd,skill_slot_lethe,skill_slot_lethe_2nd,skill_command) VALUES(900001,100,200,3,4,30,2,'synthetic-tree-1','request-1','synthetic-tree-2','request-2','lethe-1','lethe-2','commands')")
        c.commit()
    return inv


def draft(rig):
    client=rig[0];r=client.get(BASE+'/characters/900001');assert r.status_code==200,r.text
    response=client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'reference':r.json()['reference'],
        'changes':{'remain_sp':700,'remain_sfp_2nd':20},'reason':'合成技能点补偿'})
    assert response.status_code==200,response.text
    return response.json()['operation_id']


def test_points_preserve_skills_and_original_result(skills):
    client,s,db,app,root=skills
    before=client.get(BASE+'/characters/900001').json()['archive'];op=draft(skills)
    key={'idempotency_key':'skill-points-synthetic-success'};route=BASE+'/operations/'+op+'/confirm'
    r=client.post(route,json=key);assert r.status_code==200,r.text
    assert r.json()['status']=='committed'
    assert client.post(route,json=key).json()==r.json()
    assert client.get(BASE+'/characters/900001').json()['archive']=={**before,'remain_sp':700,'remain_sfp_2nd':20}
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT skill_slot,skill_command,used_sp,sp_garbage FROM taiwan_cain_2nd.skill WHERE charac_no=900001')
        assert q.fetchone()=={'skill_slot':b'synthetic-tree-1','skill_command':b'commands','used_sp':30,'sp_garbage':2}
        q.execute('SELECT before_blob,after_blob FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));row=q.fetchone()
        assert json.loads(row['before_blob'])==before
        assert json.loads(row['after_blob'])['remain_sp']==700
    assert client.post(P+'/operations/'+op+'/confirm',json=key).status_code==409
    assert client.get(P+'/character-maintenance/operations/'+op).status_code==404


def test_points_reject_stale_and_rollback_failure(skills,monkeypatch):
    client,s,db,app,root=skills;op=draft(skills)
    with db.connect() as c,c.cursor() as q:
        q.execute("UPDATE taiwan_cain_2nd.skill SET skill_slot='changed-by-game' WHERE charac_no=900001");c.commit()
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'skill-stale-synthetic'}).status_code==409
    op=draft(skills);before=client.get(BASE+'/characters/900001').json()['archive']
    apply=app.state.character_skills.apply_archive
    def fail(*args):apply(*args);raise RuntimeError('synthetic failure before commit')
    monkeypatch.setattr(app.state.character_skills,'apply_archive',fail)
    assert client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'skill-rollback-synthetic'}).status_code==500
    assert client.get(BASE+'/characters/900001').json()['archive']==before
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0


def test_points_model_and_fixed_column_grants():
    import grants
    body={'uid':1,'charac_no':1,'reference':'a'*64,'reason':'合成验证','changes':{'remain_sp':10}}
    assert SkillPointsPreview(**body).changes=={'remain_sp':10}
    for changes in ({'remain_sp':-1},{'remain_sp':True},{'remain_sp':LIMITS['remain_sp']+1},{'remain_sfp_1st':2147483648},{'used_sp':0},{'skill_slot':0}):
        with pytest.raises(ValidationError):SkillPointsPreview(**{**body,'changes':changes})
    sql=grants.character_skills_sql()
    assert 'UPDATE(remain_sp,remain_sp_2nd,remain_sfp_1st,remain_sfp_2nd)' in sql
    assert 'SELECT(skill_tree_index) ON taiwan_cain.charac_info' in sql
    assert 'GRANT ALL' not in sql and 'skill_fair_pvp' not in sql
