"""Bounded NDJSON audit export with high-water mark and completion sentinel."""
import json


def export_audit(db,uid=0):
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COALESCE(MAX(id),0) AS maximum FROM dnf_gm.audit')
        maximum=q.fetchone()['maximum']
    def line(value):
        return json.dumps(value,ensure_ascii=False,default=str,separators=(',',':'))+'\n'
    def records():
        yield line({'type':'metadata','target_uid':uid or None,'through_id':maximum,'format':'dnf-gm-audit-v1'})
        after=0;count=0
        while after<maximum:
            with db.connect() as c,c.cursor() as q:
                where='id>%s AND id<=%s';args=[after,maximum]
                if uid:
                    where+=' AND target_uid=%s';args.append(uid)
                q.execute('SELECT id,operation_id,actor,action,target_uid,reason,request_json,result_json,created_at FROM dnf_gm.audit WHERE '+where+' ORDER BY id LIMIT 100',args)
                rows=q.fetchall()
            if not rows:
                break
            for row in rows:
                after=row['id'];count+=1
                yield line({'type':'record',**row})
        yield line({'type':'complete','records':count,'through_id':maximum})
    return records()
