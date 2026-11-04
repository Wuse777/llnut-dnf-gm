import hashlib
import json
import sqlite3

import pytest
from dnfgm.catalog import Catalog
from dnfgm.pvf import build_index


@pytest.mark.parametrize('path,category,kind,single', [
    ('equipment/sword.equ','equipment','equipment',True),
    ('equipment/character/avatar/coat.equ','special','avatar',True),
    ('equipment/creature/test.equ','special','creature',True),
    ('stackable/cash/creature/food.stk','special','stackable',False),
    ('stackable/pet/rename.stk','special','stackable',False),
    ('stackable/material.stk','material','stackable',False),
])
def test_all_indexed_categories_are_enabled_without_review(path,category,kind,single):
    row = dict(id=7,name='fixture',category=category,stack_limit=0,durability=0,
               allowed=0,reviewed=0,source_path=path)
    item = Catalog.annotate(row, {}, creature_types={'7':0})
    assert item['sendable'] and item['supported'] and not item['metadata_reviewed']
    assert item['mail_kind'] == kind and item['single_item'] == single
    assert item['stack_limit'] == 2147483647 and item['indexed_stack_limit'] == 0
    assert item['quantity_unlimited'] and item['quantity_limit_source'] == 'storage-only'
    assert item['policy_state'] == 'trial'
    disabled = Catalog.annotate(row, {7:dict(enabled=0,reason='manual disable')})
    assert not disabled['sendable'] and disabled['policy_state'] == 'blocked'


def test_new_index_enables_specials_and_records_creature_types(tmp_path,monkeypatch):
    class Reader:
        tree = {}
        def __init__(self,*args): pass
        def close(self): pass
        def mapping(self,name):
            return [(1,'creature/test.equ'),(2,'character/avatar/test.equ')] if name.startswith('equipment/') else [(3,'cash/special.stk')]
        def fields(self,name):
            return {'[name]':['fixture'], '[sub type]':[1]}
    monkeypatch.setattr('dnfgm.pvf.Reader',Reader)
    source = tmp_path/'fixture.pvf'
    source.write_bytes(b'synthetic bytes only')
    output = tmp_path/'catalog.sqlite'
    result = build_index(source,output)
    assert result['items'] == 3
    with sqlite3.connect(output) as c:
        assert c.execute('SELECT allowed,reviewed FROM items').fetchall() == [(1,0)]*3
        metadata = dict(c.execute('SELECT key,value FROM metadata'))
    assert json.loads(metadata['creature_types']) == {'1':0}
    assert metadata['pvf_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
