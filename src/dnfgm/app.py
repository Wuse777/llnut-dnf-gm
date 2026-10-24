from typing import Literal
from pathlib import Path
import re
import time
from fastapi import Path as PathParameter, FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from .config import load_settings
from .db import Database, Busy
from .models import Login, Preview, Confirm, Gift, CatalogPolicyPreview
from .security import COOKIE, Limits, authenticate, new_session, session, digest
from .service import Service

BASE = '/dnf-gm'
API = BASE + '/api/v1'


class Guard:
    """Bound body memory; strict origin for unsafe verbs; no CORS middleware."""
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode().lower():v.decode() for k,v in scope['headers']}
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
                    (b'content-security-policy',b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                ])
            await send(message)
        await self.app(scope, replay, secure_send)


def create_app(settings=None, database=None):
    settings = settings or load_settings()
    db = database or Database(settings)
    service, limits = Service(db,settings), Limits()
    app = FastAPI(title='DNF GM', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(Guard, settings=settings)
    app.state.db, app.state.settings, app.state.service = db,settings,service

    @app.exception_handler(Busy)
    async def busy(request,error):
        return JSONResponse({'detail':'数据库繁忙，请稍后重试'},503)

    @app.exception_handler(Exception)
    async def generic(request,error):
        # Never leak SQL, passwords, filesystem or raw tracebacks into browsers.
        return JSONResponse({'detail':'服务内部异常，请查询原操作结果；不要自动重放写入'},500)

    def user(request, write=False, recent=False):
        csrf = request.headers.get('x-csrf-token','') if write else None
        return session(db,settings,request.cookies.get(COOKIE),csrf,recent)[0]

    @app.get(API+'/health')
    def health():
        with db.connect() as c, c.cursor() as q:
            q.execute('SELECT version FROM dnf_gm.schema_versions ORDER BY version DESC LIMIT 1')
            if not q.fetchone():
                raise HTTPException(503,'管理库迁移未完成')
        return {'ok':True,'version':'0.1.0'}

    @app.get(API+'/auth/methods')
    def methods():
        return {'totp_required':settings.require_totp}

    @app.post(API+'/auth/login')
    def login(data:Login,request:Request,response:Response):
        limits.check('login:global',20)
        limits.check('login:'+(request.client.host if request.client else 'unknown'),5)
        authenticate(db,settings,data.username,data.password,data.code)
        token,csrf = new_session(db,settings)
        # Drop the previous session instead of leaving one per successful login.
        old = request.cookies.get(COOKIE)
        if old:
            with db.connect() as c, c.cursor() as q:
                q.execute('DELETE FROM dnf_gm.sessions WHERE token_hash=%s',(digest(old),))
                c.commit()
        response.set_cookie(COOKIE,token,max_age=28800,httponly=True,secure=settings.public,samesite='strict',path=BASE)
        return {'csrf':csrf,'username':data.username}

    @app.get(API+'/auth/me')
    def me(request:Request):
        _,csrf = session(db,settings,request.cookies.get(COOKIE))
        return {'csrf':csrf,'role':'owner','public':settings.public}

    @app.post(API+'/auth/reauth')
    def reauth(data:Login,request:Request):
        key=user(request,True)
        limits.check('reauth:'+key,5)
        authenticate(db,settings,data.username,data.password,data.code)
        with db.connect() as c, c.cursor() as q:
            q.execute('UPDATE dnf_gm.sessions SET authenticated_at=%s WHERE token_hash=%s',(int(time.time()),key))
            c.commit()
        return {'ok':True}

    @app.post(API+'/auth/logout')
    def logout(request:Request,response:Response):
        key=user(request,True)
        with db.connect() as c, c.cursor() as q:
            q.execute('DELETE FROM dnf_gm.sessions WHERE token_hash=%s',(key,))
            c.commit()
        response.delete_cookie(COOKIE,path=BASE,secure=settings.public,httponly=True,samesite='strict')
        return {'ok':True}

    @app.get(API+'/overview')
    def overview(request:Request):
        user(request)
        return service.overview()

    @app.get(API+'/accounts')
    def accounts(request:Request,q:str=Query('',max_length=80),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.accounts(q,page)

    @app.get(API+'/accounts/{uid}')
    def account(uid:int,request:Request):
        user(request)
        with db.connect() as c,c.cursor() as q:
            return service.account(q,uid)

    @app.get(API+'/online')
    def online(request:Request,page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.accounts('',page,True)

    @app.get(API+'/characters')
    def characters(request:Request,uid:int=Query(0,ge=0),q:str=Query('',max_length=80),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.characters(uid,q,page)

    @app.get(API+'/characters/{charac_no}')
    def character_detail(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        user(request)
        return service.character_detail(charac_no)

    @app.get(API+'/catalog')
    def catalog(request:Request,q:str=Query('',max_length=80),category:str=Query('',max_length=24),page:int=Query(1,ge=1,le=10000),allowed_only:bool=False,state:Literal['','trial','verified','blocked']=''):
        user(request)
        return service.catalog.search(q,category,page,allowed_only,state)

    @app.post(API+'/catalog/policy/preview')
    def policy_preview(data:CatalogPolicyPreview,request:Request):
        key=user(request,True,True)
        limits.check('policy-preview:'+key,12)
        return service.preview_policy(key,data.model_dump())

    @app.get(API+'/gift-templates')
    def templates(request:Request,q:str=Query('',max_length=80),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.templates(q,page)

    @app.post(API+'/gift-templates')
    def new_template(data:Gift,request:Request):
        user(request,True,True)
        return service.save_template(0,data.model_dump())

    @app.put(API+'/gift-templates/{tid}')
    def update_template(tid:int,data:Gift,request:Request):
        user(request,True,True)
        return service.save_template(tid,data.model_dump())

    @app.post(API+'/operations/preview')
    def preview(data:Preview,request:Request):
        key=user(request,True)
        limits.check('preview:'+key,30)
        return service.preview(key,data.model_dump())

    @app.post(API+'/operations/{op}/confirm')
    def confirm(op:str,data:Confirm,request:Request):
        key=user(request,True,True)
        limits.check('confirm:'+key,20)
        if not re.fullmatch('[a-f0-9]{32}',op):
            raise HTTPException(422,'非法操作编号')
        return service.confirm(key,op,data.idempotency_key)

    @app.get(API+'/operations/{op}')
    def operation(op:str,request:Request):
        key=user(request)
        if not re.fullmatch('[a-f0-9]{32}',op):
            raise HTTPException(422,'非法操作编号')
        return service.operation(key,op)

    @app.get(API+'/audit')
    def audit(request:Request,page:int=Query(1,ge=1,le=10000),uid:int=Query(0,ge=0)):
        user(request)
        return service.audit(page,uid)

    # Static Vue build, no production Node/Vite process.
    @app.get(BASE+'/{path:path}')
    def static(path:str):
        if path.startswith('api/'):
            raise HTTPException(404,'接口不存在')
        root=Path(settings.static_dir).resolve() if settings.static_dir else None
        if not root or not root.is_dir():
            raise HTTPException(503,'静态产物尚未构建')
        target=(root/path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(404,'文件不存在')
        if target.is_file():
            return FileResponse(target)
        if path and ('.' in path or path.startswith('assets/')):
            raise HTTPException(404,'文件不存在')
        return FileResponse(root/'index.html')

    return app
