import json
import sqlite3
import struct
import zlib
import pytest
from dnfgm.character_detail import decode_container,profession,MAX_SLOTS
P='/dnf-gm/api/v1'


def slot(item_id=990001,kind=1,quantity=1):
    b=bytearray(61);b[1]=kind;struct.pack_into('<I',b,2,item_id)
    b[6]=7;struct.pack_into('<I',b,7,quantity);struct.pack_into('<H',b,11,33)
    b[17]=3;struct.pack_into('<H',b,18,12);b[51]=4
    return bytes(b)


def blob(*slots):
    data=b''.join(slots)
    return struct.pack('<I',len(data))+zlib.compress(data)


def test_item_layout_and_empty_slots():
    d=decode_container(blob(slot(),b'\0'*61,slot(990002,3,55)),True)
    assert d['state']=='ok' and d['slot_count']==3 and len(d['items'])==2
    a,b=d['items'];assert a['id']==990001 and a['slot_label']=='武器'
    assert a['quantity']==1 and a['enhancement']==7 and a['durability']==33
    assert a['forge']==4 and a['amplify_value']==12
    assert b['quantity']==55 and b['enhancement'] is None and b['slot']==2


@pytest.mark.parametrize('bad',[
    b'',b'abc',b'xxxxnotzlib',struct.pack('<I',61)+zlib.compress(b'x'*60),
    struct.pack('<I',62)+zlib.compress(b'x'*62),
    struct.pack('<I',(MAX_SLOTS+1)*61)+b'x',
    struct.pack('<I',61)+zlib.compress(b'x'*1000000),
    blob(slot())[:-2],blob(slot())+b'trailing',
    struct.pack('<I',61)+zlib.compress(b'\0'*61)+zlib.compress(b'\0'*61),
])
def test_bad_storage_is_not_an_empty_backpack(bad):
    d=decode_container(bad)
    assert d['state']=='invalid' and d['slot_count'] is None and d['items']==[]


def test_missing_empty_and_unknown_types_are_distinct():
    assert decode_container(None)['state']=='missing'
    assert decode_container(blob(b'\0'*61))['state']=='ok'
    d=decode_container(blob(slot(123,99,800)))['items'][0]
    assert d['type_name']=='未知类型 99' and d['quantity'] is None


def test_job_mapping_does_not_invent_awakening():
    jobs={'0':{'grow_names':['鬼剑士','剑魂']}}
    assert profession(0,1,jobs)['name']=='剑魂'
    assert not profession(0,17,jobs)['grow_name_known']
    assert profession(99,1,jobs)['name']=='未知职业 #99'


def seed(env):
    c,s,db,_=env
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET lev=27,job=0,grow_type=1,maxHP=14000,phy_attack=1300 WHERE charac_no=900001')
        q.execute('INSERT INTO taiwan_cain_2nd.inventory VALUES(%s,%s,%s,%s,%s,%s)',(900001,150460,3,8,blob(slot(990002,3,55),slot(888888,2,2)),blob(slot())))
        q.execute("INSERT INTO taiwan_cain.charac_stat VALUES(900001,12345,20,7,'2026-10-24 07:00:00')")
        conn.commit()
    with sqlite3.connect(s.catalog_file) as cat:
        cat.execute('INSERT INTO metadata VALUES(?,?)',('jobs',json.dumps({'0':{'grow_names':['鬼剑士','剑魂']}})))
    return c,s,db


def test_character_detail_snapshot_ownership_gold_equipment_inventory(env):
    c,s,db=seed(env)
    r=c.get(P+'/characters/900001');assert r.status_code==200,r.text
    d=r.json();assert d['character']['uid']==900001 and d['account']['accountname']=='gm_m0_fixture'
    assert d['character']['charac_name']=='GM测试角色' and d['character']['lev']==27
    assert d['profession']['name']=='剑魂' and d['wealth']['gold']==150460
    assert d['play_state']['exp']==12345
    assert d['equipment']['items'][0]['name']=='测试装备'
    assert d['backpack']['items'][0]['quantity']==55
    assert d['backpack']['items'][1]['name']=='未知物品 #888888'
    assert d['read_only'] and d['collected_at'] and d['account_online']['login_status']==1
    assert {a['key']:a['value'] for a in d['attributes']}['maxHP']==14000
    assert 'VIP' not in r.text and 'element_resist' not in r.text and 'inventory_bytes' not in r.text
    with db.connect() as conn,conn.cursor() as q:
        for t in ('operations','audit','gift_versions'):
            q.execute('SELECT COUNT(*) n FROM dnf_gm.'+t);assert q.fetchone()['n']==0
        q.execute('SELECT money FROM taiwan_cain_2nd.inventory WHERE charac_no=900001');assert q.fetchone()['money']==150460


def test_detail_auth_validation_missing_and_deleted(env):
    c,s,db=seed(env)
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001');conn.commit()
    d=c.get(P+'/characters/900001').json();assert d['character']['delete_flag']==1 and d['read_only']
    assert c.get(P+'/characters/2147483647').status_code==404
    for path in ('0','-1','2147483648','abc',"1 OR 1=1"):
        assert c.get(P+'/characters/'+path).status_code==422
    c.cookies.clear();assert c.get(P+'/characters/900001').status_code==401


def test_missing_inventory_unknown_not_zero_and_bad_data_visible(env):
    c,s,db,_=env
    d=c.get(P+'/characters/900001').json()
    assert d['wealth']['gold'] is None and d['wealth']['state']=='missing'
    assert d['equipment']['state']=='missing' and d['play_state'] is None
    with db.connect() as conn,conn.cursor() as q:
        q.execute("INSERT INTO taiwan_cain_2nd.inventory VALUES(900001,0,0,0,%s,%s)",(b'bad',blob(b'\0'*61)));conn.commit()
    d=c.get(P+'/characters/900001').json()
    assert d['backpack']['state']=='invalid' and d['equipment']['state']=='ok'
    assert d['wealth']['gold']==0


def test_missing_or_mismatched_catalog_does_not_hide_stored_items(env):
    c,s,db=seed(env)
    s.pvf_sha256='f'*64
    d=c.get(P+'/characters/900001').json()
    assert d['catalog_state']=='mismatch' and d['backpack']['items'][0]['id']==990002
    assert not d['backpack']['items'][0]['catalog_known']
    s.catalog_file='/does/not/exist'
    d=c.get(P+'/characters/900001').json()
    assert d['catalog_state']=='unavailable' and len(d['equipment']['items'])==1


def test_live_pvf_mismatch_is_displayed_as_unknown_labels(env):
    from pathlib import Path
    c,s,db=seed(env)
    p=Path(s.status_file);status=json.loads(p.read_text());status['pvf_sha256']='b'*64;p.write_text(json.dumps(status))
    d=c.get(P+'/characters/900001').json()
    assert d['catalog_state']=='mismatch' and d['equipment']['items'][0]['id']==990001
    assert not d['equipment']['items'][0]['catalog_known']


def test_readable_items_do_not_gain_mail_rights(env):
    c,s,db=seed(env)
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE taiwan_cain_2nd.inventory SET inventory=%s WHERE charac_no=900001',(blob(slot(990003,5,1)),));conn.commit()
    d=c.get(P+'/characters/900001').json()
    assert d['backpack']['items'][0]['name']=='特殊宠物'
    payload={'action':'mail','uid':900001,'charac_no':900001,'reason':'negative permission test','items':[{'id':990003,'quantity':1}]}
    assert c.post(P+'/operations/preview',json=payload).status_code==422


def test_offline_profession_metadata_uses_pvf_not_guessed_map():
    from dnfgm.pvf import job_metadata
    class Reader:
        tree={'character/character.lst':True}
        def mapping(self,path):return [(0,'swordman.chr'),(99,'missing.chr')]
        def fields(self,path):
            if 'missing' in path:raise KeyError()
            return {'[growtype name]':['鬼剑士','剑魂']}
    assert job_metadata(Reader())=={'0':{'grow_names':['鬼剑士','剑魂']}}
