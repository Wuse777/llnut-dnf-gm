import pytest
from fastapi import HTTPException
from dnfgm.ui_preferences import preference_payload, UiPreferences


def test_saved_filter_and_layout_payloads_are_typed_not_arbitrary_documents():
    saved=preference_payload('catalog-filter',{'rarity':0,'job':'[mage]','weapon_type':'staff','set_id':10,'sort':'level_desc'})
    assert saved['rarity']==0 and saved['sort']=='level_desc'
    assert preference_payload('layout',{})['theme']=='light'
    for kind,payload in [('layout',{'password':'never persist'}),('catalog-filter',{'min_level':80,'max_level':10}),
            ('catalog-filter',{'pendingId':'a'*32}),('appearance',{'job':True})]:
        with pytest.raises(HTTPException) as error:preference_payload(kind,payload)
        assert error.value.status_code==422


def test_appearance_scheme_accepts_only_unique_explicit_avatar_slots():
    saved=preference_payload('appearance',{'job':3,'slots':[{'slot':'[shoes avatar]','item_id':2},{'slot':'[hat avatar]','item_id':1}]})
    assert [r['item_id'] for r in saved['slots']]==[1,2] and saved['direction']=='right'
    assert preference_payload('appearance',{'job':3,'direction':'mirror_left'})['direction']=='mirror_left'
    for payload in [{'job':3,'slots':[{'slot':'[hat avatar]','item_id':1}]*2},
            {'job':3,'direction':'left'}, {'job':3,'slots':[{'slot':'weapon','item_id':1}]},
            {'job':3,'slots':[{'slot':'[hat avatar]','item_id':True}]},
            {'job':3,'atlas_path':'../../anything'}, {'job':3,'grow_type':128}]:
        with pytest.raises(HTTPException):preference_payload('appearance',payload)


@pytest.mark.parametrize('name',['',' name','name ','bad/name','bad\\name','bad\x00name','x'*49])
def test_preference_name_rejects_hidden_or_path_text(name):
    with pytest.raises(HTTPException):UiPreferences.name(name)
