"""Fixed local transport for senderless, character-bound system notifications.

The caller must own a durable NativeOperations dispatch claim. No retries,
client acknowledgement, caller-selected socket, packet or expression exists.
"""
import json
import math
import re
import socket
import unicodedata

from .catalog import snapshot

SOCKET = '/run/dnf-gm-message/relay.sock'
BRIDGE_VERSION = 1
GAME_SHA256 = '8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261'
TIMEOUT = 2.0
LIMIT = 4096


def message_text(value):
    if (not isinstance(value, str) or not value.strip()
            or any(unicodedata.category(c).startswith('C') for c in value)
            or len(value.encode('utf-8')) > 254):
        raise ValueError('系统消息不能为空、包含控制字符或超过254个UTF-8字节')
    return value


def read_frame(sock):
    body = bytearray()
    while b'\n' not in body:
        chunk = sock.recv(min(1024, LIMIT + 1 - len(body)))
        if not chunk or len(body) + len(chunk) > LIMIT:
            raise ValueError('Invalid local message frame')
        body.extend(chunk)
    if not body.endswith(b'\n') or body.count(b'\n') != 1:
        raise ValueError('Invalid local message frame')
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError('Invalid local message response')
    return data


class PrivateMessageTransport:
    def __init__(self, native, socket_factory=None):
        self.native = native
        self.monitor = native.monitor
        self.settings = native.settings
        self.socket_factory = socket_factory or socket.socket

    def unavailable_reason(self, uid=None):
        return self.native.unavailable_reason('native-message', uid)

    def _exchange(self, request):
        with self.socket_factory(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT)
            sock.connect(SOCKET)
            sock.sendall(json.dumps(request, separators=(',', ':'), ensure_ascii=False).encode() + b'\n')
            return read_frame(sock)

    def status(self):
        reason = self.unavailable_reason()
        enabled = ('native-message' in self.settings.native_control_actions
                   and self.settings.write_approvals.get('native-message') is True
                   and self.settings.native_monitor_enabled is True)
        if reason in (None, 'test_target_only'):
            live = snapshot(self.settings)
            if any(type(live.get(key)) not in (int, float) or not math.isfinite(live[key]) or live[key] < minimum
                   for key, minimum in (('mem_available_mib', 256), ('swap_free_mib', 1536))):
                reason = 'resource_guard'
        result = {'implemented': True, 'enabled': enabled,
                  'ready': False, 'reason_code': reason, 'bridge_state': 'disabled' if reason == 'disabled' else 'unavailable',
                  'note': '定向调用游戏系统消息；发送状态不证明客户端已显示。插件须在维护窗口显式安装并验收。'}
        # The test-account restriction applies to a target, not to a read-only handshake.
        if reason and reason != 'test_target_only':
            return result
        if not self.monitor.slot.acquire(blocking=False):
            return {**result, 'reason_code': 'busy'}
        try:
            data = self._exchange({'action': 'status'})
            ready = (data == {'ready': True, 'bridge_version': BRIDGE_VERSION, 'game_sha256': GAME_SHA256})
            return {**result, 'ready': ready, 'reason_code': None if ready else 'bridge_unavailable',
                    'bridge_state': 'ready' if ready else 'unavailable'}
        except (OSError, ValueError, TypeError):
            return {**result, 'reason_code': 'bridge_unavailable'}
        finally:
            self.monitor.slot.release()

    def send(self, operation_id, uid, charac_no, message):
        message_text(message)
        if (not isinstance(operation_id, str) or not re.fullmatch('[a-f0-9]{32}', operation_id)
                or any(type(v) is not int or not 1 <= v <= 0x7fffffff for v in (uid, charac_no))):
            raise ValueError('Invalid message target or operation')
        result = {'transport_status': 'not_sent', 'effect_status': 'unknown',
                  'reason_code': None, 'automatic_retry_allowed': False}
        reason = self.unavailable_reason(uid)
        if reason:
            return {**result, 'reason_code': reason}
        if not self.monitor.slot.acquire(blocking=False):
            return {**result, 'reason_code': 'busy'}
        sock = None
        entered_send = False
        try:
            reason = self.unavailable_reason(uid)
            if reason:
                return {**result, 'reason_code': reason}
            sock = self.socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(TIMEOUT)
            sock.connect(SOCKET)
            request = {'action': 'send', 'operation_id': operation_id, 'uid': uid,
                       'charac_no': charac_no, 'message': message}
            entered_send = True
            sock.sendall(json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
            data = read_frame(sock)
            allowed = {'primitive_invoked', 'target_offline', 'character_changed', 'expired',
                       'duplicate_operation', 'bridge_unavailable', 'busy', 'invalid_request', 'primitive_failed'}
            if (set(data) != {'operation_id', 'transport_status', 'reason_code'}
                    or data['operation_id'] != operation_id or data['reason_code'] not in allowed
                    or data['transport_status'] not in ('sent', 'not_sent', 'uncertain')
                    or (data['transport_status'] == 'sent') != (data['reason_code'] == 'primitive_invoked')):
                raise ValueError('Invalid local message acknowledgement')
            return {**result, 'transport_status': data['transport_status'], 'reason_code': data['reason_code']}
        except (OSError, ValueError, TypeError):
            return {**result, 'transport_status': 'uncertain' if entered_send else 'not_sent',
                    'reason_code': 'send_uncertain' if entered_send else 'bridge_unavailable'}
        finally:
            try:
                if sock is not None:
                    sock.close()
            finally:
                self.monitor.slot.release()
