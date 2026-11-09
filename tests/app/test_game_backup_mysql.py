"""Actual mixed-engine locks and isolated restore; only the existing socket lab."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import time

import pymysql
import pytest

from dnfgm.backup import assert_lab
from dnfgm.game_backup import dump_game, restore_game_drill, database_identity, sql, SYSTEM_SCHEMAS
from dnfgm_m0.lab import connect


def prepare(lab):
    source = connect(lab.socket)
    socket, datadir = sql(source, 'SELECT @@socket,@@datadir')[0]
    assert_lab(source, socket, datadir)
    with source.cursor() as q:
        q.execute("CREATE TABLE taiwan_cain.fixture_game_backup (UID int,body varbinary(20),bits bit(9),moment datetime,"
                  "note varchar(80) NOT NULL DEFAULT '100% `taiwan_cain`.' COMMENT 'Chance 50% `taiwan_cain`.') "
                  "ENGINE=MyISAM COMMENT='Backup is 100% exact `taiwan_cain`.'")
        q.execute("INSERT INTO taiwan_cain.fixture_game_backup(UID,body,bits,moment) VALUES"
                  "(1,UNHEX('00FFB7E7'),257,'0000-00-00 00:00:00'),(1,UNHEX('00FFB7E7'),257,'0000-00-00 00:00:00')")
    source.commit()
    schemas = sorted({r[0] for r in sql(source, 'SHOW DATABASES')} - SYSTEM_SCHEMAS)
    ident = database_identity(source)
    binding = {'window_id': 'a' * 32, 'pvf_sha256': 'b' * 64, 'program_sha256': 'c' * 64,
               'source_revision_sha256': 'd' * 64, 'image_digest': 'sha256:' + 'e' * 64,
               'server_uuid': ident['server_uuid']}
    return source, socket, datadir, schemas, binding


def assert_clean(lab):
    c = connect(lab.socket)
    try:
        assert sql(c, "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE 'gb_restore_%'") == ()
        assert sql(c, "SELECT User FROM mysql.user WHERE User LIKE 'gbr_%'") == ()
    finally:c.close()


def test_mixed_innodb_myisam_no_primary_key_roundtrip_and_locks(lab, tmp_path):
    source, socket, datadir, schemas, binding = prepare(lab)
    writer_started = threading.Event(); writer_done = threading.Event(); errors = []
    def write_later():
        c = connect(lab.socket)
        try:
            writer_started.set()
            with c.cursor() as q:q.execute('UPDATE taiwan_cain.fixture_game_backup SET UID=2 WHERE UID=1')
            c.commit(); writer_done.set()
        except Exception as e: errors.append(type(e).__name__)
        finally:c.close()
    checks = []
    thread = None
    def guard():
        nonlocal thread
        checks.append(time.monotonic())
        # Second guard is after LOCK TABLES; verify the writer cannot complete
        # while the source owns all READ locks, including the MyISAM table.
        if len(checks) == 2:
            thread = threading.Thread(target=write_later); thread.start()
            assert writer_started.wait(3)
            assert not writer_done.wait(0.1)
    relations = [{'name': 'characters_account', 'child_schema': 'taiwan_cain', 'child_table': 'charac_info',
                  'child_column': 'm_id', 'parent_schema': 'd_taiwan', 'parent_table': 'accounts', 'parent_column': 'UID'}]
    artifact = tmp_path / 'game.ndjson'
    result = dump_game(source, artifact, schemas=schemas, binding=binding, guard=guard, relations=relations)
    thread.join(timeout=5)
    assert writer_done.is_set() and not errors
    text = artifact.read_text()
    assert 'AP+35w==' in text
    fixture_ddl = next(r['ddl'] for r in map(json.loads, text.splitlines())
                       if r.get('type') == 'table' and r.get('name') == 'fixture_game_backup')
    assert "DEFAULT '100% `taiwan_cain`.'" in fixture_ddl
    assert "COMMENT 'Chance 50% `taiwan_cain`.'" in fixture_ddl
    assert "COMMENT='Backup is 100% exact `taiwan_cain`.'" in fixture_ddl
    restored = restore_game_drill(artifact, result['artifact_sha256'], socket=socket, datadir=datadir)
    assert restored['state'] == 'verified'
    assert (restored['tables'], restored['rows']) == (result['tables'], result['rows'])
    assert restored['relations'] == result['relations'] and restored['production_restored'] is False
    assert_clean(lab)


def test_guard_interrupt_releases_real_myisam_and_innodb_locks(lab, tmp_path):
    source, _, _, schemas, binding = prepare(lab)
    calls = 0
    def guard():
        nonlocal calls
        calls += 1
        if calls == 2: raise ValueError('original maintenance window changed')
    artifact = tmp_path / 'interrupted.ndjson'
    with pytest.raises(ValueError, match='window changed'):
        dump_game(source, artifact, schemas=schemas, binding=binding, guard=guard)
    assert not source.open and not artifact.exists()
    writer = connect(lab.socket)
    try:
        sql(writer, 'SET SESSION lock_wait_timeout=1')
        sql(writer, 'SET SESSION innodb_lock_wait_timeout=1')
        sql(writer, 'UPDATE taiwan_cain.fixture_game_backup SET UID=3')
        sql(writer, 'UPDATE taiwan_cain.charac_info SET lev=lev+1 WHERE charac_no=900001')
        writer.commit()
    finally:writer.close()


def test_deadline_interrupts_real_lock_wait_without_killing_the_other_transaction(lab, tmp_path):
    source, _, _, schemas, binding = prepare(lab)
    holder = connect(lab.socket)
    try:
        sql(holder, 'UPDATE taiwan_cain.charac_info SET lev=lev+1 WHERE charac_no=900001')
        began = time.monotonic()
        with pytest.raises((pymysql.MySQLError, OSError, TimeoutError)):
            dump_game(source, tmp_path / 'waiting.ndjson', schemas=schemas, binding=binding,
                      guard=lambda: None, budget=0.15)
        assert time.monotonic() - began < 5 and not source.open
        # The independent holder remains alive; no KILL connection was needed.
        assert sql(holder, 'SELECT lev FROM taiwan_cain.charac_info WHERE charac_no=900001')
        holder.rollback()
        sql(holder, 'UPDATE taiwan_cain.fixture_game_backup SET UID=4')
        holder.commit()
    finally:holder.close()


def test_wrong_database_binding_and_artifact_tampering_fail_before_restore(lab, tmp_path):
    source, socket, datadir, schemas, binding = prepare(lab)
    wrong = {**binding, 'server_uuid': 'different-source'}
    with pytest.raises(ValueError, match='database identity changed'):
        dump_game(source, tmp_path / 'wrong.ndjson', schemas=schemas, binding=wrong, guard=lambda: None)
    assert not source.open
    source = connect(lab.socket)
    artifact = tmp_path / 'valid.ndjson'
    result = dump_game(source, artifact, schemas=schemas, binding=binding, guard=lambda: None)
    with artifact.open('ab') as output:output.write(b'tampered\n')
    with pytest.raises(ValueError, match='checksum mismatch'):
        restore_game_drill(artifact, result['artifact_sha256'], socket=socket, datadir=datadir)
    assert_clean(lab)


def test_wrong_lab_identity_is_rejected_and_artifact_ddl_never_gets_root_rights(lab, tmp_path):
    source, socket, datadir, schemas, binding = prepare(lab)
    artifact = tmp_path / 'valid.ndjson'
    result = dump_game(source, artifact, schemas=schemas, binding=binding, guard=lambda: None)
    with pytest.raises(ValueError):
        restore_game_drill(artifact, result['artifact_sha256'], socket=socket, datadir=datadir + '/wrong')
    # Deliberately give an artifact the correct new hash but executable DDL
    # attempting to read a source schema. The throwaway user has no such right.
    records = [json.loads(line) for line in artifact.read_text().splitlines()]
    first = next(r for r in records if r['type'] == 'table')
    first['ddl'] = ('CREATE TABLE `' + first['name'] + '` (`stolen` bigint) ENGINE=InnoDB '
                    'AS SELECT UID AS stolen FROM d_taiwan.accounts')
    malicious = tmp_path / 'untrusted-ddl.ndjson'
    malicious.write_text(''.join(json.dumps(r) + '\n' for r in records))
    malicious.chmod(0o600)
    with pytest.raises(pymysql.MySQLError):
        restore_game_drill(malicious, hashlib.sha256(malicious.read_bytes()).hexdigest(), socket=socket, datadir=datadir)
    assert_clean(lab)


def load_deploy(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[2] / 'deploy' / filename)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_fixed_web_grants_allow_request_locking_without_game_or_ddl_rights(env):
    _, _, db, _ = env
    grants = load_deploy('game_backup_web_grants_mysql_test', 'grants.py')
    user = 'gb_app_' + secrets.token_hex(6); password = secrets.token_hex(20)
    connection = None
    with db.connect() as root, root.cursor() as q:
        q.execute("CREATE USER %s@'localhost' IDENTIFIED BY %s", (user, password))
        try:
            for statement in grants.game_backups_sql("'" + user + "'@'localhost'").split(';'):
                if statement.strip(): q.execute(statement)
            root.commit()
            connection = pymysql.connect(unix_socket=root.unix_socket, user=user, password=password, autocommit=False)
            with connection.cursor() as restricted:
                restricted.execute('SELECT revision FROM dnf_gm.game_backup_control WHERE id=1 FOR UPDATE')
                assert restricted.fetchone() == (1,)
                connection.rollback()
                with pytest.raises(pymysql.MySQLError):
                    restricted.execute('SELECT * FROM taiwan_cain.charac_info')
                with pytest.raises(pymysql.MySQLError):
                    restricted.execute('DROP TABLE dnf_gm.game_backup_control')
                with pytest.raises(pymysql.MySQLError):
                    restricted.execute('UPDATE dnf_gm.game_backup_runs SET spec_json=JSON_OBJECT()')
        finally:
            if connection is not None: connection.close()
            q.execute("DROP USER %s@'localhost'", (user,))


@pytest.mark.skipif(not shutil.which('age') or not shutil.which('age-keygen'), reason='Install age for actual encrypted-copy integration')
def test_actual_age_receiver_decryption_and_database_restore_chain(lab, tmp_path, monkeypatch):
    """Real encryption and receiver on separate private dirs; no remote-host claim."""
    source, socket, datadir, schemas, binding = prepare(lab)
    artifact = tmp_path / 'valid.ndjson'
    result = dump_game(source, artifact, schemas=schemas, binding=binding, guard=lambda: None)
    transport = load_deploy('game_backup_copy_mysql_test', 'game_backup_copy.py')
    receiver = load_deploy('game_backup_receive_mysql_test', 'game_backup_receive.py')
    key = tmp_path / 'test-only-age-identity'
    subprocess.run(['age-keygen', '-o', str(key)], capture_output=True, check=True)
    recipient = subprocess.run(['age-keygen', '-y', str(key)], capture_output=True, text=True, check=True).stdout.strip()
    remote = tmp_path / 'receiver';remote.mkdir(mode=0o700)
    remote_machine = transport.machine_sha256()
    # Tests exercise sender/receiver protocol locally; distinct-host detection
    # itself is covered by the same-machine rejection unit test.
    monkeypatch.setattr(transport, 'machine_sha256', lambda: 'f' * 64)
    config = {'age_recipient': recipient, 'ssh_config': str(tmp_path / 'fixed-ssh'),
              'ssh_host': 'fixture-receiver', 'remote_machine_sha256': remote_machine}
    def run(argv, *, stdin, output, timeout, max_output):
        if argv[0] == 'age':
            return transport.checked_process(argv, stdin=stdin, output=output, timeout=timeout, max_output=max_output)
        receipt = receiver.receive(' '.join(argv[-4:]), stdin, root=remote)
        output.write(json.dumps(receipt).encode())
    copied = transport.encrypted_copy(artifact, 'a' * 32, result['artifact_sha256'], config, run=run)
    assert copied['remote_received_and_hashed'] and not copied['remote_restore_verified']
    recovered = tmp_path / 'decrypted.ndjson'
    with recovered.open('xb') as output:
        recovered.chmod(0o600)
        subprocess.run(['age', '-d', '-i', str(key), str(remote / ('a' * 32 + '.ndjson.age'))], stdout=output, stderr=subprocess.PIPE, check=True)
    assert hashlib.sha256(recovered.read_bytes()).hexdigest() == result['artifact_sha256']
    drill = restore_game_drill(recovered, result['artifact_sha256'], socket=socket, datadir=datadir)
    assert drill['state'] == 'verified' and drill['rows'] == result['rows']
    assert_clean(lab)
