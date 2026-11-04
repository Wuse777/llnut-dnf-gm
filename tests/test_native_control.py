"""Synthetic transport tests. No production control packets are sent."""
import json
import struct
import time

import pytest

from dnfgm.config import Settings
from dnfgm.native_monitor import NativeMonitor, MONITOR_SHA256
from dnfgm.native_control import NativeControlTransport, notice_packet, kick_packet


@pytest.fixture
def settings(tmp_path):
    s = Settings(db_password='fixture', secret='x'*64, image_digest='fixture',
                 native_monitor_enabled=True, native_control_actions=('native-notice', 'native-kick'),
                 write_approvals={'native-notice': True, 'native-kick': True},
                 test_uids=(), status_file=str(tmp_path/'status.json'))
    (tmp_path/'status.json').write_text(json.dumps({'collected_at': time.time(),
        'image_digest': 'fixture', 'native_monitor_sha256': MONITOR_SHA256, 'core_ok': True}))
    return s


class Socket:
    def __init__(self, failure=None):
        self.failure = failure
        self.packets = []
        self.closed = False
    def settimeout(self, timeout):
        self.timeout = timeout
        if self.failure == 'timeout_setup': raise OSError('private-details')
    def connect(self, endpoint):
        self.endpoint = endpoint
        if self.failure == 'connect': raise OSError('private-details')
    def send(self, packet):
        self.packets.append(packet)
        if self.failure == 'send': raise OSError('private-details')
        if self.failure == 'timeout': raise TimeoutError('private-details')
        if self.failure == 'partial': return len(packet)-1
        return len(packet)
    def recv(self, n):
        pytest.fail('Control transport must not invent an acknowledgement protocol')
    def close(self):
        self.closed = True
        if self.failure == 'close': raise OSError('private-details')


def adapter(settings, sock):
    return NativeControlTransport(NativeMonitor(settings, lambda *args: sock))


def test_notice_layout_and_utf8_byte_length():
    b = notice_packet('维护公告')
    assert len(b) == 266
    assert struct.unpack('<HHHIB', b[:11]) == (2528, 266, 0, 0, 12)
    assert b[11:23] == '维护公告'.encode()
    assert b[23:] == b'\0' * 243
    b = notice_packet('a'*254)
    assert b[10] == 254 and b[-1] == 0
    assert notice_packet('中'*84)[10] == 252


@pytest.mark.parametrize('text', ['', '   ', '\n', 'a\0b', 'a\nb', 'a\tb',
    '\x7f', '\u202ehi', '\ud800', 'a'*255, '中'*85, None, 1, b'hi'])
def test_invalid_notice(text):
    with pytest.raises(ValueError): notice_packet(text)


def test_kick_account_only_layout():
    assert struct.unpack('<HHHIII', kick_packet(900001)) == (1217, 18, 0, 0, 900001, 0)
    assert struct.unpack('<HHHIII', kick_packet(2**32-1))[-2] == 2**32-1


@pytest.mark.parametrize('uid', [0, -1, True, 1.5, '1', None, 2**32])
def test_invalid_uid(uid):
    with pytest.raises(ValueError): kick_packet(uid)


@pytest.mark.parametrize('action', ['notice', 'kick'])
def test_single_send_never_claims_effect(settings, action):
    sock = Socket(); control = adapter(settings, sock)
    r = getattr(control, action)('公告' if action == 'notice' else 900001)
    assert r == {'transport_status': 'sent', 'effect_status': 'unknown',
                 'reason_code': 'no_application_ack', 'automatic_retry_allowed': False}
    assert len(sock.packets) == 1 and sock.closed
    assert sock.endpoint == ('127.0.0.1', 30303) and sock.timeout == .75


@pytest.mark.parametrize('failure,status,count', [
    ('timeout_setup','not_sent',0), ('connect','not_sent',0),
    ('send','uncertain',1), ('timeout','uncertain',1), ('partial','uncertain',1),
    ('close','sent',1)])
def test_fault_boundary_and_no_retry(settings, failure, status, count):
    sock = Socket(failure); control = adapter(settings, sock)
    r = control.kick(900001)
    assert r['transport_status'] == status and r['effect_status'] == 'unknown'
    assert not r['automatic_retry_allowed'] and 'private-details' not in json.dumps(r)
    assert len(sock.packets) == count and sock.closed
    # Failure must not permanently acquire the shared semaphore.
    sock.failure = None
    assert control.kick(900001)['transport_status'] == 'sent'


def test_socket_creation_error_is_not_sent(settings):
    def fail(*args): raise OSError('secret')
    control = NativeControlTransport(NativeMonitor(settings, fail))
    assert control.kick(1)['transport_status'] == 'not_sent'
    assert control.monitor.slot.acquire(False)
    control.monitor.slot.release()


@pytest.mark.parametrize('change,code', [
    ({'native_control_actions': ()}, 'disabled'),
    ({'write_approvals': {}}, 'disabled'),
    ({'native_monitor_enabled': False}, 'disabled'),
    ({'db_host': '8.8.8.8'}, 'invalid_endpoint'),
    ({'db_host': 'localhost'}, 'invalid_endpoint'),
    ({'image_digest': 'wrong'}, 'image_mismatch'),
    ({'test_uids': (-1,)}, 'test_target_only')])
def test_activation_guards_do_not_open_socket(settings, change, code):
    for k, v in change.items(): setattr(settings, k, v)
    control = NativeControlTransport(NativeMonitor(settings, lambda *a: pytest.fail('network')))
    r = control.kick(900001)
    assert r['reason_code'] == code and r['transport_status'] == 'not_sent'


def test_no_broadcast_to_test_scope(settings):
    settings.test_uids = (900001,)
    sock = Socket(); control = adapter(settings, sock)
    assert control.notice('测试')['reason_code'] == 'broadcast_test_scope'
    assert not sock.packets
    assert control.kick(900001)['transport_status'] == 'sent'


@pytest.mark.parametrize('change,code', [
    ({'collected_at': 0}, 'stale_snapshot'),
    ({'native_monitor_sha256': 'wrong'}, 'protocol_unverified'),
    ({'core_ok': False}, 'core_unhealthy')])
def test_snapshot_guards(settings, change, code):
    from pathlib import Path
    path = Path(settings.status_file)
    data = json.loads(path.read_text()); data.update(change); path.write_text(json.dumps(data))
    sock = Socket(); r = adapter(settings, sock).kick(900001)
    assert r['reason_code'] == code and not sock.packets


def test_shared_read_write_semaphore(settings):
    sock = Socket(); control = adapter(settings, sock)
    assert control.monitor.slot.acquire(False)
    try:
        assert control.kick(1)['reason_code'] == 'busy'
        assert control.monitor.query(1)['reason_code'] == 'busy'
        assert not sock.packets
    finally: control.monitor.slot.release()
    assert control.kick(1)['transport_status'] == 'sent'


def test_recheck_after_slot_claim(settings):
    sock = Socket(); control = adapter(settings, sock)
    calls = []
    def unavailable(*args):
        calls.append(1)
        return None if len(calls) == 1 else 'stale_snapshot'
    control.unavailable_reason = unavailable
    assert control.kick(1)['reason_code'] == 'stale_snapshot'
    assert not sock.packets
    assert control.monitor.slot.acquire(False)
    control.monitor.slot.release()


@pytest.mark.parametrize('actions', ['native-kick', ['raw'], ['native-kick']*2, [None], [{}], None])
def test_config_rejects_untyped_or_duplicate_actions(settings, actions):
    settings.native_control_actions = actions
    with pytest.raises(ValueError): settings.check()


def test_config_requires_explicit_activation(settings):
    assert settings.check() is settings
    settings.write_approvals['native-kick'] = 1
    with pytest.raises(ValueError): settings.check()
    settings.write_approvals['native-kick'] = True
    settings.native_monitor_enabled = False
    with pytest.raises(ValueError): settings.check()


def test_default_disabled():
    assert Settings().native_control_actions == ()


def test_real_loopback_datagram_without_ack(settings, monkeypatch):
    import socket
    import dnfgm.native_control as module
    # Only the synthetic receiver chooses an ephemeral loopback port. Production
    # destination remains the fixed private monitor port; never connect to a game.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(('127.0.0.1', 0))
        receiver.settimeout(1)
        monkeypatch.setattr(module, 'MONITOR_PORT', receiver.getsockname()[1])
        control = NativeControlTransport(NativeMonitor(settings))
        r = control.notice('本地合成测试')
        assert r['transport_status'] == 'sent' and r['effect_status'] == 'unknown'
        data, peer = receiver.recvfrom(1024)
        assert data == notice_packet('本地合成测试') and peer[0] == '127.0.0.1'


def test_unknown_action_cannot_be_activated(settings):
    settings.native_control_actions = ('raw',)
    settings.write_approvals['raw'] = True
    sock = Socket(); control = adapter(settings, sock)
    assert control.unavailable_reason('raw') == 'unsupported_action'
    assert not sock.packets
