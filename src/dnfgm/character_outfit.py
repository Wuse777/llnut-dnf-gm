"""Read the verified equipped avatar region without interpreting bag ownership.

Native evidence and unsupported appearance modifiers are documented in
docs/CHARACTER-APPEARANCE.md. This module never modifies game records.
"""
import pymysql
from .outfit_recipe import AVATAR_SLOTS, OutfitRecipeError, canonical_outfit_recipe


def unavailable(note='未获时装存档列读取权限或目标数据库版本不支持；其余角色资料仍可查看'):
    return {'state':'unavailable','items':[],'note':note}


def read_saved_outfit(q, charac_no, uid, *, deleted=False):
    if deleted:
        return unavailable('角色已删除，不读取其穿戴时装')
    try:
        q.execute('SELECT a.slot,a.it_id,a.clear_avatar_id,a.color1,a.color2 '
                  'FROM taiwan_cain_2nd.user_items a '
                  'JOIN taiwan_cain.charac_info c ON c.charac_no=a.charac_no '
                  'WHERE a.charac_no=%s AND c.m_id=%s AND c.delete_flag=0 '
                  'AND a.slot BETWEEN 0 AND 9 AND a.stat=0 AND a.expire_date>NOW() '
                  'ORDER BY a.slot LIMIT 11', (charac_no, uid))
        rows=q.fetchall()
    except pymysql.MySQLError:
        return unavailable()
    return validate_saved_rows(rows)


def validate_saved_rows(rows):
    if not isinstance(rows,(list,tuple)) or len(rows)>10:
        return {'state':'unsupported','items':[],'note':'穿戴时装记录超出已核实的十个槽位，无法确认完整外观'}
    seen=set();items=[]
    for row in rows:
        if (not isinstance(row,dict) or
            any(type(row.get(k)) is not int for k in ('slot','it_id','clear_avatar_id','color1','color2')) or
            not 0<=row['slot']<=9 or not 1<=row['it_id']<=0x7fffffff or row['slot'] in seen):
            return {'state':'unsupported','items':[],'note':'穿戴时装存在重复槽位或未知记录，无法确认完整外观'}
        if row['clear_avatar_id'] or row['color1'] or row['color2']:
            return {'state':'unsupported','items':[],'note':'穿戴时装含透明替代或染色标识，尚不支持最终外观解析'}
        seen.add(row['slot']);items.append({'stored_slot':row['slot'],'id':row['it_id']})
    return {'state':'pending' if items else 'empty','items':items,
            'note':'数据库穿戴时装存档；在线变化可能尚未保存' if items else '当前未读取到有效的穿戴时装存档'}


def resolve_saved_outfit(saved, job, labels):
    """Part identities come from exact PVF metadata, never database slot order."""
    if saved['state']!='pending':
        return saved
    if labels['state']!='ok':
        return unavailable('PVF索引缺失或指纹不匹配，无法确认穿戴时装部位')
    items=[];parts=set()
    for record in saved['items']:
        metadata=labels['items'].get(record['id'],{})
        part=metadata.get('part_code')
        if part not in AVATAR_SLOTS or part in parts:
            return {'state':'unsupported','items':[],
                    'note':'穿戴时装含未知或重复PVF部位，无法确认完整外观'}
        parts.add(part);items.append({'slot':part,'id':record['id']})
    try:
        recipe,sha=canonical_outfit_recipe(job,items)
    except OutfitRecipeError:
        return {'state':'unsupported','items':[],'note':'基础职业或装扮配方无法确认'}
    return {'state':'ok','items':recipe['items'],'recipe_sha256':sha,
            'note':'已按穿戴存档及PVF部位核实配方；不含武器、染色、透明替代及在线变化'}
