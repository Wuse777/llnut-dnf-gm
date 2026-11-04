"""Single-admin player notes and case history. No game writes or arbitrary SQL.

Management mutations and their result receipts/audits commit together. Reward
association is called inside the existing reward transaction; creating a draft
never grants rewards, bypasses write checks, or marks a case resolved.
"""
import hashlib
import json
import time
import uuid
import pymysql
from fastapi import HTTPException
from .service import one,dump,character

TABLES=('player_profiles','support_cases','support_events','support_links','support_requests','audit')
REWARDS=('currency','mail','reward')

class SupportDesk:
    def __init__(self,db):self.db=db

    @staticmethod
    def engines(q):
        q.execute('SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=\'dnf_gm\' AND TABLE_NAME IN ('+','.join(['%s']*len(TABLES))+')',TABLES)
        rows=q.fetchall()
        if {r['TABLE_NAME'] for r in rows}!=set(TABLES) or any(r['ENGINE']!='InnoDB' for r in rows):raise HTTPException(503,'问题工作台迁移或事务引擎未就绪')

    @staticmethod
    def target(q,uid,charac_no=None):
        account=one(q,'SELECT UID AS uid,accountname FROM d_taiwan.accounts WHERE UID=%s',(uid,))
        if not account:raise HTTPException(404,'账号不存在')
        if charac_no:
            row=one(q,'SELECT m_id AS uid,charac_no,charac_name,delete_flag,CAST(CONVERT(charac_name USING latin1) AS BINARY) AS client_name_bytes FROM taiwan_cain.charac_info WHERE charac_no=%s',(charac_no,))
            if not row or row['uid']!=uid:raise HTTPException(409,'角色不属于此账号')
            account['character']=character(row)
        return account

    def profile(self,uid):
        with self.db.connect() as c,c.cursor() as q:
            target=self.target(q,uid)
            row=one(q,'SELECT * FROM dnf_gm.player_profiles WHERE uid=%s',(uid,))
        return {'target':target,**(self.profile_public(row) if row else {'uid':uid,'revision':0,'notes':'','tags':[],'updated_at':None})}

    @staticmethod
    def profile_public(row):
        return {k:row[k] for k in ('uid','revision','notes','updated_at')}|{'tags':json.loads(row['tags_json'])}

    @staticmethod
    def case(q,cid,lock=False):
        row=one(q,'SELECT * FROM dnf_gm.support_cases WHERE case_id=%s'+(' FOR UPDATE' if lock else ''),(cid,))
        if not row:raise HTTPException(404,'问题记录不存在')
        return row

    @staticmethod
    def public(row):
        return {k:v for k,v in row.items() if k!='target_json'}|{'target':json.loads(row['target_json'])}

    def cases(self,uid=0,status='',category='',text='',page=1):
        terms=[];args=[]
        for col,value in (('uid',uid),('status',status),('category',category)):
            if value:terms.append(col+'=%s');args.append(value)
        if text:
            terms.append('(case_id=%s OR title LIKE %s)');args.extend([text,'%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'])
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT * FROM dnf_gm.support_cases'+(' WHERE '+' AND '.join(terms) if terms else '')+' ORDER BY updated_at DESC,case_id DESC LIMIT 21 OFFSET %s',(*args,(page-1)*20));rows=q.fetchall()
        return {'items':[self.public(r) for r in rows[:20]],'has_more':len(rows)>20,'page':page}

    def detail(self,cid,event_page=1,link_page=1):
        with self.db.connect() as c,c.cursor() as q:
            row=self.case(q,cid)
            q.execute('SELECT revision,kind,note,details_json,created_at FROM dnf_gm.support_events WHERE case_id=%s ORDER BY revision DESC LIMIT 21 OFFSET %s',(cid,(event_page-1)*20));events=q.fetchall()
            q.execute('SELECT l.operation_id,l.relation,l.created_at,o.action,o.status FROM dnf_gm.support_links l LEFT JOIN dnf_gm.operations o ON o.operation_id=l.operation_id WHERE l.case_id=%s ORDER BY l.created_at DESC,l.operation_id DESC LIMIT 21 OFFSET %s',(cid,(link_page-1)*20));links=q.fetchall()
        return {'case':self.public(row),'events':[{k:v for k,v in e.items() if k!='details_json'}|{'details':json.loads(e['details_json'])} for e in events[:20]],'events_has_more':len(events)>20,'links':links[:20],'links_has_more':len(links)>20}

    @staticmethod
    def expected(row,data):
        if row['revision']!=data['expected_revision']:raise HTTPException(409,'记录已变化，请刷新后重新编辑，未覆盖其他修改')
        if row['revision']>=2147483647:raise HTTPException(409,'记录版本已达到上限，需维护处理')

    @staticmethod
    def event(q,row,kind,note,details,increment=True):
        revision=row['revision']+(1 if increment else 0);now=int(time.time())
        q.execute('INSERT INTO dnf_gm.support_events(case_id,revision,kind,note,details_json,created_at) VALUES(%s,%s,%s,%s,%s,%s)',(row['case_id'],revision,kind,note,dump(details),now))
        if increment:q.execute('UPDATE dnf_gm.support_cases SET revision=%s,updated_at=%s WHERE case_id=%s',(revision,now,row['case_id']))
        return revision

    def request(self,key):
        with self.db.connect() as c,c.cursor() as q:
            row=one(q,'SELECT result_json FROM dnf_gm.support_requests WHERE request_key=%s',(key,))
        if not row:raise HTTPException(404,'暂未查到提交记录，不代表请求一定未执行；请保留原编号核对')
        return json.loads(row['result_json'])

    def mutation(self,kind,target,data):
        key=data['idempotency_key'];payload={k:v for k,v in data.items() if k!='idempotency_key'}
        fingerprint=hashlib.sha256(dump({'kind':kind,'target':target,'payload':payload}).encode()).hexdigest()
        committing=False
        try:
            with self.db.connect() as c,c.cursor() as q:
                self.engines(q)
                old=one(q,'SELECT fingerprint,result_json FROM dnf_gm.support_requests WHERE request_key=%s',(key,))
                if old:
                    if old['fingerprint']!=fingerprint:raise HTTPException(409,'请求编号已经用于不同内容')
                    return json.loads(old['result_json'])
                # Unique insert arbitrates concurrent keys; receipt is never visible
                # without the entire mutation and audit committing in this transaction.
                q.execute('INSERT INTO dnf_gm.support_requests(request_key,fingerprint,result_json,created_at) VALUES(%s,%s,\'{}\',%s)',(key,fingerprint,int(time.time())))
                result,uid,details=self.apply(q,kind,target,payload)
                result.update(request_id=key,kind=kind,uid=uid,state='management_committed')
                q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner',%s,%s,'玩家问题工作台记录',%s,%s)",('support:'+uuid.uuid4().hex,kind,uid,dump({'target':target,**payload,'details':details}),dump(result)))
                q.execute('UPDATE dnf_gm.support_requests SET result_json=%s WHERE request_key=%s',(dump(result),key))
                committing=True;c.commit();return result
        except Exception as error:
            if committing:raise HTTPException(503,'管理记录提交结果待确认，请按原请求编号查询，不要重复创建') from None
            if isinstance(error,pymysql.OperationalError) and error.args[0] in (1205,1213):
                raise HTTPException(409,'管理记录正在变化，请刷新核对，不自动重放保存') from None
            if isinstance(error,pymysql.IntegrityError):
                with self.db.connect() as c,c.cursor() as q:
                    old=one(q,'SELECT fingerprint,result_json FROM dnf_gm.support_requests WHERE request_key=%s',(key,))
                if old and old['fingerprint']==fingerprint:return json.loads(old['result_json'])
                raise HTTPException(409,'请求编号冲突或记录已变化，请核对原请求') from None
            raise

    def apply(self,q,kind,target,data):
        now=int(time.time())
        if kind=='player-profile':
            self.target(q,target)
            old=one(q,'SELECT * FROM dnf_gm.player_profiles WHERE uid=%s FOR UPDATE',(target,))
            before=self.profile_public(old) if old else {'uid':target,'revision':0,'notes':'','tags':[],'updated_at':None}
            self.expected(before,data);revision=before['revision']+1
            if old:q.execute('UPDATE dnf_gm.player_profiles SET revision=%s,notes=%s,tags_json=%s,updated_at=%s WHERE uid=%s',(revision,data['notes'],dump(data['tags']),now,target))
            else:q.execute('INSERT INTO dnf_gm.player_profiles(uid,revision,notes,tags_json,updated_at) VALUES(%s,%s,%s,%s,%s)',(target,revision,data['notes'],dump(data['tags']),now))
            return {'revision':revision},target,{'before':before}
        if kind=='case-create':
            identity=self.target(q,data['uid'],data['charac_no']);cid=uuid.uuid4().hex
            q.execute("INSERT INTO dnf_gm.support_cases(case_id,uid,charac_no,target_json,title,category,description,status,revision,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,'open',1,%s,%s)",(cid,data['uid'],data['charac_no'],dump(identity),data['title'],data['category'],data['description'],now,now))
            row=self.case(q,cid);self.event(q,row,kind,'建立问题记录',data,False)
            return {'case_id':cid,'revision':1},data['uid'],{}
        row=self.case(q,target,True);self.expected(row,data)
        if kind=='case-update':
            changes={k:{'before':row[k],'after':data[k]} for k in ('title','category','description','status') if row[k]!=data[k]}
            if not changes:raise HTTPException(422,'没有状态或内容变化；请使用追加处理记录')
            q.execute('UPDATE dnf_gm.support_cases SET title=%s,category=%s,description=%s,status=%s WHERE case_id=%s',(data['title'],data['category'],data['description'],data['status'],target))
            revision=self.event(q,row,kind,data['note'],changes)
        elif kind=='case-comment':revision=self.event(q,row,kind,data['note'],{})
        elif kind=='case-link':
            op=one(q,'SELECT action,status,request_json FROM dnf_gm.operations WHERE operation_id=%s',(data['operation_id'],))
            if not op:raise HTTPException(404,'原操作不存在')
            request=json.loads(op['request_json'])
            self.link_target(row,request)
            if data['relation']=='compensation' and (op['action'] not in REWARDS or op['status']!='committed'):raise HTTPException(409,'只有本账号已提交的奖励操作才能标记为补偿')
            revision=self.link(q,row,data['operation_id'],data['relation'],data['note'],{'action':op['action'],'status_at_link':op['status']})
        else:raise HTTPException(422,'未知工作台操作')
        return {'case_id':target,'revision':revision},row['uid'],{}

    @staticmethod
    def link_target(row,data):
        if data.get('uid')!=row['uid']:raise HTTPException(409,'操作不属于此问题账号，禁止跨账号关联')
        if row['charac_no'] and data.get('charac_no') and row['charac_no']!=data['charac_no']:raise HTTPException(409,'操作角色与问题角色不一致')

    def link(self,q,row,op,relation,note,details):
        old=one(q,'SELECT relation FROM dnf_gm.support_links WHERE case_id=%s AND operation_id=%s',(row['case_id'],op))
        if old:
            if old['relation']==relation:raise HTTPException(409,'此操作已经关联，无需重复添加')
            # Keep evidence: reference may be promoted, compensation cannot be hidden.
            if old['relation']=='compensation':raise HTTPException(409,'不能抹去已记录的补偿；请追加处理说明')
            q.execute("UPDATE dnf_gm.support_links SET relation='compensation' WHERE case_id=%s AND operation_id=%s",(row['case_id'],op))
        else:q.execute('INSERT INTO dnf_gm.support_links(case_id,operation_id,relation,created_at) VALUES(%s,%s,%s,%s)',(row['case_id'],op,relation,int(time.time())))
        if relation=='compensation':q.execute('UPDATE dnf_gm.support_cases SET compensation_count=compensation_count+1 WHERE case_id=%s',(row['case_id'],))
        return self.event(q,row,'case-link',note,{'operation_id':op,'relation':relation,**details})

    def reward_preview(self,q,data,lock=False):
        cid=data.get('support_case_id')
        if not cid:return None
        if data['action'] not in REWARDS:raise HTTPException(422,'问题关联仅用于余额或奖励补偿')
        self.engines(q);row=self.case(q,cid,lock);self.link_target(row,data)
        return {k:row[k] for k in ('case_id','uid','charac_no','title','status','revision','compensation_count')}

    def attach_reward(self,q,data,op,preview):
        if not data.get('support_case_id'):return
        row=self.case(q,data['support_case_id'],True)
        self.link(q,row,op,'compensation',data['reason'],{'action':data['action'],'status_at_link':'committed_with_reward_transaction'})
