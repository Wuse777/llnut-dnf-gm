"""Authenticated, bounded owner switches for the independent observer."""
import math

PATH='/dnf-gm/api/v1/internal/observer-policy'
SWITCHES=('health-alerts','backup-alerts','task-alerts')


def validate(value,now=None):
    if not isinstance(value,dict) or set(value)!={'revision','checked_at','enabled'}:
        raise ValueError('Invalid observer policy')
    if type(value['revision']) is not int or not 1<=value['revision']<=2147483647:
        raise ValueError('Invalid policy revision')
    stamp=value['checked_at']
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<0:
        raise ValueError('Invalid policy time')
    if now is not None and not 0<=now-stamp<=60:raise ValueError('Stale policy response')
    enabled=value['enabled']
    if not isinstance(enabled,list) or any(type(v) is not str or v not in SWITCHES for v in enabled) or len(enabled)!=len(set(enabled)):
        raise ValueError('Invalid observer switches')
    return {'revision':value['revision'],'checked_at':stamp,'enabled':sorted(enabled)}


def resolve(cfg,root,now,fetch,*,clock=None):
    from .alerts import read_json,atomic
    cache=root/'policy.json'
    try:previous=validate(read_json(cache))
    except FileNotFoundError:previous=None
    # A corrupt cache must not silently re-enable disabled notifications.
    try:
        response=fetch(cfg)
        current=validate(response,clock() if clock else now)
        if previous and (current['revision']<previous['revision'] or (current['revision']==previous['revision'] and current['enabled']!=previous['enabled'])):
            raise ValueError('Policy revision regressed')
    except (OSError,ValueError,TypeError,KeyError):
        if previous:return previous,'cached'
        return {'revision':None,'checked_at':None,'enabled':['health-alerts']+(['backup-alerts'] if cfg.get('backup_health_enabled') else [])+(['task-alerts'] if cfg.get('task_health_enabled') else [])},'installation'
    atomic(cache,current)
    return current,'live'


def public(value):
    if not isinstance(value,dict) or value.get('source') not in ('live','cached','installation'):
        return None
    data={k:value.get(k) for k in ('revision','checked_at','enabled')}
    try:
        if value['source']=='installation':
            if data['revision'] is not None or data['checked_at'] is not None:return None
            validate({**data,'revision':1,'checked_at':0})
        else:data=validate(data)
    except (ValueError,TypeError):return None
    return {**data,'source':value['source']}
