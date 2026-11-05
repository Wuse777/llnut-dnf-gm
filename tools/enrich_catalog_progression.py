"""Extract PVF experience references locally into a new copy of the current index."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader


def progression_rows(reader):
    tokens=reader.tokens('character/exptable.tbl')
    if not 1<=len(tokens)<=199 or any(kind not in (2,3) or type(n) is not int for kind,n in tokens):
        raise ValueError('Unsupported experience table format')
    rows=[];last=0
    for level,(_,raw) in enumerate(tokens,2):
        n=raw&0xffffffff
        if not last<n<=0xffffffff:raise ValueError('Non-increasing experience table')
        rows.append((level,n));last=n
    return rows


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():raise FileExistsError('Output already exists')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:meta=dict(c.execute('SELECT key,value FROM metadata'))
    if meta.get('pvf_sha256')!=sha:raise ValueError('PVF/index fingerprint mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'))
    try:rows=progression_rows(reader)
    finally:reader.close()
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:
            created=True;shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('DROP TABLE IF EXISTS progression_thresholds')
            c.execute('CREATE TABLE progression_thresholds(level INTEGER PRIMARY KEY,total_exp INTEGER NOT NULL)')
            c.executemany('INSERT INTO progression_thresholds VALUES(?,?)',rows)
            c.execute("INSERT OR REPLACE INTO metadata VALUES('progression_index_version','1')")
        return {'pvf_sha256':sha,'thresholds':len(rows),'item_permissions_changed':False}
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('pvf');p.add_argument('output');a=p.parse_args()
    print(json.dumps(enrich(a.source,a.pvf,a.output)))
