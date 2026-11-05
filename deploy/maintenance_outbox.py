"""Fixed planning/cancellation worker for the web maintenance outbox.

No service-control CLI or installation entry point. execute_supported=False
until complete writer stop/fence/close/restore is connected. Game-only drain is
NEVER used as a substitute. The real planning path uses the durable coordinator.
"""
import os
from pathlib import Path
import re
import time
import hashlib
from dnfgm.inventory_fence import directory
from dnfgm.release_files import Refused, read_json, atomic_json, canonical, maintenance_lock
from maintenance_drain import error_code

ID=re.compile(r'[a-f0-9]{32}\Z')
SHA=re.compile(r'[a-f0-9]{64}\Z')
FIELDS={'operation_id','reason','created_at','image_digest','pvf_sha256','program_sha256'}
PHASES={'prepare','confirm','cancel','observe','close','recover'}


def validate_packet(value, filename):
    if not isinstance(value,dict) or value.get('version')!=1:
        raise Refused('maintenance_request_invalid')
    phase=value.get('phase');op=value.get('operation_id');request=value.get('request')
    if (phase not in PHASES or not isinstance(op,str) or not ID.fullmatch(op)
            or filename!=op+'.'+phase+'.json' or not isinstance(request,dict)
            or set(request)!=FIELDS or request.get('operation_id')!=op
            or set(value)!=({'version','operation_id','phase','request','request_sha256'}|({'fingerprint'} if phase in ('confirm','close','recover') else set())|({'recovery_id','revision'} if phase=='recover' else set()))):
        raise Refused('maintenance_request_invalid')
    if (not isinstance(request['reason'],str) or not 2<=len(request['reason'].strip())<=200
            or request['reason']!=request['reason'].strip() or type(request['created_at']) is not int
            or request['created_at']<0 or not isinstance(request['image_digest'],str)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',request['image_digest'])
            or any(not isinstance(request[k],str) or not SHA.fullmatch(request[k]) for k in ('pvf_sha256','program_sha256'))
            or value.get('request_sha256')!=hashlib.sha256(canonical(request)).hexdigest()
            or phase in ('confirm','close','recover') and (not isinstance(value.get('fingerprint'),str) or not SHA.fullmatch(value['fingerprint']))):
        raise Refused('maintenance_request_invalid')
    if phase=='recover' and (not isinstance(value.get('recovery_id'),str) or not ID.fullmatch(value['recovery_id'])
            or type(value.get('revision')) is not int or not 1<=value['revision']<=2048):
        raise Refused('maintenance_recovery_request_invalid')
    return value


class PreparationWorker:
    def __init__(self, root, coordinator, app_uid, *, owner=0, clock=time.time):
        self.root=Path(root);self.coordinator=coordinator;self.app_uid=app_uid
        self.owner,self.clock=owner,clock

    def publish_status(self):
        cfg=self.coordinator.host.cfg
        atomic_json(self.root/'status.json',{'version':1,'collected_at':self.clock(),
                    'image_digest':cfg['image_digest'],'pvf_sha256':cfg['pvf_sha256'],
                    'program_sha256':cfg['program_sha256'],'prepare_supported':self.coordinator.admission is not None,'execute_supported':False})

    def previous(self, data):
        try:prior=read_json(self.root/'results'/(data['operation_id']+'.json'),owner=self.owner,limit=65536)
        except FileNotFoundError:return None
        if (prior.get('request_sha256')!=data['request_sha256'] or prior.get('operation_id')!=data['operation_id']
                or prior.get('version')!=1):raise Refused('maintenance_receipt_mismatch')
        return prior

    def publish(self, data, result):
        result={**result,'version':1,'operation_id':data['operation_id'],'request_sha256':data['request_sha256']}
        if len(canonical(result))>65536:raise Refused('maintenance_receipt_budget')
        atomic_json(self.root/'results'/(data['operation_id']+'.json'),result)
        return result

    def private_status(self, op):
        try:return self.coordinator.status(op)
        except FileNotFoundError:
            # An active pointer without its journal is an unresolved operation,
            # not a new, unstarted request that can be expired or cancelled.
            if self.coordinator._active()==op:
                raise Refused('maintenance_journal_missing') from None
            return None

    def bind(self, data):
        # Public receipts may be lost. Keep the original web envelope in a
        # separate root-private ledger so the same ID cannot acquire new input.
        folder=self.root/'bindings'
        try:folder.mkdir(mode=0o700)
        except FileExistsError:pass
        directory(folder,self.owner)
        if folder.stat().st_mode & 0o077:raise Refused('maintenance_binding_not_private')
        path=folder/(data['operation_id']+'.json')
        try:old=read_json(path,owner=self.owner,limit=8192)
        except FileNotFoundError:
            # Do not adopt a different envelope for an orphaned private plan.
            if self.private_status(data['operation_id']) is not None and self.previous(data) is None:
                raise Refused('maintenance_binding_missing') from None
            old={'version':1,'request':data['request'],'request_sha256':data['request_sha256'],'cancelled':False}
            atomic_json(path,old,mode=0o600)
        if (not isinstance(old,dict) or set(old)!={'version','request','request_sha256','cancelled'}
                or old['version']!=1 or old['request']!=data['request']
                or old['request_sha256']!=data['request_sha256'] or type(old['cancelled']) is not bool):
            raise Refused('maintenance_binding_conflict')
        return old

    def process(self, data):
        op,phase,request=data['operation_id'],data['phase'],data['request']
        prior=self.previous(data)
        binding=self.bind(data)
        if binding['cancelled']:
            record=self.private_status(op)
            if record is not None:return self.publish(data,record)
            return self.publish(data,{'state':'cancelled','can_confirm':False,'can_cancel':False,
                'command_may_have_run':False,'maintenance_permit':False,'updated_at':self.clock()})
        if prior and prior['state'] in ('cancelled','expired','rejected','completed'):return prior
        if phase=='cancel':
            self.private_status(op)
            try:result=self.coordinator.cancel(op)
            except FileNotFoundError:
                # Cancellation may arrive first. Retain a tombstone so a late
                # prepare cannot reopen this request or steal logical ownership.
                atomic_json(self.root/'bindings'/(op+'.json'),{**binding,'cancelled':True},mode=0o600)
                result={'state':'cancelled','can_confirm':False,'can_cancel':False,
                        'command_may_have_run':False,'maintenance_permit':False,'updated_at':self.clock()}
            return self.publish(data,result)
        if phase in ('close','recover'):raise Refused('maintenance_full_executor_unavailable')
        if phase=='confirm':
            # Never call coordinator.confirm: game-only drain has no complete
            # stop/fence/restore workflow. HTTP readiness also refuses this.
            result=self.private_status(op) or {}
            if result and result.get('state')!='prepared':return self.publish(data,result)
            if result.get('state')=='prepared':self.coordinator.cancel(op)
            return self.publish(data,{'state':'rejected','error':'maintenance_full_executor_unavailable',
                    'can_confirm':False,'can_cancel':False,'maintenance_permit':False,
                    'command_may_have_run':result.get('command_may_have_run',False),'updated_at':self.clock()})
        if phase=='prepare':
            if self.private_status(op) is not None:
                return self.publish(data,self.coordinator.prepare(op,request['reason']))
            if not 0<=self.clock()-request['created_at']<300 and prior is None:
                return self.publish(data,{'state':'expired','can_confirm':False,'can_cancel':False,
                        'command_may_have_run':False,'maintenance_permit':False,'updated_at':self.clock()})
            cfg=self.coordinator.host.cfg
            if any(request[k]!=cfg[k] for k in ('image_digest','pvf_sha256','program_sha256')):
                raise Refused('maintenance_version_changed')
            result=self.coordinator.prepare(op,request['reason'])
        else:result={**self.coordinator.status(op),'observation':self.coordinator.observe(op)}
        return self.publish(data,result)

    def tick(self):
        directory(self.root,self.owner);directory(self.root/'results',self.owner)
        # Not the deployment lock acquired separately by the coordinator.
        with maintenance_lock(self.root/'worker.lock'):
            self.publish_status()
            candidates=[]
            with os.scandir(self.root/'inbox') as entries:
                for i,entry in enumerate(entries):
                    if i>=96:break
                    if re.fullmatch(r'[a-f0-9]{32}\.(prepare|confirm|cancel|observe|close|recover)\.json',entry.name):candidates.append(entry.name)
            errors=0
            for name in sorted(candidates):
                path=self.root/'inbox'/name
                try:
                    data=validate_packet(read_json(path,owner=self.app_uid,limit=8192),name)
                    # Binding conflicts are input errors, not execution errors.
                    # They must never produce a receipt under altered parameters.
                    self.previous(data);self.bind(data)
                    try:self.process(data)
                    except Refused as error:
                        # Preserve old authoritative receipts; an uncertain prior
                        # execution can never become a clean rejection here.
                        if self.previous(data) is not None:raise
                        # A missing public receipt is not evidence of no effects.
                        # Reconcile the private durable journal before reporting a
                        # terminal rejection (e.g. cancel after a lost drain reply).
                        record=self.private_status(data['operation_id'])
                        if record is not None:
                            self.publish(data,record)
                        else:
                            self.publish(data,{'state':'rejected','error':error_code(error),'can_confirm':False,
                                'can_cancel':False,'maintenance_permit':False,'command_may_have_run':False,'updated_at':self.clock()})
                    if read_json(path,owner=self.app_uid,limit=8192)==data:path.unlink()
                    return {'processed':1,'invalid':errors}
                except (OSError,ValueError,TypeError,KeyError,AttributeError):errors+=1
            return {'processed':0,'invalid':errors}
