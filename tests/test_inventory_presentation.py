"""Only preview identity presentation: no database, maintenance or game writes."""
from types import SimpleNamespace
import pytest
from dnfgm.inventory_operations import InventoryOperations

@pytest.mark.parametrize('before_slot,after_slot',[
    ({'id':123,'enhancement':3},{'id':123,'enhancement':12}),
    ({'id':123,'enhancement':3},{'id':0,'empty':True}),
    ({'id':0,'empty':True},{'id':456,'enhancement':5}),
])
def test_preview_retains_independent_item_identity_without_images(before_slot,after_slot):
    labels={123:{'id':123,'name':'修改前长剑','part_name':'武器'},456:{'id':456,'name':'恢复项链','part_name':'项链'}}
    service=SimpleNamespace(catalog=SimpleNamespace(read_labels=lambda ids:{'state':'ok','items':labels}))
    op=InventoryOperations.__new__(InventoryOperations);op.service=service
    op.target=lambda *args:{'uid':1,'character':{'charac_no':2}}
    op.blob=lambda *args:b'before';op.reference=lambda *args:'ref'
    op.make_change=lambda *args:(b'after',{},before_slot,after_slot)
    op.versions=lambda :{'pvf_sha256':'a'*64}
    data={'action':'item-restore','uid':1,'charac_no':2,'container':'inventory','slot':0,'reference':'ref','changes':{},'reason':'只检查预览'}
    before,after,preview=op.build(None,data)
    assert before==b'before' and after==b'after'
    assert preview['before_item_info']==labels.get(before_slot['id'],{})
    assert preview['after_item_info']==labels.get(after_slot['id'],{})
    assert all('image' not in preview[key] for key in ('before_item_info','after_item_info'))
