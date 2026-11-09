"""Bounded cross-workflow inbox. It only reads records and offers deep links."""
import time
from datetime import datetime, timedelta, timezone


def mapping(value):
    return value if isinstance(value, dict) else {}


class Workbench:
    def __init__(self, db, maintenance, task_health, settings, game_backups):
        self.db, self.maintenance, self.task_health = db, maintenance, task_health
        self.settings, self.game_backups = settings, game_backups

    def read(self):
        now = int(time.time())
        local = datetime.fromtimestamp(now, timezone(timedelta(hours=8)))
        day_start = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        sections = []
        with self.db.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            connection.begin()
            def collect(key, label, sql, args, convert):
                cursor.execute(sql, args)
                rows = cursor.fetchall()
                sections.append({'key': key, 'label': label, 'items': [convert(row) for row in rows[:20]],
                                 'has_more': len(rows) > 20})
            collect('support', '玩家问题', "SELECT case_id,uid,charac_no,title,status,updated_at FROM dnf_gm.support_cases WHERE status IN ('open','in_progress') ORDER BY updated_at DESC,case_id DESC LIMIT 21", (),
                    lambda row: {**row, 'id': row['case_id'], 'path': '/players/support',
                                 'query': {'uid': str(row['uid']), 'case_id': row['case_id']}})
            # One indexed, capped read per status. A global filesort over all
            # historical operations would defeat the inbox's fixed budget.
            operations = []
            for status in ('uncertain', 'dispatching', 'executing'):
                cursor.execute('SELECT operation_id,action,status,created_at FROM dnf_gm.operations '
                               'WHERE status=%s ORDER BY created_at DESC,operation_id DESC LIMIT 21', (status,))
                operations.extend(cursor.fetchall())
            operations.sort(key=lambda row: (row['created_at'], row['operation_id']), reverse=True)
            sections.append({'key': 'operations', 'label': '结果待核对', 'items': [
                {**row, 'id': row['operation_id'], 'title': '核对原操作 · ' + row['action'],
                 'path': '/system/audit', 'query': {'operation_id': row['operation_id']}}
                for row in operations[:20]], 'has_more': len(operations) > 20})
            collect('batches', '批量异常', "SELECT t.job_id,t.ordinal,t.target_uid,t.charac_no,t.status,t.error_message,t.operation_id,j.reason FROM dnf_gm.reward_targets t JOIN dnf_gm.reward_jobs j ON j.id=t.job_id WHERE t.status IN ('failed','uncertain') AND j.status<>'cancelled' ORDER BY t.status,t.job_id,t.ordinal LIMIT 21", (),
                    lambda row: {**row, 'id': row['job_id'] + ':' + str(row['ordinal']),
                                 'title': row['error_message'] or ('结果待核对' if row['status'] == 'uncertain' else row['reason']),
                                 'path': '/rewards/batches', 'query': {'job_id': row['job_id'], 'status': row['status']}})
            collect('schedules', '今日计划与异常', "SELECT id,title,status,next_due,last_error FROM dnf_gm.schedules WHERE status='needs_attention' OR (status='paused' AND last_error<>'') OR (status='active' AND next_due<%s) ORDER BY next_due,id LIMIT 21", (day_start + 86400,),
                    lambda row: {**row, 'title': row['title'], 'path': '/rewards/schedules', 'query': {'schedule_id': row['id']}})
            # Query exceptions independently of the latest all-state history:
            # newer successes must never hide an unresolved failed run.
            backup_issues = []
            for state in ('failed', 'needs_review'):
                cursor.execute('SELECT run_id,action,state,created_at FROM dnf_gm.game_backup_runs '
                               'WHERE state=%s ORDER BY created_at DESC,run_id DESC LIMIT 21', (state,))
                backup_issues.extend(cursor.fetchall())
            backup_issues.sort(key=lambda row: (row['created_at'], row['run_id']), reverse=True)
            connection.rollback()
        # These services own trusted-file reading and sanitize executor observations.
        try:
            maintenance = mapping(self.maintenance.status())
        except (OSError, ValueError, RuntimeError):
            maintenance = {'state': 'unknown', 'message': '维护状态暂不可读，请在维护中心核对'}
        health = mapping(self.task_health.read())
        for issue in (health.get('issues') or [])[:20]:
            if issue.get('kind') == 'reward':
                key, path, query = 'batches', '/rewards/batches', {'job_id': issue['id']}
            elif issue.get('kind') == 'schedule':
                key, path, query = 'schedules', '/rewards/schedules', {'schedule_id': issue['id']}
            else:
                continue
            section = next(section for section in sections if section['key'] == key)
            if not any(item['id'].split(':')[0] == issue['id'] for item in section['items']):
                if len(section['items']) < 20:
                    section['items'].append({'id': issue['id'], 'title': '任务健康提示 · ' + issue['code'],
                                             'status': issue['code'], 'path': path, 'query': query})
                else:
                    section['has_more'] = True
        from .backup_health import read_health
        management_backup = read_health(self.settings.backup_health_file, now)
        game_backup = self.game_backups.view()
        infrastructure = []
        def alert(identifier, title, status, path, query=None):
            infrastructure.append({'id': identifier, 'title': title, 'status': status,
                                   'path': path, 'query': query or {}})
        if maintenance.get('state') != 'ok' or mapping(maintenance.get('write_gate')).get('state') != 'open':
            alert('maintenance', maintenance.get('message', '维护状态待核对'), maintenance.get('state', 'unknown'), '/system/maintenance')
        if (management_backup['state'] != 'ok' or mapping(management_backup.get('backup')).get('state') != 'recent'
                or mapping(management_backup.get('restore')).get('state') != 'recent'):
            alert('management-backup', 'GM管理库备份或恢复证据待核对', management_backup['state'], '/system/maintenance')
        if health.get('state', 'unknown') == 'unknown' or health.get('truncated'):
            alert('task-health', '后台任务健康状态尚未完整核对', health.get('state', 'unknown'), '/system/diagnostics')
        if not mapping(game_backup.get('worker')).get('configured'):
            alert('game-backup-worker', '游戏存档备份尚未配置或执行器状态过期', 'unknown', '/system/game-backups')
        for run in backup_issues:
            title = {'backup': '游戏存档备份', 'copy': '游戏存档异地副本', 'rehearse': '游戏存档隔离恢复演练'}.get(run['action'], '游戏存档备份操作')
            alert(run['run_id'], title + '需核对', run['state'], '/system/game-backups', {'run_id': run['run_id']})
        sections.append({'key': 'infrastructure', 'label': '维护与备份', 'items': infrastructure[:20], 'has_more': len(infrastructure) > 20})
        return {'sections': sections, 'maintenance': maintenance, 'task_health': health,
                'management_backup': management_backup, 'game_backup': game_backup,
                'checked_at': now, 'timezone': 'Asia/Shanghai', 'read_only': True,
                'note': '每组展示最多20条记录；异常提示不重放任务。当前浏览器保留的待核对编号也应继续按原编号查询。'}
