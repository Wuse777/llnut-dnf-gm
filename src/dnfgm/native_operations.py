"""Audited at-most-once native dispatch. MySQL and native transports are not atomic.

Commit the dispatch claim before opening a socket. Any ambiguous commit aborts
sending; a durable claim without a final result stays uncertain indefinitely.
Confirming that original operation never sends again, including after restart.
"""
from contextlib import ExitStack
import hashlib
import json
import math
import re
import time
import uuid

from fastapi import HTTPException

from .catalog import snapshot
from .native_control import NativeControlTransport, notice_packet, kick_packet
from .private_message import PrivateMessageTransport, message_text
from .service import OWNER, dump, one

ACTIONS = ('native-notice', 'native-kick', 'native-ban-kick', 'native-message')
REASONS = {'disabled': '该原生控制能力尚未激活', 'invalid_endpoint': '原生私网地址未配置',
           'stale_snapshot': '采集快照已过期', 'image_mismatch': '游戏镜像指纹不匹配',
           'protocol_unverified': '原生程序指纹未通过核验', 'core_unhealthy': '核心服务状态异常',
           'broadcast_test_scope': '测试账号限制生效时不能发送全服广播',
           'test_target_only': '当前仅允许对专用测试账号操作',
           'bridge_unavailable': '定向系统消息插件未安装或核验未通过'}


class NativeOperations:
    def __init__(self, service, monitor):
        self.service = service
        self.db, self.settings = service.db, service.settings
        self.transport = NativeControlTransport(monitor)
        self.private_message = PrivateMessageTransport(self.transport)

    def ready(self, action, uid):
        reason = self.transport.unavailable_reason('native-kick' if action == 'native-ban-kick' else action, uid)
        if reason:
            raise HTTPException(409, '原生控制暂不可用：' + REASONS.get(reason, '状态未知'))
        live = snapshot(self.settings)
        if any(type(live.get(key)) not in (int,float) or not math.isfinite(live[key]) or live[key] < minimum
               for key,minimum in (('mem_available_mib',256),('swap_free_mib',1536))):
            raise HTTPException(503, '资源保护阈值触发，暂不发送控制指令')
        if action == 'native-ban-kick' and ('ban' not in self.settings.writes or self.settings.write_approvals.get('ban') is not True):
            raise HTTPException(403, '封禁能力未激活')
        if action == 'native-message' and not self.private_message.status()['ready']:
            raise HTTPException(409, '定向系统消息插件未就绪；请先完成维护窗口安装和适配核验')

    @staticmethod
    def engines(q):
        q.execute("SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','native_controls')")
        rows = q.fetchall()
        if len(rows) != 3 or any(r['ENGINE'] != 'InnoDB' for r in rows):
            raise HTTPException(409, '防重、审计或原生控制索引表未就绪，拒绝原生控制')

    @staticmethod
    def target(q, uid, charac_no=None):
        if uid is None:
            return {'uid': None, 'accountname': '当前monitor管理的全部游戏服务器'}
        row = one(q, 'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s', (uid,))
        if not row:
            raise HTTPException(404, '账号不存在')
        if charac_no is not None:
            char = one(q, 'SELECT charac_no,charac_name FROM taiwan_cain.charac_info WHERE m_id=%s AND charac_no=%s AND delete_flag=0', (uid, charac_no))
            if not char:
                raise HTTPException(409, '目标角色不属于账号、已删除或发生变化')
            row.update(char)
        return row

    @staticmethod
    def punishment(q, uid, lock=False):
        suffix = ' FOR UPDATE' if lock else ''
        row = one(q, 'SELECT apply_flag,admin_id,reason,end_time FROM d_taiwan.member_punish_info WHERE m_id=%s AND punish_type=1' + suffix, (uid,))
        own = one(q, 'SELECT marker FROM dnf_gm.owned_bans WHERE uid=%s' + suffix, (uid,))
        if row and (not own or row['admin_id'] != OWNER or row['reason'] != own['marker']):
            raise HTTPException(409, '存在非本后台处罚，禁止覆盖')
        if row and row['apply_flag']:
            raise HTTPException(409, '账号已被封禁；如需断线请使用单独踢人')
        return {'record': row, 'owned': own}

    def create_in_transaction(self, q, session_hash, data, op=None, now=None):
        # Validate here as well: scheduled/internal callers must use the same types.
        from .models import NativePreview
        data = NativePreview(**data).model_dump()
        action, uid = data['action'], data['uid']
        if action == 'native-notice':
            notice_packet(data['message'])
        elif action == 'native-message':
            message_text(data['message'])
        else:
            kick_packet(uid)
        self.ready(action, uid)
        self.engines(q)
        preview = {'action': action, 'target': self.target(q, uid, data['charac_no']), 'reason': data['reason'],
                   'message': data['message'], 'image_digest': self.settings.image_digest,
                   'note': '只记录发送状态，没有业务回执；不能据此证明游戏内生效。封禁与踢人不是一个原子操作。'}
        if action == 'native-ban-kick':
            self.service.check_write(q, {'action': 'ban', 'uid': uid}, {})
            preview['punishment'] = self.punishment(q, uid)
        op = op or uuid.uuid4().hex
        now = int(time.time()) if now is None else now
        fingerprint = hashlib.sha256(dump({'request': data, 'preview': preview}).encode()).hexdigest()
        q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,'preview',%s,%s)",
                  (op, session_hash, fingerprint, action, dump(data), dump(preview), now, now+300))
        q.execute('INSERT INTO dnf_gm.native_controls(operation_id,target_uid,created_at) VALUES(%s,%s,%s)', (op, uid, now))
        return {'operation_id': op, 'preview': preview, 'expires_at': now+300, 'status': 'preview'}

    def preview(self, session_hash, data):
        with self.db.connect() as c, c.cursor() as q:
            result = self.create_in_transaction(q, session_hash, data)
            c.commit()
        return result

    @staticmethod
    def row(q, op, session_hash=None, lock=False):
        row = one(q, 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s' + (' FOR UPDATE' if lock else ''), (op,))
        if not row or row['action'] not in ACTIONS or (session_hash is not None and row['session_hash'] != session_hash):
            raise HTTPException(404, '原生控制操作不存在或不属于当前会话')
        return row

    @staticmethod
    def view(row):
        return {'operation_id': row['operation_id'], 'action': row['action'], 'status': row['status'],
                'preview': json.loads(row['preview_json']), 'expires_at': row['expires_at'],
                'result': json.loads(row['result_json'] or 'null'), 'automatic_retry_allowed': False}

    def detail(self, op):
        with self.db.connect() as c, c.cursor() as q:
            return self.view(self.row(q, op))

    def history(self, uid=0, page=1):
        with self.db.connect() as c, c.cursor() as q:
            # Scan only the small native history index, not JSON in every game
            # operation. Both global and per-account history have matching indexes.
            index, clause, args = ('target_created', ' WHERE n.target_uid=%s', [uid]) if uid else ('created', '', [])
            q.execute('SELECT o.operation_id,o.action,o.status,o.preview_json,o.result_json,o.expires_at,n.created_at '
                      'FROM dnf_gm.native_controls n FORCE INDEX ('+index+') STRAIGHT_JOIN dnf_gm.operations o ON o.operation_id=n.operation_id'
                      +clause+' ORDER BY n.created_at DESC,n.operation_id DESC LIMIT 50 OFFSET %s', (*args, (page-1)*50))
            rows = q.fetchall()
            return {'items': [{**self.view(r), 'created_at': r['created_at']} for r in rows], 'page': page}

    @staticmethod
    def audit(q, audit_id, data, result, actor="owner"):
        q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                  (audit_id, actor, data['action'], data['uid'], data['reason'], dump(data), dump(result)))

    def failure(self, op, stage, error):
        # Separate diagnostic attempt, never a replacement for the transactional
        # success audit. Store only a bounded class name, not SQL/endpoint text.
        try:
            with self.db.connect() as c, c.cursor() as q:
                q.execute('INSERT INTO dnf_gm.failures(operation_id,error_type) VALUES(%s,%s)',
                          (op, ('native-'+stage+':'+type(error).__name__)[:64]))
                c.commit()
        except Exception:
            pass

    def confirm(self, session_hash, op, key, actor="owner"):
        with ExitStack() as gates:
            return self._confirm(session_hash,op,key,actor,gates)

    def _confirm(self, session_hash, op, key, actor, gates):
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', key):
            raise HTTPException(422, '非法幂等键')
        committing = False
        try:
            with self.db.connect() as c, c.cursor() as q:
                row = self.row(q, op, session_hash, True)
                old = one(q, 'SELECT operation_id FROM dnf_gm.operations WHERE idempotency_key=%s', (key,))
                if old and old['operation_id'] != op:
                    raise HTTPException(409, '幂等键已用于其他操作')
                if row['status'] != 'preview':
                    if row['idempotency_key'] != key:
                        raise HTTPException(409, '操作已提交或取消，不能使用新的幂等键重发')
                    return self.view(row)
                if row['expires_at'] <= int(time.time()):
                    raise HTTPException(409, '预览已过期，请重新预览')
                data, preview = json.loads(row['request_json']), json.loads(row['preview_json'])
                if row['fingerprint'] != hashlib.sha256(dump({'request': data, 'preview': preview}).encode()).hexdigest():
                    raise HTTPException(409, '预览完整性校验失败')
                if row['action'] != data['action'] or preview['image_digest'] != self.settings.image_digest:
                    raise HTTPException(409, '适配版本发生变化，请重新预览')
                lease=gates.enter_context(self.service.write_gate.writer())
                lease.protect_transaction(q)
                self.ready(data['action'], data['uid'])
                self.engines(q)
                if self.target(q, data['uid'], data.get('charac_no')) != preview['target']:
                    raise HTTPException(409, '目标发生变化，请重新预览')
                result = {'operation_id': op, 'action': data['action'], 'transport_status': 'uncertain',
                          'effect_status': 'unknown', 'reason_code': 'dispatch_claimed',
                          'automatic_retry_allowed': False, 'ban_status': 'not_requested'}
                if data['action'] == 'native-ban-kick':
                    self.service.check_write(q, {'action': 'ban', 'uid': data['uid']}, {})
                    existing = self.punishment(q, data['uid'], True)
                    if dump(existing) != dump(preview['punishment']):
                        raise HTTPException(409, '处罚记录已变化，请重新预览')
                    marker = 'GM-' + op
                    if existing['record']:
                        q.execute("UPDATE d_taiwan.member_punish_info SET apply_flag=1,start_time=UTC_TIMESTAMP(),end_time='2099-01-01',admin_id=%s,reason=%s WHERE m_id=%s AND punish_type=1", (OWNER, marker, data['uid']))
                    else:
                        q.execute("INSERT INTO d_taiwan.member_punish_info(m_id,punish_type,occ_time,punish_value,apply_flag,start_time,end_time,admin_id,reason) VALUES(%s,1,UTC_TIMESTAMP(),1,1,UTC_TIMESTAMP(),'2099-01-01',%s,%s)", (data['uid'], OWNER, marker))
                    q.execute('INSERT INTO dnf_gm.owned_bans(uid,marker) VALUES(%s,%s) ON DUPLICATE KEY UPDATE marker=VALUES(marker)', (data['uid'], marker))
                    result['ban_status'] = 'committed_login_test_pending'
                q.execute("UPDATE dnf_gm.operations SET idempotency_key=%s,status='dispatching',result_json=%s WHERE operation_id=%s", (key, dump(result), op))
                self.audit(q, op, data, {**result, 'stage': 'dispatch_claim'}, actor)
                lease.check()
                committing = True
                c.commit()
        except Exception as error:
            self.failure(op, 'claim', error)
            if committing:
                raise HTTPException(503, '防重事务结果待确认；本请求没有发送指令，请查询原操作编号，不要重新提交') from None
            raise
        # No connection is held while sending. A process exit here leaves a durable
        # uncertain claim. There is intentionally no background replay worker.
        try:
            self.ready(data['action'], data['uid'])
            lease.check()
        except HTTPException:
            transport = {'transport_status': 'not_sent', 'effect_status': 'unknown',
                         'reason_code': 'readiness_changed_after_claim', 'automatic_retry_allowed': False}
        else:
            transport = self.send_once(data, op)
        result.update(transport)
        try:
            with self.db.connect() as c, c.cursor() as q:
                row = self.row(q, op, session_hash, True)
                if row['status'] != 'dispatching' or row['idempotency_key'] != key:
                    raise RuntimeError('Claim mismatch')
                self.audit(q, 'native-result:' + op, data, {**result, 'stage': 'transport_result'}, actor)
                q.execute('UPDATE dnf_gm.operations SET status=%s,result_json=%s WHERE operation_id=%s', (result['transport_status'], dump(result), op))
                c.commit()
        except Exception as error:
            self.failure(op, 'result', error)
            raise HTTPException(503, '指令处理后的结果记录待确认；请只查询原编号，禁止自动重发') from None
        return self.detail(op)

    def send_once(self, data, operation_id=None):
        try:
            if data['action'] == 'native-message':
                return self.private_message.send(operation_id, data['uid'], data['charac_no'], data['message'])
            return (self.transport.notice(data['message']) if data['action'] == 'native-notice'
                    else self.transport.kick(data['uid']))
        except Exception:
            return {'transport_status': 'uncertain', 'effect_status': 'unknown',
                    'reason_code': 'transport_exception', 'automatic_retry_allowed': False}

    def cancel(self, session_hash, op, actor="owner"):
        # Recent authenticated admin may cancel stale-session previews. Confirmation
        # remains session-bound; this cannot cancel an already-claimed operation.
        with self.db.connect() as c, c.cursor() as q:
            row = self.row(q, op, lock=True)
            if row['status'] == 'cancelled':
                return self.view(row)
            if row['status'] != 'preview':
                raise HTTPException(409, '已取得发送占位，不能取消或重发')
            self.engines(q)
            data = json.loads(row['request_json'])
            result = {'operation_id': op, 'action': data['action'], 'transport_status': 'not_sent',
                      'effect_status': 'unknown', 'reason_code': 'cancelled', 'ban_status': 'not_requested'}
            self.audit(q, 'native-cancel:' + op, data, result, actor)
            q.execute("UPDATE dnf_gm.operations SET status='cancelled',result_json=%s WHERE operation_id=%s", (dump(result), op))
            c.commit()
            row.update(status='cancelled', result_json=dump(result))
            return self.view(row)
