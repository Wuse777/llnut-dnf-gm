from typing import Annotated,Literal
from pydantic import Field,StrictInt,model_validator
from .models import Model,Confirm

Category=Literal['reward','mail','unlock','stuck','account','other']
CaseStatus=Literal['open','in_progress','resolved']
Tag=Annotated[str,Field(min_length=1,max_length=24)]

class ProfileSave(Confirm):
    expected_revision:StrictInt=Field(ge=0,le=2147483647)
    notes:str=Field(default='',max_length=4000)
    tags:list[Tag]=Field(default_factory=list,max_length=10)

    @model_validator(mode='after')
    def clean(self):
        self.tags=[t.strip() for t in self.tags]
        if any(not t for t in self.tags) or len(set(self.tags))!=len(self.tags):raise ValueError('标签不能为空或重复')
        return self

class CaseCreate(Confirm):
    uid:StrictInt=Field(ge=1,le=2147483647)
    charac_no:StrictInt|None=Field(default=None,ge=1,le=2147483647)
    title:str=Field(min_length=1,max_length=120)
    category:Category='other'
    description:str=Field(min_length=1,max_length=4000)

    @model_validator(mode='after')
    def clean(self):
        if not self.title.strip() or not self.description.strip():raise ValueError('请填写问题标题与描述')
        self.title=self.title.strip();self.description=self.description.strip();return self

class CaseUpdate(Confirm):
    expected_revision:StrictInt=Field(ge=1,le=2147483647)
    title:str=Field(min_length=1,max_length=120)
    category:Category
    description:str=Field(min_length=1,max_length=4000)
    status:CaseStatus
    note:str=Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def clean(self):
        if any(not x.strip() for x in (self.title,self.description,self.note)):raise ValueError('标题、描述和处理说明不能为空')
        return self

class CaseEntry(Confirm):
    expected_revision:StrictInt=Field(ge=1,le=2147483647)
    note:str=Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def clean(self):
        if not self.note.strip():raise ValueError('请填写处理说明')
        return self

class CaseLink(CaseEntry):
    operation_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    relation:Literal['reference','compensation']='reference'
