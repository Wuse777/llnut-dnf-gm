"""Synthetic archives only. Byte-format correctness is not in-game acceptance."""
import hashlib
import random
import struct
import zlib

import pytest

from dnfgm.inventory_codec import (InventoryFormatError, SLOT_SIZE, MAX_SLOTS, digest,
                                   identity, pack, patch, restore, slot_view, unpack)


def slot(kind=1, item=101):
    raw = bytearray(random.Random(42).randbytes(SLOT_SIZE))
    raw[1] = kind
    struct.pack_into('<I', raw, 2, item)
    raw[6] = 0xe7  # Reseal bits must survive enhancement changes.
    raw[17] = 2
    struct.pack_into('<H', raw, 18, 123)
    raw[20] = 0
    return bytes(raw)


def archive(kind=1):
    return pack(slot(2, 111) + slot(kind) + slot(3, 222))


def test_round_trip_and_bounds():
    for count in (1, 3, MAX_SLOTS):
        raw = random.Random(count).randbytes(count * SLOT_SIZE)
        assert unpack(pack(raw)) == raw
    for raw in (b'', b'x', bytes(SLOT_SIZE * (MAX_SLOTS + 1)), bytearray(SLOT_SIZE), None):
        with pytest.raises(InventoryFormatError):
            pack(raw)


@pytest.mark.parametrize('value', [None, bytearray(61), b'', bytes(4), bytes(65536),
    struct.pack('<I', 0) + zlib.compress(b''), struct.pack('<I', 62) + zlib.compress(bytes(62)),
    struct.pack('<I', 61 * (MAX_SLOTS + 1)) + zlib.compress(bytes(61)),
    struct.pack('<I', 61) + zlib.compress(bytes(62)),
    struct.pack('<I', 61) + zlib.compress(bytes(60)),
    struct.pack('<I', 61) + b'not zlib',
    struct.pack('<I', 61) + zlib.compress(bytes(61))[:-1],
    struct.pack('<I', 61) + zlib.compress(bytes(61)) + b'x',
    struct.pack('<I', 61) + zlib.compress(bytes(61)) + zlib.compress(bytes(61)),
    struct.pack('<I', 61) + zlib.compress(bytes(1000000))])
def test_corrupt_archive_is_never_an_empty_inventory(value):
    with pytest.raises(InventoryFormatError):
        unpack(value)


@pytest.mark.parametrize('field,value,offsets', [
    ('enhancement', 31, {6}), ('durability', 65535, {11, 12}), ('forge', 255, {51}),
    ('amplify_type', 4, {17}), ('amplify_value', 65535, {18, 19}),
    ('orb_id', 4294967295, {13, 14, 15, 16}), ('quality_raw', 0x12345678, {7, 8, 9, 10})])
def test_edit_preserves_all_other_bytes_and_slots(field, value, offsets):
    before = archive()
    edit = patch(before, 1, {field: value})
    old, new = unpack(before), unpack(edit.after_blob)
    assert new[:61] == old[:61] and new[122:] == old[122:]
    assert all(new[i] == old[i] for i in range(61, 122) if i - 61 not in offsets)
    assert new[67] & 0xe0 == old[67] & 0xe0
    assert edit.before_sha256 == digest(before)
    assert edit.after_sha256 == digest(edit.after_blob)
    assert edit.after_slot[field] == value
    assert edit.changed_fields == {field: {'before': edit.before_slot[field], 'after': value}}
    if field == 'quality_raw':
        assert new[68:72] == b'\x12\x34\x56\x78'
        assert '不是百分比' in edit.after_slot['quality_note']


@pytest.mark.parametrize('kind', [2, 3, 4, 7, 10])
def test_stackable_native_int32_without_pvf_limit(kind):
    before = archive(kind)
    for quantity in (1, 1000000, 2147483647):
        edit = patch(before, 1, {'quantity': quantity})
        assert edit.after_slot['quantity'] == quantity
        assert unpack(edit.after_blob)[68:72] == struct.pack('<I', quantity)
        assert unpack(edit.after_blob)[:68] == unpack(before)[:68]
        assert unpack(edit.after_blob)[72:] == unpack(before)[72:]


@pytest.mark.parametrize('field,high', [('enhancement', 31), ('durability', 65535), ('forge', 255),
    ('amplify_type', 4), ('amplify_value', 65535), ('orb_id', 4294967295), ('quality_raw', 4294967295), ('quantity', 2147483647)])
def test_scalar_limits_and_types(field, high):
    before = archive(2 if field == 'quantity' else 1)
    for value in (-1, high+1, True, False, 1.0, '1', None, [], {}, float('nan')):
        with pytest.raises(InventoryFormatError):
            patch(before, 1, {field: value})
    if field == 'quantity':
        with pytest.raises(InventoryFormatError):
            patch(before, 1, {'quantity': 0})


def test_amplification_clear_must_clear_value_and_order_does_not_matter():
    with pytest.raises(InventoryFormatError):
        patch(archive(), 1, {'amplify_type': 0})
    a = patch(archive(), 1, {'amplify_type': 0, 'amplify_value': 0})
    b = patch(archive(), 1, {'amplify_value': 0, 'amplify_type': 0})
    assert a.after_blob == b.after_blob


@pytest.mark.parametrize('kind,field', [(1, 'quantity'), (6, 'quality_raw'), (2, 'enhancement'), (3, 'orb_id'), (5, 'quantity'), (0, 'quantity'), (255, 'quantity')])
def test_incompatible_or_linked_types_rejected(kind, field):
    with pytest.raises(InventoryFormatError):
        patch(archive(kind), 1, {field: 1})


def test_noop_empty_unknown_and_bad_selection():
    for changes in ({}, {'item_id': 123}, {'lock_key': 0}, {'sealed_raw': 0}, {'enhancement': 7}, []):
        with pytest.raises(InventoryFormatError):
            patch(archive(), 1, changes)
    for index in (-1, 3, MAX_SLOTS, True, '1'):
        with pytest.raises(InventoryFormatError):
            patch(archive(), index, {'enhancement': 2})
    with pytest.raises(InventoryFormatError):
        patch(pack(bytes(61)), 0, {'quantity': 1})


@pytest.mark.parametrize('kind', [1, 2, 3, 4, 6, 7, 10])
def test_reclaim_zeros_exactly_one_slot(kind):
    blob = archive(kind)
    result = patch(blob, 1, {}, reclaim=True)
    assert unpack(result.after_blob) == unpack(blob)[:61] + bytes(61) + unpack(blob)[122:]
    assert result.after_slot['empty']
    assert result.changed_fields == {'reclaimed': {'before': 101, 'after': None}}


def test_reclaim_does_not_orphan_lock_or_pet_records():
    locked = bytearray(slot()); locked[20] = 13
    for blob in (pack(bytes(locked)), pack(slot(5)), pack(slot(255))):
        with pytest.raises(InventoryFormatError):
            patch(blob, 0, {}, reclaim=True)
    with pytest.raises(InventoryFormatError):
        patch(archive(), 1, {'enhancement': 2}, reclaim=True)
    with pytest.raises(InventoryFormatError):
        patch(archive(), 1, {}, reclaim=1)


def test_restore_exact_original_compressed_image_only():
    original = archive()
    result = patch(original, 1, {'enhancement': 9})
    assert restore(result.after_blob, expected_after_sha256=result.after_sha256,
                   saved_before=original, saved_before_sha256=digest(original)) == original
    for current in (patch(result.after_blob, 1, {'forge': 0}).after_blob,
                    patch(result.after_blob, 0, {'quantity': 200}).after_blob):
        with pytest.raises(InventoryFormatError, match='后续变化'):
            restore(current, expected_after_sha256=result.after_sha256, saved_before=original, saved_before_sha256=digest(original))
    with pytest.raises(InventoryFormatError, match='校验失败'):
        restore(result.after_blob, expected_after_sha256=result.after_sha256, saved_before=original, saved_before_sha256='0'*64)
    shorter = pack(slot())
    with pytest.raises(InventoryFormatError, match='尺寸'):
        restore(result.after_blob, expected_after_sha256=result.after_sha256, saved_before=shorter, saved_before_sha256=digest(shorter))
    for value in (None, 7, True, '0'*63, 'X'*64):
        with pytest.raises(InventoryFormatError):
            restore(result.after_blob, expected_after_sha256=value, saved_before=original, saved_before_sha256=digest(original))


def test_reference_binds_every_coordinate_full_image_and_version():
    args = dict(secret='a'*32, uid=1, charac_no=2, container='inventory', slot=1, blob=archive(),
                image_digest='sha256:'+'a'*64, pvf_sha256='b'*64, program_sha256='c'*64)
    initial = identity(**args)
    assert initial == identity(**args) and len(initial) == 64
    changes = dict(secret='b'*32, uid=2, charac_no=3, container='warehouse', slot=0,
                   blob=patch(args['blob'], 0, {'quantity': 9876}).after_blob,
                   image_digest='sha256:'+'d'*64, pvf_sha256='e'*64, program_sha256='f'*64)
    assert len({identity(**{**args, key:value}) for key, value in changes.items()}) == len(changes)
    for key, value in changes.items():
        assert identity(**{**args, key: value}) != initial
    for key, value in [('secret',''), ('uid',True), ('container','../../etc'), ('slot',3), ('image_digest',''), ('pvf_sha256',None)]:
        with pytest.raises(InventoryFormatError):
            identity(**{**args, key:value})


def test_random_unknown_bytes_survive_combined_patches():
    rng = random.Random(107)
    for _ in range(200):
        raw = bytearray(rng.randbytes(61 * 8))
        target = rng.randrange(8); base = target*61
        raw[base+1] = 1
        struct.pack_into('<I', raw, base+2, 123)
        raw[base+17] = 1
        change = {'enhancement': rng.randrange(32), 'forge': rng.randrange(256), 'durability': rng.randrange(65536)}
        result = unpack(patch(pack(bytes(raw)), target, change).after_blob)
        changed = {base+6, base+11, base+12, base+51}
        assert all(result[i] == raw[i] for i in range(len(raw)) if i not in changed)
        assert result[base+6] & 0xe0 == raw[base+6] & 0xe0
