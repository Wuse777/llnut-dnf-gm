import ipaddress
import json
import socket
import struct
import time
from types import SimpleNamespace

import pytest
from dnfgm.config import Settings
from dnfgm.native_monitor import (NativeMonitor, MONITOR_SHA256, MONITOR_PORT,
    QUERY, query_packet, decode_reply, private_ipv4)


@pytest.fixture
def settings(tmp_path):
    s=Settings(db_password='fixture',secret='x'*64,native_monitor_enabled=True,
               image_digest='fixture-image',status_file=str(tmp_path/'status.json'))
    write_status(s)
    return s


def write_status(s, **changes):
    from pathlib import Path
    data={'collected_at':time.time(),'image_digest':s.image_digest,
          'core_ok':True,'native_monitor_sha256':MONITOR_SHA256}
    data.update(changes)
    Path(s.status_file).write_text(json.dumps(data))


class FakeSocket:
    def __init__(self, state=1, error=None, transform=lambda b:b):
        self.state,self.error,self.transform=state,error,transform
        self.sent=[];self.closed=False
    def settimeout(self,n):self.timeout=n
    def connect(self,endpoint):self.endpoint=endpoint
    def getsockname(self):return '127.0.0.1',45678
    def send(self,packet):self.sent.append(packet);return len(packet)
    def recv(self,n):
        if self.error:raise self.error
        op,size,_,_,uid,nonce,_=QUERY.unpack(self.sent[-1])
        return self.transform(QUERY.pack(op,size,45678,int(ipaddress.IPv4Address('127.0.0.1')),uid,nonce,self.state))
    def close(self):self.closed=True


@pytest.mark.parametrize('address', ['127.0.0.1','10.0.0.2','172.18.0.2','192.168.1.2'])
def test_explicit_private_ipv4(address):assert private_ipv4(address)


@pytest.mark.parametrize('address', ['localhost','example.com','8.8.8.8','0.0.0.0','169.254.169.254','100.64.0.2','::1','224.0.0.1',2130706433,None,'127.1','127.0.0.1:30303'])
def test_no_dns_metadata_or_public_targets(address):assert not private_ipv4(address)


def test_exact_fixed_protocol_layout():
    packet=query_packet(900001,12345)
    assert len(packet)==19
    assert struct.unpack('<HHHIIIB',packet)==(2000,19,0,0,900001,12345,0)
    assert packet[:4]==b'\xd0\x07\x13\x00'


@pytest.mark.parametrize('uid', [0,-1,2**32,True,1.5,'1',None])
def test_invalid_uid_never_contacts_network(settings,uid):
    n=NativeMonitor(settings,lambda *a:pytest.fail('network must not run'))
    with pytest.raises(ValueError):n.query(uid)


@pytest.mark.parametrize('nonce', [-1,2**32,True,1.2,'0'])
def test_invalid_nonce(nonce):
    with pytest.raises(ValueError):query_packet(1,nonce)


@pytest.mark.parametrize('state', [0,1])
def test_valid_read_has_no_retry_and_closes_socket(settings,state):
    sock=FakeSocket(state)
    n=NativeMonitor(settings,lambda *args:sock)
    r=n.query(900001)
    assert r['state']==('online' if state else 'offline')
    assert r['observed_at']>=r['queried_at']
    assert sock.endpoint==('127.0.0.1',MONITOR_PORT) and sock.timeout==.75
    assert len(sock.sent)==1 and sock.closed


@pytest.mark.parametrize('error,code', [(TimeoutError(),'timeout'),(OSError('secret-host'),'invalid_or_unreachable')])
def test_failure_is_unknown_not_logout(settings,error,code):
    sock=FakeSocket(error=error);n=NativeMonitor(settings,lambda *a:sock)
    r=n.query(1)
    assert (r['state'],r['observed_at'],r['reason_code'])==('unknown',None,code)
    assert 'secret-host' not in json.dumps(r) and len(sock.sent)==1 and sock.closed
    sock.error=None
    assert n.query(1)['state']=='online' # semaphore released on error


@pytest.mark.parametrize('offset,value', [(0,2001),(1,18),(2,1),(3,0),(4,2),(5,10),(6,2)])
def test_reply_fields_must_match_request(offset,value):
    fields=[2000,19,45678,int(ipaddress.IPv4Address('127.0.0.1')),1,9,1]
    fields[offset]=value
    with pytest.raises(ValueError):decode_reply(QUERY.pack(*fields),1,9,45678,'127.0.0.1')


@pytest.mark.parametrize('transform', [lambda b:b[:-1],lambda b:b+b'\0',lambda b:b[:18]+b'\xff'])
def test_bad_reply_is_unknown(settings,transform):
    n=NativeMonitor(settings,lambda *a:FakeSocket(transform=transform))
    assert n.query(1)['state']=='unknown'


@pytest.mark.parametrize('change,code', [({'collected_at':0},'stale_snapshot'),
    ({'collected_at':time.time()+1000},'stale_snapshot'),({'image_digest':'different'},'image_mismatch'),
    ({'native_monitor_sha256':None},'protocol_unverified'),({'core_ok':False},'core_unhealthy')])
def test_snapshot_gates_without_network(settings,change,code):
    write_status(settings,**change)
    n=NativeMonitor(settings,lambda *a:pytest.fail('unverified transport'))
    assert n.query(1)['reason_code']==code


def test_disabled_invalid_address_busy(settings):
    n=NativeMonitor(settings,lambda *a:pytest.fail('must not send'))
    settings.native_monitor_enabled=False
    assert n.query(1)['reason_code']=='disabled'
    settings.native_monitor_enabled=True;settings.db_host='example.com'
    assert n.query(1)['reason_code']=='invalid_endpoint'
    settings.db_host='127.0.0.1';assert n.slot.acquire(blocking=False)
    assert n.query(1)['reason_code']=='busy'
    n.slot.release()


def test_configuration_is_explicit():
    s=Settings(db_password='fixture',secret='s'*64)
    assert not s.check().native_monitor_enabled
    s.native_monitor_enabled='yes'
    with pytest.raises(ValueError):s.check()
    s.native_monitor_enabled=True
    with pytest.raises(ValueError):s.check()
    s.image_digest='fixture';s.db_host='example.com'
    with pytest.raises(ValueError):s.check()
    s.db_host='172.18.0.2';assert s.check() is s


def test_real_loopback_udp_roundtrip(settings, monkeypatch):
    # Only a synthetic loopback server, never a game daemon.
    import threading
    import dnfgm.native_monitor as native
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
        server.bind(('127.0.0.1',0));server.settimeout(2)
        monkeypatch.setattr(native,'MONITOR_PORT',server.getsockname()[1])
        errors=[]
        def respond():
            try:
                packet,peer=server.recvfrom(64)
                op,size,_,_,uid,nonce,_=QUERY.unpack(packet)
                assert (op,size,uid)==(2000,19,900001)
                server.sendto(QUERY.pack(op,size,peer[1],int(ipaddress.IPv4Address(peer[0])),uid,nonce,1),peer)
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=respond);thread.start()
        try:assert NativeMonitor(settings).query(900001)['state']=='online'
        finally:thread.join(3)
        assert not thread.is_alive() and not errors
