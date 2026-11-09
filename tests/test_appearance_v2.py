"""Synthetic identity, timeline and allocation checks; no client assets."""
import json
import sqlite3
import struct

import pytest

from dnfgm.character_assets import AnimationFrame,parse_ani
from dnfgm.character_outfit import validate_appearance_rows,resolve_saved_appearance
from dnfgm.outfit_recipe import canonical_appearance_recipe
from dnfgm.appearance_manifest import assemble,merge_clips,validate_clip
from dnfgm.appearance_assets import color_map,compile_component,timeline,SCHEMA
from dnfgm.npk_assets import AssetFormatError,Raster


def avatar(slot,item,identity,clear=0,**values):
    return dict(slot=slot,it_id=item,ui_id=identity,clear_avatar_id=clear,color1=0,color2=0,**values)


def labels():
    return {'state':'ok','items':{11:{'part_code':'[coat avatar]'},12:{'part_code':'[coat avatar]'},
            13:{'part_code':'[hair avatar]'},14:{'part_code':'[aurora avatar]'}}}


def test_clear_reference_is_valid_same_snapshot_bag_identity_and_never_pvf_id():
    snapshot=validate_appearance_rows([avatar(0,11,100,200),avatar(10,12,200)])
    saved=resolve_saved_appearance(snapshot,0,0,labels())
    assert saved['state']=='ok' and saved['clear_applied'] is True
    assert saved['recipe']['items']==[{'slot':'[coat avatar]','id':12,'color1':0,'color2':0}]
    assert 'ui_id' not in json.dumps(saved) and '200' not in json.dumps(saved)
    assert validate_appearance_rows([avatar(0,11,100,12)])['reason_codes']==['clear_reference_missing']
    assert validate_appearance_rows([avatar(0,11,100,200),avatar(1,12,200)])['reason_codes']==['clear_reference_missing']


def test_clear_duplicate_nested_wrong_part_and_dye_are_explicitly_refused():
    assert validate_appearance_rows([avatar(0,11,100),avatar(10,12,100)])['state']=='unsupported'
    assert validate_appearance_rows([avatar(0,11,100,200),avatar(10,12,200,300)])['reason_codes']==['clear_reference_nested']
    snapshot=validate_appearance_rows([avatar(0,11,100,200),avatar(10,13,200)])
    assert resolve_saved_appearance(snapshot,0,0,labels())['reason_codes']==['avatar_part_unverified']
    row=avatar(0,11,100);row['color1']=1
    dyed=resolve_saved_appearance(validate_appearance_rows([row]),0,0,labels())
    assert dyed['state']=='unsupported' and dyed['reason_codes']==['dye_pixel_rule_unverified']


def test_known_aura_is_preserved_in_identity_and_does_not_replace_other_parts():
    saved=resolve_saved_appearance(validate_appearance_rows([avatar(0,11,100),avatar(9,14,101)]),0,0,labels())
    assert saved['state']=='ok' and saved['recipe']['aura_id']==14
    assert len(saved['recipe']['items'])==1


def test_v2_preserves_modifiers_and_is_separate_from_instance_identity():
    items=[{'slot':'[coat avatar]','id':11}]
    recipe,sha=canonical_appearance_recipe(0,-128,items)
    assert recipe['version']==2 and recipe['grow_type']==0
    assert canonical_appearance_recipe(0,0,items)[1]==sha
    assert canonical_appearance_recipe(0,0,[{**items[0],'color1':1}])[1]!=sha
    assert canonical_appearance_recipe(0,0,items,42)[1]!=sha
    assert canonical_appearance_recipe(0,0,items,0,14)[1]!=sha


def test_ani_retains_exact_delays_loop_and_empty_frame_time():
    path=b'character/example/skin/body%04d.img'
    raw=struct.pack('<HHI',2,1,len(path))+path+struct.pack('<HHB',1,0,1)
    for index,delay in ((0,70),(-1,130)):
        raw+=struct.pack('<Hh',0,index)
        if index>=0:raw+=struct.pack('<h',2)
        raw+=struct.pack('<iiHHi',-10,-20,1,12,delay)
    frames=parse_ani(raw)
    assert [f.duration_ms for f in frames]==[70,130]
    assert frames[0].loop and frames[1].image==''
    assert timeline(frames)==(200,True)


def clip(durations,draws=None):
    return {'loop':True,'duration_ms':sum(durations),'frames':[{'duration_ms':v,'draws':draws or []} for v in durations]}


def test_merges_layer_timeline_boundaries_without_body_frame_assumptions():
    body=clip([60,40]);coat=clip([25,75])
    assert [f['duration_ms'] for f in merge_clips([body,coat])['frames']]==[25,35,40]
    with pytest.raises(ValueError):merge_clips([body,clip([90])])


def test_manifest_refuses_unregistered_atlas_crops_and_oversized_draws():
    sha='a'*64;pages={sha:{'width':1024,'height':512}}
    draw={'atlas':sha,'sx':0,'sy':0,'width':10,'height':20,'x':0,'y':-20,'z':1000}
    assert validate_clip(clip([100],[draw]),pages)
    for changes in ({'atlas':'b'*64},{'sx':1020},{'width':513},{'x':250},{'y':60}):
        with pytest.raises(ValueError):validate_clip(clip([100],[{**draw,**changes}]),pages)


def test_color_table_is_lookup_evidence_not_a_guessed_pixel_algorithm():
    tokens=[(5,'[avatar color map]'),(2,1),(2,252),(2,159),(2,172),(7,'sample'),(5,'[/avatar color map]')]
    assert color_map(tokens)==[(1,252,159,172,'sample')]
    with pytest.raises(AssetFormatError):color_map(tokens[:-2])


def test_worn_part_missing_never_uses_a_default_component():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE metadata(key TEXT,value TEXT)');c.execute("INSERT INTO metadata VALUES('appearance_version','2')")
    c.executescript(SCHEMA)
    from dnfgm.outfit_recipe import AVATAR_SLOTS
    for action in ('idle','walk','attack'):
        for slot in AVATAR_SLOTS:c.execute('INSERT INTO appearance_parts VALUES(?,?,?,?,?,?,?)',(0,slot,0,action,'ready',json.dumps(clip([100])),''))
    recipe,sha=canonical_appearance_recipe(0,0,[{'slot':'[coat avatar]','id':11}])
    result=assemble(c,'a'*64,{'state':'ok','recipe':recipe,'recipe_sha256':sha})
    assert result['state']=='missing' and not result['actions']
    assert any(row.get('reason_code')=='appearance_part_missing' for row in result['coverage'])
    c.close()


def test_special_effect_layer_is_explicitly_omitted_while_actual_base_is_retained(tmp_path,monkeypatch):
    base=AnimationFrame('character/coat%02d%02d.img',0,-1,-2,(),100,True)
    effect=AnimationFrame('character/effect%02d%02d.img',0,-1,-2,((11,2),),100,True)
    class Reader:
        def fields(self,path):return {'[waiting motion]':['%s/stay.ani']}
        def read(self,path):return [effect] if '_f/' in path else [base]
    monkeypatch.setattr('dnfgm.appearance_assets.parse_ani',lambda value:value)
    calls=[]
    def raster(name,frame):
        calls.append(name);return Raster(1,1,b'\xff\xff\xff\xff'),0,0
    clip,pages,omitted=compile_component(Reader(),raster,tmp_path,[base],((1,0),((1000,'coat_a'),(2000,'coat_f')),'layer.lay'),
                                       'equipment/character/test/avatar/coat/item.equ','idle')
    assert omitted==['graphic_effect_unverified'] and len(pages)==1
    assert calls==['character/coat0100.img'] and clip['frames'][0]['draws'][0]['z']==1000
    with pytest.raises(AssetFormatError,match='no supported base layers'):
        compile_component(Reader(),raster,tmp_path,[base],((1,0),((2000,'coat_f'),),'layer.lay'),
                          'equipment/character/test/avatar/coat/item.equ','idle')


def test_partial_base_weapon_is_drawn_and_effect_gap_remains_visible():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE metadata(key TEXT,value TEXT)');c.execute("INSERT INTO metadata VALUES('appearance_version','2')")
    c.executescript(SCHEMA)
    from dnfgm.outfit_recipe import AVATAR_SLOTS
    sha='a'*64;draw={'atlas':sha,'sx':0,'sy':0,'width':1,'height':1,'x':0,'y':0,'z':2000}
    c.execute('INSERT INTO appearance_atlases VALUES(?,?,?,?)',(sha,1,1,70))
    for action in ('idle','walk','attack'):
        for slot in AVATAR_SLOTS:c.execute('INSERT INTO appearance_parts VALUES(?,?,?,?,?,?,?)',(0,slot,0,action,'ready',json.dumps(clip([100])),''))
        c.execute('INSERT INTO appearance_parts VALUES(?,?,?,?,?,?,?)',(0,'[weapon]',42,action,'partial',json.dumps(clip([100],[draw])),'graphic_effect_unverified'))
    recipe,key=canonical_appearance_recipe(0,0,[],42)
    result=assemble(c,'b'*64,{'state':'ok','recipe':recipe,'recipe_sha256':key})
    assert result['actions']['idle']['frames'][0]['draws']==[draw]
    assert 'weapon_effect_unverified' in result['reason_codes'] and result['complete'] is False
    assert 'weapon_rule_unverified' not in result['reason_codes']
    c.close()
