"""Public defaults and maintenance configuration; no production connections."""
import importlib.util
import json
import os
import sys
from pathlib import Path
import pytest
from dnfgm.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    sys.path.insert(0, str(ROOT / 'deploy'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy' / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_examples_are_readonly_and_not_production_targets():
    cfg = json.loads((ROOT / 'deploy/config.example.json').read_text())
    assert cfg['writes'] == [] and cfg['test_uids'] == [-1]
    assert cfg['image_digest'] == cfg['pvf_sha256'] == ''
    cfg.update(secret='s' * 64, db_password='generated-only-for-fixture')
    assert Settings(**cfg).check().public is False


def test_writes_require_explicit_fingerprints():
    s = Settings(secret='s' * 64, db_password='fixture', writes=('currency',), write_approvals={'currency': True})
    with pytest.raises(ValueError, match='image fingerprint'):
        s.check()
    s.image_digest = 'fixture-image'
    with pytest.raises(ValueError, match='PVF SHA-256'):
        s.check()
    s.pvf_sha256 = 'a' * 64
    s.check()


def test_totp_cannot_be_mistaken_for_implemented_enrollment():
    with pytest.raises(ValueError, match='enrollment'):
        Settings(secret='s' * 64, db_password='fixture', require_totp=True).check()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX config modes are enforced on deployment Linux')
def test_config_permissions(tmp_path, monkeypatch):
    p = tmp_path / 'config.json'
    p.write_text(json.dumps(dict(secret='s' * 64, db_password='fixture')))
    monkeypatch.setenv('DNFGM_CONFIG', str(p))
    p.chmod(0o644)
    with pytest.raises(ValueError, match='0600'):
        load_settings()
    p.chmod(0o600)
    assert load_settings().writes == ()


@pytest.mark.parametrize('bad', ['%', "x'; DROP USER root; --", '-hfoo', 'host name'])
def test_grants_reject_wildcard_or_sql_literals(bad):
    with pytest.raises(ValueError):
        module('grants').bootstrap_sql(dict(db_password='f' * 64, db_account_host=bad), 'ignored')


def test_grants_accept_explicit_private_source_without_broadening():
    text = module('grants').bootstrap_sql(dict(db_password='f' * 64, db_account_host='192.0.2.10'),
                                        '$argon2id$v=19$m=1,t=1,p=1$c2FsdA$aGFzaA')
    assert "'dnf_gm_app'@'192.0.2.10'" in text
    assert "@'%'" not in text
    assert 'MAX_USER_CONNECTIONS 3' in text
    assert 'UPDATE(gold)' not in text and 'UPDATE(money)' not in text


@pytest.mark.parametrize('url', ['https://127.0.0.1/health', 'http://192.0.2.1/health',
                                'http://example.com/health', 'http://user:pass@127.0.0.1/health'])
def test_monitor_rejects_nonlocal_or_credentialed_targets(url):
    cfg = json.loads((ROOT / 'deploy/monitor.example.json').read_text())
    cfg['gateway_url'] = url
    with pytest.raises(ValueError):
        module('monitor').validate(cfg)


def test_monitor_defaults_and_strict_identifiers():
    m = module('monitor')
    cfg = json.loads((ROOT / 'deploy/monitor.example.json').read_text())
    assert m.validate(cfg)['min_memory_mib'] == 256
    cfg['components'] = ['mysql;echo unsafe']
    with pytest.raises(ValueError):
        m.validate(cfg)


def test_monitor_is_standalone_and_only_stops_gm():
    text = (ROOT / 'deploy/monitor.py').read_text()
    runtime = (ROOT / 'deploy/monitor_runtime.py').read_text()
    assert 'verify-core-services' not in text
    assert "['systemctl', 'stop', 'dnf-gm.service']" in runtime
    assert "['systemctl', 'start', 'dnf-gm.service']" in runtime
    assert 'shell=True' not in text + runtime
