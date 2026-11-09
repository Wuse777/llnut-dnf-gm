"""Offline compilation of explicitly verified client profession artwork.

The large v2 illustration reader is deliberately separate from the runtime
512px image contract. A mapping must bind the exact PVF, archive and labelled
official artwork. No identity is inferred from an archive filename or index.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import zlib

from .npk_assets import AssetFormatError,MAX_IMG,Npk,Raster,normalized
from .portrait_credits import source_page
from .portrait_pack import enrich_portraits
from .pvf import Reader

SHA=re.compile(r'^[a-f0-9]{64}$')


def portrait_frame(data,index):
    """Bounded v2 BGRA8 art, normalized to a cropped <=512px RGBA portrait."""
    if not 32<=len(data)<=MAX_IMG or data[:16].rstrip(b'\0')!=b'Neople Img File':
        raise AssetFormatError('Unsupported portrait IMG header')
    table,_,version,count=struct.unpack_from('<4i',data,16)
    if version!=2 or not 1<=count<=1024 or type(index) is not int or not 0<=index<count:
        raise AssetFormatError('Unsupported portrait sheet or frame')
    pos=32;frames=[]
    for _ in range(count):
        if pos+4>len(data):raise AssetFormatError('Truncated portrait table')
        fmt=struct.unpack_from('<i',data,pos)[0]
        if fmt==17:
            if pos+8>len(data):raise AssetFormatError('Truncated portrait link')
            target=struct.unpack_from('<i',data,pos+4)[0];pos+=8
            if not 0<=target<count:raise AssetFormatError('Portrait link out of range')
            frames.append({'link':target});continue
        if pos+36>len(data):raise AssetFormatError('Truncated portrait record')
        fmt,compression,w,h,size,x,y,cw,ch=struct.unpack_from('<9i',data,pos);pos+=36
        if fmt!=16 or compression not in (5,6):raise AssetFormatError('Unsupported portrait pixels')
        if not all(1<=n<=2048 for n in (w,h,cw,ch)) or not 0<=x<=cw-w or not 0<=y<=ch-h:
            raise AssetFormatError('Portrait canvas exceeds bounds')
        expected=w*h*4
        if compression==5:size=expected
        if not 1<=size<=MAX_IMG:raise AssetFormatError('Portrait payload exceeds bounds')
        frames.append({'w':w,'h':h,'size':size,'expected':expected,'compression':compression})
    offset=32+table
    if not pos<=offset<=len(data):raise AssetFormatError('Invalid portrait payload offset')
    for frame in frames:
        if 'link' in frame:continue
        frame['offset']=offset;offset+=frame['size']
        if offset>len(data):raise AssetFormatError('Portrait payload outside file')
    seen=set()
    while 'link' in frames[index]:
        if index in seen:raise AssetFormatError('Cyclic portrait link')
        seen.add(index);index=frames[index]['link']
    f=frames[index];raw=data[f['offset']:f['offset']+f['size']]
    if f['compression']==6:
        stream=zlib.decompressobj()
        try:raw=stream.decompress(raw,f['expected']+1)
        except zlib.error as error:raise AssetFormatError('Invalid portrait compression') from error
        if not stream.eof or stream.unconsumed_tail or stream.unused_data:
            raise AssetFormatError('Invalid portrait stream length')
    if len(raw)!=f['expected']:raise AssetFormatError('Portrait raster length mismatch')
    w,h=f['w'],f['h'];scale=max(w,h,512)
    width=max(1,w*512//scale);height=max(1,h*512//scale)
    # Deterministic nearest sampling preserves straight-alpha source colours.
    rgba=bytearray(width*height*4)
    for y in range(height):
        for x in range(width):
            src=((y*h//height)*w+x*w//width)*4;dst=(y*width+x)*4
            b,g,r,a=raw[src:src+4];rgba[dst:dst+4]=bytes((r,g,b,a))
    return Raster(width,height,bytes(rgba))


def compile_portraits(source,pvf,npk_dir,mapping,output):
    """Never mutates the source pack or client; all pixels stay in private output."""
    source,pvf,npk_dir,mapping,output=map(Path,(source,pvf,npk_dir,mapping,output))
    if output.exists():raise FileExistsError('Refusing to overwrite an asset pack')
    if mapping.stat().st_size>256*1024:raise ValueError('Portrait evidence map too large')
    evidence=json.loads(mapping.read_text(encoding='utf-8'))
    if (evidence.get('format')!='dnfgm-client-portrait-evidence-v1' or
            evidence.get('method')!='official_labelled_artwork_visual_comparison' or
            any(not isinstance(evidence.get(k),str) or not SHA.fullmatch(evidence[k]) for k in ('pvf_sha256','archive_sha256'))):
        raise ValueError('Explicit versioned portrait evidence is required')
    archive_name=evidence.get('archive','')
    if not isinstance(archive_name,str) or Path(archive_name).name!=archive_name or '\\' in archive_name:
        raise ValueError('Portrait archive must be a local basename')
    archive=npk_dir/archive_name
    if archive.is_symlink() or not archive.is_file():raise ValueError('Portrait archive unavailable')
    with pvf.open('rb') as stream:pvf_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    with archive.open('rb') as stream:archive_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if pvf_sha!=evidence['pvf_sha256'] or archive_sha!=evidence['archive_sha256']:
        raise ValueError('Portrait evidence fingerprint mismatch')
    with closing(sqlite3.connect((source/'manifest.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as c:
        if dict(c.execute('SELECT key,value FROM metadata')).get('pvf_sha256')!=pvf_sha:
            raise ValueError('Source asset pack belongs to a different PVF')
    rows=evidence.get('entries')
    if not isinstance(rows,list) or not 1<=len(rows)<=128:raise ValueError('Invalid portrait evidence entries')
    reader=Reader(pvf);prepared=[];seen=set();available={}
    try:
        jobs={job:'character/'+path.lower() for job,path in reader.mapping('character/character.lst')}
        for job,path in jobs.items():available[job]=reader.fields(path).get('[growtype name]',[])
        data=Npk(archive).read(normalized(evidence['member']))
        with TemporaryDirectory(prefix='dnfgm-portraits-') as scratch:
            scratch=Path(scratch)
            for entry in rows:
                if not isinstance(entry,dict):raise ValueError('Invalid portrait evidence entry')
                job,grow,frame=(entry.get(k) for k in ('job','grow_type','frame'))
                identity=(job,grow)
                if (any(type(v) is not int for v in identity+(frame,)) or not 0<=job<=255 or
                        not 1<=grow<=15 or not 0<=frame<1024 or identity in seen):
                    raise ValueError('Invalid or duplicate profession identity')
                seen.add(identity)
                if grow>=len(available.get(job,[])) or available[job][grow]!=entry.get('pvf_name'):
                    raise ValueError('Portrait identity differs from matching PVF profession')
                page=source_page(entry.get('official_page',''));art=source_page(entry.get('official_art',''))
                label=entry.get('official_label')
                if (urlsplit(page).hostname!='www.dfoneople.com' or urlsplit(art).hostname!='static.dfoneople.com'
                        or not isinstance(label,str) or not 1<=len(label)<=64):
                    raise ValueError('Labelled primary artwork evidence is missing')
                image=portrait_frame(data,frame);filename=str(frame)+'.png';(scratch/filename).write_bytes(image.png())
                prepared.append({'job':job,'grow_type':grow,'sex':-1,'png':filename,'kind':'client',
                                 'label':entry['pvf_name']+' · 客户端转职插画（觉醒0）','page':page,'focus_x':50,'focus_y':30})
            manifest=scratch/'mapping.json';manifest.write_text(json.dumps(prepared,ensure_ascii=False),encoding='utf-8')
            result=enrich_portraits(source,manifest,output)
    finally:reader.close()
    gaps=[{'job':job,'grow_type':grow,'name':name} for job,names in available.items()
          for grow,name in enumerate(names) if grow and (job,grow) not in seen]
    result.update(profession_portraits=len(prepared),awakening_specific_portraits=0,
                  missing_profession_portraits=gaps,
                  awakening_note='没有核实独立觉醒阶段插画；觉醒角色只能标注为同转职示意回退',
                  evidence_sha256=hashlib.sha256(mapping.read_bytes()).hexdigest())
    (output/'portrait-coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result
