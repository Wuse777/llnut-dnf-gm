"""Build offline level-maintenance rules in a NEW matching catalog copy."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader
from dnfgm.progression_rules import PROGRAM_SHA,RULE_VERSION,growth_profiles,sp_table
from enrich_catalog_progression import progression_rows


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():raise FileExistsError('Refusing to overwrite an index')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:
        meta=dict(c.execute('SELECT key,value FROM metadata'))
        previous=c.execute('SELECT level,total_exp FROM progression_thresholds ORDER BY level').fetchall()
    if meta.get('pvf_sha256')!=sha:raise ValueError('PVF/index fingerprint mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'));rows=[];jobs=[]
    try:
        thresholds=progression_rows(reader)
        if previous!=thresholds:raise ValueError('Existing experience references differ; refusing to replace them')
        sp=sp_table(reader.fields('etc/sptable.etc')['[sp table]'])
        for job,path in reader.mapping('character/character.lst'):
            if type(job) is not int or job in jobs:raise ValueError('Invalid/duplicate job')
            profiles=growth_profiles(reader.tokens('character/'+path));jobs.append(job)
            for (first,second),values in profiles.items():
                rows.append((job,first,second,json.dumps(values,sort_keys=True,separators=(',',':'))))
    finally:reader.close()
    if not rows:raise ValueError('No growth profiles extracted')
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:
            created=True;shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('DROP TABLE IF EXISTS progression_growth')
            c.execute('DROP TABLE IF EXISTS progression_sp')
            c.execute('CREATE TABLE progression_growth(job INTEGER NOT NULL,first_growth INTEGER NOT NULL,second_growth INTEGER NOT NULL,values_json TEXT NOT NULL,PRIMARY KEY(job,first_growth,second_growth))')
            c.execute('CREATE TABLE progression_sp(level INTEGER PRIMARY KEY,points INTEGER NOT NULL)')
            c.executemany('INSERT INTO progression_growth VALUES(?,?,?,?)',rows)
            c.executemany('INSERT INTO progression_sp VALUES(?,?)',sorted(sp.items()))
            c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[
                ('progression_growth_version',RULE_VERSION),('progression_growth_program_sha256',PROGRAM_SHA)])
        return {'pvf_sha256':sha,'jobs':len(jobs),'growth_profiles':len(rows),'sp_levels':len(sp),
                'item_permissions_changed':False,'experience_references_changed':False}
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('pvf');p.add_argument('output');a=p.parse_args()
    print(json.dumps(enrich(a.source,a.pvf,a.output),ensure_ascii=False))
