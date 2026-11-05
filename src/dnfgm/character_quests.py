"""QF1031 quest snapshots, literal catalog search and prerequisite inspection."""
from contextlib import closing
from collections import Counter
import hashlib
import json
import sqlite3
import struct
import time
import zlib

from fastapi import HTTPException
from .catalog import Catalog,snapshot
from .inventory_operations import InventoryOperations
from .service import one

CLEAR_SIZE=30000
PROGRAM_SHA='8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261'
QUEST_COLUMNS=('charac_no','clear_quest','urgentQuestIndex',*(k for i in range(1,21) for k in (f'play_{i}',f'play_{i}_trigger')))


def decode_clear(blob):
    if not isinstance(blob,bytes) or not 5<=len(blob)<=65535:raise ValueError('完成标记为空或长度异常，不能视为零个已完成任务')
    expected=struct.unpack_from('<I',blob)[0]&0x3fffffff
    if expected!=CLEAR_SIZE:raise ValueError('完成标记不是当前镜像的30000字节格式')
    try:
        stream=zlib.decompressobj();raw=stream.decompress(blob[4:],CLEAR_SIZE+1)
        if len(raw)!=CLEAR_SIZE or not stream.eof or stream.unconsumed_tail or stream.unused_data:raise ValueError('完成标记压缩流不完整或有多余数据')
    except zlib.error:raise ValueError('完成标记无法解压') from None
    return raw


class CharacterQuests:
    def __init__(self,service):
        self.db,self.settings=service.db,service.settings
        self.catalog=Catalog(self.settings)

    def metadata(self,ids):
        state='unavailable';rows={};live=snapshot(self.settings)
        try:
            with closing(self.catalog.connect()) as c:
                meta=self.catalog.meta(c)
                if meta.get('pvf_sha256')!=self.settings.pvf_sha256 or (live.get('fresh') and live.get('pvf_sha256')!=self.settings.pvf_sha256):state='mismatch'
                elif meta.get('quest_index_version')!='1':state='not_installed'
                else:
                    state='matched'
                    if ids:
                        for row in c.execute('SELECT * FROM quests WHERE id IN ('+','.join('?' for _ in ids)+')',list(ids)):
                            row=dict(row);row['prerequisites']=json.loads(row['prerequisites']);rows[row['id']]=row
        except (OSError,sqlite3.Error,ValueError,HTTPException):state='unavailable';rows={}
        return {'state':state,'runtime_fresh':live.get('fresh') is True},rows

    @staticmethod
    def prerequisite_ids(definition):
        values=definition.get('prerequisites',[]) if definition else []
        return list(dict.fromkeys(v for v in values if type(v) is int and 0<v<=65535))

    def prerequisites(self,definition,raw,active):
        if not definition:return None
        values=definition['prerequisites'];ids=self.prerequisite_ids(definition)
        catalog,meta=self.metadata(ids)
        return {'raw':values,'state':'references' if all(type(v) is int and 0<v<=65535 for v in values) else 'partially_interpreted',
            'items':[{'id':i,'name':meta.get(i,{}).get('name'),
                'clear_flag':raw[i] if raw is not None and i<CLEAR_SIZE else None,
                'active_slots':[x['slot'] for x in active if x['id']==i]} for i in ids],
            'note':'逐项展示前置任务的数据库标记，不推断多个条件的AND/OR、可接资格或客户端即时进度。'}

    def search(self,charac_no,query,page=1):
        # One bounded character snapshot; never scan players to search PVF.
        with self.db.connect() as c,c.cursor() as q:
            target=InventoryOperations.target(q,charac_no)
            row=one(q,'SELECT '+','.join('`'+k+'`' for k in QUEST_COLUMNS)+' FROM taiwan_cain.new_charac_quest WHERE charac_no=%s',(charac_no,))
        collected_at=time.time()
        active=[{'slot':i,'id':row[f'play_{i}']} for i in range(1,21)] if row else []
        catalog,unused=self.metadata([])
        base={'target':target,'catalog':catalog,'query':query,'page':page,'page_size':20,
            'collected_at':collected_at,'items':[],'has_more':False}
        if catalog['state']!='matched':return base
        # Literal substring (including % and _) with numeric exact ID first.
        identifier=int(query) if query.isascii() and query.isdigit() and len(query)<=5 else 0
        try:
            with closing(self.catalog.connect()) as c:
                metadata=self.catalog.meta(c)
                if metadata.get('pvf_sha256')!=self.settings.pvf_sha256 or metadata.get('quest_index_version')!='1':
                    return {**base,'catalog':{'state':'mismatch','runtime_fresh':catalog['runtime_fresh']}}
                rows=list(c.execute('SELECT id,name,grade,kind,min_level,max_level FROM quests WHERE id=? OR instr(name,?)>0 ORDER BY (id=?) DESC,id LIMIT 21 OFFSET ?',
                    (identifier,query,identifier,(page-1)*20)))
        except (OSError,sqlite3.Error):raise HTTPException(503,'任务索引暂时不可读') from None
        raw=None
        # Completed status must not be guessed from just the visible 50 flags.
        if row and self.settings.inventory_program_sha256==PROGRAM_SHA:
            try:raw=decode_clear(row['clear_quest'])
            except ValueError:pass
        return {**base,'items':[{**dict(r),'clear_flag':raw[r['id']] if raw is not None and 0<r['id']<CLEAR_SIZE else None,
            'active_slots':[x['slot'] for x in active if x['id']==r['id']]} for r in rows[:20]],'has_more':len(rows)>20}

    def read(self,charac_no,page=1,quest_id=0):
        with self.db.connect() as c,c.cursor() as q:
            target=InventoryOperations.target(q,charac_no)
            row=one(q,'SELECT '+','.join('`'+k+'`' for k in QUEST_COLUMNS)+' FROM taiwan_cain.new_charac_quest WHERE charac_no=%s',(charac_no,))
        base={'target':target,'collected_at':time.time(),'note':'数据库持久快照，在线进度可能尚未保存；疑点仅供排查，不自动完成或重置任务。','page':page,'page_size':50}
        if row is None:return {**base,'state':'missing','message':'缺少任务存档，不代表角色没有任务','active':[],'completed':[],'completed_count':None,'has_more':False,'issues':[],'lookup':None,'catalog':{'state':'not_checked'}}
        issues=[];raw=None
        if self.settings.inventory_program_sha256!=PROGRAM_SHA:
            clear={'state':'unsupported','message':'当前程序指纹不是已适配版本，仅显示任务槽，不推断完成标记'}
        else:
            try:
                raw=decode_clear(row['clear_quest']);clear={'state':'decoded','sha256':hashlib.sha256(row['clear_quest']).hexdigest()}
            except ValueError as e:clear={'state':'unavailable','message':str(e)}
        ids=[i for i in range(1,CLEAR_SIZE) if raw[i]] if raw is not None else []
        visible=ids[(page-1)*50:page*50]
        active=[{'slot':i,'id':row[f'play_{i}'],'trigger_raw':row[f'play_{i}_trigger']} for i in range(1,21)]
        urgent=row['urgentQuestIndex'];wanted={x['id'] for x in active if x['id']>0}|set(visible)
        if quest_id:wanted.add(quest_id)
        if urgent>0:wanted.add(urgent)
        catalog,meta=self.metadata(wanted)
        counts=Counter(x['id'] for x in active if x['id'])
        for x in active:
            x['definition']=meta.get(x['id']);x['clear_flag']=raw[x['id']] if raw is not None and 0<x['id']<CLEAR_SIZE else None
            x['issues']=[]
            if not x['id'] and x['trigger_raw']:x['issues'].append('empty_with_progress')
            if x['id']>=CLEAR_SIZE:x['issues'].append('id_out_of_range')
            if x['id'] and counts[x['id']]>1:x['issues'].append('duplicate_active')
            if x['id'] and catalog['state']=='matched' and not x['definition']:x['issues'].append('missing_definition')
            if x['clear_flag']:x['issues'].append('active_with_clear_flag')
        if raw is None:issues.append({'code':'clear_unknown','message':clear['message']})
        elif any(v not in (0,1) for v in raw) or raw[0]:issues.append({'code':'nonstandard_clear_flags','message':'完成标记存在非0/1或保留位值，按原生非零判断展示，不将其自动修正'})
        completed=[{'id':i,'clear_flag':raw[i],'definition':meta.get(i)} for i in visible]
        lookup=None
        if quest_id:lookup={'id':quest_id,'definition':meta.get(quest_id),'active_slots':[x['slot'] for x in active if x['id']==quest_id],
            'clear_flag':raw[quest_id] if raw is not None and quest_id<CLEAR_SIZE else None,'within_native_range':quest_id<CLEAR_SIZE,'prerequisites':self.prerequisites(meta.get(quest_id),raw,active)}
        return {**base,'state':'read','active':active,'completed':completed,'completed_count':len(ids) if raw is not None else None,
            'has_more':page*50<len(ids),'clear':clear,'catalog':catalog,'issues':issues,'lookup':lookup,
            'urgent':{'id':urgent,'definition':meta.get(urgent)}}
