import sqlite3
import pytest
from dnfgm.outfit_recipe import canonical_outfit_recipe

P='/dnf-gm/api/v1'


def seed(env,rows=None):
    c,s,db,app=env
    with sqlite3.connect(s.catalog_file) as index:
        index.execute('CREATE TABLE equipment_details(item_id INTEGER PRIMARY KEY,part_code TEXT,rarity INTEGER)')
        index.executemany('INSERT INTO equipment_details VALUES(?,?,?)',[(995001,'[coat avatar]',0),(995002,'[hat avatar]',0),(995003,'[coat avatar]',0)])
        index.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',[(identity,'合成时装','equipment',1,1,0,0,0,'equipment/avatar/synthetic.equ') for identity in (995001,995002,995003)])
    with db.connect() as conn,conn.cursor() as q:
        for char,slot,item,stat,expires,clear,color1,color2 in (rows or [(900001,8,995001,0,'2099-01-01',0,0,0),(900001,0,995002,0,'2099-01-01',0,0,0)]):
            q.execute('INSERT INTO taiwan_cain_2nd.user_items(charac_no,slot,it_id,stat,expire_date,clear_avatar_id,color1,color2,jewel_socket,reg_date) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())',(char,slot,item,stat,expires,clear,color1,color2,b''))
        conn.commit()
    return c,s,db,app


def test_exact_saved_avatar_recipe_and_owner_scope_are_read_only(env,monkeypatch):
    c,s,db,app=seed(env)
    calls=[]
    def preview(sha,job,recipe):
        calls.append((sha,job,recipe));return {'state':'ready','url':'fixture','source_kind':'saved_avatar_outfit'}
    monkeypatch.setattr(app.state.service.catalog.assets,'outfit_preview',preview)
    with db.connect() as conn,conn.cursor() as q:
        for char,slot,stat,expires in [(900002,1,0,'2099-01-01'),(900001,10,0,'2099-01-01'),(900001,1,2,'2099-01-01'),(900001,2,0,'2000-01-01')]:
            q.execute('INSERT INTO taiwan_cain_2nd.user_items(charac_no,slot,it_id,stat,expire_date,jewel_socket,reg_date) VALUES(%s,%s,995003,%s,%s,%s,NOW())',(char,slot,stat,expires,b''))
        conn.commit()
    result=c.get(P+'/characters/900001?uid=900002')
    assert result.status_code==200,result.text
    data=result.json();recipe,sha=canonical_outfit_recipe(data['character']['job'],[{'slot':'[coat avatar]','id':995001},{'slot':'[hat avatar]','id':995002}])
    assert data['outfit']['state']=='ok' and data['outfit']['items']==recipe['items']
    assert calls==[(s.pvf_sha256,data['character']['job'],sha)] and data['outfit_preview']['state']=='ready'
    with db.connect() as conn,conn.cursor() as q:
        for table in ('operations','audit'):
            q.execute('SELECT COUNT(*) n FROM dnf_gm.'+table);assert q.fetchone()['n']==0
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.user_items');assert q.fetchone()['n']==6


@pytest.mark.parametrize('modifier',['clear_avatar_id','color1','color2','duplicate_slot','duplicate_part','unknown_item'])
def test_unsupported_appearance_never_requests_partial_preview(env,monkeypatch,modifier):
    c,s,db,app=seed(env)
    def refuse(*args):raise AssertionError('unsupported outfit must not be rendered')
    monkeypatch.setattr(app.state.service.catalog.assets,'outfit_preview',refuse)
    with db.connect() as conn,conn.cursor() as q:
        if modifier in ('clear_avatar_id','color1','color2'):
            q.execute('UPDATE taiwan_cain_2nd.user_items SET '+modifier+'=1 WHERE slot=8')
        elif modifier=='duplicate_slot':q.execute('UPDATE taiwan_cain_2nd.user_items SET slot=0 WHERE slot=8')
        elif modifier=='duplicate_part':q.execute('UPDATE taiwan_cain_2nd.user_items SET it_id=995003 WHERE slot=0')
        else:q.execute('UPDATE taiwan_cain_2nd.user_items SET it_id=888888 WHERE slot=0')
        conn.commit()
    response=c.get(P+'/characters/900001');assert response.status_code==200,response.text
    data=response.json();assert data['outfit']['state']=='unsupported' and data['outfit_preview']['url'] is None
    assert data['read_only'] and data['character']['charac_no']==900001


def test_legacy_schema_mismatched_catalog_and_deleted_character_preserve_detail(env):
    c,s,db,app=seed(env)
    s.pvf_sha256='f'*64
    data=c.get(P+'/characters/900001').json();assert data['outfit']['state']=='unavailable' and data['catalog_state']=='mismatch'
    s.pvf_sha256='a'*64
    with db.connect() as conn,conn.cursor() as q:
        q.execute('ALTER TABLE taiwan_cain_2nd.user_items DROP COLUMN color2');conn.commit()
    response=c.get(P+'/characters/900001');assert response.status_code==200,response.text
    data=response.json();assert data['outfit']['state']=='unavailable' and data['read_only']
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001');conn.commit()
    data=c.get(P+'/characters/900001').json();assert data['outfit']['state']=='unavailable' and '已删除' in data['outfit']['note']
