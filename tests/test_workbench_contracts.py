"""Inbox boundaries and degraded file evidence without a running game server."""
from contextlib import contextmanager
from types import SimpleNamespace

from dnfgm.workbench import Workbench


class ReadDatabase:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.active = False
        self.rolled_back = False
        self.statements = []

    @contextmanager
    def connect(self):
        assert not self.active
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    @contextmanager
    def cursor(self):
        yield self

    def begin(self):
        pass

    def rollback(self):
        self.rolled_back = True

    def execute(self, sql, args=()):
        assert sql.startswith(('SELECT ', 'SET TRANSACTION READ ONLY'))
        self.statements.append((sql, args))
        if 'FROM dnf_gm.operations ' in sql:
            self.current = self.rows.get(('operations', args[0]), [])
        elif 'FROM dnf_gm.game_backup_runs ' in sql:
            self.current = self.rows.get(('backups', args[0]), [])
        else:
            self.current = []

    def fetchall(self):
        return self.current


def workbench(db, monkeypatch, *, maintenance=None, health=None, backup=None):
    def released(value):
        assert not db.active, 'file projections and health readers must not nest database connections'
        return value
    monkeypatch.setattr('dnfgm.backup_health.read_health', lambda *args: released(backup or {
        'state': 'unavailable', 'backup': None, 'restore': None}))
    return Workbench(db, SimpleNamespace(status=lambda: released(maintenance)),
        SimpleNamespace(read=lambda: released(health)), SimpleNamespace(backup_health_file='unused'),
        SimpleNamespace(view=lambda: released({'items': [], 'worker': None})))


def section(result, key):
    return next(item for item in result['sections'] if item['key'] == key)


def test_missing_and_null_health_evidence_is_visible_without_crashing(monkeypatch):
    db = ReadDatabase()
    result = workbench(db, monkeypatch, maintenance={'state': 'ok', 'write_gate': None}).read()
    alerts = section(result, 'infrastructure')['items']
    assert {a['id'] for a in alerts} == {'maintenance', 'management-backup', 'game-backup-worker', 'task-health'}
    assert result['read_only'] and db.rolled_back and not db.active
    assert db.statements[0][0] == 'SET TRANSACTION READ ONLY'


def test_inbox_keeps_newest_original_ids_and_states_with_a_visible_cap(monkeypatch):
    rows = {('operations', state): [dict(operation_id=f'{start+i:032x}', action='reward',
            status=state, created_at=start+i) for i in range(21)]
            for state, start in [('uncertain', 0), ('dispatching', 100), ('executing', 200)]}
    db = ReadDatabase(rows)
    result = workbench(db, monkeypatch).read()
    inbox = section(result, 'operations')
    assert len(inbox['items']) == 20 and inbox['has_more']
    assert [item['created_at'] for item in inbox['items']] == list(range(220, 200, -1))
    assert all(item['status'] == 'executing' and item['query']['operation_id'] == item['operation_id']
               for item in inbox['items'])
    reads = [(sql, args) for sql, args in db.statements if 'FROM dnf_gm.operations ' in sql]
    assert len(reads) == 3 and all(sql.endswith('LIMIT 21') for sql, _ in reads)


def test_backup_exception_cap_is_independent_of_recent_success_history(monkeypatch):
    rows = {('backups', 'failed'): [dict(run_id=f'{i:032x}', action='copy', state='failed',
                created_at=i) for i in range(21)],
            ('backups', 'needs_review'): [dict(run_id='f'*32, action='legacy',
                state='needs_review', created_at=100)]}
    db = ReadDatabase(rows)
    result = workbench(db, monkeypatch, maintenance={'state': 'ok', 'write_gate': {'state': 'open'}},
        health={'state': 'clear', 'issues': []}, backup={'state': 'ok', 'backup': {'state': 'recent'},
                                                    'restore': {'state': 'recent'}}).read()
    inbox = section(result, 'infrastructure')
    assert len(inbox['items']) == 20 and inbox['has_more']
    original = next(item for item in inbox['items'] if item['id'] == 'f'*32)
    assert original['query'] == {'run_id': 'f'*32} and original['status'] == 'needs_review'
    assert original['title'] == '游戏存档备份操作需核对'
    assert result['game_backup']['items'] == []
