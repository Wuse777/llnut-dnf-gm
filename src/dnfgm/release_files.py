"""Narrow release-file protocol. No shell, database, game data, or restart access."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import secrets
import stat
import time

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z')
OP = re.compile(r'[0-9a-f]{32}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_FILES = 20000
MAX_SECONDS = 8
MAX_DEPTH = 48


class Refused(ValueError):
    pass


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def invalid_constant(value):
    raise Refused('non_finite_json')


def read_json(path, *, owner=None, limit=65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022 or st.st_nlink != 1 or st.st_size > limit or (owner is not None and st.st_uid != owner):
            raise Refused('unsafe_file')
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise Refused('oversized_file')
        return json.loads(raw,parse_constant=invalid_constant)
    finally:
        os.close(fd)


def atomic_json(path, value, mode=0o644):
    path = Path(path)
    # Only called in directories owned by this writer; never follow temp links.
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(8) + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(canonical(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp, path)
        d = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if tmp.exists():tmp.unlink()


@contextmanager
def maintenance_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid() or st.st_mode & 0o022:raise Refused('unsafe_lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def mounted_below(root, text=None):
    if text is None:
        with open('/proc/self/mountinfo') as f:text=f.read(1024*1024+1)
    if len(text)>1024*1024:raise Refused('mount_table_oversized')
    for line in text.splitlines():
        pieces=line.split()
        if len(pieces)<6:raise Refused('mount_table_invalid')
        mount=re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),pieces[4])
        if Path(mount).is_relative_to(root):return True
    return False


def protected_names(base, owner=0):
    base=Path(base);root=base/'releases'
    for directory in (base, root):
        st=directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=owner or st.st_mode & 0o022:raise Refused('release_root_invalid')
    protected=set()
    for name in ('current','previous'):
        pointer=base/name
        if not pointer.is_symlink():
            if name=='previous' and not pointer.exists():continue
            raise Refused('release_pointer_invalid')
        target=pointer.resolve(strict=True)
        if target.parent!=root.resolve() or not NAME.fullmatch(target.name):raise Refused('release_pointer_outside')
        protected.add(target.name)
    # Also protect the two newest release directories, even if not pointed to.
    entries=[]
    with os.scandir(root) as scan:
        for i,entry in enumerate(scan):
            if i>=100:raise Refused('release_inventory_truncated')
            if entry.is_dir(follow_symlinks=False) and NAME.fullmatch(entry.name):
                entries.append((entry.stat(follow_symlinks=False).st_mtime_ns,entry.name))
    protected.update(name for _,name in sorted(entries,reverse=True)[:2])
    return protected


def describe(base, name, *, owner=0, mounts=None):
    if not isinstance(name,str) or not NAME.fullmatch(name):raise Refused('invalid_release_name')
    base=Path(base);root=base/'releases';path=root/name
    if name in protected_names(base, owner):raise Refused('protected_release')
    if mounted_below(path.resolve(),mounts):raise Refused('nested_mount')
    started=time.monotonic();digest=hashlib.sha256();count=0;size=0
    def visit(folder,relative='',depth=0):
        nonlocal count,size
        if depth > MAX_DEPTH:raise Refused('tree_too_deep')
        if time.monotonic()-started>MAX_SECONDS:raise Refused('scan_timeout')
        # A candidate's tree is required to be owner-only mutable.
        st=folder.lstat()
        if st.st_uid!=owner or st.st_mode & 0o022 or stat.S_ISLNK(st.st_mode):raise Refused('release_not_immutable')
        if st.st_dev!=device:raise Refused('different_filesystem')
        digest.update(canonical([relative,st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns]))
        count+=1;size+=st.st_blocks*512
        if count>MAX_FILES:raise Refused('too_many_entries')
        if stat.S_ISDIR(st.st_mode):
            with os.scandir(folder) as entries:
                children=[]
                for entry in entries:
                    if len(children)+count>MAX_FILES:raise Refused('too_many_entries')
                    children.append(entry.name)
            for child in sorted(children):visit(folder/child,relative+'/'+child,depth+1)
        elif not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022 or st.st_nlink!=1:raise Refused('special_or_linked_file')
    initial=path.lstat();device=initial.st_dev
    if not stat.S_ISDIR(initial.st_mode):raise Refused('not_a_release_directory')
    # Require recognizable packaged source, not just an arbitrary old directory.
    for marker in ('SOURCE_REVISION','SHA256SUMS','pyproject.toml'):
        if not (path/marker).is_file():raise Refused('not_a_release_package')
    visit(path)
    return {'name':name,'device':device,'inode':initial.st_ino,'fingerprint':digest.hexdigest(),
            'allocated_bytes':size,'entries':count,'expires_at':int(time.time())+300}


def sign(descriptor, key):
    return hmac.new(key,canonical(descriptor),hashlib.sha256).hexdigest()


def verify(item,key):
    if not isinstance(item,dict) or set(item)!={'descriptor','ticket'}:raise Refused('invalid_ticket')
    d=item['descriptor'];ticket=item['ticket']
    if not isinstance(d,dict) or set(d)!={'name','device','inode','fingerprint','allocated_bytes','entries','expires_at'}:raise Refused('invalid_descriptor')
    if not isinstance(ticket,str) or not HEX.fullmatch(ticket) or not hmac.compare_digest(ticket,sign(d,key)):raise Refused('invalid_signature')
    if type(d['expires_at']) is not int or not 0<=d['expires_at']-time.time()<=300:raise Refused('ticket_expired')
    return d


def manifest(base,key,*,owner=0):
    now=time.time();items=[]
    try:
        protected=protected_names(base, owner)
        root=Path(base)/'releases'
        for name in sorted(os.listdir(root)):
            if not NAME.fullmatch(name):continue
            if name in protected:
                items.append({'name':name,'eligible':False,'reason':'protected_release'});continue
            if time.time()-now>15:
                items.append({'name':name,'eligible':False,'reason':'scan_budget_exhausted'});continue
            try:
                d=describe(base,name,owner=owner)
                items.append({'name':name,'eligible':True,'descriptor':d,'ticket':sign(d,key)})
            except (OSError,Refused) as e:
                items.append({'name':name,'eligible':False,'reason':str(e) if isinstance(e,Refused) else 'unreadable_release'})
        return {'state':'ok','collected_at':time.time(),'items':items,'note':'只允许清理根目录内已核验的旧GM产物，当前/回滚及最新两个目录受保护；不清理游戏、备份或日志。'}
    except (OSError,Refused) as e:
        return {'state':'unavailable','collected_at':time.time(),'items':[],
                'reason':str(e) if isinstance(e,Refused) else 'inventory_failed'}


def reconcile_receipt(request, receipt_path, *, owner=0):
    """Read a prior receipt; interrupted work is never automatically replayed."""
    if receipt_path.exists():
        previous=read_json(receipt_path,owner=owner)
        if not isinstance(previous,dict) or previous.get('operation_id')!=request.get('operation_id') or previous.get('state') not in ('executing','completed','rejected','needs_review'):raise Refused('invalid_receipt')
        if previous.get('request_sha256')!=hashlib.sha256(canonical(request)).hexdigest():raise Refused('operation_conflict')
        if previous.get('state')=='executing':
            # Never re-enter rmtree after an interrupted deletion.
            previous.update(state='needs_review',reason='interrupted_execution',finished_at=time.time())
            for item in previous['items']:
                if item.get('state')=='deleting':item['state']='interrupted_unknown'
            atomic_json(receipt_path,previous)
        return read_json(receipt_path,owner=owner)
    return None


def execute(base, request, key, receipt_path, *, owner=0, remover=shutil.rmtree):
    if not isinstance(request,dict):raise Refused('invalid_request')
    op=request.get('operation_id')
    if not isinstance(op,str) or not OP.fullmatch(op) or set(request)!={'operation_id','items'}:raise Refused('invalid_request')
    previous = reconcile_receipt(request, receipt_path, owner=owner)
    if previous is not None:return previous
    items=request['items']
    if not isinstance(items,list) or not 1<=len(items)<=5:raise Refused('invalid_selection')
    receipt={'operation_id':op,'request_sha256':hashlib.sha256(canonical(request)).hexdigest(),'state':'executing','started_at':time.time(),'items':[],'atomic':False}
    try:
        descriptors=[verify(item,key) for item in items]
        if len({d['name'] for d in descriptors})!=len(descriptors):raise Refused('duplicate_release')
        if not shutil.rmtree.avoids_symlink_attacks:raise Refused('unsafe_platform')
        # Validate every selection before starting any deletion.
        for expected in descriptors:
            actual=describe(base,expected['name'],owner=owner)
            if {k:v for k,v in actual.items() if k!='expires_at'}!={k:v for k,v in expected.items() if k!='expires_at'}:raise Refused('release_changed')
            receipt['items'].append({'name':expected['name'],'state':'prepared','allocated_bytes':expected['allocated_bytes']})
    except (OSError,Refused) as e:
        receipt.update(state='rejected',reason=str(e) if isinstance(e,Refused) else 'validation_failed',finished_at=time.time())
        atomic_json(receipt_path,receipt);return receipt
    atomic_json(receipt_path,receipt)
    rootfd=os.open(Path(base)/'releases',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for i,d in enumerate(descriptors):
            # Shared maintenance flock must remain held across this whole function.
            if d['name'] in protected_names(base, owner):raise Refused('protected_release')
            st=os.stat(d['name'],dir_fd=rootfd,follow_symlinks=False)
            if st.st_ino!=d['inode'] or st.st_dev!=d['device']:raise Refused('release_changed')
            receipt['items'][i]['state']='deleting';atomic_json(receipt_path,receipt)
            remover(d['name'],dir_fd=rootfd)
            receipt['items'][i]['state']='removed';atomic_json(receipt_path,receipt)
        receipt.update(state='completed',finished_at=time.time())
    except Exception as e:
        receipt.update(state='needs_review',reason=str(e) if isinstance(e,Refused) else 'deletion_failed',finished_at=time.time())
        for item in receipt['items']:
            if item['state']=='deleting':item['state']='partial_or_unknown'
    finally:
        os.close(rootfd)
    atomic_json(receipt_path,receipt)
    return receipt
