"""Root-only writer barrier primitive for the complete maintenance coordinator.

No CLI/service entry point and no game commands. Restoration is checked by the
future fixed controller, not by a browser boolean. Never replace the lock inode,
expire a freeze, or open a missing state as if it were a new installation.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import os
import re
import time

from dnfgm.inventory_fence import directory, open_lock, _read
from dnfgm.release_files import Refused, atomic_json, canonical
from dnfgm.write_gate_state import same_lock, validate


def binding_hash(identity):
    keys={'container_id','container_started_at','image_digest','pid','boot_id','program_sha256','pvf_sha256','policy_sha256'}
    if (not isinstance(identity,dict) or set(identity)!=keys
            or any(not isinstance(identity[k],str) or not re.fullmatch('[a-f0-9]{64}',identity[k])
                   for k in ('container_id','program_sha256','pvf_sha256','policy_sha256'))
            or not isinstance(identity['image_digest'],str) or not re.fullmatch('sha256:[a-f0-9]{64}',identity['image_digest'])
            or type(identity['pid']) is not int or identity['pid']<=1
            or not isinstance(identity['boot_id'],str) or not re.fullmatch('[a-f0-9-]{36}',identity['boot_id'])
            or not isinstance(identity['container_started_at'],str) or not 1<=len(identity['container_started_at'])<=64):
        raise Refused('write_gate_binding_invalid')
    return hashlib.sha256(canonical(identity)).hexdigest()


class WriteGateManager:
    def __init__(self,root, *, owner=0,clock=time.time):
        self.root,self.owner,self.clock=Path(root),owner,clock

    def initialize(self):
        directory(self.root.parent,self.owner)
        try:self.root.mkdir(mode=0o755)
        except FileExistsError:pass
        directory(self.root,self.owner)
        if os.path.lexists(self.root/'fence.lock'):
            # Re-installation never opens an old freeze or repairs missing state.
            with self.locked(False):return self.read()
        if any(self.root.iterdir()):raise Refused('write_gate_initialization_incomplete')
        fd=os.open(self.root/'fence.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        try:os.fsync(fd)
        finally:os.close(fd)
        state={'version':1,'state':'open','generation':0,'operation_id':'','binding_sha256':'','changed_at':self.clock()}
        with self.locked(True):self.save(state)
        fd=os.open(self.root.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        return state

    @contextmanager
    def locked(self,exclusive):
        fd=open_lock(self.root,self.owner)
        try:
            try:fcntl.flock(fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
            except BlockingIOError:raise Refused('write_gate_busy') from None
            same_lock(self.root,fd,self.owner)
            yield
        finally:os.close(fd)

    def read(self):return validate(_read(self.root,'state.json',self.owner,4096))
    def save(self,state):atomic_json(self.root/'state.json',validate(state))

    def freeze(self,operation_id,identity,*,expected_state=None):
        if not isinstance(operation_id,str) or not re.fullmatch('[a-f0-9]{32}',operation_id):raise Refused('write_gate_operation_invalid')
        binding=binding_hash(identity)
        if expected_state is not None:
            validate(expected_state)
            if expected_state['state']!='open':raise Refused('write_gate_preview_changed')
        with self.locked(True):
            old=self.read()
            if old['state']=='frozen':
                if (old['operation_id']==operation_id and old['binding_sha256']==binding
                        and (expected_state is None or old['generation']==expected_state['generation']+1)):return old
                raise Refused('write_gate_owned_by_other_request')
            if expected_state is not None and old!=expected_state:raise Refused('write_gate_preview_changed')
            if old['operation_id']==operation_id:raise Refused('write_gate_request_already_released')
            state={**old,'state':'frozen','generation':old['generation']+1,'operation_id':operation_id,
                   'binding_sha256':binding,'changed_at':self.clock()}
            self.save(state)
            return state

    def check_frozen(self,token):
        validate(token)
        with self.locked(False):
            if token['state']!='frozen' or self.read()!=token:raise Refused('write_gate_token_changed')
        return token

    def drain_database(self,token,db,*,expected_server_uuid,reconcile=False):
        """Current-lock proof, optionally settling management outcomes; never a permit.

        Hold the frozen file state while waiting for all previous participating
        MySQL transactions, including COMMIT after an application crash. No game
        commands are issued here. The fixed full coordinator must journal this
        evidence before proceeding. With reconcile=True, management-only outcome
        updates/audit share this transaction and exclusive database fence. The expected
        database UUID must come from the original plan, never a fresh replacement
        target after freeze.
        """
        from dnfgm.gameplay_transactions import lock_transactions
        validate(token)
        if not isinstance(expected_server_uuid,str) or not re.fullmatch(r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}',expected_server_uuid):
            raise Refused('maintenance_database_identity_required')
        if (token['state']!='frozen' or not db.settings.gameplay_gate_dir
                or Path(db.settings.gameplay_gate_dir)!=self.root):
            raise Refused('maintenance_transaction_fence_binding_invalid')
        with self.locked(False):
            if self.read()!=token:raise Refused('write_gate_token_changed')
            with db.connect() as c,c.cursor() as q:
                protocol=lock_transactions(q,exclusive=True)
                q.execute('SELECT @@server_uuid AS server_uuid')
                server=q.fetchone()['server_uuid']
                if not isinstance(server,str) or not re.fullmatch(r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}',server):
                    raise Refused('maintenance_database_identity_unproven')
                if server!=expected_server_uuid:raise Refused('maintenance_database_identity_changed')
                if self.read()!=token:raise Refused('write_gate_token_changed')
                outcome = None
                if reconcile:
                    from dnfgm.ordinary_reconcile import settle
                    outcome = settle(q, {k: token[k] for k in ('operation_id','generation','binding_sha256')} | {'server_uuid':server})
                if self.read()!=token:raise Refused('write_gate_token_changed')
                c.commit()
            # A COMMIT/close failure never yields a successful proof. The immutable
            # reconciliation receipt handles retries; no gameplay write is replayed.
            return {'protocol_version':protocol,'ordinary_transactions_drained':True,
                    'operation_id':token['operation_id'],'generation':token['generation'],
                    'binding_sha256':token['binding_sha256'],'server_uuid':server,
                    'checked_at':self.clock(),'game_writes':False,'maintenance_permit':False,
                    **({'outcomes':outcome} if reconcile else {})}

    def release(self,token,verify_restored):
        validate(token)
        if token['state']!='frozen' or not callable(verify_restored):raise Refused('write_gate_restore_check_required')
        with self.locked(True):
            old=self.read()
            if any(old[k]!=token[k] for k in ('generation','operation_id','binding_sha256')):
                raise Refused('write_gate_token_changed')
            if old['state']=='open':return old
            if old!=token:raise Refused('write_gate_token_changed')
            # The full coordinator must close/reconcile the permit and verify
            # original services and core health before supplying this callback.
            if verify_restored() is not True:raise Refused('write_gate_restore_not_proven')
            state={**old,'state':'open','changed_at':self.clock()}
            self.save(state)
            return state
