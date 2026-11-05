"""Web -> MySQL outbox -> full root worker -> explicit web close -> restoration.

The database and file protocols are real; 60 s6 services and monitor handshake
are synthetic. These tests do NOT claim any production or game-client effect.
"""
import copy
import json
import os
import time
from pathlib import Path

from dnfgm import maintenance_requests as mod
from dnfgm.inventory_fence import boot_id
from dnfgm.release_files import atomic_json
from maintenance_admission import MaintenanceAdmission
from maintenance_drain import DrainCoordinator
from maintenance_executor import ExecutionWorker
from maintenance_session import MaintenanceSession
from service_lifecycle import ServiceLifecycle
from test_service_lifecycle import FullHost, RID
from test_maintenance_session import make_window
from test_maintenance_executor import Handshake
from test_write_gate import gate
from test_maintenance_requests import BASE


def test_authenticated_web_closes_original_full_session_without_ssh(env,gate,tmp_path,monkeypatch):
    client,s,db,app=env;monkeypatch.setattr(mod,'ROOT_UID',os.geteuid())
    h=FullHost();h.ident['boot_id']=boot_id()
    h.cfg.update({k:h.ident[k] for k in ('image_digest','pvf_sha256','program_sha256')})
    s.image_digest=h.ident['image_digest'];s.pvf_sha256=h.ident['pvf_sha256'];s.inventory_program_sha256=h.ident['program_sha256']
    s.writes=(*s.writes,'maintenance');s.write_approvals['maintenance']=True
    status=Path(s.status_file);d=json.loads(status.read_text());d.update(image_digest=s.image_digest,pvf_sha256=s.pvf_sha256);atomic_json(status,d)
    root=tmp_path/'outbox';root.mkdir(mode=0o755);(root/'inbox').mkdir(mode=0o770);(root/'results').mkdir(mode=0o755)
    s.maintenance_dir=str(root)
    coordinator=DrainCoordinator(tmp_path/'journal',h,owner=os.geteuid(),
        admission=MaintenanceAdmission(gate,db),lifecycle=ServiceLifecycle(h))
    coordinator.initialize();window=make_window(coordinator,h,tmp_path)
    health=lambda:{'core_ok':True,'services':{'dnf_gateway':True},
                   **{k:h.ident[k] for k in ('image_digest','pvf_sha256')}}
    session=MaintenanceSession(coordinator,window,health)
    worker=ExecutionWorker(root,coordinator,os.geteuid(),session,Handshake(h),owner=os.geteuid())
    original=copy.deepcopy(h.rows);worker.tick()
    prepared=client.post(BASE+'/requests',json={'request_id':RID,'reason':'网页完整恢复集成测试'})
    assert prepared.status_code==200,prepared.text
    worker.tick()
    detail=client.get(BASE+'/requests/'+RID).json();assert detail['can_confirm']
    fingerprint=detail['result']['fingerprint']
    confirmed=client.post(BASE+'/requests/'+RID+'/confirm',json={'idempotency_key':'full-executor-confirm','fingerprint':fingerprint,'acknowledge_disconnect':True})
    assert confirmed.status_code==200,confirmed.text
    worker.tick()
    detail=client.get(BASE+'/requests/'+RID).json()
    assert detail['result']['state']=='maintenance_open' and detail['can_close'],detail
    assert gate.read()['state']=='frozen'
    # Owner can still end maintenance after disabling the new-entry switch.
    s.write_approvals['maintenance']=False
    closed=client.post(BASE+'/requests/'+RID+'/close',json={'idempotency_key':'full-executor-close','fingerprint':fingerprint,'acknowledge_restore':True})
    assert closed.status_code==200,closed.text
    assert closed.json()['close_requested'] and closed.json()['result']['state']=='maintenance_open'
    worker.tick()
    detail=client.get(BASE+'/requests/'+RID).json()
    assert detail['result']['state']=='completed' and not detail['can_close'],detail
    assert gate.read()['state']=='open' and window.status()['safe_to_resume'] is True
    for name,row in original.items():assert h.rows[name][:3]==row[:3]
    commands=copy.deepcopy(h.calls)
    assert client.post(BASE+'/requests/'+RID+'/dispatch').status_code==200
    worker.tick();assert h.calls==commands
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) n FROM dnf_gm.audit WHERE action='maintenance-close'");assert q.fetchone()['n']==1
        q.execute('SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001');assert q.fetchone()['cera']==1000
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.postal');assert q.fetchone()['n']==0
