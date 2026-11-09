import hashlib
import importlib.util
import sqlite3
from pathlib import Path


def test_enrichment_adds_explicit_filter_metadata_without_changing_source_or_policy(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('equipment_enrich',Path(__file__).parents[1]/'tools/enrich_catalog_equipment.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    pvf=tmp_path/'synthetic.pvf';pvf.write_bytes(b'synthetic PVF bytes are never distributed game data')
    sha=hashlib.sha256(pvf.read_bytes()).hexdigest();source=tmp_path/'source.sqlite';output=tmp_path/'new.sqlite'
    with sqlite3.connect(source) as c:
        c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE items(id INTEGER PRIMARY KEY,source_path TEXT,allowed INTEGER);')
        c.execute('INSERT INTO metadata VALUES(?,?)',('pvf_sha256',sha))
        c.executemany('INSERT INTO items VALUES(?,?,?)',[(1,'equipment/master.equ',0),(2,'equipment/character/mage/weapon/staff/member.equ',1),(3,'stackable/enchant.stk',0)])
    definitions={
        'equipment/master.equ':[(5,'[equipment type]'),(7,'[coat]'),(5,'[set name]'),(7,'合成套装')],
        'equipment/character/mage/weapon/staff/member.equ':[(5,'[equipment type]'),(7,'[weapon]'),(5,'[usable job]'),(7,'[mage]'),(5,'[set item master]'),(2,1)],
        'stackable/enchant.stk':[(5,'[enchant]'),(5,'[physical attack]'),(2,1),(5,'[/enchant]')]}
    class Reader:
        def __init__(self,*args):pass
        def tokens(self,path):return definitions[path]
        def close(self):pass
    monkeypatch.setattr(module,'Reader',Reader)
    before=source.read_bytes();result=module.enrich(source,pvf,output)
    assert result['item_permissions_changed'] is False and result['job_declarations']==1
    assert source.read_bytes()==before
    with sqlite3.connect(output) as c:
        assert c.execute('SELECT item_id,weapon_type,set_id,set_name FROM equipment_filter_details ORDER BY item_id').fetchall()==[(1,'',1,'合成套装'),(2,'staff',1,'合成套装')]
        assert c.execute('SELECT * FROM equipment_jobs').fetchall()==[(2,'[mage]')]
        assert c.execute('SELECT id,allowed FROM items ORDER BY id').fetchall()==[(1,0),(2,1),(3,0)]
        assert c.execute("SELECT value FROM metadata WHERE key='equipment_filters_version'").fetchone()[0]=='1'
