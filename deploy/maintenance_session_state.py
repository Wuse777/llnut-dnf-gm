"""Pure-stdlib, read-only validation shared by root worker/monitor/installer."""
import hashlib
import math
import re

from dnfgm.inventory_fence import BOUND_FIELDS, _read
from dnfgm.release_files import Refused, canonical
from dnfgm.write_gate_state import validate as validate_gate
from maintenance_gate import binding_hash
from service_lifecycle import validate_cycle

MAX_BYTES=256*1024


def steps(plan):
    result=[('window-issue-intent',None),('window-issued',None),
            ('window-close-intent',None),('window-closed',None)]
    for name in plan['service_cycle']['start_order']:
        result.extend((phase,name) for phase in ('restore-marker-intent','restore-marker-applied',
            'restore-start-intent','restore-start-sent','service-restored'))
    return result+[('services-restored',None),('gate-release-intent',None),
                   ('gate-released',None),('session-completed',None)]


def bound_to_plan(binding,plan):
    return (isinstance(binding,dict) and set(binding)==set(BOUND_FIELDS)
        and all(binding[k]==plan['identity'][k] for k in BOUND_FIELDS if k!='components')
        and isinstance(binding['components'],list) and len(binding['components'])==len(plan['services_before'])
        and set(binding['components'])==set(plan['services_before']))


def restored_record(data,entry):
    state,process=data['state'],data['process']
    if (set(data)!={'service','state','process'} or not isinstance(state,list) or len(state)!=5
            or any(type(x) is not bool for x in state[:4]) or state[:3]!=entry['before'][:3]
            or type(state[4]) is not int or state[4]<=0
            or entry['contract']['notification-fd']!='absent' and state[3] is not True
            or not isinstance(process,dict) or set(process)!=set(entry['process'])
            or any(type(process[k]) is not int or process[k]<0 for k in ('pid','nspid','start_ticks','caught','ignored'))
            or process['pid']<=1 or process['nspid']!=state[4]
            or process['program_sha256']!=entry['process']['program_sha256']):
        raise Refused('maintenance_restoration_receipt_invalid')


def validate_abort(value,plan):
    if (not isinstance(value,dict) or set(value)!={'baseline','token','drain_digest','drain_revision'}
            or type(value['drain_revision']) is not int or not 2<=value['drain_revision']<=512
            or not isinstance(value['drain_digest'],str) or not re.fullmatch(r'[a-f0-9]{64}',value['drain_digest'])):
        raise Refused('maintenance_abort_record_invalid')
    token=validate_gate(value['token'])
    if (token['state']!='frozen' or token['generation']!=plan['admission']['gate']['generation']+1
            or token['binding_sha256']!=binding_hash(plan['identity'])):
        raise Refused('maintenance_abort_record_invalid')
    baseline=value['baseline'];before=plan['services_before'];cycle=validate_cycle(plan)
    if not isinstance(baseline,dict) or set(baseline)!=set(before):raise Refused('maintenance_abort_record_invalid')
    for name,row in baseline.items():
        if (not isinstance(row,list) or len(row)!=5 or any(type(x) is not bool for x in row[:4])
                or type(row[4]) is not int):raise Refused('maintenance_abort_record_invalid')
        if name not in cycle['entries']:
            if row!=before[name]:raise Refused('maintenance_abort_record_invalid')
        elif row!=[False,False,False,True,-1]:
            original=before[name]
            if row not in (original,[True,False,original[2],original[3],original[4]],
                            [True,False,False,original[3],original[4]]):
                raise Refused('maintenance_abort_record_invalid')
    return value


def validate(doc,request_id,plan):
    try:
        cycle=validate_cycle(plan)
        if (not isinstance(doc,dict) or set(doc)!=({'version','request_id','fingerprint','state','events','error','digest'}|({'abort'} if doc.get('version')==2 else set()))
                or type(doc['version']) is not int or doc['version'] not in (1,2)
                or doc['request_id']!=request_id or doc['fingerprint']!=plan['fingerprint']
                or doc['state'] not in ('opening','maintenance_open','closing','restoring','completed','needs_review')
                or doc['digest']!=hashlib.sha256(canonical({k:v for k,v in doc.items() if k!='digest'})).hexdigest()
                or not isinstance(doc['events'],list) or len(doc['events'])>512):raise ValueError()
        if doc['version']==2:
            validate_abort(doc['abort'],plan)
            if doc['abort']['token']['operation_id']!=request_id:raise ValueError()
            if any(e.get('phase') in ('window-issue-intent','window-issued') for e in doc['events']):raise ValueError()
        expected=steps(plan);count=len(doc['events'])
        if count and doc['events'][0].get('phase')=='window-abort-intent':expected[0]=('window-abort-intent',None)
        if count>=2 and doc['events'][1].get('phase')=='window-not-issued':expected[1]=('window-not-issued',None)
        if expected[0][0]=='window-abort-intent' and count>=2 and expected[1][0]!='window-not-issued':raise ValueError()
        if doc['state']=='maintenance_open' and expected[1][0]=='window-not-issued':raise ValueError()
        if doc['state']=='closing' and count==2 and expected[1][0]!='window-not-issued':raise ValueError()
        if count>len(expected):raise ValueError()
        if (doc['state']=='completed' and count!=len(expected)
                or doc['state']=='maintenance_open' and count!=2
                or doc['state']=='opening' and count>1
                or doc['state']=='closing' and count not in (2,3)
                or doc['state']=='restoring' and not 4<=count<len(expected)):raise ValueError()
        for event,(phase,name) in zip(doc['events'],expected):
            if (set(event)!={'phase','data','at','monotonic'}
                    or any(type(event[k]) not in (int,float) or not math.isfinite(event[k]) or event[k]<0 for k in ('at','monotonic'))
                    or event['phase']!=phase or not isinstance(event['data'],dict)
                    or event['data'].get('service')!=name):raise ValueError()
            data=event['data']
            if phase in ('window-issue-intent','window-abort-intent','window-not-issued','window-close-intent','gate-release-intent','session-completed'):
                if data!={'window_id':request_id}:raise ValueError()
            elif phase=='window-issued':
                if (set(data)!={'state','id','expires_at'} or data['state']!='issued' or data['id']!=request_id
                        or type(data['expires_at']) is not int):raise ValueError()
            elif phase=='window-closed':
                if (data.get('id')!=request_id or data.get('safe_to_resume') is not True
                        or data.get('game_writes') is not False or data.get('services_changed') is not False
                        or not bound_to_plan(data.get('binding'),plan)):raise ValueError()
            elif phase=='restore-marker-intent':
                if data!={'service':name,'normally_up':cycle['entries'][name]['before'][2]}:raise ValueError()
            elif phase in ('restore-marker-applied','restore-start-intent','restore-start-sent'):
                if data!={'service':name} and not (phase=='restore-start-sent' and data in ({'service':name,'reconciled':True},{'service':name,'preserved':True})):raise ValueError()
            elif phase=='service-restored':
                restored_record(data,cycle['entries'][name])
                if doc.get('abort',{}).get('baseline',{}).get(name,[False])[0] and data['process']!=cycle['entries'][name]['process']:
                    raise ValueError()
            elif phase=='services-restored':
                if data!={'services':cycle['start_order'],'ordinary_writes_open':False}:raise ValueError()
            elif phase=='gate-released':
                validate_gate(data)
                if (data['state']!='open' or data['operation_id']!=request_id
                        or data['generation']!=plan['admission']['gate']['generation']+1
                        or data['binding_sha256']!=binding_hash(plan['identity'])):raise ValueError()
        return doc
    except (KeyError,TypeError,ValueError,AttributeError):raise Refused('maintenance_session_invalid') from None


def load(root,owner,request_id,plan):
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id):
        raise Refused('maintenance_request_id_invalid')
    return validate(_read(root,'session-'+request_id+'.json',owner,MAX_BYTES),request_id,plan)
