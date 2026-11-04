"""Read-only pre-upgrade reference report. Never activates a candidate or grants writes."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import base64
import hashlib
import hmac
import json
import re
import sqlite3
import time
from fastapi import HTTPException
from .catalog import Catalog, snapshot

SHA = re.compile(r'^[a-f0-9]{64}$')
KINDS = ('templates', 'preferences', 'policies', 'schedules', 'jobs', 'previews', 'images', 'portraits')
NOTE = '仅检查已保存引用与候选索引，不安装版本、不改礼包、不暂停任务、不保证游戏内兼容。无差异也不等于可以直接发布。'
FIELDS = ('id', 'name', 'category', 'level', 'stack_limit', 'durability', 'source_path')
ITEM_SELECT = 'id,' + ','.join(
    f"CASE WHEN typeof({key})='text' AND length({key})<={limit} THEN {key} ELSE NULL END AS {key}"
    for key, limit in (('name',255),('category',64),('source_path',2048))) + ',' + ','.join(
    f"CASE WHEN typeof({key})='integer' THEN {key} ELSE NULL END AS {key}"
    for key in ('level','stack_limit','durability'))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def payload(value):
    if not isinstance(value, str) or len(value.encode()) > 65536:
        raise ValueError('invalid document')
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('invalid document')
    return result


def bounded(column):
    # All callers use literal column names; never an HTTP-provided expression.
    return f'CASE WHEN OCTET_LENGTH({column})<=65536 THEN {column} ELSE NULL END'


def identity(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ValueError('invalid index')
    s = p.stat()
    if not 0 < s.st_size <= 256 * 1024 * 1024:
        raise ValueError('invalid index size')
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


class TimedIndex:
    def __init__(self, connection): self.connection = connection

    def execute(self, sql, args=()):
        deadline = time.monotonic() + .5
        self.connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return self.connection.execute(sql, args)


@contextmanager
def index(path, assets=False):
    c = None
    try:
        stamp = identity(path)
        c = sqlite3.connect(Path(path).absolute().as_uri() + '?mode=ro', uri=True, timeout=.2)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON'); c.execute('PRAGMA trusted_schema=OFF'); c.execute('PRAGMA cache_size=-256')
        deadline = time.monotonic() + 2
        c.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        c.execute('BEGIN')
        rows = c.execute("SELECT key,CASE WHEN length(value)<=128 THEN value ELSE NULL END AS value FROM metadata WHERE key IN ('pvf_sha256','format','state') LIMIT 4").fetchall()
        if len(rows)>3 or len({r['key'] for r in rows})!=len(rows): raise ValueError('invalid metadata')
        meta = dict(rows)
        if not SHA.fullmatch(meta.get('pvf_sha256', '')):
            raise ValueError('invalid fingerprint')
        if assets:
            if meta.get('format') != 'dnfgm-assets-v1' or meta.get('state') != 'ready':
                raise ValueError('invalid asset format')
            c.execute('SELECT item_id,state,sha256 FROM item_images LIMIT 0')
            c.execute('SELECT job,grow_type,sex,sha256 FROM portraits LIMIT 0')
        else:
            c.execute('SELECT '+','.join(FIELDS)+' FROM items LIMIT 0')
        c.set_progress_handler(None, 0)
        yield {'db': TimedIndex(c), 'sha': meta['pvf_sha256'], 'stamp': stamp, 'path': path}
    except (OSError, sqlite3.Error, ValueError, TypeError):
        raise HTTPException(503, '升级检查索引缺失、忙碌或格式异常，请维护人员核对离线文件；未判定兼容') from None
    finally:
        if c is not None: c.close()


class UpgradeCheck:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db

    @contextmanager
    def context(self, expected=''):
        s = self.settings
        if not s.upgrade_catalog_file:
            raise HTTPException(409, '尚未安装候选索引；由维护人员配置离线检查目标，不支持网页上传或自动激活')
        with ExitStack() as stack:
            old = stack.enter_context(index(s.catalog_file)); new = stack.enter_context(index(s.upgrade_catalog_file))
            art = {}
            for key, directory in (('current', s.assets_dir), ('candidate', s.upgrade_assets_dir)):
                if directory:
                    art[key] = stack.enter_context(index(str(Path(directory)/'manifest.sqlite'), assets=True))
            live = snapshot(s)
            binding = {'current': old['sha'], 'candidate': new['sha'], 'old_stamp': old['stamp'], 'new_stamp': new['stamp'],
                       'assets': {k: [v['sha'], v['stamp']] for k, v in art.items()},
                       'configured_pvf': s.pvf_sha256, 'configured_image': s.image_digest, 'candidate_image': s.upgrade_image_digest,
                       'live_pvf': live.get('pvf_sha256') if live.get('fresh') else None,
                       'live_image': live.get('image_digest') if live.get('fresh') else None}
            fingerprint = hashlib.sha256(encoded(binding).encode()).hexdigest()
            if expected and not hmac.compare_digest(expected, fingerprint):
                raise HTTPException(409, '检查目标或运行指纹已变化，请重新读取概览并从第一页开始')
            ctx = {'old': old, 'new': new, 'art': art, 'fingerprint': fingerprint, 'live': live}
            yield ctx
            for item in [old, new, *art.values()]:
                try: unchanged = identity(item['path']) == item['stamp']
                except (ValueError, OSError): unchanged = False
                if not unchanged: raise HTTPException(409, '检查期间索引已变化，本次结果不可作为完整报告，请重新检查')

    def header(self, ctx):
        s = self.settings; old, new, live = ctx['old'], ctx['new'], ctx['live']
        pvf_changed = old['sha'] != new['sha']
        image_changed = bool(s.upgrade_image_digest and s.upgrade_image_digest != s.image_digest)
        aligned = bool(live.get('fresh') and live.get('pvf_sha256') == old['sha'] == s.pvf_sha256
                       and live.get('image_digest') == s.image_digest)
        assets = {}
        for name, sha in (('current', old['sha']), ('candidate', new['sha'])):
            a = ctx['art'].get(name)
            assets[name] = {'state': 'not_installed' if a is None else 'matched' if a['sha'] == sha else 'mismatch',
                            'pvf_sha256': a['sha'] if a else None, 'client_verified': False}
        recheck = []
        if not aligned: recheck.append({'capability': 'baseline', 'reason': '当前索引、配置或实时服务器指纹未对齐，不能作为已确认基线'})
        if pvf_changed:
            recheck.extend({'capability': name, 'reason': reason} for name, reason in (
                ('mail', '物品类型、邮件附属表与领取效果需要复验'),
                ('templates', '引用相同物品编号不保证名称、类型和属性不变'),
                ('policies', '停用策略和已验证证据绑定旧PVF，不会自动迁移'),
                ('assets', '图标与头像包须针对候选PVF重新构建，不沿用旧映射'),
                ('schedules', '已激活计划绑定旧指纹，核对后重新建立或激活；本检查不会代为暂停'),
                ('inventory', '装备存档属性解析、编辑及解锁物品关联需要复验')))
        if image_changed:
            recheck.extend({'capability': name, 'reason': '候选镜像与当前配置不同，现有镜像或程序指纹批准不能移用'} for name in ('currency', 'mail', 'ban', 'native', 'inventory', 'unlock'))
        if not s.upgrade_image_digest: recheck.append({'capability': 'image', 'reason': '未声明候选镜像摘要，本报告只比较索引，不评价镜像升级'})
        return {'state': 'ready', 'fingerprint': ctx['fingerprint'], 'generated_at': int(time.time()), 'note': NOTE,
                'current': {'pvf_sha256': old['sha'], 'configured_image': s.image_digest, 'live_aligned': aligned},
                'candidate': {'pvf_sha256': new['sha'], 'declared_image': s.upgrade_image_digest or None,
                              'image_verified': False}, 'pvf_changed': pvf_changed, 'image_changed': image_changed,
                'assets': assets, 'recheck': recheck, 'sources': list(KINDS), 'can_deploy': False,
                'scope': '引用级静态检查，不覆盖所有未引用物品、完整PVF内容、客户端或镜像实际数据库结构'}

    def overview(self):
        if not self.settings.upgrade_catalog_file:
            return {'state': 'not_configured', 'note': NOTE, 'sources': [], 'can_deploy': False,
                    'message': '尚未配置候选索引，请维护人员离线安装；不会为检查替换当前索引。'}
        with self.context() as ctx: return self.header(ctx)

    def cursor(self, kind, position, fingerprint):
        data = base64.urlsafe_b64encode(encoded([kind, position, fingerprint]).encode()).decode().rstrip('=')
        return data+'.'+hmac.new(self.settings.secret.encode(), data.encode(), hashlib.sha256).hexdigest()

    def position(self, token, kind, fingerprint):
        if not token: return None
        try:
            data, sig = token.split('.')
            if not hmac.compare_digest(hmac.new(self.settings.secret.encode(), data.encode(), hashlib.sha256).hexdigest(), sig): raise ValueError()
            source, position, bound = json.loads(base64.urlsafe_b64decode(data+'='*(-len(data)%4)))
            if source != kind or bound != fingerprint: raise ValueError()
            return position
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(422, '分页凭据无效或不属于本次检查，请从第一页重新查询') from None

    def source_page(self, q, kind, after, ctx):
        if kind == 'portraits':
            a = ctx['art'].get('current')
            if a is None: return []
            tail, args = (' WHERE (job,grow_type,sex)>(?,?,?)', tuple(after)) if after else ('', ())
            rows = a['db'].execute('SELECT job,grow_type,sex,sha256 FROM portraits'+tail+' ORDER BY job,grow_type,sex LIMIT 51', args).fetchall()
            return [{'position': [r['job'], r['grow_type'], r['sex']], 'label': f"职业 {r['job']} · 转职 {r['grow_type']} · 性别 {r['sex']}", 'status': 'ready', 'digest': r['sha256'], 'source_pvf': a['sha']} for r in rows]
        if kind == 'images':
            a = ctx['art'].get('current')
            if a is None: return []
            rows = a['db'].execute('SELECT item_id,state,sha256 FROM item_images WHERE item_id>? ORDER BY item_id LIMIT 51', (after[0] if after else 0,)).fetchall()
            return [{'position': [r['item_id']], 'label': f"图片 #{r['item_id']}", 'status': r['state'], 'item_id': r['item_id'], 'source_pvf': a['sha']} for r in rows]
        if kind == 'templates':
            tail, args = (' AND (v.template_id>%s OR (v.template_id=%s AND v.version>%s))', (after[0], after[0], after[1])) if after else ('', ())
            q.execute('SELECT v.template_id,v.version,t.name,t.enabled,t.current_version,'+bounded('v.payload_json')+' document FROM dnf_gm.gift_versions v JOIN dnf_gm.gift_templates t ON t.id=v.template_id WHERE 1=1'+tail+' ORDER BY v.template_id,v.version LIMIT 51', args)
            return [{'position': [r['template_id'], r['version']], 'label': r['name'], 'status': 'active' if r['enabled'] and r['current_version']==r['version'] else 'historical', 'document': r['document']} for r in q.fetchall()]
        if kind in ('preferences', 'policies'):
            table = 'item_preferences' if kind == 'preferences' else 'catalog_policy_items'
            extra = 'favorite' if kind == 'preferences' else 'enabled'
            tail, args = (' AND (pvf_sha256>%s OR (pvf_sha256=%s AND item_id>%s))', (after[0], after[0], after[1])) if after else ('', ())
            q.execute(f'SELECT pvf_sha256,item_id,{extra} FROM dnf_gm.{table} WHERE 1=1'+tail+' ORDER BY pvf_sha256,item_id LIMIT 51', args)
            return [{'position': [r['pvf_sha256'], r['item_id']], 'label': f"物品 #{r['item_id']}", 'status': ('favorite' if r['favorite'] else 'recent') if kind=='preferences' else ('enabled' if r['enabled'] else 'disabled'), 'item_id': r['item_id'], 'source_pvf': r['pvf_sha256']} for r in q.fetchall()]
        table, key, label = {'schedules': ('schedules', 'id', 'title'), 'jobs': ('reward_jobs', 'id', 'reason'), 'previews': ('operations', 'operation_id', 'action')}[kind]
        where = "status='preview'" if kind == 'previews' else '1=1'
        args = (after[0],) if after else ()
        if after: where += f' AND {key}>%s'
        q.execute(f'SELECT {key} id,{label} label,status,'+bounded('request_json')+' document,'+bounded('preview_json')+f' binding_document FROM dnf_gm.{table} WHERE '+where+f' ORDER BY {key} LIMIT 51', args)
        return [{'position': [r['id']], 'label': r['label'], 'status': r['status'], 'document': r['document'], 'binding_document': r['binding_document']} for r in q.fetchall()]

    def inspect(self, q, kind, row, ctx):
        issues = []; items = []; template = None; stored_pvf = None; label = row['label']
        try:
            if kind in ('schedules', 'jobs', 'previews'):
                frozen = payload(row['binding_document'])
                if kind == 'schedules':
                    bound = frozen.get('binding', {})
                    if not isinstance(bound, dict): raise ValueError()
                    stored_pvf = bound.get('pvf_sha256')
                    if bound.get('image_digest') != (self.settings.upgrade_image_digest or self.settings.image_digest): issues.append('saved_image_mismatch')
                else:
                    bound = frozen.get('rewards', {})
                    if not isinstance(bound, dict): raise ValueError()
                    stored_pvf = bound.get('pvf_sha256')
                if not isinstance(stored_pvf, str) or not SHA.fullmatch(stored_pvf):
                    issues.append('saved_binding_unknown'); stored_pvf = None
                elif stored_pvf != ctx['new']['sha']: issues.append('saved_pvf_mismatch')
            if kind == 'portraits':
                ids = []; a = ctx['art'].get('candidate')
                if a is None: issues.append('portrait_pack_missing')
                elif a['sha'] != ctx['new']['sha']: issues.append('portrait_pvf_mismatch')
                else:
                    hit = a['db'].execute('SELECT sha256 FROM portraits WHERE job=? AND grow_type=? AND sex=?', tuple(row['position'])).fetchone()
                    if hit is None: issues.append('portrait_mapping_missing')
                    elif hit['sha256'] != row['digest']: issues.append('portrait_mapping_changed')
            elif 'item_id' in row: ids = [row['item_id']]
            else:
                data = payload(row['document'])
                if kind == 'templates':
                    label = data['name'] if isinstance(data.get('name'), str) and len(data['name'])<=80 else '当前模板名称：'+row['label']
                if kind == 'schedules':
                    job = data.get('reward_job', {})
                    if not isinstance(job, dict): raise ValueError()
                    data = job.get('reward', {})
                elif kind == 'jobs': data = data['reward']
                if not isinstance(data, dict): raise ValueError()
                if 'template_id' in data and data['template_id'] is not None:
                    tid, ver = data['template_id'], data.get('template_version')
                    if type(tid) is not int or type(ver) is not int: raise ValueError()
                    template = {'id': str(tid), 'version': ver}
                    q.execute('SELECT '+bounded('v.payload_json')+' document,t.enabled,t.current_version FROM dnf_gm.gift_versions v JOIN dnf_gm.gift_templates t ON t.id=v.template_id WHERE v.template_id=%s AND v.version=%s', (tid, ver)); gift = q.fetchone()
                    if not gift: issues.append('template_missing'); data = {}
                    else:
                        if not gift['enabled']: issues.append('template_disabled')
                        if gift['current_version'] != ver: issues.append('template_version_old')
                        data = payload(gift['document'])
                attachments = data.get('items', [])
                if not isinstance(attachments, list) or len(attachments) > 20: raise ValueError()
                ids = []
                for entry in attachments:
                    if not isinstance(entry, dict) or type(entry.get('id')) is not int or not 1 <= entry['id'] <= 4294967295: raise ValueError()
                    if entry['id'] not in ids: ids.append(entry['id'])
            source_pvf = row.get('source_pvf') or stored_pvf
            if source_pvf and source_pvf != ctx['new']['sha']: issues.append('pvf_bound_reference')
            if source_pvf and source_pvf != ctx['old']['sha']: issues.append('historical_pvf_unknown')
            if kind in ('schedules', 'jobs', 'previews') and (ctx['old']['sha'] != ctx['new']['sha'] or self.settings.upgrade_image_digest and self.settings.upgrade_image_digest != self.settings.image_digest):
                issues.append('recreate_bound_operation')
            for item_id in ids:
                old = ctx['old']['db'].execute('SELECT '+ITEM_SELECT+' FROM items WHERE id=?', (item_id,)).fetchone()
                new = ctx['new']['db'].execute('SELECT '+ITEM_SELECT+' FROM items WHERE id=?', (item_id,)).fetchone()
                before = dict(old) if old and (not source_pvf or source_pvf == ctx['old']['sha']) else None
                after = dict(new) if new else None
                if any(value is None for item in (before, after) if item for value in item.values()): raise ValueError('invalid catalog entry')
                changes = []
                if before is None: changes.append('current_item_unknown')
                if after is None: changes.append('candidate_item_missing')
                if before and after:
                    changes += [field+'_changed' for field in FIELDS[1:] if before[field] != after[field]]
                    if Catalog.annotate({**before, 'reviewed': 0}, {})['mail_kind'] != Catalog.annotate({**after, 'reviewed': 0}, {})['mail_kind']: changes.append('mail_kind_changed')
                q.execute('SELECT enabled FROM dnf_gm.catalog_policy_items WHERE pvf_sha256=%s AND item_id=%s', (ctx['new']['sha'], item_id))
                policy = q.fetchone()
                if policy and not policy['enabled']: changes.append('candidate_policy_disabled')
                a = ctx['art'].get('candidate'); picture = 'not_installed'
                if a:
                    if a['sha'] != ctx['new']['sha']: picture = 'mismatch'
                    else:
                        hit = a['db'].execute('SELECT state FROM item_images WHERE item_id=?', (item_id,)).fetchone(); picture = hit['state'] if hit else 'missing'
                items.append({'id': item_id, 'before': before, 'after': after, 'changes': changes, 'candidate_image_state': picture})
        except (ValueError, TypeError, KeyError, OverflowError): issues.append('unreadable_reference')
        return {'id': ':'.join(map(str, row['position'])), 'label': label, 'status': row['status'], 'template': template,
                'issues': issues, 'items': items, 'needs_review': bool(issues or any(i['changes'] or (kind=='images' and i['candidate_image_state']!='ready') for i in items)),
                'note': '物品属性对照使用当前索引，不是建立引用时的历史快照。堆叠元数据不限制发放数量；历史引用不自动重写。'}

    def page(self, q, kind, token, ctx):
        after = self.position(token, kind, ctx['fingerprint']); rows = self.source_page(q, kind, after, ctx)
        more = len(rows) > 50; rows = rows[:50]
        return {'kind': kind, 'fingerprint': ctx['fingerprint'], 'items': [self.inspect(q, kind, r, ctx) for r in rows],
                'next_cursor': self.cursor(kind, rows[-1]['position'], ctx['fingerprint']) if more else None,
                'scope_note': '本页有界检查；跨页不是同一数据库快照。需要完整引用快照请导出并检查末行complete。'}

    def references(self, kind, fingerprint, cursor=''):
        if kind not in KINDS: raise HTTPException(422, '未知引用类型')
        with self.context(fingerprint) as ctx, self.db.connect() as c, c.cursor() as q:
            return self.page(q, kind, cursor, ctx)

    def export(self, fingerprint):
        with self.context(fingerprint): pass  # fail before sending headers
        def generate():
            count = 0; began = time.monotonic()
            try:
                with self.context(fingerprint) as ctx, self.db.connect() as c, c.cursor() as q:
                    q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'); q.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
                    yield encoded({'type': 'metadata', **self.header(ctx), 'snapshot': 'repeatable_read'})+'\n'
                    counts = {}
                    for kind in KINDS:
                        cursor = ''; counts[kind] = {'checked': 0, 'needs_review': 0}
                        while True:
                            if time.monotonic()-began > 110: raise TimeoutError()
                            page = self.page(q, kind, cursor, ctx)
                            for row in page['items']:
                                count += 1; counts[kind]['checked'] += 1; counts[kind]['needs_review'] += int(row['needs_review'])
                                yield encoded({'type': 'reference', 'kind': kind, **row})+'\n'
                            cursor = page['next_cursor']
                            if cursor is None: break
                # File identity checks and connections close before complete.
                yield encoded({'type': 'complete', 'count': count, 'sources': counts, 'can_deploy': False})+'\n'
            except Exception:
                yield encoded({'type': 'incomplete', 'count': count, 'can_deploy': False, 'reason': '查询超时、索引变化或数据不可读；请重新核对，不将本文件作为完整报告'})+'\n'
        return generate()
