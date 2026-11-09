import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location('rollback_guard', Path(__file__).parents[1] / 'deploy/check_rollback.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_older_release_without_schedules_is_compatible(tmp_path):
    q = Mock(); q.fetchone.return_value = {'n': 0}
    mod.check(q, tmp_path)
    assert q.execute.call_count == 8


@pytest.mark.parametrize('found', [None, {'found': 1}])
def test_older_release_rejects_any_account_schedule(tmp_path, found):
    q = Mock(); q.fetchone.side_effect = [{'n': 1}, found] + [{'n': 0}] * 7
    if found:
        with pytest.raises(mod.IncompatibleRollback): mod.check(q, tmp_path)
    else: mod.check(q, tmp_path)
    sql = q.execute.call_args_list[1].args[0]
    assert '$.reward_job.targets.mode' in sql and 'status' not in sql
    assert all(call.args[0].startswith('SELECT') for call in q.execute.call_args_list)


def test_explicitly_compatible_target(tmp_path):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text(json.dumps({'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1,'maintenance_requests':1,'campaign_rewards':1,'game_backup_requests':1}))
    q = Mock(); mod.check(q, tmp_path); q.execute.assert_not_called()


@pytest.mark.parametrize('data', ['bad', '{"schema_version":9}', '{"schema_version":1,"reward_target_modes":[1]}'])
def test_bad_manifest_fails_closed(tmp_path, data):
    (tmp_path/'deploy').mkdir(); (tmp_path/'deploy/release-features.json').write_text(data)
    with pytest.raises((mod.IncompatibleRollback, ValueError)): mod.check(Mock(), tmp_path)


def test_stop_and_guard_before_previous_installer():
    text = (Path(__file__).parents[1]/'deploy/rollback.sh').read_text()
    assert text.index('no-auto-recover') < text.index('systemctl stop "$UNIT"') < text.index('check_rollback.py') < text.index('bash "$PREVIOUS/deploy/install.sh"')
    assert 'docker ' not in text and 'mihomo' not in text and 'cliproxyapi' not in text


def test_older_release_cannot_ignore_managed_permissions(tmp_path):
    q=Mock();q.fetchone.side_effect=[{'n':0},{'n':1},{'revision':1}]
    with pytest.raises(mod.IncompatibleRollback,match='web-managed'):mod.check(q,tmp_path)


def test_older_target_cannot_abandon_maintenance_queue(tmp_path):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text(json.dumps({'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1}))
    q=Mock();q.fetchone.side_effect=[{'n':1},{'found':1}]
    with pytest.raises(mod.IncompatibleRollback,match='maintenance requests'):mod.check(q,tmp_path)
    assert all(call.args[0].startswith('SELECT') for call in q.execute.call_args_list)


def test_older_policy_reader_cannot_disable_all_writes_on_unknown_maintenance_switch(tmp_path):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text(json.dumps({'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1}))
    q=Mock();q.fetchone.side_effect=[{'n':0},{'n':1},{'found':1}]
    with pytest.raises(mod.IncompatibleRollback,match='maintenance capability'):mod.check(q,tmp_path)


def test_configured_gate_refuses_old_file_only_or_no_gate_release(tmp_path):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text(json.dumps({'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1,'maintenance_requests':1}))
    q=Mock()
    with pytest.raises(mod.IncompatibleRollback,match='transaction fence'):
        mod.check(q,tmp_path,gameplay_gate_configured=True)
    q.execute.assert_not_called()
    data=json.loads((tmp_path/'deploy/release-features.json').read_text());data.update(gameplay_transaction_fence=1,campaign_rewards=1,game_backup_requests=1)
    (tmp_path/'deploy/release-features.json').write_text(json.dumps(data))
    mod.check(q,tmp_path,gameplay_gate_configured=True)
    q.execute.assert_not_called()


def test_rollback_cli_supplies_actual_gate_configuration():
    text=(Path(__file__).parents[1]/'deploy/check_rollback.py').read_text()
    assert 'gameplay_gate_configured=bool(settings.gameplay_gate_dir)' in text


def feature_target(tmp_path, **features):
    (tmp_path/'deploy').mkdir()
    data={'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1,'maintenance_requests':1,
          'campaign_rewards':1,'game_backup_requests':1}
    data.update(features)
    (tmp_path/'deploy/release-features.json').write_text(json.dumps(data))


@pytest.mark.parametrize('table,paths', [
    ('reward_jobs', ('$.campaign_id','$.reward.campaign_id')),
    ('schedules', ('$.reward_job.campaign_id','$.reward_job.reward.campaign_id')),
    ('operations', ('$.campaign_id',)),
])
def test_old_worker_rejects_campaign_binding_in_all_record_states(tmp_path, table, paths):
    feature_target(tmp_path,campaign_rewards=0)
    q=Mock()
    earlier={'reward_jobs':0,'schedules':1,'operations':2}[table]
    q.fetchone.side_effect=[{'n':0}]*earlier+[{'n':1},{'found':1}]
    with pytest.raises(mod.IncompatibleRollback,match='campaign reward claims'):
        mod.check(q,tmp_path)
    statement,args=q.execute.call_args.args
    assert 'dnf_gm.'+table in statement and args==paths
    assert 'status' not in statement
    assert all(call.args[0].startswith('SELECT') for call in q.execute.call_args_list)


def test_old_worker_accepts_empty_campaign_tables(tmp_path):
    feature_target(tmp_path,campaign_rewards=0)
    q=Mock();q.fetchone.side_effect=[{'n':1},None]*3
    mod.check(q,tmp_path)


@pytest.mark.parametrize('found',[None,{'found':1}])
def test_old_worker_cannot_abandon_unfinished_game_backup(tmp_path,found):
    feature_target(tmp_path,game_backup_requests=0)
    q=Mock();q.fetchone.side_effect=[{'n':1},found]
    if found:
        with pytest.raises(mod.IncompatibleRollback,match='unfinished game backup'):
            mod.check(q,tmp_path)
    else:
        mod.check(q,tmp_path)
    statement=q.execute.call_args.args[0]
    assert "state NOT IN ('succeeded','failed')" in statement
    assert all(call.args[0].startswith('SELECT') for call in q.execute.call_args_list)


def test_current_release_declares_campaign_and_game_backup_protocols():
    data=json.loads((Path(__file__).parents[1]/'deploy/release-features.json').read_text())
    assert data['campaign_rewards']==data['game_backup_requests']==1
