import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest
from dnfgm_m0.gateway import Gateway

class Response:
    status=200
    def __init__(self,text):
        nonce=b'\x01'*12
        self.data=base64.b64encode(nonce+AESGCM(b'\0'*32).encrypt(nonce,text.encode(),None))
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return self.data[:n]

class Opener:
    def __init__(self,text):self.text=text
    def open(self,request,timeout):return Response(self.text)

@pytest.mark.parametrize('command,text,accepted',[
 ('regedit','success',True),('regedit','already registered',False),
 ('login','0|sensitive-game-token',True),('login','account banned',False),
])
def test_protocol_success_and_secret_redaction(command,text,accepted):
    gate=Gateway('https://example.invalid/dnf','00'*32);gate.opener=Opener(text)
    result=gate.request(command,'gmtest_fixture','synthetic-password')
    assert result=={'accepted':accepted,'http_status':200}
    assert 'sensitive-game-token' not in str(result)

def test_plain_http_refused():
    with pytest.raises(ValueError):Gateway('http://example.invalid','00'*32)

def test_unsupported_protocol_action_refused():
    gate=Gateway('https://example.invalid','00'*32)
    with pytest.raises(ValueError):gate.request('repasswd','fixture','password')
