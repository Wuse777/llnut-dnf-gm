"""Internal typed transport; never expose this directly as an HTTP endpoint.

The orchestration layer MUST commit a durable dispatch claim and audit before
calling this transport, and must never automatically replay an uncertain claim.
A completed UDP send is not an application acknowledgement. No receive/retry,
raw-packet, host, character-selector or user-supplied opcode interface exists.
"""
import socket
import struct
import unicodedata

from .native_monitor import MONITOR_PORT, TIMEOUT

NOTICE = struct.Struct('<HHHIB255s')
KICK = struct.Struct('<HHHIII')
ACTIONS = ('native-notice', 'native-kick', 'native-message')


def notice_packet(text):
    if (not isinstance(text, str) or not text.strip()
            or any(unicodedata.category(c).startswith('C') for c in text)):
        raise ValueError('公告不能为空或包含控制字符')
    encoded = text.encode('utf-8')
    # Buffer is 255 bytes; reserve one NUL because monitor logs it as a C string.
    # This is the protocol byte bound, not an arbitrary game item quantity cap.
    if len(encoded) > 254:
        raise ValueError('公告 UTF-8 编码不能超过254字节')
    return NOTICE.pack(2528, NOTICE.size, 0, 0, len(encoded), encoded)


def kick_packet(uid):
    if type(uid) is not int or not 1 <= uid <= 0xffffffff:
        raise ValueError('UID outside native uint32 range')
    # Always account scoped. A nonzero character selector takes another lookup
    # path in the original monitor and is deliberately not accepted here.
    return KICK.pack(1217, KICK.size, 0, 0, uid, 0)


class NativeControlTransport:
    def __init__(self, monitor):
        self.monitor = monitor
        self.settings = monitor.settings

    def unavailable_reason(self, action, uid=None):
        if action not in ACTIONS:
            return 'unsupported_action'
        s = self.settings
        if action not in s.native_control_actions or s.write_approvals.get(action) is not True:
            return 'disabled'
        unavailable = self.monitor.unavailable_reason()
        if unavailable:
            return unavailable[0]
        # A broadcast cannot be scoped to dedicated test accounts.
        if action == 'native-notice' and s.test_uids:
            return 'broadcast_test_scope'
        if action in ('native-kick', 'native-message') and s.test_uids and uid not in s.test_uids:
            return 'test_target_only'
        return None

    def notice(self, text):
        return self._send('native-notice', notice_packet(text))

    def kick(self, uid):
        return self._send('native-kick', kick_packet(uid), uid)

    def _send(self, action, packet, uid=None):
        result = {'transport_status': 'not_sent', 'effect_status': 'unknown',
                  'reason_code': None, 'automatic_retry_allowed': False}
        unavailable = self.unavailable_reason(action, uid)
        if unavailable:
            return {**result, 'reason_code': unavailable}
        # Share the exact semaphore with read-only session queries.
        if not self.monitor.slot.acquire(blocking=False):
            return {**result, 'reason_code': 'busy'}
        sock = None
        entered_send = False
        try:
            # Recheck current snapshot/activation after acquiring the shared slot.
            unavailable = self.unavailable_reason(action, uid)
            if unavailable:
                return {**result, 'reason_code': unavailable}
            sock = self.monitor.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(TIMEOUT)
            sock.connect((self.settings.db_host, MONITOR_PORT))
            entered_send = True
            if sock.send(packet) != len(packet):
                return {**result, 'transport_status': 'uncertain', 'reason_code': 'send_uncertain'}
            return {**result, 'transport_status': 'sent', 'reason_code': 'no_application_ack'}
        except OSError:
            # Includes timeout. Even a send error is not permission to replay.
            return {**result, 'transport_status': 'uncertain' if entered_send else 'not_sent',
                    'reason_code': 'send_uncertain' if entered_send else 'connection_failed'}
        finally:
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                # A close failure cannot undo a successful datagram or justify a retry.
                pass
            finally:
                self.monitor.slot.release()
