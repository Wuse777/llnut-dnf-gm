"""Typed campaign definitions. The activated reward and audience are immutable."""
from typing import Literal
from pydantic import Field, StrictInt, model_validator
from .models import Model, RewardTargets


class CampaignSave(Model):
    campaign_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    expected_revision: StrictInt = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=1000)
    status: Literal['draft', 'active', 'paused', 'archived'] = 'draft'
    dedupe: Literal['account', 'character'] = 'account'
    targets: RewardTargets
    template_id: StrictInt = Field(ge=1)
    template_version: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def meaningful(self):
        self.name = self.name.strip()
        self.reason = self.reason.strip()
        if not self.name or not self.reason:
            raise ValueError('请填写活动名称和操作原因')
        if self.campaign_id is None and self.status not in ('draft', 'active'):
            raise ValueError('新活动只能保存草稿或启用')
        return self
