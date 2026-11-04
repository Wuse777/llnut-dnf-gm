"""Private, streaming management-only snapshots and isolated restore drills.

Never restore to a live schema. Data/DDL are private, not web artifacts. Successful
backup and successful restore are separate evidence with the same artifact hash.
"""
import base64
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
import uuid
import pymysql

from .backup_format import FORMAT, MAX_ARTIFACT
MAX_LINE = 2 * 1024 * 1024
MAX_CELL_ROW = 512 * 1024
SCHEMA = 'dnf_gm'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value):
        raise ValueError('Unsupported database identifier')
    return '`' + value + '`'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def pack(value):
    if value is None or type(value) in (str, int):
        return value
    if isinstance(value, bytes): return {'bytes': base64.b64encode(value).decode('ascii')}
    if isinstance(value, datetime): return {'datetime': value.isoformat(' ')}
    if isinstance(value, date): return {'date': value.isoformat()}
    if isinstance(value, timedelta): return {'timedelta_us': (value.days * 86400 + value.seconds) * 1000000 + value.microseconds}
    if isinstance(value, Decimal) and value.is_finite(): return {'decimal': str(value)}
    if type(value) is float and math.isfinite(value): return {'float': value.hex()}
    raise ValueError('Unsupported snapshot value')


def unpack(value):
    if value is None or type(value) in (str, int): return value
    if not isinstance(value, dict) or len(value) != 1: raise ValueError('Malformed snapshot value')
    key, raw = next(iter(value.items()))
    if key == 'bytes': return base64.b64decode(raw, validate=True)
    if key == 'datetime': return datetime.fromisoformat(raw)
    if key == 'date': return date.fromisoformat(raw)
    if key == 'timedelta_us' and type(raw) is int: return timedelta(microseconds=raw)
    if key == 'decimal' and isinstance(raw, str) and Decimal(raw).is_finite(): return Decimal(raw)
    if key == 'float' and isinstance(raw, str) and math.isfinite(float.fromhex(raw)): return float.fromhex(raw)
    raise ValueError('Malformed snapshot value')


def configure(c):
    with c.cursor(pymysql.cursors.Cursor) as q:
        q.execute("SET SESSION time_zone='+00:00'")
        q.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES,NO_AUTO_VALUE_ON_ZERO,NO_ENGINE_SUBSTITUTION'")
        q.execute('SET SESSION innodb_lock_wait_timeout=2')
        q.execute('SET SESSION lock_wait_timeout=2')
        q.execute('SET SESSION max_execution_time=10000')


def tables(c, schema=SCHEMA):
    identifier(schema)
    with c.cursor(pymysql.cursors.Cursor) as q:
        q.execute('SELECT TABLE_NAME,ENGINE,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME', (schema,))
        rows=q.fetchmany(65)
        if not rows or len(rows)>64 or any(engine!='InnoDB' or typ!='BASE TABLE' for _,engine,typ in rows):
            raise ValueError('Only 1-64 InnoDB management tables supported')
        for name,_,_ in rows: identifier(name)
        q.execute('SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s',(schema,))
        if q.fetchone()[0]: raise ValueError('Triggers require a separately reviewed backup strategy')
        for catalog,field in [('ROUTINES','ROUTINE_SCHEMA'),('EVENTS','EVENT_SCHEMA')]:
            q.execute(f'SELECT COUNT(*) FROM information_schema.{catalog} WHERE {field}=%s',(schema,))
            if q.fetchone()[0]:raise ValueError('Stored programs require a separate backup strategy')
        return [row[0] for row in rows]


def table_spec(c, name, schema=SCHEMA):
    qualified=identifier(schema)+'.'+identifier(name)
    with c.cursor(pymysql.cursors.Cursor) as q:
        q.execute('SHOW CREATE TABLE '+qualified);ddl=q.fetchone()[1]
        if len(ddl.encode())>65536:raise ValueError('Oversized table definition')
        q.execute('SHOW FULL COLUMNS FROM '+qualified);columns=q.fetchall()
        if not columns or len(columns)>64 or any('GENERATED' in str(row[6]).upper() for row in columns):
            raise ValueError('Unsupported columns')
        names=[row[0] for row in columns]
        for field in names:identifier(field)
        q.execute('SHOW INDEX FROM '+qualified+" WHERE Key_name='PRIMARY'");keys=q.fetchall()
        primary=[row[4] for row in sorted(keys,key=lambda r:r[3])]
        if not primary:raise ValueError('Deterministic primary key required')
    return {'name':name,'ddl':ddl,'columns':names,'types':[row[1] for row in columns],'primary':primary}


def rows(c, spec, schema=SCHEMA):
    cols=[identifier(x) for x in spec['columns']]
    size=' + '.join('COALESCE(OCTET_LENGTH('+col+'),0)' for col in cols)
    safe='('+size+')<='+str(MAX_CELL_ROW)
    binary=[bool(re.match(r'^(?:tinyblob|mediumblob|longblob|blob|binary|varbinary|bit)(?:\(|$)',kind)) for kind in spec['types']]
    expressions=[('HEX('+col+')' if raw else 'CAST('+col+' AS CHAR CHARACTER SET ascii)' if re.match(r'^time(?:\(|$)',kind) else col) for col,raw,kind in zip(cols,binary,spec['types'])]
    select='SELECT '+safe+','+','.join('CASE WHEN '+safe+' THEN '+expr+' ELSE NULL END' for expr in expressions)
    select+=' FROM '+identifier(schema)+'.'+identifier(spec['name'])
    order=','.join(identifier(x) for x in spec['primary'])
    indexes=[spec['columns'].index(x) for x in spec['primary']]
    last=None
    # Eight bounded rows per keyset page in the SAME consistent snapshot.
    # Avoid unbuffered-cursor cancellation drains and driver private APIs.
    while True:
        params=[];placeholders=[]
        if last is not None:
            for i in indexes:
                value=last[i]
                if spec['types'][i].startswith('bit('):value=int.from_bytes(value,'big')
                if isinstance(value,bytes):placeholders.append('UNHEX(%s)');params.append(value.hex())
                else:placeholders.append('%s');params.append(value)
        where='' if last is None else ' WHERE ('+order+') > ('+','.join(placeholders)+')'
        with c.cursor(pymysql.cursors.Cursor) as q:
            q.execute(select+where+' ORDER BY '+order+' LIMIT 8',params);page=q.fetchall()
        if not page:return
        for row in page:
            if row[0]!=1:raise ValueError('Row exceeds supported backup size; snapshot incomplete')
            last=[bytes.fromhex(value) if raw and value is not None else value for value,raw in zip(row[1:],binary)]
            yield [pack(value) for value in last]
        if len(page)<8:return


def identity(st):
    return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)


@contextmanager
def private_artifact(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or not 0<st.st_size<=MAX_ARTIFACT:
            raise ValueError('Private regular artifact (0600) required')
        yield f,identity(st)
        if identity(os.fstat(f.fileno()))!=identity(st) or identity(os.stat(path,follow_symlinks=False))!=identity(st):raise ValueError('Artifact changed during verification')


def file_sha(f):
    h=hashlib.sha256();f.seek(0);total=0
    while chunk:=f.read(65536):
        total+=len(chunk)
        if total>MAX_ARTIFACT:raise ValueError('Artifact grew beyond supported size')
        h.update(chunk)
    f.seek(0);return h.hexdigest()


def dump(c, output, *, budget=900, checkpoint=lambda _:None):
    """Caller supplies a maintenance connection, never a game/schema writer."""
    output=Path(output)
    if not output.is_absolute():raise ValueError('Absolute private output required')
    partial=output.with_name(output.name+'.partial')
    if output.exists() or output.is_symlink():raise FileExistsError('Output already exists')
    fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    started=time.time();deadline=time.monotonic()+budget;digest=hashlib.sha256();size=0;counts={}
    try:
        configure(c);c.rollback()
        with c.cursor(pymysql.cursors.Cursor) as q:
            q.execute('SELECT VERSION()');version=q.fetchone()[0]
            if not version.startswith('5.7.'):raise ValueError('Requires reviewed MySQL 5.7')
            q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            q.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        names=tables(c);specs={name:table_spec(c,name) for name in names}
        if 'schema_versions' not in names or 'audit' not in names:raise ValueError('Not a GM management schema')
        with os.fdopen(fd,'wb') as f:
            fd=None
            def emit(record):
                nonlocal size
                if time.monotonic()>deadline:raise TimeoutError('Snapshot budget exceeded')
                line=canonical(record)+b'\n';size+=len(line)
                if len(line)>MAX_LINE or size>MAX_ARTIFACT:raise ValueError('Snapshot size limit exceeded')
                f.write(line);digest.update(line)
            emit({'type':'header','format':FORMAT,'scope':'management_only','started_at':started,'mysql':version})
            for name in names:
                spec=specs[name];emit({'type':'table',**spec});h=hashlib.sha256();count=0
                for row in rows(c,spec):
                    h.update(canonical(row)+b'\n');emit({'type':'row','values':row});count+=1
                counts[name]={'rows':count,'sha256':h.hexdigest()}
                emit({'type':'table_end',**counts[name]});checkpoint(name)
            if tables(c)!=names or any(table_spec(c,name)!=specs[name] for name in names):
                raise ValueError('Schema changed during snapshot')
            completed=time.time();emit({'type':'complete','tables':len(counts),'rows':sum(v['rows'] for v in counts.values()),'completed_at':completed})
            f.flush();os.fsync(f.fileno())
        c.rollback()
        # Atomic publication with no-overwrite even after a race on output name.
        os.link(partial,output);partial.unlink()
        directory=os.open(output.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return {'format':FORMAT,'kind':'backup','state':'complete','scope':'management_only','started_at':started,
                'completed_at':completed,'artifact_sha256':digest.hexdigest(),'bytes':size,'tables':len(counts),
                'rows':sum(v['rows'] for v in counts.values()),'mysql':version}
    finally:
        if fd is not None:os.close(fd)
        if c.open:c.rollback()


def records(f):
    while True:
        line=f.readline(MAX_LINE+1)
        if not line:break
        if len(line)>MAX_LINE or not line.endswith(b'\n'):raise ValueError('Truncated/oversized backup line')
        value=json.loads(line)
        if not isinstance(value,dict):raise ValueError('Malformed backup record')
        yield value


def assert_lab(c, socket, datadir):
    # Must be a Unix socket, not a forwarded TCP connection. A server-id alone
    # is insufficient: verify version, skip-networking and exact local datadir.
    if not Path(socket).is_socket() or not Path(datadir).is_absolute():raise ValueError('Local lab paths required')
    with c.cursor(pymysql.cursors.Cursor) as q:
        q.execute('SELECT VERSION(),@@server_id,@@skip_networking,@@datadir');v=q.fetchone()
    if not v[0].startswith('5.7.') or v[1]!=57044 or v[2]!=1 or Path(v[3]).resolve()!=Path(datadir).resolve():
        raise ValueError('Not the isolated restore lab')


def restore_drill(artifact, expected_sha256, *, socket, datadir, budget=900):
    if not re.fullmatch(r'[a-f0-9]{64}',expected_sha256):raise ValueError('Explicit artifact SHA-256 required')
    root=pymysql.connect(unix_socket=str(socket),user='root',charset='utf8mb4',autocommit=True,connect_timeout=3,read_timeout=10,write_timeout=10,local_infile=False)
    schema='gm_restore_'+uuid.uuid4().hex;user='gmr_'+secrets.token_hex(8);password=secrets.token_hex(32)
    created_schema=created_user=False;client=None;started=time.time();deadline=time.monotonic()+budget
    receipt=None
    try:
        assert_lab(root,socket,datadir)
        with private_artifact(artifact) as (f,sig):
            if file_sha(f)!=expected_sha256:raise ValueError('Artifact checksum mismatch')
            it=iter(records(f));header=next(it)
            if header.get('format')!=FORMAT or header.get('type')!='header' or header.get('scope')!='management_only':raise ValueError('Wrong snapshot format/scope')
            with root.cursor() as q:
                q.execute('CREATE DATABASE '+identifier(schema)+' CHARACTER SET utf8mb4 COLLATE utf8mb4_bin');created_schema=True
                q.execute('CREATE USER %s@\'localhost\' IDENTIFIED BY %s',(user,password));created_user=True
                # No DROP/ALTER/TRIGGER/FILE/global access, nor access to dnf_gm.
                q.execute('GRANT SELECT,INSERT,CREATE ON '+identifier(schema)+'.* TO %s@\'localhost\'',(user,))
            client=pymysql.connect(unix_socket=str(socket),user=user,password=password,database=schema,charset='utf8mb4',autocommit=False,connect_timeout=3,read_timeout=10,write_timeout=10,local_infile=False)
            configure(client);summaries={};spec=None;complete=None
            for record in it:
                if time.monotonic()>deadline:raise TimeoutError('Restore budget exceeded')
                kind=record.get('type')
                if kind=='table' and spec is None:
                    spec={k:record[k] for k in ('name','ddl','columns','types','primary')}
                    name=spec['name'];identifier(name)
                    if name in summaries or len(summaries)>=64:raise ValueError('Duplicate/excess table')
                    if (not isinstance(spec['ddl'],str) or len(spec['ddl'].encode())>65536
                            or not spec['ddl'].startswith('CREATE TABLE '+identifier(name)+' (')
                            or not isinstance(spec['columns'],list) or not 1<=len(spec['columns'])<=64
                            or len(set(spec['columns']))!=len(spec['columns']) or not isinstance(spec['types'],list) or len(spec['types'])!=len(spec['columns']) or not isinstance(spec['primary'],list)
                            or not spec['primary'] or not set(spec['primary'])<=set(spec['columns'])):raise ValueError('Unsupported table record')
                    for field in spec['columns']:identifier(field)
                    with client.cursor() as q:q.execute(spec['ddl'])
                    if table_spec(client,name,schema)!=spec:raise ValueError('Restored table definition differs')
                    binary_types=[bool(re.match(r'^(?:tinyblob|mediumblob|longblob|blob|binary|varbinary)(?:\(|$)',typ)) for typ in spec['types']]
                    insert='INSERT INTO '+identifier(name)+' ('+','.join(identifier(x) for x in spec['columns'])+') VALUES ('+','.join('UNHEX(%s)' if raw else '%s' for raw in binary_types)+')'
                    h=hashlib.sha256();count=0
                elif kind=='row' and spec is not None:
                    row=record.get('values')
                    if not isinstance(row,list) or len(row)!=len(spec['columns']):raise ValueError('Invalid row length')
                    decoded=[unpack(v) for v in row]
                    if [pack(v) for v in decoded]!=row:raise ValueError('Noncanonical typed row')
                    inserted=[int.from_bytes(v,'big') if typ.startswith('bit(') and isinstance(v,bytes) else v.hex() if raw and isinstance(v,bytes) else v for v,typ,raw in zip(decoded,spec['types'],binary_types)]
                    with client.cursor() as q:q.execute(insert,inserted)
                    h.update(canonical(row)+b'\n');count+=1
                elif kind=='table_end' and spec is not None:
                    if record.get('rows')!=count or record.get('sha256')!=h.hexdigest():raise ValueError('Table payload checksum mismatch')
                    client.commit()
                    restored=hashlib.sha256();n=0
                    for row in rows(client,spec,schema):
                        if time.monotonic()>deadline:raise TimeoutError('Restore verification budget exceeded')
                        restored.update(canonical(row)+b'\n');n+=1
                    if n!=count or restored.hexdigest()!=h.hexdigest() or table_spec(client,spec['name'],schema)!=spec:
                        raise ValueError('Restored content/definition mismatch')
                    summaries[spec['name']]=count;spec=None
                elif kind=='complete' and spec is None:
                    if record.get('tables')!=len(summaries) or record.get('rows')!=sum(summaries.values()) or not {'schema_versions','audit'}<=summaries.keys():
                        raise ValueError('Incomplete snapshot inventory')
                    complete=record
                    if next(it,None) is not None:raise ValueError('Trailing snapshot records')
                    break
                else:raise ValueError('Unexpected snapshot record')
            if not complete:raise ValueError('No complete snapshot marker')
            if identity(os.fstat(f.fileno()))!=sig or file_sha(f)!=expected_sha256:raise ValueError('Artifact changed')
            receipt={'format':FORMAT,'kind':'restore','state':'verified','scope':'management_only','artifact_sha256':expected_sha256,
                     'started_at':started,'completed_at':time.time(),'tables':len(summaries),'rows':sum(summaries.values()),'bytes':sig[2],
                     'checks':['table_definitions','primary_key_ordered_values','row_counts','artifact_sha256'],'target':'isolated_mysql57'}
    finally:
        if client is not None:client.close()
        try:
            if created_schema or created_user:
                assert_lab(root,socket,datadir)
                with root.cursor() as q:
                    if created_schema:q.execute('DROP DATABASE '+identifier(schema))
                    if created_user:q.execute('DROP USER %s@\'localhost\'',(user,))
        finally:root.close()
    return receipt
