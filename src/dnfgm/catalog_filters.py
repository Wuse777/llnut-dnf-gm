"""Shared read-only catalogue predicates, including bulk-policy selections."""
from fastapi import HTTPException
from .equipment_metadata import PARTS,JOB_NAMES,WEAPON_NAMES

ORDERS={'id':'id','level_asc':'level,id','level_desc':'level DESC,id','name':'name,id'}


def equipment_available(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='equipment_details'").fetchone() is not None


def extended_available(c):
    version=c.execute("SELECT value FROM metadata WHERE key='equipment_filters_version'").fetchone()
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('equipment_filter_details','equipment_jobs')")}
    return bool(version and version[0]=='1' and len(tables)==2)


def predicates(c,filters):
    where=[];args=[]
    lo,hi=filters.get('min_level'),filters.get('max_level')
    if lo is not None and hi is not None and lo>hi:
        raise HTTPException(422,'最低等级不能大于最高等级')
    if lo is not None:where.append('level>=?');args.append(lo)
    if hi is not None:where.append('level<=?');args.append(hi)
    part,rarity=filters.get('part',''),filters.get('rarity')
    if part or rarity is not None:
        if not equipment_available(c):
            raise HTTPException(409,'当前索引没有装备部位与品级元数据，请先离线补全索引')
        terms=['e.item_id=items.id']
        if part:terms.append('e.part_code=?');args.append(part)
        if rarity is not None:terms.append('e.rarity=?');args.append(rarity)
        where.append('EXISTS (SELECT 1 FROM equipment_details e WHERE '+' AND '.join(terms)+')')
    job,weapon,set_id=filters.get('job',''),filters.get('weapon_type',''),filters.get('set_id')
    if job or weapon or set_id is not None:
        if not extended_available(c):
            raise HTTPException(409,'当前索引没有职业、武器类别和套装元数据，请先离线补全索引')
        if job:
            # Known or actually indexed job codes include explicitly universal
            # equipment. Unknown literal inputs never broaden to all-job items.
            known=job in JOB_NAMES or c.execute('SELECT 1 FROM equipment_jobs WHERE job_code=? LIMIT 1',(job,)).fetchone() is not None
            where.append("EXISTS (SELECT 1 FROM equipment_jobs j WHERE j.item_id=items.id AND (j.job_code=?"+(" OR j.job_code='[all]'" if known else '')+'))')
            args.append(job)
        terms=['f.item_id=items.id']
        if weapon:terms.append('f.weapon_type=?');args.append(weapon)
        if set_id is not None:terms.append('f.set_id=?');args.append(set_id)
        if len(terms)>1:where.append('EXISTS (SELECT 1 FROM equipment_filter_details f WHERE '+' AND '.join(terms)+')')
    return where,args


def facets(c):
    available=equipment_available(c)
    parts=[];rarities=[]
    if available:
        parts=[{'code':r[0],'name':PARTS.get(r[0],r[0]),'count':r[1]} for r in c.execute('SELECT part_code,COUNT(*) FROM equipment_details GROUP BY part_code ORDER BY part_code')]
        rarities=[{'value':r[0],'label':'PVF 品级 '+str(r[0]),'count':r[1]} for r in c.execute('SELECT rarity,COUNT(*) FROM equipment_details WHERE rarity IS NOT NULL GROUP BY rarity ORDER BY rarity')]
    limits=c.execute('SELECT MIN(level),MAX(level) FROM items').fetchone()
    extended=extended_available(c);jobs=[];weapons=[];sets=[]
    if extended:
        jobs=[{'code':r[0],'name':JOB_NAMES.get(r[0],r[0]),'count':r[1]} for r in c.execute('SELECT job_code,COUNT(*) FROM equipment_jobs GROUP BY job_code ORDER BY job_code')]
        weapons=[{'code':r[0],'name':WEAPON_NAMES.get(r[0],r[0]),'count':r[1]} for r in c.execute("SELECT weapon_type,COUNT(*) FROM equipment_filter_details WHERE weapon_type<>'' GROUP BY weapon_type ORDER BY weapon_type")]
        sets=[{'id':r[0],'name':r[1] or 'PVF 套装 #'+str(r[0]),'count':r[2]} for r in c.execute('SELECT set_id,MAX(set_name),COUNT(*) FROM equipment_filter_details WHERE set_id IS NOT NULL GROUP BY set_id ORDER BY set_id LIMIT 2000')]
    return {'equipment_metadata':available,'extended_equipment_metadata':extended,'parts':parts,'rarities':rarities,'jobs':jobs,'weapon_types':weapons,'sets':sets,'sets_truncated':bool(extended and c.execute('SELECT COUNT(DISTINCT set_id) FROM equipment_filter_details').fetchone()[0]>2000),'min_level':limits[0],'max_level':limits[1]}
