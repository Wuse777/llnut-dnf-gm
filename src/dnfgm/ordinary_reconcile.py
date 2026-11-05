"""Management-only outcome settlement under the frozen gate + exclusive DB fence.

Caller owns one transaction and verifies the original server UUID. No gameplay
writes, socket commands, retries or gate release. Native uncertainty stays unknown.
"""
import hashlib
import json
import re

from .release_files import Refused, canonical

LIMIT = 100
TABLES = ('operations', 'audit', 'reward_jobs', 'reward_targets', 'native_controls',
          'mail_batches', 'mail_deliveries', 'economy_operations', 'economy_values',
          'reward_account_credits')
NATIVE = ('native-notice', 'native-kick', 'native-ban-kick')


def one(q, sql, args=()):
    q.execute(sql, args)
    return q.fetchone()


def parsed(value):
    try:
        result = json.loads(value)
        if not isinstance(result, dict): raise ValueError()
        return result
    except (ValueError, TypeError):
        raise Refused('maintenance_outcome_record_invalid') from None


def validate_summary(value):
    expected = {'version', 'audit_id', 'sha256', 'rewards_committed', 'rewards_failed',
                'native_uncertain', 'game_writes', 'automatic_replay'}
    if (not isinstance(value, dict) or set(value) != expected
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['audit_id'], str)
            or not re.fullmatch(r'maintenance-outcomes:[a-f0-9]{32}', value['audit_id'])
            or not isinstance(value['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['sha256'])
            or any(type(value[k]) is not int or not 0 <= value[k] <= LIMIT
                   for k in ('rewards_committed', 'rewards_failed', 'native_uncertain'))
            or value['rewards_committed'] + value['rewards_failed'] > LIMIT
            or value['game_writes'] is not False or value['automatic_replay'] is not False):
        raise Refused('maintenance_outcome_proof_invalid')
    return value


def summary(receipt, request_id):
    try:
        if (set(receipt) != {'version', 'rewards', 'native_uncertain', 'game_writes', 'automatic_replay'}
                or type(receipt['version']) is not int or receipt['version'] != 1
                or receipt['game_writes'] is not False or receipt['automatic_replay'] is not False
                or not isinstance(receipt['rewards'], list) or len(receipt['rewards']) > LIMIT
                or not isinstance(receipt['native_uncertain'], list) or len(receipt['native_uncertain']) > LIMIT):
            raise ValueError()
        ids = []
        for row in receipt['rewards']:
            if (set(row) != {'operation_id', 'job_id', 'ordinal', 'status'}
                    or row['status'] not in ('committed', 'failed')
                    or type(row['ordinal']) is not int or row['ordinal'] < 0
                    or any(not isinstance(row[k], str) or not re.fullmatch('[a-f0-9]{32}', row[k])
                           for k in ('operation_id', 'job_id'))): raise ValueError()
            ids.append(row['operation_id'])
        for op in receipt['native_uncertain']:
            if not isinstance(op, str) or not re.fullmatch('[a-f0-9]{32}', op): raise ValueError()
            ids.append(op)
        if len(set(ids)) != len(ids): raise ValueError()
        return validate_summary({'version': 1, 'audit_id': 'maintenance-outcomes:' + request_id,
            'sha256': hashlib.sha256(canonical(receipt)).hexdigest(),
            'rewards_committed': sum(r['status'] == 'committed' for r in receipt['rewards']),
            'rewards_failed': sum(r['status'] == 'failed' for r in receipt['rewards']),
            'native_uncertain': len(receipt['native_uncertain']),
            'game_writes': False, 'automatic_replay': False})
    except (ValueError, TypeError, KeyError):
        raise Refused('maintenance_outcome_record_invalid') from None


def check_schema(q):
    q.execute("SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN (" + ','.join(['%s'] * len(TABLES)) + ')', TABLES)
    tables = q.fetchall()
    if {r['TABLE_NAME'] for r in tables} != set(TABLES) or any(r['ENGINE'] != 'InnoDB' for r in tables):
        raise Refused('maintenance_outcome_schema_unproven')
    q.execute("SELECT COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='operations' AND INDEX_NAME='outcome_status' ORDER BY SEQ_IN_INDEX")
    if [r['COLUMN_NAME'] for r in q.fetchall()] != ['status', 'action', 'operation_id']:
        raise Refused('maintenance_outcome_index_unproven')


def settle(q, binding):
    request_id = binding['operation_id']
    if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
        raise Refused('maintenance_outcome_binding_invalid')
    check_schema(q)
    audit_id = 'maintenance-outcomes:' + request_id
    old = one(q, 'SELECT * FROM dnf_gm.audit WHERE operation_id=%s FOR UPDATE', (audit_id,))
    if old:
        if (old['actor'] != 'maintenance' or old['action'] != 'maintenance-reconcile'
                or parsed(old['request_json']) != binding):
            raise Refused('maintenance_outcome_binding_changed')
        return summary(parsed(old['result_json']), request_id)

    # Both lookups have status-leading indexes. Bound work before any mutation.
    q.execute("SELECT job_id,ordinal FROM dnf_gm.reward_targets FORCE INDEX(recovery) WHERE status IN ('executing','uncertain') ORDER BY status,job_id,ordinal LIMIT 101")
    targets = q.fetchall()
    q.execute("SELECT operation_id FROM dnf_gm.operations FORCE INDEX(outcome_status) WHERE status IN ('dispatching','uncertain','executing') ORDER BY status,action,operation_id LIMIT 101")
    native = q.fetchall()
    if len(targets) > LIMIT or len(native) > LIMIT:
        raise Refused('maintenance_pending_budget_exceeded')
    result = {'version': 1, 'rewards': [], 'native_uncertain': [], 'game_writes': False, 'automatic_replay': False}
    for found in sorted(targets, key=lambda t: (t['job_id'], t['ordinal'])):
        job = one(q, 'SELECT id,status FROM dnf_gm.reward_jobs WHERE id=%s FOR UPDATE', (found['job_id'],))
        target = one(q, 'SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s AND ordinal=%s FOR UPDATE', (found['job_id'], found['ordinal']))
        if not job or not target: raise Refused('maintenance_outcome_target_missing')
        if target['status'] not in ('executing', 'uncertain'): continue  # Already reconciled by ordinary worker.
        op = target['operation_id']
        operation = one(q, 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE', (op,))
        audited = one(q, 'SELECT * FROM dnf_gm.audit WHERE operation_id=%s FOR UPDATE', (op,))
        if operation and audited:
            data, evidence = parsed(operation['result_json']), parsed(audited['result_json'])
            if (operation['action'] != 'reward' or operation['status'] != 'committed'
                    or audited['action'] != 'reward' or audited['target_uid'] != target['target_uid']
                    or data != evidence or data.get('operation_id') != op
                    or data.get('job_id') != job['id'] or data.get('uid') != target['target_uid']):
                raise Refused('maintenance_outcome_conflict')
            status, message = 'committed', ''
        elif operation or audited:
            raise Refused('maintenance_outcome_conflict')
        else:
            # Never call an orphaned projection/ledger a safe negative outcome.
            for table in ('mail_batches', 'mail_deliveries', 'economy_operations', 'economy_values'):
                if one(q, 'SELECT operation_id FROM dnf_gm.' + table + ' WHERE operation_id=%s LIMIT 1 FOR UPDATE', (op,)):
                    raise Refused('maintenance_outcome_conflict')
            if one(q, 'SELECT operation_id FROM dnf_gm.reward_account_credits WHERE job_id=%s AND target_uid=%s AND operation_id=%s FOR UPDATE', (job['id'], target['target_uid'], op)):
                raise Refused('maintenance_outcome_conflict')
            status, message = 'failed', '维护前已核对事务结束且无提交记录；不会自动重发，可在原任务中人工处理'
        q.execute('UPDATE dnf_gm.reward_targets SET status=%s,error_type=%s,error_message=%s WHERE job_id=%s AND ordinal=%s',
                  (status, '' if status == 'committed' else 'MaintenanceReconciled', message, job['id'], target['ordinal']))
        q.execute("UPDATE dnf_gm.reward_jobs SET status=IF(status='running','paused',status),pause_reason=%s WHERE id=%s", ('维护前已核对中断目标，请查看原任务；未重发奖励', job['id']))
        result['rewards'].append({'operation_id': op, 'job_id': job['id'], 'ordinal': target['ordinal'], 'status': status})

    for found in native:
        op = found['operation_id']
        operation = one(q, 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE', (op,))
        if not operation or operation['status'] not in ('dispatching', 'uncertain', 'executing'): continue
        if operation['action'] not in NATIVE or operation['status']=='executing':
            raise Refused('maintenance_outcome_action_unproven')
        native_index = one(q, 'SELECT target_uid FROM dnf_gm.native_controls WHERE operation_id=%s FOR UPDATE', (op,))
        request = parsed(operation['request_json'])
        claim = one(q, 'SELECT * FROM dnf_gm.audit WHERE operation_id=%s FOR UPDATE', (op,))
        end = one(q, 'SELECT * FROM dnf_gm.audit WHERE operation_id=%s FOR UPDATE', ('native-result:' + op,))
        claim_result = parsed(claim['result_json']) if claim else {}
        if (not claim or not native_index or native_index['target_uid'] != request.get('uid')
                or claim['target_uid'] != request.get('uid') or parsed(claim['request_json']) != request
                or claim['action'] != operation['action'] or claim_result.get('action') != operation['action']
                or claim_result.get('stage') != 'dispatch_claim' or claim_result.get('operation_id') != op
                or claim_result.get('automatic_retry_allowed') is not False):
            raise Refused('maintenance_outcome_native_conflict')
        stored = parsed(operation['result_json'])
        if operation['status'] == 'dispatching':
            if end or stored != {k:v for k,v in claim_result.items() if k != 'stage'}:
                raise Refused('maintenance_outcome_native_conflict')
        elif (not end or end['action'] != operation['action']
                or parsed(end['result_json']) != {**stored, 'stage': 'transport_result'}
                or stored.get('transport_status') != 'uncertain' or stored.get('automatic_retry_allowed') is not False):
            raise Refused('maintenance_outcome_native_conflict')
        # Do not infer whether a packet reached the game, or reverse a committed ban.
        result['native_uncertain'].append(op)
    proof = summary(result, request_id)
    q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'maintenance','maintenance-reconcile',%s,%s,%s)",
              (audit_id, '维护前核对普通操作结果；不修改游戏数据、不重发原生指令', canonical(binding).decode(), canonical(result).decode()))
    return proof


def public_audit(row):
    """Keep root-only binding evidence out of both list and export responses."""
    if row.get('action') != 'maintenance-reconcile': return row
    value = dict(row)
    audit_id = row.get('operation_id', '')
    match = re.fullmatch(r'maintenance-outcomes:([a-f0-9]{32})', audit_id)
    request_id = match[1] if match else None
    value['request_json'] = canonical({'operation_id': request_id, 'binding_redacted': True}).decode()
    try:
        if not request_id: raise Refused('maintenance_outcome_record_invalid')
        receipt = parsed(row['result_json'])
        summary(receipt, request_id)  # Reject extra or malformed fields, don't reflect them.
        value['result_json'] = canonical(receipt).decode()
    except (ValueError, TypeError, KeyError):
        value['result_json'] = canonical({'state':'unknown','automatic_replay':False}).decode()
    return value
