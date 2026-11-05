import sys
from pathlib import Path
import pytest
from dnfgm.observer_policy import resolve
from dnfgm import alerts
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import alert_worker


def test_persisted_policy_survives_gm_outage_and_rejects_revision_regression(tmp_path):
    cfg={'task_probe_token':'a'*64,'task_health_enabled':True}
    p={'revision':2,'checked_at':100,'enabled':[]}
    assert resolve(cfg,tmp_path,100,lambda _:p)==(p,'live')
    def down(_):raise OSError('offline')
    assert resolve(cfg,tmp_path,130,down)==(p,'cached')
    assert resolve(cfg,tmp_path,130,lambda _:{**p,'revision':1,'checked_at':130,'enabled':['health-alerts']})==(p,'cached')
    (tmp_path/'policy.json').write_text('corrupt')
    with pytest.raises(ValueError):resolve(cfg,tmp_path,160,down)


def test_disabled_groups_do_not_probe_or_report_false_recovery(tmp_path):
    cfg={'health_host':'testserver','thresholds':{'memory':256,'swap':1536,'disk':2},'task_probe_token':'a'*64,'webhook_url':''}
    def forbidden(_):raise AssertionError('disabled group performed probe')
    result=alert_worker.run_once(cfg,root=tmp_path,status_path=tmp_path/'missing',clock=lambda:100,probe=forbidden,task_probe=forbidden,policy_probe=lambda _:{'revision':3,'checked_at':100,'enabled':[]})
    assert all(r['observed']=='disabled' for r in result['rules'])
    assert result['history']==[]
    public=alerts.read_report(tmp_path/'public.json',100)
    assert public['observer_policy']=={'revision':3,'checked_at':100,'enabled':[],'source':'live'}
