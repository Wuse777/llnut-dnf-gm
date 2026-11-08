"""Offline client waiting-pose extraction and bounded straight-alpha composition.

ANI layout reference: sjy0727/DNFToolKit AniParser.java. Independent parser;
unknown parameters/transforms are refused rather than skipped. No runtime PVF
or NPK decoding. Default sprites never claim awakening or equipped appearance.
"""
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import shutil
import sqlite3
import struct

from .npk_assets import AssetFormatError, MAX_IMG, Npk, Raster, decode_img, dxt_size, inflate, normalized
from .outfit_recipe import canonical_outfit_recipe
from .pvf import Reader

SCHEMA = '''CREATE TABLE IF NOT EXISTS job_previews(
job INTEGER PRIMARY KEY,sha256 TEXT,state TEXT NOT NULL,pose TEXT NOT NULL,
source_kind TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS outfit_previews(
job INTEGER NOT NULL,recipe_sha256 TEXT NOT NULL,sha256 TEXT,state TEXT NOT NULL,
detail TEXT NOT NULL DEFAULT '',PRIMARY KEY(job,recipe_sha256))'''


def resolve_outfit_recipes(reader,job_tag,defaults,items,equipment):
    """Replace only exact matching slots; unsupported IDs never fall back."""
    result=dict(defaults)
    for item in items:
        paths=equipment.get(item['id'],[])
        if len(paths)!=1:raise AssetFormatError('Missing or ambiguous outfit equipment ID')
        path=normalized('equipment/'+paths[0]);fields=reader.fields(path)
        kind=fields.get('[equipment type]',[])
        if not kind or kind[0]!=item['slot']:raise AssetFormatError('Outfit item equipment slot mismatch')
        result[item['slot']]=equipment_recipe(reader.tokens(path),job_tag)
    return result


@dataclass(frozen=True)
class AnimationFrame:
    image: str
    frame: int
    x: int
    y: int
    visual: tuple


def parse_ani(data):
    """Read all records before accepting a first frame, never scan for a marker."""
    if not isinstance(data, bytes) or not 8 <= len(data) <= 1024 * 1024:
        raise AssetFormatError('ANI exceeds bounded size')
    pos = 0
    def read(fmt):
        nonlocal pos
        size = struct.calcsize('<' + fmt)
        if pos + size > len(data):raise AssetFormatError('Truncated ANI')
        result = struct.unpack_from('<' + fmt, data, pos);pos += size
        return result[0] if len(result) == 1 else result
    def string():
        nonlocal pos
        n = read('I')
        if not 1 <= n <= 1024 or pos + n > len(data):raise AssetFormatError('Invalid ANI string')
        try:value = data[pos:pos+n].decode('utf-8')
        except UnicodeError as e:raise AssetFormatError('Invalid ANI string encoding') from e
        pos += n
        if '\0' in value:raise AssetFormatError('ANI string contains NUL')
        return value
    fixed = {0:'B',1:'B',3:'B',7:'ff',8:'f',9:'BBBB',10:'B',12:'i',13:'h',14:'iiiiii',15:'iiiiii',23:'i',24:'h',25:'',26:'h',27:'hhhh'}
    visual_tags = {7,8,9,11,24,27}
    def params():
        count = read('H')
        if count > 64:raise AssetFormatError('Excessive ANI parameters')
        visual = []
        for _ in range(count):
            tag = read('H')
            if tag == 16:value = string()
            elif tag == 11:
                value = read('h')
                if value == 5:value = (value, read('hhh'))
            elif tag in fixed:value = read(fixed[tag]) if fixed[tag] else None
            else:raise AssetFormatError('Unsupported ANI parameter')
            if tag in visual_tags:visual.append((tag,value))
        return tuple(visual)
    count, path_count = read('HH')
    if not 1 <= count <= 4096 or not 1 <= path_count <= 256:raise AssetFormatError('Invalid ANI frame/path count')
    paths = [normalized(string()) for _ in range(path_count)]
    global_visual = params()
    frames = []
    for _ in range(count):
        extra = params();index = read('h')
        if index == -1:image,frame = '',-1
        else:
            if not 0 <= index < len(paths):raise AssetFormatError('ANI image path index out of range')
            image,frame = paths[index],read('h')
            if frame < 0:raise AssetFormatError('ANI frame index out of range')
        x,y = read('ii')
        if abs(x) > 8192 or abs(y) > 8192:raise AssetFormatError('ANI image position exceeds budget')
        frames.append(AnimationFrame(image,frame,x,y,global_visual+extra+params()))
    if pos != len(data):raise AssetFormatError('Unexpected ANI trailing data')
    return tuple(frames)


def validate_static(frame):
    if not frame.image or frame.frame < 0:raise AssetFormatError('Empty waiting frame')
    for tag,value in frame.visual:
        if ((tag==7 and value==(1.0,1.0)) or (tag==8 and value==0.0)
                or (tag==9 and value==(255,255,255,255)) or (tag in (11,24) and value==0)):
            continue
        raise AssetFormatError('Waiting frame needs unsupported visual transform')


def equipment_recipe(tokens, job):
    """Keep repeated animation-job blocks separate; Reader.fields merges them."""
    blocks=[];block=None;key=None
    for kind,value in tokens:
        if kind==5:
            key=value
            if key=='[animation job]':block={};blocks.append(block)
        elif block is not None and key:
            block.setdefault(key,[]).append(value)
    found=[b for b in blocks if b.get('[animation job]')==[job]]
    if len(found)!=1:raise AssetFormatError('Missing or ambiguous equipment animation job')
    b=found[0];variation=b.get('[variation]')
    if not isinstance(variation,list) or len(variation)!=2 or any(type(v) is not int or not 0<=v<=9999 for v in variation):
        raise AssetFormatError('Invalid avatar variation')
    layers=b.get('[layer variation]',[])
    if len(layers)%2 or len(layers)>64:raise AssetFormatError('Invalid avatar layer list')
    result=[]
    for i in range(0,len(layers),2):
        order,label=layers[i:i+2]
        if type(order) is not int or not -10000<=order<=10000 or not isinstance(label,str) or not re.fullmatch(r'[a-z]+_[a-z][0-9]?',label):
            raise AssetFormatError('Invalid avatar layer identity')
        result.append((order,label))
    scripts=b.get('[equipment ani script]',[])
    if result and (not scripts or any(not isinstance(s,str) for s in scripts) or len(set(scripts))!=1):
        raise AssetFormatError('Avatar has no exact equipment animation script')
    return tuple(variation),tuple(result),normalized(scripts[0]) if scripts else None


def member_name(body_template, variation, layer=None):
    """Apply client avatar naming to the exact .chr family and .equ variation.

    This is accepted only when the resulting single member exists in the NPK
    index; overlapping client patches remain ambiguous and are refused.
    """
    body_template=normalized(body_template)
    match=re.fullmatch(r'(.*/avatar)/skin/([a-z]+_)body%04d\.img',body_template)
    if not match:raise AssetFormatError('Unsupported client body image template')
    style,color=variation
    if layer is None:return body_template.replace('%04d',f'{style*100+color:04d}')
    part,suffix=layer.split('_')
    return f'{match[1]}/{part}/{match[2]}{part}{style:02d}{color:02d}{suffix}.img'


def composite(layers):
    """Compose ordered (Raster,x,y) tuples and crop only transparent margins."""
    if not 1<=len(layers)<=64:raise AssetFormatError('Invalid character layer count')
    prepared=[]
    for raster,x,y in layers:
        if type(x) is not int or type(y) is not int or abs(x)>8192 or abs(y)>8192:raise AssetFormatError('Layer position exceeds budget')
        points=[(i%raster.width,i//raster.width) for i in range(raster.width*raster.height) if raster.rgba[i*4+3]]
        if not points:continue
        left=min(p[0] for p in points);right=max(p[0] for p in points)+1
        top=min(p[1] for p in points);bottom=max(p[1] for p in points)+1
        prepared.append((raster,x,y,left,top,right,bottom))
    if not prepared:raise AssetFormatError('Character layers are empty')
    origin_x=min(x+l for _,x,_,l,_,_,_ in prepared);origin_y=min(y+t for _,_,y,_,t,_,_ in prepared)
    width=max(x+r for _,x,_,_,_,r,_ in prepared)-origin_x
    height=max(y+b for _,_,y,_,_,_,b in prepared)-origin_y
    if not 1<=width<=512 or not 1<=height<=512:raise AssetFormatError('Character composite exceeds canvas budget')
    canvas=bytearray(width*height*4)
    for raster,x,y,left,top,right,bottom in prepared:
        for py in range(top,bottom):
            for px in range(left,right):
                src=(py*raster.width+px)*4;sa=raster.rgba[src+3]
                if not sa:continue
                dst=((py+y-origin_y)*width+px+x-origin_x)*4;da=canvas[dst+3]
                alpha=sa*255+da*(255-sa)
                for channel in range(3):canvas[dst+channel]=(raster.rgba[src+channel]*sa*255+canvas[dst+channel]*da*(255-sa)+alpha//2)//alpha
                canvas[dst+3]=(alpha+127)//255
    return Raster(width,height,bytes(canvas))


def decode_avatar_img(data,index):
    """Extract cropped IMG pixels with original offsets, preserving empty layers.

    Avatar sheets use transparent sentinels at x==canvas_width, including a
    0x0 compressed empty stream. Validate every table record/payload offset,
    resolve links, then pass one bounded cropped frame to the shared codec.
    Nonempty pixels still must fit the original canvas. The icon decoder's
    stricter canvas policy remains unchanged.
    """
    if len(data)<32 or len(data)>MAX_IMG or data[:16].rstrip(b'\0')!=b'Neople Img File':
        raise AssetFormatError('Invalid avatar IMG header')
    table_size,_,version,count=struct.unpack_from('<4i',data,16)
    if version not in (2,4) or type(index) is not int or not 0<=index<count or not 0<count<=100000:
        raise AssetFormatError('Invalid avatar IMG frame')
    pos=32;palette=b''
    if version==4:
        if len(data)<36:raise AssetFormatError('Truncated avatar palette')
        colors=struct.unpack_from('<i',data,pos)[0]
        if not 0<=colors<=256 or pos+4+colors*4>len(data):raise AssetFormatError('Invalid avatar palette')
        palette=data[pos:pos+4+colors*4]
        pos+=4+colors*4
    records=[]
    for _ in range(count):
        if pos+4>len(data):raise AssetFormatError('Truncated avatar frame table')
        fmt=struct.unpack_from('<i',data,pos)[0]
        n=8 if fmt==17 else 36
        if pos+n>len(data):raise AssetFormatError('Truncated avatar frame table')
        values=struct.unpack_from('<2i' if fmt==17 else '<9i',data,pos);pos+=n
        if fmt==17:
            if not 0<=values[1]<count:raise AssetFormatError('Avatar IMG link out of range')
            records.append({'link':values[1]});continue
        _,extra,w,h,size,x,y,cw,ch=values
        if fmt not in (14,15,16,18,19,20) or extra not in (5,6):raise AssetFormatError('Unsupported avatar pixel/compression variant')
        if not 1<=cw<=512 or not 1<=ch<=512 or not ((1<=w<=512 and 1<=h<=512) or (w==h==0 and extra==6 and fmt in (14,15,16))):
            raise AssetFormatError('Avatar frame dimensions exceed budget')
        if fmt in (18,19,20):
            decoded=dxt_size(w,h,fmt)
            if version==4 and colors:raise AssetFormatError('Unsupported avatar palette/DXT combination')
            if extra==5 and size!=decoded:raise AssetFormatError('Avatar raw DXT size mismatch')
        elif extra==5:size=w*h*(4 if fmt==16 else 2)
        if not 0<size<=MAX_IMG:raise AssetFormatError('Invalid avatar frame payload size')
        records.append(dict(values=(fmt,extra,w,h,size,x,y,cw,ch),size=size))
    payload=32+table_size if version==2 else pos
    if payload<pos or payload>len(data):raise AssetFormatError('Invalid avatar data offset')
    for record in records:
        if 'link' in record:continue
        record['offset']=payload;payload+=record['size']
        if payload>len(data):raise AssetFormatError('Avatar frame outside file')
        if record['values'][2:4]==(0,0):
            inflate(data[record['offset']:payload],0)
    seen=set()
    while 'link' in records[index]:
        if index in seen:raise AssetFormatError('Cyclic avatar IMG link')
        seen.add(index);index=records[index]['link']
    record=records[index];fmt,extra,w,h,size,x,y,cw,ch=record['values']
    if abs(x)>8192 or abs(y)>8192:raise AssetFormatError('Avatar layer offset exceeds budget')
    if w==h==0:return Raster(1,1,b'\0'*4),x,y
    header=b'Neople Img File'.ljust(16,b'\0')+struct.pack('<4i',36,0,version,1)
    selected=struct.pack('<9i',fmt,extra,w,h,size,0,0,w,h)
    raw=data[record['offset']:record['offset']+size]
    image=decode_img(header+palette+selected+raw,0)
    visible=any(image.rgba[i] for i in range(3,len(image.rgba),4))
    if visible and (not 0<=x<=cw-w or not 0<=y<=ch-h):raise AssetFormatError('Nonempty avatar layer outside original canvas')
    return image,x,y


def render_pose(reader,raster,ani,first,recipes):
    """Render an exact CHR/ANI identity and per-slot PVF layer definitions."""
    ordered=[]
    for slot,(variation,layers,script) in recipes.items():
        if slot=='[skin avatar]':
            if layers:raise AssetFormatError('Unsupported skin layer override')
            ordered.append((1000,member_name(first.image,variation)))
        else:
            lay=reader.fields(script)
            if lay.get('[waiting motion]')!=['%s/Stay.ani'] or Path(ani).name!='stay.ani':
                raise AssetFormatError('Equipment waiting animation mismatch')
            for order,label in layers:ordered.append((order,member_name(first.image,variation,label)))
    rendered=[]
    for _,name in sorted(ordered,key=lambda entry:entry[0]):
        pixels,x,y=raster(name,first.frame)
        rendered.append((pixels,first.x+x,first.y+y))
    return composite(rendered)


def build_character_assets(pvf, npk_dir, source, output, encoding='gbk',outfits=()):
    """Merge clothed default poses and optional explicit avatar item recipes.

    Recipes are offline requests, not evidence of a character's current outfit.
    The runtime may use a recipe only after reading all actual worn slots and
    matching the same job, item identities and PVF fingerprint.
    """
    pvf,npk_dir,source,output=map(Path,(pvf,npk_dir,source,output))
    if output.exists():raise FileExistsError('Refusing to overwrite an asset pack')
    if source.is_symlink() or (source/'manifest.sqlite').is_symlink():raise AssetFormatError('Source pack symlink refused')
    with pvf.open('rb') as f:pvf_sha=hashlib.file_digest(f,'sha256').hexdigest()
    archives=[];members={}
    for path in sorted(npk_dir.iterdir()):
        if path.is_file() and path.suffix.lower()=='.npk':
            archive=Npk(path);archives.append(archive)
            for name in archive.members:members.setdefault(name,[]).append(archive)
    @lru_cache(maxsize=32)
    def raster(name,index):
        actual=name if name in members else 'sprite/'+name
        candidates=members.get(actual,[])
        if len(candidates)!=1:raise AssetFormatError('Missing or ambiguous character IMG member')
        try:return decode_avatar_img(candidates[0].read(actual),index)
        except AssetFormatError as error:raise AssetFormatError(actual+': '+str(error)) from error
    if not isinstance(outfits,(list,tuple)) or len(outfits)>256:raise AssetFormatError('Too many outfit recipes')
    requested={}
    for outfit in outfits:
        if not isinstance(outfit,dict) or set(outfit)!={'job','items'}:raise AssetFormatError('Invalid outfit recipe fields')
        recipe,digest=canonical_outfit_recipe(outfit['job'],outfit['items']);requested[digest]=recipe
    reader=Reader(pvf,encoding);prepared=[];contexts={};outfit_images=[]
    try:
        defaults=[]
        for name in reader.tree:
            if name.startswith('equipment/character/') and name.endswith('_default.equ') and ('/avatar/' in name or '/at_avatar/' in name):
                fields=reader.fields(name)
                defaults.append((name,fields,reader.tokens(name)))
        for job,path in reader.mapping('character/character.lst'):
            identity=normalized('character/'+path);detail='';image=None
            try:
                fields=reader.fields(identity);tag=fields.get('[job]',[])
                if len(tag)!=1 or not isinstance(tag[0],str):raise AssetFormatError('Invalid PVF job identity')
                waiting=fields.get('[waiting motion]',[])
                if len(waiting)!=1 or not isinstance(waiting[0],str):raise AssetFormatError('Missing waiting animation')
                ani=normalized(str(Path(identity).parent.as_posix())+'/'+waiting[0])
                first=parse_ani(reader.read(ani))[0];validate_static(first)
                body=fields.get('[body image path]',[])
                if len(body)!=1 or normalized(body[0])!=first.image:raise AssetFormatError('ANI/CHR body identity mismatch')
                by_slot={}
                for name,equ,tokens in defaults:
                    if tag[0] not in equ.get('[animation job]',[]):continue
                    kind=equ.get('[equipment type]',[])
                    if not kind or not isinstance(kind[0],str):continue
                    slot=kind[0]
                    recipe=equipment_recipe(tokens,tag[0])
                    by_slot.setdefault(slot,set()).add(recipe)
                if any(len(v)!=1 for v in by_slot.values()):raise AssetFormatError('Ambiguous default avatar recipes')
                if not all('['+slot+' avatar]' in by_slot for slot in ('skin','coat','pants','shoes','hair')):
                    raise AssetFormatError('Incomplete default outfit')
                context=(tag[0],ani,first,{slot:next(iter(recipes)) for slot,recipes in by_slot.items()})
                image=render_pose(reader,raster,*context[1:])
                contexts[job]=context
                state='ready'
            except (AssetFormatError,KeyError,ValueError,TypeError,UnicodeError) as error:
                state='unsupported';detail=str(error)[:160]
            prepared.append((job,image,state,detail))
        equipment={}
        if requested:
            for identity,path in reader.mapping('equipment/equipment.lst'):equipment.setdefault(identity,[]).append(path)
        for digest,recipe in requested.items():
            image=None;detail='';job=recipe['job']
            try:
                if job not in contexts:raise AssetFormatError('No supported default job context for outfit')
                tag,ani,first,defaults=contexts[job]
                resolved=resolve_outfit_recipes(reader,tag,defaults,recipe['items'],equipment)
                image=render_pose(reader,raster,ani,first,resolved);state='ready'
            except (AssetFormatError,KeyError,ValueError,TypeError,UnicodeError) as error:
                state='unsupported';detail=str(error)[:160]
            outfit_images.append((job,digest,image,state,detail))
        with closing(sqlite3.connect((source/'manifest.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as old:
            meta=dict(old.execute('SELECT key,value FROM metadata'))
            if meta.get('pvf_sha256')!=pvf_sha or meta.get('state')!='ready':raise AssetFormatError('PVF/source-pack mismatch')
            output.mkdir(mode=0o750);(output/'images').mkdir(mode=0o750)
            with closing(sqlite3.connect(output/'manifest.sqlite')) as new:
                old.backup(new);new.executescript(SCHEMA);new.execute('DELETE FROM job_previews')
                new.execute('DELETE FROM outfit_previews')
                for digest,width,height in old.execute('SELECT sha256,width,height FROM files'):
                    if not re.fullmatch(r'[0-9a-f]{64}',digest):raise AssetFormatError('Invalid source image digest')
                    path=source/'images'/(digest+'.png')
                    if path.is_symlink() or not path.is_file() or path.stat().st_size>2*1024*1024:raise AssetFormatError('Invalid source image file')
                    data=path.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=digest:raise AssetFormatError('Source image checksum mismatch')
                    (output/'images'/path.name).write_bytes(data)
                for job,image,state,detail in prepared:
                    digest=None
                    if image:
                        data=image.png();digest=hashlib.sha256(data).hexdigest()
                        (output/'images'/(digest+'.png')).write_bytes(data)
                        new.execute('INSERT OR IGNORE INTO files VALUES(?,?,?)',(digest,image.width,image.height))
                    new.execute('INSERT INTO job_previews VALUES(?,?,?,?,?,?)',(job,digest,state,'waiting_first_frame','client_default_pose',detail))
                for job,recipe_digest,image,state,detail in outfit_images:
                    digest=None
                    if image:
                        data=image.png();digest=hashlib.sha256(data).hexdigest()
                        (output/'images'/(digest+'.png')).write_bytes(data)
                        new.execute('INSERT OR IGNORE INTO files VALUES(?,?,?)',(digest,image.width,image.height))
                    new.execute('INSERT INTO outfit_previews VALUES(?,?,?,?,?)',(job,recipe_digest,digest,state,detail))
                ready=sum(state=='ready' for _,_,state,_ in prepared)
                outfit_ready=sum(state=='ready' for _,_,_,state,_ in outfit_images)
                new.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[
                    ('job_previews_version','1'),('job_previews',str(ready)),
                    ('outfit_previews_version','1'),('outfit_previews',str(outfit_ready))]);new.commit()
        for path in output.rglob('*'):
            if path.is_file():path.chmod(0o640)
        return {'pvf_sha256':pvf_sha,'jobs':len(prepared),'ready':ready,
                'unsupported':[{'job':job,'reason':detail} for job,_,state,detail in prepared if state!='ready'],
                'outfits':len(outfit_images),'outfits_ready':outfit_ready,
                'outfits_unsupported':[{'job':job,'recipe_sha256':digest,'reason':detail} for job,digest,_,state,detail in outfit_images if state!='ready'],
                'client_verified':False}
    except BaseException:
        if output.exists():shutil.rmtree(output)
        raise
    finally:reader.close()
