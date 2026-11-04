"""Management-only settlement after the root tool owns the EXCLUSIVE fence.

Never call while an application transaction could still acquire/shared-hold that
fence. The caller revokes the permit first. FOR UPDATE waits for any DB-side
commit still running after a disconnected/crashed app; timeout means NOT safe.
"""
import re
from .service import dump
from .inventory_fence import Refused


def settle_window(db,window_id):
    if not isinstance(window_id,str) or not re.fullmatch(r'[a-f0-9]{32}',window_id):
        raise Refused('maintenance_window_invalid')
    with db.connect() as c,c.cursor() as q:
        q.execute("SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('operations','audit','inventory_operations','inventory_snapshots')")
        rows=q.fetchall()
        if len(rows)!=4 or any(r['ENGINE']!='InnoDB' for r in rows):raise Refused('maintenance_database_schema_unproven')
        q.execute("SELECT o.operation_id,i.uid FROM dnf_gm.inventory_operations i JOIN dnf_gm.operations o ON o.operation_id=i.operation_id WHERE i.maintenance_id=%s AND o.status='executing' ORDER BY i.operation_id LIMIT 101 FOR UPDATE",(window_id,))
        pending=q.fetchall()
        if len(pending)>100:raise Refused('maintenance_pending_budget_exceeded')
        for row in pending:
            op=row['operation_id']
            q.execute('SELECT operation_id FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,))
            if q.fetchone():raise Refused('maintenance_inconsistent_snapshot')
            q.execute('SELECT operation_id FROM dnf_gm.audit WHERE operation_id=%s',(op,))
            if q.fetchone():raise Refused('maintenance_inconsistent_success_audit')
            q.execute('SELECT operation_id FROM dnf_gm.audit WHERE operation_id=%s',('intent:'+op,))
            if not q.fetchone():raise Refused('maintenance_intent_missing')
            result={'operation_id':op,'state':'aborted_before_game_commit','client_verified':False,
                    'note':'独占维护窗口下已取得操作行锁；没有本操作的游戏事务、快照或成功审计提交。不得重放原操作。'}
            q.execute("UPDATE dnf_gm.operations SET status='aborted',result_json=%s WHERE operation_id=%s AND status='executing'",(dump(result),op))
            if q.rowcount!=1:raise Refused('maintenance_resolution_changed')
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'maintenance','item-aborted',%s,'关闭维护窗口时核对中断意向',%s,%s)",('abort:'+op,row['uid'],dump({'operation_id':op,'maintenance_id':window_id}),dump(result)))
        c.commit()
    return {'resolved_aborted':[row['operation_id'] for row in pending], 'game_writes':False}
