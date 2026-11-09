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

    def portrait_row(self,c,pvf_sha,row,meta):
        image=self.image(row,pvf_sha,'missing')
        if image['state']!='ready':return image
        image['match_level']='base' if row['grow_type']==-1 else 'growth'
        if meta.get('portrait_credits_version')=='1':
            credit=c.execute('SELECT kind,label,page,focus_x,focus_y FROM portrait_sources WHERE job=? AND grow_type=? AND sex=?',(row['job'],row['grow_type'],row['sex'])).fetchone()
            if credit is not None:
                from .portrait_credits import KINDS,source_page
                if credit['kind'] not in KINDS or not isinstance(credit['label'],str) or len(credit['label'])>120 or any(type(credit[k]) is not int or not 0<=credit[k]<=100 for k in ('focus_x','focus_y')):raise ValueError()
                image.update(source_kind=credit['kind'],source_label=credit['label'],source_page=source_page(credit['page']),focus_x=credit['focus_x'],focus_y=credit['focus_y'])
                image['note']={'official_promotional':'DNF官方宣传插画，非当前客户端NPK；职业示意，不代表角色装备／外观或精确觉醒阶段','client':'维护者提供的客户端职业插画，请查看来源标注；不代表角色装备或独立觉醒阶段插画，未验收客户端一致性','custom':'维护者提供的职业示意图，非游戏客户端像素验证'}[credit['kind']]
        return image

    def portrait(self,pvf_sha,job,grow_type,sex):
        with self.connection(pvf_sha) as (c,state):
            if c:
                try:
                    grow=grow_type&127 if type(grow_type) is int and -128<=grow_type<=255 else grow_type
                    profession=grow&15 if type(grow) is int and 0<=grow<=127 else grow
                    row=c.execute("SELECT p.*,f.width,f.height,'ready' state FROM portraits p JOIN files f ON f.sha256=p.sha256 WHERE p.job=? AND p.grow_type IN (?,?,-1) AND p.sex IN (?,-1) ORDER BY (p.grow_type=?) DESC,(p.grow_type=?) DESC,(p.sex=?) DESC LIMIT 1",(job,grow,profession,sex,grow,profession,sex)).fetchone()
                    if row is None:return self.image(None,pvf_sha,'missing')
                    image=self.portrait_row(c,pvf_sha,row,dict(c.execute('SELECT key,value FROM metadata')))
                    if image['state']=='ready':
                        image.update(requested_growth=grow,mapped_growth=row['grow_type'],awakening_specific=row['grow_type']>=16)
                        if row['grow_type']==profession and profession!=grow:
                            image['match_level']='profession'
                            image['note']+='；当前觉醒阶段使用同转职示意，未匹配独立觉醒插画'
                    return image
                except (sqlite3.Error,ValueError,TypeError):state='unavailable'
            return self.image(None,pvf_sha,state)

    def job_preview(self,pvf_sha,job):
        """Exact job's offline client default pose, separate from worn appearance."""
        with self.connection(pvf_sha) as (c,state):
            if c:
                try:
                    metadata=dict(c.execute('SELECT key,value FROM metadata'))
                    if metadata.get('job_previews_version')!='1':
                        return {'state':'missing','url':None,'note':'尚未安装此客户端的默认职业站姿'}
                    row=c.execute('SELECT j.*,f.width,f.height FROM job_previews j LEFT JOIN files f ON f.sha256=j.sha256 WHERE j.job=?',(job,)).fetchone()
                    image=self.image(row,pvf_sha,'missing')
                    if image['state']=='ready':
                        if row['source_kind']!='client_default_pose' or row['pose']!='waiting_first_frame':raise ValueError()
                        image.update(source_kind='client_default_pose',pose='waiting_first_frame',
                            note='匹配客户端的基础职业默认站姿首帧；不代表当前角色时装、武器外观或精确觉醒阶段',client_verified=False)
                    return image
                except (sqlite3.Error,ValueError,TypeError):state='unavailable'
            return self.image(None,pvf_sha,state)

    def outfit_preview(self,pvf_sha,job,recipe_sha256):
        """Serve only the exact saved-avatar recipe from an offline private pack."""
        if type(job) is not int or not 0<=job<=255 or not isinstance(recipe_sha256,str) or not SHA.fullmatch(recipe_sha256):
            return {'state':'unsupported','url':None,'note':'装扮配方无法确认'}
        with self.connection(pvf_sha) as (c,state):
            if c:
                try:
                    metadata=dict(c.execute('SELECT key,value FROM metadata'))
                    if metadata.get('outfit_previews_version')!='1':
                        return {'state':'missing','url':None,'note':'尚未安装此客户端的装扮配方预览'}
                    row=c.execute('SELECT o.*,f.width,f.height FROM outfit_previews o LEFT JOIN files f ON f.sha256=o.sha256 WHERE o.job=? AND o.recipe_sha256=?',(job,recipe_sha256)).fetchone()
                    image=self.image(row,pvf_sha,'missing')
                    if image['state']=='ready':
                        image.update(source_kind='saved_avatar_outfit',pose='waiting_first_frame',recipe_sha256=recipe_sha256,
                            note='匹配客户端的时装存档首帧；不含武器外观、染色、透明替代或实时变化',client_verified=False)
                    return image
                except (sqlite3.Error,ValueError,TypeError):state='unavailable'
            return self.image(None,pvf_sha,state)

    def appearance(self,pvf_sha,saved):
        """Resolve only registered v2 component records for this saved outfit."""
        from .appearance_manifest import assemble,failure
        if saved.get('state')!='ok':return {**failure(saved),'pvf_sha256':pvf_sha}
        with self.connection(pvf_sha) as (c,state):
            if c is None:return {**failure({'state':state},'appearance_pack_missing'),'pvf_sha256':pvf_sha}
            try:return {**assemble(c,pvf_sha,saved),'pvf_sha256':pvf_sha}
            except (sqlite3.Error,ValueError,TypeError,KeyError,StopIteration):
                return {**failure({'state':'unavailable'},'appearance_manifest_invalid'),'pvf_sha256':pvf_sha}

    def preview_appearance(self,pvf_sha,preset):
        """Read-only local fitting; accepts item identities, never drawing code."""
        from .outfit_recipe import canonical_appearance_recipe,OutfitRecipeError
        try:
            if not isinstance(preset,dict) or set(preset)-{'job','grow_type','sex','slots','direction','animation'}:raise ValueError()
            if preset.get('direction','right') not in ('right','mirror_left') or preset.get('animation','idle') not in ('idle','walk','attack'):raise ValueError()
            slots=preset.get('slots',[])
            if not isinstance(slots,list) or len(slots)>9:raise ValueError()
            if any(not isinstance(i,dict) or set(i)!={'slot','item_id'} for i in slots):raise ValueError()
            recipe,sha=canonical_appearance_recipe(preset['job'],preset.get('grow_type',0),
                [{'slot':i['slot'],'id':i['item_id'],'color1':0,'color2':0} for i in slots])
        except (KeyError,ValueError,TypeError,OutfitRecipeError):raise HTTPException(422,'试衣方案格式或职业／部位无效') from None
        result=self.appearance(pvf_sha,{'state':'ok','recipe':recipe,'recipe_sha256':sha,'items':recipe['items'],'reason_codes':[]})
        result.update(source_kind='local_fitting',scope='local_fitting',note='本地试衣方案，不是角色当前穿戴；不会写入游戏。未覆盖项目见下方清单')
        return result

    def atlas(self,pvf_sha,digest):
        """Independent authenticated atlas resource; never relax icon bounds."""
        if not SHA.fullmatch(pvf_sha) or not SHA.fullmatch(digest):raise HTTPException(404,'图集不存在')
        with self.connection(pvf_sha) as (c,state):
            if c is None:raise HTTPException(404,'图集不可用或版本不匹配')
            try:
                meta=dict(c.execute('SELECT key,value FROM metadata'))
                row=c.execute('SELECT width,height,bytes FROM appearance_atlases WHERE sha256=?',(digest,)).fetchone()
                if meta.get('appearance_version')!='2' or row is None:raise ValueError()
                expected=dict(row)
            except (sqlite3.Error,ValueError):raise HTTPException(404,'图集清单不可用') from None
        try:
            directory_path=Path(self.settings.assets_dir).resolve()/'atlases'
            if directory_path.is_symlink():raise ValueError()
            directory=os.open(directory_path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:fd=os.open(digest+'.png',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
            finally:os.close(directory)
            with os.fdopen(fd,'rb') as f:
                info=os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or not 33<=info.st_size<=16*1024*1024 or info.st_size!=expected['bytes']:raise ValueError()
                data=f.read(16*1024*1024+1)
            if not data.startswith(PNG_MAGIC) or data[12:16]!=b'IHDR' or hashlib.sha256(data).hexdigest()!=digest:raise ValueError()
            width,height=struct.unpack_from('>II',data,16)
            if not 1<=width<=2048 or not 1<=height<=2048 or width!=expected['width'] or height!=expected['height']:raise ValueError()
            return data
        except (OSError,ValueError,struct.error):raise HTTPException(404,'图集缺失或校验失败') from None

    def coverage(self,pvf_sha,state='all',page=1):
        from contextlib import closing
        from .catalog import Catalog
        if state not in ('all','ready','missing','missing_reference','ambiguous','unsupported'):raise HTTPException(422,'未知的图片状态')
        with self.connection(pvf_sha) as (c,pack_state):
            if not c:raise HTTPException(409,MESSAGES[pack_state])
            try:
                meta=dict(c.execute('SELECT key,value FROM metadata'))
                where='' if state=='all' else ' WHERE state=?';args=() if state=='all' else (state,)
                rows=c.execute('SELECT i.item_id,i.state,i.sha256,f.width,f.height FROM item_images i LEFT JOIN files f ON f.sha256=i.sha256'+where+' ORDER BY item_id LIMIT 21 OFFSET ?',(*args,(page-1)*20)).fetchall()
                items=[{'id':r['item_id'],'state':r['state'],'note':MESSAGES.get(r['state'],MESSAGES['unavailable']),'image':self.image(r,pvf_sha,'missing')} for r in rows[:20]]
                with closing(Catalog(self.settings).connect()) as catalog:
                    binding=dict(catalog.execute('SELECT key,value FROM metadata'))
                    if binding.get('pvf_sha256')!=pvf_sha:raise HTTPException(409,'物品索引与图片包PVF不匹配')
                    names={}
                    if items:
                        ids=[r['id'] for r in items]
                        names={r['id']:r['name'] for r in catalog.execute('SELECT id,name FROM items WHERE id IN ('+','.join('?' for _ in ids)+')',ids)}
                    jobs=json.loads(binding.get('jobs','{}'))
                for r in items:r['name']=names.get(r['id'],'索引中不存在的物品')
                portraits=[]
                for row in c.execute("SELECT p.*,f.width,f.height,'ready' state FROM portraits p JOIN files f ON f.sha256=p.sha256 ORDER BY p.job,p.grow_type,p.sex LIMIT 128"):
                    base=jobs.get(str(row['job']),{}).get('grow_names',[])
                    growth=row['grow_type']&15 if row['grow_type']>=0 else 0
                    name=base[growth] if growth<len(base) else '职业 #'+str(row['job'])
                    portraits.append({'job':row['job'],'grow_type':row['grow_type'],'sex':row['sex'],'name':name,'image':self.portrait_row(c,pvf_sha,row,meta)})
                return {'pvf_sha256':pvf_sha,'state':'ready','items':items,'page':page,'has_more':len(rows)>20,'portraits':portraits,'portrait_total':int(meta.get('portraits','0')),'item_states':json.loads(meta.get('counts','{}')),'client_verified':False}
            except (sqlite3.Error,ValueError,TypeError,KeyError):raise HTTPException(409,'图片覆盖信息不可读取，请核对私有图片包') from None

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
