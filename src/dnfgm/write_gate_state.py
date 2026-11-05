"""Dependency-free gate file protocol shared by root installation and the app."""
from pathlib import Path
import math
import os
import re
from .inventory_fence import directory
from .release_files import Refused

FIELDS = {'version','state','generation','operation_id','binding_sha256','changed_at'}


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

