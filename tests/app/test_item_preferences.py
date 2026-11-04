import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from dnfgm.item_preferences import ItemPreferences
from dnfgm.catalog import Catalog

P='/dnf-gm/api/v1'


def favorite(c, item_id=990002, enabled=True, sha='a'*64):
    return c.put(P+f'/catalog/{item_id}/favorite',json={'pvf_sha256':sha,'favorite':enabled})


def selected(c, item_id=990002, sha='a'*64):
    return c.post(P+f'/catalog/{item_id}/selection',json={'pvf_sha256':sha})


def collection(c, kind='favorites', page=1):
    r=c.get(P+'/catalog/collections',params={'collection':kind,'page':page})
    assert r.status_code==200,r.text
    return r.json()


def test_favorites_and_recents_are_independent_persistent_metadata_not_rewards(env):
    c,s,db,app=env
    assert collection(c)['total']==collection(c,'recent')['total']==0
    assert favorite(c,item_id=80000,enabled=False).status_code==200
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.item_preferences');assert q.fetchone()['n']==0
    assert favorite(c).json()['favorite'] is True
    saved=collection(c)['items'][0]
    assert saved['id']==990002 and saved['name']=='测试材料' and saved['selected_at'] is None
    assert 'source_path' not in saved
    # Idempotent desired state does not bump ordering on a duplicate request.
    assert favorite(c).json()['favorited_at']==saved['favorited_at']
    assert selected(c).status_code==200
    assert selected(c).status_code==200
    assert collection(c,'recent')['total']==1
    assert favorite(c,enabled=False).status_code==200
    assert collection(c)['total']==0 and collection(c,'recent')['total']==1
    item=c.get(P+'/catalog?q=990002').json()['items'][0]
    assert not item['favorite'] and item['selected_at'] and item['pvf_sha256']=='a'*64
    # Service restarts do not clear selections, as they are not in process memory.
    fresh=ItemPreferences(db,Catalog(s,db))
    assert fresh.list('recent',1)['items'][0]['id']==990002
    with db.connect() as conn,conn.cursor() as q:
        for table in ('operations','audit','mail_batches','mail_deliveries'):
            q.execute('SELECT COUNT(*) n FROM dnf_gm.'+table);assert q.fetchone()['n']==0
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.postal');assert q.fetchone()['n']==0


def test_preference_versions_unknown_items_and_input_validation(env):
    c,s,db,app=env
    assert favorite(c,sha='f'*64).status_code==409
    assert favorite(c,item_id=80000).status_code==404
    assert selected(c,item_id=80000).status_code==404
    assert favorite(c,sha='bad').status_code==422
    assert favorite(c,item_id=4294967296).status_code==422
    assert favorite(c,item_id=0).status_code==422
    assert c.get(P+'/catalog/collections?collection=anything').status_code==422
    assert c.get(P+'/catalog/collections?page=0').status_code==422
    assert favorite(c).status_code==200
    with sqlite3.connect(s.catalog_file) as index:
        index.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('b'*64,))
    assert collection(c)['total']==0
    assert favorite(c).status_code==409
    assert favorite(c,sha='b'*64).status_code==200
    assert collection(c)['items'][0]['pvf_sha256']=='b'*64
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.item_preferences');assert q.fetchone()['n']==2


def test_collection_keeps_disabled_and_missing_items_distinct_and_removable(env):
    c,s,db,app=env
    favorite(c)
    with db.connect() as conn,conn.cursor() as q:
        q.execute('INSERT INTO dnf_gm.catalog_policy_items(pvf_sha256,item_id,enabled,reason,revision) VALUES(%s,990002,0,%s,1)',('a'*64,'管理员停用'));conn.commit()
    d=collection(c)['items'][0]
    assert d['favorite'] and not d['sendable'] and d['policy_state']=='blocked'
    with sqlite3.connect(s.catalog_file) as index:
        index.execute('DELETE FROM items WHERE id=990002')
    d=collection(c)['items'][0]
    assert not d['sendable'] and d['name']=='索引中已不存在'
    assert favorite(c,enabled=False).status_code==200
    assert collection(c)['total']==0


def test_collection_pagination_and_stable_tie_ordering(env):
    c,s,db,app=env
    with sqlite3.connect(s.catalog_file) as index:
        index.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',
                          [(i,f'物品{i}','material',1,0,0,1,0,'fixture') for i in range(1,76)])
    with db.connect() as conn,conn.cursor() as q:
        q.executemany('INSERT INTO dnf_gm.item_preferences VALUES(%s,%s,1,%s,%s)',
                      [('a'*64,i,'2026-11-04 00:00:00','2026-11-04 01:00:00') for i in range(1,76)])
        conn.commit()
    for kind in ('favorites','recent'):
        a,b=collection(c,kind,1),collection(c,kind,2)
        assert a['total']==75 and len(a['items'])==50 and len(b['items'])==25
        assert [i['id'] for i in a['items']+b['items']]==list(range(75,0,-1))
        assert collection(c,kind,3)['items']==[]


def test_preferences_do_not_invalidate_preview_or_change_quantity_rules(env):
    c,s,db,app=env
    payload={'action':'mail','uid':900001,'charac_no':900001,'items':[{'id':990002,'quantity':100000}], 'reason':'preference snapshot fixture'}
    r=c.post(P+'/operations/preview',json=payload);assert r.status_code==200,r.text
    op=r.json()['operation_id']
    assert favorite(c).status_code==selected(c).status_code==200
    r=c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':'preference-no-reward-changes'})
    assert r.status_code==200,r.text
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT add_info FROM taiwan_cain_2nd.postal');assert q.fetchone()['add_info']==100000


def test_favorite_and_selection_concurrent_updates_preserve_both_fields(env):
    c,s,db,app=env
    preferences=ItemPreferences(db,Catalog(s,db))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(preferences.update,990002,'a'*64,True),
                 executor.submit(preferences.update,990002,'a'*64)]
        for future in futures:future.result(timeout=10)
    item=collection(c)['items'][0]
    assert item['favorite'] and item['selected_at']
    assert collection(c,'recent')['total']==1


def test_preferences_require_session_origin_and_csrf(env):
    c,s,db,app=env
    c.headers['Origin']='https://attacker.invalid'
    assert favorite(c).status_code==403 and selected(c).status_code==403
    c.headers['Origin']='http://testserver';c.headers['X-CSRF-Token']='bad'
    assert favorite(c).status_code==403 and selected(c).status_code==403
    c.cookies.clear()
    assert c.get(P+'/catalog/collections').status_code==401
    assert favorite(c).status_code==401 and selected(c).status_code==401


def test_preference_migration_repeats_without_losing_existing_records(env):
    c,s,db,app=env
    favorite(c);selected(c)
    migration=Path(__file__).resolve().parents[2]/'migrations/005-item-preferences.sql'
    with db.connect() as conn,conn.cursor() as q:
        for statement in migration.read_text().split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    assert collection(c)['total']==collection(c,'recent')['total']==1
