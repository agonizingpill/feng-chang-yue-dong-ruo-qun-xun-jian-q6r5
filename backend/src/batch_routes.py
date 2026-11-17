from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor
from .batch_models import FeedBatch
from .batch_schemas import PreviewInput,ConfirmInput,BatchCancelInput
from . import batch_service
router=APIRouter()
@router.get('/feed-batches')
def batches(user=Depends(current),db=Depends(session)):
    rows=db.scalars(select(FeedBatch).order_by(FeedBatch.id.desc())).all()
    return [batch_service.detail(db,b) for b in rows]
@router.post('/feed-batches/preview')
def preview(body:PreviewInput,user=Depends(editor),db=Depends(session)):return batch_service.preview(db,body,user)
@router.post('/feed-batches')
def confirm(body:ConfirmInput,user=Depends(editor),db=Depends(session)):return batch_service.confirm(db,body,user)
@router.post('/feed-batches/{key}/cancel')
def cancel(key:int,body:BatchCancelInput,user=Depends(editor),db=Depends(session)):return batch_service.cancel_batch(db,key,body,user)
