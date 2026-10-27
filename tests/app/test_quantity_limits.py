"""Only a reviewed per-id maintenance cap can fill missing ordinary-item metadata."""
from contextlib import closing
import json
import sqlite3
import uuid

import pytest
from test_catalog_policy import add_items, apply, scalar
from test_application import mail, confirm


def configure(settings, cap=1000):
    settings.mail_stack_limits={'992000':dict(pvf_sha256=settings.pvf_sha256,stack_limit=cap,reason='synthetic quantity trial')}


def test_single_missing_cap_trial_keeps_other_policies_and_bounds(env):
    client, settings, db, app = env
    add_items(settings, 1)
    configure(settings)
    before=client.get('/dnf-gm/api/v1/catalog?allowed_only=1').json()['total']
    assert before==2
    apply(client,item_id=992000,reason='explicit single fixture item')
    item=client.get('/dnf-gm/api/v1/catalog?q=992000').json()['items'][0]
    assert item['sendable'] and item['stack_limit']==1000 and item['indexed_stack_limit']==0
    assert item['policy_state']=='trial' and not item['verification_evidence']
    assert item['quantity_limit_source']=='maintenance-trial'
    assert client.get('/dnf-gm/api/v1/catalog?allowed_only=1').json()['total']==before+1
    assert not client.get('/dnf-gm/api/v1/catalog?q=991000').json()['items'][0]['sendable']
    assert not client.get('/dnf-gm/api/v1/catalog?q=990003').json()['items'][0]['sendable']
    assert mail(client,[{'id':992000,'quantity':1001}]).status_code==422
    preview=mail(client,[{'id':992000,'quantity':1000}]);assert preview.status_code==200,preview.text
    result=confirm(client,preview.json()['operation_id'],uuid.uuid4().hex);assert result.status_code==200,result.text
    assert result.json()['client_verified'] is False
    with db.connect() as con,con.cursor() as cursor:
        cursor.execute('SELECT item_id,add_info,endurance FROM taiwan_cain_2nd.postal')
        assert cursor.fetchone()==dict(item_id=992000,add_info=1000,endurance=0)
    apply(client,item_id=992000,enabled=False)
    assert mail(client,[{'id':992000,'quantity':1}]).status_code==422


def test_quantity_trial_never_bypasses_specials_or_pvf(env):
    client, settings, db, app=env
    add_items(settings,1);configure(settings)
    settings.mail_stack_limits['990003']=dict(pvf_sha256=settings.pvf_sha256,stack_limit=1000,reason='synthetic special must refuse')
    with sqlite3.connect(settings.catalog_file) as index:
        index.execute('UPDATE items SET stack_limit=0 WHERE id=990003')
    from test_catalog_policy import policy
    assert policy(client,item_id=990003).status_code==422
    settings.mail_stack_limits['992000']['pvf_sha256']='b'*64
    assert policy(client,item_id=992000).status_code==422


def test_cap_change_invalidates_pending_mail_and_verified_label(env):
    client, settings, db, app=env
    add_items(settings,1);configure(settings)
    apply(client,item_id=992000)
    preview=mail(client,[{'id':992000,'quantity':500}]).json()['operation_id']
    settings.mail_stack_limits['992000']['stack_limit']=100
    assert confirm(client,preview,uuid.uuid4().hex).status_code in (409,422)
    assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.postal')==0
    with db.connect() as con,con.cursor() as cursor:
        cursor.execute("UPDATE dnf_gm.catalog_policy_items SET verification_evidence='synthetic evidence' WHERE item_id=992000");con.commit()
    assert client.get('/dnf-gm/api/v1/catalog?state=verified').json()['total']==0
    assert client.get('/dnf-gm/api/v1/catalog?q=992000').json()['items'][0]['policy_state']=='trial'


def test_quantity_trial_sql_and_streaming_filters_agree(env):
    client, settings, db, app=env
    add_items(settings,1);configure(settings);apply(client,item_id=992000)
    catalog=app.state.service.catalog
    with db.connect() as con,con.cursor() as cursor,closing(catalog.connect()) as index:
        _,overrides=catalog.policy(cursor,settings.pvf_sha256)
        for state in ('','trial','verified','blocked'):
            for allowed_only in (False,True):
                filters=dict(q='',category='',state=state,allowed_only=allowed_only)
                expected=[i['id'] for i in catalog.rows(index,filters,overrides)]
                result=catalog.search(**filters)
                assert result['total']==len(expected)
                assert [i['id'] for i in result['items']]==expected


def test_unlimited_single_trial_uses_signed_int_storage_bound_only(env):
    client, settings, db, app=env
    add_items(settings,1);configure(settings,None);apply(client,item_id=992000)
    item=client.get('/dnf-gm/api/v1/catalog?q=992000').json()['items'][0]
    assert item['quantity_unlimited'] and item['stack_limit']==2147483647
    assert client.get('/dnf-gm/api/v1/catalog?allowed_only=1').json()['total']==3
    assert mail(client,[{'id':992000,'quantity':2147483648}]).status_code==422
    assert mail(client,[{'id':990002,'quantity':1000001}]).status_code==422
    for count in (1000001,2147483647):
        preview=mail(client,[{'id':992000,'quantity':count}]);assert preview.status_code==200,preview.text
        result=confirm(client,preview.json()['operation_id'],uuid.uuid4().hex);assert result.status_code==200,result.text
    with db.connect() as con,con.cursor() as cursor:
        cursor.execute('SELECT add_info FROM taiwan_cain_2nd.postal ORDER BY postal_id')
        assert [row['add_info'] for row in cursor.fetchall()]==[1000001,2147483647]
