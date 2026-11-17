from pydantic import BaseModel,Field,ConfigDict,field_validator
class Inputs(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
class BatchDose(Inputs):
    hive_id:int
    feed_kg:float=Field(gt=0,le=3)
class PreviewInput(Inputs):
    items:list[BatchDose]=Field(min_length=1,max_length=160)
    @field_validator('items')
    @classmethod
    def unique_hives(cls,v):
        ids=[x.hive_id for x in v]
        if len(set(ids))!=len(ids):raise ValueError('同一蜂箱不能重复提交用量')
        return v
class ConfirmInput(PreviewInput):
    token:str=Field(min_length=8,max_length=64,pattern=r'^[A-Za-z0-9-]+$')
    fingerprint:str=Field(min_length=32,max_length=64)
class BatchCancelInput(Inputs):
    reason:str=Field(min_length=5,max_length=300)
    @field_validator('reason')
    @classmethod
    def reason_required(cls,v):
        if len(v.strip())<5:raise ValueError('取消依据至少5字')
        return v.strip()
