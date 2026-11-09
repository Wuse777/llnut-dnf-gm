"""Small, read-only character workbench; storage/appearance remain lazy reads."""
import time

from fastapi import HTTPException

from .character_detail import INFO_COLUMNS, ATTRIBUTES, decode_container, profession
from .service import character
from .mail_center import receipt_state


def one(cursor, sql, args=()):
    cursor.execute(sql, args)
    return cursor.fetchone()


def overview(service, charac_no):
    with service.db.connect() as connection, connection.cursor() as cursor:
        fields = ','.join('`' + key + '`' for key in INFO_COLUMNS)
        row = one(cursor, 'SELECT ' + fields + ',CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes '
                  'FROM taiwan_cain.charac_info WHERE charac_no=%s', (charac_no,))
        if not row:
            raise HTTPException(404, '角色不存在')
        row['uid'] = row.pop('m_id')
        row = character(row)
        owner = one(cursor, 'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s', (row['uid'],))
        online = one(cursor, 'SELECT login_status,m_channel_no AS channel FROM taiwan_login.login_account_3 WHERE m_id=%s', (row['uid'],))
        saved = one(cursor, 'SELECT money,coin,inventory_capacity,inventory,equipslot FROM taiwan_cain_2nd.inventory WHERE charac_no=%s', (charac_no,))
        play = one(cursor, 'SELECT exp,fatigue,used_fatigue,last_play_time FROM taiwan_cain.charac_stat WHERE charac_no=%s', (charac_no,))
        cursor.execute("SELECT status,COUNT(*) AS n FROM dnf_gm.support_cases WHERE uid=%s AND (charac_no=%s OR charac_no IS NULL) AND status IN ('open','in_progress') GROUP BY status", (row['uid'], charac_no))
        counts = {item['status']: item['n'] for item in cursor.fetchall()}
        cursor.execute("SELECT case_id,title,status,charac_no FROM dnf_gm.support_cases WHERE uid=%s AND (charac_no=%s OR charac_no IS NULL) AND status IN ('open','in_progress') ORDER BY updated_at DESC,case_id DESC LIMIT 5", (row['uid'], charac_no))
        cases = [{**item, 'scope': 'character' if item['charac_no'] else 'account'} for item in cursor.fetchall()]
        # The cap is visible: this is a recent attachment sample, never a mailbox total.
        cursor.execute('SELECT p.postal_id AS live_postal_id,p.receive_time,p.delete_flag FROM '
                       '(SELECT d.postal_id,b.created_at,b.operation_id,d.ordinal FROM dnf_gm.mail_batches b '
                       'JOIN dnf_gm.mail_deliveries d ON d.operation_id=b.operation_id '
                       'WHERE b.target_uid=%s AND b.charac_no=%s ORDER BY b.created_at DESC,b.operation_id DESC,d.ordinal DESC LIMIT 201) recent '
                       'LEFT JOIN taiwan_cain_2nd.postal p ON p.postal_id=recent.postal_id '
                       'ORDER BY recent.created_at DESC,recent.operation_id DESC,recent.ordinal DESC', (row['uid'], charac_no))
        deliveries = cursor.fetchall()
    equipment = decode_container(saved['equipslot'] if saved else None, True)
    backpack = decode_container(saved['inventory'] if saved else None)
    sample = backpack['items'][:6]
    labels = service.catalog.read_labels([key for item in equipment['items'] + sample for key in (item['id'], item.get('orb_id', 0))])
    for item in equipment['items'] + sample:
        metadata = labels['items'].get(item['id'])
        if metadata:
            item.update(metadata)
        item.update(name=metadata['name'] if metadata else f"未知物品 #{item['id']}", catalog_known=bool(metadata))
    art_sha = service.settings.pvf_sha256 if labels['state'] == 'ok' else ''
    service.catalog.assets.decorate(art_sha, equipment['items'] + sample)
    mail_counts = {state: 0 for state in ('unclaimed_marker', 'claimed_marker', 'deleted_marker', 'record_missing')}
    for item in deliveries[:200]:
        mail_counts[receipt_state(item)] += 1
    for key in ATTRIBUTES:
        row.pop(key, None)
    return {'character': row, 'account': owner, 'account_online': online, 'play_state': play,
            'profession': profession(row['job'], row['grow_type'], labels['jobs']),
            'portrait': service.catalog.assets.portrait(art_sha, row['job'], row['grow_type'], row['sex']),
            'wealth': {'state': 'ok' if saved else 'missing', 'gold': saved['money'] if saved else None,
                       'revival_coin_raw': saved['coin'] if saved else None,
                       'inventory_capacity_raw': saved['inventory_capacity'] if saved else None},
            'equipment': equipment, 'attributes': [], 'catalog_state': labels['state'],
            'backpack_summary': {'state': backpack['state'], 'message': backpack['message'],
                                 'occupied_slots': len(backpack['items']) if backpack['state'] == 'ok' else None,
                                 'slot_count': backpack['slot_count'], 'items': sample, 'has_more': len(backpack['items']) > 6},
            'support_summary': {'state': 'ok', 'open_count': counts.get('open', 0),
                                'in_progress_count': counts.get('in_progress', 0), 'items': cases},
            'mail_summary': {'state': 'ok', **mail_counts, 'checked_attachments': min(len(deliveries), 200),
                             'has_more': len(deliveries) > 200, 'scope': 'recent_200_attachments', 'client_verified': False},
            'collected_at': time.time(), 'read_only': True,
            'snapshot_note': '数据库存档快照；装备与背包不是实时战斗状态。邮件仅统计最近最多200条本后台投递附件，领取标记不等于客户端确认。'}
