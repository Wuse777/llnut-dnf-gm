"""Synthetic artwork only. Never imports or bundles real game material."""
import binascii
import hashlib
import json
import sqlite3
import struct
import time
import zlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from dnfgm.config import Settings
from dnfgm.npk_assets import Raster,decode_png,decode_img,Npk,KEY,AssetFormatError,inflate,normalized
from dnfgm.asset_builder import build_assets,SCHEMA
from dnfgm.game_assets import GameAssets


def img(fmt=16,raw=b'\x30\x20\x10\xff',compressed=False,version=2,palette=b'',link=False):
    payload=zlib.compress(raw) if compressed else raw
    table=struct.pack('<9i',fmt,6 if compressed else 5,1,1,len(payload),1,1,2,2)
    if link:table+=struct.pack('<2i',17,0)
    return b'Neople Img File'.ljust(16,b'\0')+struct.pack('<4i',len(table),0,version,2 if link else 1)+(struct.pack('<i',len(palette)//4)+palette if version==4 else b'')+table+payload


def npk(path,entries):
    offset=20+264*len(entries);table=bytearray();payload=bytearray()
    for name,data in entries:
        encoded=bytes(a^b for a,b in zip(name.encode('cp949').ljust(256,b'\0'),KEY))
        table.extend(struct.pack('<II',offset,len(data))+encoded);payload.extend(data);offset+=len(data)
    path.write_bytes(b'NeoplePack_Bill'.ljust(16,b'\0')+struct.pack('<I',len(entries))+table+payload)
    return path


def pack(tmp_path,sha='a'*64):
    root=tmp_path/'pack';root.mkdir();(root/'images').mkdir()
    png=Raster(1,1,b'\x12\x34\x56\xff').png();digest=hashlib.sha256(png).hexdigest()
    (root/'images'/(digest+'.png')).write_bytes(png)
    with sqlite3.connect(root/'manifest.sqlite') as c:
        c.executescript(SCHEMA)
        c.executemany('INSERT INTO metadata VALUES(?,?)',{'format':'dnfgm-assets-v1','state':'ready','pvf_sha256':sha,'counts':'{"ready":1}','portraits':'1'}.items())
        c.execute('INSERT INTO files VALUES(?,?,?)',(digest,1,1))
        c.execute('INSERT INTO item_images(item_id,sha256,state) VALUES(?,?,?)',(990001,digest,'ready'))
        c.execute('INSERT INTO portraits VALUES(0,-1,-1,?)',(digest,))
    return root,digest,png


@pytest.mark.parametrize('fmt,raw,expected',[(16,b'\x30\x20\x10\xff',b'\x10\x20\x30\xff'),(14,struct.pack('<H',0xfc00),b'\xff\0\0\xff'),(15,struct.pack('<H',0xf123),b'\x11\x22\x33\xff')])
@pytest.mark.parametrize('compressed',[False,True])
def test_decode_formats_canvas_and_png(fmt,raw,expected,compressed):
    r=decode_img(img(fmt,raw,compressed),0)
    assert (r.width,r.height)==(2,2) and r.rgba==b'\0'*12+expected
    assert decode_png(r.png())==r


def test_links_palette_and_reject_cycles():
    assert decode_img(img(link=True),1)==decode_img(img(),0)
    r=decode_img(img(raw=b'\x01',compressed=True,version=4,palette=b'\0'*4+b'\x12\x34\x56\xff'),0)
    assert r.rgba[-4:]==b'\x12\x34\x56\xff'
    data=b'Neople Img File'.ljust(16,b'\0')+struct.pack('<4i',8,0,2,1)+struct.pack('<2i',17,0)
    with pytest.raises(AssetFormatError,match='Cyclic'):decode_img(data,0)
    with pytest.raises(AssetFormatError,match='Palette'):decode_img(img(raw=b'\x02',compressed=True,version=4,palette=b'\0'*4),0)


@pytest.mark.parametrize('data,index',[(b'',0),(img()[:-1],0),(img(),-1),(img(),True),(img(version=5),0),(img(fmt=20),0)])
def test_reject_bad_img(data,index):
    with pytest.raises(AssetFormatError):decode_img(data,index)


def test_reject_bombs_trailing_deflate_and_bad_png():
    for data,n in [(zlib.compress(b'x'*100000),4),(zlib.compress(b'ab')+b'trailing',2),(b'not zlib',1)]:
        with pytest.raises(AssetFormatError):inflate(data,n)
    png=Raster(1,1,b'\0'*4).png()
    for data in [png[:-1],png+b'extra',png[:40]+b'X'+png[41:]]:
        with pytest.raises(AssetFormatError):decode_png(data)
    with pytest.raises(AssetFormatError):Raster(513,1,b'')


@pytest.mark.parametrize('method',range(5))
def test_png_all_filters_rgb_and_ancillary_stripping(method):
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',binascii.crc32(k+v)&0xffffffff)
    encoded=[([10,20,30,40,50,60],[70,80,90,100,110,120]),
             ([10,20,30,30,30,30],[70,80,90,30,30,30]),
             ([10,20,30,40,50,60],[60,60,60,60,60,60]),
             ([10,20,30,35,40,45],[65,70,75,45,45,45]),
             ([10,20,30,30,30,30],[60,60,60,30,30,30])][method]
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'tEXt',b'private metadata')+chunk(b'IDAT',zlib.compress(bytes([method,*encoded[0],method,*encoded[1]])))+chunk(b'IEND',b'')
    r=decode_png(png);assert r.rgba==bytes([10,20,30,255,40,50,60,255,70,80,90,255,100,110,120,255]);assert b'private metadata' not in r.png()


def test_npk_names_bounds_duplicates(tmp_path):
    p=npk(tmp_path/'fixture.npk',[('Sprite\\Item/Test.img',img())]);n=Npk(p)
    assert decode_img(n.read('sprite/item/test.img'),0).width==2
    for name in ['../bad.img','a/../b','/a//b','a/./b']:
        with pytest.raises(AssetFormatError):normalized(name)
    npk(p,[('a.img',img()),('A.img',img())])
    with pytest.raises(AssetFormatError,match='duplicate'):Npk(p)
    npk(p,[('a.img',img())]);data=bytearray(p.read_bytes());struct.pack_into('<I',data,20,1);p.write_bytes(data)
    with pytest.raises(AssetFormatError,match='outside'):Npk(p)


def test_runtime_readonly_metadata_version_and_missing(tmp_path):
    root,digest,png=pack(tmp_path);s=Settings(assets_dir=str(root),pvf_sha256='a'*64,status_file=str(tmp_path/'status'))
    a=GameAssets(s);rows=[{'id':990001},{'id':123}];a.decorate('a'*64,rows)
    assert rows[0]['image']['state']=='ready' and rows[1]['image']['state']=='missing'
    assert a.png('a'*64,digest)==png and a.portrait('a'*64,0,2,1)['state']=='ready'
    assert a.portrait('a'*64,1,2,1)['state']=='missing'
    assert a.status('b'*64)['state']=='mismatch'
    Path(s.status_file).write_text(json.dumps({'collected_at':time.time(),'pvf_sha256':'b'*64}))
    assert a.status('a'*64)['state']=='mismatch'
    with pytest.raises(HTTPException):a.png('a'*64,digest)
    s.assets_dir='';assert a.status('a'*64)['state']=='not_installed'


@pytest.mark.parametrize('attack',['corrupt','leaf_symlink','directory_symlink','manifest_symlink','unregistered','traversal'])
def test_runtime_no_path_escape_or_unverified_bytes(tmp_path,attack):
    root,digest,_=pack(tmp_path);s=Settings(assets_dir=str(root),pvf_sha256='a'*64);a=GameAssets(s)
    p=root/'images'/(digest+'.png')
    if attack=='corrupt':p.write_bytes(b'broken')
    if attack=='leaf_symlink':p.rename(tmp_path/'outside');p.symlink_to(tmp_path/'outside')
    if attack=='directory_symlink':(root/'images').rename(tmp_path/'outside');(root/'images').symlink_to(tmp_path/'outside',target_is_directory=True)
    if attack=='manifest_symlink':(root/'manifest.sqlite').rename(tmp_path/'outside');(root/'manifest.sqlite').symlink_to(tmp_path/'outside')
    if attack=='unregistered':digest='b'*64
    if attack=='traversal':digest='../../etc/passwd'
    with pytest.raises(HTTPException) as e:a.png('a'*64,digest)
    assert e.value.status_code==404


def test_invalid_dimensions_never_advertised_ready(tmp_path):
    root,_,_=pack(tmp_path)
    with sqlite3.connect(root/'manifest.sqlite') as c:c.execute('UPDATE files SET width=0')
    items=[{'id':990001}];GameAssets(Settings(assets_dir=str(root),pvf_sha256='a'*64)).decorate('a'*64,items)
    assert items[0]['image']['state']=='unavailable' and items[0]['image']['url'] is None


def builder_setup(tmp_path,monkeypatch):
    pvf=tmp_path/'fixture.pvf';pvf.write_bytes(b'synthetic pvf')
    catalog=tmp_path/'catalog.sqlite';sha=hashlib.sha256(pvf.read_bytes()).hexdigest()
    with sqlite3.connect(catalog) as c:
        c.executescript('CREATE TABLE metadata(key TEXT,value TEXT);CREATE TABLE items(id INTEGER,source_path TEXT)')
        c.execute('INSERT INTO metadata VALUES(?,?)',('pvf_sha256',sha));c.executemany('INSERT INTO items VALUES(?,?)',[(1,'first'),(2,'second'),(3,'missing')])
    class Reader:
        def __init__(self,*a):pass
        def fields(self,path):return {'[icon]':['Item/Test.img',0]} if path!='missing' else {}
        def close(self):pass
    monkeypatch.setattr('dnfgm.asset_builder.Reader',Reader)
    return pvf,catalog,sha


def test_builder_deduplicates_and_never_overwrites(tmp_path,monkeypatch):
    pvf,catalog,sha=builder_setup(tmp_path,monkeypatch);npks=tmp_path/'npks';npks.mkdir();npk(npks/'fixture.npk',[('sprite/item/test.img',img())])
    portrait=tmp_path/'portrait.png';portrait.write_bytes(Raster(1,1,b'\x01'*4).png())
    mapping=tmp_path/'portraits.json';mapping.write_text(json.dumps([{'job':0,'png':'portrait.png'}]))
    output=tmp_path/'result';r=build_assets(pvf,catalog,output,npks,mapping)
    assert r['states']=={'ready':2,'missing_reference':1} and r['unique_images']==2 and r['portraits']==1
    assert r['pvf_sha256']==sha and not r['client_verified']
    with pytest.raises(FileExistsError):build_assets(pvf,catalog,output,npks)
    assert len(list((output/'images').glob('*.png')))==2
    with sqlite3.connect(output/'manifest.sqlite') as c:
        assert c.execute('SELECT COUNT(DISTINCT sha256) FROM item_images').fetchone()[0]==1



@pytest.mark.parametrize('fmt', [18,19,20])
def test_builder_decodes_synthetic_dxt_into_deduplicated_private_png(tmp_path,monkeypatch,fmt):
    pvf,catalog,sha=builder_setup(tmp_path,monkeypatch)
    npks=tmp_path/'npks';npks.mkdir()
    block=struct.pack('<HHI',0xf800,0x07e0,0)
    raw=(b'' if fmt==18 else b'\xff'*8)+block
    npk(npks/'synthetic.npk',[('sprite/item/test.img',img(fmt,raw,compressed=True))])
    output=tmp_path/'result';result=build_assets(pvf,catalog,output,npks)
    assert result['states']=={'ready':2,'missing_reference':1}
    assert result['unique_images']==1 and result['pvf_sha256']==sha
    assert result['client_verified'] is False
    pngs=list((output/'images').glob('*.png'));assert len(pngs)==1
    assert decode_png(pngs[0].read_bytes()).rgba==b'\0'*12+b'\xff\0\0\xff'

def test_builder_missing_ambiguous_and_failed_cleanup(tmp_path,monkeypatch):
    pvf,catalog,_=builder_setup(tmp_path,monkeypatch)
    assert build_assets(pvf,catalog,tmp_path/'missing')['states']=={'missing':2,'missing_reference':1}
    npks=tmp_path/'npks';npks.mkdir()
    for name in ['one','two']:npk(npks/(name+'.npk'),[('item/test.img',img())])
    assert build_assets(pvf,catalog,tmp_path/'ambiguous',npks)['states']=={'ambiguous':2,'missing_reference':1}
    mapping=tmp_path/'portraits.json';mapping.write_text('[{"job":0,"png":"missing.png"}]')
    with pytest.raises(FileNotFoundError):build_assets(pvf,catalog,tmp_path/'failed',portraits=mapping)
    assert not (tmp_path/'failed').exists()
    pvf.write_bytes(b'changed')
    with pytest.raises(ValueError,match='fingerprint'):build_assets(pvf,catalog,tmp_path/'wrong')
    assert not (tmp_path/'wrong').exists()


def test_runtime_imports_no_offline_decoder():
    import subprocess,sys,os
    result=subprocess.run([sys.executable,'-c',"import dnfgm.app,sys; assert not ({'dnfgm.npk_assets','dnfgm.asset_builder','dnfgm.pvf'} & set(sys.modules))"],capture_output=True,text=True,env={**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[1]/"src")})
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('value',[123,None,'relative/path'])
def test_asset_configuration_rejects_invalid_path(value):
    with pytest.raises(ValueError,match='Assets directory'):
        Settings(secret='s'*40,db_password='fixture',assets_dir=value).check()
