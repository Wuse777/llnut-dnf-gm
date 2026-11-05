"""Pure stdlib proof validation also used by installed maintenance monitors."""
import copy
import pytest
from dnfgm.ordinary_reconcile import summary, validate_summary
from dnfgm.release_files import Refused


def record():
    return {'version':1,'rewards':[{'operation_id':'a'*32,'job_id':'b'*32,'ordinal':1,'status':'failed'}],
            'native_uncertain':['c'*32],'game_writes':False,'automatic_replay':False}


def test_valid_summary_is_deterministic_and_contains_no_player_data():
    first=summary(record(),'d'*32)
    assert first==summary(copy.deepcopy(record()),'d'*32)
    assert first['rewards_failed']==1 and first['rewards_committed']==0 and first['native_uncertain']==1
    assert validate_summary(first)==first


@pytest.mark.parametrize('field,value',[('version',True),('rewards_failed',True),('rewards_failed',101),
    ('rewards_committed',-1),('native_uncertain',1.0),('game_writes',True),('automatic_replay',True),
    ('audit_id','invalid'),('sha256','invalid')])
def test_invalid_proof_rejected(field,value):
    proof=summary(record(),'d'*32);proof[field]=value
    with pytest.raises(Refused):validate_summary(proof)


@pytest.mark.parametrize('change',['duplicate','native_duplicate','status','ordinal','extra','too_many','not_dict'])
def test_rehashed_receipt_still_must_be_consistent(change):
    r=record()
    if change=='duplicate':r['rewards'].append(copy.deepcopy(r['rewards'][0]))
    if change=='native_duplicate':r['native_uncertain'].append('a'*32)
    if change=='status':r['rewards'][0]['status']='unknown'
    if change=='ordinal':r['rewards'][0]['ordinal']=True
    if change=='extra':r['untrusted']='field'
    if change=='too_many':r['native_uncertain']=['c'*32]*101
    if change=='not_dict':r=[]
    with pytest.raises(Refused):summary(r,'d'*32)


def test_public_audit_does_not_mutate_stored_record_or_leak_malformed_payload():
    import json
    from dnfgm.ordinary_reconcile import public_audit
    row={'action':'maintenance-reconcile','operation_id':'maintenance-outcomes:'+'d'*32,
         'request_json':json.dumps({'server_uuid':'private'}),'result_json':json.dumps(record())}
    old=copy.deepcopy(row);view=public_audit(row)
    assert row==old and 'private' not in str(view) and 'binding_redacted' in view['request_json']
    row['result_json']=json.dumps({**record(),'password':'private-extra'})
    assert json.loads(public_audit(row)['result_json'])=={'state':'unknown','automatic_replay':False}
    row['action']='currency';assert public_audit(row) is row
