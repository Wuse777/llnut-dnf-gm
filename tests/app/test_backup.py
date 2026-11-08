"""Actual management snapshots and restores, exclusively in the socket-only lab."""
from datetime import date,datetime,timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time
import pymysql
import pytest
from dnfgm.backup import dump,restore_drill,pack,unpack,canonical,MAX_CELL_ROW
from dnfgm.backup_health import verify_evidence,read_health
from dnfgm.alerts import atomic


def labargs(env):
    with env[2].connect() as c,c.cursor() as q:
        q.execute('SELECT @@socket socket,@@datadir datadir');d=q.fetchone()
    return {'socket':d['socket'],'datadir':d['datadir']}


def backup(env,path,**kw):
    with env[2].connect() as c:return dump(c,path,**kw)


def summaries(env):
    with env[2].connect() as c,c.cursor() as q:
        q.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA');schemas={r['SCHEMA_NAME'] for r in q.fetchall()}
        q.execute("SELECT User FROM mysql.user WHERE User LIKE 'gmr_%'");users={r['User'] for r in q.fetchall()}
        q.execute('SELECT COUNT(*) n FROM dnf_gm.admins');admins=q.fetchone()['n']
    return schemas,users,admins


def test_complete_management_backup_restore_real_content_and_cleanup(env,tmp_path):
    args=labargs(env)
    with env[2].connect() as c,c.cursor() as q:
        q.execute('CREATE TABLE dnf_gm.fixture_types (id int PRIMARY KEY AUTO_INCREMENT, raw longblob, decval decimal(30,8), timeval time(6), dateval date, moment datetime(6), bits bit(8), num bigint unsigned, realval double, emptyval varchar(10), nullable text) ENGINE=InnoDB')
        q.execute("SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO,NO_ENGINE_SUBSTITUTION'")
        q.execute('INSERT INTO dnf_gm.fixture_types VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(0,b'\x00\xffsecret\x00',Decimal('12345678901234567890.12345678'),'-00:02:03.000456',date(2020,1,2),datetime(2021,2,3,4,5,6,7),255,2**64-1,1.23456789,'',None))
        c.commit()
    before=summaries(env);artifact=tmp_path/'backup.ndjson';b=backup(env,artifact)
    assert b['state']=='complete' and b['tables']>20 and b['rows']>=3
    assert artifact.stat().st_mode&0o777==0o600 and not artifact.with_name('backup.ndjson.partial').exists()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==b['artifact_sha256']
    r=restore_drill(artifact,b['artifact_sha256'],**args)
    assert r['state']=='verified' and r['tables']==b['tables'] and r['rows']==b['rows']
    assert summaries(env)==before
    bp=tmp_path/'backup.receipt';rp=tmp_path/'restore.receipt';atomic(bp,b);atomic(rp,r)
    h=verify_evidence(artifact,bp,rp);assert h['restore']['state']=='verified'
    hp=tmp_path/'health';atomic(hp,h,0o644);view=read_health(hp,time.time())
    assert view['state']=='ok' and view['backup']['state']=='recent' and view['restore']['state']=='recent'
    assert view['coverage']['game_database']=='not_covered'
    assert 'secret' not in json.dumps(view) and str(tmp_path) not in json.dumps(view)


def test_partial_snapshot_no_overwrite_and_no_success(env,tmp_path):
    p=tmp_path/'backup'
    with pytest.raises(RuntimeError):backup(env,p,checkpoint=lambda _:(_ for _ in ()).throw(RuntimeError('fault')))
    assert not p.exists() and p.with_name('backup.partial').exists()
    with pytest.raises(FileExistsError):backup(env,p)
    other=tmp_path/'existing';other.write_text('do not replace')
    with pytest.raises(FileExistsError):backup(env,other)
    assert other.read_text()=='do not replace'


def test_snapshot_does_not_take_later_updates(env,tmp_path):
    with env[2].connect() as c,c.cursor() as q:
        q.execute("INSERT INTO dnf_gm.gift_templates(name,current_version,enabled) VALUES('snapshot-before',1,1)");c.commit()
    def change(name):
        if name=='admins':
            with env[2].connect() as c,c.cursor() as q:q.execute("UPDATE dnf_gm.gift_templates SET name='snapshot-after'");c.commit()
    p=tmp_path/'snapshot';b=backup(env,p,checkpoint=change)
    text=p.read_text();assert 'snapshot-before' in text and 'snapshot-after' not in text
    assert restore_drill(p,b['artifact_sha256'],**labargs(env))['state']=='verified'


def test_oversize_row_is_detected_without_success(env,tmp_path):
    with env[2].connect() as c,c.cursor() as q:
        q.execute('CREATE TABLE dnf_gm.fixture_big(id int PRIMARY KEY, body longblob) ENGINE=InnoDB')
        q.execute('INSERT INTO dnf_gm.fixture_big VALUES(1,%s)',(b'x'*(MAX_CELL_ROW+1),));c.commit()
    with pytest.raises(ValueError):backup(env,tmp_path/'too-big')
    assert not (tmp_path/'too-big').exists()


def test_corruption_or_wrong_lab_does_not_touch_existing_schemas(env,tmp_path):
    p=tmp_path/'snapshot';b=backup(env,p);args=labargs(env);before=summaries(env)
    with pytest.raises(ValueError):restore_drill(p,'0'*64,**args)
    with pytest.raises(ValueError):restore_drill(p,b['artifact_sha256'],socket=args['socket'],datadir=tmp_path)
    assert summaries(env)==before


def test_restore_requires_final_marker_and_rolls_back_temporary_resources(env,tmp_path):
    p=tmp_path/'snapshot';backup(env,p);lines=p.read_bytes().splitlines(keepends=True);p.write_bytes(b''.join(lines[:-1]))
    before=summaries(env)
    with pytest.raises(ValueError):restore_drill(p,hashlib.sha256(p.read_bytes()).hexdigest(),**labargs(env))
    assert summaries(env)==before


def test_restore_does_not_execute_sql_as_root(env,tmp_path):
    p=tmp_path/'snapshot';backup(env,p);lines=[json.loads(x) for x in p.read_text().splitlines()]
    table=next(x for x in lines if x['type']=='table')
    table['ddl']+='; DROP DATABASE dnf_gm'
    p.write_bytes(b''.join(canonical(x)+b'\n' for x in lines));before=summaries(env)
    with pytest.raises(pymysql.MySQLError):restore_drill(p,hashlib.sha256(p.read_bytes()).hexdigest(),**labargs(env))
    assert summaries(env)==before


def test_incomplete_or_other_artifact_restore_never_certified(env,tmp_path):
    p=tmp_path/'snapshot';b=backup(env,p);bp=tmp_path/'bp';atomic(bp,b)
    h=verify_evidence(p,bp);assert h['restore'] is None
    r=restore_drill(p,b['artifact_sha256'],**labargs(env));r['artifact_sha256']='f'*64;rp=tmp_path/'rp';atomic(rp,r)
    assert verify_evidence(p,bp,rp)['restore']['state']=='other_artifact'
    p.write_bytes(p.read_bytes()+b'changed')
    assert verify_evidence(p,bp,rp)['integrity']=='failed'


def test_finite_budget_and_nontransactional_tables_rejected(env,tmp_path):
    with pytest.raises(TimeoutError):backup(env,tmp_path/'timed',budget=-1)
    with env[2].connect() as c,c.cursor() as q:q.execute('CREATE TABLE dnf_gm.fixture_myisam(id int PRIMARY KEY) ENGINE=MyISAM');c.commit()
    with pytest.raises(ValueError):backup(env,tmp_path/'wrong-engine')


def test_binary_composite_keyset_beyond_one_page(env,tmp_path):
    with env[2].connect() as c,c.cursor() as q:
        q.execute('CREATE TABLE dnf_gm.fixture_keys(k varbinary(8),n int,body longblob,PRIMARY KEY(k,n)) ENGINE=InnoDB')
        q.executemany('INSERT INTO dnf_gm.fixture_keys VALUES(UNHEX(%s),%s,UNHEX(%s))',[(bytes([i%3,255,i]).hex(),i,b'\x00\xff'.hex()) for i in range(25)]);c.commit()
    p=tmp_path/'paged';b=backup(env,p)
    assert restore_drill(p,b['artifact_sha256'],**labargs(env))['state']=='verified'


def test_restore_user_cannot_read_source_management_schema(env,tmp_path):
    p=tmp_path/'snapshot';backup(env,p);lines=[json.loads(x) for x in p.read_text().splitlines()]
    table=next(x for x in lines if x['type']=='table')
    table['ddl']='CREATE TABLE `admins` (`id` int) ENGINE=InnoDB AS SELECT id FROM dnf_gm.admins'
    p.write_bytes(b''.join(canonical(x)+b'\n' for x in lines));before=summaries(env)
    with pytest.raises(pymysql.MySQLError) as e:restore_drill(p,hashlib.sha256(p.read_bytes()).hexdigest(),**labargs(env))
    assert e.value.args[0] in (1142,1143)
    assert summaries(env)==before


def test_api_only_reads_sanitized_evidence(env,tmp_path):
    from fastapi.testclient import TestClient
    c,s,_,app=env;s.backup_health_file=str(tmp_path/'not-created-private.json')
    path='/dnf-gm/api/v1/backup-health';r=c.get(path)
    assert r.status_code==200 and r.json()['state']=='unavailable' and 'private.json' not in r.text
    assert c.post(path,json={'sql':'DROP DATABASE dnf_gm'}).status_code==405
    with TestClient(app) as anon:assert anon.get(path).status_code==401
    assert 429 in [c.get(path).status_code for _ in range(31)]


def test_cli_actual_backup_restore_publish_and_refuse_overwrite(env,tmp_path):
    import subprocess,sys
    args=labargs(env);script=Path(__file__).resolve().parents[2]/'tools/management_backup.py'
    def run(*a):return subprocess.run([sys.executable,str(script),*map(str,a)],capture_output=True,text=True,timeout=60)
    artifact=tmp_path/'cli.ndjson';bp=tmp_path/'backup.receipt';rp=tmp_path/'restore.receipt';hp=tmp_path/'health.json'
    r=run('backup','--output',artifact,'--receipt',bp,'--lab-socket',args['socket'],'--lab-datadir',args['datadir'])
    assert r.returncode==0,r.stderr
    b=json.loads(bp.read_text());assert 'password' not in r.stdout
    r=run('restore-check','--artifact',artifact,'--sha256',b['artifact_sha256'],'--lab-socket',args['socket'],'--lab-datadir',args['datadir'],'--receipt',rp)
    assert r.returncode==0,r.stderr
    r=run('publish-health','--artifact',artifact,'--backup-receipt',bp,'--restore-receipt',rp,'--output',hp)
    assert r.returncode==0 and read_health(hp,time.time())['restore']['state']=='recent'
    r=run('publish-health','--artifact',artifact,'--backup-receipt',bp,'--output',artifact)
    assert r.returncode!=0 and hashlib.sha256(artifact.read_bytes()).hexdigest()==b['artifact_sha256']
    r=run('backup','--output',artifact,'--receipt',bp,'--lab-socket',args['socket'],'--lab-datadir',args['datadir'])
    assert r.returncode!=0


def test_cli_latest_rehearsal_restores_actual_snapshot_and_cleans_lab(env,tmp_path):
    import subprocess,sys
    args=labargs(env);root=tmp_path/'automatic';root.mkdir(mode=0o700)
    folder=root/('management-'+'a'*32);folder.mkdir(mode=0o700)
    receipt=backup(env,folder/'management.ndjson');atomic(folder/'backup-receipt.json',receipt)
    before=summaries(env);private=tmp_path/'restore.json';public=tmp_path/'health.json'
    script=Path(__file__).resolve().parents[2]/'tools/management_backup.py'
    result=subprocess.run([sys.executable,str(script),'rehearse-latest','--backup-root',str(root),
        '--lab-socket',args['socket'],'--lab-datadir',args['datadir'],'--receipt',str(private),'--health-output',str(public)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['restore']=='verified' and read_health(public,time.time())['restore']['state']=='recent'
    assert summaries(env)==before and 'password' not in result.stdout and str(root) not in result.stdout
