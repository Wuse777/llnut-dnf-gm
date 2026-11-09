"""Manual game-backup actions inside the existing serial maintenance worker.

No new daemon/timer, automatic maintenance opening or production restore. The
dedicated source connection replaces the worker's management connection while
dumping; both are never held together. The app retains its existing two slots.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time

import pymysql

from dnfgm.alerts import atomic
from dnfgm.game_backup import (dump_game, restore_game_drill, file_hash, write_new, schemas_checked,
                               validate_relation, canonical, ID, HEX)
from dnfgm.inventory_fence import BOUND_FIELDS, _read, read_permit, validate_permit, directory
from dnfgm.release_files import Refused, read_json
from dnfgm.service import one, dump
from configure_task_probe import read_private
from game_backup_copy import encrypted_copy, validate_copy

CONFIG = Path('/etc/dnf-gm/game-backup.json')
ROOT = Path('/var/backups/dnf-gm/game')


def configuration(path, settings, *, owner=0):
    value, st, _ = read_private(Path(path), (owner,), 0o077)
    if (st.st_nlink != 1 or set(value) != {'version', 'connection', 'schemas', 'relations', 'copy', 'lab'}
            or value['version'] != 1):
        raise ValueError('Fixed private game-backup configuration required')
    connection = value['connection']
    if (not isinstance(connection, dict) or set(connection) != {'host', 'port', 'user', 'password'}
            or connection['user'] != 'root' or not isinstance(connection['password'], str) or not connection['password']
            or (connection['host'], connection['port']) != (settings.db_host, settings.db_port)):
        raise ValueError('Game source does not match the installed instance')
    schemas_checked(value['schemas'])
    if not isinstance(value['relations'], list) or len(value['relations']) > 64:
        raise ValueError('Bounded installed relationship checks required')
    for relation in value['relations']:
        validate_relation(relation)
        if relation['child_schema'] not in value['schemas'] or relation['parent_schema'] not in value['schemas']:
            raise ValueError('Relationship check outside business inventory')
        if (relation['child_schema'], relation['child_table']) == (relation['parent_schema'], relation['parent_table']):
            raise ValueError('Self relationships require a separate reviewed lock adapter')
    if len({r['name'] for r in value['relations']}) != len(value['relations']):
        raise ValueError('Duplicate relationship check name')
    validate_copy(value['copy'])
    if value['copy']:
        path = Path(value['copy']['ssh_config'])
        directory(path.parent, owner)
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != owner or st.st_mode & 0o077:
            raise ValueError('Root-only fixed SSH configuration required')
    lab = value['lab']
    if lab is not None and (not isinstance(lab, dict) or set(lab) != {'socket', 'datadir'}
                            or any(not isinstance(v, str) or not Path(v).is_absolute() or '..' in Path(v).parts for v in lab.values())):
        raise ValueError('Explicit socket-only isolated rehearsal target required')
    return value


def public_receipt(receipt):
    # Never publish table names, stored rows, binlog filenames, paths or root
    # connection details. The private manifest retains full recovery evidence.
    fields = ('kind', 'state', 'scope', 'artifact_sha256', 'bytes', 'tables', 'rows', 'started_at', 'completed_at',
              'consistency', 'pitr_verified', 'encrypted', 'encrypted_sha256', 'encrypted_bytes',
              'remote_received_and_hashed', 'remote_restore_verified', 'checks', 'target', 'production_restored',
              'evidence_reconciled', 'mysql')
    return {key: receipt[key] for key in fields if key in receipt}


def request_spec(row):
    if (any(not ID.fullmatch(row.get(key, '')) for key in ('run_id', 'backup_id', 'window_id'))
            or row.get('action') not in ('backup', 'copy', 'rehearse')
            or not HEX.fullmatch(row.get('fingerprint', ''))):
        raise ValueError('Untrusted game-backup request')
    spec = json.loads(row['spec_json'])
    fields = ({'request_id', 'window_id', 'reason', 'image_digest', 'pvf_sha256', 'program_sha256'}
              if row['action'] == 'backup' else {'request_id', 'reason', 'backup_id', 'action', 'artifact_sha256'})
    if (not isinstance(spec, dict) or set(spec) != fields or spec['request_id'] != row['run_id']
            or spec['reason'] != row['reason'] or hashlib.sha256(canonical(spec)).hexdigest() != row['fingerprint']):
        raise ValueError('Game-backup request specification changed')
    if row['action'] == 'backup':
        if (row['run_id'] != row['backup_id'] or spec['window_id'] != row['window_id']
                or any(not HEX.fullmatch(spec.get(k, '')) for k in ('pvf_sha256', 'program_sha256'))):
            raise ValueError('Game-backup source binding changed')
    elif (spec['backup_id'] != row['backup_id'] or spec['action'] != row['action']
            or not HEX.fullmatch(spec.get('artifact_sha256', ''))):
        raise ValueError('Game-backup followup binding changed')
    return spec


class GameBackupWorker:
    def __init__(self, maintenance_worker, settings, *, config=CONFIG, root=ROOT, owner=0,
                 connect=pymysql.connect, clock=time.time):
        self.worker = maintenance_worker
        self.db = maintenance_worker.coordinator.admission.db
        self.settings = settings
        self.config, self.root = Path(config), Path(root)
        self.owner, self.connect, self.clock = owner, connect, clock
        self.next_poll = 0

    def report(self, config=None, state='ready'):
        atomic(Path(self.settings.game_backup_status_file), {'version': 1, 'scope': 'game_databases',
               'checked_at': self.clock(), 'state': state, 'configured': config is not None,
               'copy_configured': bool(config and config['copy']), 'rehearsal_configured': bool(config and config['lab'])}, mode=0o644)

    def claim(self):
        with self.db.connect() as c, c.cursor() as q:
            one(q, 'SELECT revision FROM dnf_gm.game_backup_control WHERE id=1 FOR UPDATE')
            prior = one(q, "SELECT * FROM dnf_gm.game_backup_runs WHERE state='running' ORDER BY created_at,run_id LIMIT 1 FOR UPDATE")
            if prior:
                # Do not re-execute an interrupted export/transport/restore.
                # Outside this DB transaction, reconcile only a durable private
                # receipt, or retain a visible needs_review result.
                return {**prior, '_interrupted': True}
            row = one(q, "SELECT * FROM dnf_gm.game_backup_runs WHERE state='queued' ORDER BY created_at,run_id LIMIT 1 FOR UPDATE")
            if row:
                request_spec(row)
                q.execute("UPDATE dnf_gm.game_backup_runs SET state='running',started_at=%s WHERE run_id=%s", (self.clock(), row['run_id']))
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'maintenance','game-backup-start',%s,%s,%s)",
                          ('game-backup-start:' + row['run_id'], row['reason'], dump({'run_id': row['run_id'], 'action': row['action']}), dump({'state': 'running'})))
                c.commit()
                row = {**row, 'state': 'running', 'started_at': self.clock()}
            return row

    def finish(self, row, result=None, error=None, *, needs_review=False):
        with self.db.connect() as c, c.cursor() as q:
            current = one(q, 'SELECT * FROM dnf_gm.game_backup_runs WHERE run_id=%s FOR UPDATE', (row['run_id'],))
            if not current or current['state'] != 'running':
                return
            state = 'needs_review' if needs_review else 'failed' if error else 'succeeded'
            view = public_receipt(result) if result else None
            q.execute('UPDATE dnf_gm.game_backup_runs SET state=%s,result_json=%s,error_code=%s,finished_at=%s WHERE run_id=%s',
                      (state, dump(view) if view else None, error, self.clock(), row['run_id']))
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'maintenance','game-backup-finish',%s,%s,%s)",
                      ('game-backup-finish:' + row['run_id'], row['reason'], dump({'run_id': row['run_id']}), dump({'state': state, 'result': view, 'error_code': error})))
            c.commit()

    def durable_receipt(self, row):
        """Read-only completion recovery; never repeat an uncertain side effect."""
        spec = request_spec(row)
        folder, original = self.original(row['backup_id'])
        if original.get('binding', {}).get('window_id') != row['window_id']:
            raise ValueError('Interrupted backup window binding changed')
        if row['action'] == 'backup':
            if (row['backup_id'] != row['run_id'] or original.get('kind') != 'backup'
                    or original.get('consistency') != 'all_business_tables_read_locked'
                    or any(original['binding'].get(k) != spec.get(k) for k in ('image_digest', 'pvf_sha256', 'program_sha256'))):
                raise ValueError('Interrupted backup evidence does not match the request')
            receipt = original
        else:
            receipt = read_json(folder / (row['action'] + '-' + row['run_id'] + '.json'), owner=self.owner, limit=1024 * 1024)
            if spec.get('artifact_sha256') != original['artifact_sha256']:
                raise ValueError('Interrupted followup original artifact changed')
            if row['action'] == 'copy':
                if (receipt.get('kind') != 'copy' or receipt.get('encrypted') is not True
                        or receipt.get('remote_received_and_hashed') is not True
                        or receipt.get('remote_restore_verified') is not False
                        or not HEX.fullmatch(receipt.get('encrypted_sha256', ''))
                        or receipt.get('backup_id') != row['backup_id']):
                    raise ValueError('Interrupted encrypted-copy receipt incomplete')
            elif (receipt.get('kind') != 'restore' or receipt.get('target') != 'isolated_exact_mysql57'
                    or receipt.get('production_restored') is not False
                    or set(receipt.get('checks', [])) != {'exact_mysql_version', 'table_definitions', 'all_stored_values',
                        'row_counts', 'business_relationships', 'artifact_sha256'}):
                raise ValueError('Interrupted isolated-drill receipt incomplete')
            if receipt.get('state') != 'verified':
                raise ValueError('Interrupted followup has no verified receipt')
        if (receipt.get('scope') != 'game_databases' or receipt.get('artifact_sha256') != original['artifact_sha256']
                or not row.get('started_at') or not row['started_at'] <= receipt['started_at'] <= receipt['completed_at'] <= self.clock()):
            raise ValueError('Interrupted receipt identity/timing changed')
        return {**receipt, 'evidence_reconciled': True}

    @contextmanager
    def heartbeat(self, config):
        stop = threading.Event()
        def beat():
            while not stop.wait(5):
                try:
                    self.report(config, 'running')
                    # Existing heartbeat reads only files, never game tables.
                    self.worker.publish_status()
                except Exception:
                    pass
        thread = threading.Thread(target=beat, name='game-backup-public-status', daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set(); thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('Game backup status publisher did not stop')

    def original(self, backup_id):
        folder = self.root / ('game-' + backup_id)
        directory(folder, self.owner)
        if folder.stat().st_mode & 0o077:
            raise ValueError('Private restore-point directory required')
        receipt = read_json(folder / 'manifest.json', owner=self.owner, limit=1024 * 1024)
        if (receipt.get('format') != 'dnfgm-game-1' or receipt.get('state') != 'complete'
                or receipt.get('scope') != 'game_databases'
                or file_hash(folder / 'game.ndjson') != (receipt['artifact_sha256'], receipt['bytes'])):
            raise ValueError('Original game restore-point evidence incomplete')
        return folder, receipt

    def backup(self, row, config):
        c = self.worker.coordinator
        session, window = self.worker.session, self.worker.session.window
        # Global lock excludes close/recover, deployments and management backup;
        # exclusive fence excludes equipment/character maintenance transactions.
        # The locks remain held until the dedicated DB connection is closed.
        with c.locked(), window.locked(True):
            op = row['window_id']
            if c._active() != op:
                raise ValueError('Original maintenance session no longer owns the instance')
            plan, token = session._plan(op)
            state = session._load(op, plan)
            if state['state'] != 'maintenance_open' or c._load(op)['state'] != 'writers_stopped':
                raise ValueError('All-writers-stopped original maintenance window required')
            spec = request_spec(row)
            if any(spec[k] != plan['identity'][k] for k in ('image_digest', 'pvf_sha256', 'program_sha256')):
                raise ValueError('Previewed game identity changed')
            permit = read_permit(window.root, self.owner)
            expected_binding = session.binding(plan)
            if permit['id'] != op or any(permit[k] != v for k, v in expected_binding.items()):
                raise ValueError('Original maintenance permit changed')
            # The normal monitor needs this same exclusive fence. During the
            # backup we refresh its evidence ourselves under the already-held
            # lock, using only host probes/files, never a locked DB transaction.
            checked = [float('-inf')]
            def guard():
                if shutil.disk_usage(self.root).free < 2 * 1024 ** 3:
                    raise ValueError('Game backup disk reserve exhausted')
                current = read_permit(window.root, self.owner)
                if current != permit:
                    raise ValueError('Original game backup permit changed')
                c.admission.verify_frozen(token)
                if time.monotonic() - checked[0] >= 5:
                    sample = window.checked_snapshot()
                    if any(sample[k] != permit[k] for k in BOUND_FIELDS):
                        raise ValueError('Live stopped-writer/source identity changed')
                    c.lifecycle.check(plan, c.lifecycle.stopped_snapshot(plan))
                    from dnfgm.release_files import atomic_json
                    atomic_json(window.root / 'evidence.json', {**sample, 'permit_id': op})
                    checked[0] = time.monotonic()
            guard()
            remaining = min(540, permit['expires_at'] - time.time() - 5,
                            permit['expires_monotonic'] - time.monotonic() - 5)
            if remaining < 15:
                raise ValueError('Maintenance window has insufficient backup time remaining')
            folder = self.root / ('game-' + row['run_id'])
            folder.mkdir(mode=0o700)
            package = Path(__file__).resolve().parents[1]
            source = package / 'SOURCE_REVISION'
            if not source.is_file():
                source = package / 'src/dnfgm/game_backup.py'
            revision_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            binding = {**{k: permit[k] for k in ('image_digest', 'pvf_sha256', 'program_sha256')},
                       'window_id': op, 'server_uuid': plan['admission']['server_uuid'],
                       'source_revision_sha256': revision_sha}
            connection = self.connect(**config['connection'], charset='utf8mb4', autocommit=False,
                                      connect_timeout=3, read_timeout=10, write_timeout=10, local_infile=False)
            receipt = dump_game(connection, folder / 'game.ndjson', schemas=config['schemas'], binding=binding,
                                guard=guard, relations=config['relations'], budget=remaining)
            write_new(folder / 'manifest.json', receipt)
            return receipt

    def execute(self, row, config):
        spec = request_spec(row)
        if row['action'] == 'backup':
            return self.backup(row, config)
        folder, original = self.original(row['backup_id'])
        if spec['artifact_sha256'] != original['artifact_sha256']:
            raise ValueError('Followup no longer matches the original restore point')
        with self.worker.coordinator.locked():
            if row['action'] == 'copy':
                receipt = encrypted_copy(folder / 'game.ndjson', row['backup_id'], original['artifact_sha256'], config['copy'])
            else:
                if config['lab'] is None:
                    raise ValueError('No explicit isolated rehearsal target configured')
                receipt = restore_game_drill(folder / 'game.ndjson', original['artifact_sha256'], **config['lab'])
            write_new(folder / (row['action'] + '-' + row['run_id'] + '.json'), receipt)
            return receipt

    def tick(self, *, force=False):
        if not force and time.monotonic() < self.next_poll:
            return
        self.next_poll = time.monotonic() + 5
        if not self.config.exists():
            self.report(state='unconfigured')
            return
        try:
            config = configuration(self.config, self.settings, owner=self.owner)
            directory(self.root, self.owner)
            if self.root.stat().st_mode & 0o077:
                raise ValueError('Private game backup root required')
        except Exception:
            self.report(state='error')
            return
        row = self.claim()
        if not row:
            self.report(config)
            return
        if row.get('_interrupted'):
            try:
                receipt = self.durable_receipt(row)
            except Exception:
                self.finish(row, error='game_backup_interrupted', needs_review=True)
            else:
                self.finish(row, receipt)
            self.report(config)
            return
        self.report(config, 'running')
        try:
            with self.heartbeat(config):
                receipt = self.execute(row, config)
        except Exception:
            try:
                receipt = self.durable_receipt(row)
            except Exception:
                self.finish(row, error='game_backup_action_failed')
            else:
                self.finish(row, receipt)
        else:
            # A lost management response leaves running intact for the next
            # read-only reconciliation; do not turn a valid receipt into a
            # failed action merely because this result transaction was lost.
            self.finish(row, receipt)
        self.report(config)
