from datetime import datetime,timezone
from dnfgm.backup_schedule import daily_key,next_due,scheduler_status
from dnfgm.alerts import observations


def test_local_daily_identity_and_failure_alert_opt_in(tmp_path):
    before=datetime(2026,11,4,19,59,tzinfo=timezone.utc).timestamp()
    after=before+60
    policy={'enabled':True,'hour':4,'minute':0}
    assert daily_key(policy,before) is None
    assert daily_key(policy,after)=='daily:2026-11-05'
    assert daily_key({**policy,'minute':1},after) is None
    assert next_due(policy,after)==after+86400
    assert daily_key({**policy,'enabled':False},after) is None
    assert scheduler_status(tmp_path/'missing',after)['state']=='unknown'
    b={'state':'ok','backup':{'state':'recent'},'restore':{'state':'recent'},'scheduler':{'alerts_enabled':True,'failure':True}}
    assert observations(None,True,after,{},backup=b)['backup']['bad'] is True
    b['scheduler']['alerts_enabled']=False
    assert observations(None,True,after,{},backup=b)['backup']['bad'] is False


def test_retention_keeps_newest_two_and_skips_unknown_or_partial(tmp_path):
    import json
    import os
    from pathlib import Path
    from types import SimpleNamespace
    from backup_worker import BackupWorker
    from dnfgm.backup_format import FORMAT
    root=tmp_path/'backups';root.mkdir(mode=0o700)
    now=2_000_000_000
    known=[]
    for i in range(4):
        folder=root/('management-'+format(i+1,'032x'));folder.mkdir(mode=0o700)
        (folder/'management.ndjson').write_bytes(b'private synthetic fixture\n')
        receipt={'format':FORMAT,'kind':'backup','scope':'management_only','state':'complete',
            'started_at':now-(10+i)*86400-1,'completed_at':now-(10+i)*86400,
            'artifact_sha256':'a'*64,'bytes':26,'tables':1,'rows':0}
        (folder/'backup-receipt.json').write_text(json.dumps(receipt))
        for p in folder.iterdir():p.chmod(0o600)
        known.append(folder)
    unknown=root/'manual-backup';unknown.mkdir(mode=0o700)
    partial=root/('management-'+'e'*32);partial.mkdir(mode=0o700)
    (partial/'management.ndjson.partial').write_bytes(b'incomplete')
    worker=BackupWorker(None,SimpleNamespace(),root=root,owner=os.getuid(),clock=lambda:now)
    assert worker.retention(7)==2
    assert all(p.is_dir() for p in known[:2])
    assert all(not p.exists() for p in known[2:])
    assert unknown.is_dir() and (partial/'management.ndjson.partial').is_file()
