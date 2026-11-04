#!/usr/bin/env python3
"""One bounded observer pass, invoked by an independent unprivileged timer."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from dnfgm.alerts import atomic, delivery, new_state, observations, observe, public_view, read_json, validate_state

CONFIG = Path('/etc/dnf-gm-alerts.json')
ROOT = Path('/var/lib/dnf-gm/alerts')
STATUS = Path('/run/dnf-gm/status.json')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_config(cfg):
    if set(cfg) - {'health_host', 'thresholds', 'webhook_url', 'webhook_token'}:
        raise ValueError('Unknown notification configuration')
    host = cfg.get('health_host')
    if not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9.-]+(?::[0-9]{1,5})?', host):
        raise ValueError('Explicit health Host header required')
    thresholds = cfg.get('thresholds', {})
    if set(thresholds) != {'memory', 'swap', 'disk'}:
        raise ValueError('Explicit thresholds required')
    for key, floor, ceiling in [('memory', 256, 1048576), ('swap', 1536, 1048576), ('disk', 2, 1048576)]:
        if type(thresholds[key]) is not int or not floor <= thresholds[key] <= ceiling:
            raise ValueError('Invalid notification threshold')
    url, token = cfg.get('webhook_url', ''), cfg.get('webhook_token', '')
    if not isinstance(url, str) or len(url) > 2048 or not isinstance(token, str) or len(token) > 4096:
        raise ValueError('Invalid notification destination')
    if url:
        u = urlsplit(url)
        if (u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment
                or any(ord(c) < 33 for c in url) or (u.port is not None and u.port != 443)):
            raise ValueError('Webhook requires fixed HTTPS port 443; credentials use token')
        try:
            if not ipaddress.ip_address(u.hostname).is_global:
                raise ValueError('Literal webhook IP must be public')
        except ValueError as e:
            # A DNS name is an explicit operator trust decision, not browser input.
            if re.fullmatch(r'[0-9.:]+', u.hostname):
                raise e
        if not re.fullmatch(r'[A-Za-z0-9.-]+', u.hostname):
            raise ValueError('Invalid webhook host')
    if any(ord(c) < 33 or ord(c) > 126 for c in token) or (token and not url):
        raise ValueError('Invalid webhook token')
    return cfg


def private_config(path=CONFIG):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o027:
        raise ValueError('Notification config must be root-owned, private and not group writable')
    return validate_config(read_json(path))


def health(cfg):
    req = Request('http://127.0.0.1:8765/dnf-gm/api/v1/health', headers={'Host': cfg['health_host']})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3) as r:
            body = r.read(8193)
            return r.status == 200 and len(body) <= 8192 and json.loads(body).get('ok') is True
    except Exception:
        return False


def notify(cfg, body):
    headers = {'Content-Type': 'application/json', 'User-Agent': 'dnf-gm-health/1'}
    if cfg.get('webhook_token'):
        headers['Authorization'] = 'Bearer ' + cfg['webhook_token']
    req = Request(cfg['webhook_url'], data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method='POST')
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3) as r:
        return 200 <= r.status < 300  # Never read/log arbitrary receiver response bodies.


def run_once(cfg, *, root=ROOT, status_path=STATUS, clock=time.time, probe=health, send=notify):
    # The installer owns this directory and grants write access only to the
    # observer account. Do not silently create directories from untrusted paths.
    fd = os.open(root / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            state = validate_state(read_json(root / 'private.json'))
        except FileNotFoundError:
            # A pre-existing public report means state loss, not first install.
            if (root / 'public.json').exists():
                raise ValueError('Deduplication state missing')
            state = new_state()
        try:
            status = read_json(status_path)
        except (OSError, ValueError, TypeError):
            status = None
        gm_ok = probe(cfg)
        now = clock()
        observe(state, observations(status, gm_ok, now, cfg['thresholds']), now)
        def persist(value):
            atomic(root / 'private.json', value)
            atomic(root / 'public.json', public_view(value, now), mode=0o644)
        delivery(state, now, bool(cfg.get('webhook_url')), lambda body: send(cfg, body), persist)
        return public_view(state, now)


if __name__ == '__main__':
    try:
        run_once(private_config())
    except Exception:
        # Deliberately exclude exception text/traceback (which may contain URL).
        print('{"event":"alert_observer_failed","action":"inspect_private_config_and_state"}', flush=True)
        raise SystemExit(1)
