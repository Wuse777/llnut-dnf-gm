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


class CurrencyRewards(Model):
    cera: StrictInt = Field(default=0,ge=0,le=1000000000)
    cera_point: StrictInt = Field(default=0,ge=0,le=1000000000)
    mileage: StrictInt = Field(default=0,ge=0,le=1000000000)


class Preview(Model):
    action: Literal['currency', 'mail', 'ban', 'unban', 'equipment-unlock', 'reward']
    uid: StrictInt = Field(ge=1, le=2147483647)
    charac_no: StrictInt | None = Field(default=None, ge=1, le=2147483647)
    currency: Literal['cera', 'cera_point', 'mileage'] | None = None
    delta: StrictInt | None = Field(default=None, ge=-1000000000, le=1000000000)
    reason: str = Field(min_length=1, max_length=200)
    items: list[Attachment] = Field(default_factory=list, max_length=20)
    gold: StrictInt = Field(default=0, ge=0, le=MAIL_GOLD_MAX)
    lock_keys: list[StrictInt] = Field(default_factory=list, max_length=100)
    message: str = Field(default='GM rewards', max_length=60)
    template_id: StrictInt | None = Field(default=None, ge=1)
    template_version: StrictInt | None = Field(default=None, ge=1)
    currency_rewards: CurrencyRewards = Field(default_factory=CurrencyRewards)


class Confirm(Model):
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class Gift(Model):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    expected_version: StrictInt = Field(ge=0)
    items: list[Attachment] = Field(default_factory=list, max_length=20)
    gold: StrictInt | None = Field(default=None, ge=0, le=MAIL_GOLD_MAX)
    message: str | None = Field(default=None, max_length=60)
    category: str = Field(default='', max_length=32)
    currency_rewards: CurrencyRewards = Field(default_factory=CurrencyRewards)


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


class ItemSelection(Model):
    pvf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ItemFavorite(ItemSelection):
    favorite: bool


class RewardDefinition(Model):
    items: list[Attachment] = Field(default_factory=list,max_length=20)
    gold: StrictInt = Field(default=0,ge=0,le=MAIL_GOLD_MAX)
    message: str = Field(default='GM rewards',max_length=60)
    currency_rewards: CurrencyRewards = Field(default_factory=CurrencyRewards)
    template_id: StrictInt | None = Field(default=None,ge=1)
    template_version: StrictInt | None = Field(default=None,ge=1)


class RewardTargets(Model):
    mode: Literal['selected','filtered','online','all'] = 'selected'
    charac_nos: list[StrictInt] = Field(default_factory=list,max_length=5000)
    uid: StrictInt = Field(default=0,ge=0,le=2147483647)
    job: StrictInt | None = Field(default=None,ge=0,le=255)
    min_level: StrictInt = Field(default=0,ge=0,le=255)
    max_level: StrictInt = Field(default=255,ge=0,le=255)
    q: str = Field(default='',max_length=80)


class RewardJob(Model):
    targets: RewardTargets
    reward: RewardDefinition
    account_reward_mode: Literal['once_per_account','per_character'] = 'once_per_account'
    reason: str = Field(min_length=1,max_length=200)


class StartRewardJob(Confirm):
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    target_count: StrictInt = Field(ge=1)
    account_count: StrictInt = Field(ge=1)
    all_server_confirmation: str = Field(default='',max_length=20)
    acknowledge_repeat: bool = False


class RewardJobControl(Model):
    action: Literal['pause','resume','retry-failed','cancel','reconcile']
