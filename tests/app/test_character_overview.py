"""Lightweight role workbench SQL and honest recent delivery sampling."""
from test_character_detail import seed
from test_combined_rewards import read, write
from test_mail_center import deliver

P = '/dnf-gm/api/v1'


def test_overview_is_lightweight_owner_bound_and_does_not_write(env):
    client, settings, db = seed(env)
    write(db, "INSERT INTO dnf_gm.support_cases(case_id,uid,charac_no,target_json,title,category,description,"
        "status,revision,created_at,updated_at) VALUES(%s,900001,NULL,'{}','账号问题','other','fixture','open',1,1,1),"
        "(%s,900001,900001,'{}','角色问题','other','fixture','in_progress',1,2,2),"
        "(%s,900002,900002,'{}','其他玩家','other','fixture','open',1,3,3)", ('a'*32, 'b'*32, 'c'*32))
    response = client.get(P+'/characters/900001/overview?uid=900002')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['character']['uid'] == data['account']['uid'] == 900001
    assert data['wealth']['gold'] == 150460 and data['play_state']['used_fatigue'] == 7
    assert data['equipment']['items'][0]['name'] == '测试装备'
    assert data['backpack_summary']['occupied_slots'] == 2
    assert data['attributes'] == [] and 'maxHP' not in data['character']
    assert data['support_summary']['open_count'] == data['support_summary']['in_progress_count'] == 1
    assert {i['scope'] for i in data['support_summary']['items']} == {'account', 'character'}
    assert 'warehouse' not in data and 'appearance' not in data and data['read_only']
    assert not read(db, 'SELECT * FROM dnf_gm.operations') and not read(db, 'SELECT * FROM dnf_gm.audit')
    assert client.get(P+'/characters/2147483647/overview').status_code == 404
    client.cookies.clear(); assert client.get(P+'/characters/900001/overview').status_code == 401


def test_mail_sample_uses_latest_two_hundred_attachments_with_stable_ordinal_order(env):
    client, settings, db, app = env
    older, _ = deliver(client, 201)
    newer, _ = deliver(client, 1)
    write(db, "UPDATE dnf_gm.mail_batches SET created_at=IF(operation_id=%s,'2026-11-08 12:00:00','2026-11-09 12:00:00')", (older,))
    records = read(db, 'SELECT ordinal,postal_id FROM dnf_gm.mail_deliveries WHERE operation_id=%s ORDER BY ordinal', (older,))
    write(db, 'UPDATE taiwan_cain_2nd.postal SET receive_time=UTC_TIMESTAMP() WHERE postal_id=%s', (records[0]['postal_id'],))
    write(db, 'UPDATE taiwan_cain_2nd.postal SET delete_flag=1 WHERE postal_id=%s', (records[1]['postal_id'],))
    response = client.get(P+'/characters/900001/overview'); assert response.status_code == 200, response.text
    summary = response.json()['mail_summary']
    assert summary['checked_attachments'] == summary['unclaimed_marker'] == 200 and summary['has_more']
    assert summary['claimed_marker'] == summary['deleted_marker'] == summary['record_missing'] == 0
    assert summary['scope'] == 'recent_200_attachments' and summary['client_verified'] is False


def test_missing_storage_and_broken_storage_remain_unknown_in_overview(env):
    client, settings, db, app = env
    data = client.get(P+'/characters/900001/overview').json()
    assert data['wealth']['state'] == data['equipment']['state'] == data['backpack_summary']['state'] == 'missing'
    assert data['wealth']['gold'] is None and data['backpack_summary']['occupied_slots'] is None
    write(db, 'INSERT INTO taiwan_cain_2nd.inventory VALUES(900001,0,0,0,%s,%s)', (b'corrupt', b'corrupt'))
    data = client.get(P+'/characters/900001/overview').json()
    assert data['wealth']['gold'] == 0 and data['equipment']['state'] == data['backpack_summary']['state'] == 'invalid'
    assert data['backpack_summary']['occupied_slots'] is None
