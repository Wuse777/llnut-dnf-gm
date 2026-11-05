import sqlite3
import struct
import zlib
from dnfgm.character_quests import PROGRAM_SHA,QUEST_COLUMNS

P='/dnf-gm/api/v1'

def test_quest_diagnosis_pagination_lookup_and_unknown_flags(env):
    client,s,db,app=env;s.inventory_program_sha256=PROGRAM_SHA
    raw=bytearray(30000)
    for i in range(1,53):raw[i]=1
    raw[77]=2
    blob=struct.pack('<I',30000|0x80000000)+zlib.compress(raw)
    with db.connect() as c,c.cursor() as q:
        columns=['charac_no INT PRIMARY KEY','clear_quest BLOB','urgentQuestIndex SMALLINT DEFAULT 0']
        columns += [f'`{k}` INT UNSIGNED DEFAULT 0' for k in QUEST_COLUMNS[3:]]
        q.execute('CREATE TABLE taiwan_cain.new_charac_quest('+','.join(columns)+') ENGINE=InnoDB')
        q.execute('INSERT INTO taiwan_cain.new_charac_quest(charac_no,clear_quest,play_1,play_1_trigger,play_2,play_3,play_4_trigger) VALUES(900001,%s,1,4,1,60000,8)',(blob,));c.commit()
    with sqlite3.connect(s.catalog_file) as c:
        c.execute("INSERT INTO metadata VALUES('quest_index_version','1')")
        c.execute('CREATE TABLE quests(id INTEGER PRIMARY KEY,name TEXT,grade TEXT,kind TEXT,min_level INTEGER,max_level INTEGER,prerequisites TEXT,condition TEXT)')
        c.execute("INSERT INTO quests VALUES(1,'合成任务','[epic]','[condition]',1,99,'[]','合成说明')")
    r=client.get(P+'/characters/900001/quests?quest_id=1');assert r.status_code==200,r.text
    d=r.json();assert d['completed_count']==53 and len(d['completed'])==50 and d['has_more']
    assert d['lookup']['active_slots']==[1,2] and d['lookup']['clear_flag']==1
    assert d['active'][0]['definition']['name']=='合成任务'
    assert set(d['active'][0]['issues'])=={'duplicate_active','active_with_clear_flag'}
    assert 'id_out_of_range' in d['active'][2]['issues']
    assert d['active'][3]['issues']==['empty_with_progress']
    assert d['issues'][0]['code']=='nonstandard_clear_flags'
    assert len(client.get(P+'/characters/900001/quests?page=2').json()['completed'])==3
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT clear_quest FROM taiwan_cain.new_charac_quest WHERE charac_no=900001');assert q.fetchone()['clear_quest']==blob
        q.execute("UPDATE taiwan_cain.new_charac_quest SET clear_quest='broken' WHERE charac_no=900001");c.commit()
    d=client.get(P+'/characters/900001/quests').json();assert d['completed_count'] is None and d['clear']['state']=='unavailable'
    assert client.get(P+'/characters/900002/quests').json()['state']=='missing'
