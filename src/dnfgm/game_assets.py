"""Read-only image lookup. No PVF/NPK parser, user path or image upload at runtime."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
from fastapi import HTTPException

SHA=re.compile(r'^[a-f0-9]{64}$')
PNG_MAGIC=b'\x89PNG\r\n\x1a\n'
MESSAGES={'not_installed':'未安装图片包','unavailable':'图片包不可用','mismatch':'图片包与PVF版本不一致',
          'missing':'缺少客户端素材','missing_reference':'PVF没有可用图片引用','ambiguous':'客户端图片来源冲突',
          'unsupported':'图片格式尚未适配','ready':'图片已离线解析，未验收客户端一致性'}


class GameAssets:
    def __init__(self,settings):self.settings=settings

    @contextmanager
    def connection(self,pvf_sha):
        c=None;state='not_installed'
        try:
            if self.settings.assets_dir:
                state='unavailable'
                root=Path(self.settings.assets_dir).resolve();p=root/'manifest.sqlite'
                if p.is_symlink() or not p.is_file() or p.stat().st_size>128*1024*1024:raise ValueError()
                c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=1);c.row_factory=sqlite3.Row
                c.execute('PRAGMA query_only=ON');c.execute('PRAGMA trusted_schema=OFF')
                metadata=dict(c.execute('SELECT key,value FROM metadata'))
                if metadata.get('format')!='dnfgm-assets-v1' or metadata.get('state')!='ready':raise ValueError()
                state='ready' if metadata.get('pvf_sha256')==pvf_sha==self.settings.pvf_sha256 and isinstance(pvf_sha,str) and SHA.fullmatch(pvf_sha) else 'mismatch'
                # Reuse the same fresh server fingerprint evidence as the catalog.
                from .catalog import snapshot
                live=snapshot(self.settings)
                if live.get('fresh') and live.get('pvf_sha256')!=pvf_sha:state='mismatch'
        except (OSError,ValueError,sqlite3.Error):state='unavailable'
        if state!='ready' and c:c.close();c=None
        try:yield c,state
        finally:
            if c:c.close()

    @staticmethod
    def image(row,pvf_sha,state):
        if row is not None and row['state']=='ready' and SHA.fullmatch(row['sha256'] or '') and all(type(row[k]) is int and 1<=row[k]<=512 for k in ('width','height')):
            return {'state':'ready','url':f"/dnf-gm/api/v1/assets/{pvf_sha}/{row['sha256']}.png",'sha256':row['sha256'],'width':row['width'],'height':row['height'],'note':MESSAGES['ready']}
        actual=row['state'] if row is not None and row['state'] in MESSAGES else state
        if actual=='ready':actual='unavailable'
        return {'state':actual,'url':None,'note':MESSAGES.get(actual,MESSAGES['unavailable'])}

    def decorate(self,pvf_sha,items):
        if not items:return
        with self.connection(pvf_sha) as (c,state):
            found={}
            if c:
                try:
                    ids=sorted(set(i['id'] for i in items))
                    for offset in range(0,len(ids),400):
                        group=ids[offset:offset+400]
                        rows=c.execute('SELECT i.item_id,i.sha256,i.state,f.width,f.height FROM item_images i LEFT JOIN files f ON f.sha256=i.sha256 WHERE item_id IN ('+','.join('?' for _ in group)+')',group)
                        found.update({r['item_id']:r for r in rows})
                except sqlite3.Error:state='unavailable';found={}
            for item in items:item['image']=self.image(found.get(item['id']),pvf_sha,'missing' if state=='ready' else state)

    def portrait(self,pvf_sha,job,grow_type,sex):
        with self.connection(pvf_sha) as (c,state):
            if c:
                try:
                    # Exact mapping preferred, then explicitly declared wildcard.
                    row=c.execute("SELECT p.sha256,f.width,f.height,'ready' state FROM portraits p JOIN files f ON f.sha256=p.sha256 WHERE p.job=? AND p.grow_type IN (?,-1) AND p.sex IN (?,-1) ORDER BY (p.grow_type=?) DESC,(p.sex=?) DESC LIMIT 1",(job,grow_type,sex,grow_type,sex)).fetchone()
                    return self.image(row,pvf_sha,'missing')
                except sqlite3.Error:state='unavailable'
            return self.image(None,pvf_sha,state)

    def status(self,pvf_sha):
        with self.connection(pvf_sha) as (c,state):
            result={'state':state,'note':'图片包版本匹配；实际可用情况以各物品为准' if state=='ready' else MESSAGES[state],'client_verified':False}
            if c:
                try:
                    meta=dict(c.execute('SELECT key,value FROM metadata'))
                    result.update(item_states=json.loads(meta.get('counts','{}')),portraits=int(meta.get('portraits','0')))
                except (sqlite3.Error,ValueError):return {'state':'unavailable','note':MESSAGES['unavailable']}
            return result

    def png(self,pvf_sha,digest):
        if not SHA.fullmatch(pvf_sha) or not SHA.fullmatch(digest):raise HTTPException(404,'图片不存在')
        with self.connection(pvf_sha) as (c,state):
            if c is None:raise HTTPException(404,'图片不可用或版本不匹配')
            try:row=c.execute('SELECT width,height FROM files WHERE sha256=?',(digest,)).fetchone()
            except sqlite3.Error:raise HTTPException(404,'图片清单不可用') from None
            if row is None:raise HTTPException(404,'图片不存在')
        try:
            root=Path(self.settings.assets_dir).resolve();images=root/'images'
            if images.is_symlink():raise ValueError()
            # dir_fd and O_NOFOLLOW prevent leaf/intermediate symlink traversal.
            directory=os.open(images,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:fd=os.open(digest+'.png',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
            finally:os.close(directory)
            with os.fdopen(fd,'rb') as f:
                info=os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or not 33<=info.st_size<=2*1024*1024:raise ValueError()
                data=f.read(2*1024*1024+1)
            if not data.startswith(PNG_MAGIC) or data[12:16]!=b'IHDR' or hashlib.sha256(data).hexdigest()!=digest:raise ValueError()
            width,height=struct.unpack_from('>II',data,16)
            if not 1<=width<=512 or not 1<=height<=512 or width!=row['width'] or height!=row['height']:raise ValueError()
            return data
        except (OSError,ValueError,struct.error):raise HTTPException(404,'图片缺失或校验失败') from None
