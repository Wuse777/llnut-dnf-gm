"""Offline quest metadata for a matching PVF; never edit the source index."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader


def quest_rows(reader):
    seen=set()
    for quest_id,path in reader.mapping('n_quest/quest.lst'):
        if quest_id in seen or not 1<=quest_id<=65535:raise ValueError('Duplicate or invalid quest identifier')
        seen.add(quest_id)
        fields=reader.fields('n_quest/'+path.lower())
        def text(key):return next((x for x in fields.get(key,[]) if isinstance(x,str)),'')
        levels=fields.get('[level]',[])
        levels=levels if len(levels)==2 and all(type(x) is int for x in levels) else [None,None]
        yield (quest_id,text('[name]'),text('[grade]'),text('[type]'),*levels,
            json.dumps(fields.get('[pre required quest]',[]),ensure_ascii=False),text('[condition message]'))
    if not seen:raise ValueError('No quest definitions found')


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():raise FileExistsError('Output already exists')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:
        meta=dict(c.execute('SELECT key,value FROM metadata'))
    if meta.get('pvf_sha256')!=sha:raise ValueError('PVF/index fingerprint mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'))
    try:rows=list(quest_rows(reader))
    finally:reader.close()
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:
            created=True;shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('DROP TABLE IF EXISTS quests')
            c.execute('CREATE TABLE quests(id INTEGER PRIMARY KEY,name TEXT,grade TEXT,kind TEXT,min_level INTEGER,max_level INTEGER,prerequisites TEXT,condition TEXT)')
            c.executemany('INSERT INTO quests VALUES(?,?,?,?,?,?,?,?)',rows)
            c.execute("INSERT OR REPLACE INTO metadata VALUES('quest_index_version','1')")
        return {'pvf_sha256':sha,'quests':len(rows),'item_permissions_changed':False}
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('pvf');p.add_argument('output');a=p.parse_args()
    print(json.dumps(enrich(a.source,a.pvf,a.output),ensure_ascii=False))
