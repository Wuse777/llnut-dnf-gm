import base64
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from threading import Lock
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
import pyotp
from fastapi import HTTPException

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
AUTH_SLOT = Lock()  # Bound concurrent Argon2 work / memory.
COOKIE = 'dnfgm_session'


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def box(secret):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def verify_password(encoded, password):
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


class Limits:
    def __init__(self):
        self.items = OrderedDict()
        self.lock = Lock()

    def check(self, key, max_count=5, window=60):
        t = time.monotonic()
        with self.lock:
            while self.items and next(iter(self.items.values()))[0] < t - window:
                self.items.popitem(last=False)
            start, n = self.items.get(key, (t, 0))
            if t - start >= window:
                start, n = t, 0
            if n >= max_count:
                raise HTTPException(429, '尝试过于频繁，请稍后重试')
            if key not in self.items and len(self.items) >= 4096:
                raise HTTPException(429, '认证队列已满')
            self.items[key] = (start, n + 1)


def verify_factor(q, admin, code, secret):
    if code.startswith('R-'):
        q.execute('UPDATE dnf_gm.recovery_codes SET used_at=UTC_TIMESTAMP() WHERE code_hash=%s AND used_at IS NULL', (digest(code),))
        return q.rowcount == 1
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return False
    totp = pyotp.TOTP(box(secret).decrypt(admin['totp_encrypted'].encode()).decode())
    tick = int(time.time()) // 30
    for t in (tick, tick - 1, tick + 1):
        if t > admin['last_totp'] and hmac.compare_digest(totp.generate_otp(t), code):
            q.execute('UPDATE dnf_gm.admins SET last_totp=%s WHERE id=1 AND last_totp<%s', (t, t))
            return q.rowcount == 1
    return False


def authenticate(db, settings, username, password, code):
    if not AUTH_SLOT.acquire(timeout=1):
        raise HTTPException(429, '认证繁忙')
    try:
        with db.connect() as c:
            with c.cursor() as q:
                q.execute('SELECT id,username,password_hash,totp_encrypted,last_totp FROM dnf_gm.admins WHERE id=1 FOR UPDATE')
                a = q.fetchone()
                # Hash verification runs even for a wrong username.
                if not a or not verify_password(a['password_hash'], password) or not hmac.compare_digest(a['username'], username) or (settings.require_totp and not verify_factor(q, a, code, settings.secret)):
                    c.rollback()
                    raise HTTPException(401, '账号或密码不正确' if not settings.require_totp else '账号、密码或动态验证码不正确')
            c.commit()
            return a['username']
    finally:
        AUTH_SLOT.release()


def new_session(db, settings):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    t = int(time.time())
    with db.connect() as c:
        with c.cursor() as q:
            q.execute('INSERT INTO dnf_gm.sessions(token_hash,csrf_encrypted,created_at,touched_at,authenticated_at,mode) VALUES(%s,%s,%s,%s,%s,%s)',
                      (digest(token), box(settings.secret).encrypt(csrf.encode()).decode(), t, t, t, 'public' if settings.public else 'tunnel'))
        c.commit()
    return token, csrf


def session(db, settings, token, csrf=None, reauth=False):
    if not token or len(token) > 128:
        raise HTTPException(401, '请登录')
    key, t = digest(token), int(time.time())
    with db.connect() as c:
        with c.cursor() as q:
            q.execute('SELECT token_hash,csrf_encrypted,created_at,touched_at,authenticated_at,mode FROM dnf_gm.sessions WHERE token_hash=%s', (key,))
            s = q.fetchone()
            mode = 'public' if settings.public else 'tunnel'
            if not s or s['mode'] != mode or t - s['created_at'] > 28800 or t - s['touched_at'] > 1800:
                raise HTTPException(401, '会话已过期')
            actual_csrf = box(settings.secret).decrypt(s['csrf_encrypted'].encode()).decode()
            if csrf is not None and not hmac.compare_digest(actual_csrf, csrf):
                raise HTTPException(403, 'CSRF 校验失败')
            if reauth and t - s['authenticated_at'] > 300:
                raise HTTPException(403, '请先重新认证，敏感操作认证有效期为5分钟')
            q.execute('UPDATE dnf_gm.sessions SET touched_at=%s WHERE token_hash=%s', (t, key))
        c.commit()
    return key, actual_csrf
