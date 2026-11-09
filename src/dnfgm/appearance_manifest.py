"""Bounded public appearance v2 contract. No client parsers or game writes."""
import json
import re

from .outfit_recipe import AVATAR_SLOTS

SHA=re.compile(r'^[a-f0-9]{64}$')
ACTIONS=('idle','walk','attack')
MAX_DECODED_BYTES=64*1024*1024
REASONS={
 'character_deleted':'角色已删除',
 'appearance_read_unavailable':'缺少时装身份列读取权限，或当前数据库版本不支持',
 'avatar_region_overflow':'时装区域记录超过已核实的115个位置',
 'avatar_record_invalid':'时装记录格式无法确认',
 'avatar_identity_ambiguous':'时装槽位或实例身份重复',
 'clear_reference_missing':'透明装扮没有唯一有效的同角色背包来源',
 'clear_reference_nested':'尚未确认嵌套透明装扮的显示规则',
 'clear_source_dye_unverified':'透明来源含染色，覆盖顺序尚未核实',
 'avatar_part_unverified':'时装PVF部位未知、冲突或透明来源部位不匹配',
 'catalog_mismatch':'物品索引与当前PVF不匹配',
 'appearance_identity_invalid':'外观配方身份无法确认',
 'dye_pixel_rule_unverified':'已识别染色标识；客户端掩码混色公式尚未核实',
 'weapon_rule_unverified':'存档武器的部分动作或武器装扮尚未适配',
 'weapon_effect_unverified':'武器强化、锻造、幻化与发光特效尚未完整适配',
 'aura_rule_unverified':'尚未绘制存档光环与其特效',
 'avatar_effect_unverified':'已绘制时装基础层；特殊发光／混色图层尚未绘制',
 'profession_layer_unverified':'尚未绘制转职／觉醒常驻附加层',
 'visibility_rule_unverified':'尚未确认客户端部位隐藏开关',
 'appearance_pack_missing':'尚未安装匹配的部件动画包',
 'appearance_part_missing':'该动作缺少实际穿戴部件，未替换成默认装扮',
 'appearance_motion_unsupported':'该动作包含尚未适配的时间线或视觉变换',
 'appearance_manifest_invalid':'外观清单损坏或超出资源预算',
 'client_attack_missing':'该职业CHR未定义站立普通攻击',
}


def failure(saved,code=None):
    codes=list(saved.get('reason_codes',[]))
    if code and code not in codes:codes.append(code)
    return {'version':2,'state':saved.get('state','unavailable'),'source_kind':'saved_avatar_layers',
            'complete':False,'client_verified':False,'actions':{},'atlases':[],
            'reason_codes':codes,'reasons':[REASONS.get(c,'当前外观暂不可解析') for c in codes],
            'coverage':[],'note':'数据库外观存档；在线变化可能尚未保存'}


def integer(value,lo,hi):
    if type(value) is not int or not lo<=value<=hi:raise ValueError('Appearance integer outside budget')
    return value


def validate_clip(payload,atlases):
    """Validate every draw, including invisible frames, before browser delivery."""
    if not isinstance(payload,dict) or set(payload)!={'loop','duration_ms','frames'} or type(payload['loop']) is not bool:
        raise ValueError('Invalid appearance clip')
    duration=integer(payload['duration_ms'],1,10000);frames=payload['frames']
    if not isinstance(frames,list) or not 1<=len(frames)<=120:raise ValueError('Appearance frame budget')
    total=0
    for frame in frames:
        if not isinstance(frame,dict) or set(frame)!={'duration_ms','draws'}:raise ValueError('Invalid appearance frame')
        total+=integer(frame['duration_ms'],1,10000)
        if not isinstance(frame['draws'],list) or len(frame['draws'])>64:raise ValueError('Appearance layer budget')
        for draw in frame['draws']:
            if not isinstance(draw,dict) or set(draw)!={'atlas','sx','sy','width','height','x','y','z'}:
                raise ValueError('Invalid appearance draw')
            key=draw['atlas']
            if not isinstance(key,str) or not SHA.fullmatch(key) or key not in atlases:raise ValueError('Unregistered appearance atlas')
            page=atlases[key]
            w=integer(draw['width'],1,512);h=integer(draw['height'],1,512)
            integer(draw['sx'],0,page['width']-w);integer(draw['sy'],0,page['height']-h)
            integer(draw['x'],-256,256-w);integer(draw['y'],-448,64-h)
            integer(draw['z'],-10000,10000)
    if total!=duration:raise ValueError('Appearance duration mismatch')
    return payload


def merge_clips(clips):
    """Merge exact component timelines; never reuse body frame IDs for clothes."""
    if not clips:raise ValueError('No appearance components')
    duration=clips[0]['duration_ms'];loop=clips[0]['loop'];points={0,duration};prepared=[]
    for clip in clips:
        if clip['duration_ms']!=duration or clip['loop']!=loop:raise ValueError('Appearance timeline mismatch')
        offset=0;segments=[]
        for frame in clip['frames']:
            segments.append((offset,offset+frame['duration_ms'],frame['draws']))
            offset+=frame['duration_ms'];points.add(offset)
        prepared.append(segments)
    points=sorted(points)
    if len(points)>121:raise ValueError('Appearance merged frame budget')
    frames=[]
    for start,end in zip(points,points[1:]):
        draws=[]
        for segments in prepared:
            draws.extend(next(d for a,b,d in segments if a<=start<b))
        if len(draws)>64:raise ValueError('Appearance merged layer budget')
        frames.append({'duration_ms':end-start,'draws':sorted(draws,key=lambda d:d['z'])})
    return {'loop':loop,'duration_ms':duration,'frames':frames}


def assemble(c,pvf_sha,saved):
    if saved.get('state')!='ok':return failure(saved)
    result=failure(saved);recipe=saved['recipe'];job=recipe['job'];result['recipe_sha256']=saved['recipe_sha256'];result['recipe']=recipe
    if dict(c.execute('SELECT key,value FROM metadata')).get('appearance_version')!='2':
        result.update(state='missing');return {**result,**failure({'state':'missing'},'appearance_pack_missing')}
    pages={}
    for row in c.execute('SELECT sha256,width,height,bytes FROM appearance_atlases'):
        key=row['sha256']
        if not isinstance(key,str) or not SHA.fullmatch(key):raise ValueError('Invalid atlas identity')
        pages[key]={'sha256':key,'width':integer(row['width'],1,2048),'height':integer(row['height'],1,2048),
                    'bytes':integer(row['bytes'],33,16*1024*1024),
                    'url':f'/dnf-gm/api/v1/assets/{pvf_sha}/{key}.atlas.png'}
    used=set();coverage=[];selected={i['slot']:i['id'] for i in recipe['items']};weapon_actions=[]
    for action in ACTIONS:
        clips=[];action_reason=None;partial_effect=False
        for slot in sorted(AVATAR_SLOTS):
            item_id=selected.get(slot,0)
            row=c.execute('SELECT state,payload_json FROM appearance_parts WHERE job=? AND slot=? AND item_id=? AND action=?',
                          (job,slot,item_id,action)).fetchone()
            if row is None:action_reason='appearance_part_missing';break
            if row['state'] not in ('ready','partial'):action_reason='appearance_motion_unsupported';break
            partial_effect=partial_effect or row['state']=='partial'
            if not isinstance(row['payload_json'],str) or len(row['payload_json'])>512*1024:raise ValueError('Appearance component budget')
            clips.append(validate_clip(json.loads(row['payload_json']),pages))
        if action_reason:
            coverage.append({'component':action,'state':'unsupported','reason_code':action_reason,'note':REASONS[action_reason]});continue
        if recipe['weapon_id']:
            row=c.execute('SELECT state,payload_json FROM appearance_parts WHERE job=? AND slot=? AND item_id=? AND action=?',
                          (job,'[weapon]',recipe['weapon_id'],action)).fetchone()
            if row is not None and row['state'] in ('ready','partial'):
                if not isinstance(row['payload_json'],str) or len(row['payload_json'])>512*1024:raise ValueError('Appearance weapon budget')
                weapon_clip=validate_clip(json.loads(row['payload_json']),pages)
                if weapon_clip['duration_ms']==clips[0]['duration_ms'] and weapon_clip['loop']==clips[0]['loop']:
                    clips.append(weapon_clip);weapon_actions.append(action)
        merged=merge_clips(clips);validate_clip(merged,pages)
        action_pages={d['atlas'] for frame in merged['frames'] for d in frame['draws']}
        if sum(pages[key]['width']*pages[key]['height']*4 for key in action_pages)>MAX_DECODED_BYTES:
            coverage.append({'component':action,'state':'unsupported','reason_code':'appearance_manifest_invalid','note':'当前动作超过64 MiB图集预算'});continue
        result['actions'][action]=merged;used.update(action_pages)
        coverage.append({'component':action,'state':'ready','note':'按存档实际部件与各自ANI时间线合成'})
        if partial_effect:coverage.append({'component':action+'_effects','state':'partial','reason_code':'avatar_effect_unverified','note':REASONS['avatar_effect_unverified']})
    codes=[]
    if any(row.get('reason_code')=='avatar_effect_unverified' for row in coverage):codes.append('avatar_effect_unverified')
    if recipe['weapon_id']:
        if len(weapon_actions)!=len(result['actions']):codes.append('weapon_rule_unverified')
        codes.append('weapon_effect_unverified')
        weapon_state=('ready' if len(weapon_actions)==len(result['actions']) else 'partial') if weapon_actions else 'unsupported'
        coverage.append({'component':'base_weapon','state':weapon_state,
                         'note':'已绘制存档基础武器：'+', '.join(weapon_actions) if weapon_actions else REASONS['weapon_rule_unverified']})
    if recipe.get('aura_id'):codes.append('aura_rule_unverified')
    if recipe['grow_type']&15:codes.append('profession_layer_unverified')
    codes.append('visibility_rule_unverified')
    coverage.extend([{'component':'transparent_avatar','state':'ready','note':'已解析同角色有效背包身份关联' if saved.get('clear_applied') else '无透明替代标识'},
                     {'component':'dye','state':'ready','note':'当前穿戴无染色标识'}])
    coverage.extend({'component':code,'state':'unsupported','reason_code':code,'note':REASONS[code]} for code in codes)
    result.update(state='partial' if result['actions'] else 'missing',complete=False,coverage=coverage,
                  atlases=[pages[key] for key in sorted(used)],reason_codes=codes,
                  reasons=[REASONS[c] for c in codes],canvas={'width':512,'height':512,'anchor_x':256,'anchor_y':448},
                  note='实际时装存档的部件动作预览；未覆盖项目见下方清单，不代表完整或在线外观')
    return result
