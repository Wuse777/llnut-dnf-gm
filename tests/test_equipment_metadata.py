import pytest
from dnfgm.equipment_metadata import enchant_definition,equipment_definition


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
