"""Read-only progression archive diagnosis; never implements synthetic level-up."""
from contextlib import closing
import sqlite3
import time
from fastapi import HTTPException
from .catalog import Catalog, snapshot
from .inventory_operations import InventoryOperations
from .service import one

PROGRAM_SHA='8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261'


def experience(value):
    if type(value) is not int or not -(1<<31)<=value<(1<<31):
        return {'raw':value,'unsigned':None,'hex':None,'state':'unsupported'}
    return {'raw':value,'unsigned':value&0xffffffff,'hex':f'0x{value&0xffffffff:08X}','state':'decoded'}


def compare_archive(level,info,stat,thresholds):
    """PVF reference only: do not conflate different save times with corruption."""
    a,b=experience(info),experience(stat)
    lower=0 if level==1 else thresholds.get(level)
    upper=thresholds.get(level+1) if type(level) is int else None
    known=type(lower) is int and type(upper) is int and 0<=lower<upper<=0xffffffff
    def reference(value):
        n=value['unsigned']
        if not known or n is None:return {'state':'unknown'}
        return {'state':'within_reference' if lower<=n<=upper else 'outside_reference',
                'remaining':max(0,upper-n),'progress_percent':round((n-lower)*100/(upper-lower),2)}
    return {'selection':{**a,'reference':reference(a)},'saved':{**b,'reference':reference(b)},
            'same_value':None if a['unsigned'] is None or b['unsigned'] is None else a['unsigned']==b['unsigned'],
            'range':{'state':'available' if known else 'unknown','lower':lower if known else None,'upper':upper if known else None}}


class CharacterProgression:
    def __init__(self,service):
        self.db,self.settings=service.db,service.settings
        self.catalog=Catalog(self.settings)

    def thresholds(self):
        live=snapshot(self.settings);rows={};state='unavailable'
        try:
            with closing(self.catalog.connect()) as c:
                meta=self.catalog.meta(c)
                if meta.get('pvf_sha256')!=self.settings.pvf_sha256 or (live.get('fresh') and live.get('pvf_sha256')!=self.settings.pvf_sha256):state='mismatch'
                elif self.settings.inventory_program_sha256!=PROGRAM_SHA:state='unsupported_program'
                elif meta.get('progression_index_version')!='1':state='not_installed'
                else:
                    values=c.execute('SELECT level,total_exp FROM progression_thresholds ORDER BY level LIMIT 201').fetchall()
                    if not values or len(values)>199:raise ValueError('Invalid threshold count')
                    last=0
                    for expected,row in enumerate(values,2):
                        level,n=row['level'],row['total_exp']
                        if level!=expected or type(n) is not int or not last<n<=0xffffffff:raise ValueError('Invalid threshold ordering')
                        rows[level]=n;last=n
                    state='matched'
        except (OSError,sqlite3.Error,ValueError,HTTPException):state='unavailable';rows={}
        if state!='matched':rows={}
        return {'state':state,'runtime_fresh':live.get('fresh') is True,'threshold_count':len(rows),
                'source':'character/exptable.tbl','note':'PVF参考阈值不代表运行中等级上限；插件或补丁可能改变实际规则。'},rows

    def read(self,charac_no):
        with self.db.connect() as c,c.cursor() as q:
            target=InventoryOperations.target(q,charac_no)
            # One statement keeps both archive columns in the same DB snapshot.
            row=one(q,'SELECT i.lev,i.exp AS selection_exp,s.exp AS saved_exp,s.charac_no AS stat_id '
                'FROM taiwan_cain.charac_info i LEFT JOIN taiwan_cain.charac_stat s ON s.charac_no=i.charac_no '
                'WHERE i.charac_no=%s',(charac_no,))
        if not row:raise HTTPException(404,'角色存档已不存在，请刷新角色列表')
        catalog,thresholds=self.thresholds()
        comparison=compare_archive(row['lev'],row['selection_exp'],row['saved_exp'],thresholds)
        return {'target':target,'level':row['lev'],'stat_present':row['stat_id'] is not None,'catalog':catalog,
                **comparison,'collected_at':time.time(),'writable':False,
                'note':'仅显示数据库快照，不是客户端实时经验。两处经验可能因保存时点不同而有差异，不自动判定损坏或修复；本区域仅查询；下方独立等级维护入口会预览关联修改，不自动修正。'}
