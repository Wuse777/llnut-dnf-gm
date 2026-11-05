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
    assert q.execute.call_count == 1


@pytest.mark.parametrize('found', [None, {'found': 1}])
def test_older_release_rejects_any_account_schedule(tmp_path, found):
    q = Mock(); q.fetchone.side_effect = [{'n': 1}, found]
    if found:
        with pytest.raises(mod.IncompatibleRollback): mod.check(q, tmp_path)
    else: mod.check(q, tmp_path)
    sql = q.execute.call_args.args[0]
    assert '$.reward_job.targets.mode' in sql and 'status' not in sql
    assert all(call.args[0].startswith('SELECT') for call in q.execute.call_args_list)


def test_explicitly_compatible_target(tmp_path):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text(json.dumps({'schema_version':1,'reward_target_modes':['accounts']}))
    q = Mock(); mod.check(q, tmp_path); q.execute.assert_not_called()


@pytest.mark.parametrize('data', ['bad', '{"schema_version":9}', '{"schema_version":1,"reward_target_modes":[1]}'])
def test_bad_manifest_fails_closed(tmp_path, data):
    (tmp_path/'deploy').mkdir(); (tmp_path/'deploy/release-features.json').write_text(data)
    with pytest.raises((mod.IncompatibleRollback, ValueError)): mod.check(Mock(), tmp_path)


def test_stop_and_guard_before_previous_installer():
    text = (Path(__file__).parents[1]/'deploy/rollback.sh').read_text()
    assert text.index('no-auto-recover') < text.index('systemctl stop "$UNIT"') < text.index('check_rollback.py') < text.index('bash "$PREVIOUS/deploy/install.sh"')
    assert 'docker ' not in text and 'mihomo' not in text and 'cliproxyapi' not in text
