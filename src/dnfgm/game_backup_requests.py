"""Authenticated manual requests for fixed game restore-point actions.

No paths, SQL, connection information, remote targets or restore destinations
are accepted from the browser. Game services are never stopped by this module.
"""
import hashlib
import json
from pathlib import Path
import time

from fastapi import HTTPException
from pydantic import Field

from .backup import canonical
from .models import Model


def one(cursor, statement, args=()):
    cursor.execute(statement, args)
    return cursor.fetchone()


def dump(value):
    return canonical(value).decode('utf-8')


class GameBackupPreview(Model):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    window_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(min_length=1, max_length=200)


class GameBackupConfirm(Model):
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledge_game_scope: bool


class GameBackupFollowup(Model):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(min_length=1, max_length=200)


def run_view(row):
    return {k: row.get(k) for k in ('run_id', 'backup_id', 'action', 'window_id', 'reason', 'state',
            'fingerprint', 'created_at', 'expires_at', 'started_at', 'finished_at', 'error_code')} | {
            'scope': 'game_databases', 'result': json.loads(row['result_json']) if row.get('result_json') else None,
            'automatic_game_stop': False, 'production_restore_available': False}


class GameBackups:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    @property
    def status_path(self):
        return Path(self.settings.game_backup_status_file)

    def installed(self):
        from .alerts import read_json
        try:
            value = read_json(self.status_path)
            if (value.get('version') != 1 or value.get('scope') != 'game_databases'
                    or not 0 <= time.time() - value['checked_at'] <= 90):
                raise ValueError('Stale game backup worker')
            return {k: value.get(k) for k in ('configured', 'copy_configured', 'rehearsal_configured', 'checked_at', 'scope', 'state')}
        except (OSError, ValueError, TypeError, KeyError):
            return {'configured': False, 'copy_configured': False, 'rehearsal_configured': False,
                    'scope': 'game_databases', 'state': 'unknown', 'checked_at': None}

    def view(self, page=1):
        with self.db.connect() as c, c.cursor() as q:
            q.execute('SELECT * FROM dnf_gm.game_backup_runs ORDER BY created_at DESC,run_id DESC LIMIT 21 OFFSET %s', ((page - 1) * 20,))
            rows = q.fetchall()
            latest = one(q, "SELECT * FROM dnf_gm.game_backup_runs WHERE action='backup' AND state='succeeded' ORDER BY created_at DESC,run_id DESC LIMIT 1")
            latest_backup = ({**run_view(latest), 'evidence': self.evidence(q, latest)} if latest else None)
        return {'items': [run_view(r) for r in rows[:20]], 'has_more': len(rows) > 20,
                'page': page, 'scope': 'game_databases', 'worker': self.installed(),
                'latest_backup': latest_backup,
                'note': '玩家存档恢复点与GM管理库备份分开；仅在已开启维护窗口中手动备份，不自动停游戏。'}

    def evidence(self, q, original):
        result = json.loads(original.get('result_json') or '{}')
        sha = result.get('artifact_sha256')
        evidence = {'artifact_sha256': sha, 'backup': run_view(original), 'copy': None, 'rehearse': None}
        for action in ('copy', 'rehearse'):
            args = (original['backup_id'], action)
            latest = one(q, 'SELECT * FROM dnf_gm.game_backup_runs WHERE backup_id=%s AND action=%s ORDER BY created_at DESC,run_id DESC LIMIT 1', args)
            # Query success independently of list pagination and newer failures.
            # A receipt for another artifact never makes this restore point green.
            verified = (one(q, "SELECT * FROM dnf_gm.game_backup_runs WHERE backup_id=%s AND action=%s AND state='succeeded' "
                              "AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.artifact_sha256'))=%s ORDER BY created_at DESC,run_id DESC LIMIT 1",
                            args + (sha,)) if sha and original['state'] == 'succeeded' else None)
            evidence[action] = {'latest_attempt': run_view(latest) if latest else None,
                                'verified_run': run_view(verified) if verified else None}
        return evidence

    def detail(self, run_id):
        with self.db.connect() as c, c.cursor() as q:
            row = one(q, 'SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s', (run_id,))
            if not row:
                raise HTTPException(404, '游戏备份请求不存在，请保留原编号核对')
            original = one(q, "SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s AND action='backup'", (row['backup_id'],))
            q.execute('SELECT * FROM dnf_gm.game_backup_runs WHERE backup_id=%s ORDER BY created_at DESC,run_id DESC LIMIT 20', (row['backup_id'],))
            related = q.fetchall()
            evidence = self.evidence(q, original) if original else None
        return {**run_view(row), 'original_backup': run_view(original) if original else None,
                'related_runs': [run_view(r) for r in related], 'evidence': evidence}

    def preview(self, data):
        data = GameBackupPreview(**data).model_dump()
        data['reason'] = data['reason'].strip()
        if not data['reason']:
            raise HTTPException(422, '请填写玩家存档备份原因')
        installed = self.installed()
        if not installed['configured']:
            raise HTTPException(409, '游戏存档备份执行器尚未配置或状态过期')
        from .inventory_fence import read_permit
        try:
            permit = read_permit('/run/dnf-gm/maintenance')
        except (OSError, ValueError):
            raise HTTPException(409, '请先在维护中心开启并核验维护窗口') from None
        if (permit['id'] != data['window_id'] or permit['pvf_sha256'] != self.settings.pvf_sha256
                or permit['image_digest'] != self.settings.image_digest):
            raise HTTPException(409, '原维护窗口或游戏版本已变化')
        spec = {**data, 'image_digest': self.settings.image_digest, 'pvf_sha256': self.settings.pvf_sha256,
                'program_sha256': self.settings.inventory_program_sha256}
        return self._create(data['request_id'], data['request_id'], 'backup', data['window_id'], data['reason'], spec, 'preview')

    def _create(self, run_id, backup_id, action, window_id, reason, spec, state):
        fingerprint = hashlib.sha256(canonical(spec)).hexdigest()
        now = time.time()
        with self.db.connect() as c, c.cursor() as q:
            # Serialize requests without introducing a second scheduler.
            one(q, 'SELECT revision FROM dnf_gm.game_backup_control WHERE id=1 FOR UPDATE')
            prior = one(q, 'SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s', (run_id,))
            if prior:
                if prior['fingerprint'] != fingerprint or prior['action'] != action or prior['backup_id'] != backup_id:
                    raise HTTPException(409, '原请求编号已绑定不同备份操作')
                return run_view(prior)
            if one(q, "SELECT run_id FROM dnf_gm.game_backup_runs WHERE state IN ('queued','running') LIMIT 1"):
                raise HTTPException(409, '已有排队或执行中的游戏备份操作，请核对原编号')
            q.execute('INSERT INTO dnf_gm.game_backup_runs(run_id,backup_id,action,window_id,reason,state,fingerprint,spec_json,created_at,expires_at) '
                      'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                      (run_id, backup_id, action, window_id, reason, state, fingerprint, dump(spec), now, now + 300))
            result = run_view(one(q, 'SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s', (run_id,)))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner',%s,%s,%s,%s)",
                      ('game-backup:' + run_id, 'game-backup-' + action, reason, dump(spec), dump(result)))
            c.commit()
            return result

    def confirm(self, run_id, data):
        data = GameBackupConfirm(**data).model_dump()
        if data['acknowledge_game_scope'] is not True:
            raise HTTPException(422, '请确认正在备份玩家存档，且不会自动关闭或恢复维护窗口')
        with self.db.connect() as c, c.cursor() as q:
            one(q, 'SELECT revision FROM dnf_gm.game_backup_control WHERE id=1 FOR UPDATE')
            row = one(q, 'SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s FOR UPDATE', (run_id,))
            if not row or row['action'] != 'backup' or row['fingerprint'] != data['fingerprint']:
                raise HTTPException(409, '游戏备份预览已变化，请核对原编号')
            if row['state'] != 'preview':
                return run_view(row)
            if row['expires_at'] < time.time():
                raise HTTPException(409, '备份预览已过期，请重新预览')
            if one(q, "SELECT run_id FROM dnf_gm.game_backup_runs WHERE state IN ('queued','running') LIMIT 1"):
                raise HTTPException(409, '已有游戏备份请求正在执行')
            q.execute("UPDATE dnf_gm.game_backup_runs SET state='queued' WHERE run_id=%s", (run_id,))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','game-backup-confirm',%s,%s,%s)",
                      ('game-backup-confirm:' + run_id, row['reason'], dump(data), dump({'state': 'queued', 'run_id': run_id})))
            c.commit()
        return self.detail(run_id)

    def followup(self, backup_id, action, data):
        if action not in ('copy', 'rehearse'):
            raise HTTPException(422, '不支持的游戏备份操作')
        data = GameBackupFollowup(**data).model_dump()
        data['reason'] = data['reason'].strip()
        if not data['reason']:
            raise HTTPException(422, '请填写操作原因')
        installed = self.installed()
        if not installed[action == 'copy' and 'copy_configured' or 'rehearsal_configured']:
            raise HTTPException(409, '对应的异地副本或隔离演练目标尚未配置')
        with self.db.connect() as c, c.cursor() as q:
            original = one(q, "SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s AND action='backup' AND state='succeeded'", (backup_id,))
        if original is None:
            raise HTTPException(409, '只有完整成功的原始玩家存档备份可复制或演练')
        original_result = json.loads(original['result_json'])
        spec = {**data, 'backup_id': backup_id, 'action': action, 'artifact_sha256': original_result['artifact_sha256']}
        return self._create(data['request_id'], backup_id, action, original['window_id'], data['reason'], spec, 'queued')
