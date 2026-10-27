import struct
import zlib
import pytest
from dnfgm.equipment_unlock import decode, expire, WAIT_SECONDS

NOW = 1792890000

def blob(rows=((1,NOW-100,2),(2,NOW-200,2),(3,NOW-300,1))):
    raw=bytearray(800)
    for key,stamp,state in rows:
        struct.pack_into('<IB',raw,(key-1)*8,stamp,state)
    return struct.pack('<I',800)+zlib.compress(raw)

def test_only_selected_pending_timestamp_changes():
    original=blob();updated,selected=expire(original,[2],NOW)
    before,_=decode(original);after,records=decode(updated)
    assert before[:8]==after[:8] and before[12:]==after[12:]
    assert records[1]['requested_at']==NOW-WAIT_SECONDS-1
    assert selected[0]['lock_key']==2

@pytest.mark.parametrize('keys', [[],[0],[101],[1,1],[True],[3],[4]])
def test_bad_selection(keys):
    with pytest.raises(ValueError):expire(blob(),keys,NOW)

@pytest.mark.parametrize('bad',[b'',struct.pack('<I',799)+zlib.compress(bytes(800)),blob()+b'extra',blob()[:-1],struct.pack('<I',800)+zlib.compress(bytes(801)),struct.pack('<I',800)+zlib.compress(bytes(100000))])
def test_bad_stream(bad):
    with pytest.raises(ValueError):decode(bad)

@pytest.mark.parametrize('offset,value',[(4,3),(5,1),(6,1),(7,1)])
def test_unknown_state_or_padding(offset,value):
    raw=bytearray(800);raw[offset]=value
    with pytest.raises(ValueError):decode(struct.pack('<I',800)+zlib.compress(raw))

def test_already_expired_not_reprocessed():
    with pytest.raises(ValueError):expire(blob(((1,NOW-WAIT_SECONDS,2),)),[1],NOW)
