from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from fastapi import HTTPException
from .limits import MAIL_ITEM_QUANTITY_MAX


def snapshot(settings):
    try:
        p = Path(settings.status_file)
        if p.stat().st_size > 65536:
            raise ValueError()
        d = json.loads(p.read_text())
        age = time.time() - d['collected_at']
        if age < -5 or age > 45:
            return {'fresh': False, 'state': 'unknown', 'reason': '采集快照已过期', 'collected_at': d.get('collected_at')}
        return {**d, 'fresh': True}
    except (OSError, ValueError, KeyError, TypeError):
        return {'fresh': False, 'state': 'unknown', 'reason': '无有效采集快照'}


class Catalog:
    def __init__(self, settings, db=None):
        self.settings, self.db = settings, db

    def connect(self):
        p = Path(self.settings.catalog_file).resolve()
        if not p.is_file():
            raise HTTPException(503, '尚未安装只读物品索引')
        c = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=1)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        return c

    def meta(self, c):
        return dict(c.execute('SELECT key,value FROM metadata').fetchall())

    def quantity_limits(self, c):
        """Root-configured trials for a missing cap, never special-type bypasses."""
        configured = self.settings.mail_stack_limits
        if not configured or self.meta(c).get('pvf_sha256') != self.settings.pvf_sha256:
            return {}
        limits = {}
        for item_id, entry in configured.items():
            if entry['pvf_sha256'] != self.settings.pvf_sha256:
                continue
            row = c.execute('SELECT * FROM items WHERE id=?', (int(item_id),)).fetchone()
            if (row and row['category'] in ('material', 'consumable') and row['stack_limit'] == 0
                    and 0 <= row['durability'] <= 65535
                    and not any(word in row['source_path'].lower() for word in ('avatar', 'creature', 'pet/'))):
                limits[row['id']] = entry
        return limits

    def policy(self, q, sha, lock=False, ids=None):
        if q is None:
            if self.db is not None:
                raise HTTPException(503, '缺少同事务策略校验，拒绝发放')
            return 0, {}
        q.execute('SELECT revision FROM dnf_gm.catalog_policy_state WHERE id=1' + (' FOR UPDATE' if lock else ' LOCK IN SHARE MODE'))
        state = q.fetchone()
        if not state:
            raise HTTPException(503, '物品策略迁移未完成，拒绝发放')
        if ids == []:
            return state['revision'], {}
        clause = (' AND item_id IN ('+','.join(['%s']*len(ids))+')') if ids else ''
        q.execute('SELECT item_id,enabled,reason,verification_evidence FROM dnf_gm.catalog_policy_items WHERE pvf_sha256=%s'+clause+' LOCK IN SHARE MODE', (sha,*(ids or [])))
        return state['revision'], {x['item_id']:x for x in q.fetchall()}

    @staticmethod
    def annotate(row, overrides, limits=None):
        item = dict(row)
        limit = (limits or {}).get(item['id'])
        if limit:
            item.update(indexed_stack_limit=item['stack_limit'], stack_limit=limit['stack_limit'] or MAIL_ITEM_QUANTITY_MAX,
                        quantity_limit_source='maintenance-trial', quantity_unlimited=limit['stack_limit'] is None)
        path = item.get('source_path', '').lower()
        unsupported_reason = ''
        if item['category'] not in ('equipment','material','consumable') or any(x in path for x in ('avatar','creature','pet/')):
            unsupported_reason = '特殊类型尚未适配，不能手动开放'
        elif not 1 <= item['stack_limit'] <= (MAIL_ITEM_QUANTITY_MAX if limit and item['quantity_unlimited'] else 1000000):
            unsupported_reason = '堆叠上限未知或超出支持范围，不能手动开放'
        elif not 0 <= item['durability'] <= 65535:
            unsupported_reason = '耐久超出当前邮件字段范围，不能手动开放'
        elif item['category'] == 'equipment' and item['stack_limit'] != 1:
            unsupported_reason = '普通装备每条数量必须为1，索引上限异常，不能开放'
        supported = not unsupported_reason
        override = overrides.get(item['id'])
        enabled = supported and (bool(override['enabled']) if override else bool(not limit and item['allowed'] and item['reviewed']))
        evidence = override.get('verification_evidence','') if override and not limit else ''
        state = ('verified' if evidence else 'trial') if enabled else 'blocked'
        why = (unsupported_reason if not supported
               else (override['reason'] if override else '原索引元数据审核允许试发；尚无逐项客户端验证记录' if enabled else '默认禁止；可由管理员预览后开放试发'))
        if limit:
            cap_label = '无策略上限（数据库数量字段最大2147483647）' if item['quantity_unlimited'] else str(limit['stack_limit'])
            why += f"；PVF未声明堆叠上限，维护试发数量{cap_label}：{limit['reason']}；客户端未验证"
        return {**item, 'allowed':int(enabled), 'supported':supported, 'policy_state':state,
                'policy_reason':why, 'verification_evidence':evidence,
                'sendable':bool(enabled), 'metadata_reviewed':bool(item['reviewed'])}

    def rows(self, c, filters, overrides):
        # Literal name substring, not user supplied SQL/LIKE wildcards. Iterate,
        # never materialize the entire PVF catalogue in application memory.
        q, category = filters.get('q',''), filters.get('category','')
        limits = self.quantity_limits(c)
        rows = c.execute("SELECT * FROM items WHERE (?='' OR instr(name,?)>0 OR CAST(id AS TEXT)=?) AND (?='' OR category=?) ORDER BY id", (q,q,q,category,category))
        for row in rows:
            item = self.annotate(row,overrides,limits)
            if filters.get('allowed_only') and not item['sendable']:
                continue
            if filters.get('state') and item['policy_state'] != filters['state']:
                continue
            yield item

    def search(self, q='', category='', page=1, allowed_only=False, state=''):
        if self.db:
            with self.db.connect() as con, con.cursor() as cursor:
                return self._search(q,category,page,allowed_only,state,cursor)
        return self._search(q,category,page,allowed_only,state,None)

    def _search(self, q, category, page, allowed_only, state, cursor):
        with closing(self.connect()) as c:
            m = self.meta(c)
            revision, overrides = self.policy(cursor,m.get('pvf_sha256'))
            limits = self.quantity_limits(c)
            # Count/page in SQLite C code. Only decorate the displayed 50 rows;
            # Python scans of 66k rows per page exceed the 25%-CPU slice budget.
            where = ["(?='' OR instr(name,?)>0 OR CAST(id AS TEXT)=?)", "(?='' OR category=?)"]
            args = [q,q,q,category,category]
            supported = "(category IN ('equipment','material','consumable') AND stack_limit BETWEEN 1 AND 1000000 AND durability BETWEEN 0 AND 65535 AND (category<>'equipment' OR stack_limit=1) AND instr(lower(source_path),'avatar')=0 AND instr(lower(source_path),'creature')=0 AND instr(lower(source_path),'pet/')=0)"
            # Only validated numeric maintenance ids enter this clause; no
            # per-row Python callbacks or scans on the constrained server.
            if limits:
                ids = ','.join(str(int(i)) for i in limits)
                supported = supported.replace('stack_limit BETWEEN 1 AND 1000000', '(stack_limit BETWEEN 1 AND 1000000 OR id IN ('+ids+'))')
            def in_set(ids, negate=False):
                if not ids:
                    return '1' if negate else '0', []
                return 'id '+('NOT IN' if negate else 'IN')+' ('+','.join('?' for _ in ids)+')', list(ids)
            enabled_ids = [i for i,p in overrides.items() if p['enabled']]
            disabled_ids = [i for i,p in overrides.items() if not p['enabled']]
            verified_ids = [i for i,p in overrides.items() if p['enabled'] and p['verification_evidence'] and i not in limits]
            enabled_sql, enabled_args = in_set(enabled_ids)
            default_sql, default_args = in_set(disabled_ids,True)
            default_trial = 'id NOT IN ('+','.join(str(int(i)) for i in limits)+')' if limits else '1'
            sendable = '((('+enabled_sql+') OR (allowed=1 AND reviewed=1 AND '+default_sql+' AND '+default_trial+')) AND '+supported+')'
            sendable_args = enabled_args+default_args
            if state == 'verified':
                verified_sql, verified_args = in_set(verified_ids)
                where.append(supported+' AND '+verified_sql)
                args += verified_args
            elif state == 'blocked':
                where.append('0' if allowed_only else 'NOT '+sendable)
                if not allowed_only: args += sendable_args
            elif state == 'trial' or allowed_only:
                where.append(sendable)
                args += sendable_args
                if state == 'trial':
                    not_verified_sql, verified_args = in_set(verified_ids,True)
                    where.append(not_verified_sql)
                    args += verified_args
            clause = ' AND '.join('('+part+')' for part in where)
            total = c.execute('SELECT COUNT(*) FROM items WHERE '+clause,args).fetchone()[0]
            rows = c.execute('SELECT * FROM items WHERE '+clause+' ORDER BY id LIMIT 50 OFFSET ?',args+[(page-1)*50])
            result = []
            for row in rows:
                item = self.annotate(row,overrides,limits)
                item.pop('source_path',None)
                result.append(item)
            return {'items':result,'page':page,'total':total,'metadata':{**m,'policy_revision':revision}}

    def selection(self, cursor, data, lock=False):
        with closing(self.connect()) as c:
            m = self.meta(c)
            live = snapshot(self.settings)
            if not live.get('fresh') or live.get('pvf_sha256') != m.get('pvf_sha256') or m.get('pvf_sha256') != self.settings.pvf_sha256:
                raise HTTPException(409, 'PVF版本不匹配或状态未知，禁止修改发放策略')
            if live.get('mem_available_mib',0) < 256 or live.get('swap_free_mib',0) < 1536:
                raise HTTPException(503, '资源保护阈值触发，拒绝策略变更')
            revision, overrides = self.policy(cursor,m['pvf_sha256'],lock)
            matched = supported = 0
            affected, digest = [], hashlib.sha256()
            for item in self.rows(c,data['filters'],overrides):
                if data.get('item_id') is not None and item['id'] != data['item_id']:
                    continue
                matched += 1
                supported += int(item['supported'])
                digest.update(json.dumps(item,sort_keys=True,ensure_ascii=False).encode())
                if item['supported'] and item['sendable'] != data['enabled']:
                    affected.append(item['id'])
            return {'pvf_sha256':m['pvf_sha256'],'policy_revision':revision,
                    'matched':matched,'supported':supported,'skipped':matched-supported,
                    'affected':len(affected),'unchanged':supported-len(affected),
                    'selection_sha256':digest.hexdigest()}, affected

    def read_labels(self, ids):
        """Display-only metadata: never calls the delivery allowlist or grants rights."""
        try:
            with closing(self.connect()) as c:
                m = self.meta(c)
                live = snapshot(self.settings)
                if m.get('pvf_sha256') != self.settings.pvf_sha256 or (live.get('fresh') and live.get('pvf_sha256') != m.get('pvf_sha256')):
                    return {'state':'mismatch','items':{},'jobs':{}}
                labels = {}
                ids = sorted(set(ids))
                for start in range(0,len(ids),400):
                    batch = ids[start:start+400]
                    rows = c.execute('SELECT id,name,level FROM items WHERE id IN ('+','.join('?' for _ in batch)+')',batch)
                    labels.update({row['id']:dict(row) for row in rows})
                jobs = json.loads(m.get('jobs','{}'))
                if not isinstance(jobs,dict): jobs = {}
                return {'state':'ok','items':labels,'jobs':jobs}
        except (HTTPException,sqlite3.Error,ValueError,OSError):
            return {'state':'unavailable','items':{},'jobs':{}}

    def describe(self, requests, q=None):
        """Read-only labels for saved templates; never activates an item for delivery."""
        with closing(self.connect()) as c:
            _, overrides = self.policy(q,self.meta(c).get('pvf_sha256'),ids=[a['id'] for a in requests])
            limits = self.quantity_limits(c)
            result = []
            for a in requests:
                row = c.execute('SELECT * FROM items WHERE id=?', (a['id'],)).fetchone()
                result.append({**(self.annotate(row,overrides,limits) if row else {'id':a['id'],'name':'索引中已不存在','allowed':0,'sendable':False}), 'quantity':a['quantity']})
            return result

    def items(self, requests, active=True, q=None, allow_empty=False):
        if not (0 if allow_empty else 1) <= len(requests) <= 20:
            raise HTTPException(422, '一次需1至20条附件')
        with closing(self.connect()) as c:
            m = self.meta(c)
            if active:
                s = snapshot(self.settings)
                if not s.get('fresh') or s.get('pvf_sha256') != m.get('pvf_sha256') or m.get('pvf_sha256') != self.settings.pvf_sha256:
                    raise HTTPException(409, 'PVF版本不匹配或状态未知，禁止发放')
            revision, overrides = self.policy(q,m.get('pvf_sha256'),ids=[a['id'] for a in requests])
            limits = self.quantity_limits(c)
            result = []
            for a in requests:
                row = c.execute('SELECT * FROM items WHERE id=?', (a['id'],)).fetchone()
                row = self.annotate(row,overrides,limits) if row else None
                if row is None or not row['sendable']:
                    raise HTTPException(422, '未知、特殊或策略已禁止的物品不能发放')
                n = a['quantity']
                if type(n) is not int or n < 1 or n > row['stack_limit'] or (row['category'] == 'equipment' and n != 1):
                    raise HTTPException(422, '物品数量或堆叠上限不合法')
                result.append({**dict(row), 'quantity': n})
            return {'items': result, 'pvf_sha256': m['pvf_sha256'], 'policy_revision':revision}
