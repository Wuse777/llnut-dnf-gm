"""Verified character dates and account tags, shared by campaigns and rewards.

Dates use the game's persisted calendar values. They are not account registration
dates, live session clocks, or a promise that a returning player has logged in.
"""
from datetime import date
from fastapi import HTTPException

DATE_COLUMNS = (('charac_info', 'create_time'), ('charac_info', 'last_play_time'),
                ('charac_stat', 'last_play_time'))


def schema(q):
    q.execute("SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS "
              "WHERE TABLE_SCHEMA='taiwan_cain' AND ((TABLE_NAME='charac_info' AND "
              "COLUMN_NAME IN ('create_time','last_play_time')) OR "
              "(TABLE_NAME='charac_stat' AND COLUMN_NAME='last_play_time'))")
    found = {(r['TABLE_NAME'], r['COLUMN_NAME']): r['DATA_TYPE'] for r in q.fetchall()}
    available = all(found.get(key) == 'datetime' for key in DATE_COLUMNS)
    if available:
        try:
            q.execute('SELECT c.create_time,c.last_play_time,s.last_play_time FROM '
                      'taiwan_cain.charac_info c LEFT JOIN taiwan_cain.charac_stat s '
                      'ON s.charac_no=c.charac_no LIMIT 0')
        except Exception:
            available = False
    return {
        'character_dates': {'available': available, 'source': 'charac_info / charac_stat',
            'note': '角色创建日期、两处最后游玩存档的较新值；按游戏存档日历筛选，零日期未知。'
                    if available else '角色日期字段类型或只读权限未核实，日期筛选不可用。'},
        'account_registration': {'available': False, 'note': '未适配账号注册时间；角色创建日不是账号注册日。'},
        'tags': {'available': True, 'source': 'GM账号备注标签', 'match': 'all'},
        'returning': {'available': available, 'note': '最后游玩早于截止日且登录表明确离线；不是完整登录历史。'},
    }


def verify(q, filters):
    if any(filters.get(k) for k in ('created_from', 'created_to', 'inactive_before')):
        if not schema(q)['character_dates']['available']:
            raise HTTPException(409, '角色日期字段类型或权限未核实，不能使用新建／回归筛选')


def predicates(filters):
    clauses, args = [], []
    for tag in filters.get('tags_all', []):
        clauses.append('EXISTS (SELECT 1 FROM dnf_gm.player_profiles profile '
                       "WHERE profile.uid=c.m_id AND JSON_CONTAINS("
                       "IF(JSON_VALID(profile.tags_json),profile.tags_json,'[]'),JSON_QUOTE(%s)))")
        args.append(tag)
    for name, op in (('created_from', '>='), ('created_to', '<=')):
        if filters.get(name):
            value = date.fromisoformat(str(filters[name]))
            clauses.append("c.create_time>'0000-00-00 00:00:00'")
            # DATE() deliberately compares the game's calendar, without guessing timezone.
            clauses.append('DATE(c.create_time)' + op + '%s')
            args.append(value.isoformat())
    if filters.get('inactive_before'):
        value = date.fromisoformat(str(filters['inactive_before']))
        latest = "GREATEST(c.last_play_time,COALESCE((SELECT s.last_play_time FROM " \
                 "taiwan_cain.charac_stat s WHERE s.charac_no=c.charac_no),'0000-00-00 00:00:00'))"
        clauses.extend([latest + ">'0000-00-00 00:00:00'", latest + '<%s', 'l.login_status=0'])
        args.append(value.isoformat() + ' 00:00:00')
    return clauses, args
