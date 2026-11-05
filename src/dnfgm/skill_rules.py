"""Fixed QF1031 PvE learned-skill codec and offline reset rules.

408 bytes = 204 (uint8 skill ID, uint8 level) pairs. This module has no
process/network/DB access and does not treat unspent point assignment as reset.
"""
import re
import struct
import zlib
from .progression_rules import PROGRAM_SHA, decode_grow_type

RULE_VERSION='qf1031-skills-1'
SIZE=408
GROUPS={0:(6,54),1:(54,102),2:(102,150),3:(150,198)}


def unpack(blob):
    if not isinstance(blob,bytes) or not 5<=len(blob)<=1024 or struct.unpack_from('<I',blob)[0]!=SIZE:
        raise ValueError('技能树不是已适配的408字节压缩存档')
    try:
        stream=zlib.decompressobj();raw=stream.decompress(blob[4:],SIZE+1)
    except zlib.error:raise ValueError('技能树压缩流无法解码') from None
    if len(raw)!=SIZE or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ValueError('技能树压缩流不完整或有额外数据')
    if any(raw[n]==0 and raw[n+1]!=0 for n in range(0,SIZE,2)):
        raise ValueError('空技能槽携带非零等级，不能自动重置')
    return raw


def pack(raw):
    if not isinstance(raw,bytes) or len(raw)!=SIZE:raise ValueError('技能树明文长度无效')
    return struct.pack('<I',SIZE)+zlib.compress(raw)


def native_group(skill_class,feature,fitness_count):
    # CSkill::reform_ui_group_no: the display class is NOT a storage group.
    if feature:return 3
    if skill_class==4:return 2
    if type(skill_class) is int and 0<=skill_class<=3:return 0 if fitness_count>2 else 1
    return None


def profiles(tokens):
    """Keep ordered repeated skill sections; numeric growtype, not file order."""
    result={};first=-1;second=0;tag=None;values=[]
    def flush():
        if tag not in ('[skill]','[awakening skill]'):return
        if len(values)%2 or any(type(v) is not int for v in values) or any(not 1<=v<=255 for v in values[::2]) or any(not 0<=v<=255 for v in values[1::2]):
            raise ValueError('默认技能编号／等级不是已适配的字节对')
        key=f'{first}:{second}'
        if key in result:raise ValueError('默认技能段重复')
        result[key]=list(zip(values[::2],values[1::2]))
    for kind,value in tokens:
        if kind==5:
            flush();tag=None;values=[]
            growth=re.fullmatch(r'\[growtype ([1-6])\]',str(value))
            awakening=re.fullmatch(r'\[awakening ([12])\]',str(value))
            if growth:first=int(growth[1])-1;second=0
            elif awakening:
                if first<0:raise ValueError('觉醒段没有所属转职')
                second=int(awakening[1])
            elif value in ('[skill]','[awakening skill]'):tag=value
        elif tag is not None:values.append(value)
    flush()
    return result


def learned(raw,definitions):
    if len(raw)!=SIZE:raise ValueError('技能树长度异常')
    rows=[]
    for slot in range(SIZE//2):
        sid,level=raw[slot*2:slot*2+2]
        if not sid:continue
        meta=definitions.get(str(sid),{})
        rows.append({'slot':slot,'skill_id':sid,'level':level,'name':meta.get('name') or f'未知技能 #{sid}',
            'group':meta.get('group'),'active':meta.get('active'),'known':bool(meta),
            'section':'initial' if slot<6 else 'stolen' if slot>=198 else 'group'})
    return rows


def rebuild(job_rules,grow_type,expert=None):
    """Initial skills then exact advancement/awakening gifts, with native order.

    The native insert searches initial/stolen slots only for active skills;
    creation defaults use the first six initial slots, other entries their group.
    Side-profession skills are re-added separately at the native effective level.
    """
    first,second=decode_grow_type(grow_type)
    definitions=job_rules['definitions'];defaults=job_rules['defaults'];raw=bytearray(SIZE)
    skipped=[]
    def add(sid,level,initial=False):
        meta=definitions.get(str(sid))
        # Native ignores unresolved script IDs. Preserve this evidence in preview.
        if meta is None:skipped.append({'skill_id':sid,'reason':'PVF技能列表中不存在，原生创建也跳过'});return
        if type(level) is not int or not 0<=level<=255:raise ValueError('默认技能等级超出已适配格式')
        group=meta.get('group');active=meta.get('active') is True
        if not initial:
            ranges=([(0,6),(198,204)] if active else [])+([GROUPS[group]] if group in GROUPS else [])
            for start,end in ranges:
                for slot in range(start,end):
                    if raw[2*slot]==sid:
                        if level==0:raw[2*slot:2*slot+2]=b'\0\0'
                        else:raw[2*slot+1]=level
                        return
        if not initial and level==0:return
        # Demonic swordman (job9) excludes ID0 lookup in native insertion:
        # gifted skills use their group even if initial active slots are free.
        candidates=([(0,6)] if active and (initial or job_rules.get('job')!=9) else [])+([GROUPS[group]] if group in GROUPS else [])
        for start,end in candidates:
            for slot in range(start,end):
                if raw[2*slot]==0:raw[2*slot:2*slot+2]=bytes((sid,level));return
        raise ValueError(f'默认技能 #{sid} 的分组或槽位未适配')
    for sid,level in defaults.get('-1:0',[]):add(sid,level,True)
    for key in (f'{first}:0',*( [f'{first}:{second}'] if second else [])):
        for sid,level in defaults.get(key,[]):add(sid,level)
    if expert:
        for sid,_ in expert['skills']:add(sid,expert['level'])
    return bytes(raw),skipped


def reset_points(level,sp):
    if type(level) is not int or not 1<=level<=127:raise ValueError('等级超出已适配范围')
    try:total=sum(sp[n] for n in range(1,min(level,95)+1))
    except KeyError:raise ValueError('缺少原生技能点等级表') from None
    if not 0<=total<=1073741823:raise ValueError('重置SP超出存档范围')
    return {'sp':total,'tp':max(0,level-49)}


def expert_skills(kind,experience,level,rules):
    if type(kind) is not int or type(experience) is not int:raise ValueError('副职业存档类型异常')
    if kind==0:return None
    row=rules['experts'].get(str(kind))
    if not row or experience<0:raise ValueError('副职业种类／经验尚未适配')
    thresholds=row['thresholds']
    if not thresholds or any(type(n) is not int for n in thresholds) or sorted(set(thresholds))!=thresholds:
        raise ValueError('副职业经验规则异常')
    effective=next((i+1 for i,n in enumerate(thresholds) if n>experience),len(thresholds))
    if experience in thresholds:
        limit=rules['level_limits'].get(str(effective))
        if limit is None or level<limit:effective-=1
    if not 1<=effective<=255:raise ValueError('副职业有效等级无法确定')
    return {'kind':kind,'level':effective,'skills':row['skills']}
