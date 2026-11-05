"""Synthetic files and protocol checker, no production config/service changes."""
import json
import os
from pathlib import Path
import stat
import sys
from contextlib import contextmanager

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import configure_write_gate as install
from maintenance_gate import WriteGateManager
from check_maintenance_idle import assert_config_gate
from dnfgm.release_files import Refused
from test_gameplay_write_gate import OP,IDENTITY


class Cursor:
    def __init__(self):self.sql=''
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql):self.sql=sql
    def fetchone(self):return {'ENGINE':'InnoDB'} if 'information_schema' in self.sql else {'id':1,'protocol_version':1}
class Connection:
    def cursor(self):return Cursor()
class Database:
    def __init__(self,settings):self.settings=settings
    @contextmanager
    def connect(self):yield Connection()


@pytest.fixture
def files(tmp_path):
    cfg=tmp_path/'config.json';root=tmp_path/'gate'
    value={'secret':'s'*64,'db_password':'synthetic','writes':[],'test_uids':[900001],'task_probe_token':'a'*64}
    cfg.write_text(json.dumps(value));cfg.chmod(0o600)
    args=dict(config=cfg,root=root,owner=os.geteuid(),app_uid=os.geteuid(),app_gid=os.getegid(),db_factory=Database)
    return args,value


def test_fixed_installation_preserves_secrets_policy_and_stable_inode(files):
    args,value=files;first=install.configure(**args)
    assert first=={'configured':True,'changed':True,'protocol_version':1,'services_changed':False}
    assert json.loads(args['config'].read_text())=={**value,'gameplay_gate_dir':str(args['root'])}
    st=args['config'].stat();assert (st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode))==(os.geteuid(),os.getegid(),0o640)
    lock=(args['root']/'fence.lock').stat().st_ino
    assert not install.configure(**args)['changed']
    assert (args['root']/'fence.lock').stat().st_ino==lock
    assert_config_gate(args['config'],owner=os.geteuid())


def test_reinstall_cannot_open_frozen_or_missing_state(files):
    args,value=files;install.configure(**args);before=args['config'].read_bytes()
    manager=WriteGateManager(args['root'],owner=os.geteuid());token=manager.freeze(OP,IDENTITY)
    with pytest.raises(Refused):install.configure(**args)
    with pytest.raises(Refused):assert_config_gate(args['config'],owner=os.geteuid())
    assert manager.read()==token and args['config'].read_bytes()==before
    (args['root']/'state.json').unlink()
    with pytest.raises((Refused,OSError)):install.configure(**args)
    with pytest.raises((Refused,OSError)):assert_config_gate(args['config'],owner=os.geteuid())


def test_different_configured_gate_is_not_silently_replaced(files,tmp_path):
    args,value=files;other=tmp_path/'other';value['gameplay_gate_dir']=str(other)
    args['config'].write_text(json.dumps(value))
    with pytest.raises(Refused,match='path_changed'):install.configure(**args)
    assert not args['root'].exists()
    with pytest.raises(OSError):assert_config_gate(args['config'],owner=os.geteuid())


def test_protocol_failure_does_not_create_state_or_rewrite_config(files,monkeypatch):
    args,value=files;before=args['config'].read_bytes()
    def fail(q):raise Refused('synthetic_missing_migration')
    monkeypatch.setattr(install,'inspect_protocol',fail)
    with pytest.raises(Refused):install.configure(**args)
    assert args['config'].read_bytes()==before and not args['root'].exists()


@pytest.mark.parametrize('kind',['symlink','hardlink','writable','invalid'])
def test_untrusted_config_refused_before_gate_creation(files,tmp_path,kind):
    args,value=files;path=args['config']
    if kind=='symlink':
        source=tmp_path/'original';path.rename(source);path.symlink_to(source)
    elif kind=='hardlink':os.link(path,tmp_path/'alias')
    elif kind=='writable':path.chmod(0o666)
    else:path.write_text('[]')
    with pytest.raises((Refused,ValueError,OSError)):install.configure(**args)
    assert not args['root'].exists()


def test_install_checks_schema_then_configures_gate_before_release_switch():
    text=(Path(__file__).parents[1]/'deploy/install.sh').read_text()
    assert text.index('check_maintenance_idle.py')<text.index('systemctl stop')<text.index('configure_write_gate.py')<text.index('ln -sfn')<text.index('systemctl start dnf-gm.service')
    helper=(Path(__file__).parents[1]/'deploy/upgrade-gameplay-fence.py').read_text()
    assert helper.index('assert_config_gate()')<helper.index('mysql(a.container')
    assert 'systemctl' not in helper and 'SELECT grant' in helper


def test_preflight_can_inspect_installed_gate_without_site_packages(tmp_path):
    import subprocess
    repo=Path(__file__).resolve().parents[1]
    code=f'''
import sys,os,json
from pathlib import Path
sys.path[:0]=[{str(repo/'src')!r},{str(repo/'deploy')!r}]
from maintenance_gate import WriteGateManager
from check_maintenance_idle import assert_config_gate,assert_idle
root=Path({str(tmp_path/'gate')!r})
WriteGateManager(root,owner=os.geteuid()).initialize()
config=Path({str(tmp_path/'config.json')!r})
config.write_text(json.dumps({{'gameplay_gate_dir':str(root)}}));config.chmod(0o600)
assert_config_gate(config,owner=os.geteuid())
assert_idle(state=Path({str(tmp_path/'absent')!r}),runtime=Path({str(tmp_path/'absent-permit')!r}),gate=root,owner=os.geteuid())
assert 'fastapi' not in sys.modules and 'pymysql' not in sys.modules
'''
    result=subprocess.run([sys.executable,'-I','-S','-c',code],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_runtime_loader_accepts_only_private_or_root_managed_application_group():
    from types import SimpleNamespace
    from dnfgm.config import trusted_config_file
    def sample(uid,gid,mode=0o640,links=1):return SimpleNamespace(st_mode=stat.S_IFREG|mode,st_uid=uid,st_gid=gid,st_nlink=links,st_size=100)
    assert trusted_config_file(sample(0,1001),1001,1001)
    assert trusted_config_file(sample(1001,1001,0o600),1001,1001)
    assert not trusted_config_file(sample(1001,1001),1001,1001)
    assert not trusted_config_file(sample(0,1002),1001,1001)
    assert not trusted_config_file(sample(0,1001,0o644),1001,1001)
    assert not trusted_config_file(sample(0,1001,links=2),1001,1001)


def test_runtime_loader_keeps_legacy_private_config_and_refuses_symlink(files,monkeypatch,tmp_path):
    from dnfgm.config import load_settings
    args,value=files;monkeypatch.setenv('DNFGM_CONFIG',str(args['config']))
    assert load_settings().db_password=='synthetic'
    alias=tmp_path/'alias';alias.symlink_to(args['config']);monkeypatch.setenv('DNFGM_CONFIG',str(alias))
    with pytest.raises(OSError):load_settings()
