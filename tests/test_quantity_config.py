import pytest
from dnfgm.config import Settings


@pytest.mark.parametrize('legacy', [{}, {'7':{'stack_limit':1}},
    {'7':{'pvf_sha256':'b'*64,'stack_limit':1000,'reason':'legacy'}},
    {'7':{'pvf_sha256':'a'*64,'stack_limit':None,'reason':'legacy'}}])
def test_deprecated_quantity_configuration_does_not_gate_startup(legacy):
    settings=Settings(db_password='fixture',secret='s'*64,pvf_sha256='a'*64,
                      mail_stack_limits=legacy)
    assert settings.check() is settings
