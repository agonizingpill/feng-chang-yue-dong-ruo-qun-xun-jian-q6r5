// 无浏览器渲染冒烟：node test_render.mjs（在 frontend 目录下运行）
globalThis.localStorage={getItem:()=>JSON.stringify({role:'beekeeper',email:'beekeeper@shanjing.test',token:'t'}),removeItem(){}};
globalThis.document={querySelector:()=>null,querySelectorAll:()=>[]};
const {book}=await import('/workspace/frontend/src/notebook.js');
const batch=await import('/workspace/frontend/src/pages/batch.js');
book.hives=[{id:1,code:'H-001',site:'东坡',queen_present:true,colony_frames:8,care_state:'observe'},{id:2,code:'H-002',site:'东坡',queen_present:true,colony_frames:8,care_state:'observe'},{id:3,code:'H-003',site:'东坡',queen_present:false,colony_frames:4,care_state:'needs_care'}];
book.visits=[{id:11,hive_id:1,code:'V-1',status:'screened',anomaly_score:-0.31,queen_seen:true,colony_frames:8,weight_kg:20,temperature:33,activity:40,feed_left:1},{id:12,hive_id:2,code:'V-2',status:'screened',anomaly_score:-0.31,queen_seen:true,colony_frames:8,weight_kg:21,temperature:33,activity:40,feed_left:1},{id:13,hive_id:3,code:'V-3',status:'screened',anomaly_score:-0.5,queen_seen:false,colony_frames:4,weight_kg:18,temperature:33,activity:40,feed_left:1}];
book.care=[];book.issues=[];book.queens=[];book.moves=[];book.insulationLots=[];book.installs=[];book.spring=[];
book.lots=[{id:1,code:'FD-A',received_kg:30,available_kg:28.5,expires_on:'2027-11-30',state:'active'}];
book.batches=[{id:1,token:'abcdef1234567890',state:'confirmed',total_kg:3,created_by:'beekeeper@shanjing.test',created_at:'2026-11-17T08:30:00',items:[{id:1,hive_id:1,hive_code:'H-001',visit_id:11,visit_code:'V-1',care_id:9,care_status:'planned',feed_kg:1.5,anomaly_score:-0.31,state:'issued',lines:[{id:1,lot_id:1,lot_code:'FD-A',kg:1.5,state:'issued',returned_by:''}]},{id:2,hive_id:2,hive_code:'H-002',visit_id:12,visit_code:'V-2',care_id:10,care_status:'executed',feed_kg:1.5,anomaly_score:-0.31,state:'used',lines:[{id:2,lot_id:1,lot_code:'FD-A',kg:1.5,state:'used',returned_by:''}]}]}];
const html=batch.render();
for(const marker of ['H-001','H-002','批量安排与领退台账','FD-A 1.50kg','已领待执行','已用于饲喂','异常分值 -0.3100','生成批量预览','BATCH-1'])
    if(!html.includes(marker))throw new Error('缺少渲染内容: '+marker);
if(html.includes('H-003</strong><br><span class="code">V-3'))throw new Error('无王箱不应进入候选');
batch.bind(()=>{});
console.log('渲染冒烟通过，HTML长度',html.length);
