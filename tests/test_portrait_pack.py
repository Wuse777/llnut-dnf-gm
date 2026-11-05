"""Synthetic PNGs only; no downloaded game artwork enters tests or source."""
import json
import sqlite3
import pytest
from dnfgm.portrait_pack import enrich_portraits
from dnfgm.game_assets import GameAssets
from dnfgm.config import Settings
from test_game_assets import pack


def test_attributed_portraits_preserve_items_and_match_signed_growth(tmp_path):
    source,digest,png=pack(tmp_path);before=(source/'manifest.sqlite').read_bytes()
    image=tmp_path/'synthetic.png';image.write_bytes(png)
    mapping=tmp_path/'mapping.json';mapping.write_text(json.dumps([{'job':0,'grow_type':17,'png':image.name,'kind':'official_promotional','label':'合成示例，不是真实素材','page':'https://dnf.qq.com/','focus_x':50,'focus_y':20}]))
    target=tmp_path/'new';result=enrich_portraits(source,mapping,target)
    assert result['portraits']==2 and result['item_images_unchanged'] and (source/'manifest.sqlite').read_bytes()==before
    settings=Settings(assets_dir=str(target),pvf_sha256='a'*64)
    artwork=GameAssets(settings).portrait('a'*64,0,-111,0)
    assert artwork['state']=='ready' and artwork['source_kind']=='official_promotional' and artwork['match_level']=='growth'
    assert '非当前客户端NPK' in artwork['note'] and artwork['focus_y']==20
    assert GameAssets(settings).portrait('a'*64,0,0,0)['match_level']=='base'
    with sqlite3.connect(source/'manifest.sqlite') as a,sqlite3.connect(target/'manifest.sqlite') as b:
        assert a.execute('SELECT * FROM item_images').fetchall()==b.execute('SELECT * FROM item_images').fetchall()
    with pytest.raises(FileExistsError):enrich_portraits(source,mapping,target)


def test_invalid_attribution_rejected_without_output(tmp_path):
    source,_,png=pack(tmp_path);(tmp_path/'synthetic.png').write_bytes(png)
    mapping=tmp_path/'mapping.json';mapping.write_text(json.dumps([{'job':0,'png':'synthetic.png','label':'bad','page':'javascript:alert(1)'}]))
    with pytest.raises(ValueError):enrich_portraits(source,mapping,tmp_path/'new')
    assert not (tmp_path/'new').exists()
