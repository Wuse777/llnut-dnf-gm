"""Mileage and every indexed mail type, using synthetic isolated game data."""
import json
from pathlib import Path
import sqlite3
import uuid

import pytest
from test_application import P, preview, confirm, mail
from test_catalog_policy import scalar


def mileage(client, **changes):
    return preview(client, currency='mileage', **changes)


def test_mileage_initializes_missing_row_and_is_idempotent(env):
    client, _, db, _ = env
    assert client.get(P+'/accounts/900001').json()['mileage'] == 0
    assert client.get(P+'/accounts').json()['items'][0]['mileage'] == 0
    p = mileage(client, charac_no=900001)
    assert p.status_code == 200, p.text
    assert p.json()['preview']['before'] == 0
    op, key = p.json()['operation_id'], uuid.uuid4().hex
    result = confirm(client, op, key)
    assert result.status_code == 200, result.text
    assert result.json()['currency'] == 'mileage' and result.json()['after'] == 100
    assert confirm(client, op, key).json() == result.json()
    assert scalar(db, 'SELECT miles FROM d_taiwan.member_miles') == 100
    assert scalar(db, 'SELECT daily_miles FROM d_taiwan.member_miles') == 0
    assert scalar(db, 'SELECT cera FROM taiwan_billing.cash_cera') == 1000
    assert scalar(db, 'SELECT cera_point FROM taiwan_billing.cash_cera_point') == 1000
    assert scalar(db, 'SELECT COUNT(*) FROM dnf_gm.audit') == 1
    assert client.get(P+'/operations/'+op).json()['result'] == result.json()


def test_mileage_debit_limits_stale_balance_and_owner(env):
    client, _, db, _ = env
    with db.connect() as c, c.cursor() as q:
        q.execute('INSERT INTO d_taiwan.member_miles VALUES(900001,250,7)')
        c.commit()
    assert mileage(client, delta=-251).status_code == 422
    assert mileage(client, charac_no=900002).status_code == 409
    p = mileage(client, delta=-250)
    assert confirm(client, p.json()['operation_id']).json()['after'] == 0
    assert scalar(db, 'SELECT daily_miles FROM d_taiwan.member_miles') == 7
    a = mileage(client)
    b = mileage(client)
    assert confirm(client, a.json()['operation_id'], uuid.uuid4().hex).status_code == 200
    assert confirm(client, b.json()['operation_id'], uuid.uuid4().hex).status_code == 409
    with db.connect() as c, c.cursor() as q:
        q.execute('UPDATE d_taiwan.member_miles SET miles=2147483647')
        c.commit()
    assert mileage(client, delta=1).status_code == 422


def test_mileage_creation_rolls_back_with_audit(env):
    client, _, db, _ = env
    op = mileage(client).json()['operation_id']
    with db.connect() as c, c.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.fail_reward_audit BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'")
        c.commit()
    assert confirm(client, op).status_code == 500
    assert scalar(db, 'SELECT COUNT(*) FROM d_taiwan.member_miles') == 0
    assert client.get(P+'/operations/'+op).json()['status'] == 'preview'


def seed_specials(settings):
    with sqlite3.connect(settings.catalog_file) as c:
        c.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)', [
            (993001,'时装','special',1,0,0,0,0,'equipment/character/avatar/coat.equ'),
            (993002,'宠物','special',1,0,0,0,0,'equipment/creature/test.equ'),
            (993003,'宠物装备','special',1,0,0,0,0,'equipment/creature/artifact/test.equ'),
            (993004,'特殊道具','special',1,0,0,0,0,'stackable/cash/creature/food.stk'),
        ])
        c.execute('INSERT INTO metadata VALUES(?,?)', ('creature_types',json.dumps({'993002':1,'993003':0})))


def test_all_indexed_types_deliver_with_atomic_storage_records(env):
    client, settings, db, _ = env
    seed_specials(settings)
    items = client.get(P+'/catalog?allowed_only=1').json()
    assert items['total'] == 7 and all(i['sendable'] for i in items['items'])
    special = {i['id']:i for i in items['items'] if i['id'] >= 993001}
    assert [special[i]['mail_kind'] for i in sorted(special)] == ['avatar','creature','creature','stackable']
    assert all(i['stack_limit'] == 2147483647 and i['quantity_unlimited'] for i in special.values())
    assert mail(client, [{'id':993001,'quantity':2}]).status_code == 200
    p = mail(client, [{'id':i,'quantity':1} for i in special], gold=99)
    assert p.status_code == 200, p.text
    op, key = p.json()['operation_id'], uuid.uuid4().hex
    result = confirm(client, op, key)
    assert result.status_code == 200, result.text
    assert confirm(client, op, key).json() == result.json()
    with db.connect() as c, c.cursor() as q:
        q.execute('SELECT item_id,add_info,avata_flag,creature_flag,gold FROM taiwan_cain_2nd.postal ORDER BY postal_id')
        rows = q.fetchall()
        q.execute('SELECT ui_id,it_id,stat,LENGTH(jewel_socket) AS sockets FROM taiwan_cain_2nd.user_items')
        avatar = q.fetchone()
        q.execute('SELECT ui_id,it_id,creature_type FROM taiwan_cain_2nd.creature_items ORDER BY ui_id')
        creatures = q.fetchall()
    assert rows[0]['avata_flag'] == 1 and rows[0]['add_info'] == avatar['ui_id']
    assert avatar['it_id'] == 993001 and avatar['stat'] == 2 and avatar['sockets'] == 30
    assert [x['creature_type'] for x in creatures] == [1,0]
    assert all(rows[n+1]['creature_flag'] == 1 and rows[n+1]['add_info'] == x['ui_id'] for n,x in enumerate(creatures))
    assert rows[3]['add_info'] == 1 and rows[3]['creature_flag'] == 0
    assert [r['gold'] for r in rows] == [99,0,0,0]


def test_special_storage_rolls_back_on_failed_postal(env):
    client, settings, db, _ = env
    seed_specials(settings)
    op = mail(client, [{'id':993001,'quantity':1},{'id':993002,'quantity':1}]).json()['operation_id']
    with db.connect() as c, c.cursor() as q:
        q.execute("CREATE TRIGGER taiwan_cain_2nd.fail_postal BEFORE INSERT ON taiwan_cain_2nd.postal FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'")
        c.commit()
    assert confirm(client, op).status_code == 500
    for table in ('user_items','creature_items','letter','postal'):
        assert scalar(db, 'SELECT COUNT(*) FROM taiwan_cain_2nd.'+table) == 0


def test_all_items_migration_runs_once_and_preserves_later_disables(env):
    _, settings, db, _ = env
    migration = (Path(__file__).resolve().parents[2]/'migrations/003-all-items.sql').read_text(encoding='utf-8')
    with db.connect() as c, c.cursor() as q:
        q.execute('DELETE FROM dnf_gm.schema_versions WHERE version=3')
        q.execute('INSERT INTO dnf_gm.catalog_policy_items VALUES(%s,990003,0,%s,0,%s)', (settings.pvf_sha256,'fixture disabled',''))
        c.commit()
        for statement in migration.split(';'):
            if statement.strip(): q.execute(statement)
        assert scalar(db, 'SELECT enabled FROM dnf_gm.catalog_policy_items') == 1
        q.execute('UPDATE dnf_gm.catalog_policy_items SET enabled=0')
        c.commit()
        for statement in migration.split(';'):
            if statement.strip(): q.execute(statement)
    assert scalar(db, 'SELECT enabled FROM dnf_gm.catalog_policy_items') == 0


def test_multiple_equipment_and_special_copies_keep_native_linkage_and_gold_once(env):
    client,settings,db,_=env
    seed_specials(settings)
    request=[{'id':990001,'quantity':2},{'id':993001,'quantity':3},
             {'id':993002,'quantity':2},{'id':993003,'quantity':2},
             {'id':993004,'quantity':1000001}]
    p=mail(client,request,gold=123);assert p.status_code==200,p.text
    op,key=p.json()['operation_id'],uuid.uuid4().hex
    result=confirm(client,op,key);assert result.status_code==200,result.text
    assert result.json()['postal_count']==10 and not result.json()['postal_ids_truncated']
    assert confirm(client,op,key).json()==result.json()
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT item_id,add_info,endurance,avata_flag,creature_flag,gold FROM taiwan_cain_2nd.postal ORDER BY postal_id')
        rows=q.fetchall()
        q.execute('SELECT ui_id FROM taiwan_cain_2nd.user_items ORDER BY ui_id');avatars=q.fetchall()
        q.execute('SELECT ui_id FROM taiwan_cain_2nd.creature_items ORDER BY ui_id');creatures=q.fetchall()
    assert [r['item_id'] for r in rows]==[990001]*2+[993001]*3+[993002]*2+[993003]*2+[993004]
    assert all(r['add_info']==0 and r['endurance']==20 for r in rows[:2])
    assert [r['add_info'] for r in rows[2:5]]==[r['ui_id'] for r in avatars]
    assert [r['add_info'] for r in rows[5:9]]==[r['ui_id'] for r in creatures]
    assert rows[-1]['add_info']==1000001
    assert [r['gold'] for r in rows]==[123]+[0]*9


def test_expanded_delivery_does_not_materialize_unbounded_result_ids(env):
    client,_,db,_=env
    p=mail(client,[{'id':990001,'quantity':25}],gold=5)
    assert p.status_code==200,p.text
    result=confirm(client,p.json()['operation_id'],uuid.uuid4().hex)
    assert result.status_code==200,result.text
    assert result.json()['postal_count']==25 and result.json()['postal_ids_truncated']
    assert len(result.json()['postal_ids'])==20
    assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.postal')==25
    status=client.get(P+'/operations/'+p.json()['operation_id']).json()
    assert status['delivery_records_truncated'] is True
    assert '前20条' in status['delivery_note']


def test_failure_midway_through_multiple_copies_rolls_back_everything(env):
    client,settings,db,_=env
    seed_specials(settings)
    p=mail(client,[{'id':993001,'quantity':3}])
    assert p.status_code==200,p.text
    with db.connect() as c,c.cursor() as q:
        q.execute("CREATE TRIGGER taiwan_cain_2nd.fail_second_copy BEFORE INSERT ON taiwan_cain_2nd.postal FOR EACH ROW BEGIN IF (SELECT COUNT(*) FROM taiwan_cain_2nd.postal)>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic second-copy failure'; END IF; END")
        c.commit()
    assert confirm(client,p.json()['operation_id'],uuid.uuid4().hex).status_code==500
    for table in ('user_items','creature_items','letter','postal'):
        assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.'+table)==0
