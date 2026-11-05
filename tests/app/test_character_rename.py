"""Minimal rename transaction/encoding/linkage checks on isolated MySQL5.7."""
import json
import pytest
from dnfgm.encoding import mysql_latin1_text
from dnfgm.character_name_schema import LINKS
from test_inventory_operations import inv, P

BASE=P+'/character-renames'

@pytest.fixture
def rename(inv):
    client,s,db,app,root=inv
    s.writes=(*s.writes,'char-rename');s.write_approvals['char-rename']=True
    app.state.character_rename.fence=app.state.inventory_operations.fence
    with db.connect() as c,c.cursor() as q:
        # Minimal faithful identifiers and utf8_general_ci names; no real players.
        for schema,table,column,keys,_ in LINKS.values():
            fields=','.join('`'+k+'` INT NOT NULL' for k in keys)
            q.execute(f'CREATE TABLE `{schema}`.`{table}` ({fields},`{column}` VARCHAR(20) NOT NULL,PRIMARY KEY ({",".join("`"+k+"`" for k in keys)})) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci')
            row={k:1 for k in keys};row.update({k:900001 for k in ('m_id','master_id','master_no','charac_no') if k in keys})
            if 'server_id' in row:row['server_id']=3
            q.execute(f'INSERT INTO `{schema}`.`{table}` VALUES('+','.join(['%s']*(len(keys)+1))+')',[*(row[k] for k in keys),'OldName'])
        q.execute("UPDATE taiwan_cain.charac_info SET charac_name='OldName' WHERE charac_no=900001")
        q.execute('ALTER TABLE taiwan_cain.charac_info ADD UNIQUE KEY unique_name(charac_name)')
        q.execute("INSERT INTO d_taiwan.guild_member VALUES(2,900001,4,900002,'OtherShard')")
        c.commit()
    return inv


def preview(rig,name='改名测试'):
    client=rig[0];read=client.get(BASE+'/characters/900001');assert read.status_code==200,read.text
    response=client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'reference':read.json()['reference'],'new_name':name,'reason':'合成改名'})
    assert response.status_code==200,response.text
    return response.json()


def test_rename_chinese_all_links_atomic_idempotent_and_other_shard_untouched(rename):
    client,s,db,app,root=rename;draft=preview(rename);op=draft['operation_id']
    route=BASE+'/operations/'+op+'/confirm';key={'idempotency_key':'rename-test-000001'}
    response=client.post(route,json=key);assert response.status_code==200,response.text
    assert response.json()['status']=='committed'
    assert client.post(route,json=key).json()==response.json()
    assert client.get(BASE+'/characters/900001').json()['target']['character']['charac_name']=='改名测试'
    with db.connect() as c,c.cursor() as q:
        for schema,table,col,keys,_ in LINKS.values():
            where=' WHERE server_id=3' if 'server_id' in keys else ''
            q.execute(f'SELECT `{col}` AS name FROM `{schema}`.`{table}`'+where)
            assert all(r['name']==mysql_latin1_text('改名测试'.encode()) for r in q.fetchall())
        q.execute('SELECT charac_name FROM d_taiwan.guild_member WHERE server_id=4');assert q.fetchone()['charac_name']=='OtherShard'
        q.execute('SELECT before_blob,after_blob FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));row=q.fetchone()
        assert json.loads(row['before_blob'])['name']=='OldName'
        assert json.loads(row['after_blob'])['format']=='qf1031-character-name-1'
    assert client.post(P+'/operations/'+op+'/confirm',json=key).status_code==409


def test_name_conflict_and_mid_transaction_failure_leave_every_name_unchanged(rename,monkeypatch):
    client,s,db,app,root=rename
    assert client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'reference':'a'*64,'new_name':'名'*7,'reason':'合成'}).status_code==422
    current=client.get(BASE+'/characters/900001').json()
    assert client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'reference':current['reference'],'new_name':'其他角色','reason':'重名检查'}).status_code==409
    draft=preview(rename)
    original=app.state.character_rename.apply_archive
    def fail(*args):original(*args);raise RuntimeError('synthetic transaction interruption')
    monkeypatch.setattr(app.state.character_rename,'apply_archive',fail)
    response=client.post(BASE+'/operations/'+draft['operation_id']+'/confirm',json={'idempotency_key':'rename-test-fail-001'})
    assert response.status_code==500
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT charac_name FROM taiwan_cain.charac_info WHERE charac_no=900001');assert q.fetchone()['charac_name']=='OldName'
        q.execute('SELECT charac_name FROM d_taiwan.guild_member WHERE server_id=3');assert q.fetchone()['charac_name']=='OldName'
        q.execute('SELECT COUNT(*) AS n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0
