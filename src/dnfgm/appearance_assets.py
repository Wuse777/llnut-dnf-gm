"""Offline private appearance v2 compiler. Runtime never imports this module.

Each equipment layer follows its own LAY/ANI timeline. Exact extracted pixels,
anchors and delays are retained; unsupported transforms never become defaults.
"""
import binascii
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import zlib

from .character_assets import parse_ani,validate_static,equipment_recipe,decode_avatar_img
from .npk_assets import AssetFormatError,Npk,normalized
from .outfit_recipe import AVATAR_SLOTS
from .appearance_manifest import merge_clips,validate_clip
from .pvf import Reader

SCHEMA='''CREATE TABLE IF NOT EXISTS appearance_atlases(
 sha256 TEXT PRIMARY KEY,width INTEGER NOT NULL,height INTEGER NOT NULL,bytes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS appearance_parts(
 job INTEGER NOT NULL,slot TEXT NOT NULL,item_id INTEGER NOT NULL,action TEXT NOT NULL,
 state TEXT NOT NULL,payload_json TEXT NOT NULL,detail TEXT NOT NULL,
 PRIMARY KEY(job,slot,item_id,action));
CREATE TABLE IF NOT EXISTS appearance_dye_colors(
 color_id INTEGER PRIMARY KEY,r INTEGER NOT NULL,g INTEGER NOT NULL,b INTEGER NOT NULL,label TEXT NOT NULL);
'''
MOTIONS={'idle':'[waiting motion]','walk':'[move motion]','attack':'[attack motion]'}


def png(width,height,rgba):
    """Atlas-only encoder. The shared 512px Raster contract stays unchanged."""
    if not 1<=width<=2048 or not 1<=height<=2048 or len(rgba)!=width*height*4:raise AssetFormatError('Atlas pixel budget')
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
    lines=b''.join(b'\0'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
    result=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(lines))+chunk(b'IEND',b'')
    if len(result)>16*1024*1024:raise AssetFormatError('Atlas encoded budget')
    return result


class AtlasPacker:
    """One bounded scratch page; deduplicated exact tiles within a component."""
    def __init__(self,directory):
        self.directory=directory;self.pages=[];self.tiles={};self.refs=[]
        self.pixels=bytearray(1024*2048*4);self.x=self.y=self.row_height=0
    def flush(self):
        height=self.y+self.row_height
        if not height:return
        data=png(1024,height,bytes(self.pixels[:1024*height*4]));sha=hashlib.sha256(data).hexdigest()
        path=self.directory/(sha+'.png')
        if not path.exists():path.write_bytes(data)
        self.pages.append({'sha256':sha,'width':1024,'height':height,'bytes':len(data)})
        self.pixels=bytearray(1024*2048*4);self.x=self.y=self.row_height=0
    def add(self,raster):
        key=hashlib.sha256(struct.pack('<HH',raster.width,raster.height)+raster.rgba).digest()
        if key in self.tiles:return self.tiles[key]
        w,h=raster.width,raster.height
        if self.x+w>1024:self.y+=self.row_height;self.x=0;self.row_height=0
        if self.y+h>2048:self.flush()
        result={'page':len(self.pages),'sx':self.x,'sy':self.y,'width':w,'height':h}
        for y in range(h):
            start=((self.y+y)*1024+self.x)*4;self.pixels[start:start+w*4]=raster.rgba[y*w*4:(y+1)*w*4]
        self.x+=w;self.row_height=max(self.row_height,h);self.tiles[key]=result
        return result
    def finish(self,clip):
        self.flush()
        for frame in clip['frames']:
            for draw in frame['draws']:draw['atlas']=self.pages[draw.pop('page')]['sha256']
        return clip,self.pages


def timeline(frames):
    if not 1<=len(frames)<=120:raise AssetFormatError('ANI exceeds 120-frame budget')
    for frame in frames:
        # Empty image frames still have time and are preserved.
        if frame.image:validate_static(frame)
        if type(frame.duration_ms) is not int or not 1<=frame.duration_ms<=10000:
            raise AssetFormatError('ANI delay missing or outside budget')
        params=dict(frame.parameters)
        if params.get(0,0) not in (0,1) or any(tag in params for tag in (25,26)):
            raise AssetFormatError('ANI partial-loop rules not adapted')
        if params.get(3,0)!=0:raise AssetFormatError('ANI coordinate mode not adapted')
    duration=sum(f.duration_ms for f in frames)
    if duration>10000 or len({f.loop for f in frames})!=1:raise AssetFormatError('ANI duration/loop budget')
    return duration,frames[0].loop


def color_map(tokens):
    """Exact PVF ID→RGB table, independently useful without claiming tint math."""
    if tokens and tokens[-1]==(5,'[/avatar color map]'):tokens=tokens[:-1]
    if not tokens or tokens[0]!=(5,'[avatar color map]') or (len(tokens)-1)%5:
        raise AssetFormatError('Avatar color table shape not adapted')
    rows=[];seen=set()
    for start in range(1,len(tokens),5):
        group=tokens[start:start+5]
        if any(kind!=2 or type(value) is not int for kind,value in group[:4]) or group[4][0]!=7:
            raise AssetFormatError('Invalid avatar color fields')
        identity,r,g,b=(p[1] for p in group[:4]);label=group[4][1]
        if not 0<=identity<=32767 or identity in seen or any(not 0<=c<=255 for c in (r,g,b)) or not isinstance(label,str) or len(label)>120:
            raise AssetFormatError('Invalid avatar color values')
        seen.add(identity);rows.append((identity,r,g,b,label))
    return rows


def compile_component(reader,raster,directory,body_frames,recipe,equ_path,action):
    variation,layers,script=recipe;duration,loop=timeline(body_frames)
    packer=AtlasPacker(directory);clips=[];omissions=[]
    def layer_clip(frames,order,template=None):
        actual_duration,actual_loop=timeline(frames)
        if actual_duration!=duration or actual_loop!=loop:raise AssetFormatError('Equipment/body timeline mismatch')
        output=[]
        for frame in frames:
            draws=[]
            if frame.image:
                name=frame.image
                if template=='body':
                    if name.count('%04d')!=1:raise AssetFormatError('Unexpected body image template')
                    name=name.replace('%04d',f'{variation[0]*100+variation[1]:04d}')
                else:
                    if name.count('%02d')!=2:raise AssetFormatError('Unexpected equipment image template')
                    name=name.replace('%02d',f'{variation[0]:02d}',1).replace('%02d',f'{variation[1]:02d}',1)
                pixels,x,y=raster(name,frame.frame)
                if any(pixels.rgba[i] for i in range(3,len(pixels.rgba),4)):
                    draws.append({**packer.add(pixels),'x':frame.x+x,'y':frame.y+y,'z':order})
            output.append({'duration_ms':frame.duration_ms,'draws':draws})
        return {'loop':loop,'duration_ms':duration,'frames':output}
    if not layers:
        if '/skin/' in equ_path:clips.append(layer_clip(body_frames,1000,'body'))
    else:
        fields=reader.fields(script);paths=fields.get(MOTIONS[action],[])
        if not paths or not isinstance(paths[0],str) or paths[0].count('%s')!=1:
            raise AssetFormatError('Missing exact equipment action mapping')
        marker='/at_avatar/' if '/at_avatar/' in equ_path else '/avatar/'
        weapon='/weapon/' in equ_path
        if weapon:root=str(Path(equ_path).parent.as_posix())
        elif marker in equ_path:root=equ_path.split(marker)[0]+marker.rstrip('/')
        else:raise AssetFormatError('Unknown equipment script family')
        for order,label in layers:
            part=label.split('_')[0]
            folder=root+'/'+label if weapon else root+'/'+part+'/'+label
            path=normalized(paths[0].replace('%s',folder))
            frames=parse_ani(reader.read(path))
            # A separately identified graphic-effect layer can be omitted only
            # as an explicit partial result. Its pixels are never normal-blended.
            if any(tag==11 and value!=0 for frame in frames for tag,value in frame.visual):
                omissions.append('graphic_effect_unverified');continue
            clips.append(layer_clip(frames,order))
    if not clips and omissions:raise AssetFormatError('Component has no supported base layers')
    clip=merge_clips(clips) if clips else {'loop':loop,'duration_ms':duration,'frames':[{'duration_ms':duration,'draws':[]}]}
    clip,pages=packer.finish(clip)
    return clip,pages,sorted(set(omissions))


def enrich_appearance_assets(pvf,npk_dir,pack,items=(),encoding='gbk'):
    """Append v2 to a newly created PRIVATE pack; callers never mutate live packs.

    `items` is an explicit list of PVF item IDs. Defaults are separate item_id=0
    components and can only fill unworn slots, never replace a missing worn ID.
    """
    pvf,npk_dir,pack=map(Path,(pvf,npk_dir,pack));directory=pack/'atlases'
    if directory.exists():raise FileExistsError('Refusing to overwrite appearance atlas library')
    if not isinstance(items,(tuple,list,set)) or len(items)>20000 or any(type(i) is not int or not 1<=i<=0x7fffffff for i in items):
        raise AssetFormatError('Invalid explicit avatar item list')
    with pvf.open('rb') as source:pvf_sha=hashlib.file_digest(source,'sha256').hexdigest()
    with sqlite3.connect(pack/'manifest.sqlite') as c:
        if dict(c.execute('SELECT key,value FROM metadata')).get('pvf_sha256')!=pvf_sha:raise AssetFormatError('Appearance pack fingerprint mismatch')
    members={}
    for path in sorted(npk_dir.iterdir()):
        if path.is_file() and path.suffix.lower()=='.npk':
            archive=Npk(path)
            for name in archive.members:members.setdefault(name,[]).append(archive)
    @lru_cache(maxsize=128)
    def raster(name,index):
        actual=name if name in members else 'sprite/'+name;candidates=members.get(actual,[])
        if len(candidates)!=1:raise AssetFormatError('Missing or ambiguous avatar member')
        return decode_avatar_img(candidates[0].read(actual),index)
    directory.mkdir();reader=Reader(pvf,encoding);prepared=[];pages={};diagnostics=[]
    try:
        defaults=[]
        for path in reader.tree:
            if path.startswith('equipment/character/') and path.endswith('_default.equ') and any(s in path for s in ('/avatar/','/at_avatar/')):
                defaults.append((path,reader.fields(path),reader.tokens(path)))
        equipment={}
        for identity,path in reader.mapping('equipment/equipment.lst'):
            if identity in items:equipment.setdefault(identity,[]).append(normalized('equipment/'+path))
        for job,path in reader.mapping('character/character.lst'):
            identity=normalized('character/'+path);fields=reader.fields(identity);tag=fields.get('[job]',[])
            if len(tag)!=1:continue
            base={};ambiguous=set()
            for equ_path,equ,tokens in defaults:
                if tag[0] not in equ.get('[animation job]',[]):continue
                slot=equ.get('[equipment type]',[None])[0]
                if slot not in AVATAR_SLOTS:continue
                recipe=equipment_recipe(tokens,tag[0]);value=(recipe,equ_path)
                if slot in base and base[slot][0]!=recipe:ambiguous.add(slot)
                base[slot]=value
            requested=[]
            for slot in sorted(AVATAR_SLOTS):requested.append((slot,0,base.get(slot)))
            for item_id,paths in sorted(equipment.items()):
                if len(paths)!=1:continue
                equ_path=paths[0];equ=reader.fields(equ_path);slot=equ.get('[equipment type]',[None])[0]
                if slot not in AVATAR_SLOTS|{'[weapon]'} or tag[0] not in equ.get('[animation job]',[]):continue
                try:requested.append((slot,item_id,(equipment_recipe(reader.tokens(equ_path),tag[0],layer_pattern=r'[a-z][a-z_0-9]{0,47}'),equ_path)))
                except (ValueError,TypeError,KeyError):continue
            for action,motion in MOTIONS.items():
                body=None;error=None;paths=fields.get(motion,[])
                try:
                    if not paths or not isinstance(paths[0],str):raise AssetFormatError('CHR has no exact action mapping')
                    body=parse_ani(reader.read(normalized(str(Path(identity).parent.as_posix())+'/'+paths[0])))
                    timeline(body)
                    expected=fields.get('[body image path]',[])
                    if len(expected)!=1 or any(f.image and f.image!=normalized(expected[0]) for f in body):
                        raise AssetFormatError('Action body identity mismatch')
                except (ValueError,TypeError,KeyError) as e:error=str(e)
                cache={}
                for slot,item_id,value in requested:
                    payload='{}';state='unsupported';detail=error or ''
                    try:
                        if error:raise AssetFormatError(error)
                        if slot in ambiguous and item_id==0:raise AssetFormatError('Ambiguous default component')
                        if value is None:
                            if slot in ('[skin avatar]','[coat avatar]','[pants avatar]','[shoes avatar]','[hair avatar]'):
                                raise AssetFormatError('Required default component missing')
                            clip={'loop':body[0].loop,'duration_ms':sum(f.duration_ms for f in body),'frames':[{'duration_ms':sum(f.duration_ms for f in body),'draws':[]}]};actual_pages=[]
                            omitted=[]
                        elif value in cache:clip,actual_pages,omitted=cache[value]
                        else:
                            clip,actual_pages,omitted=compile_component(reader,raster,directory,body,value[0],value[1],action);cache[value]=(clip,actual_pages,omitted)
                        for page in actual_pages:pages[page['sha256']]=page
                        validate_clip(clip,pages);payload=json.dumps(clip,separators=(',',':'));state='partial' if omitted else 'ready'
                        if omitted:detail=','.join(omitted)
                    except (ValueError,TypeError,KeyError,StopIteration) as e:detail=str(e)[:200]
                    prepared.append((job,slot,item_id,action,state,payload,detail))
                    if state=='unsupported':diagnostics.append({'job':job,'slot':slot,'item_id':item_id,'action':action,'detail':detail})
        palette=color_map(reader.tokens('etc/avatarcolorvariation.etc')) if 'etc/avatarcolorvariation.etc' in reader.tree else []
        with sqlite3.connect(pack/'manifest.sqlite') as c:
            c.executescript(SCHEMA)
            c.executemany('INSERT INTO appearance_parts VALUES(?,?,?,?,?,?,?)',prepared)
            c.executemany('INSERT OR IGNORE INTO appearance_atlases VALUES(?,?,?,?)',[(p['sha256'],p['width'],p['height'],p['bytes']) for p in pages.values()])
            c.executemany('INSERT INTO appearance_dye_colors VALUES(?,?,?,?,?)',palette)
            c.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('appearance_version','2'),('appearance_source','private_client'),('appearance_dye_pixel_rule','unverified')])
        for p in directory.iterdir():p.chmod(0o640)
        return {'version':2,'parts_ready':sum(p[4]=='ready' for p in prepared),'parts_partial':sum(p[4]=='partial' for p in prepared),'parts_unsupported':len(diagnostics),
                'atlases':len(pages),'dye_colors':len(palette),'client_verified':False,'diagnostics':diagnostics}
    finally:reader.close();raster.cache_clear()
