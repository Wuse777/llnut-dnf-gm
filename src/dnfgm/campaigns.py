"""Campaign management and atomic, cross-job reward claims.

All helpers receiving a cursor join the caller's transaction and never connect,
commit, or dispatch work. The campaign row serializes state and claims; a unique
claim is the final database constraint. A failed reward rolls its claim back.
"""
import copy
import hashlib
import json
import time
import uuid
from fastapi import HTTPException
from pymysql.err import IntegrityError
from .campaign_models import CampaignSave
from .models import RewardDefinition, RewardTargets
from .service import one, dump
from . import campaign_audience

TABLES = ('campaigns', 'campaign_claims', 'campaign_links', 'operations', 'audit')
TRANSITIONS = {'draft': {'draft', 'active', 'archived'},
               'active': {'active', 'paused', 'archived'},
               'paused': {'paused', 'active', 'archived'}, 'archived': set()}


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


class Campaigns:
    def __init__(self, service):
        self.service, self.db = service, service.db

    @staticmethod
    def engines(q):
        q.execute("SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE "
                  "TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN (" + ','.join(['%s'] * len(TABLES)) + ')', TABLES)
        rows = q.fetchall()
        if {r['TABLE_NAME'] for r in rows} != set(TABLES) or any(r['ENGINE'] != 'InnoDB' for r in rows):
            raise HTTPException(503, '活动迁移018或事务引擎未就绪')

    @staticmethod
    def row(q, campaign_id, lock=False):
        row = one(q, 'SELECT * FROM dnf_gm.campaigns WHERE id=%s' + (' FOR UPDATE' if lock else ''), (campaign_id,))
        if not row:
            raise HTTPException(404, '活动不存在')
        return row

    @staticmethod
    def public(row):
        result = {k: v for k, v in row.items() if not k.endswith('_json')}
        for field in ('definition', 'reward', 'binding'):
            result[field] = json.loads(row[field + '_json'])
        result['job_draft'] = {'campaign_id': row['id'], 'targets': result['definition']['targets'],
            'reward': {}, 'account_reward_mode': 'once_per_account' if result['definition']['dedupe']=='account' else 'per_character',
            'reason': '活动：' + row['name']}
        return result

    def audience_schema(self):
        with self.db.connect() as c, c.cursor() as q:
            return campaign_audience.schema(q)

    def list(self, page=1, status='', text=''):
        clauses, args = [], []
        if status:
            if status not in TRANSITIONS:
                raise HTTPException(422, '未知活动状态')
            clauses.append('status=%s'); args.append(status)
        if text:
            clauses.append('(id=%s OR name LIKE %s)')
            args.extend([text, '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'])
        with self.db.connect() as c, c.cursor() as q:
            self.engines(q)
            q.execute('SELECT id,name,status,revision,activated,created_at,updated_at FROM dnf_gm.campaigns' +
                      (' WHERE ' + ' AND '.join(clauses) if clauses else '') +
                      ' ORDER BY updated_at DESC,id DESC LIMIT 21 OFFSET %s', (*args, (page - 1) * 20))
            rows = q.fetchall()
        return {'items': rows[:20], 'page': page, 'has_more': len(rows) > 20}

    def detail(self, campaign_id, page=1):
        with self.db.connect() as c, c.cursor() as q:
            self.engines(q)
            result = self.public(self.row(q, campaign_id))
            result['claims'] = one(q, 'SELECT COUNT(*) subjects,COUNT(DISTINCT target_uid) accounts '
                                  'FROM dnf_gm.campaign_claims WHERE campaign_id=%s', (campaign_id,))
            q.execute('SELECT v.metric,v.item_id,v.pvf_sha256,MAX(v.item_name) item_name,CAST(SUM(v.amount) AS CHAR) amount '
                      'FROM dnf_gm.campaign_claims c JOIN dnf_gm.economy_values v ON v.operation_id=c.operation_id '
                      'WHERE c.campaign_id=%s GROUP BY v.metric,v.item_id,v.pvf_sha256 '
                      'ORDER BY v.metric,v.item_id LIMIT 51', (campaign_id,))
            totals = q.fetchall(); result['totals'] = totals[:50]; result['totals_truncated'] = len(totals) > 50
            q.execute('SELECT l.kind,l.reference_id,l.created_at,COALESCE(j.status,s.status,o.status) status '
                      'FROM dnf_gm.campaign_links l '
                      "LEFT JOIN dnf_gm.reward_jobs j ON l.kind='job' AND j.id=l.reference_id "
                      "LEFT JOIN dnf_gm.schedules s ON l.kind='schedule' AND s.id=l.reference_id "
                      "LEFT JOIN dnf_gm.operations o ON l.kind='reward' AND o.operation_id=l.reference_id "
                      'WHERE l.campaign_id=%s ORDER BY l.created_at DESC,l.kind,l.reference_id LIMIT 21 OFFSET %s',
                      (campaign_id, (page - 1) * 20))
            links = q.fetchall(); result.update(links=links[:20], has_more=len(links) > 20, page=page)
            result['note'] = '领取次数指本GM奖励已提交，不等于玩家已领取；仅汇总本活动成功投影。重复目标跳过整份奖励。'
        return result

    def freeze(self, q, request, existing=None):
        definition = {k: request[k] for k in ('name', 'description', 'dedupe', 'targets', 'template_id', 'template_version')}
        if existing and existing['activated']:
            if definition != json.loads(existing['definition_json']):
                raise HTTPException(409, '活动已启用，礼包版本、人群和去重口径不可修改；请复制为新活动')
            return definition, json.loads(existing['reward_json']), json.loads(existing['binding_json'])
        campaign_audience.verify(q, definition['targets'])
        from .reward_jobs import RewardJobs
        selected, _, _ = RewardJobs(self.db,self.service.settings,self.service).resolve_accounts(q,definition['targets'])
        definition['targets'] = selected
        template = one(q, 'SELECT t.enabled,v.payload_json FROM dnf_gm.gift_templates t '
                       'JOIN dnf_gm.gift_versions v ON v.template_id=t.id '
                       'WHERE t.id=%s AND v.version=%s', (request['template_id'], request['template_version']))
        if not template or not template['enabled']:
            raise HTTPException(409, '来源礼包或指定版本不存在／已停用')
        payload = json.loads(template['payload_json'])
        reward = RewardDefinition.model_validate({k: v for k, v in payload.items()
                    if k in RewardDefinition.model_fields and v is not None}).model_dump(mode='json')
        # A campaign pins the selected version, even when the template later advances.
        reward.pop('template_id', None); reward.pop('template_version', None); reward.pop('template_overrides', None)
        resolved = self.service.reward_snapshot(q, {**reward, 'action': 'reward'})
        binding = {'image_digest': self.service.settings.image_digest, 'snapshot': resolved}
        return definition, reward, binding

    def preview(self, session_hash, data):
        request = CampaignSave.model_validate(data).model_dump(mode='json')
        campaign_id = request['campaign_id'] or uuid.uuid4().hex
        with self.db.connect() as c, c.cursor() as q:
            self.engines(q)
            current = self.row(q, campaign_id) if request['campaign_id'] else None
            if request['expected_revision'] != (current['revision'] if current else 0):
                raise HTTPException(409, '活动版本已变化，请重新读取')
            if current and request['status'] not in TRANSITIONS[current['status']]:
                raise HTTPException(409, '活动状态不可这样变更；归档活动保留历史')
            definition, reward, binding = self.freeze(q, request, current)
            request['campaign_id'] = campaign_id
            preview = {'campaign_id': campaign_id, 'definition': definition, 'reward': reward,
                       'binding': binding, 'status': request['status'], 'previous_status': current['status'] if current else None,
                       'revision': request['expected_revision'] + 1,
                       'note': '只保存活动，不发放奖励或启动计划；启用后固定礼包、人群和去重口径。'}
            op, now = uuid.uuid4().hex, int(time.time())
            q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) "
                      "VALUES(%s,%s,%s,'campaign',%s,%s,'preview',%s,%s)",
                      (op, session_hash, digest({'request': request, 'preview': preview}), dump(request), dump(preview), now, now + 300))
            c.commit()
        return {'operation_id': op, 'preview': preview, 'expires_at': now + 300, 'status': 'preview'}

    def operation(self, session_hash, op):
        with self.db.connect() as c, c.cursor() as q:
            row = one(q, "SELECT operation_id,status,session_hash,preview_json,result_json,expires_at FROM dnf_gm.operations "
                      "WHERE operation_id=%s AND action='campaign'", (op,))
            if not row:
                raise HTTPException(404, '活动操作不存在，请保留原编号核对')
            return self.operation_view(row, session_hash)

    @staticmethod
    def operation_view(row, session_hash):
        result = {key: row[key] for key in ('operation_id', 'status', 'expires_at')}
        result['same_session'] = row['session_hash'] == session_hash
        result['confirmable'] = result['same_session'] and row['status'] == 'preview' and row['expires_at'] >= time.time()
        result['preview'] = json.loads(row['preview_json'])
        result['result'] = json.loads(row['result_json'] or 'null')
        return result

    def cancel(self, session_hash, op):
        committing = False
        try:
            with self.db.connect() as c, c.cursor() as q:
                self.engines(q)
                row = one(q, "SELECT * FROM dnf_gm.operations WHERE operation_id=%s AND action='campaign' FOR UPDATE", (op,))
                if not row:
                    raise HTTPException(404, '活动操作不存在，请保留原编号核对')
                if row['status'] == 'preview':
                    q.execute("UPDATE dnf_gm.operations SET status='cancelled' WHERE operation_id=%s AND status='preview'", (op,))
                    q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) "
                              "VALUES(%s,'owner','campaign-cancel',%s,%s,%s)",
                              ('campaign-cancel-' + uuid.uuid4().hex, '取消尚未保存的活动预览；不撤销已提交活动',
                               dump({'operation_id': op}), dump({'operation_id': op, 'state': 'cancelled'})))
                    row['status'] = 'cancelled'
                    committing = True
                    c.commit()
                return self.operation_view(row, session_hash)
        except Exception:
            if committing:
                raise HTTPException(503, '取消结果待核对，请只查询原活动操作编号') from None
            raise

    def confirm(self, session_hash, op, key):
        committing = False
        try:
            with self.db.connect() as c, c.cursor() as q:
                self.engines(q)
                row = one(q, "SELECT * FROM dnf_gm.operations WHERE operation_id=%s AND session_hash=%s "
                          "AND action='campaign' FOR UPDATE", (op, session_hash))
                if not row:
                    raise HTTPException(404, '活动预览不存在')
                old = one(q, 'SELECT operation_id FROM dnf_gm.operations WHERE idempotency_key=%s', (key,))
                if old and old['operation_id'] != op:
                    raise HTTPException(409, '幂等键已用于其他操作')
                if row['status'] == 'committed':
                    if row['idempotency_key'] != key:
                        raise HTTPException(409, '活动操作已由其他幂等键完成')
                    return json.loads(row['result_json'])
                if row['status'] != 'preview' or row['expires_at'] < time.time():
                    raise HTTPException(409, '活动预览已过期，请重新预览')
                request, preview = json.loads(row['request_json']), json.loads(row['preview_json'])
                if row['fingerprint'] != digest({'request': request, 'preview': preview}):
                    raise HTTPException(409, '活动预览校验失败')
                current = one(q, 'SELECT * FROM dnf_gm.campaigns WHERE id=%s FOR UPDATE', (request['campaign_id'],))
                if request['expected_revision'] != (current['revision'] if current else 0):
                    raise HTTPException(409, '活动已被修改，请重新读取')
                if current and request['status'] not in TRANSITIONS[current['status']]:
                    raise HTTPException(409, '活动状态已变化')
                definition, reward, binding = self.freeze(q, request, current)
                if (definition, reward, binding) != (preview['definition'], preview['reward'], preview['binding']):
                    raise HTTPException(409, '礼包、索引或活动定义已变化，请重新预览')
                now = int(time.time()); activated = bool(current and current['activated']) or request['status'] == 'active'
                values = (request['name'], request['status'], preview['revision'], dump(definition), dump(reward),
                          dump(binding), digest({'definition': definition, 'reward': reward, 'binding': binding}), int(activated), now)
                if current:
                    q.execute('UPDATE dnf_gm.campaigns SET name=%s,status=%s,revision=%s,definition_json=%s,reward_json=%s,'
                              'binding_json=%s,definition_hash=%s,activated=%s,updated_at=%s WHERE id=%s', (*values, request['campaign_id']))
                else:
                    q.execute('INSERT INTO dnf_gm.campaigns(name,status,revision,definition_json,reward_json,binding_json,'
                              'definition_hash,activated,updated_at,id,created_at) VALUES(' + ','.join(['%s'] * 11) + ')',
                              (*values, request['campaign_id'], now))
                result = {'campaign_id': request['campaign_id'], 'revision': preview['revision'], 'status': request['status'], 'operation_id': op}
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) "
                          "VALUES(%s,'owner','campaign',%s,%s,%s)", (op, request['reason'], dump(request), dump(result)))
                q.execute("UPDATE dnf_gm.operations SET status='committed',idempotency_key=%s,result_json=%s WHERE operation_id=%s",
                          (key, dump(result), op))
                committing = True; c.commit()
                return result
        except Exception as error:
            if committing:
                raise HTTPException(503, '活动保存结果待核对，请只查询原操作编号') from None
            if isinstance(error, IntegrityError):
                raise HTTPException(409, '活动版本或幂等键冲突，请查询原操作') from None
            raise

    def active(self, q, data, lock=False):
        row = self.row(q, data['campaign_id'], lock)
        if row['status'] != 'active':
            raise HTTPException(409, '活动未启用、已暂停或已归档')
        frozen = {field: json.loads(row[field + '_json']) for field in ('definition', 'reward', 'binding')}
        if digest(frozen) != row['definition_hash']:
            raise HTTPException(409, '活动冻结定义校验失败，禁止发放')
        if json.loads(row['binding_json']).get('image_digest') != self.service.settings.image_digest:
            raise HTTPException(409, '活动冻结的游戏镜像已变化，请暂停旧活动并建立新活动')
        if data.get('_campaign_hash') and data['_campaign_hash'] != row['definition_hash']:
            raise HTTPException(409, '活动定义已变化，请重新建立预览')
        return row

    def bind_reward(self, q, data):
        if not data.get('campaign_id'):
            return None
        if data.get('action') != 'reward':
            raise HTTPException(422, '活动奖励必须使用组合奖励入口')
        row = self.active(q, data)
        frozen = json.loads(row['reward_json'])
        definition = json.loads(row['definition_json'])
        if data.get('template_overrides'):
            raise HTTPException(422, '活动固定礼包版本，不接受临时调整')
        for key, fallback in (('items', []), ('gold', 0), ('mail_title', ''), ('message', 'GM rewards')):
            if data.get(key, fallback) not in (fallback, frozen.get(key, fallback)):
                raise HTTPException(409, '奖励与活动冻结礼包不一致')
        given = self.service.currency_rewards(data)
        if given and given != self.service.currency_rewards(frozen):
            raise HTTPException(409, '账号货币与活动冻结礼包不一致')
        if data.get('template_id') and (data['template_id'], data.get('template_version')) != (definition['template_id'], definition['template_version']):
            raise HTTPException(409, '来源礼包与活动不一致')
        data.update(copy.deepcopy(frozen)); data['_campaign_hash'] = row['definition_hash']
        data.pop('template_id', None); data.pop('template_version', None); data.pop('template_overrides', None)
        return {'id': row['id'], 'name': row['name'], 'dedupe': definition['dedupe'],
                'definition_hash': row['definition_hash'], 'template_id': definition['template_id'],
                'template_version': definition['template_version']}

    def bind_job(self, q, data):
        if not data.get('campaign_id'):
            return
        row = self.active(q, data)
        definition = json.loads(row['definition_json'])
        data['targets'] = copy.deepcopy(definition['targets'])
        data['reward']['campaign_id'] = row['id']
        data['account_reward_mode'] = 'once_per_account' if definition['dedupe']=='account' else 'per_character'

    @staticmethod
    def link(q, campaign_id, kind, reference):
        q.execute('INSERT IGNORE INTO dnf_gm.campaign_links(campaign_id,kind,reference_id,created_at) VALUES(%s,%s,%s,%s)',
                  (campaign_id, kind, reference, int(time.time())))

    def eligible(self, q, row, uid, charac_no):
        if not charac_no:
            raise HTTPException(422, '活动人群按角色核对，必须指定角色')
        targets = json.loads(row['definition_json'])['targets']
        from .reward_jobs import RewardJobs
        # Resolve exact account names in the same transaction, without widening them.
        selected, _, _ = RewardJobs(self.db, self.service.settings, self.service).resolve_accounts(q, targets)
        clause, args, _ = RewardJobs.selector(selected)
        candidate = one(q, 'SELECT c.charac_no FROM taiwan_cain.charac_info c '
                        'JOIN d_taiwan.accounts a ON a.UID=c.m_id '
                        'LEFT JOIN taiwan_login.login_account_3 l ON l.m_id=c.m_id '
                        'WHERE c.charac_no=%s AND c.m_id=%s AND ' + clause, (charac_no, uid, *args))
        if not candidate:
            raise HTTPException(409, '目标不符合活动保存的人群条件')

    def claim(self, q, data, op, preview):
        if not data.get('campaign_id'):
            return None
        self.engines(q)
        row = self.active(q, data, True)
        expected = preview.get('campaign')
        if not expected or expected['definition_hash'] != row['definition_hash']:
            raise HTTPException(409, '活动预览绑定缺失或已变化')
        self.eligible(q, row, data['uid'], data.get('charac_no'))
        definition = json.loads(row['definition_json'])
        subject = data['uid'] if definition['dedupe'] == 'account' else data['charac_no']
        old = one(q, 'SELECT operation_id FROM dnf_gm.campaign_claims WHERE campaign_id=%s AND subject_id=%s FOR UPDATE',
                  (row['id'], subject))
        self.link(q, row['id'], 'reward', op)
        result = {**expected, 'subject_id': subject, 'skipped': bool(old),
                  'original_operation_id': old['operation_id'] if old else op}
        if not old:
            q.execute('INSERT INTO dnf_gm.campaign_claims(campaign_id,subject_id,target_uid,charac_no,operation_id,created_at) '
                      'VALUES(%s,%s,%s,%s,%s,%s)', (row['id'], subject, data['uid'], data['charac_no'], op, int(time.time())))
        return result
