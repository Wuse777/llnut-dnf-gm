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
    assert q.execute.call_count == 4


@pytest.mark.parametrize('found', [None, {'found': 1}])
def test_older_release_rejects_any_account_schedule(tmp_path, found):
    q = Mock(); q.fetchone.side_effect = [{'n': 1}, found, {'n': 0}, {'n': 0}, {'n': 0}]
    if found:
        with pytest.raises(mod.IncompatibleRollback): mod.check(q, tmp_path)
    else: mod.check(q, tmp_path)
    sql = q.execute.call_args_list[1].args[0]
    assert '$.reward_job.targets.mode' in sql and 'status' not in sql
    assert all(call.args[0].startswith('SELECT') for call in q.execute.call_args_list)


def test_explicitly_compatible_target(tmp_path):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text(json.dumps({'schema_version':1,'reward_target_modes':['accounts'],'web_capability_policy':1,'maintenance_requests':1}))
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
    data=json.loads((tmp_path/'deploy/release-features.json').read_text());data['gameplay_transaction_fence']=1
    (tmp_path/'deploy/release-features.json').write_text(json.dumps(data))
    mod.check(q,tmp_path,gameplay_gate_configured=True)
    q.execute.assert_not_called()


def test_rollback_cli_supplies_actual_gate_configuration():
    text=(Path(__file__).parents[1]/'deploy/check_rollback.py').read_text()
    assert 'gameplay_gate_configured=bool(settings.gameplay_gate_dir)' in text
