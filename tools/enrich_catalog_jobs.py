"""Offline enrichment of existing index with matching PVF profession names only.

Creates a NEW index, preserves all item data and permissions, refuses overwrite.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dnfgm.pvf import Reader,job_metadata


def enrich(source,pvf,output):
    source,pvf,output=map(Path,(source,pvf,output))
    if output.exists():
        raise FileExistsError('Refusing to overwrite an existing index')
    digest=hashlib.file_digest(pvf.open('rb'),'sha256').hexdigest()
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as c:
        meta=dict(c.execute('SELECT key,value FROM metadata'))
        if meta.get('pvf_sha256')!=digest:
            raise ValueError('PVF/index fingerprint mismatch')
    reader=Reader(pvf,meta.get('encoding','gbk'))
    try:
        jobs=job_metadata(reader)
    finally:
        reader.close()
    if not jobs:
        raise ValueError('No profession names could be extracted')
    # Exclusive creation, copy only once, clean incomplete outputs on failure.
    created=False
    try:
        with output.open('xb') as target,source.open('rb') as origin:
            created=True
            shutil.copyfileobj(origin,target)
        with sqlite3.connect(output) as c:
            c.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)',('jobs',json.dumps(jobs,ensure_ascii=False)))
        return {'pvf_sha256':digest,'professions':len(jobs),'item_permissions_changed':False}
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('pvf');p.add_argument('output')
    a=p.parse_args()
    print(json.dumps(enrich(a.source,a.pvf,a.output),ensure_ascii=False))
