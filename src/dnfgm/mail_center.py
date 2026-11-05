"""Immutable delivery ledger and bounded read-only receipt queries.

A missing game row is unknown, not evidence of successful receipt. Pagination
uses ledger ordinals so deletions by the game cannot hide historic deliveries.
"""
import json
from .mail_content import mail_text
from fastapi import HTTPException


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
    def __init__(self, db):
        self.db = db

    def list(self, uid=0, charac_no=0, operation_id='', page=1):
        predicates, args = [], []
        for column, value in [('target_uid', uid), ('charac_no', charac_no), ('operation_id', operation_id)]:
            if value:
                predicates.append(column + '=%s')
                args.append(value)
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT operation_id,target_uid,charac_no,account_name,character_name,letter_id,'
                      'postal_count,recorded_count,history_complete,message,created_at '
                      'FROM dnf_gm.mail_batches' + where +
                      ' ORDER BY created_at DESC,operation_id DESC LIMIT 51 OFFSET %s', (*args, (page-1)*50))
            rows = q.fetchall()
        return {'items': rows[:50], 'page': page, 'has_more': len(rows)>50}

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
        return {'batch': batch, 'items': records, 'next_after': records[-1]['ordinal'] if more else None,
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
