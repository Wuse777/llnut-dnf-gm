import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dnfgm.capabilities import evidence, release_identity
from dnfgm.capability_policy import RuntimeSettings, overrides, PolicyWorker, normalized
from dnfgm.config import Settings

BINDING={'source_revision':'abcdef123456','pvf_sha256':'a'*64,'image_digest':'sha256:'+'b'*64}


def write(tmp_path,**kw):
    row={**BINDING,'capability':'mail','checked_at':100,'level':'client','reference':'fixture-report-01',**kw}
    path=tmp_path/'evidence.json';path.write_text(json.dumps({'schema_version':1,'records':[row]}));return str(path)


def test_attestation_requires_exact_release_image_and_pvf(tmp_path):
    path=write(tmp_path)
    assert evidence(path,BINDING,101)['records']['mail']['state']=='matched'
    for key in BINDING:
        assert evidence(path,{**BINDING,key:'different'},101)['records']['mail']['state']=='version_mismatch'
    assert evidence(path,{**BINDING,'source_revision':None},101)['records']['mail']['state']=='version_mismatch'


@pytest.mark.parametrize('kw',[{'checked_at':True},{'checked_at':500},{'reference':'../../secret'},{'capability':'shell'},{'level':'enabled'}])
def test_invalid_evidence_is_not_accepted(tmp_path,kw):
    assert evidence(write(tmp_path,**kw),BINDING,101)=={'state':'unavailable','records':{}}


def test_dirty_build_never_inherits_client_attestation(tmp_path):
    binding={**BINDING,'source_revision':'abcdef123456-dirty'}
    assert evidence(write(tmp_path,source_revision=binding['source_revision']),binding,101)['records']['mail']['state']=='version_mismatch'


def test_missing_oversized_and_duplicate_evidence(tmp_path):
    assert evidence('',BINDING,101)['state']=='not_configured'
    path=Path(write(tmp_path));data=json.loads(path.read_text());data['records']*=2;path.write_text(json.dumps(data))
    assert evidence(str(path),BINDING,101)['state']=='unavailable'
    path.write_text('x'*65537);assert evidence(str(path),BINDING,101)['state']=='unavailable'


def test_runtime_settings_keep_private_base_and_atomically_replace_overlay():
    base=Settings(db_password='private',writes=('mail',),test_uids=(123,))
    s=RuntimeSettings(base);assert s.writes==('mail',)
    base.writes=('currency',);assert s.writes==('currency',)
    s.overlay=overrides(['mail','native-monitor']);assert s.writes==('mail',) and s.test_uids==()
    assert s.db_password=='private' and base.test_uids==(123,)


def test_dependency_normalization_is_explicit_and_bounded():
    assert normalized(['native-kick','batch-worker'])==['batch-reward','batch-worker','native-kick','native-monitor']
    for enabled in (['shell'],['mail','mail']):
        with pytest.raises(ValueError):normalized(enabled)


def test_idle_worker_observes_web_changes_without_restart():
    calls=[];policy=SimpleNamespace(refresh=lambda:calls.append('policy'));worker=SimpleNamespace(step=lambda:calls.append('step'))
    PolicyWorker(policy,worker).step();assert calls==['policy','step']
