import pytest
from dnfgm.equipment_metadata import enchant_definition,equipment_definition,attribute_definition,read_metadata


def test_enchant_requires_explicit_section_not_orb_name():
    assert enchant_definition([(5,'[name]'),(7,'低级地狱宝珠'),(5,'[stackable type]'),(7,'[quest]')]) is None
    tokens=[(5,'[string data]'),(7,'Interface/private.img'),(7,'[weapon]'),
        (5,'[enchant]'),(5,'[elemental property]'),(7,'[fire element]'),(5,'[/enchant]'),
        (5,'[physical attack]'),(2,999)]
    row=enchant_definition(tokens)
    assert row['target_names']==['武器']
    assert row['summary']=='攻击属性 火属性'
    assert len(row['effects'])==1
    with pytest.raises(ValueError):enchant_definition(tokens[:6])


def test_equipment_preserves_unknown_codes_and_does_not_invent_rarity():
    assert equipment_definition([(5,'[equipment type]'),(7,'[coat]'),(2,14),(5,'[rarity]'),(2,0)])=={'part_code':'[coat]','part_name':'上衣','rarity':0}
    assert equipment_definition([(5,'[equipment type]'),(7,'[future type]')])['part_name']=='[future type]'


def test_comparison_excludes_explicit_nested_effects_without_merging_same_tag():
    tokens=[(5,'[physical attack]'),(2,10),(2,20),
        (5,'[enchant]'),(5,'[physical attack]'),(2,99),
        (5,'[future conditional section]'),(5,'[magical attack]'),(2,999),
        (5,'[/future conditional section]'),(5,'[/enchant]'),
        (5,'[magical attack]'),(2,30)]
    assert attribute_definition(tokens)==[
        {'tag':'[physical attack]','label':'物理攻击','values':[10,20]},
        {'tag':'[magical attack]','label':'魔法攻击','values':[30]}]


def test_repeated_top_level_attributes_are_omitted_instead_of_added_or_replaced():
    tokens=[(5,'[physical attack]'),(2,10),(5,'[physical attack]'),(2,99),
        (5,'[magical attack]'),(2,30)]
    assert attribute_definition(tokens)==[{'tag':'[magical attack]','label':'魔法攻击','values':[30]}]


@pytest.mark.parametrize('tail',[
    [(5,'[enchant]'),(5,'[physical attack]'),(2,99)],
    [(5,'[if]'),(5,'[physical attack]'),(2,99)],
    [(5,'[/unknown section]')],
    [(5,'[if]'),(5,'[then]'),(5,'[/if]'),(5,'[/then]')],
])
def test_unbalanced_or_crossed_sections_cannot_be_presented_as_top_level(tail):
    assert attribute_definition([(5,'[physical attack]'),(2,10),*tail])==[]


def test_conditional_top_level_sections_do_not_become_comparison_values():
    tokens=[(5,'[if]'),(5,'[physical attack]'),(2,99),(5,'[/if]'),
        (5,'[then]'),(5,'[magical attack]'),(2,199),(5,'[/then]'),
        (5,'[HP MAX]'),(2,100)]
    assert attribute_definition(tokens)==[{'tag':'[HP MAX]','label':'HP上限','values':[100]}]


@pytest.mark.parametrize('version',[None,'1','2'])
def test_old_merged_attribute_indexes_are_hidden_until_reenriched(version):
    import json,sqlite3
    with sqlite3.connect(':memory:') as c:
        c.row_factory=sqlite3.Row
        c.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE equipment_attributes(item_id INTEGER PRIMARY KEY,attributes_json TEXT);')
        values=[{'tag':'[physical attack]','label':'物理攻击','values':[10]}]
        c.execute('INSERT INTO equipment_attributes VALUES(?,?)',(1,json.dumps(values)))
        if version is not None:c.execute('INSERT INTO metadata VALUES(?,?)',('equipment_attributes_version',version))
        labels={1:{'id':1}}
        read_metadata(c,labels)
    assert labels[1].get('base_attributes')==(values if version=='2' else None)
