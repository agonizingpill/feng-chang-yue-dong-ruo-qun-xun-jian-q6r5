"""并发确认契约测试。
生产栈为PostgreSQL：确认事务以with_for_update锁定全部巡检/蜂箱/批次，两人并发确认被行锁串行，
后到者指纹复核失效整批拒绝。SQLite不支持行锁，本文件以确定性顺序验证同一契约：
后到确认必被拒、不超领不重复；同token并发重试回到原批（唯一约束保证）。
运行：cd /workspace/backend && DATABASE_URL=sqlite:////tmp/batchconc.db SEED_DEMO=false PYTHONPATH=/workspace/backend python3 /workspace/test-artifacts/batch-test/test_concurrent.py
"""
import os,threading,uuid
from datetime import date
from fastapi.testclient import TestClient

os.environ.setdefault('DATABASE_URL','sqlite:////tmp/batchconc.db')
os.environ.setdefault('SEED_DEMO','false')
if os.path.exists('/tmp/batchconc.db'):os.remove('/tmp/batchconc.db')

from src.app import app
from src.database import Session
from src.models import User,Hive,Visit,CareAction
from src.resource_models import FeedLot
from src.batch_models import FeedBatch,FeedBatchIssue
from src.auth import hash_password

with TestClient(app) as client:
    with Session() as db:
        db.add(User(email='beekeeper@shanjing.test',password=hash_password('Hive2026!'),role='beekeeper'))
        for i in range(1,5):
            db.add(Hive(id=i,code=f'H-{i:03}',site='山荆东坡',queen_present=True,colony_frames=8,care_state='observe'))
            db.add(Visit(id=i,code=f'V-C-{i:03}',hive_id=i,weight_kg=20,temperature=33,activity=40,feed_left=1,
                queen_seen=True,colony_frames=8,anomaly_score=-0.1*i,anomaly_flag=True,decision_margin=0,status='screened'))
        db.add(FeedLot(id=1,code='LOT-X',received_kg=3,available_kg=3,expires_on=date(2027,6,1),state='active'))
        db.commit()
    r=client.post('/auth/login',json={'email':'beekeeper@shanjing.test','password':'Hive2026!'})
    bee={'Authorization':'Bearer '+r.json()['token']}
    items=[{'hive_id':i,'feed_kg':1.5} for i in range(1,5)]  # 共6kg需求，库存仅3kg

    # 两人基于同一状态预览，先后确认：先者生效，后者指纹失效整批拒绝（PG上行锁保证串行）
    fpA=client.post('/feed-batches/preview',json={'items':items},headers=bee).json()['fingerprint']
    fpB=client.post('/feed-batches/preview',json={'items':items},headers=bee).json()['fingerprint']
    assert fpA==fpB
    rA=client.post('/feed-batches',json={'token':uuid.uuid4().hex,'fingerprint':fpA,'items':items},headers=bee)
    assert rA.status_code==200,rA.text
    rB=client.post('/feed-batches',json={'token':uuid.uuid4().hex,'fingerprint':fpB,'items':items},headers=bee)
    assert rB.status_code==409 and '整批拒绝' in rB.json()['detail'],rB.text
    print('PASS 后到确认整批拒绝:',rB.json()['detail'])
    with Session() as db:
        issued=round(sum(l.kg for l in db.query(FeedBatchIssue).all()),4)
        left=db.get(FeedLot,1).available_kg
        assert db.query(FeedBatch).count()==1 and issued==3.0 and left==0.0,f'FAIL 超领或重复: {issued}/{left}'
        assert db.query(CareAction).count()==2,'FAIL 重复安排'
    print(f'PASS 不超领不重复安排: 领{issued}kg 余{left}kg 计划2箱')

    # 同token并发重试：唯一约束兜底，两请求都回到同一批，不新增也不重复扣料
    with Session() as db:
        db.get(FeedLot,1).available_kg=2;db.commit()
    fp2=client.post('/feed-batches/preview',json={'items':[{'hive_id':2,'feed_kg':1.0}]},headers=bee).json()['fingerprint']
    tok=uuid.uuid4().hex;retry={}
    barrier=threading.Barrier(3)
    def again(name):
        barrier.wait()
        r=client.post('/feed-batches',json={'token':tok,'fingerprint':fp2,'items':[{'hive_id':2,'feed_kg':1.0}]},headers=bee)
        retry[name]=(r.status_code,r.json().get('id') if r.status_code==200 else r.json())
    t1=threading.Thread(target=again,args=('R1',));t2=threading.Thread(target=again,args=('R2',))
    t1.start();t2.start();barrier.wait();t1.join();t2.join()
    ids={v[1] for v in retry.values()}
    assert all(s==200 for s,_ in retry.values()) and len(ids)==1,f'FAIL 同token重试应回到原批: {retry}'
    with Session() as db:
        assert db.query(FeedBatch).count()==2,'FAIL 不应新增计划'
        assert db.get(FeedLot,1).available_kg==1.0,'FAIL 不应重复扣料'
    print(f'PASS 同token并发重试回到原批: {retry}')
    print('并发契约测试全部通过')
