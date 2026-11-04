"""Typed, read-only adapter for the fingerprinted 1031 monitor.

No arbitrary packet API, writes, DNS, retries, or player credential access.
An absent/late/malformed response is UNKNOWN, never evidence of logout.
"""
from contextlib import closing
import ipaddress
import secrets
import socket
import struct
from threading import BoundedSemaphore
import time

from .catalog import snapshot

MONITOR_SHA256 = 'a099d2b3ebc77bfe1393bec3543a41ba8c20c99d0abc26619241d31964dea6d7'
MONITOR_PORT = 30303
QUERY_OPCODE = 2000
QUERY = struct.Struct('<HHHIIIB')
TIMEOUT = .75
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in
                         ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def private_ipv4(value):
    if not isinstance(value, str):
        return False
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError, TypeError):
        return False
    return any(address in network for network in PRIVATE_NETWORKS)


def query_packet(uid, nonce):
    if type(uid) is not int or not 1 <= uid <= 0xffffffff:
        raise ValueError('UID outside native uint32 range')
    if type(nonce) is not int or not 0 <= nonce <= 0xffffffff:
        raise ValueError('Nonce outside uint32 range')
    return QUERY.pack(QUERY_OPCODE, QUERY.size, 0, 0, uid, nonce, 0)


def decode_reply(data, uid, nonce, client_port, client_ip):
    if len(data) != QUERY.size:
        raise ValueError('Unexpected native response length')
    opcode, size, port, ip, account, echoed, state = QUERY.unpack(data)
    if (opcode, size, account, echoed) != (QUERY_OPCODE, QUERY.size, uid, nonce):
        raise ValueError('Mismatched native response')
    if port != client_port or ip != int(ipaddress.IPv4Address(client_ip)) or state not in (0, 1):
        raise ValueError('Invalid native response fields')
    return bool(state)


class NativeMonitor:
    def __init__(self, settings, socket_factory=None):
        self.settings = settings
        self.socket_factory = socket_factory or socket.socket
        self.slot = BoundedSemaphore(1)

    def unavailable_reason(self):
        s = self.settings
        if not s.native_monitor_enabled:
            return 'disabled', '尚未启用原生在线查询；数据库登录记录仍可查看'
        if not private_ipv4(s.db_host):
            return 'invalid_endpoint', '原生查询仅允许已配置的数据库私网 IPv4 地址'
        status = snapshot(s)
        if not status.get('fresh'):
            return 'stale_snapshot', '采集快照无效或已过期，实时状态未知'
        if not s.image_digest or status.get('image_digest') != s.image_digest:
            return 'image_mismatch', '服务器镜像与适配配置不匹配'
        if status.get('native_monitor_sha256') != MONITOR_SHA256:
            return 'protocol_unverified', '尚未核验当前原生 monitor 程序指纹'
        if status.get('core_ok') is not True:
            return 'core_unhealthy', '核心状态未确认正常，暂不进行原生查询'
        return None

    def query(self, uid):
        # Validate before even considering network access; no caller-supplied opcodes.
        nonce = secrets.randbits(32)
        packet = query_packet(uid, nonce)
        result = {'uid': uid, 'source': 'native_monitor', 'state': 'unknown',
                  'observed_at': None, 'queried_at': time.time(),
                  'note': '原生 monitor 的账号会话快照；不证明当前角色、客户端响应或可立即安全修改存档'}
        unavailable = self.unavailable_reason()
        if unavailable:
            return {**result, 'reason_code': unavailable[0], 'reason': unavailable[1]}
        if not self.slot.acquire(blocking=False):
            return {**result, 'reason_code': 'busy', 'reason': '已有实时查询进行中，请稍后手动刷新'}
        try:
            with closing(self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
                sock.settimeout(TIMEOUT)
                # Connected UDP filters replies to the fixed peer; never bind a public listener.
                sock.connect((self.settings.db_host, MONITOR_PORT))
                client_ip, client_port = sock.getsockname()
                if sock.send(packet) != len(packet):
                    raise OSError('Incomplete datagram')
                data = sock.recv(QUERY.size + 1)
                active = decode_reply(data, uid, nonce, client_port, client_ip)
            return {**result, 'state': 'online' if active else 'offline',
                    'observed_at': time.time(), 'reason_code': 'reply',
                    'reason': '原生服务返回账号存在于会话表' if active else '原生服务返回账号不在会话表'}
        except TimeoutError:
            return {**result, 'reason_code': 'timeout', 'reason': '原生查询超时；不能据此判断离线'}
        except (OSError, ValueError):
            # Do not leak endpoints, raw packets, errno text or exception payloads.
            return {**result, 'reason_code': 'invalid_or_unreachable', 'reason': '未取得有效原生响应；实时状态未知'}
        finally:
            self.slot.release()
