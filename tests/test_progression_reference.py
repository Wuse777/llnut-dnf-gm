from types import SimpleNamespace
import pytest
from dnfgm.character_progression import compare_archive,experience
from tools.enrich_catalog_progression import progression_rows


def test_signed_bits_and_reference_range():
    assert experience(-2005093948)['unsigned']==2289873348
    d=compare_archive(2,1000,1200,{2:1000,3:2653})
    assert d['same_value'] is False
    assert d['saved']['reference']['state']=='within_reference'
    assert d['saved']['reference']['remaining']==1453
    assert compare_archive(2,999,2654,{2:1000,3:2653})['saved']['reference']['state']=='outside_reference'


def test_missing_does_not_become_zero_or_max_level():
    d=compare_archive(100,1,None,{100:2846271542})
    assert d['same_value'] is None
    assert d['saved']['unsigned'] is None
    assert d['range']['state']=='unknown'
    assert experience(True)['state']=='unsupported'


def test_table_uint32_and_order():
    reader=SimpleNamespace(tokens=lambda _: [(2,1000),(2,2127330010),(2,-2005093948)])
    assert progression_rows(reader)==[(2,1000),(3,2127330010),(4,2289873348)]
    reader.tokens=lambda _: [(2,1000),(2,999)]
    with pytest.raises(ValueError):progression_rows(reader)
