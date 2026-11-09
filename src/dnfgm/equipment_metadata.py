"""PVF display metadata, not a compatibility oracle or a delivery policy."""
import json
import math
import re

PARTS = {'[weapon]':'武器','[title name]':'称号','[coat]':'上衣','[shoulder]':'头肩',
    '[pants]':'下装','[shoes]':'鞋','[waist]':'腰带','[amulet]':'项链','[wrist]':'手镯',
    '[ring]':'戒指','[support]':'辅助装备','[magic stone]':'魔法石',
    '[coat avatar]':'装扮上衣','[pants avatar]':'装扮下装','[hat avatar]':'装扮帽子',
    '[shoes avatar]':'装扮鞋','[hair avatar]':'装扮头发','[breast avatar]':'装扮胸部',
    '[face avatar]':'装扮脸部','[waist avatar]':'装扮腰部','[skin avatar]':'装扮皮肤'}
EFFECTS = {'[physical attack]':'物理攻击','[magical attack]':'魔法攻击',
    '[physical defense]':'物理防御','[magical defense]':'魔法防御',
    '[physical attack bonus]':'力量','[magical attack bonus]':'智力',
    '[physical defense bonus]':'体力','[magical defense bonus]':'精神',
    '[attack speed]':'攻击速度','[move speed]':'移动速度','[cast speed]':'施放速度',
    '[elemental property]':'攻击属性','[HP MAX]':'HP上限','[MP MAX]':'MP上限',
    '[all elemental resistance]':'所有属性抗性','[all elemental attack]':'所有属性强化',
    '[fire attack]':'火属性强化','[water attack]':'冰属性强化',
    '[light attack]':'光属性强化','[dark attack]':'暗属性强化',
    '[physical critical hit]':'物理暴击','[magical critical hit]':'魔法暴击'}
VALUES = {'[fire element]':'火属性','[water element]':'冰属性','[light element]':'光属性','[dark element]':'暗属性'}
JOB_NAMES = {'[all]':'不限职业','[swordman]':'鬼剑士','[fighter]':'格斗家（女）',
    '[gunner]':'神枪手（男）','[mage]':'魔法师（女）','[priest]':'圣职者',
    '[thief]':'暗夜使者','[at fighter]':'格斗家（男）','[at gunner]':'神枪手（女）',
    '[at mage]':'魔法师（男）','[at swordman]':'鬼剑士（女）',
    '[demonic swordman]':'黑暗武士','[creator mage]':'缔造者'}
# These labels translate explicit PVF directory codes, never an item name.
WEAPON_NAMES = {'ssword':'短剑','katana':'太刀','club':'钝器','lsword':'巨剑','beamsword':'光剑',
    'knuckle':'手套','gauntlet':'臂铠','claw':'爪','tonfa':'东方棍','boxingglove':'拳套',
    'revolver':'左轮枪','automatic':'自动手枪','auto':'自动手枪','musket':'步枪','hcannon':'手炮','bowgun':'手弩',
    'spear':'矛','pole':'棍棒','rod':'魔杖','staff':'法杖','broom':'扫把',
    'cross':'十字架','rosary':'念珠','totem':'图腾','axe':'战斧','scythe':'镰刀',
    'dagger':'匕首','twinsword':'双剑','wand':'权杖'}


def fields(tokens):
    result={};key=None
    for kind,value in tokens:
        if kind==5 and isinstance(value,str):key=value;result.setdefault(key,[])
        elif key is not None:result[key].append(value)
    return result


def enchant_definition(tokens):
    """Only an explicit, terminated enchant section qualifies; names don't."""
    active=False;ended=False;tag=None;effects=[]
    for kind,value in tokens:
        if kind==5 and value=='[enchant]':
            if active or ended:raise ValueError('Duplicate enchant section')
            active=True
        elif kind==5 and value=='[/enchant]' and active:
            active=False;ended=True
        elif active and kind==5:
            if not isinstance(value,str) or len(value)>120:raise ValueError('Invalid effect tag')
            tag={'tag':value,'label':EFFECTS.get(value,value),'values':[]};effects.append(tag)
        elif active and tag is not None:
            if isinstance(value,str):value=value[:240]
            elif type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Unknown effect value')
            tag['values'].append(value)
            if len(tag['values'])>32:raise ValueError('Oversized effect')
        elif active:raise ValueError('Unlabelled enchant values')
        if len(effects)>64:raise ValueError('Oversized enchant section')
    if active:raise ValueError('Unterminated enchant section')
    if not ended or not effects:return None
    data=fields(tokens)
    targets=[v for v in data.get('[string data]',[]) if isinstance(v,str) and v.startswith('[') and v.endswith(']') and len(v)<=120]
    targets=list(dict.fromkeys(targets))
    summary='；'.join(e['label']+' '+', '.join(str(VALUES.get(v,v)) if isinstance(v,str) else str(v) for v in e['values']) for e in effects)
    return {'targets':targets,'target_names':[PARTS.get(v,v) for v in targets],'effects':effects,'summary':summary}


def equipment_definition(tokens):
    data=fields(tokens);kind=data.get('[equipment type]',[])
    if not kind or not isinstance(kind[0],str):return None
    rarity=data.get('[rarity]',[])
    return {'part_code':kind[0],'part_name':PARTS.get(kind[0],kind[0]),
        'rarity':rarity[0] if rarity and type(rarity[0]) is int else None}


def filter_definition(tokens, source_path='', item_id=None):
    """Unambiguous declared jobs/set identity and the explicit weapon directory.

    Nested effects cannot replace an equipment's applicability. Unknown codes
    remain literal; this metadata does not establish that a character can equip
    an item. Malformed or repeated sections are omitted rather than guessed.
    """
    tokens=list(tokens)
    wanted={'[usable job]','[equipment type]','[set item master]','[set name]'}
    headers=[v for kind,v in tokens if kind==5 and isinstance(v,str)]
    paired={'['+v[2:] for v in headers if v.startswith('[/') and v.endswith(']')}
    if any(v in {'[enchant]','[if]','[then]','[else]','[condition]','[random]'} and v not in paired for v in headers):
        return {'job_codes':[],'weapon_type':'','set_id':None,'set_name':''}
    stack=[];data={};repeated=set();key=None;key_depth=0
    for kind,value in tokens:
        if kind==5:
            key=None
            if not isinstance(value,str):return {'job_codes':[],'weapon_type':'','set_id':None,'set_name':''}
            if value.startswith('[/') and value.endswith(']'):
                if not stack or stack.pop()!='['+value[2:]:
                    return {'job_codes':[],'weapon_type':'','set_id':None,'set_name':''}
            else:
                if not stack and value in wanted:
                    if value in data:repeated.add(value)
                    else:data[value]=[]
                    key=value;key_depth=int(value in paired)
                if value in paired:stack.append(value)
        elif key is not None and len(stack)==key_depth:
            data[key].append(value)
    if stack:return {'job_codes':[],'weapon_type':'','set_id':None,'set_name':''}
    for tag in repeated:data.pop(tag,None)
    raw=data.get('[usable job]',[])
    jobs=list(dict.fromkeys(raw)) if len(raw)<=32 and all(isinstance(v,str) and re.fullmatch(r'\[[a-z][a-z0-9 _-]{0,77}\]',v) for v in raw) else []
    master=data.get('[set item master]',[]);names=data.get('[set name]',[])
    name=names[0].strip() if len(names)==1 and isinstance(names[0],str) and len(names[0])<=160 and not any(ord(v)<32 for v in names[0]) else ''
    set_id=master[0] if len(master)==1 and type(master[0]) is int and 0<master[0]<=4294967295 else None
    # A master item declares the set name; members point to that exact item ID.
    if not master and name and type(item_id) is int and 0<item_id<=4294967295:set_id=item_id
    match=re.fullmatch(r'equipment/character/[a-z0-9 _-]+/weapon/([a-z0-9_-]{1,40})/[^\x00]*\.equ',source_path.lower().replace('\\','/'))
    kind=data.get('[equipment type]',[])
    weapon=match[1] if match and kind and kind[0]=='[weapon]' else ''
    return {'job_codes':jobs,'weapon_type':weapon,'set_id':set_id,'set_name':name}


def attribute_definition(tokens):
    """Only unambiguous top-level values, excluding explicitly paired sections.

    PVF scalar tags have no closing marker. Discover paired sections before
    reading values, then omit their entire contents (including unknown nested
    sections). Known conditional/enchant openers without a closing marker and
    malformed nesting invalidate the extraction. Repeated top-level attributes
    are omitted instead of being added, merged or silently taking the last one.
    This is a bounded source projection, not a full PVF expression evaluator.
    """
    tokens=list(tokens)
    headers=[value for kind,value in tokens if kind==5 and isinstance(value,str)]
    paired={'['+value[2:] for value in headers if value.startswith('[/') and value.endswith(']')}
    conditional={'[enchant]','[if]','[then]','[else]','[condition]','[random]'}
    if any(value in conditional and value not in paired for value in headers):return []
    stack=[];data={};repeated=set();key=None
    for kind,value in tokens:
        if kind==5:
            key=None
            if not isinstance(value,str):return []
            if value.startswith('[/') and value.endswith(']'):
                opening='['+value[2:]
                if not stack or stack.pop()!=opening:return []
            elif value in paired:
                stack.append(value)
            elif not stack and value in EFFECTS:
                if value in data:repeated.add(value)
                else:data[value]=[]
                key=value
        elif not stack and key is not None:
            data[key].append(value)
    if stack:return []
    result=[]
    for tag,label in EFFECTS.items():
        values=data.get(tag,[])
        if tag not in repeated and values and len(values)<=16 and all(type(v) in (int,float) and math.isfinite(v) for v in values):
            result.append({'tag':tag,'label':label,'values':values})
    return result


def read_metadata(connection,labels):
    """Optional enrichment: older indexes retain their original functionality."""
    tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('equipment_details','equipment_attributes','enchantments','equipment_filter_details','equipment_jobs')")}
    filter_version=connection.execute("SELECT value FROM metadata WHERE key='equipment_filters_version'").fetchone()
    filters_verified=bool(filter_version and filter_version[0]=='1' and {'equipment_filter_details','equipment_jobs'}<=tables)
    attribute_version=connection.execute("SELECT value FROM metadata WHERE key='equipment_attributes_version'").fetchone() if 'equipment_attributes' in tables else None
    attributes_verified=bool(attribute_version and attribute_version[0]=='2')
    ids=list(labels)
    for start in range(0,len(ids),400):
        batch=ids[start:start+400];marks=','.join('?' for _ in batch)
        if 'equipment_details' in tables:
            for r in connection.execute(f'SELECT * FROM equipment_details WHERE item_id IN ({marks})',batch):
                labels[r['item_id']].update(part_code=r['part_code'],part_name=PARTS.get(r['part_code'],r['part_code']),rarity=r['rarity'])
        if filters_verified:
            for r in connection.execute(f'SELECT * FROM equipment_filter_details WHERE item_id IN ({marks})',batch):
                labels[r['item_id']].update(weapon_type=r['weapon_type'],weapon_type_name=WEAPON_NAMES.get(r['weapon_type'],r['weapon_type']),set_id=r['set_id'],set_name=r['set_name'],usable_jobs=[])
            for r in connection.execute(f'SELECT item_id,job_code FROM equipment_jobs WHERE item_id IN ({marks}) ORDER BY item_id,job_code',batch):
                labels[r['item_id']].setdefault('usable_jobs',[]).append({'code':r['job_code'],'name':JOB_NAMES.get(r['job_code'],r['job_code'])})
        if attributes_verified:
            for r in connection.execute(f'SELECT * FROM equipment_attributes WHERE item_id IN ({marks})',batch):
                labels[r['item_id']]['base_attributes']=json.loads(r['attributes_json'])
        if 'enchantments' in tables:
            for r in connection.execute(f'SELECT * FROM enchantments WHERE item_id IN ({marks})',batch):
                labels[r['item_id']]['enchantment_definition']=decode_enchantment(r)


def decode_enchantment(row):
    targets=json.loads(row['targets_json'])
    return {'targets':targets,'target_names':[PARTS.get(v,v) for v in targets],
        'effects':json.loads(row['effects_json']),'summary':row['summary']}


def enchantment(labels,item_id):
    if not item_id:return {'id':0,'name':'无附魔','known':True,'definition_known':False}
    row=labels.get(item_id)
    return {'id':item_id,'name':row['name'] if row else f'未识别附魔 #{item_id}',
        'known':row is not None,'definition_known':bool(row and row.get('enchantment_definition')),
        **(row.get('enchantment_definition',{}) if row else {})}
