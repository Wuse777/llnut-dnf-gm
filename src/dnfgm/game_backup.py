"""Private game restore points; mixed engines, bounded locks and isolated drills.

The caller must hold the existing maintenance/coordinator and exclusive inventory
fence. This module NEVER stops services or restores a production database. One
dedicated maintenance connection holds all business-table READ locks and streams
their data; no global read lock blocks the separate GM management schema.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket as sockets
import stat
import threading
import time
import uuid

import pymysql

from .backup import canonical, pack, unpack, configure, assert_lab

FORMAT = 'dnfgm-game-1'
SCOPE = 'game_databases'
MAX_BYTES = 8 * 1024 ** 3
MAX_ENCRYPTED_BYTES = 9 * 1024 ** 3
MAX_LINE = 4 * 1024 ** 2
MAX_ROW = 1024 ** 2
MAX_TABLES = 2048
MAX_METADATA = 8 * 1024 ** 2
SYSTEM_SCHEMAS = {'information_schema', 'performance_schema', 'mysql', 'sys', 'dnf_gm'}
HEX = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[a-f0-9]{32}\Z')
MODULUS = 1 << 256


def identifier(value):
    # Legacy game columns include UID/VIP/maxHP; management-only identifiers
    # intentionally use a narrower lowercase convention in backup.py.
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', value):
        raise ValueError('Unsupported game database identifier')
    return '`' + value + '`'


def qualified(schema, table):
    return identifier(schema) + '.' + identifier(table)


def schemas_checked(schemas):
    if (not isinstance(schemas, (list, tuple)) or not 1 <= len(schemas) <= 64
            or len(set(schemas)) != len(schemas) or set(schemas) & SYSTEM_SCHEMAS):
        raise ValueError('Explicit complete business schema list required')
    for name in schemas:
        identifier(name)
    return sorted(schemas)


def sql(c, statement, args=()):
    with c.cursor(pymysql.cursors.Cursor) as q:
        q.execute(statement, args)
        return q.fetchall()


def database_identity(c):
    version, server_uuid = sql(c, 'SELECT VERSION(),@@server_uuid')[0]
    if not re.fullmatch(r'5\.7\.\d+(?:[-+].*)?', version):
        raise ValueError('Reviewed MySQL 5.7 source required')
    return {'mysql': version, 'server_uuid': server_uuid}


def inventory(c, schemas, *, complete_scope=True):
    schemas = schemas_checked(schemas)
    available = sql(c, 'SELECT SCHEMA_NAME,DEFAULT_CHARACTER_SET_NAME,DEFAULT_COLLATION_NAME '
                       'FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME')
    business = {r[0] for r in available} - SYSTEM_SCHEMAS
    if complete_scope and business != set(schemas):
        raise ValueError('Configured business database inventory changed')
    if not set(schemas) <= {r[0] for r in available}:
        raise ValueError('A configured business schema is missing')
    result = {'schemas': [], 'tables': []}
    for schema, charset, collation in available:
        if schema not in schemas:
            continue
        if not re.fullmatch(r'[a-z0-9_]+', charset + collation):
            raise ValueError('Unsupported schema character set')
        result['schemas'].append({'name': schema, 'charset': charset, 'collation': collation})
        tables = sql(c, 'SELECT TABLE_NAME,ENGINE,TABLE_TYPE FROM information_schema.TABLES '
                        'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME LIMIT 2049', (schema,))
        for name, engine, kind in tables:
            identifier(name)
            if kind != 'BASE TABLE' or engine not in ('InnoDB', 'MyISAM'):
                raise ValueError('Unreviewed view/table engine; backup is incomplete')
            result['tables'].append({'schema': schema, 'name': name, 'engine': engine})
            if len(result['tables']) > MAX_TABLES:
                raise ValueError('Business table count outside fixed budget')
        # Never silently omit executable schema objects. They need an explicit
        # adapter before this instance can advertise a complete restore point.
        for catalog, column in [('TRIGGERS', 'TRIGGER_SCHEMA'), ('ROUTINES', 'ROUTINE_SCHEMA'), ('EVENTS', 'EVENT_SCHEMA')]:
            if sql(c, f'SELECT COUNT(*) FROM information_schema.{catalog} WHERE {column}=%s', (schema,))[0][0]:
                raise ValueError('Stored programs require a reviewed backup adapter')
    if not 1 <= len(result['tables']) <= MAX_TABLES:
        raise ValueError('Business table count outside fixed budget')
    return result


def table_spec(c, schema, name):
    table = qualified(schema, name)
    ddl = sql(c, 'SHOW CREATE TABLE ' + table)[0][1]
    fields = sql(c, 'SHOW FULL COLUMNS FROM ' + table)
    if not 1 <= len(fields) <= 256 or len(ddl.encode()) > 262144:
        raise ValueError('Unsupported table dimensions')
    for row in fields:
        identifier(row[0])
    if any('GENERATED' in str(r[6]).upper() for r in fields):
        raise ValueError('Generated columns require a reviewed backup adapter')
    # No primary key is required: locked MyISAM legacy tables often lack one.
    return {'schema': schema, 'name': name, 'ddl': ddl, 'columns': [r[0] for r in fields],
            'types': [r[1] for r in fields]}


def storage_type(typ):
    if re.match(r'^bit\(', typ):
        return 'bit'
    if re.match(r'^(?:tinyint|smallint|mediumint|int|bigint|decimal|numeric|float|double|real)(?:\(|\s|$)', typ):
        return 'number'
    if re.match(r'^(?:date|datetime|timestamp|time|year)(?:\(|$)', typ):
        return 'temporal'
    return 'bytes'


def table_rows(c, spec, schema=None):
    """SSCursor + a server-side row guard, bounded to one reviewed-size row.

    Text/blob/enum/set/bit are selected as HEX and restored using UNHEX so legacy
    latin1/GBK storage bytes survive without a client character conversion.
    """
    columns = [identifier(x) for x in spec['columns']]
    safe = '(' + '+'.join('COALESCE(OCTET_LENGTH(' + x + '),0)' for x in columns) + ')<=' + str(MAX_ROW)
    kinds = [storage_type(t) for t in spec['types']]
    expressions = [('HEX(' + col + ')' if kind == 'bytes' else 'CAST(' + col + ' AS UNSIGNED)' if kind == 'bit' else
                    'CAST(' + col + ' AS CHAR CHARACTER SET ascii)' if kind == 'temporal' else col)
                   for col, kind in zip(columns, kinds)]
    statement = 'SELECT ' + safe + ',' + ','.join('CASE WHEN ' + safe + ' THEN ' + e + ' ELSE NULL END' for e in expressions)
    statement += ' FROM ' + qualified(schema or spec['schema'], spec['name'])
    # close() on a live unbuffered cursor drains unread rows. On exceptional exit
    # close the entire disposable connection instead; never drain an unbounded
    # table after a cancelled/failed backup.
    q = c.cursor(pymysql.cursors.SSCursor)
    complete = False
    try:
        q.execute(statement)
        while True:
            row = q.fetchone()
            if row is None:
                complete = True
                break
            if row[0] != 1:
                raise ValueError('Game row exceeds snapshot budget')
            yield [pack(bytes.fromhex(value)) if kind == 'bytes' and value is not None else pack(value)
                   for value, kind in zip(row[1:], kinds)]
    finally:
        if complete:
            q.close()
        else:
            abort_connection(c)


def row_digest_update(value, row):
    """Order-independent multiset hash; preserves duplicate rows without a PK."""
    n = int.from_bytes(hashlib.sha256(canonical(row)).digest(), 'big')
    return (value + n) % MODULUS


def abort_connection(c):
    # PyMySQL's public close waits for the command to finish. A watchdog must
    # interrupt an in-flight LOCK TABLES/read independently before close().
    sock = getattr(c, '_sock', None)
    if sock is not None:
        try:
            sock.shutdown(sockets.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
    try:
        c.close()
    except Exception:
        pass


@contextmanager
def deadline_connection(c, seconds):
    if type(seconds) not in (int, float) or not 0 < seconds <= 3600:
        raise ValueError('Finite 1-3600 second connection budget required')
    stop = threading.Event()
    expired = threading.Event()
    def watchdog():
        if not stop.wait(seconds):
            expired.set()
            abort_connection(c)
    thread = threading.Thread(target=watchdog, name='game-backup-lock-deadline', daemon=True)
    thread.start()
    try:
        yield expired
        if expired.is_set():
            raise TimeoutError('Game backup connection deadline exceeded')
    finally:
        stop.set()
        thread.join(timeout=3)
        if thread.is_alive():
            abort_connection(c)
            raise RuntimeError('Game backup watchdog did not stop')


def new_private(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('Absolute new private artifact required')
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)


def fsync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_new(path, value):
    with os.fdopen(new_private(path), 'wb') as f:
        f.write(canonical(value) + b'\n')
        f.flush()
        os.fsync(f.fileno())
    fsync_directory(Path(path).parent)


def file_hash(path, *, max_bytes=MAX_BYTES):
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_ENCRYPTED_BYTES:
        raise ValueError('Fixed artifact size budget required')
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Artifact symlinks are not accepted')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= max_bytes:
            raise ValueError('Regular bounded artifact required')
        if os.name != 'nt' and before.st_mode & 0o077:
            raise ValueError('Private artifact required')
        digest = hashlib.sha256(); total = 0
        while part := f.read(65536):
            total += len(part)
            if total > max_bytes:
                raise ValueError('Artifact grew beyond fixed size budget')
            digest.update(part)
        after = os.fstat(f.fileno())
        current = path.lstat()
        fields = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        # Python 3.12 on Windows exposes change-time through fstat but keeps
        # the legacy creation-time meaning in lstat.st_ctime. Compare ctime
        # across the two descriptor samples, and also against the path on
        # POSIX where the meanings agree. Inode/device still bind the path.
        if (fields(before) != fields(after) or before.st_ctime_ns != after.st_ctime_ns
                or fields(before) != fields(current)
                or (os.name != 'nt' and before.st_ctime_ns != current.st_ctime_ns)):
            raise ValueError('Artifact changed while verifying')
        return digest.hexdigest(), before.st_size


def lock_statement(tables):
    if not 1 <= len(tables) <= MAX_TABLES:
        raise ValueError('Complete bounded table list required')
    return 'LOCK TABLES ' + ','.join(qualified(t['schema'], t['name']) + ' READ' for t in tables)


def _dump_game(c, output, *, schemas, binding, guard, relations=(), budget=540, complete_scope=True):
    """Consume and close a dedicated source connection, including after failure.

    guard is the installed maintenance adapter, not a browser boolean. It verifies
    the original window, freeze and stopped writers before locks, periodically
    while streaming and before publication. READ (never READ LOCAL) excludes
    MyISAM concurrent inserts. Schema inventory and every DDL are checked again.
    """
    if not callable(guard):
        raise ValueError('Installed live maintenance guard required')
    if (not isinstance(binding, dict) or not ID.fullmatch(binding.get('window_id', ''))
            or any(not HEX.fullmatch(binding.get(k, '')) for k in ('pvf_sha256', 'program_sha256', 'source_revision_sha256'))
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', binding.get('image_digest', ''))
            or not isinstance(binding.get('server_uuid'), str)):
        raise ValueError('Immutable source/window binding required')
    output = Path(output)
    partial = output.with_name(output.name + '.partial')
    if output.exists() or output.is_symlink():
        raise FileExistsError('Restore point already exists')
    fd = new_private(partial)
    started = time.time()
    summaries = []
    total_bytes = 0
    digest = hashlib.sha256()
    locked = False
    try:
        with deadline_connection(c, budget):
            configure(c)
            sql(c, 'SET autocommit=0')
            sql(c, 'SET SESSION innodb_table_locks=1')
            c.rollback()
            guard()
            source = database_identity(c)
            if source['server_uuid'] != binding['server_uuid']:
                raise ValueError('Original maintenance database identity changed')
            catalog = inventory(c, schemas, complete_scope=complete_scope)
            # Metadata locks and every MyISAM/InnoDB table lock are acquired in
            # one statement. A socket deadline covers storage-lock waits too.
            sql(c, lock_statement(catalog['tables']))
            locked = True
            guard()
            if inventory(c, schemas, complete_scope=complete_scope) != catalog:
                raise ValueError('Schema inventory changed before locking')
            specs = []; metadata_bytes = 0
            for table in catalog['tables']:
                spec = table_spec(c, table['schema'], table['name'])
                metadata_bytes += len(canonical(spec))
                if metadata_bytes > MAX_METADATA:
                    raise ValueError('Game schema metadata exceeds fixed memory budget')
                specs.append(spec)
            coords = sql(c, 'SHOW MASTER STATUS')
            binlog = {'file': coords[0][0], 'position': coords[0][1]} if coords else None
            # Binlog coordinates document this locked business state. They do
            # not assert continuous archiving or a usable PITR chain.
            with os.fdopen(fd, 'wb') as f:
                fd = None
                checked_bytes = 0
                def emit(record):
                    nonlocal total_bytes, checked_bytes
                    line = canonical(record) + b'\n'
                    total_bytes += len(line)
                    if len(line) > MAX_LINE or total_bytes > MAX_BYTES:
                        raise ValueError('Game backup artifact budget exceeded')
                    if total_bytes - checked_bytes >= 1024 ** 2:
                        guard()
                        checked_bytes = total_bytes
                    f.write(line)
                    digest.update(line)
                emit({'type': 'header', 'format': FORMAT, 'scope': SCOPE, 'started_at': started,
                      'source': source, 'binding': binding, 'catalog': catalog, 'binlog': binlog,
                      'relations': list(relations), 'consistency': 'all_business_tables_read_locked'})
                checked = time.monotonic()
                for spec in specs:
                    emit({'type': 'table', **spec})
                    n = 0
                    multiset = 0
                    for row in table_rows(c, spec):
                        emit({'type': 'row', 'values': row})
                        multiset = row_digest_update(multiset, row)
                        n += 1
                        if time.monotonic() - checked >= 5:
                            guard()
                            checked = time.monotonic()
                    item = {'schema': spec['schema'], 'name': spec['name'], 'rows': n,
                            'values_sha256_sum': f'{multiset:064x}',
                            'ddl_sha256': hashlib.sha256(spec['ddl'].encode()).hexdigest()}
                    emit({'type': 'table_end', **item})
                    summaries.append(item)
                    guard()
                relation_results = verify_relations(c, relations)
                if inventory(c, schemas, complete_scope=complete_scope) != catalog:
                    raise ValueError('Database inventory changed during backup')
                if any(table_spec(c, s['schema'], s['name']) != s for s in specs):
                    raise ValueError('Table definition changed during backup')
                guard()
                completed = time.time()
                emit({'type': 'complete', 'tables': len(summaries), 'rows': sum(s['rows'] for s in summaries),
                      'summaries': summaries, 'relations': relation_results, 'completed_at': completed})
                f.flush()
                os.fsync(f.fileno())
            # Locks are released before any management result/audit transaction.
            sql(c, 'UNLOCK TABLES')
            locked = False
            c.close()
        os.link(partial, output)
        partial.unlink()
        fsync_directory(output.parent)
        return {'format': FORMAT, 'scope': SCOPE, 'kind': 'backup', 'state': 'complete',
                'started_at': started, 'completed_at': completed, 'artifact_sha256': digest.hexdigest(),
                'bytes': total_bytes, 'tables': len(summaries), 'rows': sum(s['rows'] for s in summaries),
                'source': source, 'binding': binding, 'binlog': binlog, 'schemas': schemas_checked(schemas),
                'summaries': summaries, 'relations': relation_results,
                'consistency': 'all_business_tables_read_locked', 'pitr_verified': False}
    finally:
        if fd is not None:
            os.close(fd)
        # Closing a failed dedicated connection is the independent last line of
        # cleanup even if UNLOCK or the filesystem failed. Never reuse it.
        abort_connection(c)


def dump_game(c, output, **options):
    """Export a complete game restore point and always dispose its connection."""
    try:
        return _dump_game(c, output, **options)
    finally:
        abort_connection(c)


def validate_relation(value):
    required = {'name', 'child_schema', 'child_table', 'child_column', 'parent_schema', 'parent_table', 'parent_column'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Typed installed relationship check required')
    for part in value.values():
        identifier(part)
    return value


def verify_relations(c, relations, mapping=None):
    mapping = mapping or {}
    results = []
    for value in relations:
        v = validate_relation(value)
        child = qualified(mapping.get(v['child_schema'], v['child_schema']), v['child_table'])
        parent = qualified(mapping.get(v['parent_schema'], v['parent_schema']), v['parent_table'])
        cc, pc = identifier(v['child_column']), identifier(v['parent_column'])
        # LOCK TABLES prohibits undeclared aliases. Use qualified table names;
        # no user-supplied SQL or arbitrary predicates are accepted.
        query = 'SELECT COUNT(*) FROM ' + child + ' LEFT JOIN ' + parent + ' ON ' + child + '.' + cc + '=' + parent + '.' + pc
        query += ' WHERE ' + child + '.' + cc + ' IS NOT NULL AND ' + parent + '.' + pc + ' IS NULL'
        results.append({'name': v['name'], 'orphan_rows': int(sql(c, query)[0][0])})
    return results


def records(stream):
    while True:
        raw = stream.readline(MAX_LINE + 1)
        if not raw:
            return
        if len(raw) > MAX_LINE or not raw.endswith(b'\n'):
            raise ValueError('Truncated or oversized game backup record')
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError('Malformed game backup record')
        yield record


def validate_spec(spec):
    if set(spec) != {'schema', 'name', 'ddl', 'columns', 'types'}:
        raise ValueError('Malformed game table specification')
    identifier(spec['schema']); identifier(spec['name'])
    if (not isinstance(spec['columns'], list) or not 1 <= len(spec['columns']) <= 256
            or len(set(spec['columns'])) != len(spec['columns'])
            or not isinstance(spec['types'], list) or len(spec['types']) != len(spec['columns'])
            or any(not isinstance(t, str) or len(t) > 4096 for t in spec['types'])
            or not isinstance(spec['ddl'], str) or len(spec['ddl'].encode()) > 262144
            or not spec['ddl'].startswith('CREATE TABLE ' + identifier(spec['name']) + ' (')):
        raise ValueError('Unsupported game table specification')
    for column in spec['columns']:
        identifier(column)
    return spec


def remap_ddl_schemas(ddl, mapping):
    """Rewrite qualified schema tokens without changing defaults/comments.

    SHOW CREATE TABLE may contain text values such as '`game`.' in a DEFAULT
    or COMMENT. A global replace would silently change those stored semantics
    while an inverse replace could hide the change during DDL verification.
    """
    for original, destination in mapping.items():
        identifier(original); identifier(destination)
    tokens = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"|`(?:[^`]|``)*`|/\*.*?\*/|--[ \t][^\n]*|#[^\n]*", re.DOTALL)
    def replace(match):
        token = match.group()
        name = token[1:-1]
        if token.startswith('`') and name in mapping and re.match(r'\s*\.', ddl[match.end():]):
            return identifier(mapping[name])
        return token
    return tokens.sub(replace, ddl)


def restore_game_drill(artifact, expected_sha256, *, socket, datadir, budget=900, connect=pymysql.connect):
    """Restore into random schemas on the socket-only lab, then remove them.

    Source DDL runs as a throwaway user restricted to those random schemas; root
    only creates/grants/drops them. No network target or production restore mode.
    Exact MySQL version, table DDL, row counts, full stored values and installed
    cross-table orphan counts must all match the source evidence.
    """
    if not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256):
        raise ValueError('Explicit game artifact checksum required')
    before_hash, size = file_hash(artifact)
    if before_hash != expected_sha256:
        raise ValueError('Game artifact checksum mismatch')
    started = time.time()
    deadline = time.monotonic() + budget
    root = connect(unix_socket=str(socket), user='root', charset='utf8mb4', autocommit=True,
                   connect_timeout=3, read_timeout=10, write_timeout=10, local_infile=False)
    created = []
    user = 'gbr_' + secrets.token_hex(8)
    made_user = False
    client = None
    mapping = {}
    receipt = None
    try:
        assert_lab(root, socket, datadir)
        version = sql(root, 'SELECT VERSION()')[0][0]
        with open(artifact, 'rb') as f:
            it = iter(records(f))
            header = next(it, {})
            if (header.get('type') != 'header' or header.get('format') != FORMAT or header.get('scope') != SCOPE
                    or header.get('source', {}).get('mysql') != version
                    or header.get('consistency') != 'all_business_tables_read_locked'):
                raise ValueError('Wrong format, scope or exact MySQL version')
            catalog = header['catalog']
            names = schemas_checked([s['name'] for s in catalog['schemas']])
            if not 1 <= len(catalog['tables']) <= MAX_TABLES:
                raise ValueError('Invalid game table inventory')
            expected_tables = {(t['schema'], t['name']) for t in catalog['tables']}
            if len(expected_tables) != len(catalog['tables']):
                raise ValueError('Duplicate table inventory')
            password = secrets.token_hex(32)
            with root.cursor() as q:
                q.execute('CREATE USER %s@\'localhost\' IDENTIFIED BY %s', (user, password)); made_user = True
                prefix = 'gb_restore_' + uuid.uuid4().hex[:16]
                for n, schema in enumerate(catalog['schemas']):
                    original = schema['name']; identifier(original)
                    charset, collation = schema['charset'], schema['collation']
                    if not re.fullmatch(r'[a-z0-9_]+', charset + collation):
                        raise ValueError('Invalid restore character set')
                    target = prefix + '_' + str(n)
                    q.execute('CREATE DATABASE ' + identifier(target) + ' CHARACTER SET ' + charset + ' COLLATE ' + collation)
                    created.append(target); mapping[original] = target
                    q.execute('GRANT SELECT,INSERT,CREATE,REFERENCES ON ' + identifier(target) + '.* TO %s@\'localhost\'', (user,))
            client = connect(unix_socket=str(socket), user=user, password=password, charset='utf8mb4', autocommit=False,
                             connect_timeout=3, read_timeout=10, write_timeout=10, local_infile=False)
            configure(client)
            sql(client, 'SET SESSION FOREIGN_KEY_CHECKS=0')
            summaries = []
            seen = set()
            spec = None
            finished = None
            for record in it:
                if time.monotonic() > deadline:
                    raise TimeoutError('Game restore drill budget exceeded')
                kind = record.get('type')
                if kind == 'table' and spec is None:
                    spec = validate_spec({k: v for k, v in record.items() if k != 'type'})
                    key = (spec['schema'], spec['name'])
                    if key not in expected_tables or key in seen:
                        raise ValueError('Unexpected or duplicate game table')
                    seen.add(key)
                    target = mapping[spec['schema']]
                    sql(client, 'USE ' + identifier(target))
                    # Rewrite only backtick-quoted schema qualifiers from SHOW
                    # CREATE TABLE. Root never executes artifact-supplied DDL.
                    ddl = remap_ddl_schemas(spec['ddl'], mapping)
                    sql(client, ddl)
                    got = table_spec(client, target, spec['name'])
                    normalized = remap_ddl_schemas(got['ddl'], {v: k for k, v in mapping.items()})
                    if {**got, 'schema': spec['schema'], 'ddl': normalized} != spec:
                        raise ValueError('Restored game DDL mismatch')
                    kinds = [storage_type(t) for t in spec['types']]
                    insert = 'INSERT INTO ' + qualified(target, spec['name']) + ' (' + ','.join(identifier(x) for x in spec['columns']) + ') VALUES ('
                    insert += ','.join('UNHEX(%s)' if k == 'bytes' else '%s' for k in kinds) + ')'
                    count = 0; multiset = 0
                elif kind == 'row' and spec is not None:
                    row = record.get('values')
                    if not isinstance(row, list) or len(row) != len(spec['columns']):
                        raise ValueError('Malformed game row')
                    values = [unpack(v) for v in row]
                    if [pack(v) for v in values] != row:
                        raise ValueError('Noncanonical game values')
                    values = [v.hex() if k == 'bytes' and isinstance(v, bytes) else v for v, k in zip(values, kinds)]
                    sql(client, insert, values)
                    count += 1; multiset = row_digest_update(multiset, row)
                    if count % 128 == 0:
                        client.commit()
                elif kind == 'table_end' and spec is not None:
                    summary = {'schema': spec['schema'], 'name': spec['name'], 'rows': count,
                               'values_sha256_sum': f'{multiset:064x}',
                               'ddl_sha256': hashlib.sha256(spec['ddl'].encode()).hexdigest()}
                    if {k: v for k, v in record.items() if k != 'type'} != summary:
                        raise ValueError('Game table payload checksum mismatch')
                    client.commit()
                    restored_sum = 0; restored_count = 0
                    for row in table_rows(client, spec, mapping[spec['schema']]):
                        if time.monotonic() > deadline:
                            raise TimeoutError('Game verification budget exceeded')
                        restored_sum = row_digest_update(restored_sum, row); restored_count += 1
                    if (restored_count, restored_sum) != (count, multiset):
                        raise ValueError('Restored game values/count mismatch')
                    summaries.append(summary); spec = None
                elif kind == 'complete' and spec is None:
                    if (seen != expected_tables or record.get('tables') != len(summaries)
                            or record.get('rows') != sum(s['rows'] for s in summaries)
                            or record.get('summaries') != summaries or next(it, None) is not None):
                        raise ValueError('Incomplete game snapshot inventory')
                    relations = verify_relations(client, header.get('relations', []), mapping)
                    if relations != record.get('relations'):
                        raise ValueError('Restored game relationships differ')
                    finished = record
                    break
                else:
                    raise ValueError('Unexpected game backup record')
            if finished is None or file_hash(artifact) != (expected_sha256, size):
                raise ValueError('Game artifact incomplete or changed')
            receipt = {'format': FORMAT, 'scope': SCOPE, 'kind': 'restore', 'state': 'verified',
                       'artifact_sha256': expected_sha256, 'bytes': size, 'started_at': started,
                       'completed_at': time.time(), 'tables': len(summaries), 'rows': sum(s['rows'] for s in summaries),
                       'target': 'isolated_exact_mysql57', 'mysql': version,
                       'checks': ['exact_mysql_version', 'table_definitions', 'all_stored_values', 'row_counts', 'business_relationships', 'artifact_sha256'],
                       'relations': relations, 'production_restored': False}
    finally:
        if client is not None:
            abort_connection(client)
        try:
            assert_lab(root, socket, datadir)
            with root.cursor() as q:
                for schema in reversed(created):
                    q.execute('DROP DATABASE ' + identifier(schema))
                if made_user:
                    q.execute('DROP USER %s@\'localhost\'', (user,))
        finally:
            root.close()
    return receipt
