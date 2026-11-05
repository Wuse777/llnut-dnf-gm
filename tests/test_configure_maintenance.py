"""Small installation smoke test; temporary files only, no service commands."""
import json
import os
import stat
from dataclasses import asdict

from configure_maintenance import configure
from dnfgm.config import Settings
from dnfgm.release_files import atomic_json
from test_inventory_probe import scene


def test_installation_preserves_switches_and_caps_connections(scene,tmp_path):
    policy,*_=scene
    app=tmp_path/'app.json';monitor=tmp_path/'monitor.json';policy_path=tmp_path/'policy.json'
    outbox=tmp_path/'outbox';state=tmp_path/'drain'
    value=asdict(Settings(secret='synthetic-secret-'*3,db_password='synthetic-test-only',
        maintenance_dir=str(outbox),image_digest=policy['image_digest'],
        pvf_sha256=policy['pvf_sha256'],inventory_program_sha256=policy['program_sha256'],
        writes=('currency','mail'),write_approvals={'currency':True,'mail':True}))
    atomic_json(app,value,mode=0o600)
    cfg={'container':policy['container'],'pvf_path':policy['pvf_path'],'disk_path':str(tmp_path),
         'gateway_url':'http://127.0.0.1:5505/health','core_services':['docker.service'],
         'components':policy['components'],'min_memory_mib':256,'min_swap_free_mib':1536}
    atomic_json(monitor,cfg,mode=0o600)
    args=dict(app=app,monitor=monitor,policy=policy_path,root=outbox,state=state,
              owner=os.geteuid(),app_gid=os.getegid())
    assert configure(**args)['configured'] is False
    atomic_json(policy_path,policy,mode=0o600)
    assert configure(**args)['connection_budget']==3
    saved=(app.read_bytes(),monitor.read_bytes())
    assert configure(**args)['configured'] is True
    assert saved==(app.read_bytes(),monitor.read_bytes())
    final=json.loads(app.read_text())
    assert final['writes']==['currency','mail'] and final['db_connection_limit']==2
    assert stat.S_IMODE((outbox/'inbox').stat().st_mode)==0o770
