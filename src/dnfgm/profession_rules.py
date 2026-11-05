"""Fixed-image advancement/awakening archive rules, not live job events."""
import re
import struct
from .progression_rules import PROGRAM_SHA,STATS,RESISTS,LIMITS,baseline,decode_grow_type

RULE_VERSION='qf1031-profession-1'


def names(tokens):
    """Keep per-growtype awakening names instead of flattening repeated tags."""
    base=[];awake={};first=None;tag=None;values=[]
    def flush():
        if tag=='[growtype name]':
            if base or any(not isinstance(v,str) or not v for v in values):raise ValueError('职业名称格式异常')
            base.extend(values)
        elif tag=='[awakening name]':
            if first is None or first in awake or len(values)>2 or any(not isinstance(v,str) or not v for v in values):raise ValueError('觉醒名称归属异常')
            awake[first]=list(values)
    for kind,value in tokens:
        if kind==5:
            flush();values=[];tag=None
            growth=re.fullmatch(r'\[growtype ([1-6])\]',str(value))
            if growth:first=int(growth[1])-1
            elif value in ('[growtype name]','[awakening name]'):tag=value
        elif tag:values.append(value)
    flush()
    if not base:raise ValueError('缺少基础职业名称')
    return base,awake


def choices(tokens,profiles):
    base,awake=names(tokens);rows=[]
    for first,second in sorted(profiles):
        if first<0:continue
        if not 0<=first<len(base) or not 0<=second<=2:raise ValueError('成长组合缺少名称或阶段未适配')
        label=base[first] if second==0 else awake.get(first,[])[second-1] if len(awake.get(first,[]))>=second else f'{base[first]} · {"一觉" if second==1 else "二觉"}（PVF未命名）'
        rows.append({'first':first,'second':second,'name':label,'branch':base[first],'stage':('未觉醒','一觉','二觉')[second],'code':first|(second<<4)})
    return {'base_name':base[0],'choices':rows}


def encode(previous,first,second):
    decode_grow_type(previous)
    if type(first) is not int or type(second) is not int or not 0<=first<=5 or not 0<=second<=2:raise ValueError('目标转职／觉醒代码无效')
    value=(previous&0x80)|first|(second<<4)
    return value if value<128 else value-256


def plan(info,first,second,profiles):
    old_first,old_second=decode_grow_type(info['grow_type'])
    if (first,second) not in profiles:raise ValueError('目标转职／觉醒不在当前PVF成长组合中')
    grow=encode(info['grow_type'],first,second)
    if grow==info['grow_type']:raise ValueError('目标职业阶段与当前相同，无需提交')
    before=baseline(profiles,info['lev'],old_first,old_second);after=baseline(profiles,info['lev'],first,second)
    result={**info,'grow_type':grow}
    for key in STATS:
        value=info[key]+after[key]-before[key];lo,hi=LIMITS[key]
        if not lo<=value<=hi:raise ValueError(f'{key}职业成长结果超出存档范围')
        result[key]=value
    try:resists=struct.unpack('<4h',bytes.fromhex(info['element_resist']))
    except (ValueError,TypeError,struct.error):raise ValueError('元素抗性存档格式异常') from None
    values=[v+after[key]-before[key] for key,v in zip(RESISTS,resists)]
    if any(not -32768<=v<=32767 for v in values):raise ValueError('职业元素抗性成长超出存档范围')
    result['element_resist']=struct.pack('<4h',*values).hex()
    return result
