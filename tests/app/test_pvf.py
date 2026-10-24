import struct
import pytest
from dnfgm.pvf import decode_words,Reader

def test_pvf_rotation_known_roundtrip():
    plain=[0,1,0xffffffff,0x12345678];crc=0x98765432
    encoded=b''.join(struct.pack('<I',(((x<<6)|(x>>26))&0xffffffff)^crc^0x81a79011) for x in plain)
    assert decode_words(encoded,crc)==struct.pack('<4I',*plain)

def test_pvf_rejects_unaligned_blocks():
    with pytest.raises(ValueError):decode_words(b'bad',0)

def test_string_bounds():
    r=object.__new__(Reader);r.string_count=1;r.strings=b'\0'*8;r.encoding='gbk'
    with pytest.raises(ValueError):r.string(1)
