import hashlib,json
from datetime import date
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from .models import Hive,Visit,CareAction
from .resource_models import FeedLot,FeedIssue
from .batch_models import FeedBatch,FeedBatchItem,FeedBatchIssue
from .yard_service import require,audit

ACTIVE_CARE=['planned','executed','rechecked','needs_requeen']

def fingerprint(db):
    def rows(model,cols):return [[getattr(r,c) for c in cols] for r in db.scalars(select(model).order_by(model.id)).all()]
    payload={'hives':rows(Hive,['id','queen_present','colony_frames','care_state']),
        'visits':rows(Visit,['id','hive_id','status','anomaly_score','queen_seen']),
        'cares':rows(CareAction,['id','visit_id','kind','status','feed_kg']),
        'lots':rows(FeedLot,['id','available_kg','state','expires_on']),
        'issues':rows(FeedIssue,['id','care_id','lot_id','kg','state'])}
    return hashlib.sha256(json.dumps(payload,separators=(',',':'),default=str).encode()).hexdigest()

def build_plan(db,doses):
    requested={d.hive_id:d.feed_kg for d in doses}
    hids=list(requested)
    hives={h.id:h for h in db.scalars(select(Hive).where(Hive.id.in_(hids))).all()}
    latest_ids=select(func.max(Visit.id)).where(Visit.hive_id.in_(hids)).group_by(Visit.hive_id)
    visits={v.hive_id:v for v in db.scalars(select(Visit).where(Visit.id.in_(latest_ids))).all()}
    busy=set(db.scalars(select(Visit.hive_id).join(CareAction,CareAction.visit_id==Visit.id).where(Visit.hive_id.in_(hids),CareAction.status.in_(ACTIVE_CARE))).all())
    eligible=[];excluded=[]
    for hid in hids:
        hive=hives.get(hid)
        if not hive:excluded.append({'hive_id':hid,'hive_code':'','reason':'蜂箱不存在'});continue
        visit=visits.get(hid)
        if not visit or visit.status!='screened' or visit.anomaly_score is None:
            excluded.append({'hive_id':hid,'hive_code':hive.code,'reason':'最新巡检尚未完成筛查'});continue
        if not hive.queen_present:
            excluded.append({'hive_id':hid,'hive_code':hive.code,'reason':'当前无王，须换王而非饲喂'});continue
        if hid in busy:
            excluded.append({'hive_id':hid,'hive_code':hive.code,'reason':'存在未结处置'});continue
        eligible.append((hive,visit,requested[hid]))
    eligible.sort(key=lambda x:(x[1].anomaly_score,x[0].code))
    lots=db.scalars(select(FeedLot).where(FeedLot.state=='active',FeedLot.expires_on>=date.today()).order_by(FeedLot.expires_on,FeedLot.id)).all()
    remaining={lot.id:lot.available_kg for lot in lots}
    arranged=[];shortage=[]
    for rank,(hive,visit,kg) in enumerate(eligible,1):
        left=round(sum(remaining.values()),4)
        if left+1e-9<kg:
            shortage.append({'hive_id':hive.id,'hive_code':hive.code,'visit_id':visit.id,'anomaly_score':visit.anomaly_score,'feed_kg':kg,'covered_kg':left,'missing_kg':round(kg-left,4)});continue
        lines=[];need=kg
        for lot in lots:
            if need<=0:break
            take=min(remaining[lot.id],need)
            if take>0:
                lines.append({'lot_id':lot.id,'lot_code':lot.code,'expires_on':str(lot.expires_on),'kg':round(take,4)})
                remaining[lot.id]=round(remaining[lot.id]-take,4);need=round(need-take,4)
        arranged.append({'rank':rank,'hive_id':hive.id,'hive_code':hive.code,'visit_id':visit.id,'anomaly_score':visit.anomaly_score,'feed_kg':kg,'allocations':lines})
    return arranged,shortage,excluded,lots

def preview(db,body,user):
    arranged,shortage,excluded,lots=build_plan(db,body.items)
    if not arranged and not shortage:raise HTTPException(409,'没有符合批量安排的蜂箱：须最新筛查已完成、有王且无未结处置')
    return {'fingerprint':fingerprint(db),'items':arranged,'shortage':shortage,'excluded':excluded,
        'lots':[{'lot_id':lot.id,'code':lot.code,'available_kg':lot.available_kg,'expires_on':str(lot.expires_on)} for lot in lots]}

def detail(db,batch):
    items=db.scalars(select(FeedBatchItem).where(FeedBatchItem.batch_id==batch.id).order_by(FeedBatchItem.id)).all()
    out=[]
    for item in items:
        hive=db.get(Hive,item.hive_id);visit=db.get(Visit,item.visit_id);care=db.get(CareAction,item.care_id)
        lines=db.scalars(select(FeedBatchIssue).where(FeedBatchIssue.item_id==item.id).order_by(FeedBatchIssue.id)).all()
        out.append({'id':item.id,'hive_id':item.hive_id,'hive_code':hive.code,'visit_id':item.visit_id,'visit_code':visit.code,
            'care_id':item.care_id,'care_status':care.status,'feed_kg':item.feed_kg,'anomaly_score':item.anomaly_score,'state':item.state,
            'lines':[{'id':line.id,'lot_id':line.lot_id,'lot_code':db.get(FeedLot,line.lot_id).code,'kg':line.kg,'state':line.state,'returned_by':line.returned_by} for line in lines]})
    return {'id':batch.id,'token':batch.token,'state':batch.state,'total_kg':batch.total_kg,'created_by':batch.created_by,'created_at':batch.created_at,'items':out}

def confirm(db,body,user):
    existing=db.scalar(select(FeedBatch).where(FeedBatch.token==body.token))
    if existing:return detail(db,existing)
    try:
        db.scalars(select(Visit).order_by(Visit.id).with_for_update()).all()
        hives={h.id:h for h in db.scalars(select(Hive).order_by(Hive.id).with_for_update()).all()}
        lots=db.scalars(select(FeedLot).order_by(FeedLot.id).with_for_update()).all()
        if fingerprint(db)!=body.fingerprint:
            again=db.scalar(select(FeedBatch).where(FeedBatch.token==body.token))
            if again:return detail(db,again)
            raise HTTPException(409,'巡检、处置或库存已有变化，整批拒绝，请重新预览计算')
        arranged,shortage,excluded,_=build_plan(db,body.items)
        if not arranged:
            again=db.scalar(select(FeedBatch).where(FeedBatch.token==body.token))
            if again:return detail(db,again)
            raise HTTPException(409,'当前状态下没有可安排的蜂箱，请重新预览')
        lotmap={lot.id:lot for lot in lots}
        batch=FeedBatch(token=body.token,fingerprint=body.fingerprint,total_kg=round(sum(a['feed_kg'] for a in arranged),4),created_by=user.email)
        db.add(batch);db.flush()
        for a in arranged:
            visit=db.get(Visit,a['visit_id']);hive=hives[a['hive_id']]
            care=CareAction(visit_id=visit.id,kind='feed',feed_kg=a['feed_kg'],status='planned')
            db.add(care);db.flush()
            visit.status='caring';hive.care_state='caring'
            item=FeedBatchItem(batch_id=batch.id,hive_id=hive.id,visit_id=visit.id,care_id=care.id,feed_kg=a['feed_kg'],anomaly_score=a['anomaly_score'])
            db.add(item);db.flush()
            for line in a['allocations']:
                lot=lotmap[line['lot_id']];lot.available_kg=round(lot.available_kg-line['kg'],4)
                db.add(FeedBatchIssue(item_id=item.id,lot_id=lot.id,kg=line['kg']))
        audit(db,user,f'批量饲喂安排 {len(arranged)}箱 共{batch.total_kg}kg，按异常分值从低到高领料')
        db.commit()
    except IntegrityError:
        db.rollback()
        again=db.scalar(select(FeedBatch).where(FeedBatch.token==body.token))
        if again:return detail(db,again)
        raise
    return detail(db,batch)

def cancel_batch(db,key,body,user):
    batch=require(db,FeedBatch,key,True)
    items=db.scalars(select(FeedBatchItem).where(FeedBatchItem.batch_id==batch.id).order_by(FeedBatchItem.id).with_for_update()).all()
    returned=0
    for item in items:
        care=db.scalar(select(CareAction).where(CareAction.id==item.care_id).with_for_update())
        if care.status!='planned':continue
        lines=db.scalars(select(FeedBatchIssue).where(FeedBatchIssue.item_id==item.id).with_for_update()).all()
        for line in lines:
            if line.state!='issued':raise HTTPException(409,'领料状态已变化，请刷新后重试')
            lot=require(db,FeedLot,line.lot_id,True)
            lot.available_kg=round(lot.available_kg+line.kg,4)
            line.state='returned';line.returned_by=user.email
        item.state='returned';care.status='cancelled'
        visit=require(db,Visit,care.visit_id,True);hive=require(db,Hive,visit.hive_id,True)
        visit.status='screened';hive.care_state='observe' if visit.queen_seen else 'needs_care'
        returned+=1
    if not returned:raise HTTPException(409,'没有未执行项可取消，已执行项不退料')
    if all(item.state=='returned' for item in items):batch.state='returned'
    audit(db,user,f'批量取消 {batch.id} 退回{returned}项至各来源批次，依据{body.reason}')
    db.commit();return detail(db,batch)
