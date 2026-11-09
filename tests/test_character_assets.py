"""Synthetic ANI/avatar records; no proprietary client material in tests."""
import struct
import zlib
import hashlib
import json
import sqlite3

import pytest

from dnfgm.character_assets import AnimationFrame, build_character_assets, canonical_outfit_recipe, composite, decode_avatar_img, equipment_recipe, member_name, parse_ani, resolve_outfit_recipes, validate_static
from dnfgm.npk_assets import AssetFormatError, Raster
from dnfgm.outfit_recipe import OutfitRecipeError


def test_v2_source_atlases_are_preserved_or_cleanly_replaced_in_a_new_pack(tmp_path,monkeypatch):
    from dnfgm import character_assets
    from dnfgm.appearance_assets import png,SCHEMA
    pvf=tmp_path/'source.pvf';pvf.write_bytes(b'synthetic pvf')
    source=tmp_path/'source';source.mkdir();(source/'images').mkdir();(source/'atlases').mkdir()
    data=png(1024,1,b'\0'*4096);digest=hashlib.sha256(data).hexdigest()
    atlas=source/'atlases'/(digest+'.png');atlas.write_bytes(data)
    with sqlite3.connect(source/'manifest.sqlite') as c:
        c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE files(sha256 TEXT PRIMARY KEY,width INTEGER,height INTEGER);'+SCHEMA)
        c.executemany('INSERT INTO metadata VALUES(?,?)',[('state','ready'),('pvf_sha256',hashlib.sha256(pvf.read_bytes()).hexdigest()),('appearance_version','2')])
        c.execute('INSERT INTO appearance_atlases VALUES(?,?,?,?)',(digest,1024,1,len(data)))
        payload={'loop':True,'duration_ms':100,'frames':[{'duration_ms':100,'draws':[{'atlas':digest,'sx':0,'sy':0,'width':1,'height':1,'x':0,'y':0,'z':1000}]}]}
        c.execute('INSERT INTO appearance_parts VALUES(?,?,?,?,?,?,?)',(0,'[coat avatar]',0,'idle','ready',json.dumps(payload),''))
    class Reader:
        tree=()
        def __init__(self,*args):pass
        def mapping(self,path):return iter(())
        def close(self):pass
    monkeypatch.setattr(character_assets,'Reader',Reader)
    npks=tmp_path/'npks';npks.mkdir()
    preserved=tmp_path/'preserved';build_character_assets(pvf,npks,source,preserved)
    assert (preserved/'atlases'/atlas.name).read_bytes()==data
    with sqlite3.connect(preserved/'manifest.sqlite') as c:
        assert c.execute('SELECT payload_json FROM appearance_parts').fetchone()[0]==json.dumps(payload)
    replaced=tmp_path/'replaced';build_character_assets(pvf,npks,source,replaced,preserve_appearance=False)
    assert not (replaced/'atlases').exists()
    with sqlite3.connect(replaced/'manifest.sqlite') as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='appearance_parts'").fetchone() is None
        assert c.execute("SELECT 1 FROM metadata WHERE key='appearance_version'").fetchone() is None
    assert atlas.read_bytes()==data
    atlas.write_bytes(b'x'*len(data));invalid=tmp_path/'invalid'
    with pytest.raises(AssetFormatError,match='checksum'):
        build_character_assets(pvf,npks,source,invalid)
    assert not invalid.exists()


def ani(*,extra=b'',frame_params=b'',tail=b'',index=3,path_index=0):
    path=b'Character/Example/Equipment/Avatar/skin/ex_body%04d.img'
    return (struct.pack('<HHI',1,1,len(path))+path+struct.pack('<HHB',1,1,1)
            +struct.pack('<H',0)+struct.pack('<hhii',path_index,index,-200,-300)
            +struct.pack('<H',bool(frame_params))+frame_params+tail)


def test_reads_authoritative_ani_path_frame_and_position():
    result=parse_ani(ani(frame_params=struct.pack('<Hi',12,120)))
    assert result==(AnimationFrame('character/example/equipment/avatar/skin/ex_body%04d.img',3,-200,-300,()),)
    validate_static(result[0])


@pytest.mark.parametrize('change',[{'tail':b'\0'},{'path_index':1},{'index':-2},{'frame_params':struct.pack('<Hh',0x72,0)}])
def test_refuses_unknown_or_malformed_ani_without_guessing(change):
    with pytest.raises(AssetFormatError):parse_ani(ani(**change))


def test_refuses_truncated_records_and_transform_that_is_not_applied():
    raw=ani()
    for end in range(len(raw)):
        with pytest.raises(AssetFormatError):parse_ani(raw[:end])
    frame=parse_ani(ani(frame_params=struct.pack('<Hf',8,45.0)))[0]
    with pytest.raises(AssetFormatError,match='visual transform'):validate_static(frame)


def test_groups_repeated_equipment_job_sections_before_selecting_variation():
    tokens=[(5,'[animation job]'),(7,'[example]'),(5,'[variation]'),(2,0),(2,1),
            (5,'[layer variation]'),(2,1800),(7,'coat_a'),(5,'[equipment ani script]'),(7,'equipment/character/example.lay'),
            (5,'[animation job]'),(7,'[other]'),(5,'[variation]'),(2,129),(2,0),
            (5,'[layer variation]'),(2,2000),(7,'hair_a'),(5,'[equipment ani script]'),(7,'equipment/character/other.lay')]
    assert equipment_recipe(tokens,'[example]')==((0,1),((1800,'coat_a'),),'equipment/character/example.lay')
    assert equipment_recipe(tokens,'[other]')==((129,0),((2000,'hair_a'),),'equipment/character/other.lay')
    with pytest.raises(AssetFormatError):equipment_recipe(tokens+tokens,'[example]')


def test_member_identity_preserves_chr_family_and_explicit_variation():
    body='Character/Example/ATEquipment/Avatar/skin/ex_body%04d.img'
    assert member_name(body,(0,1000))=='character/example/atequipment/avatar/skin/ex_body1000.img'
    assert member_name(body,(129,0),'coat_a')=='character/example/atequipment/avatar/coat/ex_coat12900a.img'
    with pytest.raises(AssetFormatError):member_name('../unsafe/body%04d.img',(0,0))


def test_composition_uses_straight_alpha_order_and_transparent_crop():
    red=Raster(2,1,bytes((255,0,0,255,0,0,0,0)))
    blue=Raster(1,1,bytes((0,0,255,128)))
    result=composite([(red,-20,-10),(blue,-20,-10)])
    assert result.width==result.height==1
    assert result.rgba==bytes((127,0,128,255))
    assert composite([(blue,0,0),(red,0,0)]).rgba==bytes((255,0,0,255))


def test_empty_or_excessive_composite_is_never_a_blank_success():
    blank=Raster(1,1,b'\0'*4)
    opaque=Raster(1,1,b'\xff'*4)
    with pytest.raises(AssetFormatError):composite([(blank,0,0)])
    with pytest.raises(AssetFormatError):composite([(opaque,0,0),(opaque,512,0)])
    with pytest.raises(AssetFormatError):composite([(opaque,8193,0)])


def avatar_sheet(frames):
    table=bytearray();payload=bytearray()
    for entry in frames:
        if isinstance(entry,int):table.extend(struct.pack('<2i',17,entry));continue
        w,h,x,y,raw=entry;encoded=zlib.compress(raw)
        table.extend(struct.pack('<9i',16,6,w,h,len(encoded),x,y,500,500));payload.extend(encoded)
    return b'Neople Img File'.ljust(16,b'\0')+struct.pack('<4i',len(table),0,2,len(frames))+table+payload


def test_avatar_cropped_pixels_retain_offset_and_link_identity():
    raw=avatar_sheet([(1,1,240,352,b'\x30\x20\x10\xff'),0])
    assert decode_avatar_img(raw,1)==(Raster(1,1,b'\x10\x20\x30\xff'),240,352)


def test_avatar_accepts_proven_transparent_zero_and_outside_sentinels():
    raw=avatar_sheet([(0,0,500,0,b''),(1,1,500,0,b'\0'*4),(1,1,100,150,b'\xff'*4)])
    assert decode_avatar_img(raw,0)==(Raster(1,1,b'\0'*4),500,0)
    assert decode_avatar_img(raw,1)==(Raster(1,1,b'\0'*4),500,0)
    assert decode_avatar_img(raw,2)==(Raster(1,1,b'\xff'*4),100,150)
    with pytest.raises(AssetFormatError):decode_avatar_img(avatar_sheet([(0,0,500,0,b'x')]),0)
    with pytest.raises(AssetFormatError):decode_avatar_img(avatar_sheet([(0,1,500,0,b'')]),0)
    with pytest.raises(AssetFormatError,match='outside original'):decode_avatar_img(avatar_sheet([(1,1,500,0,b'\xff'*4)]),0)


def test_avatar_refuses_cycles_corrupt_records_truncation_and_bad_links():
    for frames in ([0],[1,0],[3]):
        with pytest.raises(AssetFormatError):decode_avatar_img(avatar_sheet(frames),0)
    raw=avatar_sheet([(1,1,0,0,b'\xff'*4),0])
    for end in range(len(raw)):
        with pytest.raises(AssetFormatError):decode_avatar_img(raw[:end],0)
    with pytest.raises(AssetFormatError):decode_avatar_img(b'!'*16+raw[16:],0)
    with pytest.raises(AssetFormatError):decode_avatar_img(raw,True)


def test_outfit_hash_is_canonical_and_does_not_accept_unverified_identity_fields():
    a={'slot':'[coat avatar]','id':42};b={'slot':'[hair avatar]','id':43}
    first,digest=canonical_outfit_recipe(0,[a,b])
    assert canonical_outfit_recipe(0,[b,a])==(first,digest)
    assert canonical_outfit_recipe(1,[a,b])[1]!=digest
    assert len(digest)==64 and first=={'job':0,'items':[a,b]}
    for job,items in [(True,[a]),(0,[a,a]),(0,[dict(a,id=True)]),(0,[dict(a,charac_no=3)]),(0,[dict(a,slot='[weapon]')])]:
        with pytest.raises(OutfitRecipeError):canonical_outfit_recipe(job,items)


def test_runtime_recipe_helper_does_not_load_offline_parsers():
    import os,subprocess,sys
    from pathlib import Path
    result=subprocess.run([sys.executable,'-c',
        "import dnfgm.outfit_recipe,sys; assert not ({'dnfgm.character_assets','dnfgm.npk_assets','dnfgm.pvf'} & set(sys.modules))"],
        capture_output=True,text=True,env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')})
    assert result.returncode==0,result.stderr


def test_outfit_resolution_refuses_missing_ids_wrong_slot_and_other_job():
    class Reader:
        def fields(self,path):return {'[equipment type]':['[coat avatar]']}
        def tokens(self,path):return [(5,'[animation job]'),(7,'[other]'),(5,'[variation]'),(2,1),(2,0)]
    reader=Reader();item={'id':42,'slot':'[coat avatar]'}
    for entries in ({},{42:['a','b']}):
        with pytest.raises(AssetFormatError,match='ambiguous'):resolve_outfit_recipes(reader,'[example]',{},[item],entries)
    with pytest.raises(AssetFormatError,match='slot mismatch'):
        resolve_outfit_recipes(reader,'[example]',{},[dict(item,slot='[hair avatar]')],{42:['a']})
    with pytest.raises(AssetFormatError,match='animation job'):
        resolve_outfit_recipes(reader,'[example]',{},[item],{42:['a']})


def test_builder_merges_default_and_explicit_outfit_without_silent_id_fallback(tmp_path,monkeypatch):
    from dnfgm import character_assets
    from dnfgm.asset_builder import SCHEMA
    from dnfgm.npk_assets import KEY,decode_png
    pvf=tmp_path/'private.pvf';pvf.write_bytes(b'synthetic pvf')
    source=tmp_path/'source';source.mkdir();(source/'images').mkdir()
    old=Raster(1,1,b'\x00\x00\x00\xff');png=old.png();sha=hashlib.sha256(png).hexdigest()
    (source/'images'/(sha+'.png')).write_bytes(png)
    with sqlite3.connect(source/'manifest.sqlite') as db:
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO metadata VALUES(?,?)',[('pvf_sha256',hashlib.sha256(pvf.read_bytes()).hexdigest()),('state','ready')])
        db.execute('INSERT INTO files VALUES(?,?,?)',(sha,1,1))
    body='character/example/equipment/avatar/skin/ex_body%04d.img'
    defaults={};tokens={};members=[]
    for order,part in enumerate(('skin','coat','pants','shoes','hair')):
        name='equipment/character/example/avatar/'+part+'/a_default.equ'
        defaults[name]={'[equipment type]':['['+part+' avatar]'],'[animation job]':['[example]']}
        row=[(5,'[animation job]'),(7,'[example]'),(5,'[variation]'),(2,0),(2,0)]
        if part!='skin':row+=[(5,'[layer variation]'),(2,1000+order),(7,part+'_a'),(5,'[equipment ani script]'),(7,'example.lay')]
        tokens[name]=row
        color=b'\0\0\xff\xff' if part=='skin' else (b'\xff\0\0\x80' if part=='coat' else b'\0'*4)
        members.append(('sprite/'+member_name(body,(0,0),None if part=='skin' else part+'_a'),avatar_sheet([(1,1,200,300,color)])))
    itempath='equipment/character/example/avatar/coat/changed.equ'
    defaults[itempath]={'[equipment type]':['[coat avatar]']}
    tokens[itempath]=[(5,'[animation job]'),(7,'[example]'),(5,'[variation]'),(2,1),(2,0),
        (5,'[layer variation]'),(2,1001),(7,'coat_a'),(5,'[equipment ani script]'),(7,'example.lay')]
    members.append(('sprite/'+member_name(body,(1,0),'coat_a'),avatar_sheet([(1,1,200,300,b'\0\xff\0\xff')])))
    class FakeReader:
        tree=defaults
        def __init__(self,*args):pass
        def close(self):pass
        def fields(self,path):
            if path=='character/example/example.chr':return {'[job]':['[example]'],'[waiting motion]':['Animation/Stay.ani'],'[body image path]':[body]}
            if path=='example.lay':return {'[waiting motion]':['%s/Stay.ani']}
            return defaults[path]
        def tokens(self,path):return tokens[path]
        def mapping(self,path):
            return iter([(0,'Example/Example.chr')] if path=='character/character.lst' else [(42,'character/example/avatar/coat/changed.equ')])
        def read(self,path):return ani(index=0)
    monkeypatch.setattr(character_assets,'Reader',FakeReader)
    # The ANI fixture must use the same exact body family as the CHR.
    oldpath=b'Character/Example/Equipment/Avatar/skin/ex_body%04d.img'
    assert oldpath.lower()==body.encode()
    folder=tmp_path/'npks';folder.mkdir();offset=20+264*len(members);table=bytearray();payload=bytearray()
    for name,data in members:
        encoded=bytes(a^b for a,b in zip(name.encode().ljust(256,b'\0'),KEY))
        table.extend(struct.pack('<II',offset,len(data))+encoded);payload.extend(data);offset+=len(data)
    (folder/'synthetic.npk').write_bytes(b'NeoplePack_Bill'.ljust(16,b'\0')+struct.pack('<I',len(members))+table+payload)
    outfits=[{'job':0,'items':[{'slot':'[coat avatar]','id':identity}]} for identity in (42,404)]
    out=tmp_path/'new'
    result=build_character_assets(pvf,folder,source,out,outfits=outfits)
    assert result['ready']==1 and result['outfits_ready']==1 and len(result['outfits_unsupported'])==1
    with sqlite3.connect(out/'manifest.sqlite') as db:
        default_digest=db.execute('SELECT sha256 FROM job_previews').fetchone()[0]
        changed=db.execute("SELECT sha256 FROM outfit_previews WHERE state='ready'").fetchone()[0]
        assert db.execute("SELECT sha256 FROM outfit_previews WHERE state='unsupported'").fetchone()==(None,)
    assert decode_png((out/'images'/(default_digest+'.png')).read_bytes()).rgba==b'\x7f\0\x80\xff'
    assert decode_png((out/'images'/(changed+'.png')).read_bytes()).rgba==b'\0\xff\0\xff'
    assert (out/'images'/(sha+'.png')).read_bytes()==png
