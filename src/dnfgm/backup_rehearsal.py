"""Select private automatic snapshots for an explicit socket-only restore drill.

No production connection, service controls, artifact download or fallback to an
older backup after integrity failure. Receipts stay separate from retained data.
"""
import os
from pathlib import Path
import re
import stat

from .backup import canonical, restore_drill
from .backup_health import private_receipt, validate_receipt, verify_evidence


def private_directory(path, owner=None):
    path=Path(path)
    if not path.is_absolute():raise ValueError('Absolute backup directory required')
    info=path.lstat()
    owner=os.geteuid() if owner is None else owner
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=owner or info.st_mode&0o077:
        raise ValueError('Private owned backup directory required')
    return path


def latest_backup(root, *, owner=None):
    """Newest completed receipt wins; a bad newest artifact is never skipped."""
    root=private_directory(root,owner)
    candidates=[];seen=0
    for folder in root.iterdir():
        seen+=1
        if seen>1024:raise ValueError('Backup inventory exceeds review budget')
        if not re.fullmatch(r'management-[a-f0-9]{32}',folder.name):continue
        private_directory(folder,owner)
        receipt=folder/'backup-receipt.json'
        if not os.path.lexists(receipt):continue
        # A receipt claiming completion must be valid, even if another copy is
        # available. Unknown/incomplete data never gets a fabricated success.
        value=validate_receipt(private_receipt(receipt),'backup')
        candidates.append((value['completed_at'],folder.name,folder,value))
    if not candidates:raise ValueError('No completed automatic backup found')
    _,_,folder,value=max(candidates)
    evidence=verify_evidence(folder/'management.ndjson',folder/'backup-receipt.json')
    if evidence['integrity']!='verified':raise ValueError('Latest backup integrity failed')
    return folder,value


def write_new_receipt(path, value):
    path=Path(path)
    if not path.is_absolute():raise ValueError('Absolute private receipt path required')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())


def rehearse_latest(root, receipt, *, socket, datadir, owner=None, drill=restore_drill):
    """Explicit maintenance-computer operation; never connects to production."""
    receipt=Path(receipt)
    if not receipt.is_absolute() or os.path.lexists(receipt):raise ValueError('New absolute private receipt path required')
    folder,backup=latest_backup(root,owner=owner)
    if receipt.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Restore receipts must stay outside backup retention folders')
    restored=drill(folder/'management.ndjson',backup['artifact_sha256'],socket=socket,datadir=datadir)
    validate_receipt(restored,'restore')
    if (restored.get('artifact_sha256')!=backup['artifact_sha256'] or restored['started_at']<backup['completed_at']
            or any(restored[key]!=backup[key] for key in ('bytes','tables','rows'))):
        raise ValueError('Restore proof does not match selected backup')
    # Recheck the source after the potentially long drill, before publishing.
    evidence=verify_evidence(folder/'management.ndjson',folder/'backup-receipt.json')
    if evidence['integrity']!='verified' or evidence['backup']['artifact_sha256']!=backup['artifact_sha256']:
        raise ValueError('Selected backup changed during rehearsal')
    write_new_receipt(receipt,restored)
    evidence=verify_evidence(folder/'management.ndjson',folder/'backup-receipt.json',receipt)
    if evidence['integrity']!='verified' or (evidence['restore'] or {}).get('state')!='verified':
        raise ValueError('Restore evidence could not be verified')
    return evidence
