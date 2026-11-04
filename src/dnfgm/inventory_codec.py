"""Independent QF1031 61-byte slot patcher; never a general binary/SQL editor.

The reference is the complete container image plus target coordinates, NOT a
permanent globally unique item ID. Unknown bytes/bits are retained byte-for-byte.
This module does not authorize writes, access databases, or infer client stats.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import struct
import zlib

from .character_detail import SLOT_SIZE, MAX_SLOTS

EQUIPMENT = {1, 6}
STACKABLE = {2, 3, 4, 7, 10}
ORDINARY = EQUIPMENT | STACKABLE
# Only these bytes have a format contract. Arbitrary IDs, flags, raw patches,
# pets/avatar linked records and magic-seal editing are deliberately not exposed.
FIELDS = {'enhancement', 'durability', 'forge', 'amplify_type', 'amplify_value', 'orb_id', 'quality_raw', 'quantity'}


class InventoryFormatError(ValueError):
    pass


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise InventoryFormatError('字段必须为原生存储范围内的整数')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unpack(blob):
    if not isinstance(blob, bytes) or not 5 <= len(blob) <= 65535:
        raise InventoryFormatError('容器存档长度异常，不能按空背包处理')
    expected = struct.unpack_from('<I', blob)[0]
    if not expected or expected > SLOT_SIZE * MAX_SLOTS or expected % SLOT_SIZE:
        raise InventoryFormatError('容器存档长度与61字节槽位不匹配')
    try:
        stream = zlib.decompressobj()
        data = stream.decompress(blob[4:], expected + 1)
        if len(data) != expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
            raise InventoryFormatError('容器压缩流不完整或有尾部数据')
    except zlib.error:
        raise InventoryFormatError('容器压缩数据无法解码') from None
    return data


def pack(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_SLOTS * SLOT_SIZE or len(data) % SLOT_SIZE:
        raise InventoryFormatError('非法容器明文长度')
    return struct.pack('<I', len(data)) + zlib.compress(data)


def slot_view(raw):
    if not isinstance(raw, bytes) or len(raw) != SLOT_SIZE:
        raise InventoryFormatError('槽位长度异常')
    item_id = struct.unpack_from('<I', raw, 2)[0]
    kind = raw[1]
    base = {'id': item_id, 'type': kind, 'slot_sha256': digest(raw), 'empty': item_id == 0,
            'lock_key': raw[20], 'sealed_raw': raw[0], 'equipment': kind in EQUIPMENT,
            'editable': bool(item_id and kind in ORDINARY)}
    if kind in EQUIPMENT:
        base.update(enhancement=raw[6] & 31, reseal_count_raw=raw[6] >> 5,
                    durability=struct.unpack_from('<H', raw, 11)[0], forge=raw[51],
                    amplify_type=raw[17], amplify_value=struct.unpack_from('<H', raw, 18)[0],
                    orb_id=struct.unpack_from('<I', raw, 13)[0])
        if kind == 1:
            base['quality_raw'] = struct.unpack_from('>I', raw, 7)[0]
            base['quality_note'] = '原始品级字段，不是百分比；不推断最上级或最终属性'
    elif kind in STACKABLE:
        base['quantity'] = struct.unpack_from('<I', raw, 7)[0]
    if kind == 5:
        base['unsupported_reason'] = '宠物涉及独立关联记录，不能按普通槽位回收或修改数量'
    elif kind not in ORDINARY:
        base['unsupported_reason'] = '未知或未适配槽位类型'
    return base


def identity(secret, *, uid, charac_no, container, slot, blob, image_digest, pvf_sha256, program_sha256):
    """Opaque optimistic reference. Every byte and coordinate participates."""
    integer(uid, 1, 2147483647)
    integer(charac_no, 1, 2147483647)
    integer(slot, 0, MAX_SLOTS - 1)
    if container not in ('inventory', 'equipment', 'warehouse', 'account_warehouse'):
        raise InventoryFormatError('未知容器')
    if not isinstance(secret, str) or len(secret.encode()) < 32:
        raise InventoryFormatError('实例签名密钥无效')
    for value, pattern in ((image_digest, r'sha256:[a-f0-9]{64}'), (pvf_sha256, r'[a-f0-9]{64}'), (program_sha256, r'[a-f0-9]{64}')):
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise InventoryFormatError('实例版本指纹无效')
    raw = unpack(blob)
    if (slot + 1) * SLOT_SIZE > len(raw):
        raise InventoryFormatError('槽位不在当前容器范围内')
    payload = {'version': 1, 'uid': uid, 'charac_no': charac_no, 'container': container,
               'slot': slot, 'container_sha256': digest(blob), 'slot_sha256': digest(raw[slot*SLOT_SIZE:(slot+1)*SLOT_SIZE]),
               'image_digest': image_digest, 'pvf_sha256': pvf_sha256, 'program_sha256': program_sha256}
    return hmac.new(secret.encode(), json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class InventoryPatch:
    before_sha256: str
    after_sha256: str
    before_slot: dict
    after_slot: dict
    changed_fields: dict
    after_blob: bytes


def patch(blob, slot, changes, *, reclaim=False):
    integer(slot, 0, MAX_SLOTS - 1)
    if type(reclaim) is not bool or not isinstance(changes, dict) or set(changes) - FIELDS:
        raise InventoryFormatError('不支持的修改字段或操作')
    raw = unpack(blob)
    start = slot * SLOT_SIZE
    if start + SLOT_SIZE > len(raw):
        raise InventoryFormatError('槽位不在当前容器范围内')
    original = raw[start:start+SLOT_SIZE]
    before = slot_view(original)
    if before['empty']:
        raise InventoryFormatError('目标槽位已空，不能创建或替换物品')
    kind = before['type']
    if kind not in ORDINARY:
        raise InventoryFormatError('该类型涉及未知或关联存档，不支持普通槽位编辑/回收')
    if reclaim:
        if changes:
            raise InventoryFormatError('回收不能混入属性修改')
        if before['lock_key']:
            raise InventoryFormatError('锁定物品需先完成解锁，不能留下孤立锁申请')
        edited = bytes(SLOT_SIZE)
        changed = {'reclaimed': {'before': before['id'], 'after': None}}
    else:
        if not changes:
            raise InventoryFormatError('请至少修改一个属性')
        allowed = {'enhancement', 'durability', 'forge', 'amplify_type', 'amplify_value', 'orb_id'} if kind in EQUIPMENT else {'quantity'}
        if kind == 1:
            allowed.add('quality_raw')
        if set(changes) - allowed:
            raise InventoryFormatError('修改字段与当前物品类型不匹配')
        target = bytearray(original)
        for key, value in changes.items():
            if key == 'enhancement':
                target[6] = (target[6] & 0xe0) | integer(value, 0, 31)
            elif key == 'forge':
                target[51] = integer(value, 0, 255)
            elif key == 'amplify_type':
                target[17] = integer(value, 0, 4)
            elif key in ('durability', 'amplify_value'):
                struct.pack_into('<H', target, 11 if key == 'durability' else 18, integer(value, 0, 65535))
            elif key == 'orb_id':
                struct.pack_into('<I', target, 13, integer(value, 0, 4294967295))
            elif key == 'quality_raw':
                struct.pack_into('>I', target, 7, integer(value, 0, 4294967295))
            else:
                # Matches the requested native quantity contract, never PVF caps.
                struct.pack_into('<I', target, 7, integer(value, 1, 2147483647))
        if {'amplify_type', 'amplify_value'} & set(changes):
            if target[17] > 4 or (target[17] == 0 and struct.unpack_from('<H', target, 18)[0] != 0):
                raise InventoryFormatError('增幅类型与数值不一致；清除增幅须同时归零')
        edited = bytes(target)
        after = slot_view(edited)
        changed = {key: {'before': before[key], 'after': after[key]} for key in changes if before[key] != after[key]}
        if not changed:
            raise InventoryFormatError('与原存档相同，无需提交')
    after_blob = pack(raw[:start] + edited + raw[start+SLOT_SIZE:])
    return InventoryPatch(digest(blob), digest(after_blob), before, slot_view(edited), changed, after_blob)


def restore(current, *, expected_after_sha256, saved_before, saved_before_sha256):
    """Restore only when the ENTIRE current container is the exact prior after-image."""
    for value in (expected_after_sha256, saved_before_sha256):
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
            raise InventoryFormatError('历史快照摘要格式异常')
    current_raw = unpack(current)
    before_raw = unpack(saved_before)
    if not hmac.compare_digest(digest(current), expected_after_sha256):
        raise InventoryFormatError('容器已发生后续变化，禁止用历史快照覆盖玩家进度')
    if not hmac.compare_digest(digest(saved_before), saved_before_sha256):
        raise InventoryFormatError('历史快照校验失败，不能恢复')
    if len(current_raw) != len(before_raw):
        raise InventoryFormatError('历史快照容器尺寸不匹配')
    return saved_before
