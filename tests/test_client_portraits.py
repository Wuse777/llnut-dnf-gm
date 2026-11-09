"""Synthetic oversized art exercises the offline-only portrait bounds."""
import hashlib
import json
import sqlite3
import struct
import zlib
import pytest

from dnfgm.client_portraits import portrait_frame,compile_portraits
from dnfgm.npk_assets import AssetFormatError,decode_img
from dnfgm.portrait_pack import enrich_portraits
from dnfgm.game_assets import GameAssets
from dnfgm.config import Settings
from test_game_assets import pack


def sheet(w=600,h=1,*,tail=b'',link=False):
    raw=zlib.compress(b'\x10\x20\x30\xff'*(w*h))+tail
    table=struct.pack('<9i',16,6,w,h,len(raw),0,0,w,h)
    if link:table+=struct.pack('<2i',17,0)
    return b'Neople Img File\0'+struct.pack('<4i',len(table),0,2,2 if link else 1)+table+raw


def test_large_art_is_only_supported_by_offline_reader():
    image=portrait_frame(sheet(link=True),1)
    assert (image.width,image.height)==(512,1)
    assert image.rgba==b'\x30\x20\x10\xff'*512
    with pytest.raises(AssetFormatError):decode_img(sheet(),0)
    for data,index in ((sheet(2049),0),(sheet(tail=b'x'),0),(sheet()[:-1],0),(sheet(),True),(sheet(),-1)):
        with pytest.raises(AssetFormatError):portrait_frame(data,index)


def test_portrait_enrichment_preserves_registered_v2_atlases_and_rejects_damage(tmp_path):
    source,_,png=pack(tmp_path);sha=hashlib.sha256(png).hexdigest()
    (source/'atlases').mkdir();(source/'atlases'/(sha+'.png')).write_bytes(png)
    with sqlite3.connect(source/'manifest.sqlite') as c:
        c.execute("INSERT INTO metadata VALUES('appearance_version','2')")
        c.execute('CREATE TABLE appearance_atlases(sha256 TEXT,width INTEGER,height INTEGER,bytes INTEGER)')
        c.execute('CREATE TABLE appearance_parts(state TEXT,payload_json TEXT)')
        c.execute('INSERT INTO appearance_atlases VALUES(?,?,?,?)',(sha,1,1,len(png)))
    (tmp_path/'test.png').write_bytes(png)
    mapping=tmp_path/'mapping.json';mapping.write_text(json.dumps([{'job':0,'grow_type':1,'png':'test.png','kind':'client','label':'合成测试','page':'https://example.org/'}]))
    target=tmp_path/'merged';enrich_portraits(source,mapping,target)
    assert (target/'atlases'/(sha+'.png')).read_bytes()==png
    assets=GameAssets(Settings(assets_dir=str(target),pvf_sha256='a'*64))
    image=assets.portrait('a'*64,0,-111,0)
    assert image['match_level']=='profession' and image['mapped_growth']==1 and image['requested_growth']==17
    assert image['awakening_specific'] is False and '未匹配独立觉醒插画' in image['note']
    assert assets.portrait('a'*64,0,1,0)['match_level']=='growth'
    assert assets.portrait('a'*64,0,18,0)['match_level']=='base'
    (source/'atlases'/(sha+'.png')).write_bytes(b'x'*len(png))
    with pytest.raises(ValueError,match='checksum'):enrich_portraits(source,mapping,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_unbound_evidence_never_creates_output(tmp_path):
    mapping=tmp_path/'map.json';mapping.write_text('{}')
    with pytest.raises(ValueError,match='evidence'):compile_portraits(tmp_path,tmp_path/'missing',tmp_path,mapping,tmp_path/'out')
    assert not (tmp_path/'out').exists()
