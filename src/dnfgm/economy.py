"""GM-only reporting. Immutable projection commits with the original reward.

Never read all-player balances or claim a complete game economy. Historical
records which cannot be reconstructed from committed audit evidence are marked
incomplete, not guessed. Amounts are decimal strings at the HTTP boundary.
"""
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
import hashlib
import json
import re
import time
import pymysql
from fastapi import HTTPException

COINS=('cera','cera_point','mileage')
ACTIONS=('currency','mail','reward')
TZ=timezone(timedelta(hours=8))
NOTE='仅统计本GM成功审计中的发放与扣减，不包含打怪、交易、商城消费或其他工具；数据库提交不等于游戏内生效。'


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)

def integer(value,minimum=0,maximum=9223372036854775807):
    if type(value) is not int or not minimum<=value<=maximum:raise ValueError('invalid_integer')
    return value


def normalize(audit):
    """Use committed results, never requested balances or guessed delivery IDs."""
    req=json.loads(audit['request_json']);result=json.loads(audit['result_json'])
    if not isinstance(req,dict) or not isinstance(result,dict):raise ValueError('invalid_evidence')
    uid=integer(audit['target_uid'],1,2147483647)
    if req.get('uid')!=uid or result.get('uid',uid)!=uid:raise ValueError('target_mismatch')
    role=req.get('charac_no');role=integer(role,1,2147483647) if role is not None else None
    action=audit['action']
    if action not in ACTIONS or result.get('action',action)!=action:raise ValueError('action_mismatch')
    if result.get('state')=='campaign_duplicate_skipped':
        campaign=result.get('campaign') or {}
        if not campaign.get('skipped') or campaign.get('id')!=req.get('campaign_id') or result.get('currency_rewards')!={} or 'letter_id' in result:
            raise ValueError('invalid_campaign_skip')
        return req,role,{}
    values={}
    def coin(name,entry):
        if name not in COINS or not isinstance(entry,dict) or entry.get('currency')!=name:raise ValueError('invalid_currency')
        before=integer(entry['before']);after=integer(entry['after']);values[(name,0,'')]=('',after-before)
    if action=='currency':coin(result['currency'],result)
    elif action=='reward':
        if not isinstance(result.get('currency_rewards'),dict):raise ValueError('missing_currency_results')
        for name,entry in result['currency_rewards'].items():coin(name,entry)
    has_mail=action=='mail' or 'letter_id' in result
    if has_mail:
        integer(result['letter_id'],1);gold=integer(result['gold']);values[('gold',0,'')]=('',gold)
        rewards=result['items'];items=rewards['items'];pvf=rewards['pvf_sha256']
        if not isinstance(items,list) or len(items)>20 or not re.fullmatch('[a-f0-9]{64}',pvf):raise ValueError('invalid_reward_snapshot')
        for item in items:
            item_id=integer(item['id'],1,4294967295);quantity=integer(item['quantity'],1,2147483647)
            name=item.get('name')
            if not isinstance(name,str):raise ValueError('missing_item_name')
            k=('item',item_id,pvf);previous=values.get(k,('',0))[1]
            values[k]=(name[:255],integer(previous+quantity,1))
    elif action=='reward' and (req.get('items') or req.get('gold')):raise ValueError('missing_mail_results')
    return req,role,values


class Economy:
    def __init__(self,db):self.db=db

    @staticmethod
    def engines(q):
        q.execute("SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME IN ('economy_operations','economy_values','audit')")
        rows=q.fetchall()
        if len(rows)!=3 or any(r['ENGINE']!='InnoDB' for r in rows):raise HTTPException(503,'发放统计迁移或事务引擎未就绪')

    def record(self,q,operation_id,historical=False):
        self.engines(q)
        q.execute('SELECT id,operation_id,action,actor,target_uid,reason,request_json,result_json,created_at FROM dnf_gm.audit WHERE operation_id=%s',(operation_id,));audit=q.fetchone()
        if not audit or audit['action'] not in ACTIONS:raise HTTPException(503,'缺少成功奖励审计，不能建立发放统计')
        fingerprint=hashlib.sha256(encoded(audit).encode()).hexdigest()
        issue='';complete=True
        try:req,role,values=normalize(audit)
        except (ValueError,TypeError,KeyError,OverflowError):
            if not historical:raise HTTPException(503,'奖励结果不符合统计基线，未提交奖励') from None
            # Retain unknown evidence as a record; do not infer any partial amounts.
            req={};role=None;values={};complete=False;issue='历史结果字段缺失或不一致，未推算金额或物品'
        source='schedule' if req.get('schedule_id') else 'batch' if req.get('job_id') else 'manual'
        template_id=req.get('template_id');template_version=req.get('template_version')
        campaign_result=json.loads(audit['result_json']).get('campaign') or {}
        if campaign_result and req.get('campaign_id')==campaign_result.get('id'):
            template_id=campaign_result.get('template_id');template_version=campaign_result.get('template_version')
        if template_id is not None and (type(template_id) is not int or template_id<1):template_id=None
        if template_version is not None and (type(template_version) is not int or template_version<1):template_version=None
        try:
            q.execute('INSERT INTO dnf_gm.economy_operations(operation_id,audit_id,target_uid,charac_no,action,source,actor,reason,template_id,template_version,source_hash,complete,issue,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                      (operation_id,audit['id'],audit['target_uid'] if type(audit['target_uid']) is int and audit['target_uid']>0 else 0,role,audit['action'],source,audit['actor'],audit['reason'],template_id,template_version,fingerprint,int(complete),issue,audit['created_at']))
        except pymysql.IntegrityError:
            q.execute('SELECT source_hash FROM dnf_gm.economy_operations WHERE operation_id=%s FOR UPDATE',(operation_id,));old=q.fetchone()
            if not old or old['source_hash']!=fingerprint:raise HTTPException(409,'统计来源冲突，请维护核对，不覆盖旧记录') from None
            return False
        if values:q.executemany('INSERT INTO dnf_gm.economy_values(operation_id,metric,item_id,pvf_sha256,item_name,amount) VALUES(%s,%s,%s,%s,%s,%s)',[(operation_id,*k,name,amount) for k,(name,amount) in values.items()])
        return True

    def import_history(self,after_id=0,limit=100):
        if type(after_id) is not int or after_id<0 or not 1<=limit<=100:raise ValueError('invalid_import_page')
        with self.db.connect() as c,c.cursor() as q:
            self.engines(q);q.execute("SELECT id,operation_id FROM dnf_gm.audit WHERE id>%s AND action IN ('currency','mail','reward') ORDER BY id LIMIT %s",(after_id,limit));rows=q.fetchall()
        imported=0
        for row in rows:
            with self.db.connect() as c,c.cursor() as q:
                imported+=int(self.record(q,row['operation_id'],historical=True));c.commit()
        return {'imported':imported,'after_id':rows[-1]['id'] if rows else after_id,'has_more':len(rows)==limit}

    @staticmethod
    def window(start,end,uid=0):
        if isinstance(start,str):start=date.fromisoformat(start)
        if isinstance(end,str):end=date.fromisoformat(end)
        if not 0<=(end-start).days<31:raise HTTPException(422,'请选择起止顺序正确、最多31天的日期范围；日期按北京时间')
        begin=datetime.combine(start,datetime.min.time(),TZ).astimezone(timezone.utc).replace(tzinfo=None)
        stop=datetime.combine(end+timedelta(days=1),datetime.min.time(),TZ).astimezone(timezone.utc).replace(tzinfo=None)
        return begin,stop

    @staticmethod
    def where(start,end,uid=0,alias='e'):
        begin,stop=Economy.window(start,end,uid)
        return f'{alias}.created_at>=%s AND {alias}.created_at<%s'+(f' AND {alias}.target_uid=%s' if uid else ''),(begin,stop,*((uid,) if uid else ()))

    @staticmethod
    def query(q,sql,args=()):
        try:q.execute(sql,args);return q.fetchall()
        except pymysql.OperationalError as e:
            if e.args[0] in (3024,1317,2013):raise HTTPException(503,'统计查询超时，未返回部分总计；请缩短日期范围或按账号筛选') from None
            raise

    def summary(self,start,end,uid=0):
        where,args=self.where(start,end,uid);a_where,a_args=self.where(start,end,uid,'a');began=time.monotonic()
        with self.db.connect() as c,c.cursor() as q:
            self.engines(q)
            def read(sql,params=args):
                if time.monotonic()-began>7:raise HTTPException(503,'统计查询预算不足，未返回部分总计，请缩小范围')
                return self.query(q,sql,params)
            audits=read("SELECT COUNT(*) n FROM dnf_gm.audit a WHERE "+a_where+" AND a.action IN ('currency','mail','reward')",a_args)[0]['n']
            count=read('SELECT COUNT(*) n,COALESCE(SUM(complete),0) complete FROM dnf_gm.economy_operations e WHERE '+where)[0]
            join=' FROM dnf_gm.economy_operations e JOIN dnf_gm.economy_values v ON v.operation_id=e.operation_id WHERE '+where+' AND e.complete=1'
            totals=read('SELECT v.metric,CAST(SUM(GREATEST(v.amount,0)) AS CHAR) issued,CAST(SUM(GREATEST(-v.amount,0)) AS CHAR) deducted,CAST(SUM(v.amount) AS CHAR) net'+join+' GROUP BY v.metric ORDER BY v.metric')
            daily=read("SELECT DATE(DATE_ADD(e.created_at,INTERVAL 8 HOUR)) day,v.metric,CAST(SUM(GREATEST(v.amount,0)) AS CHAR) issued,CAST(SUM(GREATEST(-v.amount,0)) AS CHAR) deducted,CAST(SUM(v.amount) AS CHAR) net"+join+' GROUP BY day,v.metric ORDER BY day,v.metric')
            targets=read('SELECT e.target_uid,COUNT(*) operations FROM dnf_gm.economy_operations e WHERE '+where+' AND e.complete=1 GROUP BY e.target_uid ORDER BY operations DESC,e.target_uid LIMIT 20')
            items=read("SELECT v.item_id,v.pvf_sha256,MAX(v.item_name) item_name,CAST(SUM(v.amount) AS CHAR) quantity,COUNT(DISTINCT e.operation_id) operations"+join+" AND v.metric='item' GROUP BY v.item_id,v.pvf_sha256 ORDER BY SUM(v.amount) DESC,v.item_id,v.pvf_sha256 LIMIT 50")
            templates=read('SELECT e.template_id,e.template_version,COUNT(*) operations FROM dnf_gm.economy_operations e WHERE '+where+' AND e.complete=1 AND e.template_id IS NOT NULL GROUP BY e.template_id,e.template_version ORDER BY operations DESC,e.template_id,e.template_version LIMIT 20')
            reasons=read('SELECT e.reason,COUNT(*) operations FROM dnf_gm.economy_operations e WHERE '+where+' AND e.complete=1 GROUP BY e.reason ORDER BY operations DESC,e.reason LIMIT 20')
            sources=read('SELECT e.source,COUNT(*) operations FROM dnf_gm.economy_operations e WHERE '+where+' AND e.complete=1 GROUP BY e.source ORDER BY e.source')
        known=int(count['complete']);projected=int(count['n'])
        return {'timezone':'Asia/Shanghai','start':str(start),'end':str(end),'uid':uid,'generated_at':int(time.time()),'note':NOTE,
                'coverage':{'reward_audits':audits,'projected':projected,'complete':known,'incomplete':projected-known,'unprojected':max(0,audits-projected),'state':'complete' if audits==known==projected else 'partial'},
                'totals':totals,'daily':daily,'targets':targets,'items':items,'templates':templates,'reasons':reasons,'sources':sources,
                'ranking_limits':{'targets':20,'items':50,'templates':20,'reasons':20},'client_verified':False}

    def operations(self,start,end,uid=0,before=0,upper=0,large=False,currency_threshold=100000,gold_threshold=100000000):
        with self.db.connect() as c,c.cursor() as q:
            result=self.operation_page(q,start,end,uid,before,upper,large,currency_threshold,gold_threshold)
        result['pagination_note']='固定投影编号上界；交互翻页不是跨请求事务快照，并发提交后可刷新查询。导出使用独立一致性快照。'
        return result

    def operation_page(self,q,start,end,uid=0,before=0,upper=0,large=False,currency_threshold=100000,gold_threshold=100000000):
        where,args=self.where(start,end,uid)
        if not upper:
            q.execute('SELECT COALESCE(MAX(projection_id),0) n FROM dnf_gm.economy_operations');upper=q.fetchone()['n']
        terms=' AND e.projection_id<=%s'+(' AND e.audit_id<%s' if before else '')
        params=(*args,upper,*((before,) if before else ()))
        if large:
            terms+=" AND EXISTS (SELECT 1 FROM dnf_gm.economy_values x WHERE x.operation_id=e.operation_id AND ((x.metric IN ('cera','cera_point','mileage') AND ABS(x.amount)>=%s) OR (x.metric='gold' AND x.amount>=%s)))";params+=currency_threshold,gold_threshold
        rows=self.query(q,'SELECT e.operation_id,e.audit_id,e.target_uid,e.charac_no,e.action,e.source,e.reason,e.template_id,e.template_version,e.complete,e.issue,e.created_at FROM dnf_gm.economy_operations e WHERE '+where+terms+' ORDER BY e.audit_id DESC LIMIT 51',params)
        more=len(rows)>50;rows=rows[:50]
        if rows:
            ids=[r['operation_id'] for r in rows];values=self.query(q,'SELECT operation_id,metric,item_id,pvf_sha256,item_name,CAST(amount AS CHAR) amount FROM dnf_gm.economy_values WHERE operation_id IN ('+','.join(['%s']*len(ids))+') ORDER BY operation_id,metric,item_id,pvf_sha256',ids)
            grouped=defaultdict(list)
            for v in values:grouped[v.pop('operation_id')].append(v)
            for r in rows:r['values']=grouped[r['operation_id']]
        return {'items':rows,'upper':upper,'next_before':rows[-1]['audit_id'] if more else None,'note':NOTE}


    def backlog(self,start,end,uid=0):
        where,args=self.where(start,end,uid,'b')
        joined=' FROM dnf_gm.mail_batches b JOIN dnf_gm.mail_deliveries d ON d.operation_id=b.operation_id LEFT JOIN taiwan_cain_2nd.postal p ON p.postal_id=d.postal_id WHERE '+where
        state="CASE WHEN p.postal_id IS NULL THEN 'record_missing' WHEN p.receive_time IS NOT NULL AND CAST(p.receive_time AS CHAR) NOT LIKE '0000-00-00%%' THEN 'claimed_marker' WHEN p.delete_flag<>0 THEN 'deleted_marker' ELSE 'unclaimed_marker' END"
        with self.db.connect() as c,c.cursor() as q:
            states=self.query(q,'SELECT '+state+' receipt_state,COUNT(*) records,CAST(SUM(d.gold) AS CHAR) gold,CAST(SUM(d.quantity) AS CHAR) quantity'+joined+' GROUP BY receipt_state',args)
            unknown=self.query(q,'SELECT COUNT(*) batches,COALESCE(SUM(b.history_complete=0),0) incomplete_batches,CAST(COALESCE(SUM(GREATEST(b.postal_count-b.recorded_count,0)),0) AS CHAR) unrecorded FROM dnf_gm.mail_batches b WHERE '+where,args)[0]
            oldest=self.query(q,'SELECT b.operation_id,b.target_uid,b.charac_no,b.character_name,b.created_at,d.postal_id,d.item_id,d.quantity,d.gold'+joined+" AND p.postal_id IS NOT NULL AND (p.receive_time IS NULL OR CAST(p.receive_time AS CHAR) LIKE '0000-00-00%%') AND COALESCE(p.delete_flag,0)=0 ORDER BY b.created_at,b.operation_id,d.ordinal LIMIT 20",args)
            e_where,e_args=self.where(start,end,uid)
            missing=self.query(q,"SELECT COUNT(*) expected,COALESCE(SUM(b.operation_id IS NULL),0) missing FROM dnf_gm.economy_operations e LEFT JOIN dnf_gm.mail_batches b ON b.operation_id=e.operation_id WHERE "+e_where+" AND (e.action='mail' OR EXISTS (SELECT 1 FROM dnf_gm.economy_values v WHERE v.operation_id=e.operation_id AND v.metric='gold'))",e_args)[0]
            unknown.update(projected_mail_operations=missing['expected'],missing_mail_ledgers=int(missing['missing']))
        return {'states':states,'coverage':{k:int(v) if isinstance(v,Decimal) else v for k,v in unknown.items()},'oldest':oldest,'generated_at':int(time.time()),'client_verified':False,'note':'仅所选投递日期范围内的GM邮件附件记录；领取标记不是客户端验收，丢失记录或未导入历史不推算为已领取。'}

    def repeated_compensation(self,start,end,uid=0):
        where,args=self.where(start,end,uid)
        with self.db.connect() as c,c.cursor() as q:
            rows=self.query(q,"SELECT s.case_id,s.uid,s.charac_no,s.title,s.status,s.compensation_count,COUNT(*) matches_in_window FROM dnf_gm.support_cases s JOIN dnf_gm.support_links l ON l.case_id=s.case_id JOIN dnf_gm.economy_operations e ON e.operation_id=l.operation_id WHERE "+where+" AND l.relation='compensation' AND s.compensation_count>1 GROUP BY s.case_id,s.uid,s.charac_no,s.title,s.status,s.compensation_count ORDER BY s.compensation_count DESC,s.case_id LIMIT 21",args)
        return {'items':rows[:20],'has_more':len(rows)>20,'note':'已关联多笔补偿的处理问题，仅是需人工核对的线索；不认定重复错误，不自动撤销奖励。补偿总数为问题全历史，日期只筛选本期有关联的案例。'}

    def export(self,start,end,uid=0):
        self.window(start,end,uid)
        # Preflight before response headers; the generator owns its own bounded
        # connection/consistent snapshot, closed also on cancellation or failure.
        with self.db.connect() as c,c.cursor() as q:self.engines(q)
        def generate():
            began=time.monotonic();count=0
            try:
                with self.db.connect() as c,c.cursor() as q:
                    q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    q.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
                    page=self.operation_page(q,start,end,uid);upper=page['upper']
                    yield encoded({'type':'metadata','start':str(start),'end':str(end),'uid':uid,'upper':upper,'upper_kind':'projection_id','snapshot':'repeatable_read','scope':'projected_operations_only','coverage_note':'仅包含快照内已投影记录；未导入审计不在文件中，complete仅表示该投影快照遍历完成','timezone':'Asia/Shanghai','note':NOTE})+'\n'
                    while True:
                        for row in page['items']:
                            if time.monotonic()-began>120:raise TimeoutError()
                            count+=1;yield encoded({'type':'operation',**row})+'\n'
                        if page['next_before'] is None:break
                        if time.monotonic()-began>120:raise TimeoutError()
                        page=self.operation_page(q,start,end,uid,before=page['next_before'],upper=upper)
                    yield encoded({'type':'complete','count':count,'scope':'projected_operations_only'})+'\n'
            except Exception:
                yield encoded({'type':'incomplete','count':count,'reason':'导出中断或超时，请保留不完整标记，不将其当作完整明细'})+'\n'
        return generate()
