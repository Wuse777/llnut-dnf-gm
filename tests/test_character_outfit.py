import pymysql
import pytest
from dnfgm.character_outfit import read_saved_outfit, resolve_saved_outfit, validate_saved_rows
from dnfgm.outfit_recipe import canonical_outfit_recipe


def row(slot=0,item=990001,**kwargs):
    return dict(slot=slot,it_id=item,clear_avatar_id=0,color1=0,color2=0,**kwargs)


def test_verified_query_is_bounded_owner_bound_and_read_only():
    class Cursor:
        def execute(self,sql,args):self.sql,self.args=sql,args
        def fetchall(self):return [row()]
    q=Cursor();assert read_saved_outfit(q,12,34)['state']=='pending'
    assert q.args==(12,34)
    for clause in ('SELECT a.slot,a.it_id,a.clear_avatar_id,a.color1,a.color2','c.m_id=%s','c.delete_flag=0','a.slot BETWEEN 0 AND 9','a.stat=0','a.expire_date>NOW()','LIMIT 11'):
        assert clause in q.sql
    assert 'ui_id' not in q.sql and 'jewel_socket' not in q.sql


@pytest.mark.parametrize('code',[1054,1142,1146])
def test_legacy_schema_or_missing_permissions_degrade_safely(code):
    class Cursor:
        def execute(self,*args):raise pymysql.OperationalError(code,'private SQL detail')
    result=read_saved_outfit(Cursor(),12,34)
    assert result['state']=='unavailable' and 'private' not in str(result)


@pytest.mark.parametrize('rows',[
    [row(),row()], [row(-1)], [row(10)], [row(item=0)], [row(item=True)],
    [row(i%10,990001+i) for i in range(11)],
    [dict(row(),clear_avatar_id=12)], [dict(row(),color1=1)], [dict(row(),color2=-1)],
])
def test_ambiguous_or_modified_outfits_are_rejected_whole(rows):
    result=validate_saved_rows(rows)
    assert result['state']=='unsupported' and result['items']==[]


def test_part_identity_comes_from_pvf_not_database_slot_order():
    saved=validate_saved_rows([row(8,990001),row(0,990002)])
    labels={'state':'ok','items':{990001:{'part_code':'[hat avatar]'},990002:{'part_code':'[coat avatar]'}}}
    result=resolve_saved_outfit(saved,4,labels)
    recipe,sha=canonical_outfit_recipe(4,[{'slot':'[coat avatar]','id':990002},{'slot':'[hat avatar]','id':990001}])
    assert result['state']=='ok' and result['recipe_sha256']==sha and result['items']==recipe['items']
    assert 'stored_slot' not in str(result)


@pytest.mark.parametrize('parts',[['[coat avatar]','[coat avatar]'],['[coat avatar]','[unknown]'],['[coat avatar]',None]])
def test_duplicate_or_unknown_pvf_parts_do_not_become_partial_recipes(parts):
    saved=validate_saved_rows([row(0,990001),row(1,990002)])
    labels={'state':'ok','items':{990001:{'part_code':parts[0]},990002:{'part_code':parts[1]}}}
    assert resolve_saved_outfit(saved,0,labels)['state']=='unsupported'
    labels['state']='mismatch'
    assert resolve_saved_outfit(saved,0,labels)['state']=='unavailable'


def test_deleted_owner_and_empty_set_do_not_produce_outfit_identity():
    assert read_saved_outfit(None,12,34,deleted=True)['state']=='unavailable'
    assert resolve_saved_outfit(validate_saved_rows([]),0,{'state':'ok','items':{}})['state']=='empty'
