"""批量饲喂安排集成测试：预览排序/纳入条件/跨批领料/缺料、确认幂等与并发拒绝、取消退料、旧单兼容。
运行：cd /workspace/backend && DATABASE_URL=sqlite:////tmp/batchtest.db SEED_DEMO=false PYTHONPATH=/workspace/backend python3 /workspace/test-artifacts/batch-test/test_batch.py
"""
import os,sys,uuid
from datetime import date
from fastapi.testclient import TestClient

os.environ.setdefault('DATABASE_URL','sqlite:////tmp/batchtest.db')
os.environ.setdefault('SEED_DEMO','false')
if os.path.exists('/tmp/batchtest.db'):os.remove('/tmp/batchtest.db')

from src.app import app
from src.database import Session
from src.models import User,Hive,Visit,CareAction
from src.resource_models import FeedLot,FeedIssue
from src.batch_models import FeedBatch,FeedBatchItem,FeedBatchIssue
from src.auth import hash_password

PASS=[]
def check(name,cond,extra=''):
    assert cond,f'FAIL {name} {extra}'
    PASS.append(name);print(f'PASS {name} {extra}')

with TestClient(app) as client:
    with Session() as db:
        for role in ['admin','beekeeper','viewer']:
            db.add(User(email=role+'@shanjing.test',password=hash_password('Hive2026!'),role=role))
        # H-001..H-006 有王可安排；H-007 无王；H-008 有未结处置
        for i in range(1,9):
            db.add(Hive(id=i,code=f'H-{i:03}',site='山荆东坡',queen_present=i!=7,colony_frames=8,care_state='observe'))
        db.flush()
        scores={1:-0.30,2:-0.30,3:-0.50,4:-0.10,5:0.20,6:0.30,7:-0.60,8:-0.40}
        for i in range(1,9):
            db.add(Visit(id=i,code=f'V-T-{i:03}',hive_id=i,weight_kg=20+i,temperature=33,activity=40,feed_left=1.0,
                queen_seen=i!=7,colony_frames=8,anomaly_score=scores[i],anomaly_flag=scores[i]<0,decision_margin=0,status='screened'))
        db.flush()
        db.add(CareAction(id=1,visit_id=8,kind='feed',feed_kg=1.0,status='planned'))  # H-008 未结处置
        db.add(FeedLot(id=1,code='LOT-A',received_kg=2,available_kg=2,expires_on=date(2027,1,1),state='active'))
        db.add(FeedLot(id=2,code='LOT-B',received_kg=3,available_kg=3,expires_on=date(2027,6,1),state='active'))
        db.add(FeedLot(id=3,code='LOT-Q',received_kg=10,available_kg=10,expires_on=date(2027,6,1),state='quarantine'))
        db.add(FeedLot(id=4,code='LOT-E',received_kg=10,available_kg=10,expires_on=date(2020,1,1),state='active'))
        db.commit()
    def login(email):
        r=client.post('/auth/login',json={'email':email,'password':'Hive2026!'})
        return {'Authorization':'Bearer '+r.json()['token']}
    bee=login('beekeeper@shanjing.test');adm=login('admin@shanjing.test');view=login('viewer@shanjing.test')

    items=[{'hive_id':i,'feed_kg':1.5} for i in range(1,9)]
    r=client.post('/feed-batches/preview',json={'items':items},headers=view)
    check('观察员预览被拒',r.status_code==403)
    r=client.post('/feed-batches/preview',json={'items':items},headers=bee)
    check('预览成功',r.status_code==200,r.text)
    p=r.json()
    arranged=[a['hive_code'] for a in p['items']]
    check('排序：分值升序同分按箱号',arranged==['H-003','H-001','H-002'],str(arranged))
    check('缺料箱为后三箱',[s['hive_code'] for s in p['shortage']]==['H-004','H-005','H-006'],str(p['shortage']))
    check('无王与未结处置被排除',{e['hive_code'] for e in p['excluded']}=={'H-007','H-008'},str(p['excluded']))
    h1=next(a for a in p['items'] if a['hive_code']=='H-001')
    check('单箱跨批领料',[(l['lot_code'],l['kg']) for l in h1['allocations']]==[('LOT-A',0.5),('LOT-B',1.0)],str(h1['allocations']))
    check('按有效期近先领',p['items'][0]['allocations'][0]['lot_code']=='LOT-A')
    check('缺口计算',all(abs(s['missing_kg']-1.0)<1e-6 for s in p['shortage']),str(p['shortage']))
    fp=p['fingerprint']

    # 确认：计划与领料一起生效
    token=uuid.uuid4().hex
    r=client.post('/feed-batches',json={'token':token,'fingerprint':fp,'items':items},headers=bee)
    check('确认成功',r.status_code==200,r.text)
    batch=r.json()
    check('整批3箱共4.5kg',len(batch['items'])==3 and abs(batch['total_kg']-4.5)<1e-6,str(batch['total_kg']))
    with Session() as db:
        lots={l.code:l.available_kg for l in db.query(FeedLot).all()}
        check('库存按批扣减',lots['LOT-A']==0 and lots['LOT-B']==0.5,str(lots))
        cares=db.query(CareAction).filter(CareAction.id>1).all()
        check('计划已生成且为planned',len(cares)==3 and all(c.status=='planned' and c.kind=='feed' for c in cares))
        visits={v.id:v.status for v in db.query(Visit).all()}
        check('巡检转入处置中',all(visits[i]=='caring' for i in [1,2,3]))
        hives={h.id:h.care_state for h in db.query(Hive).all()}
        check('蜂箱转入处置中',all(hives[i]=='caring' for i in [1,2,3]))
        lines=db.query(FeedBatchIssue).all()
        check('领料行4条(一箱跨批)',len(lines)==4 and abs(sum(l.kg for l in lines)-4.5)<1e-6)

    # 未收到回执重试：同token不新增计划也不再扣料，仍回到原批
    r=client.post('/feed-batches',json={'token':token,'fingerprint':fp,'items':items},headers=bee)
    check('重试回到原批',r.status_code==200 and r.json()['id']==batch['id'])
    with Session() as db:
        check('重试不超领不重复安排',db.query(FeedBatch).count()==1 and db.query(FeedBatchIssue).count()==4
            and db.query(CareAction).filter(CareAction.id>1).count()==3
            and abs(db.get(FeedLot,2).available_kg-0.5)<1e-6)

    # 并发场景：两人基于同一指纹预览，先确认者生效，后者整批拒绝
    r=client.post('/feed-batches/preview',json={'items':[{'hive_id':4,'feed_kg':0.5}]},headers=bee)
    fp2=r.json()['fingerprint']
    r=client.post('/feed-batches',json={'token':uuid.uuid4().hex,'fingerprint':fp2,'items':[{'hive_id':4,'feed_kg':0.5}]},headers=bee)
    check('第二人确认成功(库存够)',r.status_code==200,r.text)
    r=client.post('/feed-batches',json={'token':uuid.uuid4().hex,'fingerprint':fp2,'items':[{'hive_id':5,'feed_kg':0.5}]},headers=bee)
    check('库存变化后旧指纹整批拒绝',r.status_code==409 and '重新预览' in r.json()['detail'],r.text)

    # 巡检变化同样整批拒绝
    r=client.post('/feed-batches/preview',json={'items':[{'hive_id':6,'feed_kg':0.5}]},headers=bee)
    fp3=r.json()['fingerprint']
    r=client.post('/visits',json={'code':'V-T-101','hive_id':6,'weight_kg':26,'temperature':33,'activity':40,'feed_left':1,'queen_seen':True,'colony_frames':8},headers=bee)
    check('登记新巡检',r.status_code==200,r.text)
    r=client.post('/feed-batches',json={'token':uuid.uuid4().hex,'fingerprint':fp3,'items':[{'hive_id':6,'feed_kg':0.5}]},headers=bee)
    check('巡检变化整批拒绝',r.status_code==409,r.text)

    # 批量计划不能走单箱领料重复扣料
    with Session() as db:
        batch_care=db.query(FeedBatchItem).first().care_id
    r=client.post('/feed-issues',json={'care_id':batch_care,'lot_id':2},headers=bee)
    check('批量计划禁止重复领料',r.status_code==409,r.text)

    # 执行其中一箱（H-003 的批量计划），执行后取消只退未执行项
    with Session() as db:
        care3=db.query(FeedBatchItem).filter(FeedBatchItem.hive_id==3).first().care_id
    r=client.post(f'/care/{care3}/execute',json={},headers=bee)
    check('批量计划可登记执行',r.status_code==200,r.text)
    with Session() as db:
        used=[l.state for l in db.query(FeedBatchIssue).all() if l.item_id==db.query(FeedBatchItem).filter(FeedBatchItem.hive_id==3).first().id]
        check('执行后领料变已用',used==['used'],str(used))
    r=client.post(f'/feed-batches/{batch["id"]}/cancel',json={'reason':'天气突变取消未执行项'},headers=bee)
    check('批量取消成功',r.status_code==200,r.text)
    with Session() as db:
        lots={l.code:l.available_kg for l in db.query(FeedLot).all()}
        # LOT-B：确认后0.5 − 第二笔0.5 + 退回H-001的1.0 + 退回H-002的1.5 = 2.5；已执行的H-003(LOT-A 1.5)不退
        check('未执行项退回各来源批次，已执行不退',lots['LOT-A']==0.5 and abs(lots['LOT-B']-2.5)<1e-6,str(lots))
        states={i.hive_id:i.state for i in db.query(FeedBatchItem).all()}
        check('项状态：执行used其余returned',states[3]=='used' and states[1]=='returned' and states[2]=='returned',str(states))
        cares={c.id:c.status for c in db.query(CareAction).all()}
        check('已执行项保持executed',cares[care3]=='executed')
    r=client.post(f'/feed-batches/{batch["id"]}/cancel',json={'reason':'再次取消应被拒绝'},headers=bee)
    check('重复批量取消被拒',r.status_code==409,r.text)

    # 旧单流程：单箱建计划→领料→取消退料 仍可用
    r=client.post('/care',json={'visit_id':5,'kind':'feed','feed_kg':1.0},headers=bee)
    check('旧流程单箱建计划',r.status_code==200,r.text)
    old_care=r.json()['id']
    r=client.post('/feed-issues',json={'care_id':old_care,'lot_id':2},headers=bee)
    check('旧流程单箱领料',r.status_code==200,r.text)
    r=client.post(f'/care/{old_care}/cancel',json={'reason':'旧单取消退料测试'},headers=bee)
    check('旧单仍可执行退料',r.status_code==200,r.text)
    with Session() as db:
        check('旧单退料回到原批',abs(db.get(FeedLot,2).available_kg-2.5)<1e-6,str(db.get(FeedLot,2).available_kg))
        check('旧领料单状态returned',db.query(FeedIssue).filter(FeedIssue.care_id==old_care).first().state=='returned')

    # 台账接口结构（前端台账页）
    r=client.get('/feed-batches',headers=view)
    check('观察员可查台账',r.status_code==200 and len(r.json())==2)
    first=[b for b in r.json() if b['id']==batch['id']][0]
    check('台账含依据与领退结果',all(k in first['items'][0] for k in ['anomaly_score','visit_code','care_status','lines']))

print(f'\n全部 {len(PASS)} 项断言通过')
