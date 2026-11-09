"""Immutable delivery ledger and bounded read-only receipt queries.

A missing game row is unknown, not evidence of successful receipt. Pagination
uses ledger ordinals so deletions by the game cannot hide historic deliveries.
"""
import json
from datetime import datetime, timedelta, timezone
from .mail_content import mail_text
from fastapi import HTTPException
from pymysql.err import OperationalError


RECENT_LIMIT = 200


def search_read(cursor, sql, args=()):
    try:
        cursor.execute(sql, args)
    except OperationalError as error:
        if error.args and error.args[0] in (3024, 2013, 2006):
            raise HTTPException(503, '邮件检索未完成，结果未知；请稍后重试或缩小筛选范围') from None
        raise


def receipt_state(row):
    if row.get('live_postal_id') is None:
        return 'record_missing'
    received = row.get('receive_time')
    if received and not str(received).startswith('0000-00-00'):
        return 'claimed_marker'
    if row.get('delete_flag'):
        return 'deleted_marker'
    return 'unclaimed_marker'


class MailCenter:
    def __init__(self, db, catalog=None):
        self.db, self.catalog = db, catalog

    def list(self, uid=0, charac_no=0, operation_id='', page=1, *, text='', item_id=0,
             template_id=0, receipt='', created_from=None, created_to=None):
        predicates, args = [], []
        for column, value in [('target_uid', uid), ('charac_no', charac_no), ('operation_id', operation_id)]:
            if value:
                predicates.append('b.' + column + '=%s')
                args.append(value)
        if text:
            term = '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            predicates.append('(b.account_name LIKE %s OR b.character_name LIKE %s)')
            args.extend([term, term])
        if item_id:
            predicates.append('EXISTS (SELECT 1 FROM dnf_gm.mail_deliveries d WHERE d.operation_id=b.operation_id AND d.item_id=%s)')
            args.append(item_id)
        if template_id:
            predicates.append("CAST(JSON_UNQUOTE(JSON_EXTRACT(b.request_json,'$.template_id')) AS UNSIGNED)=%s")
            args.append(template_id)
        if created_from and created_to and created_from > created_to:
            raise HTTPException(422, '开始日期不能晚于结束日期')
        for value, operator, offset in ((created_from, '>=', 0), (created_to, '<', 1)):
            if value:
                stamp = datetime.fromisoformat(str(value)).replace(tzinfo=timezone(timedelta(hours=8))) + timedelta(days=offset)
                predicates.append('b.created_at' + operator + '%s')
                args.append(stamp.astimezone(timezone.utc).replace(tzinfo=None))
        receipt_predicates = {
            'claimed_marker': "p.postal_id IS NOT NULL AND p.receive_time IS NOT NULL AND p.receive_time<>'0000-00-00 00:00:00'",
            'unclaimed_marker': "p.postal_id IS NOT NULL AND (p.receive_time IS NULL OR p.receive_time='0000-00-00 00:00:00') AND COALESCE(p.delete_flag,0)=0",
            'deleted_marker': "p.postal_id IS NOT NULL AND (p.receive_time IS NULL OR p.receive_time='0000-00-00 00:00:00') AND p.delete_flag<>0",
            'record_missing': 'p.postal_id IS NULL',
        }
        if receipt:
            if receipt not in receipt_predicates:
                raise HTTPException(422, '未知的领取标记筛选')
            # The 200th newest ordinal is an indexed scalar lookup. Unlike a
            # count-based cutoff it also works for imported ledgers with gaps.
            cutoff = ('COALESCE((SELECT recent.ordinal FROM dnf_gm.mail_deliveries recent '
                      'WHERE recent.operation_id=b.operation_id ORDER BY recent.ordinal DESC LIMIT 1 OFFSET 199),0)')
            clause = ('EXISTS (SELECT 1 FROM dnf_gm.mail_deliveries d LEFT JOIN taiwan_cain_2nd.postal p '
                      'ON p.postal_id=d.postal_id WHERE d.operation_id=b.operation_id AND d.ordinal>=' + cutoff +
                      ' AND (' + receipt_predicates[receipt] + ') LIMIT 1)')
            predicates.append('(b.history_complete=0 OR b.recorded_count<b.postal_count OR ' + clause + ')' if receipt == 'record_missing' else clause)
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        with self.db.connect() as c, c.cursor() as q:
            search_read(q, 'SELECT b.operation_id,b.target_uid,b.charac_no,b.account_name,b.character_name,b.letter_id,'
                      'b.postal_count,b.recorded_count,b.history_complete,b.message,b.created_at '
                      'FROM dnf_gm.mail_batches b' + where +
                      ' ORDER BY b.created_at DESC,b.operation_id DESC LIMIT 51 OFFSET %s', (*args, (page-1)*50))
            rows = q.fetchall()
            visible = rows[:50]
            if visible:
                sample = ('SELECT operation_id,ordinal,postal_id FROM dnf_gm.mail_deliveries '
                          'WHERE operation_id=%s ORDER BY ordinal DESC LIMIT 201')
                samples = (' UNION ALL '.join('(' + sample + ')' for _ in visible)
                           if len(visible) > 1 else sample)
                # At most 50 * 201 rows; the extra row only proves truncation.
                search_read(q, 'SELECT d.operation_id,d.ordinal,p.postal_id AS live_postal_id,p.receive_time,p.delete_flag '
                    'FROM (' + samples + ') d LEFT JOIN taiwan_cain_2nd.postal p ON p.postal_id=d.postal_id '
                    'ORDER BY d.operation_id,d.ordinal DESC', tuple(row['operation_id'] for row in visible))
                summaries = {}
                for item in q.fetchall():
                    summaries.setdefault(item['operation_id'], []).append(item)
                for row in visible:
                    sample_rows = summaries.get(row['operation_id'], [])
                    summary = {state: 0 for state in receipt_predicates}
                    for item in sample_rows[:RECENT_LIMIT]:
                        summary[receipt_state(item)] += 1
                    row['receipt_summary'] = {**summary, 'scope': 'recent_200_attachments', 'recent_limit': RECENT_LIMIT,
                        'checked_attachments': min(len(sample_rows), RECENT_LIMIT), 'has_more': len(sample_rows) > RECENT_LIMIT,
                        'unrecorded': max(0, row['postal_count'] - row['recorded_count']), 'client_verified': False}
        return {'items': rows[:50], 'page': page, 'has_more': len(rows)>50, 'receipt_scope': 'recent_200_attachments'}

    def details(self, operation_id, after=0):
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT * FROM dnf_gm.mail_batches WHERE operation_id=%s', (operation_id,))
            batch = q.fetchone()
            if not batch:
                raise HTTPException(404, '邮件操作不存在或历史记录尚未导入')
            batch['request'] = json.loads(batch.pop('request_json'))
            q.execute('SELECT d.ordinal,d.postal_id,d.item_id,d.quantity,d.gold,'
                      'p.postal_id AS live_postal_id,p.receive_time,p.delete_flag '
                      'FROM dnf_gm.mail_deliveries d LEFT JOIN taiwan_cain_2nd.postal p '
                      'ON p.postal_id=d.postal_id WHERE d.operation_id=%s AND d.ordinal>%s '
                      'ORDER BY d.ordinal LIMIT 51', (operation_id, after))
            records = q.fetchall()
        more = len(records)>50
        records = records[:50]
        for row in records:
            row['receipt_state'] = receipt_state(row)
            row.pop('live_postal_id')
        catalog_state = 'unavailable'
        if self.catalog is not None:
            labels = self.catalog.read_labels([row['item_id'] for row in records])
            catalog_state = labels['state']
            images = []
            for row in records:
                metadata = labels['items'].get(row['item_id'], {})
                row['item'] = {**metadata, 'id': row['item_id'],
                               'name': metadata.get('name') or ('纯金币' if not row['item_id'] else '名称未收录')}
                images.append(row['item'])
            self.catalog.assets.decorate(self.catalog.settings.pvf_sha256 if catalog_state == 'ok' else '', images)
        return {'batch': batch, 'items': records, 'next_after': records[-1]['ordinal'] if more else None,
                'catalog_state': catalog_state,
                'client_verified': False,
                'note': '领取状态仅为数据库标记；记录消失不表示已领取。历史记录不完整时不推算缺失附件。'}

    def import_history(self, after_id=0, limit=50):
        """Explicit maintenance action; imports only committed GM mail evidence.

        A historical result truncates IDs at 20. Look up remaining live rows by
        recipient AND letter, not a guessed contiguous range of postal IDs.
        Deleted historic rows cannot be reconstructed and remain explicitly unknown.
        """
        imported = 0
        with self.db.connect() as c, c.cursor() as q:
            q.execute("SELECT id,operation_id,request_json,result_json,created_at FROM dnf_gm.audit WHERE id>%s AND action='mail' ORDER BY id LIMIT %s", (after_id,limit))
            audits = q.fetchall()
        for audit in audits:
            op = audit['operation_id']
            with self.db.connect() as c, c.cursor() as q:
                q.execute('SELECT operation_id FROM dnf_gm.mail_batches WHERE operation_id=%s', (op,))
                if q.fetchone():
                    continue
                request, result = json.loads(audit['request_json']), json.loads(audit['result_json'])
                if not result.get('letter_id') or not request.get('charac_no'):
                    continue
                q.execute('SELECT preview_json FROM dnf_gm.operations WHERE operation_id=%s', (op,))
                operation = q.fetchone()
                target = json.loads(operation['preview_json']).get('target', {}) if operation else {}
                rewards = result.get('items', {}).get('items', [])
                kinds = {i['id']: i.get('mail_kind', 'equipment' if i.get('category')=='equipment' else 'stackable') for i in rewards}
                # Stream in keyset pages; no full mailbox or reward expansion in RAM.
                cursor = 0
                ordinal = 0
                while True:
                    q.execute('SELECT postal_id,item_id,add_info,gold,avata_flag,creature_flag FROM taiwan_cain_2nd.postal '
                              'WHERE receive_charac_no=%s AND letter_id=%s AND postal_id>%s ORDER BY postal_id LIMIT 250',
                              (request['charac_no'],result['letter_id'],cursor))
                    records = q.fetchall()
                    for row in records:
                        ordinal += 1
                        quantity = (0 if not row['item_id'] else 1 if row['avata_flag'] or row['creature_flag'] or kinds.get(row['item_id']) == 'equipment' else max(0,row['add_info']))
                        q.execute('INSERT INTO dnf_gm.mail_deliveries(operation_id,ordinal,postal_id,item_id,quantity,gold) VALUES(%s,%s,%s,%s,%s,%s)',
                                  (op,ordinal,row['postal_id'],row['item_id'],quantity,row['gold']))
                    if len(records)<250:
                        break
                    cursor = records[-1]['postal_id']
                expected = result.get('postal_count',len(result.get('postal_ids', [])))
                if result.get('postal_ids_truncated') and 'postal_count' not in result:
                    expected = max(expected,ordinal+1)
                request['items'] = [{'id':i['id'],'quantity':i['quantity']} for i in rewards]
                q.execute('INSERT INTO dnf_gm.mail_batches(operation_id,target_uid,charac_no,account_name,character_name,letter_id,postal_count,recorded_count,history_complete,message,request_json,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          (op,request['uid'],request['charac_no'],target.get('accountname','历史名称未知'),target.get('character',{}).get('charac_name','历史名称未知'),result['letter_id'],expected,ordinal,int(expected==ordinal),mail_text({**request,'message':request.get('message','')}),json.dumps(request,ensure_ascii=False),audit['created_at']))
                c.commit()
                imported += 1
        return {'imported':imported,'after_id':audits[-1]['id'] if audits else after_id,'has_more':len(audits)==limit}
