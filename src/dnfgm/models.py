from typing import Literal
from .limits import MAIL_GOLD_MAX, MAIL_ITEM_QUANTITY_MAX
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Model):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(default='', max_length=80)


class Attachment(Model):
    id: StrictInt = Field(ge=1, le=4294967295)
    quantity: StrictInt = Field(ge=1, le=MAIL_ITEM_QUANTITY_MAX)


class Preview(Model):
    action: Literal['currency', 'mail', 'ban', 'unban', 'equipment-unlock']
    uid: StrictInt = Field(ge=1, le=2147483647)
    charac_no: StrictInt | None = Field(default=None, ge=1, le=2147483647)
    currency: Literal['cera', 'cera_point'] | None = None
    delta: StrictInt | None = Field(default=None, ge=-1000000000, le=1000000000)
    reason: str = Field(min_length=1, max_length=200)
    items: list[Attachment] = Field(default_factory=list, max_length=20)
    gold: StrictInt = Field(default=0, ge=0, le=MAIL_GOLD_MAX)
    lock_keys: list[StrictInt] = Field(default_factory=list, max_length=100)
    message: str = Field(default='GM rewards', max_length=60)
    template_id: StrictInt | None = Field(default=None, ge=1)
    template_version: StrictInt | None = Field(default=None, ge=1)


class Confirm(Model):
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class Gift(Model):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    expected_version: StrictInt = Field(ge=0)
    items: list[Attachment] = Field(min_length=1, max_length=20)


class CatalogFilters(Model):
    q: str = Field(default='', max_length=100)
    category: Literal['', 'equipment', 'material', 'consumable', 'special'] = ''
    allowed_only: bool = False
    state: Literal['', 'trial', 'verified', 'blocked'] = ''


class CatalogPolicyPreview(Model):
    item_id: StrictInt | None = Field(default=None,ge=1,le=4294967295)
    filters: CatalogFilters = Field(default_factory=CatalogFilters)
    enabled: bool
    reason: str = Field(min_length=1,max_length=200)
