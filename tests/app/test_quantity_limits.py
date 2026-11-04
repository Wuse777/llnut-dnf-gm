"""PVF caps are informational; every reward uses only the storage boundary."""
from contextlib import closing
import sqlite3
import uuid

import pytest
from test_catalog_policy import add_items, apply, scalar
from test_application import P, mail, preview, confirm


@pytest.mark.parametrize('indexed_cap', [0, -1, 1, 99, 1000000])
def test_all_stack_caps_accept_larger_quantities_and_commit_once(env, indexed_cap):
    client, settings, db, app = env
    add_items(settings, 1)
    with sqlite3.connect(settings.catalog_file) as index:
        index.execute('UPDATE items SET stack_limit=? WHERE id=992000', (indexed_cap,))
    # Legacy configuration must not silently retain the old restriction.
    settings.mail_stack_limits={'992000':dict(pvf_sha256='b'*64,stack_limit=1,reason='legacy cap')}
    item=client.get(P+'/catalog?q=992000').json()['items'][0]
    assert item['sendable'] and item['stack_limit']==2147483647
    assert item['indexed_stack_limit']==indexed_cap
    assert item['quantity_unlimited'] and item['quantity_limit_source']=='storage-only'
    assert item['policy_state']=='trial' and not item['verification_evidence']
    for count in (1000001,2147483647):
        preview=mail(client,[{'id':992000,'quantity':count}]);assert preview.status_code==200,preview.text
        op,key=preview.json()['operation_id'],uuid.uuid4().hex
        result=confirm(client,op,key);assert result.status_code==200,result.text
        assert confirm(client,op,key).json()==result.json()
        assert result.json()['client_verified'] is False
    with db.connect() as con,con.cursor() as cursor:
        cursor.execute('SELECT add_info FROM taiwan_cain_2nd.postal ORDER BY postal_id')
        assert [row['add_info'] for row in cursor.fetchall()]==[1000001,2147483647]
    apply(client,item_id=992000,enabled=False)
    assert mail(client,[{'id':992000,'quantity':2}]).status_code==422


@pytest.mark.parametrize('count', [0,-1,True,1.5,2147483648])
def test_native_quantity_representation_is_still_checked(env,count):
    client,settings,db,app=env
    assert mail(client,[{'id':990002,'quantity':count}]).status_code==422
    assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.postal')==0


def test_legacy_cap_changes_no_longer_invalidate_pending_preview(env):
    client,settings,db,app=env
    add_items(settings,1)
    settings.mail_stack_limits={'992000':dict(pvf_sha256=settings.pvf_sha256,stack_limit=1000,reason='legacy')}
    preview=mail(client,[{'id':992000,'quantity':500}]).json()['operation_id']
    settings.mail_stack_limits['992000']['stack_limit']=1
    assert confirm(client,preview,uuid.uuid4().hex).status_code==200
    assert scalar(db,'SELECT add_info FROM taiwan_cain_2nd.postal')==500


def test_gift_and_mail_share_unlimited_quantity_rules(env):
    client,settings,db,app=env
    add_items(settings,1)
    body=dict(name='No PVF quantity cap',enabled=True,expected_version=0,
              items=[dict(id=992000,quantity=2147483647),dict(id=990001,quantity=3)])
    gift=client.post(P+'/gift-templates',json=body)
    assert gift.status_code==200,gift.text
    p=preview(client,action='mail',currency=None,delta=None,charac_no=900001,items=[],
              template_id=gift.json()['id'],template_version=gift.json()['version'])
    assert p.status_code==200,p.text
    result=confirm(client,p.json()['operation_id'],uuid.uuid4().hex)
    assert result.status_code==200,result.text
    assert result.json()['postal_count']==4
    assert scalar(db,'SELECT add_info FROM taiwan_cain_2nd.postal WHERE item_id=992000')==2147483647
    assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.postal WHERE item_id=990001')==3


def test_quantity_sql_and_streaming_filters_agree(env):
    client,settings,db,app=env
    add_items(settings,1)
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
