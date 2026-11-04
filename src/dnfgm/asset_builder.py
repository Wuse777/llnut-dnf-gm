"""Offline private asset packaging. Never ships game material with public source."""
from collections import Counter
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from .npk_assets import AssetFormatError,Npk,decode_img,decode_png,normalized
from .pvf import Reader

SCHEMA='''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE files(sha256 TEXT PRIMARY KEY,width INTEGER NOT NULL,height INTEGER NOT NULL);
CREATE TABLE item_images(item_id INTEGER PRIMARY KEY,sha256 TEXT,state TEXT NOT NULL,source_img TEXT,frame INTEGER,detail TEXT NOT NULL DEFAULT '');
CREATE TABLE portraits(job INTEGER,grow_type INTEGER,sex INTEGER,sha256 TEXT NOT NULL,PRIMARY KEY(job,grow_type,sex));
'''


def image_reference(fields):
    values=fields.get('[icon]',[])
    if len(values)<2 or not isinstance(values[0],str) or type(values[1]) is not int or values[1]<0:
        raise AssetFormatError('No valid PVF icon reference')
    return normalized(values[0]),values[1]


def build_assets(pvf,catalog,output,npk_dir=None,portraits=None):
    pvf,catalog,output=map(Path,(pvf,catalog,output))
    if output.exists():raise FileExistsError('Refusing to overwrite an existing asset pack')
    with pvf.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    with closing(sqlite3.connect(catalog.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        metadata=dict(c.execute('SELECT key,value FROM metadata'))
        if metadata.get('pvf_sha256')!=sha:raise ValueError('PVF/catalog fingerprint mismatch')
    archives=[];members={};archive_sources=[]
    if npk_dir:
        directory=Path(npk_dir)
        if not directory.is_dir():raise ValueError('NPK directory does not exist')
        for path in sorted(directory.glob('*')):
            if path.suffix.lower()!='.npk' or not path.is_file():continue
            archive=Npk(path);archives.append(archive)
            with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            archive_sources.append({'file':path.name,'sha256':digest})
            for name in archive.members:
                # No arbitrary last-file-wins resolution of patched client packs.
                members.setdefault(name,[]).append(len(archives)-1)
    portrait_rows=[]
    if portraits:
        config=Path(portraits)
        if config.stat().st_size>262144:raise ValueError('Portrait mapping too large')
        portrait_rows=json.loads(config.read_text())
        if not isinstance(portrait_rows,list) or len(portrait_rows)>512:raise ValueError('Invalid portrait mapping')
        seen=set()
        for p in portrait_rows:
            if not isinstance(p,dict) or set(p)-{'job','grow_type','sex','png'} or not isinstance(p.get('png'),str) or not p['png']:raise ValueError('Invalid portrait entry')
            p.setdefault('grow_type',-1);p.setdefault('sex',-1)
            if any(type(p.get(k)) is not int or not lo<=p[k]<=hi for k,lo,hi in (('job',0,255),('grow_type',-1,255),('sex',-1,1))):raise ValueError('Invalid portrait identity')
            identity=(p['job'],p['grow_type'],p['sex'])
            if identity in seen:raise ValueError('Duplicate portrait mapping')
            seen.add(identity);p['png_path']=(config.parent/p['png']).resolve()
    output.mkdir(mode=0o750);created=True;reader=None
    try:
        (output/'images').mkdir(mode=0o750)
        reader=Reader(pvf,metadata.get('encoding','gbk'))
        counts=Counter()
        with closing(sqlite3.connect(output/'manifest.sqlite')) as pack,closing(sqlite3.connect(catalog.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            pack.executescript(SCHEMA)
            def save(raster):
                png=raster.png();digest=hashlib.sha256(png).hexdigest();path=output/'images'/(digest+'.png')
                if not path.exists():path.write_bytes(png);path.chmod(0o640)
                pack.execute('INSERT OR IGNORE INTO files VALUES(?,?,?)',(digest,raster.width,raster.height))
                return digest
            @lru_cache(maxsize=8)
            def img_bytes(archive,name):return archives[archive].read(name)
            @lru_cache(maxsize=4096)
            def render(name,frame):
                candidates=members.get(name,[]) or members.get('sprite/'+name,[])
                if not candidates:return None,'missing','Client IMG member not found'
                if len(candidates)>1:return None,'ambiguous','Multiple client packs contain this IMG; explicit source selection required'
                actual=name if name in members else 'sprite/'+name
                try:return save(decode_img(img_bytes(candidates[0],actual),frame)),'ready',''
                except (AssetFormatError,UnicodeError,KeyError,ValueError) as error:return None,'unsupported',str(error)[:160]
            for item_id,path in c.execute('SELECT id,source_path FROM items ORDER BY id'):
                name=None;frame=None;digest=None
                try:
                    name,frame=image_reference(reader.fields(path))
                    digest,state,detail=render(name,frame)
                except (AssetFormatError,KeyError,UnicodeError,ValueError) as error:
                    state,detail='missing_reference',str(error)[:160]
                counts[state]+=1
                pack.execute('INSERT INTO item_images VALUES(?,?,?,?,?,?)',(item_id,digest,state,name,frame,detail))
            for p in portrait_rows:
                if p['png_path'].stat().st_size>2*1024*1024:raise ValueError('Portrait PNG exceeds budget')
                digest=save(decode_png(p['png_path'].read_bytes()))
                pack.execute('INSERT INTO portraits VALUES(?,?,?,?)',(p['job'],p['grow_type'],p['sex'],digest))
            manifest={'format':'dnfgm-assets-v1','pvf_sha256':sha,'state':'ready',
                      'counts':json.dumps(dict(counts),sort_keys=True),'portraits':str(len(portrait_rows)),
                      'source_archives':json.dumps(archive_sources,ensure_ascii=False),'client_verified':'false'}
            pack.executemany('INSERT INTO metadata VALUES(?,?)',manifest.items());pack.commit()
            files=pack.execute('SELECT COUNT(*) FROM files').fetchone()[0]
        (output/'manifest.sqlite').chmod(0o640)
        return {'pvf_sha256':sha,'items':sum(counts.values()),'states':dict(counts),'unique_images':files,'portraits':len(portrait_rows),'client_verified':False}
    except Exception:
        if created:shutil.rmtree(output)
        raise
    finally:
        if reader:reader.close()
