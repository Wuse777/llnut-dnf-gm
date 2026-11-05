"""Fixed lifecycle with real isolated MySQL; process/s6 operations are synthetic."""
import os
import sys
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
from dnfgm.inventory_fence import boot_id
from dnfgm.inventory_reconcile import settle_window
from dnfgm.release_files import Refused
from maintenance_admission import MaintenanceAdmission
from maintenance_drain import DrainCoordinator
from maintenance_session import MaintenanceSession
from service_lifecycle import ServiceLifecycle
from test_service_lifecycle import FullHost, RID
from test_maintenance_session import make_window
from test_write_gate import gate
from test_combined_rewards import read
from test_inventory_operations import inv, prepare


def test_full_continuation_uses_original_real_database_before_releasing_gate(env,gate,tmp_path):
    h=FullHost();h.ident['boot_id']=boot_id()
    c=DrainCoordinator(tmp_path/'real-session',h,owner=os.geteuid(),
        admission=MaintenanceAdmission(gate,env[2]),lifecycle=ServiceLifecycle(h))
    c.initialize();p=c.prepare(RID,'隔离数据库维护恢复')
    assert c.confirm(RID,p['fingerprint'])['state']=='writers_stopped'
    window=make_window(c,h,tmp_path)
    health=lambda:{'core_ok':True,'services':{'dnf_gateway':True},
                   **{k:h.ident[k] for k in ('image_digest','pvf_sha256')}}
    s=MaintenanceSession(c,window,health)
    assert s.open(RID)['state']=='maintenance_open'
    assert window.status()['id']==RID
    assert s.close_restore(RID)['state']=='completed'
    assert gate.read()['state']=='open' and window.status()['safe_to_resume'] is True
    assert read(env[2],'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(env[2],'SELECT * FROM taiwan_cain_2nd.postal')
    count=len(h.calls)
    assert s.close_restore(RID)['state']=='completed' and len(h.calls)==count


def test_original_uuid_mismatch_does_not_settle_interrupted_inventory_intent(inv):
    op=prepare(inv)['operation_id'];db=inv[2]
    with db.connect() as connection,connection.cursor() as q:
        q.execute("UPDATE dnf_gm.operations SET status='executing' WHERE operation_id=%s",(op,))
        q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','item-intent',900001,'test','{}','{}')",('intent:'+op,))
        connection.commit()
    wrong='ffffffff-ffff-ffff-ffff-ffffffffffff'
    with pytest.raises(Refused,match='database_identity_changed'):
        settle_window(db,'d'*32,expected_server_uuid=wrong)
    assert read(db,'SELECT status FROM dnf_gm.operations WHERE operation_id=%s',(op,))[0]['status']=='executing'
    actual=read(db,'SELECT @@server_uuid AS server_uuid')[0]['server_uuid']
    result=settle_window(db,'d'*32,expected_server_uuid=actual)
    assert result['resolved_aborted']==[op] and result['game_writes'] is False
    assert read(db,'SELECT status FROM dnf_gm.operations WHERE operation_id=%s',(op,))[0]['status']=='aborted'
    assert settle_window(db,'d'*32,expected_server_uuid=actual)['resolved_aborted']==[]
