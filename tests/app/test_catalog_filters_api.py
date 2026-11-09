import sqlite3,uuid
from test_application import P,confirm


def test_filtered_policy_preview_only_changes_visible_full_selection(env):
    c,s,db,app=env
    with sqlite3.connect(s.catalog_file) as index:
        index.executescript('CREATE TABLE equipment_details(item_id INTEGER PRIMARY KEY,part_code TEXT,rarity INTEGER);')
        index.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',[(994000+i,'组合筛选样本'+str(i),'equipment',50+i,1,30,1,0,'equipment/synthetic.equ') for i in range(4)])
        index.executemany('INSERT INTO equipment_details VALUES(?,?,?)',[(994000,'[coat]',0),(994001,'[weapon]',0),(994002,'[weapon]',0),(994003,'[weapon]',1)])
    filters={'q':'组合筛选样本','part':'[weapon]','rarity':0,'min_level':51,'max_level':52}
    result=c.get(P+'/catalog',params={**filters,'sort':'level_desc'})
    assert result.status_code==200,result.text
    assert [i['id'] for i in result.json()['items']]==[994002,994001]
    assert result.json()['total']==2
    p=c.post(P+'/catalog/policy/preview',json={'filters':filters,'enabled':False,'reason':'合成组合筛选验证'})
    assert p.status_code==200,p.text
    assert p.json()['preview']['matched']==2
    response=confirm(c,p.json()['operation_id'],uuid.uuid4().hex)
    assert response.status_code==200,response.text
    rows=c.get(P+'/catalog?q=组合筛选样本').json()['items']
    assert {i['id'] for i in rows if not i['sendable']}=={994001,994002}
    assert c.get(P+'/catalog?min_level=80&max_level=10').status_code==422
    assert c.get(P+'/catalog?sort=arbitrary').status_code==422


def test_extended_equipment_filters_keep_search_and_bulk_policy_targets_identical(env):
    c,s,db,app=env
    with sqlite3.connect(s.catalog_file) as index:
        index.executescript('CREATE TABLE equipment_filter_details(item_id INTEGER PRIMARY KEY,weapon_type TEXT,set_id INTEGER,set_name TEXT);CREATE TABLE equipment_jobs(item_id INTEGER,job_code TEXT);')
        index.execute('INSERT INTO metadata VALUES(?,?)',('equipment_filters_version','1'))
        index.executemany('INSERT INTO equipment_filter_details VALUES(?,?,?,?)',[(990001,'staff',10,'合成套装'),(990002,'staff',11,'其他套装')])
        index.executemany('INSERT INTO equipment_jobs VALUES(?,?)',[(990001,'[mage]'),(990002,'[mage]')])
    filters={'job':'[mage]','weapon_type':'staff','set_id':10}
    result=c.get(P+'/catalog',params=filters)
    assert result.status_code==200,result.text
    assert [r['id'] for r in result.json()['items']]==[990001]
    preview=c.post(P+'/catalog/policy/preview',json={'filters':filters,'enabled':False,'reason':'职业武器套装组合筛选'})
    assert preview.status_code==200,preview.text
    assert preview.json()['preview']['matched']==1
    assert confirm(c,preview.json()['operation_id'],uuid.uuid4().hex).status_code==200
    assert not c.get(P+'/catalog?q=990001').json()['items'][0]['sendable']
    assert c.get(P+'/catalog?q=990002').json()['items'][0]['sendable']
    assert c.get(P+'/catalog?set_id=0').status_code==422
