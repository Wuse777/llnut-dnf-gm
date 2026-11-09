from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from fastapi import HTTPException
from .limits import MAIL_ITEM_QUANTITY_MAX
from .item_preferences import ItemPreferences
from .game_assets import GameAssets
from .equipment_metadata import read_metadata, decode_enchantment
from .catalog_filters import predicates,facets,ORDERS


def snapshot(settings):
    try:
        p = Path(settings.status_file)
        if p.stat().st_size > 65536:
            raise ValueError()
        d = json.loads(p.read_text())
        age = time.time() - d['collected_at']
        if age < -5 or age > 45:
            return {'fresh': False, 'state': 'unknown', 'reason': '采集快照已过期', 'collected_at': d.get('collected_at')}
        # Installed-monitor identity is only consumed by the root handshake.
        # Never expose release paths, boot/PID identity or config hashes to web.
        d.pop('maintenance_monitor', None)
        return {**d, 'fresh': True}
    except (OSError, ValueError, KeyError, TypeError):
        return {'fresh': False, 'state': 'unknown', 'reason': '无有效采集快照'}


class Catalog:
    def __init__(self, settings, db=None):
        self.settings, self.db = settings, db
        self.assets = GameAssets(settings)

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
    def annotate(row, overrides, creature_types=None):
        item = dict(row)
        path = item.get('source_path', '').lower()
        equipment = item['category'] == 'equipment' or path.startswith('equipment/')
        mail_kind = ('avatar' if equipment and 'avatar' in path else
                     'creature' if equipment and any(x in path for x in ('creature', 'pet/')) else
                     'equipment' if equipment else 'stackable')
        item['mail_kind'] = mail_kind
        item['single_item'] = equipment
        if mail_kind == 'creature':
            item['creature_type'] = (creature_types or {}).get(str(item['id']), 1)
        item['indexed_stack_limit'] = item['stack_limit']
        # PVF stack sizes are metadata, not GM issuance limits. Unknown,
        # zero and known caps all use the native postal quantity field range.
        item.update(stack_limit=MAIL_ITEM_QUANTITY_MAX, quantity_unlimited=True,
                    quantity_limit_source='storage-only')
        item['durability'] = max(0, min(item['durability'], 65535))
        supported = True
        override = overrides.get(item['id'])
        enabled = bool(override['enabled']) if override else True
        evidence = override.get('verification_evidence','') if override else ''
        state = ('verified' if evidence else 'trial') if enabled else 'blocked'
        why = override['reason'] if override else '索引物品默认可发放；尚无逐项客户端验证记录'
        return {**item, 'allowed':int(enabled), 'supported':supported, 'policy_state':state,
                'policy_reason':why, 'verification_evidence':evidence,
                'sendable':bool(enabled), 'metadata_reviewed':bool(item['reviewed'])}

    def creature_types(self, c):
        return json.loads(self.meta(c).get('creature_types', '{}'))

    def rows(self, c, filters, overrides):
        # Literal name substring, not user supplied SQL/LIKE wildcards. Iterate,
        # never materialize the entire PVF catalogue in application memory.
        q, category = filters.get('q',''), filters.get('category','')
        creature_types = self.creature_types(c)
        extra,args=predicates(c,filters)
        clause=' AND '+ ' AND '.join('('+s+')' for s in extra) if extra else ''
        rows = c.execute("SELECT * FROM items WHERE (?='' OR instr(name,?)>0 OR CAST(id AS TEXT)=?) AND (?='' OR category=?)"+clause+' ORDER BY id', (q,q,q,category,category,*args))
        for row in rows:
            item = self.annotate(row,overrides,creature_types)
            if filters.get('allowed_only') and not item['sendable']:
                continue
            if filters.get('state') and item['policy_state'] != filters['state']:
                continue
            yield item

    def search(self, q='', category='', page=1, allowed_only=False, state='', *, part='',rarity=None,min_level=None,max_level=None,job='',weapon_type='',set_id=None,sort='id'):
        filters={'part':part,'rarity':rarity,'min_level':min_level,'max_level':max_level,'job':job,'weapon_type':weapon_type,'set_id':set_id}
        if sort not in ORDERS:raise HTTPException(422,'未知的物品排序方式')
        if self.db:
            with self.db.connect() as con, con.cursor() as cursor:
                return self._search(q,category,page,allowed_only,state,cursor,filters,sort)
        return self._search(q,category,page,allowed_only,state,None,filters,sort)

    def _search(self, q, category, page, allowed_only, state, cursor, filters=None, sort='id'):
        with closing(self.connect()) as c:
            m = self.meta(c)
            revision, overrides = self.policy(cursor,m.get('pvf_sha256'))
            # Count/page in SQLite C code. Only decorate the displayed 50 rows;
            # Python scans of 66k rows per page exceed the 25%-CPU slice budget.
            where = ["(?='' OR instr(name,?)>0 OR CAST(id AS TEXT)=?)", "(?='' OR category=?)"]
            args = [q,q,q,category,category]
            extra,extra_args=predicates(c,filters or {})
            where+=extra;args+=extra_args
            creature_types = self.creature_types(c)
            def in_set(ids, negate=False):
                if not ids:
                    return '1' if negate else '0', []
                return 'id '+('NOT IN' if negate else 'IN')+' ('+','.join('?' for _ in ids)+')', list(ids)
            disabled_ids = [i for i,p in overrides.items() if not p['enabled']]
            verified_ids = [i for i,p in overrides.items() if p['enabled'] and p['verification_evidence']]
            default_sql, default_args = in_set(disabled_ids,True)
            sendable = default_sql
            sendable_args = default_args
            if state == 'verified':
                verified_sql, verified_args = in_set(verified_ids)
                where.append(verified_sql)
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
            rows = c.execute('SELECT * FROM items WHERE '+clause+' ORDER BY '+ORDERS[sort]+' LIMIT 50 OFFSET ?',args+[(page-1)*50])
            result = []
            for row in rows:
                item = self.annotate(row,overrides,creature_types)
                item.pop('source_path',None)
                result.append(item)
            read_metadata(c,{item['id']:item for item in result})
            if cursor is not None:
                ItemPreferences.decorate(cursor,m.get('pvf_sha256'),result)
            self.assets.decorate(m.get('pvf_sha256'),result)
            return {'items':result,'page':page,'total':total,'facets':facets(c),'metadata':{**m,'policy_revision':revision},'assets':self.assets.status(m.get('pvf_sha256'))}

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
                ids = sorted({n for n in ids if type(n) is int and 0<n<=4294967295})
                for start in range(0,len(ids),400):
                    batch = ids[start:start+400]
                    rows = c.execute('SELECT id,name,level,category,durability AS base_durability FROM items WHERE id IN ('+','.join('?' for _ in batch)+')',batch)
                    labels.update({row['id']:dict(row) for row in rows})
                read_metadata(c,labels)
                jobs = json.loads(m.get('jobs','{}'))
                if not isinstance(jobs,dict): jobs = {}
                if m.get('profession_rules_version')=='qf1031-profession-1':
                    for row in c.execute('SELECT job,payload_json FROM profession_rules LIMIT 32'):
                        display=json.loads(row['payload_json'])
                        jobs.setdefault(str(row['job']),{})['profiles']={str(o['code']):o['name'] for o in display['choices']}
                return {'state':'ok','items':labels,'jobs':jobs}
        except (HTTPException,sqlite3.Error,ValueError,OSError):
            return {'state':'unavailable','items':{},'jobs':{}}

    def enchantments(self, q='', page=1):
        """PVF-defined enchants only; no name-based orb guesses or policy writes."""
        with closing(self.connect()) as c:
            m=self.meta(c);live=snapshot(self.settings)
            state='ok' if m.get('pvf_sha256')==self.settings.pvf_sha256 and not (live.get('fresh') and live.get('pvf_sha256')!=m.get('pvf_sha256')) else 'mismatch'
            result={'state':state,'pvf_sha256':m.get('pvf_sha256'),'page':page,'items':[],'has_more':False,
                    'note':'效果来自PVF原始定义；适用部位仅展示明确标注，不保证当前装备可用。速度等数值未换算百分比。'}
            if m.get('equipment_index_version')!='1':return {**result,'metadata_state':'unavailable'}
            term=q.strip();args=[];where=''
            if term:
                if term.isascii() and term.isdecimal():
                    if int(term)>4294967295:return {**result,'metadata_state':'ok'}
                    where=' WHERE i.id=?';args.append(int(term))
                else:
                    literal=term.replace('!','!!').replace('%','!%').replace('_','!_')
                    where=" WHERE (i.name LIKE ? ESCAPE '!' OR e.summary LIKE ? ESCAPE '!')";args.extend(['%'+literal+'%']*2)
            rows=c.execute('SELECT i.id,i.name,i.level,e.targets_json,e.effects_json,e.summary FROM enchantments e JOIN items i ON i.id=e.item_id'+where+' ORDER BY i.id LIMIT 21 OFFSET ?',(*args,(page-1)*20)).fetchall()
            items=[{'id':r['id'],'name':r['name'],'level':r['level'],**decode_enchantment(r)} for r in rows[:20]]
            self.assets.decorate(m.get('pvf_sha256') if state=='ok' else '',items)
            return {**result,'metadata_state':'ok','items':items,'has_more':len(rows)>20}

    def describe(self, requests, q=None):
        """Read-only labels for saved templates; never activates an item for delivery."""
        with closing(self.connect()) as c:
            _, overrides = self.policy(q,self.meta(c).get('pvf_sha256'),ids=[a['id'] for a in requests])
            creature_types = self.creature_types(c)
            result = []
            for a in requests:
                row = c.execute('SELECT * FROM items WHERE id=?', (a['id'],)).fetchone()
                result.append({**(self.annotate(row,overrides,creature_types) if row else {'id':a['id'],'name':'索引中已不存在','allowed':0,'sendable':False}), 'quantity':a['quantity']})
            self.assets.decorate(self.meta(c).get('pvf_sha256'),result)
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
            creature_types = self.creature_types(c)
            result = []
            for a in requests:
                row = c.execute('SELECT * FROM items WHERE id=?', (a['id'],)).fetchone()
                row = self.annotate(row,overrides,creature_types) if row else None
                if row is None or not row['sendable']:
                    raise HTTPException(422, '未知或策略已禁止的物品不能发放')
                n = a['quantity']
                if type(n) is not int or n < 1 or n > MAIL_ITEM_QUANTITY_MAX:
                    raise HTTPException(422, '物品数量必须为正整数，且不能超出邮件数量字段范围（2147483647）')
                result.append({**dict(row), 'quantity': n})
            return {'items': result, 'pvf_sha256': m['pvf_sha256'], 'policy_revision':revision}
