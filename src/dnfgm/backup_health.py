"""Small public evidence projection; never expose backups/paths or run restore."""
import json
import math
import time
from .alerts import read_json
from .backup_format import FORMAT, MAX_ARTIFACT


def finite(v):return type(v) in (int,float) and math.isfinite(v) and v>=0

def validate_receipt(d,kind):
    if (d.get('format')!=FORMAT or d.get('kind')!=kind or d.get('scope')!='management_only'
            or d.get('state')!=('complete' if kind=='backup' else 'verified')
            or not finite(d.get('completed_at')) or not finite(d.get('started_at'))
            or d['completed_at']<d['started_at']):raise ValueError('Incomplete receipt')
    if kind=='restore' and (d.get('target')!='isolated_mysql57' or d.get('checks')!=['table_definitions','primary_key_ordered_values','row_counts','artifact_sha256']):
        raise ValueError('Insufficient restore evidence')
    for key in ('bytes','tables','rows'):
        if type(d.get(key)) is not int or d[key]<0:raise ValueError('Invalid backup summary')
    if not 1<=d['tables']<=64:raise ValueError('Invalid table count')
    return d


def private_receipt(path):
    from .backup import private_artifact
    with private_artifact(path) as (f,_):
        raw=f.read(65537)
        if len(raw)>65536:raise ValueError('Oversized receipt')
        d=json.loads(raw)
        if not isinstance(d,dict):raise ValueError('Invalid receipt')
        return d


def verify_evidence(artifact,backup_receipt,restore_receipt=None,*,now=None):
    from .backup import private_artifact, file_sha
    now=time.time() if now is None else now
    result={'version':1,'checked_at':now,'scope':'management_only','integrity':'unavailable','backup':None,'restore':None}
    try:
        b=validate_receipt(private_receipt(backup_receipt),'backup')
        with private_artifact(artifact) as (f,sig):
            if file_sha(f)!=b['artifact_sha256'] or sig[2]!=b['bytes']:raise ValueError('Artifact changed')
        if b['completed_at']>now:raise ValueError('Future evidence')
        result.update(integrity='verified',backup={k:b[k] for k in ('completed_at','artifact_sha256','bytes','tables','rows')})
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        result['integrity']='failed';return result
    if restore_receipt is not None:
        try:
            r=validate_receipt(private_receipt(restore_receipt),'restore')
            import re
            if r['completed_at']>now or not isinstance(r.get('artifact_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',r['artifact_sha256']):
                raise ValueError('Invalid restore evidence')
            if r['artifact_sha256']!=b['artifact_sha256']:
                result['restore']={'state':'other_artifact','completed_at':r['completed_at'],'artifact_sha256':r['artifact_sha256']}
            else:
                if any(r[k]!=b[k] for k in ('bytes','tables','rows')) or r['started_at']<b['completed_at']:raise ValueError('Restore summary mismatch')
                result['restore']={'state':'verified','completed_at':r['completed_at'],'artifact_sha256':r['artifact_sha256']}
        except (OSError,ValueError,TypeError,KeyError,RecursionError):
            result['restore']={'state':'unverified','completed_at':None}
    return result


def read_health(path,now,*,backup_hours=24,restore_days=30):
    out={'state':'unavailable','checked_at':None,'scope':'management_only','backup':None,'restore':None,
         'coverage':{'management_database':'unknown','game_database':'not_covered','configuration':'not_covered','pvf_and_assets':'not_covered'},
         'policy':{'backup_hours':backup_hours,'restore_days':restore_days,'evidence_max_age_hours':24}}
    try:
        d=read_json(path)
        if d.get('version')!=1 or d.get('scope')!='management_only' or not finite(d.get('checked_at')) or d['checked_at']>now:
            raise ValueError('Invalid evidence')
        out['checked_at']=d['checked_at']
        if now-d['checked_at']>86400:out['state']='stale';return out
        if d.get('integrity')=='failed':out['state']='integrity_failed';return out
        if d.get('integrity')!='verified':return out
        b=d['backup']
        if not isinstance(b,dict) or not finite(b.get('completed_at')) or b['completed_at']>now:raise ValueError('Invalid timestamp')
        for key in ('bytes','tables','rows'):
            if type(b.get(key)) is not int or b[key]<0:raise ValueError('Invalid summary')
        if not 1<=b['tables']<=64 or not 0<b['bytes']<=MAX_ARTIFACT:raise ValueError('Invalid artifact limits')
        import re
        if not isinstance(b.get('artifact_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',b['artifact_sha256']):raise ValueError('Invalid digest')
        out['backup']={k:b[k] for k in ('completed_at','artifact_sha256','bytes','tables','rows')}
        out['backup']['state']='recent' if now-b['completed_at']<=backup_hours*3600 else 'overdue'
        r=d.get('restore')
        out['restore']={'state':'not_recorded','completed_at':None}
        if r is not None:
            if not isinstance(r,dict) or r.get('state') not in ('verified','unverified','other_artifact'):raise ValueError('Invalid restore state')
            out['restore']['state']='unverified'
            if r['state']=='other_artifact':
                if not finite(r.get('completed_at')) or r['completed_at']>now or not isinstance(r.get('artifact_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',r['artifact_sha256']):raise ValueError('Invalid older restore evidence')
                out['restore']={'state':'other_artifact','completed_at':r['completed_at'],'artifact_sha256':r['artifact_sha256']}
            if r['state']=='verified':
                if not finite(r.get('completed_at')) or not b['completed_at']<=r['completed_at']<=now or r.get('artifact_sha256')!=b['artifact_sha256']:raise ValueError('Invalid restore timestamp or binding')
                out['restore']={'state':'recent' if now-r['completed_at']<=restore_days*86400 else 'overdue','completed_at':r['completed_at']}
        out.update(state='ok',coverage={**out['coverage'],'management_database':'checksum_verified'})
        return out
    except (OSError,ValueError,TypeError,KeyError,RecursionError):
        out.update(state='unavailable',backup=None,restore=None);return out
