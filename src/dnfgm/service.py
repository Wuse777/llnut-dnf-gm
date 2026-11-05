from contextlib import ExitStack
from .mail_content import mail_text
import hashlib
import json
import time
import uuid
import pymysql
from fastapi import HTTPException
from .encoding import inspect_name, mysql_latin1_text
from .catalog import Catalog, snapshot
from . import equipment_unlock as unlock
from . import unlock_center
from .limits import MAIL_GOLD_MAX
from .mail_center import MailCenter
from .write_gate import GameplayWriteGate
from .economy import Economy
from .character_detail import INFO_COLUMNS, ATTRIBUTES, decode_container, profession


CURRENCIES = {'cera': ('taiwan_billing.cash_cera','cera','account',4294967295),
              'cera_point': ('taiwan_billing.cash_cera_point','cera_point','account',4294967295),
              'mileage': ('d_taiwan.member_miles','miles','m_id',2147483647)}
OWNER = 'DNF_GM_WEB'


def dump(d):
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def one(q, sql, args=()):
    q.execute(sql, args)
    return q.fetchone()


def wire_name(s):
    # Mirror the observed game encoding only for explicit outbound game text.
    try:
        return s.encode('utf-8').decode('cp1252')
    except UnicodeError:
        raise HTTPException(422, '此文字含未经验证的客户端编码，请改用英文')


def character(row):
    if row is None:
        return None
    raw = row.pop('client_name_bytes')
    inspected = inspect_name(row['charac_name'], raw)
    return {**row, 'stored_name': row['charac_name'],
            'charac_name': inspected['client_name_candidate'] or row['charac_name'],
            'encoding_state': inspected['name_encoding']}


class Service:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.catalog = Catalog(settings, db)
        self.mail_center = MailCenter(db)
        self.economy = Economy(db)
        self.write_gate = GameplayWriteGate(settings)
        from .support import SupportDesk
        self.support = SupportDesk(db)

    def account(self, q, uid):
        a = one(q, 'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s', (uid,))
        if not a:
            raise HTTPException(404, '账号不存在')
        cash = one(q, 'SELECT cera FROM taiwan_billing.cash_cera WHERE account=%s', (str(uid),))
        points = one(q, 'SELECT cera_point FROM taiwan_billing.cash_cera_point WHERE account=%s', (str(uid),))
        mileage = one(q, 'SELECT miles FROM d_taiwan.member_miles WHERE m_id=%s', (uid,))
        online = one(q, 'SELECT login_status,m_channel_no AS channel FROM taiwan_login.login_account_3 WHERE m_id=%s', (uid,))
        return {**a, 'cera': cash['cera'] if cash else None,
                'cera_point': points['cera_point'] if points else None,
                'mileage': mileage['miles'] if mileage else 0, 'online': online}

    def overview(self):
        with self.db.connect() as c, c.cursor() as q:
            counts = {}
            for key, sql in (
                ('accounts', 'SELECT COUNT(*) n FROM d_taiwan.accounts'),
                ('characters', 'SELECT COUNT(*) n FROM taiwan_cain.charac_info WHERE delete_flag=0'),
                ('online_accounts', 'SELECT COUNT(*) n FROM taiwan_login.login_account_3 WHERE login_status=1')):
                counts[key] = one(q, sql)['n']
        return {'counts': counts, 'server': snapshot(self.settings), 'enabled_writes': list(self.settings.writes),
                'test_uids': list(self.settings.test_uids), 'write_approvals': self.settings.write_approvals,
                'online_definition': 'taiwan_login.login_account_3.login_status=1；不是网络连接数'}

    def accounts(self, text, page, online=False):
        term = '%' + text.replace('\\', '\\\\').replace('%','\\%').replace('_','\\_') + '%'
        with self.db.connect() as c, c.cursor() as q:
            sql = ('SELECT a.UID AS uid,a.accountname,c.cera,p.cera_point,COALESCE(m.miles,0) AS mileage,l.login_status,l.m_channel_no AS channel '
                   'FROM d_taiwan.accounts a LEFT JOIN taiwan_billing.cash_cera c ON c.account=CAST(a.UID AS CHAR) '
                   'LEFT JOIN taiwan_billing.cash_cera_point p ON p.account=CAST(a.UID AS CHAR) '
                   'LEFT JOIN d_taiwan.member_miles m ON m.m_id=a.UID '
                   'LEFT JOIN taiwan_login.login_account_3 l ON l.m_id=a.UID '
                   'WHERE (%s=\'\' OR a.UID=%s OR a.accountname LIKE %s) ')
            if online:
                sql += 'AND l.login_status=1 '
            q.execute(sql + 'ORDER BY a.UID LIMIT 50 OFFSET %s', (text, int(text) if text.isascii() and text.isdigit() and len(text)<11 else 0, term, (page-1)*50))
            return {'items': q.fetchall(), 'page': page}

    def characters(self, uid, text, page):
        term = '%' + text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        # Read-only search must mirror the complete MySQL latin1 mapping,
        # including its five cp1252-undefined bytes (e.g. 风筝 -> 0x9D).
        encoded = '%' + mysql_latin1_text(text.encode('utf-8')).replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT charac_no,m_id AS uid,charac_name,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes,lev,delete_flag '
                      'FROM taiwan_cain.charac_info WHERE (%s=0 OR m_id=%s) AND (%s=\'\' OR charac_no=%s OR charac_name LIKE %s OR charac_name LIKE %s) ORDER BY charac_no LIMIT 50 OFFSET %s',
                      (uid,uid,text,int(text) if text.isascii() and text.isdigit() and len(text)<11 else 0,term,encoded,(page-1)*50))
            return {'items': [character(r) for r in q.fetchall()], 'page': page}

    def audit(self, page, uid=0):
        from .ordinary_reconcile import public_audit
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT id,operation_id,actor,action,target_uid,reason,request_json,result_json,created_at FROM dnf_gm.audit WHERE (%s=0 OR target_uid=%s) ORDER BY id DESC LIMIT 50 OFFSET %s', (uid,uid,(page-1)*50))
            return {'items': [public_audit(r) for r in q.fetchall()], 'page': page}

    def target(self, q, data, lock=False):
        a = self.account(q, data['uid'])
        if data['action'] in ('mail', 'equipment-unlock') or data.get('charac_no'):
            if not data.get('charac_no'):
                raise HTTPException(422, '必须明确指定目标角色')
            row = one(q, 'SELECT m_id AS uid,charac_no,charac_name,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes,delete_flag FROM taiwan_cain.charac_info WHERE charac_no=%s' + (' FOR UPDATE' if lock else ''), (data['charac_no'],))
            if not row or row['uid'] != data['uid'] or row['delete_flag']:
                raise HTTPException(409, '角色不属于该账号或已删除')
            a['character'] = character(row)
        return a

    def unlock_blob(self, q, data, lock=False):
        login = one(q, 'SELECT login_status FROM taiwan_login.login_account_3 WHERE m_id=%s' + (' FOR UPDATE' if lock else ''), (data['uid'],))
        if not login or login['login_status'] != 0:
            raise HTTPException(409, '账号在线或登录状态未知，请完全退出账号后刷新申请')
        row = one(q, 'SELECT item_lock_info FROM taiwan_cain_2nd.charac_item_lock_info WHERE charac_no=%s' + (' FOR UPDATE' if lock else ''), (data['charac_no'],))
        if not row:
            raise HTTPException(409, '角色没有锁定存档')
        return row['item_lock_info']

    def unlock_requests(self, charac_no):
        with self.db.connect() as c, c.cursor() as q:
            row = one(q, 'SELECT m_id AS uid,delete_flag FROM taiwan_cain.charac_info WHERE charac_no=%s', (charac_no,))
            if not row:
                raise HTTPException(404, '角色不存在')
            online = one(q, 'SELECT login_status FROM taiwan_login.login_account_3 WHERE m_id=%s', (row['uid'],))
            stored = one(q, 'SELECT item_lock_info FROM taiwan_cain_2nd.charac_item_lock_info WHERE charac_no=%s', (charac_no,))
            saved=unlock_center.storage(q,charac_no)
            q.execute("SELECT operation_id,result_json,created_at FROM dnf_gm.audit WHERE target_uid=%s AND action='equipment-unlock' ORDER BY id DESC LIMIT 20",(row['uid'],))
            history=q.fetchall()
        result = dict(charac_no=charac_no, uid=row['uid'], login_status=online['login_status'] if online else None,
                      delete_flag=row['delete_flag'], wait_seconds=unlock.WAIT_SECONDS,
                      write_enabled='equipment-unlock' in self.settings.writes, collected_at=time.time(),
                      note='数据库存档快照；在线申请可能尚未保存。锁定编号通过存档锁字段关联穿戴、背包和角色仓库，不是槽位编号；未覆盖时装、宠物独立表。请完全退出账号，处理期间不要登录。', mapping_coverage={k:v['state'] for k,v in saved['containers'].items()},history_limit=20)
        try:
            _, records = unlock.decode(stored['item_lock_info']) if stored else (None, [])
            records=unlock_center.decorate(self,records,saved)
            for r in records:
                r.update(expired=r['state']==2 and r['due_at']<=time.time(),managed_operation=None)
                for entry in history:
                    try:previous=json.loads(entry['result_json'])
                    except (ValueError,TypeError):continue
                    if previous.get('charac_no')!=charac_no:continue
                    if any(x['lock_key']==r['lock_key'] and x['requested_at']==r['requested_at'] and r['state']==2 for x in previous.get('requests_after',[])):
                        r['managed_operation']=previous.get('operation_id',entry['operation_id']);break
            result.update(state='ok', items=records)
        except ValueError as e:
            result.update(state='unsupported', items=[], message=str(e), write_enabled=False)
        return result

    def character_detail(self, charac_no):
        with self.db.connect() as c, c.cursor() as q:
            fields = ','.join('`'+k+'`' for k in INFO_COLUMNS)
            row = one(q, 'SELECT '+fields+',CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes '
                      'FROM taiwan_cain.charac_info WHERE charac_no=%s', (charac_no,))
            if row is None:
                raise HTTPException(404, '角色不存在')
            row['uid'] = row.pop('m_id')
            row = character(row)
            owner = one(q, 'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s', (row['uid'],))
            online = one(q, 'SELECT login_status,m_channel_no AS channel FROM taiwan_login.login_account_3 WHERE m_id=%s', (row['uid'],))
            inventory = one(q, 'SELECT money,coin,inventory_capacity,inventory,equipslot FROM taiwan_cain_2nd.inventory WHERE charac_no=%s', (charac_no,))
            play_state = one(q, 'SELECT exp,fatigue,used_fatigue,last_play_time FROM taiwan_cain.charac_stat WHERE charac_no=%s', (charac_no,))
            storage = one(q, 'SELECT cargo,cargo_capacity FROM taiwan_cain_2nd.charac_inven_expand WHERE charac_no=%s', (charac_no,))
            # Account ownership comes only from charac_info, never a caller-supplied UID.
            account_storage = one(q, 'SELECT money,capacity,cargo,occ_time FROM taiwan_cain.account_cargo WHERE m_id=%s', (row['uid'],))
        equipment = decode_container(inventory['equipslot'] if inventory else None, True)
        backpack = decode_container(inventory['inventory'] if inventory else None)
        warehouse = decode_container(storage['cargo'] if storage else None)
        warehouse.update(owner_uid=row['uid'], charac_no=charac_no,
                         capacity_raw=storage['cargo_capacity'] if storage else None)
        account_warehouse = decode_container(account_storage['cargo'] if account_storage else None)
        account_warehouse.update(owner_uid=row['uid'],
            capacity_raw=account_storage['capacity'] if account_storage else None,
            gold=account_storage['money'] if account_storage else None,
            gold_state='ok' if account_storage else 'missing',
            stored_at=account_storage['occ_time'] if account_storage else None)
        containers = (equipment, backpack, warehouse, account_warehouse)
        labels = self.catalog.read_labels([i['id'] for group in containers for i in group['items']])
        for group in containers:
            for item in group['items']:
                meta = labels['items'].get(item['id'])
                item.update(name=meta['name'] if meta else f"未知物品 #{item['id']}",
                            catalog_known=bool(meta),level=meta['level'] if meta else None)
        art_sha=self.settings.pvf_sha256 if labels['state']=='ok' else ''
        self.catalog.assets.decorate(art_sha,[i for group in containers for i in group['items']])
        portrait=self.catalog.assets.portrait(art_sha,row['job'],row['grow_type'],row['sex'])
        attrs = [{'key':key,'label':label,'value':row.pop(key)} for key,label in ATTRIBUTES.items()]
        return {'character':row, 'portrait':portrait, 'assets':self.catalog.assets.status(art_sha), 'account':owner, 'account_online':online, 'play_state':play_state,
                'profession':profession(row['job'],row['grow_type'],labels['jobs']),
                'attributes':attrs, 'wealth':{'state':'ok' if inventory else 'missing',
                    'gold':inventory['money'] if inventory else None,
                    'revival_coin_raw':inventory['coin'] if inventory else None,
                    'inventory_capacity_raw':inventory['inventory_capacity'] if inventory else None},
                'equipment':equipment, 'backpack':backpack, 'warehouse':warehouse,
                'account_warehouse':account_warehouse, 'catalog_state':labels['state'],
                'collected_at':time.time(), 'read_only':True,
                'snapshot_note':'数据库存档快照，不是在线实时战斗面板；在线变化可能尚未保存。属性为原始字段值，未叠加装备、技能和临时效果。未解析的属性不猜测。'}

    def preview(self, session_hash, data):
        action = data['action']
        if not data['reason'].strip():
            raise HTTPException(422, '必须填写原因')
        gold = data.get('gold', 0)
        if data.get('mail_title') and action not in ('mail','reward'):
            raise HTTPException(422,'邮件标题仅用于邮件或组合奖励')
        if data.get('template_overrides') is not None and action not in ('mail','reward'):
            raise HTTPException(422,'临时奖励仅用于模板邮件或组合奖励')
        if type(gold) is not int or not 0 <= gold <= MAIL_GOLD_MAX or (action not in ('mail','reward') and gold):
            raise HTTPException(422, '金币附件仅用于邮件，金额须为0至10亿的整数')
        if action == 'currency' and (data.get('currency') not in CURRENCIES or not data.get('delta') or data.get('items') or data.get('template_id')):
            raise HTTPException(422, '请选择币种及非零变更金额，不可混合发放')
        if action != 'currency' and (data.get('currency') is not None or data.get('delta') is not None):
            raise HTTPException(422, '操作类型与参数不一致')
        if action!='reward' and self.currency_rewards(data):
            raise HTTPException(422,'账号奖励仅用于组合奖励操作')
        keys = data.get('lock_keys', [])
        if action == 'equipment-unlock':
            if data.get('items') or data.get('template_id') or data.get('template_version') or gold:
                raise HTTPException(422, '提前解锁不可混合邮件参数')
            if not keys or len(set(keys)) != len(keys) or any(type(k) is not int or not 1 <= k <= 100 for k in keys):
                raise HTTPException(422, '请选择有效且不重复的解锁申请编号')
        elif keys:
            raise HTTPException(422, '申请编号仅用于装备解锁')
        with self.db.connect() as c, c.cursor() as q:
            resolved=self.reward_snapshot(q,data) if action in ('mail','reward') else None
            if resolved and resolved['has_mail'] and not data.get('charac_no'):
                raise HTTPException(422,'邮件奖励必须明确指定目标角色')
            a = self.target(q, data)
            preview = {'target': a, 'action': action, 'reason': data['reason'], 'client_verified': False}
            if action == 'equipment-unlock':
                preview.update(unlock_center.prepare(self,q,data))
            if action == 'currency':
                before = a[data['currency']]
                if before is None or not 0 <= before + data['delta'] <= CURRENCIES[data['currency']][3]:
                    raise HTTPException(422, '余额不足、缺失或超出字段范围')
                preview.update(currency=data['currency'], before=before, after=before+data['delta'])
            if resolved:
                preview.update(resolved)
            if action=='reward':
                balances={}
                for currency,delta in self.currency_rewards(data).items():
                    before=a[currency]
                    if before is None or not 0<=before+delta<=CURRENCIES[currency][3]:
                        raise HTTPException(422,'余额缺失或超出字段范围')
                    balances[currency]={'before':before,'after':before+delta,'delta':delta}
                preview['balances']=balances
            if action in ('ban','unban'):
                punishment = one(q, 'SELECT apply_flag,admin_id,reason,end_time FROM d_taiwan.member_punish_info WHERE m_id=%s AND punish_type=1', (data['uid'],))
                preview['punishment'] = punishment
                owned = one(q, 'SELECT marker FROM dnf_gm.owned_bans WHERE uid=%s', (data['uid'],))
                if punishment and (not owned or punishment['admin_id'] != OWNER or punishment['reason'] != owned['marker']):
                    raise HTTPException(409, '存在非本后台处罚，禁止覆盖')
                if action == 'unban' and (not punishment or not punishment['apply_flag']):
                    raise HTTPException(409, '没有本后台创建的有效处罚')
            support=self.support.reward_preview(q,data)
            if support is not None:preview['support_case']=support
            op = uuid.uuid4().hex
            fingerprint = hashlib.sha256(dump({'request':data,'preview':preview}).encode()).hexdigest()
            t = int(time.time())
            q.execute('INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,\'preview\',%s,%s)',
                      (op,session_hash,fingerprint,action,dump(data),dump(preview),t,t+300))
            c.commit()
        return {'operation_id': op,'preview':preview,'expires_at':t+300,'write_enabled':self.write_enabled(data,preview)}

    def operation(self, session_hash, op):
        with self.db.connect() as c, c.cursor() as q:
            row = one(q, 'SELECT operation_id,action,status,request_json,preview_json,result_json,expires_at FROM dnf_gm.operations WHERE operation_id=%s', (op,))
            if not row:
                # Capability changes have their own transaction/receipt, not a
                # game-operation preview. Audit lookup must still resolve the
                # original ID without creating a confirmable game operation.
                policy = one(q, '''SELECT r.result_json,r.created_at,a.reason,a.request_json
                    FROM dnf_gm.capability_requests r JOIN dnf_gm.audit a
                      ON a.operation_id=r.request_id AND a.action='capability-policy'
                    WHERE r.request_id=%s LIMIT 1''', (op,))
                if not policy:
                    raise HTTPException(404, '操作不存在')
                return {'operation_id':op,'action':'capability-policy','status':'committed',
                        'request':{**json.loads(policy['request_json']),'reason':policy['reason']},
                        'preview':None,'expires_at':None,'created_at':policy['created_at'],
                        'result':json.loads(policy['result_json']),'failure_attempts':[]}
            row['request'] = json.loads(row.pop('request_json'))
            q.execute('SELECT error_type,created_at FROM dnf_gm.failures WHERE operation_id=%s ORDER BY id DESC LIMIT 20', (op,))
            row['failure_attempts'] = q.fetchall()
            row['failure_note'] = '历史尝试错误不代表当前操作最终失败；以本操作状态为准。'
            row['preview'] = json.loads(row.pop('preview_json'))
            row['result'] = json.loads(row.pop('result_json') or 'null')
            if row['result'] and row['action'] in ('mail','reward'):
                ids = row['result'].get('postal_ids',[])
                if ids:
                    q.execute('SELECT postal_id,receive_time,delete_flag,gold FROM taiwan_cain_2nd.postal WHERE postal_id IN ('+','.join(['%s']*len(ids))+')', ids)
                    row['delivery_records'] = q.fetchall()
                    row['delivery_records_truncated'] = bool(row['result'].get('postal_ids_truncated'))
                    row['delivery_note'] = ('仅显示前20条投递记录；' if row['delivery_records_truncated'] else '') + '仅数据库领取标记，不等于客户端已正确领取'
            return row

    def confirm(self, session_hash, op, key):
        commit_attempted = False
        try:
            with ExitStack() as gates, self.db.connect() as c, c.cursor() as q:
                row = one(q, 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s AND session_hash=%s FOR UPDATE', (op,session_hash))
                if not row:
                    raise HTTPException(404, '操作不存在')
                if row['action'].startswith('item-') or row['action'] in ('char-fatigue','char-rename'):
                    raise HTTPException(409, '存档操作请使用专用确认入口')
                if row['action'].startswith('native-'):
                    raise HTTPException(409, '原生控制请使用专用确认入口')
                if row['action'] in ('maintenance','maint-close','maint-recover'):
                    raise HTTPException(409, '维护申请请使用专用确认入口')
                if row['action'] == 'cleanup-release':
                    raise HTTPException(409, '旧产物清理请使用专用确认入口')
                old = one(q, 'SELECT operation_id,fingerprint,session_hash,result_json FROM dnf_gm.operations WHERE idempotency_key=%s', (key,))
                if old:
                    if old['fingerprint'] != row['fingerprint'] or old['session_hash'] != session_hash or old['operation_id'] != op:
                        raise HTTPException(409, '幂等键参数冲突')
                    if old['result_json']:
                        return json.loads(old['result_json'])
                if row['status'] == 'committed':
                    if row['idempotency_key'] != key:
                        raise HTTPException(409, '此操作已由其他幂等键完成')
                    return json.loads(row['result_json'])
                if row['expires_at'] < int(time.time()):
                    raise HTTPException(409, '预览已过期，请重新预览')
                data, preview = json.loads(row['request_json']), json.loads(row['preview_json'])
                action = data['action']
                if action == 'catalog-policy':
                    result = self.confirm_policy(c,q,row,data,preview,key)
                    commit_attempted = True
                    c.commit()
                    return result
                lease=gates.enter_context(self.write_gate.writer())
                lease.protect_transaction(q)
                if action == 'unlock-batch':
                    result=unlock_center.UnlockCenter(self).confirm(q,row,data,preview,key)
                    lease.check()
                    commit_attempted=True
                    c.commit()
                    return result
                self.check_write(q,data,preview)
                q.execute('UPDATE dnf_gm.operations SET idempotency_key=%s WHERE operation_id=%s', (key,op))
                if action=='equipment-unlock':unlock_center.lock_accounts(q,[data])
                account = self.target(q, data, lock=True)
                if account['accountname'] != preview['target']['accountname'] or (action=='equipment-unlock' and account['character']['charac_name']!=preview['target']['character']['charac_name']):
                    raise HTTPException(409, '目标身份变化，重新预览')
                support=self.support.reward_preview(q,data,lock=True)
                if support != preview.get('support_case'):raise HTTPException(409,'关联问题记录或补偿次数已变化，请重新预览')
                result = {'operation_id':op,'uid':data['uid'],'action':action,'client_verified':False}
                if action == 'currency':
                    result.update(self.apply_currency(q,data,preview['before']))
                elif action == 'equipment-unlock':
                    result.update(unlock_center.apply(self,q,data,preview))
                elif action == 'mail':
                    result.update(self.apply_mail(q,op,data,preview,account))
                elif action == 'reward':
                    result.update(self.apply_reward(q,op,data,preview,account,exact_balances=True))
                else:
                    existing = one(q, 'SELECT apply_flag,admin_id,reason FROM d_taiwan.member_punish_info WHERE m_id=%s AND punish_type=1 FOR UPDATE', (data['uid'],))
                    own = one(q, 'SELECT marker FROM dnf_gm.owned_bans WHERE uid=%s FOR UPDATE', (data['uid'],))
                    if existing and (not own or existing['admin_id'] != OWNER or existing['reason'] != own['marker']):
                        raise HTTPException(409, '处罚来源变化，禁止覆盖')
                    if action == 'ban':
                        if existing and existing['apply_flag']:
                            raise HTTPException(409, '已被本后台封禁，请重新预览')
                        marker = 'GM-' + op
                        if existing:
                            q.execute("UPDATE d_taiwan.member_punish_info SET apply_flag=1,start_time=UTC_TIMESTAMP(),end_time='2099-01-01',admin_id=%s,reason=%s WHERE m_id=%s AND punish_type=1", (OWNER,marker,data['uid']))
                        else:
                            q.execute("INSERT INTO d_taiwan.member_punish_info(m_id,punish_type,occ_time,punish_value,apply_flag,start_time,end_time,admin_id,reason) VALUES(%s,1,UTC_TIMESTAMP(),1,1,UTC_TIMESTAMP(),'2099-01-01',%s,%s)", (data['uid'],OWNER,marker))
                        q.execute('INSERT INTO dnf_gm.owned_bans(uid,marker) VALUES(%s,%s) ON DUPLICATE KEY UPDATE marker=VALUES(marker)', (data['uid'],marker))
                    else:
                        if not existing or not own or not existing['apply_flag']:
                            raise HTTPException(409, '没有本后台有效封禁')
                        q.execute('UPDATE d_taiwan.member_punish_info SET apply_flag=0 WHERE m_id=%s AND punish_type=1 AND admin_id=%s AND reason=%s AND apply_flag=1', (data['uid'],OWNER,own['marker']))
                        if q.rowcount != 1:
                            raise HTTPException(409, '解封条件未命中')
                    result.update(blocked=action=='ban',state='database_updated_login_test_pending',does_not_kick_online_player=True)
                self.support.attach_reward(q,data,op,preview)
                if support is not None:result['support_case_id']=support['case_id']
                q.execute('INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,\'owner\',%s,%s,%s,%s,%s)',
                          (op,action,data['uid'],data['reason'],dump(data),dump(result)))
                if action in ('currency','mail','reward'):self.economy.record(q,op)
                q.execute("UPDATE dnf_gm.operations SET status='committed',result_json=%s WHERE operation_id=%s", (dump(result),op))
                lease.check()
                commit_attempted = True
                c.commit()
                return result
        except Exception as error:
            # Closing connection rolls back pre-commit errors. Do not replay writes.
            if not commit_attempted:
                try:
                    with self.db.connect() as c, c.cursor() as q:
                        q.execute('INSERT INTO dnf_gm.failures(operation_id,error_type) VALUES(%s,%s)', (op,type(error).__name__))
                        c.commit()
                except Exception:
                    pass
            if commit_attempted:
                raise HTTPException(503, '提交结果待确认，请按原操作编号查询，禁止自动重放') from None
            if isinstance(error, pymysql.IntegrityError):
                raise HTTPException(409, '操作编号或幂等键冲突，请查询原结果') from None
            raise

    def templates(self, text='', page=1, category=''):
        term = '%' + text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        with self.db.connect() as c, c.cursor() as q:
            q.execute("SELECT t.id,t.name,t.current_version,t.enabled,v.payload_json FROM dnf_gm.gift_templates t JOIN dnf_gm.gift_versions v ON t.id=v.template_id AND t.current_version=v.version WHERE (%s='' OR t.name LIKE %s OR t.id=%s) AND (%s='' OR JSON_UNQUOTE(JSON_EXTRACT(v.payload_json,'$.category'))=%s) ORDER BY t.id DESC LIMIT 50 OFFSET %s",
                      (text, term, int(text) if text.isascii() and text.isdigit() and len(text)<11 else 0, category, category, (page-1)*50))
            rows = q.fetchall()
        items = []
        for row in rows:
            rewards = json.loads(row.pop('payload_json'))
            with self.db.connect() as con, con.cursor() as cursor:
                rewards['items'] = self.catalog.describe(rewards['items'],q=cursor)
            items.append({**row, 'rewards':rewards})
        return {'items':items, 'page':page}

    def template_versions(self, template_id, page=1):
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT version,payload_json,created_at FROM dnf_gm.gift_versions WHERE template_id=%s ORDER BY version DESC LIMIT 51 OFFSET %s', (template_id,(page-1)*50))
            rows = q.fetchall()
        return {'items':[{'version':r['version'],'created_at':r['created_at'],'payload':json.loads(r['payload_json'])} for r in rows[:50]],'has_more':len(rows)>50,'page':page}

    def save_template(self, template_id, data):
        # Management-only metadata, never a game write; catalog validates boundaries.
        if not data['name'].strip():
            raise HTTPException(422, '模板名称不能为空')
        with self.db.connect() as c, c.cursor() as q:
            gold = data.get('gold') or 0
            self.catalog.items(data['items'], active=False, q=q, allow_empty=bool(gold or self.currency_rewards(data)))
            wire_name(mail_text(data))
            if template_id:
                old = one(q, 'SELECT current_version FROM dnf_gm.gift_templates WHERE id=%s FOR UPDATE', (template_id,))
                if not old or old['current_version'] != data['expected_version']:
                    raise HTTPException(409, '模板版本变化')
                version = old['current_version']+1
                q.execute('UPDATE dnf_gm.gift_templates SET name=%s,enabled=%s,current_version=%s WHERE id=%s', (data['name'],int(data['enabled']),version,template_id))
            else:
                if data['expected_version'] != 0:
                    raise HTTPException(422, '新模板版本必须为0')
                version = 1
                q.execute('INSERT INTO dnf_gm.gift_templates(name,current_version,enabled) VALUES(%s,1,%s)', (data['name'],int(data['enabled'])))
                template_id = q.lastrowid
            q.execute('INSERT INTO dnf_gm.gift_versions(template_id,version,payload_json) VALUES(%s,%s,%s)', (template_id,version,dump({k:data[k] for k in ('items','gold','mail_title','message','category','name','enabled','currency_rewards') if k in data and data[k] is not None})))
            result = {'id':template_id,'version':version,'enabled':data['enabled']}
            q.execute('INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,\'owner\',\'gift-template\',\'模板版本变更\',%s,%s)', (uuid.uuid4().hex,dump(data),dump(result)))
            c.commit()
            return result


    def preview_policy(self, session_hash, data):
        data['action'] = 'catalog-policy'
        if not data['reason'].strip():
            raise HTTPException(422, '必须填写策略操作原因')
        # Item overrides ignore potentially stale table filters, by explicit id.
        if data.get('item_id') is not None:
            data['filters'] = {'q':str(data['item_id']), 'category':'', 'allowed_only':False, 'state':''}
        with self.db.connect() as c, c.cursor() as q:
            summary, _ = self.catalog.selection(q,data)
            if not summary['affected']:
                raise HTTPException(422, '没有需要变更的索引物品，请检查筛选条件及当前策略')
            op, t = uuid.uuid4().hex, int(time.time())
            fingerprint = hashlib.sha256(dump({'request':data,'preview':summary}).encode()).hexdigest()
            q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,'catalog-policy',%s,%s,'preview',%s,%s)", (op,session_hash,fingerprint,dump(data),dump(summary),t,t+300))
            c.commit()
        return {'operation_id':op,'preview':summary,'expires_at':t+300,'write_enabled':True}

    def confirm_policy(self, c, q, row, data, preview, key):
        # Global state row serializes policy writes against mail/template checks.
        # All changes, audit and idempotency commit on this same MySQL connection.
        q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','catalog_policy_state','catalog_policy_items')")
        engines = q.fetchall()
        if len(engines) != 4 or any(e['ENGINE'] != 'InnoDB' for e in engines):
            raise HTTPException(409, '策略事务表引擎不满足，拒绝变更')
        summary, affected = self.catalog.selection(q,data,lock=True)
        if summary != preview:
            raise HTTPException(409, '筛选结果、PVF或策略版本变化，请重新预览')
        op, revision = row['operation_id'],summary['policy_revision']+1
        for start in range(0,len(affected),250):
            q.executemany('INSERT INTO dnf_gm.catalog_policy_items(pvf_sha256,item_id,enabled,reason,revision) VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE enabled=VALUES(enabled),reason=VALUES(reason),revision=VALUES(revision)',
                          [(summary['pvf_sha256'],i,int(data['enabled']),data['reason'],revision) for i in affected[start:start+250]])
        q.execute('UPDATE dnf_gm.catalog_policy_state SET revision=%s WHERE id=1', (revision,))
        result = {**summary,'policy_revision':revision,'enabled':data['enabled'],'operation_id':op,'action':'catalog-policy','state':'committed','client_verified':False}
        q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','catalog-policy',%s,%s,%s)", (op,data['reason'],dump(data),dump(result)))
        q.execute("UPDATE dnf_gm.operations SET status='committed',idempotency_key=%s,result_json=%s WHERE operation_id=%s",(key,dump(result),op))
        return result


    def apply_currency(self,q,data,expected_balance=None):
        result={}
        table,column,identity,maximum = CURRENCIES[data['currency']]
        if data['currency'] == 'mileage':
            engine = one(q, "SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='d_taiwan' AND TABLE_NAME='member_miles'")
            if not engine or engine['ENGINE'] != 'InnoDB':
                raise HTTPException(409, '积分表不支持事务，拒绝写入')
            # New accounts need no synthetic personal information;
            # only the game's minimal mileage row is initialized.
            q.execute('INSERT INTO d_taiwan.member_miles(m_id,miles,daily_miles) VALUES(%s,0,0) ON DUPLICATE KEY UPDATE m_id=VALUES(m_id)', (data['uid'],))
        balance = one(q, f'SELECT {column} FROM {table} WHERE {identity}=%s FOR UPDATE', (str(data['uid']),))
        if not balance or (expected_balance is not None and balance[column] != expected_balance):
            raise HTTPException(409, '余额变化，必须重新预览')
        after = balance[column] + data['delta']
        if not 0 <= after <= maximum:
            raise HTTPException(409, '余额不足或字段溢出')
        timestamp = '' if data['currency'] == 'mileage' else ',mod_date=UTC_TIMESTAMP()'
        q.execute(f'UPDATE {table} SET {column}=%s{timestamp} WHERE {identity}=%s AND {column}=%s', (after,str(data['uid']),balance[column]))
        if q.rowcount != 1:
            raise HTTPException(409, '条件更新未命中')
        result.update(currency=data['currency'],before=balance[column],after=after,state='database_committed_refresh_client')
        return result

    def apply_mail(self,q,op,data,preview,account):
        result={}
        gold = data.get('gold', 0)
        if type(gold) is not int or not 0 <= gold <= MAIL_GOLD_MAX or gold != preview.get('gold', 0):
            raise HTTPException(409, '金币附件参数变化，请重新预览')
        rewards = self.catalog.items([{'id':i['id'],'quantity':i['quantity']} for i in preview['rewards']['items']], q=q, allow_empty=gold > 0)
        if rewards != preview['rewards']:
            raise HTTPException(409, '索引或物品版本变化')
        if data.get('template_id'):
            t = one(q, 'SELECT current_version,enabled FROM dnf_gm.gift_templates WHERE id=%s FOR UPDATE', (data['template_id'],))
            if not t or not t['enabled'] or t['current_version'] != data['template_version']:
                raise HTTPException(409, '礼包已更改或停用')
        q.execute('INSERT INTO taiwan_cain_2nd.letter(charac_no,send_charac_name,letter_text,reg_date,stat) VALUES(%s,\'GM\',%s,UTC_TIMESTAMP(),0)', (data['charac_no'],wire_name(mail_text(data))))
        letter_id, postal_ids, postal_count = q.lastrowid, [], 0
        # Gold belongs to the letter, carried ONCE by its first postal row.
        # A gold-only letter uses item_id/add_info/endurance=0, not a PVF coin item.
        deliveries = rewards['items'] or [{'id':0,'quantity':0,'category':'gold','durability':0}]
        kinds = {item.get('mail_kind') for item in deliveries} & {'avatar','creature'}
        if kinds:
            tables = {'avatar':'user_items','creature':'creature_items'}
            for kind in kinds:
                engine = one(q, "SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME=%s", (tables[kind],))
                if not engine or engine['ENGINE'] != 'InnoDB':
                    raise HTTPException(409, '特殊物品存储表不支持事务，拒绝发放')
        for item in deliveries:
            kind = item.get('mail_kind', 'stackable')
            # Equipment/avatar/creature quantities are COPY counts,
            # not stacks or foreign IDs. Persist each copy natively.
            copies = item['quantity'] if kind in ('equipment','avatar','creature') else 1
            for _ in range(copies):
                add_info = 0 if kind == 'equipment' else item['quantity']
                if kind == 'avatar':
                    q.execute("INSERT INTO taiwan_cain_2nd.user_items(charac_no,it_id,jewel_socket,expire_date,reg_date,obtain_from,stat) VALUES(%s,%s,%s,'9999-12-31 00:00:00',UTC_TIMESTAMP(),1,2)", (data['charac_no'],item['id'],b'\0'*30))
                    add_info = q.lastrowid
                elif kind == 'creature':
                    q.execute('INSERT INTO taiwan_cain_2nd.creature_items(charac_no,it_id,reg_date,stomach,creature_type) VALUES(%s,%s,UTC_TIMESTAMP(),100,%s)', (data['charac_no'],item['id'],item['creature_type']))
                    add_info = q.lastrowid
                q.execute('INSERT INTO taiwan_cain_2nd.postal(occ_time,send_charac_name,receive_charac_no,item_id,add_info,endurance,gold,letter_id,avata_flag,creature_flag) VALUES(UTC_TIMESTAMP(),\'GM\',%s,%s,%s,%s,%s,%s,%s,%s)',
                          (data['charac_no'],item['id'],add_info,item['durability'] if kind == 'equipment' else 0,gold if postal_count == 0 else 0,letter_id,int(kind == 'avatar'),int(kind == 'creature')))
                # Keep result/audit memory independent of copy count.
                # All actual records remain queryable by letter_id.
                postal_id = q.lastrowid
                if len(postal_ids) < 20:
                    postal_ids.append(postal_id)
                postal_count += 1
                q.execute('INSERT INTO dnf_gm.mail_deliveries(operation_id,ordinal,postal_id,item_id,quantity,gold) VALUES(%s,%s,%s,%s,%s,%s)',
                          (op,postal_count,postal_id,item['id'],1 if kind in ('equipment','avatar','creature') else item['quantity'],gold if postal_count == 1 else 0))
        q.execute('INSERT INTO dnf_gm.mail_batches(operation_id,target_uid,charac_no,account_name,character_name,letter_id,postal_count,recorded_count,message,request_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (op,data['uid'],data['charac_no'],account['accountname'],account['character']['charac_name'],letter_id,postal_count,postal_count,mail_text(data),dump({**data,'items':[{'id':i['id'],'quantity':i['quantity']} for i in rewards['items']]})))
        result.update(letter_id=letter_id,postal_ids=postal_ids,postal_count=postal_count,postal_ids_truncated=postal_count>len(postal_ids),items=rewards,gold=gold,template_id=data.get('template_id'),template_version=data.get('template_version'),state='database_delivered_not_claimed')
        return result

    def check_write(self,q,data,preview):
        if not self.write_enabled(data,preview):
            raise HTTPException(403, '该写入功能未激活；代码已实现但尚未验收')
        live = snapshot(self.settings)
        if not live.get('fresh') or not live.get('core_ok') or live.get('image_digest') != self.settings.image_digest:
            raise HTTPException(503, '实时服务状态未知、核心接口异常或镜像变化，拒绝写入')
        if live.get('mem_available_mib', 0) < 256 or live.get('swap_free_mib', 0) < 1536:
            raise HTTPException(503, '资源保护阈值触发，拒绝写入')
        if self.settings.test_uids and data['uid'] not in self.settings.test_uids:
            raise HTTPException(403, '当前仅允许测试账号写入')
        # Verify expected transactional engines; never mutate schema.
        q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','owned_bans','catalog_policy_state','catalog_policy_items','mail_batches','mail_deliveries')) OR (TABLE_SCHEMA='taiwan_billing' AND TABLE_NAME IN ('cash_cera','cash_cera_point')) OR (TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME IN ('letter','postal')) OR (TABLE_SCHEMA='d_taiwan' AND TABLE_NAME='member_punish_info')")
        engines = q.fetchall()
        if len(engines) != 12 or any(r['ENGINE'] != 'InnoDB' for r in engines):
            raise HTTPException(409, '事务表结构基线不满足，拒绝写入')

    @staticmethod
    def currency_rewards(data):
        amounts=data.get('currency_rewards') or {}
        if (not isinstance(amounts,dict) or set(amounts)-set(CURRENCIES)
                or any(type(v) is not int or not 0<=v<=1000000000 for v in amounts.values())):
            raise HTTPException(422,'组合奖励币种金额须为0至10亿的整数')
        return {key:amounts[key] for key in CURRENCIES if amounts.get(key)}

    def write_enabled(self,data,preview):
        action=data['action']
        if action!='reward':return action in self.settings.writes
        required={'reward'}
        if data.get('currency_rewards'):required.add('currency')
        if preview.get('has_mail'):required.add('mail')
        return required<=set(self.settings.writes)

    def reward_snapshot(self,q,data):
        """Resolve a versioned reward once, retaining its source template identity."""
        amounts=self.currency_rewards(data)
        attachments=data.get('items',[])
        gold=data.get('gold',0)
        overrides=data.get('template_overrides')
        if overrides is not None and not data.get('template_id'):
            raise HTTPException(422,'临时调整必须保留来源模板和版本')
        if data.get('template_id'):
            if attachments or not data.get('template_version'):
                raise HTTPException(422,'模板发放必须指定版本；临时附件请使用临时调整内容')
            t=one(q,'SELECT t.enabled,t.current_version,v.payload_json FROM dnf_gm.gift_templates t JOIN dnf_gm.gift_versions v ON v.template_id=t.id AND v.version=%s WHERE t.id=%s',(data['template_version'],data['template_id']))
            if not t or not t['enabled'] or t['current_version']!=data['template_version']:
                raise HTTPException(409,'礼包已停用或版本已变化')
            payload=json.loads(t['payload_json'])
            if overrides is not None:
                # Revalidate even when called by a persisted scheduled/batch task.
                from .models import RewardOverrides
                from pydantic import ValidationError
                try: overrides=RewardOverrides.model_validate(overrides).model_dump()
                except ValidationError:
                    raise HTTPException(422,'临时奖励格式无效') from None
                data['template_overrides']=overrides
                payload=overrides
            attachments=payload['items']
            for key,default in (('gold',0),('message','GM rewards'),('mail_title','')):
                if key in payload or key=='mail_title':
                    value=payload.get(key,default)
                    if data.get(key,default) not in (default,value):
                        raise HTTPException(409,'奖励内容冲突，请重新预览')
                    data[key]=value
            gold=data.get('gold',0)
            bound=self.currency_rewards(payload)
            if amounts and amounts!=bound:
                raise HTTPException(409,'账号奖励内容冲突，请重新预览')
            amounts=bound
        if amounts and data['action']!='reward':
            raise HTTPException(422,'含点券/代币券/积分的礼包请使用组合奖励操作')
        if not attachments and not gold and not amounts:
            raise HTTPException(422,'奖励至少包含物品、金币或账号币种一项')
        has_mail=bool(attachments or gold)
        if has_mail:wire_name(mail_text(data))
        # Same PVF/policy contract as mail, even for a currency-only versioned gift.
        rewards=self.catalog.items(attachments,q=q,allow_empty=bool(gold or amounts))
        if data['action']=='reward':data['currency_rewards']=amounts
        # Legacy schedules bind this exact shape. Their saved requests lack the
        # new field: do not add display metadata that invalidates that binding.
        return {'gold':gold,'rewards':rewards,'has_mail':has_mail,
                **({'mail_title':data['mail_title'],'mail_text':mail_text(data)} if has_mail and data.get('mail_title') else {}),
                **({'template_source':{'id':data['template_id'],'version':data['template_version'],
                                      'adjusted':overrides is not None}} if data.get('template_id') and 'template_overrides' in data else {})}

    def apply_reward(self,q,op,data,preview,account,exact_balances=False):
        # Validate the frozen catalogue/template even for currency-only rewards.
        rewards=self.catalog.items([{'id':i['id'],'quantity':i['quantity']} for i in preview['rewards']['items']],q=q,allow_empty=True)
        if rewards!=preview['rewards']:
            raise HTTPException(409,'索引或物品版本变化')
        if data.get('template_id'):
            t=one(q,'SELECT current_version,enabled FROM dnf_gm.gift_templates WHERE id=%s FOR UPDATE',(data['template_id'],))
            if not t or not t['enabled'] or t['current_version']!=data['template_version']:
                raise HTTPException(409,'礼包已更改或停用')
        balances={}
        for currency,delta in self.currency_rewards(data).items():
            expected=preview['balances'][currency]['before'] if exact_balances else None
            balances[currency]=self.apply_currency(q,{'uid':data['uid'],'currency':currency,'delta':delta},expected)
        result={'currency_rewards':balances,'state':'database_reward_committed','client_verified':False}
        if preview.get('template_source'):result['template_source']=preview['template_source']
        if preview['has_mail']:
            result.update(self.apply_mail(q,op,data,preview,account))
            result['state']='database_reward_committed'
        return result
