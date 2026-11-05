"""Persistent maintenance barrier for ordinary game writes, not permissions.

A shared file lock covers transaction commit/rollback and native dispatch. The
root coordinator takes it exclusively before freezing admission. The persisted
freeze survives executor death; no time-based automatic reopening is allowed.
An empty installation path supports old releases, but cannot support maintenance.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import math
import os
import re

from fastapi import HTTPException
from .inventory_fence import open_lock, _read, directory
from .release_files import Refused

ROOT_UID = 0
FIELDS = {'version','state','generation','operation_id','binding_sha256','changed_at'}


class WriteGateClosed(HTTPException):
    def __init__(self, state='unknown'):
        message = ('游戏维护已冻结普通写入；充值、邮件、解锁和游戏内指令暂不执行。可查询原结果，维护恢复后再操作。'
                   if state=='frozen' else '无法核验维护写入屏障，已暂停新的游戏写入；请在维护中心核对，不要重复提交。')
        super().__init__(409, message)
        self.gate_state = state


def validate(value):
    if (not isinstance(value,dict) or set(value)!=FIELDS or type(value['version']) is not int or value['version']!=1
            or value['state'] not in ('open','frozen') or type(value['generation']) is not int
            or not 0<=value['generation']<=2147483647 or type(value['changed_at']) not in (int,float)
            or not math.isfinite(value['changed_at']) or value['changed_at']<0):
        raise Refused('write_gate_state_invalid')
    if value['generation']==0:
        if value['state']!='open' or value['operation_id']!='' or value['binding_sha256']!='':
            raise Refused('write_gate_state_invalid')
    elif (not isinstance(value['operation_id'],str) or not re.fullmatch('[a-f0-9]{32}',value['operation_id'])
            or not isinstance(value['binding_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['binding_sha256'])):
        raise Refused('write_gate_state_invalid')
    return value


def same_lock(root, fd, owner):
    directory(root,owner)
    before=os.fstat(fd);after=(Path(root)/'fence.lock').lstat()
    if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
        raise Refused('write_gate_lock_changed')


class WriteLease:
    def __init__(self, root=None, fd=None, owner=None, state=None):
        self.root,self.fd,self.owner,self.state=root,fd,owner,state

    def check(self):
        if self.root is None:return
        try:
            same_lock(self.root,self.fd,self.owner)
            if validate(_read(self.root,'state.json',self.owner,4096))!=self.state:
                raise Refused('write_gate_state_changed')
        except (OSError,ValueError,TypeError,KeyError):
            raise WriteGateClosed() from None


class GameplayWriteGate:
    def __init__(self, settings, *, owner=None):
        self.settings,self.owner=settings,owner

    @property
    def root(self):
        value=self.settings.gameplay_gate_dir
        return Path(value) if value else None

    def status(self):
        if self.root is None:return {'configured':False,'state':'not_configured','maintenance_supported':False}
        fd=None
        try:
            owner=ROOT_UID if self.owner is None else self.owner
            fd=open_lock(self.root,owner)
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            same_lock(self.root,fd,owner)
            state=validate(_read(self.root,'state.json',owner,4096))
            return {'configured':True,'maintenance_supported':True,**state}
        except (OSError,ValueError,TypeError,KeyError):
            return {'configured':True,'state':'unknown','maintenance_supported':False}
        finally:
            if fd is not None:os.close(fd)

    @contextmanager
    def writer(self):
        root=self.root
        if root is None:
            yield WriteLease()
            return
        owner=ROOT_UID if self.owner is None else self.owner
        fd=None
        try:
            fd=open_lock(root,owner)
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            same_lock(root,fd,owner)
            state=validate(_read(root,'state.json',owner,4096))
            if state['state']!='open':raise WriteGateClosed('frozen')
        except BaseException as error:
            if fd is not None:os.close(fd)
            if isinstance(error,(OSError,ValueError,TypeError,KeyError)):raise WriteGateClosed() from None
            raise
        try:
            yield WriteLease(root,fd,owner,state)
        finally:
            os.close(fd)
