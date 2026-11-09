"""Campaign contracts that run without a database or game installation."""
import copy
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from dnfgm.campaign_models import CampaignSave
from dnfgm.campaigns import Campaigns
from dnfgm.campaign_audience import predicates, schema, verify
from dnfgm.economy import normalize
from dnfgm.models import RewardTargets
from dnfgm.reward_jobs import RewardJobs
from dnfgm.service import Service

CID = 'c' * 32


def definition(**changes):
    value = dict(name='回归补给', description='', dedupe='account',
                 targets=RewardTargets(mode='all').model_dump(mode='json'), template_id=7, template_version=2)
    value.update(changes)
    return value


def test_dates_are_character_calendar_and_tags_are_parameterized():
    targets = RewardTargets(mode='filtered', tags_all=["x') OR 1=1 --", '回归', '回归'],
                            created_from='2026-10-01', created_to='2026-11-01', inactive_before='2026-10-20')
    sql, args, _ = RewardJobs.selector(targets.model_dump(mode='json'))
    assert "x') OR 1=1 --" not in sql and "x') OR 1=1 --" in args
    assert args.count('回归') == 1
    assert "IF(JSON_VALID(profile.tags_json),profile.tags_json,'[]')" in sql
    assert 'DATE(c.create_time)>=%s' in sql and 'DATE(c.create_time)<=%s' in sql
    assert 's.last_play_time' in sql and 'GREATEST' in sql and 'l.login_status=0' in sql
    assert '2026-10-20 00:00:00' in args and "'0000-00-00 00:00:00'" in sql


@pytest.mark.parametrize('kw', [dict(created_from='2026-11-01',created_to='2026-10-01'),
                              dict(tags_all=[' ']), dict(min_level=80,max_level=10)])
def test_invalid_audiences_are_rejected(kw):
    with pytest.raises(ValidationError):RewardTargets(mode='filtered', **kw)


def test_explicit_all_and_selected_cannot_hide_filter_conditions():
    for mode in ('all', 'selected', 'accounts'):
        data = RewardTargets(mode=mode, charac_nos=[1] if mode=='selected' else [],
                             account_uids=[1] if mode=='accounts' else [], tags_all=['回归']).model_dump()
        with pytest.raises(HTTPException):RewardJobs.selector(data)


class SchemaCursor:
    def __init__(self, kind='datetime', permission=True):self.kind,self.permission=kind,permission
    def execute(self, sql, args=()):
        if sql.startswith('SELECT c.create_time') and not self.permission:raise PermissionError()
    def fetchall(self):
        return [dict(TABLE_NAME=t,COLUMN_NAME=c,DATA_TYPE=self.kind) for t,c in
                [('charac_info','create_time'),('charac_info','last_play_time'),('charac_stat','last_play_time')]]


@pytest.mark.parametrize('cursor',[SchemaCursor('int'),SchemaCursor(permission=False)])
def test_schema_or_privilege_mismatch_disables_dates_instead_of_guessing(cursor):
    result=schema(cursor)
    assert not result['character_dates']['available'] and not result['account_registration']['available']
    with pytest.raises(HTTPException,match='409'):verify(cursor,{'created_from':'2026-11-01'})


def test_verified_dates_do_not_claim_account_registration_support():
    result=schema(SchemaCursor())
    assert result['character_dates']['available'] and result['returning']['available']
    assert result['account_registration']['available'] is False


def test_activated_definition_is_immutable_but_status_has_separate_revision():
    campaigns=Campaigns(SimpleNamespace(db=None))
    d=definition();row={'activated':1,'definition_json':json.dumps(d),'reward_json':'{}','binding_json':'{}'}
    request={**d,'status':'paused'}
    assert campaigns.freeze(None,request,row)[0]==d
    changed=copy.deepcopy(request);changed['dedupe']='character'
    with pytest.raises(HTTPException,match='409'):campaigns.freeze(None,changed,row)


def test_campaign_input_rejects_ambiguous_new_paused_state_and_blank_reason():
    base={**definition(),'reason':'保存活动'}
    with pytest.raises(ValidationError):CampaignSave(**{**base,'status':'paused'})
    with pytest.raises(ValidationError):CampaignSave(**{**base,'reason':' '})


def test_campaign_rejects_changed_game_image_before_binding_or_claiming(monkeypatch):
    campaigns=Campaigns(SimpleNamespace(db=None,settings=SimpleNamespace(image_digest='current-image')))
    frozen={'definition':definition(),'reward':{},'binding':{'image_digest':'old-image'}}
    from dnfgm.campaigns import digest
    row={'status':'active','definition_hash':digest(frozen),
         **{field+'_json':json.dumps(value) for field,value in frozen.items()}}
    monkeypatch.setattr(campaigns,'row',lambda *args:row)
    with pytest.raises(HTTPException,match='409'):
        campaigns.active(None,{'campaign_id':CID})
    frozen['binding']['image_digest']='current-image'
    row['binding_json']=json.dumps(frozen['binding']);row['definition_hash']=digest(frozen)
    assert campaigns.active(None,{'campaign_id':CID}) is row
    row['reward_json']='{"gold":99}'
    with pytest.raises(HTTPException,match='409'):
        campaigns.active(None,{'campaign_id':CID})


def test_claim_locks_campaign_and_duplicates_skip_whole_reward(monkeypatch):
    campaigns=Campaigns(SimpleNamespace(db=None))
    row={'id':CID,'definition_json':json.dumps(definition()),'definition_hash':'h'}
    events=[]
    monkeypatch.setattr(campaigns,'engines',lambda q:None)
    def active(q,data,lock=False):events.append(('lock',lock));return row
    monkeypatch.setattr(campaigns,'active',active)
    monkeypatch.setattr(campaigns,'eligible',lambda *args:events.append(('eligible',True)))
    monkeypatch.setattr(campaigns,'link',lambda *args:events.append(('link',True)))
    monkeypatch.setattr('dnfgm.campaigns.one',lambda q,sql,args: {'operation_id':'original'})
    class Cursor:
        def execute(self,*args):raise AssertionError('duplicate must not insert another claim')
    result=campaigns.claim(Cursor(),{'campaign_id':CID,'uid':9,'charac_no':10},'new',
                           {'campaign':{'id':CID,'definition_hash':'h'}})
    assert events[0]==('lock',True) and result['skipped']
    assert result['subject_id']==9 and result['original_operation_id']=='original'


def test_service_skips_mail_and_every_currency_for_existing_campaign_claim():
    s=Service.__new__(Service)
    s.catalog=SimpleNamespace(items=lambda *a,**k:{'items':[]})
    s.campaigns=SimpleNamespace(claim=lambda *a:{'id':CID,'skipped':True})
    s.reward_snapshot=lambda *a:{'rewards':{'items':[]},'has_mail':True}
    s.apply_currency=lambda *a,**k:pytest.fail('duplicate cannot credit a currency')
    s.apply_mail=lambda *a,**k:pytest.fail('duplicate cannot send mail or gold')
    result=s.apply_reward(None,'op',{'campaign_id':CID},
                          {'rewards':{'items':[]},'has_mail':True,'balances':{}},{})
    assert result['state']=='campaign_duplicate_skipped' and result['currency_rewards']=={}


def test_duplicate_projection_is_complete_zero_activity_not_unknown_or_requested_amounts():
    req={'uid':9,'charac_no':10,'campaign_id':CID,'gold':100,'items':[{'id':7,'quantity':200}]}
    result={'state':'campaign_duplicate_skipped','currency_rewards':{},'campaign':{'id':CID,'skipped':True}}
    audit=dict(target_uid=9,action='reward',request_json=json.dumps(req),result_json=json.dumps(result))
    assert normalize(audit)==(req,10,{})
    result['campaign']['id']='wrong';audit['result_json']=json.dumps(result)
    with pytest.raises(ValueError):normalize(audit)
