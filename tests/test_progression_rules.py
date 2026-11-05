"""Only pure synthetic growth fixtures; no real PVF/game data in the repo."""
import struct
import pytest
from dnfgm.progression_rules import TAGS,STATS,RESISTS,scaled,growth_profiles,baseline,sp_table,point_change,level_plan


def tokens():
    result=[]
    for tag,value in [('[initial value]',100),('[growtype 1]',1),('[growtype 2]',2),('[awakening 1]',3)]:
        result.append((5,tag))
        for name in TAGS:result.extend([(5,name),(4,value)])
    return result


def test_growth_sections_scaling_and_threshold_crossings():
    rows=growth_profiles(tokens())
    assert len(rows)==4 and rows[(1,1)]['maxHP']==30
    assert scaled(1.25)==13 and scaled(-1.25)==-13
    assert baseline(rows,15,1,1)['maxHP']==1000+14*10
    assert baseline(rows,50,1,1)['maxHP']==1000+14*10+35*20
    assert baseline(rows,51,1,1)['maxHP']==1000+14*10+35*20+30
    with pytest.raises(ValueError):growth_profiles(tokens()[:-1])
    with pytest.raises(ValueError):growth_profiles(tokens()+[(5,'[HP MAX]'),(4,4)])


def test_native_admin_point_formula_and_same_level_preservation():
    points={'remain_sp':100,'remain_sp_2nd':200,'remain_sfp_1st':7,'remain_sfp_2nd':8}
    table=sp_table([v for level in range(1,201) for v in (level,30 if level<=10 else 60)])
    after=point_change(points,1,15,table)
    assert after['remain_sp']==940  # native endpoint-rate * delta, not normal upgrade sum
    assert after['remain_sfp_1st']==0
    assert point_change(points,50,51,table)['remain_sfp_1st']==2
    assert point_change(points,51,52,table)['remain_sfp_1st']==8
    assert point_change(points,94,96,table)['remain_sp']==100  # native GetSpAtLevelUp >95 -> 0
    info={**baseline(growth_profiles(tokens()),50,1,1),'lev':50,'exp':4900,'grow_type':17,
          'element_resist':struct.pack('<4h',1840,1840,1840,1840).hex()}
    info={k:v for k,v in info.items() if k not in RESISTS}
    info['phy_attack']+=123  # preserve a non-level bonus
    new,updated=level_plan(info,points,51,5000,growth_profiles(tokens()),{n:(n-1)*100 for n in range(2,101)},table)
    assert new['phy_attack']==info['phy_attack']+30 and updated['remain_sfp_1st']==2
    assert struct.unpack('<4h',bytes.fromhex(new['element_resist']))==(1870,)*4
    same,same_points=level_plan(info,points,50,4999,growth_profiles(tokens()),{50:4900,51:5000},table)
    assert same['exp']==4999 and same_points==points and same['phy_attack']==info['phy_attack']


def test_archive_bounds_unsigned_experience_and_unknown_rules():
    rows=growth_profiles(tokens());info={k:100 for k in STATS}
    info.update(lev=2,exp=100,grow_type=17,element_resist='0000000000000000')
    points={k:0 for k in ('remain_sp','remain_sp_2nd','remain_sfp_1st','remain_sfp_2nd')}
    out,_=level_plan(info,points,2,0x80000000,rows,{2:0x80000000,3:0x800000ff},{3:60})
    assert out['exp']==-2147483648
    for change in ({'grow_type':7},{'element_resist':'00'},{'maxHP':65535}):
        with pytest.raises(ValueError):level_plan({**info,**change},points,3,200,rows,{2:100,3:200,4:300},{3:60})
    with pytest.raises(ValueError):level_plan(info,points,3,201,rows,{2:100,3:200},{3:60})
