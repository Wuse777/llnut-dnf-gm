"""Locally enrich a NEW copy of an existing index, preserving all permissions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader
from dnfgm.equipment_metadata import equipment_definition,enchant_definition,attribute_definition,filter_definition


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():raise FileExistsError('Output already exists')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:
        meta=dict(c.execute('SELECT key,value FROM metadata'))
        items=c.execute('SELECT id,source_path FROM items ORDER BY id').fetchall()
    if meta.get('pvf_sha256')!=sha:raise ValueError('PVF/index fingerprint mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'));equipment=[];attributes=[];enchants=[];filters={};jobs=[];failures=0
    try:
        for item_id,path in items:
            try:
                tokens=reader.tokens(path)
                if path.startswith('equipment/'):
                    row=equipment_definition(tokens)
                    if row:
                        equipment.append((item_id,row['part_code'],row['rarity']))
                        attributes.append((item_id,json.dumps(attribute_definition(tokens),ensure_ascii=False)))
                        detail=filter_definition(tokens,path,item_id);filters[item_id]=detail
                        jobs.extend((item_id,code) for code in detail['job_codes'])
                if path.startswith('stackable/'):
                    row=enchant_definition(tokens)
                    if row:enchants.append((item_id,json.dumps(row['targets'],ensure_ascii=False),json.dumps(row['effects'],ensure_ascii=False),row['summary']))
            except (ValueError,KeyError,UnicodeError):failures+=1
    finally:reader.close()
    if not equipment or not enchants:raise ValueError('No equipment or enchantments extracted')
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:
            created=True;shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('DROP TABLE IF EXISTS equipment_details')
            c.execute('DROP TABLE IF EXISTS enchantments')
            c.execute('DROP TABLE IF EXISTS equipment_attributes')
            c.execute('DROP TABLE IF EXISTS equipment_filter_details')
            c.execute('DROP TABLE IF EXISTS equipment_jobs')
            c.execute('CREATE TABLE equipment_details(item_id INTEGER PRIMARY KEY,part_code TEXT NOT NULL,rarity INTEGER)')
            c.execute('CREATE TABLE enchantments(item_id INTEGER PRIMARY KEY,targets_json TEXT NOT NULL,effects_json TEXT NOT NULL,summary TEXT NOT NULL)')
            c.execute('CREATE TABLE equipment_attributes(item_id INTEGER PRIMARY KEY,attributes_json TEXT NOT NULL)')
            c.execute('CREATE TABLE equipment_filter_details(item_id INTEGER PRIMARY KEY,weapon_type TEXT NOT NULL,set_id INTEGER,set_name TEXT NOT NULL)')
            c.execute('CREATE TABLE equipment_jobs(item_id INTEGER NOT NULL,job_code TEXT NOT NULL,PRIMARY KEY(item_id,job_code))')
            c.execute('CREATE INDEX equipment_part_rarity ON equipment_details(part_code,rarity,item_id)')
            c.execute('CREATE INDEX equipment_weapon_type ON equipment_filter_details(weapon_type,item_id)')
            c.execute('CREATE INDEX equipment_set ON equipment_filter_details(set_id,item_id)')
            c.execute('CREATE INDEX equipment_job ON equipment_jobs(job_code,item_id)')
            c.executemany('INSERT INTO equipment_details VALUES(?,?,?)',equipment)
            c.executemany('INSERT INTO enchantments VALUES(?,?,?,?)',enchants)
            c.executemany('INSERT INTO equipment_attributes VALUES(?,?)',attributes)
            c.executemany('INSERT INTO equipment_filter_details VALUES(?,?,?,?)',[
                (item_id,row['weapon_type'],row['set_id'],filters.get(row['set_id'],{}).get('set_name','') or row['set_name'])
                for item_id,row in filters.items()])
            c.executemany('INSERT INTO equipment_jobs VALUES(?,?)',jobs)
            c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[
                ('equipment_index_version','1'),('equipment_attributes_version','2'),('equipment_filters_version','1'),('equipment_index_failures',str(failures))])
        return {'pvf_sha256':sha,'equipment':len(equipment),'enchantments':len(enchants),'job_declarations':len(jobs),'sets':len({r['set_id'] for r in filters.values() if r['set_id'] is not None}),'extraction_failures':failures,'item_permissions_changed':False}
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('pvf');p.add_argument('output');a=p.parse_args()
    print(json.dumps(enrich(a.source,a.pvf,a.output),ensure_ascii=False))
