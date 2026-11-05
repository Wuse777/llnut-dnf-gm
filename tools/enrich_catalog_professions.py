"""Add per-job advancement/awakening names to a NEW local matching catalog."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader
from dnfgm.profession_rules import PROGRAM_SHA,RULE_VERSION,choices


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():raise FileExistsError('Refusing to overwrite a catalog')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:
        meta=dict(c.execute('SELECT key,value FROM metadata'))
        profiles={job:set((a,b) for a,b in c.execute('SELECT first_growth,second_growth FROM progression_growth WHERE job=?',(job,))) for job, in c.execute('SELECT job FROM skill_rules')}
    if meta.get('pvf_sha256')!=sha or meta.get('skill_rules_program_sha256')!=PROGRAM_SHA:raise ValueError('PVF/program mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'));rows=[]
    try:
        for job,path in reader.mapping('character/character.lst'):
            rows.append((job,json.dumps(choices(reader.tokens('character/'+path),profiles[job]),ensure_ascii=False,sort_keys=True,separators=(',',':'))))
    finally:reader.close()
    if len(rows)!=len(profiles):raise ValueError('Missing profession definitions')
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:created=True;shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('DROP TABLE IF EXISTS profession_rules')
            c.execute('CREATE TABLE profession_rules(job INTEGER PRIMARY KEY,payload_json TEXT NOT NULL)')
            c.executemany('INSERT INTO profession_rules VALUES(?,?)',rows)
            c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('profession_rules_version',RULE_VERSION),('profession_rules_program_sha256',PROGRAM_SHA)])
        return {'pvf_sha256':sha,'jobs':len(rows),'choices':sum(len(json.loads(p)['choices']) for _,p in rows),'existing_tables_changed':False}
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','pvf','output'):p.add_argument(key)
    a=p.parse_args();print(json.dumps(enrich(a.source,a.pvf,a.output),ensure_ascii=False))
