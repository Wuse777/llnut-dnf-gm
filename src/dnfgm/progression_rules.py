"""QF1031 offline growth rules. No database or runtime process access.

Importer uses GetRoundInt(float32(value * 10)); InitializeCharacStat adds
base growth for levels 1..14, first-growth for 15..49, awakened growth from
50. Attribute changes use the difference of those baselines, preserving
non-level bonuses already present in the archive. This is NOT a live upgrade.
"""
import math
import re
import struct

PROGRAM_SHA='8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261'
RULE_VERSION='qf1031-growth-1'
TAGS={
 '[HP MAX]':'maxHP','[MP MAX]':'maxMP','[physical attack]':'phy_attack',
 '[physical defense]':'phy_defense','[magical attack]':'mag_attack','[magical defense]':'mag_defense',
 '[inventory limit]':'inven_weight','[HP regen speed]':'hp_regen','[MP regen speed]':'mp_regen',
 '[move speed]':'move_speed','[attack speed]':'attack_speed','[cast speed]':'cast_speed',
 '[hit recovery]':'hit_recovery','[jump power]':'jump','[weight]':'charac_weight',
 '[fire resistance]':'fire','[water resistance]':'water','[dark resistance]':'dark','[light resistance]':'light',
}
RESISTS=('fire','water','dark','light')
STATS=tuple(k for k in TAGS.values() if k not in RESISTS)
LIMITS={k:(0,65535) for k in ('maxHP','maxMP','phy_attack','phy_defense','mag_attack','mag_defense','move_speed','attack_speed','cast_speed')}
LIMITS.update({k:(-32768,32767) for k in ('hp_regen','mp_regen','hit_recovery','jump',*RESISTS)})
LIMITS.update({k:(-2147483648,2147483647) for k in ('inven_weight','charac_weight')})
POINTS=('remain_sp','remain_sp_2nd','remain_sfp_1st','remain_sfp_2nd')


def scaled(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('成长数值不是有限数字')
    # The native importer stores its multiply result back to a 32-bit float
    # before calling GetRoundInt (half away from zero, not Python bankers round).
    value=struct.unpack('<f',struct.pack('<f',value*10))[0]
    if not math.isfinite(value) or not -2147483648<=value<2147483647:raise ValueError('成长数值超出原生整数范围')
    return math.trunc(value+math.copysign(0.5,value))


def growth_profiles(tokens):
    """Keep repeated section boundaries; Reader.fields() cannot preserve them.

    initial -> (-1,0); growtype N -> (N-1,0); subsequent awakening N
    belongs to that same first-growth. STRDCharacterStatus::Clear initializes
    omitted fields to zero before import; explicit duplicates are errors.
    """
    result={};seen={};current=None;first=None;pending=None
    for kind,value in tokens:
        if kind==5:
            pending=None
            if value=='[initial value]':current=(-1,0);first=None
            elif isinstance(value,str) and (m:=re.fullmatch(r'\[growtype ([1-6])\]',value)):
                first=int(m[1])-1;current=(first,0)
            elif isinstance(value,str) and (m:=re.fullmatch(r'\[awakening ([12])\]',value)):
                if first is None:raise ValueError('觉醒成长段缺少所属转职')
                current=(first,int(m[1]))
            elif value in TAGS:
                if current is None:raise ValueError('成长属性缺少所属段')
                pending=TAGS[value]
                continue
            else:continue
            if current in result:raise ValueError('成长段重复')
            result[current]={key:0 for key in TAGS.values()};seen[current]=set()
        elif pending is not None:
            row=result[current]
            if pending in seen[current]:raise ValueError('成长属性重复')
            row[pending]=scaled(value);seen[current].add(pending);pending=None
    if pending is not None:raise ValueError('成长属性缺少数值')
    if (-1,0) not in result or (0,0) not in result:raise ValueError('缺少基础／未转职成长')
    required={'maxHP','maxMP','phy_attack','phy_defense','mag_attack','mag_defense'}
    if any(not required<=fields for fields in seen.values()):raise ValueError('成长段缺少核心属性')
    return result


def sp_table(values):
    if len(values)%2 or not values or any(type(v) is not int for v in values):raise ValueError('SP表格式未适配')
    result={}
    for level,points in zip(values[::2],values[1::2]):
        if not 1<=level<=200 or level in result or not 0<=points<=1073741823:raise ValueError('SP表内容无效')
        result[level]=points
    if set(result)!=set(range(1,max(result)+1)):raise ValueError('SP表等级不连续')
    return result


def decode_grow_type(value):
    if type(value) is not int or not -128<=value<=127:raise ValueError('职业存档格式无效')
    # Native signed low nibble and signed three-bit second growth; bit 7 is not
    # part of either getter. Preserve the original grow_type, never rewrite it.
    first=value&15;second=(value>>4)&7
    if first>5 or second>2:raise ValueError('职业组合尚未适配')
    return first,second


def baseline(profiles,level,first,second):
    if type(level) is not int or not 1<=level<=127:raise ValueError('等级超出存档范围')
    result=dict(profiles[(-1,0)])
    for step in range(1,level):
        key=(0,0) if step<=14 else (first,0) if step<=49 else (first,second)
        if key not in profiles:raise ValueError('对应转职／觉醒成长不存在')
        for field,value in profiles[key].items():result[field]+=value
    return result


def point_change(points,old_level,new_level,sp):
    """Native SetCharacLevel point formula, NOT repeated normal level-up grants.

    GetSpAtLevelUp accepts 1..95 in this binary (outside -> 0). The admin
    shortcut multiplies the endpoint rate by the level delta, not a sum of all
    intermediate rates. Show its exact effect in the preview.
    """
    result=dict(points);delta=new_level-old_level
    endpoint=new_level if delta>0 else new_level+1
    rate=sp.get(endpoint) if 1<=endpoint<=95 else 0
    if rate is None:raise ValueError('缺少目标等级SP规则')
    for field in POINTS:
        if type(points.get(field)) is not int:raise ValueError('技能点存档不完整')
    for field in POINTS[:2]:result[field]=min(1073741823,max(0,points[field]+delta*rate))
    for field in POINTS[2:]:
        value=0 if new_level<=49 else points[field]+delta if old_level>50 else new_level-49
        if not 0<=value<=2147483647:raise ValueError('TP结果超出存档范围，请先核对技能点')
        result[field]=value
    return result


def signed_exp(value):
    if type(value) is not int or not 0<=value<=0xffffffff:raise ValueError('经验须为0至4294967295整数')
    return value if value<0x80000000 else value-0x100000000


def level_plan(info,points,new_level,new_exp,profiles,thresholds,sp):
    """Return immutable proposed fixed fields, without touching learned skills.

    Offline edit preserves quest rewards, skill blobs and extra attribute
    bonuses. Their game-native level events are deliberately NOT simulated.
    """
    first,second=decode_grow_type(info['grow_type'])
    if type(new_level) is not int or not 1<=new_level<=127:raise ValueError('目标等级须在角色字段范围内')
    lower=0 if new_level==1 else thresholds.get(new_level)
    upper=thresholds.get(new_level+1)
    if lower is None:raise ValueError('缺少目标等级经验阈值')
    if type(new_exp) is not int or new_exp<lower or (upper is not None and new_exp>upper):raise ValueError('目标经验不在该等级的PVF参考区间')
    # Unknown following threshold permits the known level's exact start only;
    # it does not invent a running server cap or an arbitrary max experience.
    if upper is None and new_exp!=lower:raise ValueError('下级阈值未知，仅能设置已知本级起点经验')
    old=baseline(profiles,info['lev'],first,second);new=baseline(profiles,new_level,first,second)
    output={**info,'lev':new_level,'exp':signed_exp(new_exp)}
    for key in STATS:
        value=info[key]+new[key]-old[key];lo,hi=LIMITS[key]
        if not lo<=value<=hi:raise ValueError(f'{key}成长结果超出数据库字段范围')
        output[key]=value
    try:resists=struct.unpack('<4h',bytes.fromhex(info['element_resist']))
    except (ValueError,struct.error,TypeError):raise ValueError('元素抗性存档不是8字节格式') from None
    values=[v+new[key]-old[key] for key,v in zip(RESISTS,resists)]
    if any(not -32768<=v<=32767 for v in values):raise ValueError('元素抗性成长结果超出存档范围')
    output['element_resist']=struct.pack('<4h',*values).hex()
    # Same-level experience correction must not trigger the native shortcut's
    # TP reset/normalization, and must not change already assigned skill points.
    updated_points=point_change(points,info['lev'],new_level,sp) if new_level!=info['lev'] else dict(points)
    return output,updated_points
