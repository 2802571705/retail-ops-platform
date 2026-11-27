"""Run the real HTTP transaction endpoints against a fresh isolated PostgreSQL database."""
import argparse
import collections
import concurrent.futures
import csv
import json
import math
import os
import platform
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone, time as day_time
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8001)
args = parser.parse_args()
if args.port == 8000:
    raise SystemExit('验收服务不能占用日常业务端口8000。')
run = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
name = 'retailops_accept_' + run.lower()
out = ROOT / 'tests' / 'results' / run
out.mkdir(parents=True)
base = f'http://127.0.0.1:{args.port}'
url = make_url(os.getenv('DATABASE_URL') or (
    f'postgresql+psycopg://{quote(os.environ["POSTGRES_USER"],safe="")}:'
    f'{quote(os.environ["POSTGRES_PASSWORD"],safe="")}@127.0.0.1:'
    f'{os.getenv("POSTGRES_PORT","5432")}/{quote(os.environ["POSTGRES_DB"],safe="")}'))
if url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1','localhost'):
    raise SystemExit('仅允许本机 PostgreSQL 验收环境。')
admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
with admin.connect() as conn:
    conn.execute(text(f'CREATE DATABASE "{name}"'))
admin.dispose()
check_url = url.set(database=name)
env = {**os.environ, 'DATABASE_URL':check_url.render_as_string(hide_password=False),
       'JWT_SECRET':secrets.token_urlsafe(48), 'DEMO_ADMIN_PASSWORD':secrets.token_urlsafe(18)}
engine = create_engine(check_url)
records, cases, evidence, case_ids = [], [], {}, {}
proc = None
log = None
thread = None
completed = False
stop = threading.Event()
connections = []

def key(): return uuid.uuid4().hex

def request(path, token=None, body=None, idem=None, method='GET', case='setup', order_id=None):
    headers = {}
    if token: headers['Authorization'] = 'Bearer ' + token
    if idem: headers['Idempotency-Key'] = idem
    if body is not None: headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            status, raw, rid = r.status, r.read(), r.headers.get('X-Request-ID','')
    except urllib.error.HTTPError as e:
        status, raw, rid = e.code, e.read(), e.headers.get('X-Request-ID','')
    except (OSError, TimeoutError) as e:
        status, raw, rid = 0, str(e).encode(), ''
    elapsed = (time.perf_counter()-start)*1000
    try: result = json.loads(raw)
    except (ValueError, UnicodeError): result = {}
    error = result.get('error') or {}
    code = error.get('code') if isinstance(error,dict) else None
    data = result.get('data')
    records.append({'case':case,'method':method,'path':path,'order_id':order_id or (data.get('id') if isinstance(data,dict) else None),
                    'status':status,'code':code or ('OK' if 200<=status<300 else f'HTTP_{status}'),
                    'request_id':rid or result.get('request_id',''),'idempotency_key':idem or '', 'elapsed_ms':round(elapsed,3)})
    return status, code, data

def ok(*a, **kw):
    status, code, data = request(*a, **kw)
    if not 200<=status<300: raise RuntimeError(f'{a[0]}: {status} {code}')
    return data

def query(sql, **params):
    with engine.connect() as c: return [dict(r) for r in c.execute(text(sql),params).mappings()]

def require(condition, message):
    if not condition: raise RuntimeError(message)

def stock(pid):
    return query('SELECT available_qty FROM inventory WHERE store_id=:s AND product_id=:p',s=store,p=pid)[0]['available_qty']

def set_stock(pid, qty):
    delta = qty-stock(pid)
    if delta: ok(f'/admin/stores/{store}/stock-adjustments', admin_token,
                 {'product_id':pid,'delta_qty':delta,'reason':'正式接口验收库存准备'},key(),'POST')
    require(stock(pid)==qty,'库存准备失败')

def body(p, **extra):
    return {'store_id':store,'items':[{'item_type':'PRODUCT','product_id':p['product_id'],'quantity':1,
            'expected_price_version':p['price_version']}], 'user_coupon_id':None,'points_used':0,**extra}

def create(token, payload, idem=None, case='prepare'):
    return ok('/orders', token, payload, idem or key(), 'POST', case=case)

def call_order(o, token, action, idem, case):
    return request(f'/orders/{o}/'+action,token,idem=idem,method='POST',case=case,order_id=o)

def parallel(jobs):
    barrier = threading.Barrier(len(jobs))
    def invoke(job):
        barrier.wait(timeout=60)
        return job()
    start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results=list(pool.map(invoke,jobs))
    return results, round(time.perf_counter()-start,3)

FACT_SQL = '''SELECT o.id,o.status,o.payable_cents,o.points_used,o.user_coupon_id,
  (SELECT count(*) FROM payments p WHERE p.order_id=o.id) AS payments,
  (SELECT coalesce(sum(amount_cents),0) FROM payments p WHERE p.order_id=o.id) AS payment_cents,
  (SELECT count(*) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_rows,
  (SELECT coalesce(sum(delta_qty),0) FROM inventory_ledger l WHERE l.order_id=o.id) AS stock_delta,
  (SELECT count(*) FROM points_ledger l WHERE l.order_id=o.id) AS point_rows,
  (SELECT coalesce(sum(delta_points),0) FROM points_ledger l WHERE l.order_id=o.id) AS point_delta,
  (SELECT count(*) FROM user_coupons c WHERE c.redeemed_order_id=o.id) AS redeemed_coupons
  FROM orders o WHERE o.id=ANY(:ids) ORDER BY o.id'''

def facts(ids): return query(FACT_SQL,ids=ids)

def verify_fact(r, paid):
    require(r['status'] in (('PAID',) if paid else ('PENDING_PAYMENT','CANCELLED')),f"订单状态错误 {r}")
    if paid:
        require(r['payments']==1 and r['payment_cents']==r['payable_cents'] and r['stock_rows']==1 and r['stock_delta']==-1,
                f'支付或库存流水错误 {r}')
        earned=r['payable_cents']//100
        require(r['point_rows']==int(earned>0)+int(r['points_used']>0) and r['point_delta']==earned-r['points_used'] and r['redeemed_coupons']==int(r['user_coupon_id'] is not None),f'权益流水错误 {r}')
    else:
        require(r['payments']==r['payment_cents']==r['stock_rows']==r['stock_delta']==r['point_rows']==r['point_delta']==r['redeemed_coupons']==0,f'失败订单存在副作用 {r}')

def mark(case, ids, duration, before, after):
    case_ids[case]=ids
    evidence[case]={'orders':facts(ids),'stock_before':before,'stock_after':after}
    cases.append({'case':case,'passed':True,'duration_seconds':duration,'orders':len(ids),'stock_before':before,'stock_after':after})
    print(case,'PASS',flush=True)

def contention(case, qty):
    pid=product['product_id'];set_stock(pid,qty)
    orders=[create(t,body(product),case=case+'_create')['id'] for t in tokens]
    case_ids[case]=orders
    require(len(set(orders))==100,'订单必须独立')
    results,duration=parallel([lambda o=o,t=t,k=key():call_order(o,t,'pay',k,case) for o,t in zip(orders,tokens)])
    rows=facts(orders); evidence[case]={'orders':rows,'stock_before':qty,'stock_after':stock(pid)}
    successes=[r for r in results if r[0]==200]
    require(len(successes)==qty and sum(r[0]==409 and r[1]=='OUT_OF_STOCK' for r in results)==100-qty,'成功/库存不足计数不符，检查请求记录')
    require(len(rows)==100 and sum(r['status']=='PAID' for r in rows)==qty and stock(pid)==0,'订单或库存余额不符')
    for r in rows:
        require(r['status'] in ('PAID','PENDING_PAYMENT'),'不允许的订单状态')
        verify_fact(r,r['status']=='PAID')
    mark(case,orders,duration,qty,0)
    return orders

def monitor():
    while not stop.wait(.1):
        try:
            rows=query("SELECT count(*) FILTER (WHERE pid<>pg_backend_pid()) AS connections, count(*) FILTER (WHERE state='active' AND pid<>pg_backend_pid()) AS active FROM pg_stat_activity WHERE datname=current_database()")
            connections.append({'time':datetime.now(timezone.utc).isoformat(),**rows[0]})
        except Exception: break

def wallet_snapshot(uid, coupon, oid):
    return {'inventory':query('SELECT * FROM inventory WHERE store_id=:s AND product_id=:p',s=store,p=product['product_id']),
            'wallet':query('SELECT * FROM member_accounts WHERE user_id=:u',u=uid),
            'coupon':query('SELECT * FROM user_coupons WHERE id=:c',c=coupon),
            'order':query('SELECT * FROM orders WHERE id=:o',o=oid),'facts':facts([oid]),
            'idem':query('SELECT * FROM idempotency_requests WHERE scope=:s',s=f'orders:pay:{oid}')}

try:
    print('验收数据库:',name,flush=True)
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT/'backend',env=env,check=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/seed.py')],cwd=ROOT,env=env,check=True)
    admin_row=query("SELECT u.email,e.store_id FROM users u JOIN employees e ON e.user_id=u.id WHERE u.role='STORE_ADMIN' AND e.status='ACTIVE' ORDER BY e.id LIMIT 1")[0]
    store=admin_row['store_id']
    log=(out/'uvicorn.log').open('w',encoding='utf-8')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(args.port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
    # Wait for the spawned server to listen, then authenticate with its unique credentials.
    for _ in range(120):
        if proc.poll() is not None: raise RuntimeError('验收后端启动失败，查看 uvicorn.log')
        try:
            with urllib.request.urlopen(base+'/openapi.json',timeout=1): break
        except OSError: time.sleep(.5)
    else: raise RuntimeError('验收后端未启动')
    hq_email=query("SELECT email FROM users WHERE role='HQ_ADMIN' AND status='ACTIVE' ORDER BY id LIMIT 1")[0]['email']
    hq_token=ok('/auth/login',body={'email':hq_email,'password':env['DEMO_ADMIN_PASSWORD']},method='POST')['access_token']
    admin_token=ok('/auth/login',body={'email':admin_row['email'],'password':env['DEMO_ADMIN_PASSWORD']},method='POST')['access_token']
    product=next(p for p in ok(f'/stores/{store}/catalog') if p['price_cents']>=100)
    # Independent accounts avoid serializing all successful payments on a single points account.
    tokens=[];uids=[]
    password=secrets.token_urlsafe(16)
    for i in range(100):
        email=f'accept-{i+1}@retailops.com'
        user=ok('/auth/register',body={'email':email,'password':password,'display_name':f'验收用户{i+1}'},method='POST')
        uids.append(user['id'])
        tokens.append(ok('/auth/login',body={'email':email,'password':password},method='POST')['access_token'])
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    evidence['environment']={'database':name,'store_id':store,'product_id':product['product_id'],
        'product_name':product['name'],'platform':platform.platform(),'cpu':platform.processor(),
        'logical_cpus':os.cpu_count(),'python':sys.version,'postgres':query('SELECT version(),current_setting(\'transaction_isolation\') AS isolation,current_setting(\'max_connections\') AS max_connections')[0],
        'http_workers':1,'submitted_concurrency':100,'pool': 'pool_size=5, max_overflow=10, pool_timeout=30, async_semaphore=12'}
    c1=contention('C01',1);c2=contention('C02',50)
    # A paid consumer already has enough earned points. Issue a valid one-cent coupon as a fixture only in this database.
    winner=next(i for i,r in enumerate(facts(c2)) if r['status']=='PAID')
    # Creation was sequential; IDs sorted by creation order.
    uid,token=uids[winner],tokens[winner]
    set_stock(product['product_id'],1)
    with engine.begin() as c:
        tpl=c.scalar(text("INSERT INTO coupon_templates(name,scope,store_id,min_spend_cents,discount_cents,starts_at,ends_at,active) VALUES ('验收优惠券','STORE',:s,0,1,now()-interval '1 day',now()+interval '1 day',true) RETURNING id"),{'s':store})
        coupon=c.scalar(text("INSERT INTO user_coupons(user_id,template_id,status) VALUES (:u,:t,'AVAILABLE') RETURNING id"),{'u':uid,'t':tpl})
    oid=create(token,body(product,user_coupon_id=coupon,points_used=1),case='C03_create')['id']
    case_ids['C03']=[oid]
    before=wallet_snapshot(uid,coupon,oid); idem=key()
    # Deferred constraint trigger fires at COMMIT, after all application DML has been flushed.
    with engine.begin() as c:
        c.execute(text(f"""CREATE FUNCTION acceptance_abort_payment() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.order_id={int(oid)} THEN RAISE EXCEPTION 'STAGE10_COMMIT_FAILURE'; END IF; RETURN NEW; END; $$"""))
        c.execute(text('CREATE CONSTRAINT TRIGGER acceptance_abort_payment AFTER INSERT ON payments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION acceptance_abort_payment()'))
    try:
        result=call_order(oid,token,'pay',idem,'C03')
        after=wallet_snapshot(uid,coupon,oid)
        evidence['C03']={'before':before,'after':after,'fault':'deferred payment trigger at commit'}
        require(result[0]==500 and before==after,'C03 未实现完整回滚或未命中异常')
        verify_fact(after['facts'][0],False)
    finally:
        with engine.begin() as c:
            c.execute(text('DROP TRIGGER acceptance_abort_payment ON payments'))
            c.execute(text('DROP FUNCTION acceptance_abort_payment()'))
    # Retry the original key after the injected error is removed.
    require(call_order(oid,token,'pay',idem,'C03_retry')[0]==200,'回滚后原键重试失败')
    verify_fact(facts([oid])[0],True)
    require(stock(product['product_id'])==0,'C03 重试未正确扣减库存')
    evidence['C03']['retry']=wallet_snapshot(uid,coupon,oid)
    cases.append({'case':'C03','passed':True,'orders':1,'stock_before':1,'stock_after_failed_commit':1,'stock_after_retry':0})
    print('C03 PASS',flush=True)
    set_stock(product['product_id'],1)
    oid=create(tokens[0],body(product),case='C04_create')['id'];case_ids['C04']=[oid]
    results,duration=parallel([lambda a=a,k=key():call_order(oid,tokens[0],a,k,'C04') for a in ('pay','cancel')])
    row=facts([oid])[0];evidence['C04']={'orders':[row],'stock_before':1,'stock_after':stock(product['product_id'])}
    require(sum(r[0]==200 for r in results)==1 and sum(r[0]==409 and r[1]=='ORDER_STATE_CONFLICT' for r in results)==1,'支付与取消竞态异常')
    require(row['status'] in ('PAID','CANCELLED'),'竞态终态非法');paid=row['status']=='PAID';verify_fact(row,paid)
    require(stock(product['product_id'])==int(not paid),'竞态库存错误');mark('C04',[oid],duration,1,int(not paid))
    set_stock(product['product_id'],1)
    idem=key(); payload=body(product)
    results,duration=parallel([lambda:request('/orders',tokens[1],payload,idem,'POST',case='C05_create') for _ in range(10)])
    ids=[r[2]['id'] for r in results if r[0]==201];require(len(ids)==10 and len(set(ids))==1,'重复建单产生多个订单或失败')
    oid=ids[0];case_ids['C05']=[oid]
    changed={**payload,'items':[dict(payload['items'][0],quantity=2)]}
    conflict=request('/orders',tokens[1],changed,idem,'POST',case='C05_payload_conflict');require(conflict[:2]==(409,'IDEMPOTENCY_CONFLICT'),'同键异参未拒绝')
    paykey=key(); results,pay_duration=parallel([lambda:call_order(oid,tokens[1],'pay',paykey,'C05_pay') for _ in range(10)])
    require(all(r[0]==200 and r[2]['id']==oid for r in results),'同键支付重试异常')
    require(call_order(oid,tokens[1],'pay',key(),'C05_new_key')[:2]==(409,'ORDER_STATE_CONFLICT'),'新键重复支付未拒绝')
    verify_fact(facts([oid])[0],True);require(stock(product['product_id'])==0,'重复支付扣库异常')
    mark('C05',[oid],duration+pay_duration,1,0)
    # Check member balances against the ledger for the 100 independent registered accounts.
    mismatches=query('''SELECT a.user_id,a.points_balance,coalesce(sum(l.delta_points),0) AS ledger_balance
        FROM member_accounts a LEFT JOIN points_ledger l ON l.account_id=a.id WHERE a.user_id=ANY(:ids)
        GROUP BY a.id HAVING a.points_balance<>coalesce(sum(l.delta_points),0)''',ids=uids)
    evidence['points_balance_mismatches']=mismatches;require(not mismatches,'积分余额与流水不一致')
    # Compare the actual aggregate used by HQ sales-trend under identical parameters.
    trend_sql="""SELECT (paid_at AT TIME ZONE 'Asia/Shanghai')::date AS business_date,
        count(id) AS paid_order_count,sum(payable_cents) AS paid_sales_cents FROM orders
        WHERE status IN ('PAID','COMPLETED') AND paid_at>=:start AND paid_at<:end
        GROUP BY business_date ORDER BY business_date"""
    tz=ZoneInfo('Asia/Shanghai'); today=datetime.now(tz).date();params={'start':datetime.combine(today-timedelta(days=29),day_time.min,tzinfo=tz),'end':datetime.combine(today+timedelta(days=1),day_time.min,tzinfo=tz)}
    query_string=urlencode({'date_from':(today-timedelta(days=29)).isoformat(),'date_to':today.isoformat()})
    def explain(label):
        with engine.connect() as c:
            plan=c.scalar(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+trend_sql),params)
        (out/f'plan_{label}.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        # Actual application HTTP timings; sequential, not an extra concurrency scenario.
        for _ in range(10):
            trend=ok('/hq/analytics/sales-trend?'+query_string,hq_token,case='trend_'+label)
            detail=ok('/analytics/sales-detail?'+query_string,hq_token,case='detail_'+label)
            require(sum(x['paid_sales_cents'] for x in trend['items'])==detail['paid_sales_cents'], '销售明细与趋势实付金额不一致')
            require(sum(x['paid_order_count'] for x in trend['items'])==detail['paid_order_count'], '销售明细与趋势订单数量不一致')
    with engine.begin() as c:c.execute(text('ANALYZE orders'))
    explain('before')
    with engine.begin() as c:
        c.execute(text("CREATE INDEX ix_orders_paid_at_cover ON orders(paid_at) INCLUDE(id,payable_cents) WHERE status IN ('PAID','COMPLETED')"))
        c.execute(text('ANALYZE orders'))
    explain('after')
    evidence['index_note']='仅在验收库建立候选索引。小样本可能选择顺序扫描，不代表索引无效或已提速。'
    evidence['performance_period']={'date_from':(today-timedelta(days=29)).isoformat(),'date_to':today.isoformat(),'order_rows':query('SELECT count(*) AS n FROM orders')[0]['n'],'note':'每个实际报表接口前后各10次顺序查询，缓存状态未控制。'}
    completed=True
finally:
    stop.set()
    if thread is not None: thread.join(timeout=5)
    if proc is not None:
        proc.terminate()
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()
    if log:log.close()
    engine.dispose()
    if records:
        with (out/'requests.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    def percentile(values,p):return sorted(values)[math.ceil(len(values)*p)-1]
    metrics={}
    for label in sorted({r['case'] for r in records}):
        rs=[r for r in records if r['case']==label];values=[r['elapsed_ms'] for r in rs]
        metrics[label]={'n':len(rs),'p50_ms':percentile(values,.5),'p95_ms':percentile(values,.95),
            'status_codes':dict(collections.Counter(str(r['status'])+':'+r['code'] for r in rs)),
            'http_error_rate':sum(not 200<=r['status']<300 for r in rs)/len(rs),
            'transport_or_5xx_rate':sum(r['status']==0 or r['status']>=500 for r in rs)/len(rs)}
    (out/'summary.json').write_text(json.dumps({'completed':completed,'cases':cases,'metrics':metrics,'evidence':evidence,'connection_samples':connections},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    statements=[f'-- 连接数据库 {name}（不是日常经营库）']
    for label,ids in case_ids.items():
        statements.append(f'-- {label}\n'+FACT_SQL.replace(':ids','ARRAY['+','.join(map(str,ids))+']::bigint[]')+';')
    (out/'reconcile.sql').write_text('\n\n'.join(statements),encoding='utf-8')
    print('证据目录:',out,flush=True)
    print('验收库保留:',name,flush=True)
