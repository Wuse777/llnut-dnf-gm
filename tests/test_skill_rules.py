import struct
import pytest
from dnfgm import skill_rules as r


def test_codec_is_exact_and_bounded():
    raw=bytes((5,1))+b'\0'*406;blob=r.pack(raw)
    assert r.unpack(blob)==raw
    for invalid in (b'',blob+b'x',struct.pack('<I',409)+blob[4:],r.pack(b'\0\1'+b'\0'*406)):
        with pytest.raises(ValueError):r.unpack(invalid)


def test_repeated_profiles_order_and_native_gift_removal():
    t=[(5,'[skill]'),(2,5),(2,1),(5,'[/skill]'),(5,'[growtype 3]'),(5,'[skill]'),(2,5),(2,0),(2,6),(2,1),(5,'[/skill]'),(5,'[awakening 1]'),(5,'[awakening skill]'),(2,7),(2,1),(5,'[/awakening skill]'),(5,'[growtype 2]')]
    p={'job':0,'defaults':r.profiles(t),'definitions':{str(k):{'name':str(k),'group':1,'active':True} for k in (5,6,7)}}
    raw,skipped=r.rebuild(p,2|(1<<4))
    assert [(v['skill_id'],v['level']) for v in r.learned(raw,p['definitions'])]==[(6,1),(7,1)] and not skipped
    p['job']=9;raw,_=r.rebuild(p,2|(1<<4))
    assert all(v['slot']>=54 for v in r.learned(raw,p['definitions']))


def test_reset_totals_and_expert_boundary_rules():
    sp={n:n for n in range(1,201)}
    assert r.reset_points(100,sp)=={'sp':sum(range(1,96)),'tp':51}
    rules={'experts':{'1':{'skills':[[191,1]],'thresholds':[224,449,674]}},'level_limits':{'2':20}}
    assert r.expert_skills(1,224,19,rules)['level']==1
    assert r.expert_skills(1,224,20,rules)['level']==2
    assert r.expert_skills(0,-1,1,rules) is None


def test_native_display_class_maps_to_storage_group():
    assert r.native_group(0,False,3)==0
    assert r.native_group(0,False,2)==1
    assert r.native_group(4,False,0)==2
    assert r.native_group(0,True,0)==3
    assert r.native_group(7,False,0) is None
