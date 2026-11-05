from typing import Literal, Annotated
from .limits import MAIL_GOLD_MAX, MAIL_ITEM_QUANTITY_MAX
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


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


class RewardOverrides(Model):
    """Complete one-off reward contents; never updates the source gift version."""
    items: list[Attachment] = Field(max_length=20)
    gold: StrictInt = Field(ge=0, le=MAIL_GOLD_MAX)
    mail_title: str = Field(default='', max_length=40)
    message: str = Field(max_length=60)
    currency_rewards: CurrencyRewards


class Preview(Model):
    support_case_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    action: Literal['currency', 'mail', 'ban', 'unban', 'equipment-unlock', 'reward']
    uid: StrictInt = Field(ge=1, le=2147483647)
    charac_no: StrictInt | None = Field(default=None, ge=1, le=2147483647)
    currency: Literal['cera', 'cera_point', 'mileage'] | None = None
    delta: StrictInt | None = Field(default=None, ge=-1000000000, le=1000000000)
    reason: str = Field(min_length=1, max_length=200)
    items: list[Attachment] = Field(default_factory=list, max_length=20)
    gold: StrictInt = Field(default=0, ge=0, le=MAIL_GOLD_MAX)
    lock_keys: list[StrictInt] = Field(default_factory=list, max_length=100)
    mail_title: str = Field(default='', max_length=40)
    message: str = Field(default='GM rewards', max_length=60)
    template_id: StrictInt | None = Field(default=None, ge=1)
    template_version: StrictInt | None = Field(default=None, ge=1)
    template_overrides: RewardOverrides | None = None
    currency_rewards: CurrencyRewards = Field(default_factory=CurrencyRewards)


class Confirm(Model):
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class Gift(Model):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    expected_version: StrictInt = Field(ge=0)
    items: list[Attachment] = Field(default_factory=list, max_length=20)
    gold: StrictInt | None = Field(default=None, ge=0, le=MAIL_GOLD_MAX)
    mail_title: str = Field(default='', max_length=40)
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
    mail_title: str = Field(default='', max_length=40)
    message: str = Field(default='GM rewards',max_length=60)
    currency_rewards: CurrencyRewards = Field(default_factory=CurrencyRewards)
    template_id: StrictInt | None = Field(default=None,ge=1)
    template_version: StrictInt | None = Field(default=None,ge=1)
    template_overrides: RewardOverrides | None = None


class RewardTargets(Model):
    mode: Literal['selected','accounts','filtered','online','all'] = 'selected'
    charac_nos: list[StrictInt] = Field(default_factory=list,max_length=5000)
    account_uids: list[StrictInt] = Field(default_factory=list,max_length=5000)
    account_names: list[Annotated[str,Field(min_length=1,max_length=255)]] = Field(default_factory=list,max_length=1000)
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


class UnlockTarget(Model):
    uid: StrictInt = Field(ge=1,le=2147483647)
    charac_no: StrictInt = Field(ge=1,le=2147483647)
    lock_keys: list[StrictInt] = Field(min_length=1,max_length=100)


class UnlockBatchPreview(Model):
    targets: list[UnlockTarget] = Field(min_length=1,max_length=20)
    reason: str = Field(min_length=1,max_length=200)


class CleanupPreview(Model):
    names: list[str] = Field(min_length=1,max_length=5)
    reason: str = Field(min_length=1,max_length=200)


class CleanupConfirm(Confirm):
    confirmation: Literal['删除旧GM产物']


class NativePreview(Model):
    action: Literal['native-notice', 'native-kick', 'native-ban-kick']
    uid: StrictInt | None = Field(default=None, ge=1, le=2147483647)
    message: str = Field(default='', max_length=254)
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def valid_target(self):
        from .native_control import notice_packet
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError('请填写操作原因')
        if self.action == 'native-notice':
            if self.uid is not None:
                raise ValueError('全服公告不能指定单个账号')
            notice_packet(self.message)
        elif self.uid is None or self.message:
            raise ValueError('踢人须选择账号，不能附加聊天内容')
        return self


class SchedulePreview(Model):
    title: str = Field(min_length=1, max_length=100)
    kind: Literal['reward', 'notice']
    first_due: StrictInt = Field(ge=1, le=4102444800)
    recurrence: Literal['once', 'daily', 'weekly'] = 'once'
    end_at: StrictInt | None = Field(default=None, ge=1, le=4102444800)
    reward_job: RewardJob | None = None
    notice: NativePreview | None = None

    @model_validator(mode='after')
    def valid_definition(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError('请填写计划名称')
        if self.kind == 'reward':
            if self.reward_job is None or self.notice is not None:
                raise ValueError('奖励计划需要完整奖励定义，不能混入公告')
            self.reward_job.reason = self.reward_job.reason.strip()
            if not self.reward_job.reason:
                raise ValueError('请填写奖励计划的操作原因')
        elif self.notice is None or self.notice.action != 'native-notice' or self.reward_job is not None:
            raise ValueError('公告计划只允许全服公告，不能定时踢人或封禁')
        if self.end_at is not None and (self.end_at < self.first_due or self.recurrence == 'once'):
            raise ValueError('结束时间须不早于首次时间；一次性计划不需要结束时间')
        return self


class ActivateSchedule(Confirm):
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledge_recurring: bool = False
    acknowledge_repeat: bool = False
    all_server_confirmation: str = Field(default='', max_length=20)


class ScheduleControl(Model):
    action: Literal['pause', 'resume', 'cancel']
    acknowledge_attention: bool = False


class InventoryPreview(Model):
    action: Literal['item-edit','item-reclaim','item-restore']
    uid: StrictInt = Field(ge=1,le=2147483647)
    charac_no: StrictInt = Field(ge=1,le=2147483647)
    container: Literal['inventory','equipment','warehouse','account_warehouse']
    slot: StrictInt = Field(ge=0,le=1023)
    reference: str = Field(pattern=r'^[a-f0-9]{64}$')
    changes: dict[str,StrictInt] = Field(default_factory=dict,max_length=8)
    source_operation_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(min_length=1,max_length=200)

    @model_validator(mode='after')
    def consistent(self):
        from .inventory_codec import FIELDS
        if not self.reason.strip():raise ValueError('请填写操作原因')
        if set(self.changes)-FIELDS:raise ValueError('不支持的装备字段')
        if self.action=='item-edit':
            if not self.changes or self.source_operation_id:raise ValueError('编辑须提供修改字段，不能混用历史恢复')
        elif self.changes:raise ValueError('回收或恢复不能混入属性修改')
        if (self.action=='item-restore') != bool(self.source_operation_id):raise ValueError('恢复必须指定原操作编号')
        return self
