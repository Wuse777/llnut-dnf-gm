"""Small stdlib-only contract shared by the application and independent observer.

The probe token authorizes one aggregate read, not admin or game operations.
"""
import math
import re

PROBE_PATH = '/dnf-gm/api/v1/internal/task-health'
FIELDS = {'schema', 'checked_at', 'state', 'issue_count', 'truncated'}


def valid_token(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def summary(snapshot):
    # Explicit projection: never pass task/player IDs, raw errors or payloads.
    return {'schema': 1, 'checked_at': snapshot['checked_at'], 'state': snapshot['state'],
            'issue_count': len(snapshot.get('issues', [])), 'truncated': bool(snapshot.get('truncated', False))}


def validate_summary(value, now):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('Invalid task probe fields')
    stamp = value['checked_at']
    if (type(value['schema']) is not int or value['schema'] != 1
            or type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= now-stamp <= 60
            or value['state'] not in ('clear', 'observing', 'attention', 'unknown')
            or type(value['issue_count']) is not int or not 0 <= value['issue_count'] <= 500
            or type(value['truncated']) is not bool):
        raise ValueError('Invalid task probe evidence')
    if ((value['state'] == 'attention') != (value['issue_count'] > 0)
            or (value['truncated'] and value['state'] not in ('attention', 'unknown'))):
        raise ValueError('Inconsistent task probe evidence')
    return value
