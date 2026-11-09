"""Redesigned operator routes against the isolated MySQL 5.7 fixture."""
import json
import time

import pytest

from test_combined_rewards import read, write

P = '/dnf-gm/api/v1'
ID = 'a'*32
NEW_WRITES = [
    ('/campaigns/preview', 'campaigns', 'preview', {
        'name':'fixture', 'status':'active', 'dedupe':'account', 'expected_revision':0,
        'targets':{'mode':'all'}, 'template_id':1, 'template_version':1, 'reason':'fixture'}),
    ('/campaigns/operations/'+ID+'/confirm', 'campaigns', 'confirm', {'idempotency_key':'fixture-campaign-key-001'}),
    ('/campaigns/operations/'+ID+'/cancel', 'campaigns', 'cancel', {}),
    ('/game-backups/preview', 'game_backups', 'preview', {'request_id':ID, 'window_id':'b'*32, 'reason':'fixture'}),
    ('/game-backups/'+ID+'/confirm', 'game_backups', 'confirm', {'fingerprint':'c'*64, 'acknowledge_game_scope':True}),
    ('/game-backups/'+ID+'/copy', 'game_backups', 'followup', {'request_id':'d'*32, 'reason':'fixture'}),
    ('/game-backups/'+ID+'/rehearse', 'game_backups', 'followup', {'request_id':'d'*32, 'reason':'fixture'}),
]


@pytest.mark.parametrize('route,service,method,payload', NEW_WRITES)
def test_new_write_routes_enforce_origin_csrf_recent_auth_before_domain_work(env, monkeypatch, route, service, method, payload):
    client, settings, db, app = env
    called = []
    monkeypatch.setattr(getattr(app.state, service), method, lambda *args: called.append(args) or {'ok':True})
    assert client.post(P+route, json=payload, headers={'Origin':'https://invalid.example'}).status_code == 403
    assert client.post(P+route, json=payload, headers={'X-CSRF-Token':'incorrect'}).status_code == 403
    write(db, 'UPDATE dnf_gm.sessions SET authenticated_at=0')
    response = client.post(P+route, json=payload)
    assert response.status_code == 403 and '重新认证' in response.text and called == []
    write(db, 'UPDATE dnf_gm.sessions SET authenticated_at=%s', (int(time.time()),))
    response = client.post(P+route, json=payload)
    assert response.status_code == 200, response.text
    assert len(called) == 1
    for table in ('operations','audit','game_backup_runs','campaigns'):
        assert not read(db, 'SELECT * FROM dnf_gm.'+table)
    client.cookies.clear()
    assert client.post(P+route, json=payload).status_code == 401 and len(called) == 1


def test_new_read_routes_require_session_and_health_requires_twenty(env):
    client, settings, db, app = env
    assert client.get(P+'/health').status_code == 200
    write(db, 'DELETE FROM dnf_gm.schema_versions WHERE version=20')
    assert client.get(P+'/health').status_code == 503
    client.cookies.clear()
    for route in ('/workbench','/characters/900001/overview','/campaigns','/campaigns/audience-schema',
                  '/campaigns/'+ID,'/campaigns/operations/'+ID,'/game-backups','/game-backups/'+ID):
        assert client.get(P+route).status_code == 401, route


def seed_job(db, job_id, targets):
    write(db, "INSERT INTO dnf_gm.reward_jobs(id,session_hash,fingerprint,request_json,preview_json,status,reason,created_at,expires_at) "
        "VALUES(%s,%s,%s,'{}','{}','paused','fixture',1,300)", (job_id,'c'*64,'d'*64))
    with db.connect() as c, c.cursor() as q:
        q.executemany('INSERT INTO dnf_gm.reward_targets(job_id,ordinal,target_uid,charac_no,target_json,operation_id,status,error_type) '
            'VALUES(%s,%s,900001,%s,\'{}\',%s,%s,%s)',
            [(job_id, ordinal, ordinal, f'{int(job_id,16)+ordinal:032x}', state, error)
             for ordinal, state, error in targets])
        c.commit()


def test_target_filters_have_keyset_pagination_and_job_scoped_error_counts(env):
    client, settings, db, app = env
    job = '1'*32
    seed_job(db, job, [(i,'failed','FixtureError') for i in range(1,53)]+[(i,'committed','') for i in range(53,58)])
    seed_job(db, '2'*32, [(1,'failed','OtherJobError')])
    query = '/reward-jobs/'+job+'/targets?status=failed&error_type=FixtureError'
    response = client.get(P+query); assert response.status_code == 200, response.text
    first = response.json()
    assert len(first['items']) == first['next_after'] == 50
    assert first['counts'] == {'failed':52,'committed':5} and first['errors'] == [{'error_type':'FixtureError','n':52}]
    second = client.get(P+query+'&after=50').json()
    assert [row['ordinal'] for row in second['items']] == [51,52] and second['next_after'] is None
    assert client.get(P+'/reward-jobs/'+job+"/targets", params={'error_type':"x' OR 1=1 --"}).json()['items'] == []
    for tail in ('status=invalid','after=-1','error_type='+'x'*65):
        assert client.get(P+'/reward-jobs/'+job+'/targets?'+tail).status_code == 422


def seed_mail(db, operation_id, *, states=(), item_id=990001, template=42, uid=900001,
              character=900001, created='2026-11-08 16:00:00', unrecorded=0, ordinal_step=1, name='fixture%_'):
    serial = (int(operation_id[-6:],16) % 1_000_000) * 1000
    with db.connect() as c, c.cursor() as q:
        q.execute('INSERT INTO dnf_gm.mail_batches(operation_id,target_uid,charac_no,account_name,character_name,letter_id,'
            'postal_count,recorded_count,history_complete,message,request_json,created_at) VALUES(%s,%s,%s,%s,%s,0,%s,%s,%s,\'fixture\',%s,%s)',
            (operation_id,uid,character,name,name,len(states)+unrecorded,len(states),int(unrecorded==0),json.dumps({'template_id':template}),created))
        for i, state in enumerate(states,1):
            postal = serial+i
            q.execute('INSERT INTO dnf_gm.mail_deliveries(operation_id,ordinal,postal_id,item_id,quantity,gold) VALUES(%s,%s,%s,%s,1,0)',
                (operation_id,i*ordinal_step,postal,item_id))
            if state != 'record_missing':
                q.execute('INSERT INTO taiwan_cain_2nd.postal(postal_id,receive_charac_no,item_id,receive_time,delete_flag) VALUES(%s,%s,%s,%s,%s)',
                    (postal,character,item_id,'2026-11-09 00:00:00' if state=='claimed_marker' else '0000-00-00 00:00:00',int(state=='deleted_marker')))
        c.commit()


def mail_ids(client, **params):
    response = client.get(P+'/mail-center', params=params)
    assert response.status_code == 200, response.text
    return [row['operation_id'] for row in response.json()['items']]


def test_mail_filters_combine_uid_item_template_literal_name_and_beijing_dates(env):
    client, settings, db, app = env
    ids = [f'{i:032x}' for i in range(1,6)]
    for op, created, uid in [(ids[0],'2026-11-08 16:00:00',900001),(ids[1],'2026-11-09 15:59:59',900001),
                             (ids[2],'2026-11-08 15:59:59',900001),(ids[3],'2026-11-09 16:00:00',900001),
                             (ids[4],'2026-11-09 10:00:00',900002)]:
        seed_mail(db,op,states=('unclaimed_marker',),created=created,uid=uid,character=uid)
    params = dict(uid=900001,item_id=990001,template_id=42,q='%_',created_from='2026-11-09',created_to='2026-11-09')
    assert set(mail_ids(client,**params)) == set(ids[:2])
    assert mail_ids(client,**{**params,'item_id':990002}) == []
    assert mail_ids(client,**{**params,'template_id':43}) == []
    assert mail_ids(client,**{**params,'operation_id':ids[4]}) == []
    assert mail_ids(client,**{**params,'q':"' OR 1=1 --"}) == []
    assert client.get(P+'/mail-center',params={'created_from':'2026-11-10','created_to':'2026-11-09'}).status_code == 422
    for query in ('item_id=-1','template_id=-1','receipt=claimed','created_from=not-a-date'):
        assert client.get(P+'/mail-center?'+query).status_code == 422


def test_receipt_summary_distinguishes_missing_deleted_claimed_unrecorded_and_ownership(env):
    client, settings, db, app = env
    states = ('unclaimed_marker','claimed_marker','deleted_marker','record_missing')
    seed_mail(db,ID,states=states,unrecorded=2)
    seed_mail(db,'b'*32,states=('claimed_marker',),uid=900002,character=900002)
    response = client.get(P+'/mail-center?uid=900001'); assert response.status_code == 200, response.text
    data = response.json(); summary = data['items'][0]['receipt_summary']
    assert len(data['items']) == 1 and all(summary[state] == 1 for state in states)
    assert summary['unrecorded'] == 2 and summary['checked_attachments'] == 4
    assert summary['client_verified'] is False and data['receipt_scope'] == summary['scope'] == 'recent_200_attachments'
    for state in states:
        assert mail_ids(client,uid=900001,receipt=state) == [ID]
    assert mail_ids(client,uid=900001,receipt='claimed_marker',operation_id='b'*32) == []


def test_mail_recent_summary_and_receipt_filter_budget_handles_noncontiguous_ordinals(env):
    client, settings, db, app = env
    states = ['claimed_marker','deleted_marker']+['unclaimed_marker']*200
    seed_mail(db,ID,states=states,ordinal_step=10)
    data = client.get(P+'/mail-center?uid=900001').json()['items'][0]['receipt_summary']
    assert data['checked_attachments'] == data['unclaimed_marker'] == data['recent_limit'] == 200
    assert data['has_more'] and data['unrecorded'] == data['claimed_marker'] == data['deleted_marker'] == 0
    assert mail_ids(client,receipt='claimed_marker') == mail_ids(client,receipt='deleted_marker') == []
    assert mail_ids(client,receipt='unclaimed_marker') == [ID]


def test_mail_list_and_details_pagination_enrich_labels_without_catalog_policy_changes(env):
    client, settings, db, app = env
    for i in range(1,52):
        seed_mail(db,f'{i:032x}')
    response = client.get(P+'/mail-center'); assert response.status_code == 200, response.text
    assert len(response.json()['items']) == 50 and response.json()['has_more']
    assert len(client.get(P+'/mail-center?page=2').json()['items']) == 1
    seed_mail(db,ID,states=['unclaimed_marker']*51,item_id=990003)
    before = read(db,'SELECT * FROM dnf_gm.catalog_policy_items')
    response = client.get(P+'/mail-center/'+ID); assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['items']) == data['next_after'] == 50 and data['catalog_state'] == 'ok'
    assert all(row['item']['name'] == '特殊宠物' for row in data['items'])
    assert len(client.get(P+'/mail-center/'+ID+'?after=50').json()['items']) == 1
    assert read(db,'SELECT * FROM dnf_gm.catalog_policy_items') == before
    settings.pvf_sha256 = 'f'*64
    mismatch = client.get(P+'/mail-center/'+ID).json()
    assert mismatch['catalog_state'] == 'mismatch' and mismatch['items'][0]['item']['name'] == '名称未收录'
