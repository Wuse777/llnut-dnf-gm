import hashlib
import json
import time
import uuid
import pymysql
from fastapi import HTTPException
from .encoding import inspect_name, mysql_latin1_text
from .catalog import Catalog, snapshot
from . import equipment_unlock as unlock
from .limits import MAIL_GOLD_MAX
from .character_detail import INFO_COLUMNS, ATTRIBUTES, decode_container, profession


CURRENCIES = {'cera': ('cash_cera','cera'), 'cera_point': ('cash_cera_point','cera_point')}
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

    def account(self, q, uid):
        a = one(q, 'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s', (uid,))
        if not a:
            raise HTTPException(404, '账号不存在')
        cash = one(q, 'SELECT cera FROM taiwan_billing.cash_cera WHERE account=%s', (str(uid),))
        points = one(q, 'SELECT cera_point FROM taiwan_billing.cash_cera_point WHERE account=%s', (str(uid),))
        online = one(q, 'SELECT login_status,m_channel_no AS channel FROM taiwan_login.login_account_3 WHERE m_id=%s', (uid,))
        return {**a, 'cera': cash['cera'] if cash else None,
                'cera_point': points['cera_point'] if points else None, 'online': online}

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
            sql = ('SELECT a.UID AS uid,a.accountname,c.cera,p.cera_point,l.login_status,l.m_channel_no AS channel '
                   'FROM d_taiwan.accounts a LEFT JOIN taiwan_billing.cash_cera c ON c.account=CAST(a.UID AS CHAR) '
                   'LEFT JOIN taiwan_billing.cash_cera_point p ON p.account=CAST(a.UID AS CHAR) '
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
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT id,operation_id,actor,action,target_uid,reason,request_json,result_json,created_at FROM dnf_gm.audit WHERE (%s=0 OR target_uid=%s) ORDER BY id DESC LIMIT 50 OFFSET %s', (uid,uid,(page-1)*50))
            return {'items': q.fetchall(), 'page': page}

    def target(self, q, data, lock=False):
        a = self.account(q, data['uid'])
        if data['action'] in ('mail', 'equipment-unlock'):
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
        result = dict(charac_no=charac_no, uid=row['uid'], login_status=online['login_status'] if online else None,
                      delete_flag=row['delete_flag'], wait_seconds=unlock.WAIT_SECONDS,
                      write_enabled='equipment-unlock' in self.settings.writes, collected_at=time.time(),
                      note='数据库存档快照；在线申请可能尚未保存。编号是锁定记录编号，未验证与物品槽位的映射。请完全退出账号，处理期间不要登录。')
        try:
            _, records = unlock.decode(stored['item_lock_info']) if stored else (None, [])
            result.update(state='ok', items=[dict(r, expired=r['state']==2 and r['due_at']<=time.time()) for r in records])
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
        equipment = decode_container(inventory['equipslot'] if inventory else None, True)
        backpack = decode_container(inventory['inventory'] if inventory else None)
        labels = self.catalog.read_labels([i['id'] for group in (equipment,backpack) for i in group['items']])
        for group in (equipment,backpack):
            for item in group['items']:
                meta = labels['items'].get(item['id'])
                item.update(name=meta['name'] if meta else f"未知物品 #{item['id']}",
                            catalog_known=bool(meta),level=meta['level'] if meta else None)
        attrs = [{'key':key,'label':label,'value':row.pop(key)} for key,label in ATTRIBUTES.items()]
        return {'character':row, 'account':owner, 'account_online':online, 'play_state':play_state,
                'profession':profession(row['job'],row['grow_type'],labels['jobs']),
                'attributes':attrs, 'wealth':{'state':'ok' if inventory else 'missing',
                    'gold':inventory['money'] if inventory else None,
                    'revival_coin_raw':inventory['coin'] if inventory else None,
                    'inventory_capacity_raw':inventory['inventory_capacity'] if inventory else None},
                'equipment':equipment, 'backpack':backpack, 'catalog_state':labels['state'],
                'collected_at':time.time(), 'read_only':True,
                'snapshot_note':'数据库存档快照，不是在线实时战斗面板；在线变化可能尚未保存。属性为原始字段值，未叠加装备、技能和临时效果。未解析的属性不猜测。'}

    def preview(self, session_hash, data):
        action = data['action']
        if not data['reason'].strip():
            raise HTTPException(422, '必须填写原因')
        gold = data.get('gold', 0)
        if type(gold) is not int or not 0 <= gold <= MAIL_GOLD_MAX or (action != 'mail' and gold):
            raise HTTPException(422, '金币附件仅用于邮件，金额须为0至10亿的整数')
        if action == 'currency' and (data.get('currency') not in CURRENCIES or not data.get('delta') or data.get('items') or data.get('template_id')):
            raise HTTPException(422, '请选择币种及非零变更金额，不可混合发放')
        if action != 'currency' and (data.get('currency') is not None or data.get('delta') is not None):
            raise HTTPException(422, '操作类型与参数不一致')
        keys = data.get('lock_keys', [])
        if action == 'equipment-unlock':
            if data.get('items') or data.get('template_id') or data.get('template_version') or gold:
                raise HTTPException(422, '提前解锁不可混合邮件参数')
            if not keys or len(set(keys)) != len(keys) or any(type(k) is not int or not 1 <= k <= 100 for k in keys):
                raise HTTPException(422, '请选择有效且不重复的解锁申请编号')
        elif keys:
            raise HTTPException(422, '申请编号仅用于装备解锁')
        with self.db.connect() as c, c.cursor() as q:
            a = self.target(q, data)
            preview = {'target': a, 'action': action, 'reason': data['reason'], 'client_verified': False}
            if action == 'equipment-unlock':
                blob = self.unlock_blob(q, data, lock=False)
                try:
                    _, selected = unlock.expire(blob, keys, int(time.time()))
                except ValueError as e:
                    raise HTTPException(409, str(e))
                preview.update(lock_fingerprint=unlock.fingerprint(blob), requests=selected,
                               note='仅将选中申请设为到期；下次登录加载角色后由游戏处理，不代表装备已解锁')
            if action == 'currency':
                before = a[data['currency']]
                if before is None or not 0 <= before + data['delta'] <= 4294967295:
                    raise HTTPException(422, '余额不足、缺失或超出字段范围')
                preview.update(currency=data['currency'], before=before, after=before+data['delta'])
            if action == 'mail':
                wire_name(data['message'])
                attachments = data['items']
                if data.get('template_id'):
                    if attachments or not data.get('template_version'):
                        raise HTTPException(422, '模板发放必须指定版本，不能混入自选附件')
                    t = one(q, 'SELECT t.enabled,t.current_version,v.payload_json FROM dnf_gm.gift_templates t JOIN dnf_gm.gift_versions v ON v.template_id=t.id AND v.version=%s WHERE t.id=%s', (data['template_version'],data['template_id']))
                    if not t or not t['enabled'] or t['current_version'] != data['template_version']:
                        raise HTTPException(409, '礼包已停用或版本已变化')
                    attachments = json.loads(t['payload_json'])['items']
                if not attachments and not gold:
                    raise HTTPException(422, '邮件至少包含物品或大于0的金币附件')
                preview['gold'] = gold
                preview['rewards'] = self.catalog.items(attachments, q=q, allow_empty=gold > 0)
            if action in ('ban','unban'):
                punishment = one(q, 'SELECT apply_flag,admin_id,reason,end_time FROM d_taiwan.member_punish_info WHERE m_id=%s AND punish_type=1', (data['uid'],))
                preview['punishment'] = punishment
                owned = one(q, 'SELECT marker FROM dnf_gm.owned_bans WHERE uid=%s', (data['uid'],))
                if punishment and (not owned or punishment['admin_id'] != OWNER or punishment['reason'] != owned['marker']):
                    raise HTTPException(409, '存在非本后台处罚，禁止覆盖')
                if action == 'unban' and (not punishment or not punishment['apply_flag']):
                    raise HTTPException(409, '没有本后台创建的有效处罚')
            op = uuid.uuid4().hex
            fingerprint = hashlib.sha256(dump({'request':data,'preview':preview}).encode()).hexdigest()
            t = int(time.time())
            q.execute('INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,\'preview\',%s,%s)',
                      (op,session_hash,fingerprint,action,dump(data),dump(preview),t,t+300))
            c.commit()
        return {'operation_id': op,'preview':preview,'expires_at':t+300,'write_enabled':action in self.settings.writes}

    def operation(self, session_hash, op):
        with self.db.connect() as c, c.cursor() as q:
            row = one(q, 'SELECT operation_id,action,status,preview_json,result_json,expires_at FROM dnf_gm.operations WHERE operation_id=%s', (op,))
            if not row:
                raise HTTPException(404, '操作不存在')
            row['preview'] = json.loads(row.pop('preview_json'))
            row['result'] = json.loads(row.pop('result_json') or 'null')
            if row['result'] and row['action'] == 'mail':
                ids = row['result'].get('postal_ids',[])
                if ids:
                    q.execute('SELECT postal_id,receive_time,delete_flag,gold FROM taiwan_cain_2nd.postal WHERE postal_id IN ('+','.join(['%s']*len(ids))+')', ids)
                    row['delivery_records'] = q.fetchall()
                    row['delivery_note'] = '仅数据库领取标记，不等于客户端已正确领取'
            return row

    def confirm(self, session_hash, op, key):
        commit_attempted = False
        try:
            with self.db.connect() as c, c.cursor() as q:
                row = one(q, 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s AND session_hash=%s FOR UPDATE', (op,session_hash))
                if not row:
                    raise HTTPException(404, '操作不存在')
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
                if action not in self.settings.writes:
                    raise HTTPException(403, '该写入功能未激活；代码已实现但尚未验收')
                live = snapshot(self.settings)
                if not live.get('fresh') or not live.get('core_ok') or live.get('image_digest') != self.settings.image_digest:
                    raise HTTPException(503, '实时服务状态未知、核心接口异常或镜像变化，拒绝写入')
                if live.get('mem_available_mib', 0) < 256 or live.get('swap_free_mib', 0) < 1536:
                    raise HTTPException(503, '资源保护阈值触发，拒绝写入')
                if self.settings.test_uids and data['uid'] not in self.settings.test_uids:
                    raise HTTPException(403, '当前仅允许测试账号写入')
                # Verify expected transactional engines; never mutate schema.
                q.execute("SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','owned_bans','catalog_policy_state','catalog_policy_items')) OR (TABLE_SCHEMA='taiwan_billing' AND TABLE_NAME IN ('cash_cera','cash_cera_point')) OR (TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME IN ('letter','postal')) OR (TABLE_SCHEMA='d_taiwan' AND TABLE_NAME='member_punish_info')")
                engines = q.fetchall()
                if len(engines) != 10 or any(r['ENGINE'] != 'InnoDB' for r in engines):
                    raise HTTPException(409, '事务表结构基线不满足，拒绝写入')
                q.execute('UPDATE dnf_gm.operations SET idempotency_key=%s WHERE operation_id=%s', (key,op))
                account = self.target(q, data, lock=True)
                if account['accountname'] != preview['target']['accountname']:
                    raise HTTPException(409, '目标身份变化，重新预览')
                result = {'operation_id':op,'uid':data['uid'],'action':action,'client_verified':False}
                if action == 'currency':
                    table,column = CURRENCIES[data['currency']]
                    balance = one(q, f'SELECT {column} FROM taiwan_billing.{table} WHERE account=%s FOR UPDATE', (str(data['uid']),))
                    if not balance or balance[column] != preview['before']:
                        raise HTTPException(409, '余额变化，必须重新预览')
                    after = balance[column] + data['delta']
                    if not 0 <= after <= 4294967295:
                        raise HTTPException(409, '余额不足或字段溢出')
                    q.execute(f'UPDATE taiwan_billing.{table} SET {column}=%s,mod_date=UTC_TIMESTAMP() WHERE account=%s AND {column}=%s', (after,str(data['uid']),balance[column]))
                    if q.rowcount != 1:
                        raise HTTPException(409, '条件更新未命中')
                    result.update(currency=column,before=balance[column],after=after,state='database_committed_refresh_client')
                elif action == 'equipment-unlock':
                    q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE (TABLE_SCHEMA='taiwan_cain_2nd' AND TABLE_NAME='charac_item_lock_info') OR (TABLE_SCHEMA='taiwan_login' AND TABLE_NAME='login_account_3')")
                    rows = q.fetchall()
                    if len(rows) != 2 or any(r['ENGINE'] != 'InnoDB' for r in rows):
                        raise HTTPException(409, '解锁事务表引擎不满足')
                    blob = self.unlock_blob(q, data, lock=True)
                    if unlock.fingerprint(blob) != preview['lock_fingerprint']:
                        raise HTTPException(409, '锁定存档变化，请重新预览')
                    try:
                        updated, selected = unlock.expire(blob, data['lock_keys'], int(time.time()))
                    except ValueError as e:
                        raise HTTPException(409, str(e))
                    q.execute('UPDATE taiwan_cain_2nd.charac_item_lock_info SET item_lock_info=%s WHERE charac_no=%s AND item_lock_info=%s', (updated,data['charac_no'],blob))
                    if q.rowcount != 1:
                        raise HTTPException(409, '锁定存档条件更新未命中')
                    result.update(charac_no=data['charac_no'], lock_keys=data['lock_keys'],
                                  requests_before=selected, before_fingerprint=preview['lock_fingerprint'], after_fingerprint=unlock.fingerprint(updated),
                                  state='requests_expired_pending_game_load', note=preview['note'])
                elif action == 'mail':
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
                    q.execute('INSERT INTO taiwan_cain_2nd.letter(charac_no,send_charac_name,letter_text,reg_date,stat) VALUES(%s,\'GM\',%s,UTC_TIMESTAMP(),0)', (data['charac_no'],wire_name(data['message'])))
                    letter_id, postal_ids = q.lastrowid, []
                    # Gold belongs to the letter, carried ONCE by its first postal row.
                    # A gold-only letter uses item_id/add_info/endurance=0, not a PVF coin item.
                    deliveries = rewards['items'] or [{'id':0,'quantity':0,'category':'gold','durability':0}]
                    for index, item in enumerate(deliveries):
                        equip = item['category'] == 'equipment'
                        q.execute('INSERT INTO taiwan_cain_2nd.postal(occ_time,send_charac_name,receive_charac_no,item_id,add_info,endurance,gold,letter_id) VALUES(UTC_TIMESTAMP(),\'GM\',%s,%s,%s,%s,%s,%s)',
                                  (data['charac_no'],item['id'],0 if equip else item['quantity'],item['durability'] if equip else 0,gold if index == 0 else 0,letter_id))
                        postal_ids.append(q.lastrowid)
                    result.update(letter_id=letter_id,postal_ids=postal_ids,items=rewards,gold=gold,template_id=data.get('template_id'),template_version=data.get('template_version'),state='database_delivered_not_claimed')
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
                q.execute('INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,\'owner\',%s,%s,%s,%s,%s)',
                          (op,action,data['uid'],data['reason'],dump(data),dump(result)))
                q.execute("UPDATE dnf_gm.operations SET status='committed',result_json=%s WHERE operation_id=%s", (dump(result),op))
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

    def templates(self, text='', page=1):
        term = '%' + text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        with self.db.connect() as c, c.cursor() as q:
            q.execute("SELECT t.id,t.name,t.current_version,t.enabled,v.payload_json FROM dnf_gm.gift_templates t JOIN dnf_gm.gift_versions v ON t.id=v.template_id AND t.current_version=v.version WHERE (%s='' OR t.name LIKE %s OR t.id=%s) ORDER BY t.id DESC LIMIT 50 OFFSET %s",
                      (text, term, int(text) if text.isascii() and text.isdigit() and len(text)<11 else 0, (page-1)*50))
            rows = q.fetchall()
        items = []
        for row in rows:
            rewards = json.loads(row.pop('payload_json'))
            with self.db.connect() as con, con.cursor() as cursor:
                rewards['items'] = self.catalog.describe(rewards['items'],q=cursor)
            items.append({**row, 'rewards':rewards})
        return {'items':items, 'page':page}

    def save_template(self, template_id, data):
        # Management-only metadata, never a game write; catalog validates boundaries.
        if not data['name'].strip():
            raise HTTPException(422, '模板名称不能为空')
        with self.db.connect() as c, c.cursor() as q:
            self.catalog.items(data['items'], active=False, q=q)
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
            q.execute('INSERT INTO dnf_gm.gift_versions(template_id,version,payload_json) VALUES(%s,%s,%s)', (template_id,version,dump({'items':data['items']})))
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
                raise HTTPException(422, '没有需要变更的受支持物品；特殊类型或未知堆叠上限不能开放')
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
