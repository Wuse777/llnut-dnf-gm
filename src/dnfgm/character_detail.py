"""Read-only QF1031 storage decoding. Never builds or writes inventory bytes.

Independent implementation from the documented 4-byte LE length + zlib stream,
61-byte item layout; see THIRD_PARTY.md. Invalid data is unknown, never empty.
"""
import struct
import zlib

SLOT_SIZE = 61
MAX_SLOTS = 1024
TYPES = {1:'装备',2:'消耗品',3:'材料',4:'任务材料',5:'宠物',6:'宠物装备',7:'宠物消耗品',10:'副职业道具'}
EQUIP_SLOTS = ['武器','称号','上衣','头肩','下装','鞋','腰带','项链','手镯','戒指','辅助装备','魔法石']
ATTRIBUTES = {
    'maxHP':'最大 HP 存档值','maxMP':'最大 MP 存档值',
    'phy_attack':'物理攻击字段（原始）','phy_defense':'物理防御字段（原始）',
    'mag_attack':'魔法攻击字段（原始）','mag_defense':'魔法防御字段（原始）',
    'hp_regen':'HP 恢复原始值','mp_regen':'MP 恢复原始值',
    'move_speed':'移动速度原始值','attack_speed':'攻击速度原始值',
    'cast_speed':'施放速度原始值','hit_recovery':'硬直原始值','jump':'跳跃原始值',
    'inven_weight':'背包负重原始值','charac_weight':'角色重量原始值',
}
# Explicit allowlist, no VIP/password/QQ and no unparsed property blobs.
INFO_COLUMNS = ('m_id','charac_no','charac_name','lev','delete_flag','job','grow_type','sex','exp',
                'fatigue','max_fatigue','premium_fatigue','max_premium_fatigue','guild_id',
                'create_time','last_play_time',*ATTRIBUTES)


def decode_container(blob, equipment=False):
    if blob is None:
        return {'state':'missing','message':'无此容器的存档记录','items':[], 'slot_count':None}
    # Empty or truncated bytes are not evidence of an empty backpack.
    if not isinstance(blob, bytes) or not 5 <= len(blob) <= 65535:
        return {'state':'invalid','message':'存档长度异常，无法解析；不代表空背包','items':[], 'slot_count':None}
    try:
        expected = struct.unpack_from('<I', blob)[0]
        if expected == 0 or expected > MAX_SLOTS*SLOT_SIZE or expected % SLOT_SIZE:
            raise ValueError()
        stream = zlib.decompressobj()
        data = stream.decompress(blob[4:], expected+1)
        if len(data) != expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
            raise ValueError()
        items = []
        for slot in range(expected//SLOT_SIZE):
            raw = data[slot*SLOT_SIZE:(slot+1)*SLOT_SIZE]
            item_id = struct.unpack_from('<I', raw, 2)[0]
            if item_id == 0:
                continue
            kind = raw[1]
            equip = kind in (1,6)
            items.append({
                'slot':slot, 'slot_label':EQUIP_SLOTS[slot] if equipment and slot<len(EQUIP_SLOTS) else f'槽位 {slot}',
                'id':item_id, 'type':kind, 'type_name':TYPES.get(kind, f'未知类型 {kind}'),
                'quantity':1 if equip else struct.unpack_from('<I',raw,7)[0] if kind in (2,3,4,7,10) else None,
                'enhancement':raw[6]&31 if equip else None,
                'durability':struct.unpack_from('<H',raw,11)[0] if equip else None,
                'forge':raw[51] if equip else None,
                'amplify_type':raw[17] if equip else None,
                'amplify_value':struct.unpack_from('<H',raw,18)[0] if equip else None,
                'orb_id':struct.unpack_from('<I',raw,13)[0] if equip else None,
                'sealed_raw':raw[0],
            })
        return {'state':'ok','message':'已读取数据库存档','slot_count':expected//SLOT_SIZE,'items':items}
    except (ValueError, struct.error, zlib.error):
        return {'state':'invalid','message':'存档格式或压缩数据异常，无法解析；不代表空背包','items':[], 'slot_count':None}


def profession(job, grow_type, jobs):
    entry = jobs.get(str(job), {})
    names = entry.get('grow_names', [])
    base = names[0] if names else f'未知职业 #{job}'
    # Only exact PVF growtype-name indices. Do not infer awakening bit flags.
    mapped = 0 <= grow_type < len(names)
    return {'base_name':base, 'name':names[grow_type] if mapped else base,
            'job':job,'grow_type':grow_type,'grow_name_known':mapped,
            'note':'名称来自当前PVF；觉醒标记未推断' if mapped else '转职/觉醒代码未映射，保留原始代码'}
