import struct
import pytest
from dnfgm import profession_rules as p
from dnfgm.progression_rules import TAGS,STATS
from dnfgm.character_detail import profession


def test_segmented_names_awakening_and_preserved_high_bit():
    tokens=[(5,'[growtype name]'),(7,'基础'),(7,'分支甲'),(7,'分支乙'),(5,'[growtype 2]'),(5,'[awakening name]'),(7,'甲一觉'),(7,'甲二觉'),(5,'[growtype 3]'),(5,'[awakening name]'),(7,'乙一觉')]
    rows=p.choices(tokens,{(-1,0),(0,0),(1,0),(1,1),(1,2),(2,0),(2,1)})
    assert next(x for x in rows['choices'] if x['code']==33)['name']=='甲二觉'
    assert next(x for x in rows['choices'] if x['code']==18)['name']=='乙一觉'
    assert p.encode(-127,2,1)==-110
    jobs={'0':{'grow_names':['基础','分支甲'],'profiles':{'17':'甲一觉'}}}
    assert profession(0,-111,jobs)['name']=='甲一觉'
    assert not profession(0,33,jobs)['grow_name_known']


def test_linked_growth_delta_preserves_bonuses_and_unknown_fields():
    profiles={key:{k:v for k in TAGS.values()} for key,v in [((-1,0),100),((0,0),10),((1,0),20),((2,0),30)]}
    info={k:10000 for k in STATS};info.update(lev=70,job=0,grow_type=-127,exp=33,element_resist=struct.pack('<4h',1,2,3,4).hex(),spec_property_sha256='keep')
    result=p.plan(info,2,0,profiles)
    # Growth steps 15..69 inclusive: 55 steps times a difference of 10.
    assert result['maxHP']==10550 and struct.unpack('<4h',bytes.fromhex(result['element_resist']))==(551,552,553,554)
    assert result['grow_type']==-126 and result['exp']==33 and result['spec_property_sha256']=='keep' and info['maxHP']==10000
    with pytest.raises(ValueError):p.plan(info,1,0,profiles)
    with pytest.raises(ValueError):p.plan(info,3,0,profiles)
