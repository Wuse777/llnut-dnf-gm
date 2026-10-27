import pytest
from dnfgm.config import Settings


@pytest.mark.parametrize('changes',[dict(stack_limit=0),dict(stack_limit=True),dict(stack_limit=1000001),dict(reason=' '),dict(pvf_sha256='b'*64),dict(extra='forbidden')])
def test_maintenance_cap_validates_fingerprint_reason_and_integer(changes):
    entry=dict(pvf_sha256='a'*64,stack_limit=1000,reason='synthetic maintenance trial')
    entry.update(changes)
    with pytest.raises(ValueError,match='mail stack limit'):
        Settings(db_password='fixture',secret='s'*64,pvf_sha256='a'*64,mail_stack_limits={'7':entry}).check()


def test_defaults_do_not_relax_any_item_and_valid_trial_requires_explicit_id():
    settings=Settings(db_password='fixture',secret='s'*64,pvf_sha256='a'*64)
    assert settings.check().mail_stack_limits=={}
    settings.mail_stack_limits={'7':dict(pvf_sha256='a'*64,stack_limit=1000,reason='synthetic maintenance trial')}
    assert settings.check() is settings
    settings.mail_stack_limits['07']=settings.mail_stack_limits.pop('7')
    with pytest.raises(ValueError):settings.check()


def test_explicit_null_means_no_policy_cap_but_requires_storage_bounds():
    settings=Settings(db_password='fixture',secret='s'*64,pvf_sha256='a'*64,
        mail_stack_limits={'7':dict(pvf_sha256='a'*64,stack_limit=None,reason='explicit unbounded trial')})
    assert settings.check() is settings
