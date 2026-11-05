from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
from pathlib import Path
import re
import time
from fastapi import Path as PathParameter, FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from .config import load_settings
from .db import Database, Busy
from .models import Login, Preview, Confirm, Gift, CatalogPolicyPreview, ItemFavorite, ItemSelection, RewardJob, StartRewardJob, RewardJobControl, UnlockBatchPreview, CleanupPreview, CleanupConfirm
from .item_preferences import ItemPreferences
from .reward_jobs import RewardJobs, JobWorker
from .security import COOKIE, Limits, authenticate, new_session, session, digest
from .service import Service
from .unlock_center import UnlockCenter
from .operations_dashboard import dashboard
from .release_cleanup import ReleaseCleanup
from .native_monitor import NativeMonitor
from .native_operations import NativeOperations
from .inventory_operations import InventoryOperations
from .character_maintenance import CharacterMaintenance, CharacterMaintenancePreview
from .character_rename import CharacterRename, RenamePreview
from .character_rescue import CharacterRescue, RescuePreview
from .character_quests import CharacterQuests
from .quest_operations import QuestOperations,QuestPreview
from .character_progression import CharacterProgression
from .character_skills import CharacterSkills, SkillPointsPreview
from .player_preferences import PlayerPreferences,PlayerTarget,PlayerFavorite
from .backup_schedule import BackupSchedule,BackupPolicy,BackupRequest
from .maintenance_requests import MaintenanceRequests, MaintenancePrepare, MaintenanceConfirm, MaintenanceClose, MaintenanceRecover
from .models import InventoryPreview
from .support_models import ProfileSave, CaseCreate, CaseUpdate, CaseEntry, CaseLink, CaseStatus, Category
from .models import NativePreview, SchedulePreview, ActivateSchedule, ScheduleControl
from .schedules import Schedules, OperationsWorker
from .catalog import snapshot
from .audit_export import export_audit
from .report_stream import ReportStream
from .upgrade_check import UpgradeCheck

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
    from .capability_policy import RuntimeSettings, CapabilityPolicy, PolicyWorker, PolicyUpdate
    settings = RuntimeSettings(settings)
    policy = CapabilityPolicy(db,settings)
    policy.refresh(force=True)
    service, limits = Service(db,settings), Limits()
    jobs = RewardJobs(db,settings,service)
    cleanup = ReleaseCleanup(db,settings)
    native_monitor = NativeMonitor(settings)
    native_ops = NativeOperations(service, native_monitor)
    inventory_ops = InventoryOperations(service)
    character_ops = CharacterMaintenance(service)
    rename_ops = CharacterRename(service)
    rescue_ops = CharacterRescue(service)
    quest_reader = CharacterQuests(service)
    quest_ops = QuestOperations(service)
    progression_reader = CharacterProgression(service)
    skill_ops = CharacterSkills(service)
    player_preferences = PlayerPreferences(db)
    maintenance = MaintenanceRequests(db,settings)
    schedules = Schedules(db, settings, jobs, native_ops)
    from .task_health import TaskHealth, WorkerPulse
    pulse = WorkerPulse()
    task_monitor = TaskHealth(db,settings,pulse,lambda: bool(getattr(app.state,"worker",None) and app.state.worker.thread.is_alive()))
    @asynccontextmanager
    async def lifespan(app):
        worker = JobWorker(PolicyWorker(policy,OperationsWorker(schedules,jobs,settings,pulse)),settings.batch_worker_interval)
        app.state.worker = worker
        if worker: worker.start()
        try: yield
        finally:
            if worker: worker.stop()
    app = FastAPI(title='DNF GM', docs_url=None, redoc_url=None, openapi_url=None,lifespan=lifespan)
    app.state.capability_policy = policy
    app.state.task_health = task_monitor
    app.state.worker = None
    app.state.schedules = schedules
    app.state.reward_jobs = jobs
    app.state.native_monitor = native_monitor
    app.state.native_operations = native_ops
    app.state.inventory_operations = inventory_ops
    app.state.character_maintenance = character_ops
    app.state.character_rename = rename_ops
    app.state.character_rescue = rescue_ops
    app.state.character_skills = skill_ops
    app.state.quest_operations = quest_ops
    app.state.maintenance = maintenance
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
        key=session(db,settings,request.cookies.get(COOKIE),csrf,recent)[0]
        policy.refresh(force=write)
        return key

    @app.get(API+'/health')
    def health():
        with db.connect() as c, c.cursor() as q:
            q.execute('SELECT version FROM dnf_gm.schema_versions WHERE version BETWEEN 1 AND 16')
            versions={row['version'] for row in q.fetchall()}
            if versions != set(range(1,17)):
                raise HTTPException(503,'管理库迁移未完成，需要完成016备份计划迁移及此前迁移')
            from .gameplay_transactions import inspect_protocol
            try:inspect_protocol(q)
            except Exception:raise HTTPException(503,'管理库事务屏障不可核验；不会自动修复或开启维护') from None
        return {'ok':True,'version':'0.3.1'}

    @app.get(API+'/ready')
    def ready():
        live = snapshot(settings)
        if (not live.get('fresh') or not live.get('core_ok')
                or live.get('mem_available_mib', 0) < 256
                or live.get('swap_free_mib', 0) < 1536
                or live.get('disk_free_gib', 0) < 2):
            raise HTTPException(503, '采集或资源状态未就绪')
        return health()

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

    @app.get(API+'/capabilities')
    def capability_report(request:Request):
        key=user(request);limits.check('capabilities:'+key,15)
        from .capabilities import report
        policy.refresh(force=True)
        return {**report(settings,db),'policy':policy.view()}

    @app.post(API+'/capabilities/policy')
    def update_capability_policy(data:PolicyUpdate,request:Request):
        key=user(request,write=True,recent=True);limits.check('capability-policy:'+key,15)
        return policy.update(data.model_dump())

    @app.get(API+'/capabilities/policy/requests/{rid}')
    def capability_receipt(request:Request,rid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('capability-receipt:'+key,60)
        return policy.receipt(rid)

    @app.get(API+'/players/collections')
    def player_collection(request:Request,collection:Literal['recent','favorites']='recent',page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('players-collections:'+key,40)
        return player_preferences.list(collection,page)

    @app.post(API+'/players/visit')
    def player_visit(data:PlayerTarget,request:Request):
        key=user(request,True);limits.check('players-visit:'+key,40)
        return player_preferences.update(data.uid,data.charac_no)

    @app.put(API+'/players/favorite')
    def player_favorite(data:PlayerFavorite,request:Request):
        key=user(request,True);limits.check('players-favorite:'+key,30)
        return player_preferences.update(data.uid,data.charac_no,data.favorite)

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

    @app.get(API+'/online/{uid}/live')
    def live_online(request:Request,uid:int=PathParameter(ge=1,le=4294967295)):
        key=user(request)
        limits.check('native-query:'+key,12)
        limits.check('native-query-global',60)
        # No DB connection is held while waiting on the native UDP response.
        with db.connect() as c,c.cursor() as q:
            q.execute('SELECT UID FROM d_taiwan.accounts WHERE UID=%s',(uid,))
            if not q.fetchone():
                raise HTTPException(404,'账号不存在')
            q.execute('SELECT login_status,m_channel_no AS channel FROM taiwan_login.login_account_3 WHERE m_id=%s',(uid,))
            recorded=q.fetchone()
        return {'uid':uid,'database':{'source':'login_status_table','record':recorded,'observed_at':time.time()},
                'native':native_monitor.query(uid)}

    @app.get(API+'/characters')
    def characters(request:Request,uid:int=Query(0,ge=0),q:str=Query('',max_length=80),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.characters(uid,q,page)

    @app.get(API+'/characters/{charac_no}')
    def character_detail(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        user(request)
        return service.character_detail(charac_no)

    @app.get(API+'/characters/{charac_no}/progression')
    def character_progression(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('character-progression:'+key,30)
        return progression_reader.read(charac_no)

    @app.get(API+'/characters/{charac_no}/quests')
    def character_quests(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647),page:int=Query(1,ge=1,le=600),quest_id:int=Query(0,ge=0,le=65535)):
        key=user(request);limits.check('character-quests:'+key,30)
        return quest_reader.read(charac_no,page,quest_id)

    @app.get(API+'/characters/{charac_no}/quests/search')
    def quest_search(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647),q:str=Query(min_length=1,max_length=80),page:int=Query(1,ge=1,le=3277)):
        key=user(request);limits.check('character-quest-search:'+key,30)
        if not q.strip():raise HTTPException(422,'请填写任务名称或编号')
        return quest_reader.search(charac_no,q.strip(),page)

    @app.get(API+'/characters/{charac_no}/activity')
    def character_activity(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647),
                           before:int=Query(0,ge=0,le=9223372036854775807),include_account:bool=True):
        key=user(request);limits.check('character-activity:'+key,30)
        from .character_activity import activity
        return activity(db,charac_no,before,include_account)

    @app.get(API+'/characters/{charac_no}/unlock-requests')
    def unlock_requests(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        user(request)
        return service.unlock_requests(charac_no)

    @app.get(API+'/native-controls')
    def native_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request)
        limits.check('native-history:'+key,30)
        return native_ops.history(uid,page)

    @app.post(API+'/native-controls/preview')
    def native_preview(data:NativePreview,request:Request):
        key=user(request,True,True)
        limits.check('native-preview:'+key,12)
        return native_ops.preview(key,data.model_dump())

    @app.get(API+'/native-controls/{op}')
    def native_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request)
        limits.check('native-detail:'+key,30)
        return native_ops.detail(op)

    @app.post(API+'/native-controls/{op}/confirm')
    def native_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('native-confirm:'+key,10)
        limits.check('native-confirm-global',30)
        return native_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/native-controls/{op}/cancel-preview')
    def native_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('native-cancel:'+key,12)
        return native_ops.cancel(key,op)

    @app.get(API+'/compatibility')
    def compatibility_overview(request:Request):
        key=user(request);limits.check('upgrade-overview:'+key,15)
        return UpgradeCheck(settings,db).overview()

    @app.get(API+'/compatibility/references')
    def compatibility_references(request:Request,kind:Literal['templates','preferences','policies','schedules','jobs','previews','images','portraits'],fingerprint:str=Query(pattern=r'^[a-f0-9]{64}$'),cursor:str=Query('',max_length=1024)):
        key=user(request);limits.check('upgrade-references:'+key,60)
        return UpgradeCheck(settings,db).references(kind,fingerprint,cursor)

    @app.get(API+'/compatibility/export')
    def compatibility_export(request:Request,fingerprint:str=Query(pattern=r'^[a-f0-9]{64}$')):
        key=user(request);limits.check('upgrade-export:'+key,5)
        return ReportStream(UpgradeCheck(settings,db).export(fingerprint),media_type='application/x-ndjson',headers={'Content-Disposition':'attachment; filename="gm-upgrade-check.ndjson"'})

    @app.get(API+'/economy/summary')
    def economy_summary(request:Request,start:date,end:date,uid:int=Query(0,ge=0,le=2147483647)):
        key=user(request);limits.check('economy-summary:'+key,10)
        return service.economy.summary(start,end,uid)

    @app.get(API+'/economy/operations')
    def economy_operations(request:Request,start:date,end:date,uid:int=Query(0,ge=0,le=2147483647),before:int=Query(0,ge=0,le=9223372036854775807),upper:int=Query(0,ge=0,le=9223372036854775807),large:bool=False,currency_threshold:int=Query(100000,ge=1,le=4294967295),gold_threshold:int=Query(100000000,ge=1,le=1000000000)):
        key=user(request);limits.check('economy-operations:'+key,30)
        return service.economy.operations(start,end,uid,before,upper,large,currency_threshold,gold_threshold)

    @app.get(API+'/economy/backlog')
    def economy_backlog(request:Request,start:date,end:date,uid:int=Query(0,ge=0,le=2147483647)):
        key=user(request);limits.check('economy-backlog:'+key,10)
        return service.economy.backlog(start,end,uid)

    @app.get(API+'/economy/compensation')
    def economy_compensation(request:Request,start:date,end:date,uid:int=Query(0,ge=0,le=2147483647)):
        key=user(request);limits.check('economy-compensation:'+key,20)
        return service.economy.repeated_compensation(start,end,uid)

    @app.get(API+'/economy/export')
    def economy_export(request:Request,start:date,end:date,uid:int=Query(0,ge=0,le=2147483647)):
        key=user(request);limits.check('economy-export:'+key,5)
        return ReportStream(service.economy.export(start,end,uid),media_type='application/x-ndjson',headers={'Content-Disposition':'attachment; filename="gm-reward-report.ndjson"'})

    @app.get(API+'/support/profiles/{uid}')
    def support_profile(request:Request,uid:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('support-read:'+key,90)
        return service.support.profile(uid)

    @app.put(API+'/support/profiles/{uid}')
    def support_profile_save(data:ProfileSave,request:Request,uid:int=PathParameter(ge=1,le=2147483647)):
        key=user(request,True,True);limits.check('support-write:'+key,30)
        return service.support.mutation('player-profile',uid,data.model_dump())

    @app.get(API+'/support/cases')
    def support_cases(request:Request,uid:int=Query(0,ge=0,le=2147483647),status:CaseStatus|Literal['']='',category:Category|Literal['']='',q:str=Query('',max_length=100),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('support-read:'+key,90)
        return service.support.cases(uid,status,category,q,page)

    @app.post(API+'/support/cases')
    def support_create(data:CaseCreate,request:Request):
        key=user(request,True,True);limits.check('support-write:'+key,30)
        return service.support.mutation('case-create',None,data.model_dump())

    @app.get(API+'/support/cases/{cid}')
    def support_case(request:Request,cid:str=PathParameter(pattern=r'^[a-f0-9]{32}$'),event_page:int=Query(1,ge=1,le=10000),link_page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('support-read:'+key,90)
        return service.support.detail(cid,event_page,link_page)

    @app.put(API+'/support/cases/{cid}')
    def support_update(data:CaseUpdate,request:Request,cid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('support-write:'+key,30)
        return service.support.mutation('case-update',cid,data.model_dump())

    @app.post(API+'/support/cases/{cid}/entries')
    def support_comment(data:CaseEntry,request:Request,cid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('support-write:'+key,30)
        return service.support.mutation('case-comment',cid,data.model_dump())

    @app.post(API+'/support/cases/{cid}/links')
    def support_link(data:CaseLink,request:Request,cid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('support-write:'+key,30)
        return service.support.mutation('case-link',cid,data.model_dump())

    @app.get(API+'/support/requests/{rid}')
    def support_result(request:Request,rid:str=PathParameter(pattern=r'^[A-Za-z0-9_-]{16,64}$')):
        key=user(request);limits.check('support-result:'+key,30)
        return service.support.request(rid)

    @app.get(API+'/inventory/characters/{charac_no}/{container}/{slot}')
    def inventory_item(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647),
                       container:Literal['inventory','equipment','warehouse','account_warehouse']='inventory',slot:int=PathParameter(ge=0,le=1023)):
        key=user(request);limits.check('inventory-read:'+key,30)
        return inventory_ops.item(charac_no,container,slot)

    @app.get(API+'/inventory/operations')
    def inventory_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('inventory-history:'+key,30)
        return inventory_ops.history(uid,charac_no,page)

    @app.post(API+'/inventory/preview')
    def inventory_preview(data:InventoryPreview,request:Request):
        key=user(request,True,True);limits.check('inventory-preview:'+key,12)
        return inventory_ops.preview(key,data.model_dump())

    @app.get(API+'/inventory/operations/{op}')
    def inventory_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('inventory-detail:'+key,30)
        return inventory_ops.detail(op)

    @app.post(API+'/inventory/operations/{op}/confirm')
    def inventory_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('inventory-confirm:'+key,10)
        return inventory_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/inventory/operations/{op}/cancel-preview')
    def inventory_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('inventory-cancel:'+key,12)
        return inventory_ops.cancel(op)

    @app.get(API+'/character-maintenance/characters/{charac_no}')
    def character_maintenance_read(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('character-maintenance-read:'+key,30)
        return character_ops.read(charac_no)

    @app.get(API+'/character-maintenance/operations')
    def character_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('character-maintenance-history:'+key,30)
        return character_ops.history(uid,charac_no,page)

    @app.post(API+'/character-maintenance/preview')
    def character_preview(data:CharacterMaintenancePreview,request:Request):
        key=user(request,True,True);limits.check('character-maintenance-preview:'+key,12)
        return character_ops.preview(key,data.model_dump())

    @app.get(API+'/character-maintenance/operations/{op}')
    def character_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('character-maintenance-detail:'+key,30)
        return character_ops.detail(op)

    @app.post(API+'/character-maintenance/operations/{op}/confirm')
    def character_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-maintenance-confirm:'+key,10)
        return character_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/character-maintenance/operations/{op}/cancel-preview')
    def character_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-maintenance-cancel:'+key,12)
        return character_ops.cancel(op)

    @app.get(API+'/character-skills/characters/{charac_no}')
    def character_skills_read(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('character-skills-read:'+key,30)
        return skill_ops.read(charac_no)

    @app.get(API+'/character-skills/operations')
    def skills_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('character-skills-history:'+key,30)
        return skill_ops.history(uid,charac_no,page)

    @app.post(API+'/character-skills/preview')
    def skills_preview(data:SkillPointsPreview,request:Request):
        key=user(request,True,True);limits.check('character-skills-preview:'+key,12)
        return skill_ops.preview(key,data.model_dump())

    @app.get(API+'/character-skills/operations/{op}')
    def skills_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('character-skills-detail:'+key,30)
        return skill_ops.detail(op)

    @app.post(API+'/character-skills/operations/{op}/confirm')
    def skills_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-skills-confirm:'+key,10)
        return skill_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/character-skills/operations/{op}/cancel-preview')
    def skills_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-skills-cancel:'+key,12)
        return skill_ops.cancel(op)

    @app.get(API+'/character-renames/characters/{charac_no}')
    def rename_maintenance_read(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('character-renames-read:'+key,30)
        return rename_ops.read(charac_no)

    @app.get(API+'/character-renames/operations')
    def rename_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('character-renames-history:'+key,30)
        return rename_ops.history(uid,charac_no,page)

    @app.post(API+'/character-renames/preview')
    def rename_preview(data:RenamePreview,request:Request):
        key=user(request,True,True);limits.check('character-renames-preview:'+key,12)
        return rename_ops.preview(key,data.model_dump())

    @app.get(API+'/character-renames/operations/{op}')
    def rename_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('character-renames-detail:'+key,30)
        return rename_ops.detail(op)

    @app.post(API+'/character-renames/operations/{op}/confirm')
    def rename_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-renames-confirm:'+key,10)
        return rename_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/character-renames/operations/{op}/cancel-preview')
    def rename_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-renames-cancel:'+key,12)
        return rename_ops.cancel(op)

    @app.get(API+'/character-rescues/characters/{charac_no}')
    def rescue_maintenance_read(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('character-rescues-read:'+key,30)
        return rescue_ops.read(charac_no)

    @app.get(API+'/character-rescues/operations')
    def rescue_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('character-rescues-history:'+key,30)
        return rescue_ops.history(uid,charac_no,page)

    @app.post(API+'/character-rescues/preview')
    def rescue_preview(data:RescuePreview,request:Request):
        key=user(request,True,True);limits.check('character-rescues-preview:'+key,12)
        return rescue_ops.preview(key,data.model_dump())

    @app.get(API+'/character-rescues/operations/{op}')
    def rescue_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('character-rescues-detail:'+key,30)
        return rescue_ops.detail(op)

    @app.post(API+'/character-rescues/operations/{op}/confirm')
    def rescue_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-rescues-confirm:'+key,10)
        return rescue_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/character-rescues/operations/{op}/cancel-preview')
    def rescue_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('character-rescues-cancel:'+key,12)
        return rescue_ops.cancel(op)

    @app.get(API+'/quest-repairs/characters/{charac_no}')
    def quest_repair_maintenance_read(request:Request,charac_no:int=PathParameter(ge=1,le=2147483647)):
        key=user(request);limits.check('quest-repairs-read:'+key,30)
        return quest_ops.read(charac_no)

    @app.get(API+'/quest-repairs/operations')
    def quest_repair_history(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('quest-repairs-history:'+key,30)
        return quest_ops.history(uid,charac_no,page)

    @app.post(API+'/quest-repairs/preview')
    def quest_repair_preview(data:QuestPreview,request:Request):
        key=user(request,True,True);limits.check('quest-repairs-preview:'+key,12)
        return quest_ops.preview(key,data.model_dump())

    @app.get(API+'/quest-repairs/operations/{op}')
    def quest_repair_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('quest-repairs-detail:'+key,30)
        return quest_ops.detail(op)

    @app.post(API+'/quest-repairs/operations/{op}/confirm')
    def quest_repair_confirm(data:Confirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('quest-repairs-confirm:'+key,10)
        return quest_ops.confirm(key,op,data.idempotency_key)

    @app.post(API+'/quest-repairs/operations/{op}/cancel-preview')
    def quest_repair_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('quest-repairs-cancel:'+key,12)
        return quest_ops.cancel(op)

    @app.get(API+'/maintenance')
    def maintenance_status(request:Request):
        key=user(request);limits.check('maintenance-status:'+key,30)
        return maintenance.status()

    @app.get(API+'/maintenance/requests')
    def maintenance_history(request:Request,cursor:str=Query('',max_length=50)):
        key=user(request);limits.check('maintenance-history:'+key,30)
        return maintenance.history(cursor)

    @app.post(API+'/maintenance/requests')
    def maintenance_prepare(data:MaintenancePrepare,request:Request):
        key=user(request,True,True);limits.check('maintenance-prepare:'+key,6)
        return maintenance.prepare(key,data.model_dump())

    @app.get(API+'/maintenance/requests/{op}')
    def maintenance_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request);limits.check('maintenance-detail:'+key,40)
        return maintenance.detail(op)

    @app.post(API+'/maintenance/requests/{op}/confirm')
    def maintenance_confirm(data:MaintenanceConfirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('maintenance-confirm:'+key,6)
        return maintenance.confirm(key,op,data.model_dump())

    @app.post(API+'/maintenance/requests/{op}/close')
    def maintenance_close(data:MaintenanceClose,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('maintenance-close:'+key,6)
        return maintenance.close(key,op,data.model_dump())

    @app.post(API+'/maintenance/requests/{op}/recover')
    def maintenance_recover(data:MaintenanceRecover,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('maintenance-recover:'+key,6)
        return maintenance.recover(key,op,data.model_dump())

    @app.post(API+'/maintenance/requests/{op}/cancel')
    def maintenance_cancel(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('maintenance-cancel:'+key,10)
        return maintenance.cancel(op)

    @app.post(API+'/maintenance/requests/{op}/observe')
    def maintenance_observe(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True);limits.check('maintenance-observe:'+key,6)
        return maintenance.observe(op)

    @app.post(API+'/maintenance/requests/{op}/dispatch')
    def maintenance_dispatch(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True);limits.check('maintenance-dispatch:'+key,10)
        return maintenance.dispatch(op)

    @app.get(API+'/release-cleanups')
    def cleanup_candidates(request:Request):
        user(request)
        return cleanup.candidates()

    @app.post(API+'/release-cleanups/preview')
    def cleanup_preview(data:CleanupPreview,request:Request):
        key=user(request,True,True)
        limits.check('cleanup-preview:'+key,10)
        return cleanup.preview(key,data.names,data.reason)

    @app.get(API+'/release-cleanups/{op}')
    def cleanup_detail(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        user(request)
        return cleanup.detail(op)

    @app.post(API+'/release-cleanups/{op}/confirm')
    def cleanup_confirm(data:CleanupConfirm,request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('cleanup-confirm:'+key,10)
        return cleanup.confirm(key,op,data.idempotency_key)

    @app.post(API+'/release-cleanups/{op}/cancel-preview')
    def cleanup_cancel_preview(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('cleanup-cancel:'+key,10)
        return cleanup.cancel_preview(op)

    @app.post(API+'/release-cleanups/{op}/dispatch')
    def cleanup_dispatch(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('cleanup-dispatch:'+key,10)
        return cleanup.dispatch(op)

    def observer_auth(request:Request):
        import hmac
        from .task_probe import valid_token
        # Uvicorn is deployed with --no-proxy-headers. Never trust forwarded IPs;
        # the nginx internal-prefix deny is an additional, not sole, barrier.
        token = settings.task_probe_token
        if (not valid_token(token) or not request.client or request.client.host not in ('127.0.0.1','::1')
                or request.query_params or any(h in request.headers for h in ('origin','forwarded','x-forwarded-for'))):
            raise HTTPException(404,'Not found')
        limits.check('task-probe:global',30)
        authorization = request.headers.get('authorization','')
        if not hmac.compare_digest(authorization.encode(),('Bearer '+token).encode()):
            raise HTTPException(404,'Not found')

    @app.get(API+'/internal/task-health')
    def task_health_probe(request:Request):
        observer_auth(request)
        from .task_probe import summary
        return summary(task_monitor.read())

    @app.get(API+'/internal/observer-policy')
    def observer_policy_probe(request:Request):
        observer_auth(request)
        from .observer_policy import SWITCHES
        policy.refresh()
        current=policy.view()
        if current['state']!='managed':raise HTTPException(503,'Managed observer policy unavailable')
        return {'revision':current['revision'],'checked_at':time.time(),'enabled':[k for k in SWITCHES if k in current['enabled']]}

    @app.get(API+'/task-health')
    def task_health(request:Request):
        key=user(request)
        limits.check('task-health:'+key,15)
        return task_monitor.read()

    backups=BackupSchedule(db,settings)

    @app.get(API+'/backups')
    def backup_schedule(request:Request,page:int=Query(1,ge=1,le=10000)):
        key=user(request);limits.check('backup-schedule:'+key,30)
        return backups.view(page)

    @app.post(API+'/backups/policy')
    def backup_policy(request:Request,data:BackupPolicy):
        key=user(request,True,True);limits.check('backup-policy:'+key,10)
        return backups.update(data.model_dump())

    @app.get(API+'/backups/policy/requests/{request_id}')
    def backup_policy_result(request:Request,request_id:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        user(request)
        return backups.policy_result(request_id)

    @app.post(API+'/backups/runs')
    def request_backup(request:Request,data:BackupRequest):
        key=user(request,True,True);limits.check('backup-request:'+key,6)
        return backups.request(data.model_dump())

    @app.get(API+'/backups/runs/{run_id}')
    def backup_result(request:Request,run_id:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        user(request)
        return backups.detail(run_id)

    @app.get(API+'/backup-health')
    def backup_health(request:Request):
        key=user(request)
        limits.check('backup-health:'+key,30)
        from .backup_health import read_health
        return read_health(settings.backup_health_file,time.time())

    @app.get(API+'/alerts')
    def alerts(request:Request):
        key=user(request)
        limits.check('alerts:'+key,30)
        from .alerts import read_report
        return read_report(settings.alert_file,time.time())

    @app.get(API+'/operations-dashboard')
    def operations_dashboard(request:Request,window:Literal['24h','7d']='24h',before:int=Query(0,ge=0,le=9223372036854775807)):
        key=user(request)
        limits.check('operations-dashboard:'+key,30)
        return dashboard(settings,db,window,before)

    @app.get(API+'/unlock-requests')
    def unlock_list(request:Request,q:str=Query('',max_length=80),uid:int=Query(0,ge=0,le=2147483647),after:int=Query(0,ge=0,le=2147483647),state:Literal['all','pending','expired','unsupported']='pending'):
        user(request)
        return UnlockCenter(service).list(q,uid,after,state)

    @app.post(API+'/unlock-batches/preview')
    def unlock_batch(data:UnlockBatchPreview,request:Request):
        key=user(request,write=True,recent=True)
        limits.check('unlock-batch-preview:'+key,12)
        return UnlockCenter(service).preview(key,data.model_dump())

    @app.get(API+'/catalog')
    def catalog(request:Request,q:str=Query('',max_length=80),category:str=Query('',max_length=24),page:int=Query(1,ge=1,le=10000),allowed_only:bool=False,state:Literal['','trial','verified','blocked']=''):
        user(request)
        return service.catalog.search(q,category,page,allowed_only,state)

    @app.get(API+'/catalog/enchantments')
    def enchantments(request:Request,q:str=Query('',max_length=80),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.catalog.enchantments(q,page)

    preferences = ItemPreferences(db,service.catalog)

    @app.get(API+'/catalog/collections')
    def item_collection(request:Request,collection:Literal['favorites','recent']='favorites',page:int=Query(1,ge=1,le=10000)):
        user(request)
        return preferences.list(collection,page)

    @app.put(API+'/catalog/{item_id}/favorite')
    def favorite_item(data:ItemFavorite,request:Request,item_id:int=PathParameter(ge=1,le=4294967295)):
        key=user(request,True)
        limits.check('item-preference:'+key,60)
        return preferences.update(item_id,data.pvf_sha256,data.favorite)

    @app.post(API+'/catalog/{item_id}/selection')
    def select_item(data:ItemSelection,request:Request,item_id:int=PathParameter(ge=1,le=4294967295)):
        key=user(request,True)
        limits.check('item-selection:'+key,120)
        return preferences.update(item_id,data.pvf_sha256)

    @app.post(API+'/catalog/policy/preview')
    def policy_preview(data:CatalogPolicyPreview,request:Request):
        key=user(request,True,True)
        limits.check('policy-preview:'+key,12)
        return service.preview_policy(key,data.model_dump())

    @app.get(API+'/assets/status')
    def asset_status(request:Request):
        user(request)
        return service.catalog.assets.status(settings.pvf_sha256)

    @app.get(API+'/assets/{pvf_sha}/{image_hash}.png')
    def asset_image(request:Request,pvf_sha:str=PathParameter(pattern=r'^[a-f0-9]{64}$'),image_hash:str=PathParameter(pattern=r'^[a-f0-9]{64}$')):
        user(request)
        return Response(service.catalog.assets.png(pvf_sha,image_hash),media_type='image/png')

    @app.get(API+'/gift-templates')
    def templates(request:Request,q:str=Query('',max_length=80),page:int=Query(1,ge=1,le=10000),category:str=Query('',max_length=32)):
        user(request)
        return service.templates(q,page,category)

    @app.get(API+'/gift-templates/{tid}/versions')
    def template_versions(request:Request,tid:int=PathParameter(ge=1),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.template_versions(tid,page)

    @app.post(API+'/gift-templates')
    def new_template(data:Gift,request:Request):
        user(request,True,True)
        return service.save_template(0,data.model_dump())

    @app.put(API+'/gift-templates/{tid}')
    def update_template(tid:int,data:Gift,request:Request):
        user(request,True,True)
        return service.save_template(tid,data.model_dump())

    @app.get(API+'/schedules')
    def schedule_list(request:Request,page:int=Query(1,ge=1,le=10000)):
        user(request)
        return schedules.list(page)

    @app.post(API+'/schedules/preview')
    def schedule_preview(data:SchedulePreview,request:Request):
        key=user(request,True,True)
        limits.check('schedule-preview:'+key,6)
        return schedules.preview(key,data.model_dump())

    @app.get(API+'/schedules/{sid}')
    def schedule_detail(request:Request,sid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        user(request)
        return schedules.detail(sid)

    @app.get(API+'/schedules/{sid}/runs')
    def schedule_runs(request:Request,sid:str=PathParameter(pattern=r'^[a-f0-9]{32}$'),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return schedules.runs(sid,page)

    @app.post(API+'/schedules/{sid}/activate')
    def schedule_activate(data:ActivateSchedule,request:Request,sid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('schedule-activate:'+key,10)
        return schedules.activate(key,sid,data.model_dump())

    @app.post(API+'/schedules/{sid}/control')
    def schedule_control(data:ScheduleControl,request:Request,sid:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('schedule-control:'+key,30)
        return schedules.control(sid,data.action,data.acknowledge_attention)

    @app.get(API+'/reward-jobs')
    def reward_jobs(request:Request,page:int=Query(1,ge=1,le=10000)):
        user(request)
        return jobs.list(page)

    @app.post(API+'/reward-jobs/preview')
    def reward_job_preview(data:RewardJob,request:Request):
        key=user(request,True,True)
        limits.check('job-preview:'+key,6)
        return jobs.preview(key,data.model_dump())

    @app.get(API+'/reward-jobs/{job_id}')
    def reward_job_detail(request:Request,job_id:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        user(request)
        return jobs.detail(job_id)

    @app.get(API+'/reward-jobs/{job_id}/targets')
    def reward_job_targets(request:Request,job_id:str=PathParameter(pattern=r'^[a-f0-9]{32}$'),after:int=Query(0,ge=0,le=4294967295)):
        user(request)
        return jobs.targets(job_id,after)

    @app.post(API+'/reward-jobs/{job_id}/start')
    def reward_job_start(data:StartRewardJob,request:Request,job_id:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('job-start:'+key,10)
        return jobs.start(key,job_id,data.model_dump())

    @app.post(API+'/reward-jobs/{job_id}/control')
    def reward_job_control(data:RewardJobControl,request:Request,job_id:str=PathParameter(pattern=r'^[a-f0-9]{32}$')):
        key=user(request,True,True)
        limits.check('job-control:'+key,30)
        return jobs.control(job_id,data.action)

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
        result=service.operation(key,op)
        if result['action']=='maintenance':
            result['maintenance']=maintenance.detail(op)
            result['request']={'action':'maintenance','reason':result['maintenance']['reason']}
        if result['action']=='cleanup-release':
            result['cleanup']=cleanup.detail(op)
            # Do not expose worker signing tickets through generic audit lookup.
            result['request']={'action':'cleanup-release','reason':result['preview']['reason'],'items':result['preview']['items']}
        return result

    @app.get(API+'/mail-center')
    def mail_center(request:Request,uid:int=Query(0,ge=0,le=2147483647),charac_no:int=Query(0,ge=0,le=2147483647),operation_id:str=Query('',pattern=r'^(?:[a-f0-9]{32})?$'),page:int=Query(1,ge=1,le=10000)):
        user(request)
        return service.mail_center.list(uid,charac_no,operation_id,page)

    @app.get(API+'/mail-center/{op}')
    def mail_details(request:Request,op:str=PathParameter(pattern=r'^[a-f0-9]{32}$'),after:int=Query(0,ge=0,le=9223372036854775807)):
        user(request)
        return service.mail_center.details(op,after)

    @app.get(API+'/audit/export')
    def audit_export(request:Request,uid:int=Query(0,ge=0,le=2147483647)):
        key=user(request)
        limits.check('audit-export:'+key,3)
        return StreamingResponse(export_audit(db,uid),media_type='application/x-ndjson',headers={'Content-Disposition':'attachment; filename="dnf-gm-audit.ndjson"'})

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
