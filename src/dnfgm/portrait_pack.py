"""Offline merge of explicitly attributed portraits into a NEW private asset pack."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from .npk_assets import decode_png
from .portrait_credits import KINDS,source_page

CREDITS_SCHEMA='''CREATE TABLE IF NOT EXISTS portrait_sources(job INTEGER,grow_type INTEGER,sex INTEGER,kind TEXT NOT NULL,label TEXT NOT NULL,page TEXT NOT NULL,focus_x INTEGER NOT NULL,focus_y INTEGER NOT NULL,PRIMARY KEY(job,grow_type,sex))'''

def enrich_portraits(source,mapping,output):
    source,mapping,output=map(Path,(source,mapping,output))
    if output.exists():raise FileExistsError('Refusing to overwrite an asset pack')
    if source.is_symlink() or (source/'manifest.sqlite').is_symlink():raise ValueError('Asset pack symlink refused')
    if mapping.stat().st_size>262144:raise ValueError('Portrait mapping too large')
    rows=json.loads(mapping.read_text(encoding='utf-8'));seen=set();prepared=[]
    if not isinstance(rows,list) or not rows or len(rows)>512:raise ValueError('Invalid portrait mapping')
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'job','grow_type','sex','png','kind','label','page','focus_x','focus_y'}:raise ValueError('Invalid portrait entry')
        identity=(row.get('job'),row.get('grow_type',-1),row.get('sex',-1))
        if any(type(v) is not int or not lo<=v<=hi for v,lo,hi in zip(identity,(0,-1,-1),(255,127,1))) or identity in seen:raise ValueError('Invalid/duplicate portrait identity')
        seen.add(identity)
        kind=row.get('kind','custom');label=row.get('label','');page=source_page(row.get('page',''));focus=(row.get('focus_x',50),row.get('focus_y',50))
        if kind not in KINDS or not isinstance(label,str) or not label.strip() or len(label)>120 or any(type(v) is not int or not 0<=v<=100 for v in focus):raise ValueError('Invalid portrait attribution or focus')
        filename=row.get('png')
        if not isinstance(filename,str) or not filename:raise ValueError('Missing portrait PNG')
        path=mapping.parent/filename
        if not path.is_file() or path.is_symlink() or path.stat().st_size>2*1024*1024:raise ValueError('Portrait PNG unavailable or too large')
        png=decode_png(path.read_bytes()).png();digest=hashlib.sha256(png).hexdigest()
        import struct
        width,height=struct.unpack('>II',png[16:24])
        prepared.append((identity,png,digest,width,height,kind,label,page,focus))
    created=False
    try:
        with sqlite3.connect((source/'manifest.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as old:
            meta=dict(old.execute('SELECT key,value FROM metadata'))
            if meta.get('format')!='dnfgm-assets-v1' or meta.get('state')!='ready' or meta.get('portrait_credits_version','1')!='1':raise ValueError('Unsupported source pack')
            output.mkdir(mode=0o750);created=True;(output/'images').mkdir(mode=0o750)
            with sqlite3.connect(output/'manifest.sqlite') as new:
                old.backup(new)
                for digest,width,height in old.execute('SELECT sha256,width,height FROM files'):
                    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('Invalid source image digest')
                    p=source/'images'/(digest+'.png')
                    if p.is_symlink() or not p.is_file() or p.stat().st_size>2*1024*1024:raise ValueError('Invalid source image file')
                    data=p.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Source image checksum mismatch')
                    (output/'images'/p.name).write_bytes(data)
                new.execute(CREDITS_SCHEMA)
                for identity,png,digest,width,height,kind,label,page,focus in prepared:
                    (output/'images'/(digest+'.png')).write_bytes(png)
                    new.execute('INSERT OR IGNORE INTO files VALUES(?,?,?)',(digest,width,height))
                    new.execute('INSERT OR REPLACE INTO portraits VALUES(?,?,?,?)',(*identity,digest))
                    new.execute('INSERT OR REPLACE INTO portrait_sources VALUES(?,?,?,?,?,?,?,?)',(*identity,kind,label,page,*focus))
                count=new.execute('SELECT COUNT(*) FROM portraits').fetchone()[0]
                new.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('portraits',str(count)),('portrait_credits_version','1')]);new.commit()
        for p in output.rglob('*'):
            if p.is_file():p.chmod(0o640)
        return {'pvf_sha256':meta['pvf_sha256'],'portraits':count,'added':len(prepared),'item_images_unchanged':True,'client_verified':False}
    except Exception:
        if created:shutil.rmtree(output)
        raise
