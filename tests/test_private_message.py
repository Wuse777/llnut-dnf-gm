import json
from pathlib import Path
import time

import pytest

from dnfgm.config import Settings
from dnfgm.models import NativePreview
from dnfgm.native_control import NativeControlTransport
from dnfgm.native_monitor import MONITOR_SHA256, NativeMonitor
from dnfgm.private_message import BRIDGE_VERSION, GAME_SHA256, PrivateMessageTransport, message_text, read_frame

OP = 'a' * 32


class Socket:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.sent = []
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, value):
        self.address = value

    def sendall(self, value):
        self.sent.append(value)
        if self.error:
            raise self.error

    def recv(self, size):
        chunk, self.response = self.response[:size], self.response[size:]
        return chunk

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def transport(tmp_path, sock):
    path = tmp_path / 'status.json'
    path.write_text(json.dumps({'collected_at': time.time(), 'image_digest': 'fixture',
        'native_monitor_sha256': MONITOR_SHA256, 'core_ok': True, 'mem_available_mib': 512, 'swap_free_mib': 4096}))
    settings = Settings(native_monitor_enabled=True, native_control_actions=('native-message',),
        write_approvals={'native-message': True}, image_digest='fixture', test_uids=(900001,), status_file=str(path))
    return PrivateMessageTransport(NativeControlTransport(NativeMonitor(settings)), lambda *_: sock)


@pytest.mark.parametrize('text', ['', '   ', 'a\n', '\x00', '\u200b', 'a' * 255, '汉' * 85])
def test_invalid_message_rejected_before_transport(text):
    with pytest.raises(ValueError):
        message_text(text)


def test_model_requires_exact_character_and_rejects_extra_fields():
    value = {'action': 'native-message', 'uid': 900001, 'charac_no': 900001, 'message': '维护提示', 'reason': '测试'}
    assert NativePreview(**value).charac_no == 900001
    for mutation in ({'charac_no': None}, {'uid': None}, {'sender_uid': 1}, {'charac_no': True}, {'message': 'x\n'}):
        with pytest.raises(ValueError):
            NativePreview(**{**value, **mutation})
    with pytest.raises(ValueError):
        NativePreview(**{**value, 'action': 'native-notice', 'uid': None})


def test_send_typed_ack_does_not_claim_client_delivery(tmp_path):
    sock = Socket(json.dumps({'operation_id': OP, 'transport_status': 'sent', 'reason_code': 'primitive_invoked'}).encode() + b'\n')
    adapter = transport(tmp_path, sock)
    result = adapter.send(OP, 900001, 900001, '系统消息')
    assert result['transport_status'] == 'sent' and result['effect_status'] == 'unknown'
    assert not result['automatic_retry_allowed'] and sock.closed
    assert json.loads(sock.sent[0]) == {'action': 'send', 'operation_id': OP, 'uid': 900001, 'charac_no': 900001, 'message': '系统消息'}
    assert adapter.monitor.slot.acquire(False)


@pytest.mark.parametrize('response', [b'', b'{}\n', b'{"ready":true}\n', b'x' * 4097, b'{}\n{}\n'])
def test_malformed_ack_is_uncertain_and_never_retried(tmp_path, response):
    sock = Socket(response)
    result = transport(tmp_path, sock).send(OP, 900001, 900001, '系统消息')
    assert result['transport_status'] == 'uncertain' and len(sock.sent) == 1 and sock.closed


def test_short_send_timeout_never_retried(tmp_path):
    sock = Socket(b'', TimeoutError())
    assert transport(tmp_path, sock).send(OP, 900001, 900001, '系统消息')['transport_status'] == 'uncertain'
    assert len(sock.sent) == 1


def test_shared_slot_scope_and_activation_fail_closed(tmp_path):
    sock = Socket(b'')
    adapter = transport(tmp_path, sock)
    assert adapter.send(OP, 900002, 900002, '消息')['reason_code'] == 'test_target_only'
    adapter.monitor.slot.acquire()
    assert adapter.send(OP, 900001, 900001, '消息')['reason_code'] == 'busy'
    adapter.monitor.slot.release()
    adapter.settings.native_control_actions = ()
    assert adapter.send(OP, 900001, 900001, '消息')['reason_code'] == 'disabled' and not sock.sent


def test_handshake_requires_exact_running_bridge_identity(tmp_path):
    handshake = {'ready': True, 'bridge_version': BRIDGE_VERSION, 'game_sha256': GAME_SHA256}
    adapter = transport(tmp_path, Socket(json.dumps(handshake).encode() + b'\n'))
    assert adapter.status()['ready'] is True
    adapter.socket_factory = lambda *_: Socket(json.dumps({**handshake, 'game_sha256': 'b' * 64}).encode() + b'\n')
    assert adapter.status()['ready'] is False


@pytest.mark.parametrize('value', [0, '512', float('nan'), True])
def test_resource_guard_prevents_readiness_handshake(tmp_path, value):
    sock = Socket(b'')
    adapter = transport(tmp_path, sock)
    path = Path(adapter.settings.status_file)
    data = json.loads(path.read_text()); data['mem_available_mib'] = value
    path.write_text(json.dumps(data))
    status = adapter.status()
    assert status['ready'] is False and status['reason_code'] == 'resource_guard' and not sock.sent


def test_root_relay_durable_claim_prevents_repeat_after_restart(tmp_path, monkeypatch):
    pytest.importorskip('pwd', reason='Linux-only root relay')
    import importlib.util
    spec = importlib.util.spec_from_file_location('private_message_relay', Path(__file__).resolve().parents[1] / 'deploy/private_message_relay.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    script = tmp_path / 'frida.js'; script.write_text('private test only')
    monkeypatch.setattr(module, 'SCRIPT', script)
    relay = module.Relay({'token': 'b' * 64}, str(tmp_path / 'claims.sqlite'))
    calls = []
    def fail(request):
        calls.append(request)
        raise TimeoutError()
    relay.forward = fail
    request = {'action': 'send', 'operation_id': OP, 'uid': 900001, 'charac_no': 900001, 'message': '消息'}
    assert relay.handle(request)['transport_status'] == 'uncertain'
    relay.journal.close()
    restarted = module.Relay({'token': 'b' * 64}, str(tmp_path / 'claims.sqlite'))
    restarted.forward = fail
    assert restarted.handle(request)['reason_code'] == 'duplicate_operation' and len(calls) == 1
    restarted.journal.close()


def test_private_candidate_generator_never_overwrites_source(tmp_path):
    pytest.importorskip('pwd', reason='POSIX private-file preparation')
    import hashlib
    import importlib.util
    spec = importlib.util.spec_from_file_location('prepare_private_message', Path(__file__).resolve().parents[1] / 'deploy/prepare_private_message.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    tmp_path.chmod(0o700)
    source = tmp_path / 'original.js'
    original = b'function start(){};function api_scheduleOnMainThread(){};rpc.exports={};'
    source.write_bytes(original); source.chmod(0o600)
    output = tmp_path / 'candidate.js'; config = tmp_path / 'relay.json'
    fingerprint = module.prepare(source, output, config, hashlib.sha256(original).hexdigest())
    private = json.loads(config.read_text())
    assert source.read_bytes() == original and private['script_sha256'] == fingerprint
    assert len(private['token']) == 64 and private['token'] in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600 and config.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        module.prepare(source, output, config, hashlib.sha256(original).hexdigest())
