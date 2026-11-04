"""Receipt ledger is atomic, paginated and honest about missing game rows."""
import uuid
import pytest
from test_mail_gold import P, preview, confirm


def deliver(c, quantity=103):
    r=preview(c,items=[{'id':990001,'quantity':quantity}],gold=123)
    assert r.status_code==200,r.text
    op=r.json()['operation_id']; key=uuid.uuid4().hex
    result=confirm(c,op,key)
    assert result.status_code==200,result.text
    return op,key


def test_all_copies_paginated_without_duplicate_and_repeat_safe(env):
    c,s,db,app=env
    op,key=deliver(c)
    assert confirm(c,op,key).status_code==200
    listed=c.get(P+'/mail-center?uid=900001').json()
    assert len(listed['items'])==1 and listed['items'][0]['postal_count']==103
    assert not c.get(P+'/mail-center?charac_no=900002').json()['items']
    all_rows=[];after=0
    while True:
        r=c.get(P+f'/mail-center/{op}?after={after}')
        assert r.status_code==200,r.text
        page=r.json();all_rows+=page['items']
        assert page['batch']['history_complete']==1
        assert page['client_verified'] is False
        after=page['next_after']
        if after is None:break
    assert [r['ordinal'] for r in all_rows]==list(range(1,104))
    assert len(set(r['postal_id'] for r in all_rows))==103
    assert all(r['quantity']==1 for r in all_rows)
    assert sum(r['gold'] for r in all_rows)==123


def test_claimed_deleted_missing_and_unknown_never_conflated(env):
    c,s,db,app=env;op,key=deliver(c,4)
    records=c.get(P+'/mail-center/'+op).json()['items']
    with db.connect() as con,con.cursor() as q:
        q.execute('UPDATE taiwan_cain_2nd.postal SET receive_time=UTC_TIMESTAMP() WHERE postal_id=%s',(records[0]['postal_id'],))
        q.execute('UPDATE taiwan_cain_2nd.postal SET delete_flag=1 WHERE postal_id=%s',(records[1]['postal_id'],))
        q.execute('DELETE FROM taiwan_cain_2nd.postal WHERE postal_id=%s',(records[2]['postal_id'],));con.commit()
    actual=c.get(P+'/mail-center/'+op).json()['items']
    assert [x['receipt_state'] for x in actual]==['claimed_marker','deleted_marker','record_missing','unclaimed_marker']


@pytest.mark.parametrize('table',['mail_batches','mail_deliveries','audit'])
def test_ledger_failure_rolls_back_entire_delivery(env,table):
    c,s,db,app=env
    with db.connect() as con,con.cursor() as q:
        q.execute(f"CREATE TRIGGER dnf_gm.fail_center BEFORE INSERT ON dnf_gm.{table} FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture failure'")
    op=preview(c).json()['operation_id']
    assert confirm(c,op).status_code==500
    with db.connect() as con,con.cursor() as q:
        for t in ('dnf_gm.mail_batches','dnf_gm.mail_deliveries','taiwan_cain_2nd.postal','taiwan_cain_2nd.letter'):
            q.execute('SELECT COUNT(*) AS n FROM '+t);assert q.fetchone()['n']==0


def test_auth_input_and_read_only(env):
    c,s,db,app=env;op,_=deliver(c,1)
    assert c.get(P+'/mail-center?operation_id=bad').status_code==422
    assert c.get(P+'/mail-center/'+op+'?after=-1').status_code==422
    assert c.get(P+'/mail-center/'+'f'*32).status_code==404
    c.cookies.clear()
    assert c.get(P+'/mail-center').status_code==401
    assert c.get(P+'/mail-center/'+op).status_code==401


def test_legacy_history_import_is_complete_beyond_twenty_and_idempotent(env):
    c,s,db,app=env;op,key=deliver(c,60)
    with db.connect() as con,con.cursor() as q:
        q.execute('DELETE FROM dnf_gm.mail_deliveries');q.execute('DELETE FROM dnf_gm.mail_batches');con.commit()
    service=app.state.service.mail_center
    assert service.import_history()['imported']==1
    assert service.import_history()['imported']==0
    data=c.get(P+'/mail-center/'+op).json()
    assert data['batch']['history_complete']==1
    assert data['batch']['postal_count']==60 and data['batch']['recorded_count']==60
    assert data['batch']['request']['items']==[{'id':990001,'quantity':60}]
    assert data['next_after']==50


def test_legacy_deleted_rows_are_reported_incomplete(env):
    c,s,db,app=env;op,key=deliver(c,3)
    with db.connect() as con,con.cursor() as q:
        q.execute('DELETE FROM dnf_gm.mail_deliveries');q.execute('DELETE FROM dnf_gm.mail_batches')
        q.execute('DELETE FROM taiwan_cain_2nd.postal ORDER BY postal_id LIMIT 1');con.commit()
    app.state.service.mail_center.import_history()
    data=c.get(P+'/mail-center/'+op).json()['batch']
    assert data['history_complete']==0 and data['recorded_count']==2 and data['postal_count']==3


def test_missing_or_nontransactional_ledger_fails_closed_before_game_write(env):
    c,s,db,app=env
    with db.connect() as con,con.cursor() as q:
        q.execute('ALTER TABLE dnf_gm.mail_deliveries ENGINE=MyISAM')
    op=preview(c).json()['operation_id']
    assert confirm(c,op).status_code==409
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT COUNT(*) AS n FROM taiwan_cain_2nd.postal');assert q.fetchone()['n']==0


def test_legacy_equipment_without_mail_kind_imports_one_copy_per_row(env):
    import json
    c,s,db,app=env;op,key=deliver(c,2)
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT result_json FROM dnf_gm.audit WHERE operation_id=%s',(op,))
        result=json.loads(q.fetchone()['result_json'])
        for item in result['items']['items']:
            item.pop('mail_kind',None)
        q.execute('UPDATE dnf_gm.audit SET result_json=%s WHERE operation_id=%s',(json.dumps(result),op))
        q.execute('DELETE FROM dnf_gm.mail_deliveries');q.execute('DELETE FROM dnf_gm.mail_batches');con.commit()
    app.state.service.mail_center.import_history()
    records=c.get(P+'/mail-center/'+op).json()['items']
    assert [r['quantity'] for r in records]==[1,1]


def test_migration_is_repeatable_without_losing_delivery_evidence(env):
    from pathlib import Path
    c,s,db,app=env;op,key=deliver(c,1)
    migration=(Path(__file__).resolve().parents[2]/'migrations/004-mail-center.sql').read_text()
    with db.connect() as con,con.cursor() as q:
        for statement in migration.split(';'):
            if statement.strip():q.execute(statement)
        con.commit()
    assert c.get(P+'/mail-center/'+op).json()['batch']['recorded_count']==1
