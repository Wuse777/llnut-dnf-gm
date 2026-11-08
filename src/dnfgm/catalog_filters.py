"""Shared read-only catalogue predicates, including bulk-policy selections."""
from fastapi import HTTPException
from .equipment_metadata import PARTS

ORDERS={'id':'id','level_asc':'level,id','level_desc':'level DESC,id','name':'name,id'}


def equipment_available(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='equipment_details'").fetchone() is not None


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
    return where,args


def facets(c):
    available=equipment_available(c)
    parts=[];rarities=[]
    if available:
        parts=[{'code':r[0],'name':PARTS.get(r[0],r[0]),'count':r[1]} for r in c.execute('SELECT part_code,COUNT(*) FROM equipment_details GROUP BY part_code ORDER BY part_code')]
        rarities=[{'value':r[0],'label':'PVF 品级 '+str(r[0]),'count':r[1]} for r in c.execute('SELECT rarity,COUNT(*) FROM equipment_details WHERE rarity IS NOT NULL GROUP BY rarity ORDER BY rarity')]
    limits=c.execute('SELECT MIN(level),MAX(level) FROM items').fetchone()
    return {'equipment_metadata':available,'parts':parts,'rarities':rarities,'min_level':limits[0],'max_level':limits[1]}
