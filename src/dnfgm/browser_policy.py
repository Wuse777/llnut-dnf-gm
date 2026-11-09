"""Nonce-scoped runtime styles and the private application's static entry point."""
from pathlib import Path
import re
import secrets

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response


STYLE_NONCE_MARKER = b'__DNFGM_STYLE_NONCE__'
_NONCE = re.compile(r'[A-Za-z0-9_-]{43}\Z')


def new_style_nonce():
    """Use independent, server-generated nonces; never take one from a request."""
    return secrets.token_urlsafe(32)


def content_security_policy(nonce):
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise ValueError('A server-generated style nonce is required')
    return (
        "default-src 'self'; script-src 'self'; "
        f"style-src 'self' 'nonce-{nonce}'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )


def static_response(static_dir, path, nonce, *, head=False):
    """Serve built assets unchanged; inject the nonce only into the SPA document."""
    if path.startswith('api/'):
        raise HTTPException(404, '接口不存在')
    root = Path(static_dir).resolve() if static_dir else None
    if not root or not root.is_dir():
        raise HTTPException(503, '静态产物尚未构建')
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404, '文件不存在')
    entry = (root / 'index.html').resolve()
    if target.is_file() and target != entry:
        return FileResponse(target)
    if target != entry and path and ('.' in path or path.startswith('assets/')):
        raise HTTPException(404, '文件不存在')
    if not entry.is_relative_to(root) or not entry.is_file():
        raise HTTPException(503, '静态产物尚未构建')
    # Validation is shared with the header so an arbitrary string cannot become HTML.
    content_security_policy(nonce)
    content = entry.read_bytes().replace(STYLE_NONCE_MARKER, nonce.encode('ascii'))
    return Response(
        b'' if head else content,
        media_type='text/html',
        headers={'Content-Length': str(len(content))},
    )


class Guard:
    """Bound body memory; strict origin for unsafe verbs; no CORS middleware."""
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode().lower():v.decode() for k,v in scope['headers']}
        style_nonce = new_style_nonce()
        scope.setdefault('state', {})['style_nonce'] = style_nonce
        host = headers.get('host','')
        from urllib.parse import urlsplit
        allowed_hosts = {urlsplit(o).netloc for o in self.settings.origins}
        if host not in allowed_hosts:
            return await JSONResponse({'detail':'非法Host'},400)(scope,receive,send)
        if scope['method'] not in ('GET','HEAD'):
            if headers.get('origin') not in self.settings.origins:
                return await JSONResponse({'detail':'Origin校验失败'},403)(scope,receive,send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body',b'')
            total += len(body)
            if total > 65536:
                return await JSONResponse({'detail':'请求体过大'},413)(scope,receive,send)
            chunks.append(body)
            if not message.get('more_body'):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type':'http.request','body':b''.join(chunks),'more_body':False}
            return await receive()
        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message.setdefault('headers',[]).extend([
                    (b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),
                    (b'x-frame-options',b'DENY'),(b'referrer-policy',b'no-referrer'),
                    (b'content-security-policy',content_security_policy(style_nonce).encode('ascii')),
                ])
            await send(message)
        await self.app(scope, replay, secure_send)
