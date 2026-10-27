"""1031 lock archive adapter: fixed 100 records, never clears a lock/item."""
import hashlib
import struct
import zlib

WAIT_SECONDS = 259200
SIZE = 800


def decode(blob):
    if not isinstance(blob, (bytes, bytearray)) or not 5 <= len(blob) <= 4096:
        raise ValueError('锁定存档缺失或大小异常')
    if struct.unpack_from('<I', blob)[0] != SIZE:
        raise ValueError('不支持的锁定存档长度')
    z = zlib.decompressobj()
    try:
        raw = z.decompress(blob[4:], SIZE + 1)
    except zlib.error as e:
        raise ValueError('锁定存档压缩流损坏') from e
    if len(raw) != SIZE or not z.eof or z.unused_data or z.unconsumed_tail:
        raise ValueError('锁定存档压缩流不完整或含额外数据')
    records = []
    for i in range(100):
        stamp, state, padding = struct.unpack_from('<IB3s', raw, i * 8)
        if state not in (0, 1, 2) or padding != b'\0' * 3:
            raise ValueError('未知锁定状态或格式，禁止修改')
        if state == 2 and not stamp:
            raise ValueError('解锁申请时间异常')
        if state:
            records.append(dict(lock_key=i+1, state=state, requested_at=stamp,
                                due_at=stamp+WAIT_SECONDS if state == 2 else None))
    return raw, records


def fingerprint(blob):
    return hashlib.sha256(blob).hexdigest()


def expire(blob, keys, now):
    raw, records = decode(blob)
    if not keys or len(keys) != len(set(keys)) or any(type(k) is not int or not 1 <= k <= 100 for k in keys):
        raise ValueError('必须选择不同的有效申请编号')
    selected = [r for r in records if r['lock_key'] in keys]
    if len(selected) != len(keys) or any(r['state'] != 2 or r['due_at'] <= now for r in selected):
        raise ValueError('申请不存在、不是待解锁状态或已经到期，请刷新')
    data = bytearray(raw)
    for row in selected:
        struct.pack_into('<I', data, (row['lock_key']-1)*8, now-WAIT_SECONDS-1)
    return struct.pack('<I', SIZE)+zlib.compress(data), selected
