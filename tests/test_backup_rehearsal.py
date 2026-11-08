import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from dnfgm.backup import canonical
from dnfgm.backup_format import FORMAT
from dnfgm.backup_rehearsal import latest_backup,rehearse_latest


def fixture(root, ordinal, completed):
    root.mkdir(mode=0o700,exist_ok=True)
    folder=root/('management-'+format(ordinal,'032x'));folder.mkdir(mode=0o700)
    artifact=folder/'management.ndjson';artifact.write_bytes(b'synthetic-private-'+str(ordinal).encode());artifact.chmod(0o600)
    receipt={'format':FORMAT,'kind':'backup','state':'complete','scope':'management_only',
        'started_at':completed-1,'completed_at':completed,'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'bytes':artifact.stat().st_size,'tables':2,'rows':5}
    path=folder/'backup-receipt.json';path.write_bytes(canonical(receipt));path.chmod(0o600)
    return folder,receipt


def restored(backup):
    return {**backup,'kind':'restore','state':'verified','started_at':backup['completed_at']+1,'completed_at':backup['completed_at']+2,
        'target':'isolated_mysql57','checks':['table_definitions','primary_key_ordered_values','row_counts','artifact_sha256']}


def test_latest_complete_selection_refuses_bad_newest_instead_of_old_success(tmp_path):
    root=tmp_path/'private';old,_=fixture(root,1,time.time()-10);new,_=fixture(root,2,time.time()-5)
    incomplete=root/('management-'+'f'*32);incomplete.mkdir(mode=0o700)
    assert latest_backup(root)[0]==new
    (new/'management.ndjson').write_bytes(b'corrupt newest')
    with pytest.raises(ValueError,match='integrity'):latest_backup(root)
    assert (old/'management.ndjson').is_file()


def test_rehearsal_separates_evidence_and_requires_matching_restore(tmp_path):
    root=tmp_path/'private';folder,backup=fixture(root,1,time.time()-10)
    receipt=tmp_path/'restore.json';calls=[]
    def drill(path,sha,**kw):calls.append((path,sha,kw));return restored(backup)
    report=rehearse_latest(root,receipt,socket='/isolated/mysql.sock',datadir='/isolated/data',drill=drill)
    assert report['integrity']=='verified' and report['restore']['state']=='verified'
    assert calls==[(folder/'management.ndjson',backup['artifact_sha256'],{'socket':'/isolated/mysql.sock','datadir':'/isolated/data'})]
    assert receipt.stat().st_mode&0o777==0o600
    with pytest.raises(ValueError,match='New absolute'):rehearse_latest(root,receipt,socket='',datadir='',drill=drill)
    with pytest.raises(ValueError,match='outside backup retention'):rehearse_latest(root,folder/'restore.json',socket='',datadir='',drill=drill)
    with pytest.raises(ValueError,match='does not match'):
        rehearse_latest(root,tmp_path/'bad.json',socket='',datadir='',drill=lambda *a,**k:{**restored(backup),'rows':6})


def test_rehearsal_checks_source_again_before_certifying(tmp_path):
    root=tmp_path/'private';folder,backup=fixture(root,1,time.time()-10)
    def drill(*args,**kw):
        (folder/'management.ndjson').write_bytes(b'changed during drill')
        return restored(backup)
    receipt=tmp_path/'restore.json'
    with pytest.raises(ValueError,match='changed during'):rehearse_latest(root,receipt,socket='',datadir='',drill=drill)
    assert not receipt.exists()


def test_private_root_and_symlinked_backup_refused(tmp_path):
    root=tmp_path/'private';folder,_=fixture(root,1,time.time()-10)
    root.chmod(0o755)
    with pytest.raises(ValueError,match='Private owned'):latest_backup(root)
    root.chmod(0o700)
    alias=root/('management-'+'e'*32);alias.symlink_to(folder,target_is_directory=True)
    with pytest.raises(ValueError,match='Private owned'):latest_backup(root)


def test_daily_health_keeps_old_rehearsal_without_certifying_new_backup(tmp_path):
    from backup_worker import BackupWorker
    root=tmp_path/'private';_,old=fixture(root,1,time.time()-20);new,new_backup=fixture(root,2,time.time()-10)
    evidence=tmp_path/'evidence';evidence.mkdir(mode=0o700)
    receipt=evidence/'restore-receipt.json';receipt.write_bytes(canonical(restored(old)));receipt.chmod(0o600)
    health=evidence/'health.json'
    worker=BackupWorker(None,SimpleNamespace(backup_health_file=str(health)),owner=os.getuid())
    result=worker.publish(new)
    data=json.loads(health.read_text())
    assert result['restore_verified'] is False and data['restore']['state']=='other_artifact'
    assert data['restore']['artifact_sha256']==old['artifact_sha256']
    receipt.write_bytes(canonical(restored(new_backup)))
    assert worker.publish(new)['restore_verified'] is True
