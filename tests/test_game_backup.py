"""Bounded game-backup protocol tests using synthetic legacy table data."""
import hashlib
import json
import os
from pathlib import Path
import socket
import time

import pytest

from dnfgm.game_backup import (dump_game, row_digest_update, lock_statement, schemas_checked,
                               storage_type, deadline_connection, file_hash, records, MAX_ROW, remap_ddl_schemas)

UUID = '12345678-1234-1234-1234-123456789abc'
BINDING = {'window_id': 'a' * 32, 'pvf_sha256': 'b' * 64, 'program_sha256': 'c' * 64,
           'source_revision_sha256': 'd' * 64, 'image_digest': 'sha256:' + 'e' * 64,
           'server_uuid': UUID}


class FakeCursor:
    def __init__(self, source):
        self.source = source
        self.result = []
        self.closed = False

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.closed = True
    def fetchall(self): return self.result
    def fetchone(self): return self.result.pop(0) if self.result else None

    def execute(self, query, args=()):
        c = self.source
        c.queries.append(query)
        self.result = []
        if query.startswith('SET '): return
        if query == 'SELECT VERSION(),@@server_uuid':
            self.result = [('5.7.44-log', UUID)]
        elif query.startswith('SELECT SCHEMA_NAME,'):
            names = ['dnf_gm', 'mysql', 'game_a', 'game_b'] + (['unexpected'] if c.extra_schema else [])
            self.result = [(n, 'latin1', 'latin1_swedish_ci') for n in sorted(names)]
        elif query.startswith('SELECT TABLE_NAME,ENGINE,TABLE_TYPE'):
            name = args[0]
            self.result = [('players', 'InnoDB', 'BASE TABLE')] if name == 'game_a' else [('legacy', 'MyISAM', 'BASE TABLE')]
        elif query.startswith('SELECT COUNT(*) FROM information_schema.'):
            self.result = [(1 if c.stored_program else 0,)]
        elif query.startswith('LOCK TABLES '):
            assert '`game_a`.`players` READ' in query and '`game_b`.`legacy` READ' in query
            assert 'dnf_gm' not in query and 'READ LOCAL' not in query
            c.locked = True
        elif query == 'UNLOCK TABLES':
            assert c.locked
            c.locked = False
        elif query.startswith('SHOW CREATE TABLE '):
            table = 'players' if 'players' in query else 'legacy'
            engine = 'InnoDB' if table == 'players' else 'MyISAM'
            self.result = [(table, f'CREATE TABLE `{table}` (`UID` int,`body` varbinary(20)) ENGINE={engine}')]
        elif query.startswith('SHOW FULL COLUMNS FROM '):
            self.result = [('UID', 'int(11)', None, 'YES', '', None, '', 'select', ''),
                           ('body', 'varbinary(20)', None, 'YES', '', None, '', 'select', '')]
        elif query == 'SHOW MASTER STATUS':
            assert c.locked
            self.result = [('fixture-bin.000001', 1234, '', '', '')]
        elif query.startswith('SELECT ('):
            assert c.locked and 'HEX(`body`)' in query and 'OCTET_LENGTH' in query
            # No primary key, duplicate rows and legacy bytes are intentional.
            self.result = [(0, None, None)] if c.big else [(1, 1, '00FFB7E7'), (1, 1, '00FFB7E7')]
        else:
            raise AssertionError(query)


class Source:
    def __init__(self, *, extra_schema=False, stored_program=False, big=False):
        self.extra_schema, self.stored_program, self.big = extra_schema, stored_program, big
        self.queries = []
        self.open = True
        self.locked = False
        self._sock = None
    def cursor(self, *_): return FakeCursor(self)
    def rollback(self): pass
    def close(self): self.open = False; self.locked = False


def test_mixed_engine_snapshot_has_every_table_and_exact_legacy_bytes(tmp_path):
    source = Source()
    guards = []
    target = tmp_path / 'game.ndjson'
    result = dump_game(source, target, schemas=['game_a', 'game_b'], binding=BINDING,
                       guard=lambda: guards.append(source.locked))
    assert result['scope'] == 'game_databases' and result['tables'] == 2 and result['rows'] == 4
    assert not source.open and not source.locked
    assert file_hash(target) == (result['artifact_sha256'], result['bytes'])
    with target.open('rb') as f: data = list(records(f))
    assert data[0]['catalog']['tables'][1]['engine'] == 'MyISAM'
    assert data[-1]['type'] == 'complete'
    assert len([r for r in data if r['type'] == 'row']) == 4
    assert data[2]['values'][1] == {'bytes': 'AP+35w=='}
    assert guards[0] is False and guards[-1] is True
    assert result['pitr_verified'] is False


@pytest.mark.parametrize('options,match', [({'extra_schema': True}, 'inventory changed'),
                                          ({'stored_program': True}, 'Stored programs'),
                                          ({'big': True}, 'row exceeds')])
def test_incomplete_scope_program_or_oversized_row_never_publishes(tmp_path, options, match):
    source = Source(**options)
    target = tmp_path / 'game.ndjson'
    with pytest.raises(ValueError, match=match):
        dump_game(source, target, schemas=['game_a', 'game_b'], binding=BINDING, guard=lambda: None)
    assert not source.open and not source.locked
    assert not target.exists() and target.with_name(target.name + '.partial').is_file()


def test_changed_maintenance_guard_closes_connection_and_preserves_partial(tmp_path):
    source = Source()
    calls = 0
    def guard():
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise ValueError('window changed')
    target = tmp_path / 'game.ndjson'
    with pytest.raises(ValueError, match='window changed'):
        dump_game(source, target, schemas=['game_a', 'game_b'], binding=BINDING, guard=guard)
    assert not source.open and not source.locked and not target.exists()


def test_existing_restore_point_is_never_overwritten(tmp_path):
    target = tmp_path / 'game.ndjson'
    target.write_bytes(b'keep original')
    with pytest.raises(FileExistsError):
        dump_game(Source(), target, schemas=['game_a', 'game_b'], binding=BINDING, guard=lambda: None)
    assert target.read_bytes() == b'keep original'


def test_socket_watchdog_interrupts_without_an_extra_database_connection():
    a, b = socket.socketpair()
    source = Source(); source._sock = a
    with pytest.raises(TimeoutError):
        with deadline_connection(source, 0.02):
            time.sleep(0.05)
    assert not source.open
    assert b.recv(1) == b''
    b.close()


def test_multiset_digest_supports_duplicate_rows_and_no_primary_key():
    first = row_digest_update(row_digest_update(0, [1, 'a']), [1, 'b'])
    second = row_digest_update(row_digest_update(0, [1, 'b']), [1, 'a'])
    assert first == second
    assert row_digest_update(first, [1, 'a']) != first
    assert storage_type('bit(16)') == 'bit'
    assert storage_type('varchar(255)') == 'bytes'
    assert storage_type('timestamp(6)') == 'temporal'


def test_sql_inventory_and_record_limits_reject_untrusted_inputs(tmp_path):
    for schemas in (['dnf_gm'], ['mysql'], ['game;DROP'], ['game', 'game'], []):
        with pytest.raises(ValueError): schemas_checked(schemas)
    assert 'READ LOCAL' not in lock_statement([{'schema': 'Game', 'name': 'Characters'}])
    with pytest.raises(ValueError): lock_statement([{'schema': 'game', 'name': 'x` WRITE'}])
    target = tmp_path / 'truncated'; target.write_bytes(b'{"type":"complete"}')
    with target.open('rb') as f:
        with pytest.raises(ValueError, match='Truncated'): list(records(f))


def test_new_schema_versions_are_installed_with_least_privilege():
    import importlib.util
    path = Path(__file__).parents[1] / 'deploy/grants.py'
    spec = importlib.util.spec_from_file_location('game_backup_grants_fixture', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    grants = module.game_backups_sql("'fixture'@'localhost'")
    assert 'game_backup_control' in grants and 'game_backup_runs' in grants
    assert 'DELETE' not in grants and 'LOCK TABLES' not in grants and 'root' not in grants
    campaigns = module.campaigns_sql("'fixture'@'localhost'")
    assert 'SELECT,INSERT ON dnf_gm.campaign_claims' in campaigns
    assert 'SELECT,INSERT ON dnf_gm.campaign_links' in campaigns
    assert 'UPDATE ON dnf_gm.campaign_claims' not in campaigns


def test_published_hardlink_artifact_hash_uses_consistent_stat_semantics(tmp_path):
    partial = tmp_path / 'game.partial'; target = tmp_path / 'game.ndjson'
    partial.write_bytes(b'original private bytes'); partial.chmod(0o600)
    os.link(partial, target); partial.unlink()
    assert file_hash(target) == (hashlib.sha256(target.read_bytes()).hexdigest(), target.stat().st_size)


def test_schema_remapping_preserves_defaults_comments_and_quoted_text():
    ddl = """CREATE TABLE `child` (
      `note` varchar(80) DEFAULT '`game_a`.' COMMENT 'it''s `game_a`.',
      `other` varchar(80) DEFAULT "`game_a`.",
      CONSTRAINT `fk` FOREIGN KEY (`id`) REFERENCES `game_a` . `parent` (`id`)
    ) COMMENT='can\\'t change `game_a`.' /* `game_a`. */"""
    remapped = remap_ddl_schemas(ddl, {'game_a': 'gb_restore_fixture'})
    assert remapped == ddl.replace('REFERENCES `game_a` .', 'REFERENCES `gb_restore_fixture` .')
    assert remap_ddl_schemas(remapped, {'gb_restore_fixture': 'game_a'}) == ddl
