import copy
from datetime import datetime,date,timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import pytest
from dnfgm import backup as b
from dnfgm import backup_health as h
from dnfgm.alerts import atomic,observations
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import management_backup as cli


def report(t=100):
    return {'version':1,'checked_at':t,'scope':'management_only','integrity':'verified',
            'backup':{'completed_at':t-5,'artifact_sha256':'a'*64,'bytes':1000,'tables':20,'rows':500},
            'restore':{'state':'verified','completed_at':t-1,'artifact_sha256':'a'*64}}


def test_ages_unknown_scope_and_matching_digest(tmp_path):
    p=tmp_path/'health';d=report();atomic(p,d)
    v=h.read_health(p,100);assert v['backup']['state']=='recent' and v['restore']['state']=='recent'
    assert v['coverage']['game_database']=='not_covered'
    assert h.read_health(p,90000)['state']=='stale'
    assert h.read_health(p,99)['state']=='unavailable'
    d['checked_at']=90000;atomic(p,d);assert h.read_health(p,90000)['backup']['state']=='overdue'
    d['restore']['artifact_sha256']='b'*64;atomic(p,d);assert h.read_health(p,90000)['state']=='unavailable'


@pytest.mark.parametrize('change',[lambda d:d.update(integrity='failed'),lambda d:d.update(backup=None),lambda d:d['backup'].update(bytes=-1),lambda d:d['backup'].update(completed_at=float('inf')),lambda d:d['restore'].update(completed_at=200)])
def test_invalid_evidence_never_green(tmp_path,change):
    p=tmp_path/'health';d=report();change(d);p.write_text(json.dumps(d));assert h.read_health(p,100)['state']!='ok'


def test_projection_no_arbitrary_metadata_or_paths(tmp_path):
    p=tmp_path/'health';d=report();d['secret']='password';d['backup']['path']='/root/private';atomic(p,d)
    text=json.dumps(h.read_health(p,100));assert 'password' not in text and '/root/' not in text
    d['restore']={'state':'other_artifact','completed_at':80,'artifact_sha256':'b'*64};atomic(p,d)
    assert h.read_health(p,100)['restore']['state']=='other_artifact'


@pytest.mark.parametrize('value',[None,0,2**64-1,'测试\x00',b'\x00\xff',Decimal('123.4000'),datetime(2020,1,1,1,2,3,4),date(2020,1,1),timedelta(seconds=-5,microseconds=7),1.2345])
def test_type_roundtrip(value):assert b.unpack(b.pack(value))==value


@pytest.mark.parametrize('value',[float('nan'),float('inf'),Decimal('NaN'),True,{},set()])
def test_unsupported_values_fail(value):
    with pytest.raises(ValueError):b.pack(value)


def test_bad_identifiers_and_nonprivate_files(tmp_path):
    for name in ('dnf_gm;DROP','A','../x','`x`','a'*65):
        with pytest.raises(ValueError):b.identifier(name)
    p=tmp_path/'artifact';p.write_text('private');p.chmod(0o644)
    with pytest.raises(ValueError):
        with b.private_artifact(p):pass


def test_production_tool_only_checks_not_stops_services(monkeypatch,tmp_path):
    calls=[]
    class Result:stdout='LoadState=loaded\nActiveState=active\nMainPID=123\n'
    monkeypatch.setattr(cli.subprocess,'run',lambda args,**kw:calls.append(args) or Result())
    with pytest.raises(ValueError):cli.stopped_gm()
    assert calls==[['systemctl','show','dnf-gm.service','--property=LoadState,ActiveState,MainPID']]


def test_optional_backup_alerts_are_unknown_when_off_and_fail_when_stale():
    limits={'memory':256,'swap':1536,'disk':2}
    d=observations(None,True,100,limits);assert d['backup']['bad'] is None
    d=observations(None,True,100,limits,{'state':'stale'});assert d['backup']['bad'] is True and d['restore']['bad'] is None
    d=observations(None,True,100,limits,{'state':'ok','backup':{'state':'recent'},'restore':{'state':'other_artifact'}})
    assert d['backup']['bad'] is False and d['restore']['bad'] is True


def test_artifact_replacement_during_read_rejected(tmp_path):
    p=tmp_path/'a';p.write_bytes(b'first');p.chmod(0o600)
    with pytest.raises(ValueError):
        with b.private_artifact(p) as (f,_):
            other=tmp_path/'other';other.write_bytes(b'second');other.chmod(0o600);other.replace(p)
            assert f.read()==b'first'


def test_health_projection_does_not_import_database_runtime():
    import subprocess
    source=str(Path(__file__).resolve().parents[1]/'src')
    code=f'import sys; sys.path.insert(0,{source!r}); from dnfgm.backup_health import read_health; assert "pymysql" not in sys.modules'
    r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr


def test_receipt_without_exact_restore_checks_rejected():
    r={'format':b.FORMAT,'kind':'restore','state':'verified','scope':'management_only','started_at':1,'completed_at':2,'tables':1,'rows':1,'bytes':1,'target':'isolated_mysql57','checks':['file_exists']}
    with pytest.raises(ValueError):h.validate_receipt(r,'restore')


def test_growing_hash_input_cannot_bypass_size_limit(monkeypatch):
    import io
    monkeypatch.setattr(b,'MAX_ARTIFACT',10)
    with pytest.raises(ValueError):b.file_sha(io.BytesIO(b'x'*11))


def test_disabled_optional_rule_retains_history_but_sends_no_pending_event():
    from dnfgm.alerts import new_state,observe,pending
    thresholds={'memory':256,'swap':1536,'disk':2};s=new_state()
    for t in (100,130):observe(s,observations(None,True,t,thresholds,{'state':'stale'}),t)
    assert any(e['key']=='backup' for e in pending(s))
    observe(s,observations(None,True,160,thresholds),160)
    assert s['rules']['backup']['active'] and s['rules']['backup']['observed']=='disabled'
    assert not any(e['key']=='backup' for e in pending(s))
