"""Versioned administrator UI metadata, never a game write or reward draft."""
from contextlib import closing
import json
import re
import unicodedata
from typing import Literal
from fastapi import HTTPException
from pydantic import Field, StrictBool, StrictInt, ValidationError, model_validator
from .models import Model, CatalogFilters

PreferenceKind = Literal['catalog-filter', 'appearance', 'layout']
AVATAR_SLOTS = ('[hat avatar]', '[hair avatar]', '[face avatar]', '[breast avatar]',
    '[coat avatar]', '[skin avatar]', '[waist avatar]', '[pants avatar]', '[shoes avatar]')


class SavedCatalogFilters(CatalogFilters):
    sort: Literal['id', 'level_asc', 'level_desc', 'name'] = 'id'


class AppearanceSlot(Model):
    slot: Literal['[hat avatar]', '[hair avatar]', '[face avatar]', '[breast avatar]',
        '[coat avatar]', '[skin avatar]', '[waist avatar]', '[pants avatar]', '[shoes avatar]']
    item_id: StrictInt = Field(ge=1, le=4294967295)


class AppearancePreference(Model):
    job: StrictInt = Field(ge=0, le=255)
    grow_type: StrictInt = Field(default=0, ge=0, le=127)
    sex: StrictInt = Field(default=-1, ge=-1, le=1)
    direction: Literal['right', 'mirror_left'] = 'right'
    animation: Literal['idle', 'walk', 'attack'] = 'idle'
    slots: list[AppearanceSlot] = Field(default_factory=list, max_length=9)

    @model_validator(mode='after')
    def unique_slots(self):
        if len({s.slot for s in self.slots}) != len(self.slots):
            raise ValueError('每个外观部位只能保存一个物品')
        self.slots.sort(key=lambda s: AVATAR_SLOTS.index(s.slot))
        return self


class AppearancePreview(AppearancePreference):
    pvf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class LayoutPreference(Model):
    theme: Literal['light', 'dark', 'auto'] = 'light'
    layout: Literal['vertical', 'horizontal', 'vertical-mix', 'vertical-hybrid-header-first',
        'top-hybrid-sidebar-first', 'top-hybrid-header-first'] = 'vertical'
    density: Literal['comfortable', 'compact'] = 'comfortable'
    sidebar_collapsed: StrictBool = False
    show_job_art: StrictBool = True
    tab_visible: StrictBool = True


class PreferenceWrite(Model):
    pvf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_version: StrictInt = Field(ge=0, le=2147483646)
    payload: dict = Field(max_length=32)


class PreferenceDelete(Model):
    pvf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_version: StrictInt = Field(ge=1, le=2147483646)


def preference_payload(kind, payload):
    models={'catalog-filter':SavedCatalogFilters, 'appearance':AppearancePreference, 'layout':LayoutPreference}
    try:
        normalized=models[kind].model_validate(payload).model_dump()
    except (KeyError, ValidationError, TypeError, ValueError):
        raise HTTPException(422, '偏好内容与所选类型不匹配或超过范围') from None
    if len(json.dumps(normalized,ensure_ascii=False).encode('utf-8'))>16384:
        raise HTTPException(422, '偏好内容超过大小限制')
    return normalized


class UiPreferences:
    def __init__(self, db, catalog):
        self.db, self.catalog = db, catalog

    def scope(self, requested=None):
        with closing(self.catalog.connect()) as c:
            sha=self.catalog.meta(c).get('pvf_sha256','')
        if not re.fullmatch(r'[a-f0-9]{64}',sha):
            raise HTTPException(503, '物品索引缺少有效版本，无法读取界面偏好')
        if requested is not None and requested!=sha:
            raise HTTPException(409, 'PVF版本已改变，请重新读取当前版本的界面偏好')
        return sha

    @staticmethod
    def name(value):
        if (not isinstance(value,str) or not 1<=len(value)<=48 or value!=value.strip()
                or any(unicodedata.category(ch).startswith('C') or ch in '/\\' for ch in value)):
            raise HTTPException(422, '偏好名称须为1至48个可见字符，不能包含路径分隔符')
        return value

    @staticmethod
    def kind(value):
        if value not in ('catalog-filter','appearance','layout'):
            raise HTTPException(422, '未知的界面偏好类型')
        return value

    @staticmethod
    def view(sha, kind, name, row=None):
        row=row or {}
        payload=None
        if row.get('payload_json') is not None and not row.get('deleted'):
            try:payload=preference_payload(kind,json.loads(row['payload_json']))
            except (ValueError,TypeError,HTTPException):
                raise HTTPException(409, '保存的偏好格式无法核验，请核对后按当前版本覆盖') from None
        return {'pvf_sha256':sha,'kind':kind,'name':name,'version':row.get('version',0),
            'payload':payload,'deleted':bool(row.get('deleted',False)),
            'updated_at':row.get('updated_at'),'ui_only':True}

    def get(self, kind, name):
        kind,name=self.kind(kind),self.name(name);sha=self.scope()
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT version,payload_json,deleted,updated_at FROM dnf_gm.ui_preferences '
                'WHERE pvf_sha256=%s AND kind=%s AND name=%s',(sha,kind,name))
            return self.view(sha,kind,name,q.fetchone())

    def list(self, kind):
        kind=self.kind(kind);sha=self.scope()
        with self.db.connect() as c,c.cursor() as q:
            q.execute('SELECT name,version,payload_json,deleted,updated_at FROM dnf_gm.ui_preferences '
                'WHERE pvf_sha256=%s AND kind=%s AND deleted=0 ORDER BY updated_at DESC,name LIMIT 30',(sha,kind))
            items=[self.view(sha,kind,row['name'],row) for row in q.fetchall()]
        return {'pvf_sha256':sha,'kind':kind,'items':items,'limit':30,'ui_only':True,
            'note':'仅保存界面选择；不修改游戏装备、发放权限或待确认操作。PVF变化后不会自动套用。'}

    def write(self, kind, name, data, *, delete=False):
        kind,name=self.kind(kind),self.name(name);sha=self.scope(data['pvf_sha256'])
        payload=None if delete else preference_payload(kind,data['payload'])
        encoded=None if payload is None else json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        with self.db.connect() as c,c.cursor() as q:
            # Serialize bounded metadata updates, including first creation and
            # the per-PVF quota. This lock never touches game/operation rows.
            q.execute('SELECT revision FROM dnf_gm.ui_preference_state WHERE id=1 FOR UPDATE')
            if not q.fetchone():raise HTTPException(503, '界面偏好迁移未完成')
            q.execute('SELECT version,payload_json,deleted,updated_at FROM dnf_gm.ui_preferences '
                'WHERE pvf_sha256=%s AND kind=%s AND name=%s FOR UPDATE',(sha,kind,name))
            row=q.fetchone();version=row['version'] if row else 0
            if version!=data['expected_version']:
                raise HTTPException(409, '界面偏好已在其他页面修改，请重新读取后再保存')
            if delete and not row:raise HTTPException(404, '尚未保存此界面偏好')
            try:previous=json.loads(row['payload_json']) if row and row['payload_json'] is not None else None
            except (ValueError,TypeError):previous=None
            if row and bool(row['deleted'])==delete and (delete or previous==payload):
                c.commit();return self.view(sha,kind,name,row)
            if not delete and (not row or row['deleted']):
                q.execute('SELECT COUNT(*) total,SUM(deleted=0) active FROM dnf_gm.ui_preferences '
                    'WHERE pvf_sha256=%s AND kind=%s',(sha,kind))
                count=q.fetchone()
                if (count['active'] or 0)>=30 or (not row and count['total']>=100):
                    raise HTTPException(409, '当前版本的偏好数量已达上限，请复用已有名称')
            if row:
                q.execute('UPDATE dnf_gm.ui_preferences SET version=%s,payload_json=%s,deleted=%s,updated_at=UTC_TIMESTAMP(6) '
                    'WHERE pvf_sha256=%s AND kind=%s AND name=%s',(version+1,encoded,int(delete),sha,kind,name))
            else:
                q.execute('INSERT INTO dnf_gm.ui_preferences(pvf_sha256,kind,name,version,payload_json,deleted) '
                    'VALUES(%s,%s,%s,1,%s,0)',(sha,kind,name,encoded))
            q.execute('UPDATE dnf_gm.ui_preference_state SET revision=revision+1 WHERE id=1')
            q.execute('SELECT version,payload_json,deleted,updated_at FROM dnf_gm.ui_preferences '
                'WHERE pvf_sha256=%s AND kind=%s AND name=%s',(sha,kind,name))
            result=self.view(sha,kind,name,q.fetchone());c.commit()
        return result
