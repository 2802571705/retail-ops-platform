import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { api, ApiError, money, statusText, time } from './api';
import type { User, Store, Product, Bundle, Page, Order, OrderSummary, CreateOrder } from './api';
import './store-admin.css';
import { DatePicker, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

dayjs.locale('zh-cn');

type SKU = { product_id:number; sku:string; name:string; category:string; brand_status:string; price_cents:number; min_price_cents:number; max_price_cents:number; price_version:number; is_active:boolean; available_qty:number };
type Part = { product_id:number; quantity:number };
type Package = { bundle_id:number; name:string; price_cents:number; price_version:number; is_active:boolean; components:Part[] };
type Stock = { product_id:number; sku:string; name:string; available_qty:number };
type Member = { user_id:number; display_name:string; points_balance:number };
type MemberDetail = { user_id:number; display_name:string; paid_orders:number; paid_spend_cents:number; brand_points_balance:number };
type Template = { id:number; name:string; scope:string; store_id:number|null; min_spend_cents:number; discount_cents:number; starts_at:string; ends_at:string; active:boolean };
type Context = { store:Store & {status:string}; employee_id:number; brand_products:{product_id:number; sku:string; name:string}[] };
type Env = { token:string; user:User; context:Context; base:string };
const errText = (e:unknown) => e instanceof Error ? e.message : '请求失败，请重试。';
const orderStatus = (s:string) => s === 'PENDING_PAYMENT' ? '待支付' : statusText(s);
const yuan = (c:number) => (c/100).toFixed(2);
const shanghaiLocal = (v:string) => { const d=new Date(v); return new Date(d.getTime()+8*3600000).toISOString().slice(0,19); };
const text = (f:FormData,k:string) => String(f.get(k)??'').trim();
const num = (f:FormData,k:string) => Number(f.get(k));
const cents = (f:FormData,k:string) => Math.round(num(f,k)*100);

// The same unresolved payload retains its key, even after a page reload.
async function write<T>(env:Env, path:string, method:string, body?:unknown):Promise<T>{
  const slot=`retailops.store.write.${env.user.id}.${path}.${method}`;
  const payload=JSON.stringify(body??null);
  const raw=localStorage.getItem(slot);
  const old=raw ? JSON.parse(raw) as {payload:string;key:string} : null;
  if(old && old.payload!==payload) throw new Error('上一笔操作结果未确认。请恢复原填写内容并重试，确认结果后再提交新操作。');
  const key=old?.key??crypto.randomUUID();
  localStorage.setItem(slot,JSON.stringify({payload,key,path,method}));
  try {const result=await api<T>(path,env.token,{method,body,key}); localStorage.removeItem(slot);return result;}
  catch(e){if(e instanceof ApiError && e.status>=400 && e.status<500 && e.status!==401 && e.status!==408 && e.status!==429) localStorage.removeItem(slot);throw e;}
}
function useRead<T>(path:string,token:string){
  const [data,setData]=useState<T|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[version,setVersion]=useState(0);
  useEffect(()=>{let live=true;setLoading(true);setError('');setData(null);api<T>(path,token).then(x=>{if(live)setData(x);}).catch(e=>{if(live)setError(errText(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[path,token,version]);
  return {data,error,loading,reload:()=>setVersion(v=>v+1)};
}
function Feedback({error,loading=false}:{error?:string;loading?:boolean}){return <>{error&&<div className="notice" role="alert">{error}</div>}{loading&&<div className="empty">正在读取数据…</div>}</>;}
function Head({title,sub,refresh}:{title:string;sub:string;refresh?:()=>void}){return <div className="page-head"><div><span className="eyebrow">STORE OPERATIONS</span><h1>{title}</h1><p className="muted">{sub}</p></div>{refresh&&<button className="secondary" onClick={refresh}>刷新数据</button>}</div>;}
function Table({heads,rows}:{heads:string[];rows:ReactNode[][]}){return rows.length?<div className="admin-table-wrap"><table className="admin-table"><thead><tr>{heads.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>:<div className="empty">暂无记录</div>;}
function Form({title,children,submit,close}:{title:string;children:ReactNode;submit:(f:FormData)=>Promise<void>;close?:()=>void}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function save(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError('');try{await submit(new FormData(e.currentTarget));}catch(e){setError(errText(e));}finally{setBusy(false);}}
  return <section className="panel admin-editor"><div className="section-head"><h2>{title}</h2>{close&&<button className="link" disabled={busy} onClick={close}>关闭</button>}</div><Feedback error={error}/><form onSubmit={save}><fieldset disabled={busy}>{children}<button className="primary" disabled={busy}>{busy?'正在提交…':'确认提交'}</button></fieldset></form></section>;
}
function Field({label,name,type='text',value,min,max,step,required=true}:{label:string;name:string;type?:string;value?:string|number;min?:number;max?:number;step?:number|string;required?:boolean}){return <label>{label}<input name={name} type={type} defaultValue={value} min={min} max={max} step={step} required={required}/></label>;}
function Active({value=true}:{value?:boolean}){return <label>销售 / 启用状态<select name="active" defaultValue={String(value)}><option value="true">启用</option><option value="false">停用</option></select></label>;}
function Pager({data,page,setPage}:{data:Page<unknown>|null;page:number;setPage:(p:number)=>void}){return <div className="pagination"><button type="button" className="secondary" disabled={page<=1} onClick={()=>setPage(page-1)}>上一页</button><span>第 {page} 页 · 共 {data?.total??'—'} 条</span><button type="button" className="secondary" disabled={!data||page*data.page_size>=data.total} onClick={()=>setPage(page+1)}>下一页</button></div>;}
function PendingActions({env,refresh}:{env:Env;refresh:()=>void}){
  const prefix=`retailops.store.write.${env.user.id}.`;
  const pending=Object.keys(localStorage).filter(k=>k.startsWith(prefix)).map(k=>JSON.parse(localStorage.getItem(k)!) as {path:string;method:string;payload:string;key:string});
  const [busy,setBusy]=useState(false),[note,setNote]=useState(''),[error,setError]=useState('');
  async function retry(p:typeof pending[number]){setBusy(true);setError('');setNote('');try{const payload=JSON.parse(p.payload);await write(env,p.path,p.method,payload===null?undefined:payload);setNote('原请求已确认成功，请查看更新后的业务记录。');refresh();}catch(e){setError(errText(e));}finally{setBusy(false);}}
  return pending.length||note||error?<section className="panel admin-editor"><h2>未确认操作</h2><Feedback error={error}/>{note&&<div className="info">{note}</div>}{pending.length>0&&<p className="fine">连接异常可能发生在提交之后。请使用原请求重试，不要重复新建业务操作。</p>}{pending.map(p=><div className="cart-line" key={p.key}><div><strong>{p.method} {p.path}</strong><small>请求标识：{p.key}</small></div><button className="secondary" disabled={busy} onClick={()=>retry(p)}>重试原请求</button></div>)}</section>:null;
}
function Dashboard({env,go}:{env:Env;go:(v:View)=>void}){
  const p=useRead<SKU[]>(`${env.base}/products`,env.token),s=useRead<Stock[]>(`${env.base}/inventory`,env.token),o=useRead<Page<OrderSummary>>('/orders?page=1&page_size=10',env.token),m=useRead<Page<Member>>(`${env.base}/members?page=1&page_size=1`,env.token);
  return <><Head title="门店工作台" sub={`${env.context.store.city} · ${env.context.store.name}`} refresh={()=>{p.reload();s.reload();o.reload();m.reload();}}/><section className="store-panel"><div><span className="eyebrow light">STORE WORKSPACE</span><h2>{env.context.store.name}</h2><p>{env.context.store.address} · 员工 #{env.context.employee_id}</p></div><button className="secondary" onClick={()=>go('counter')}>柜台开单</button></section><div className="admin-metrics">{[['在售 SKU',p.data?.filter(x=>x.is_active&&x.brand_status==='ACTIVE').length],['零库存 SKU',s.data?.filter(x=>x.available_qty===0).length],['本店订单总量',o.data?.total],['本店消费会员',m.data?.total]].map(([label,value])=><section className="panel" key={label}><span className="muted">{label}</span><strong>{value??'—'}</strong></section>)}</div><Feedback error={[p.error,s.error,o.error,m.error].filter(Boolean).join('；')} loading={p.loading||s.loading||o.loading||m.loading}/><section className="panel"><div className="section-head"><h2>最近订单</h2><button className="link" onClick={()=>go('orders')}>查看全部</button></div>{o.data&&<Table heads={['订单','来源','状态','应付金额','创建时间']} rows={o.data.items.map(x=>[`#${x.id}`,x.order_source==='COUNTER'?'柜台':'线上',orderStatus(x.status),money(x.payable_cents),time(x.created_at)])}/>}</section><PendingActions env={env} refresh={()=>{p.reload();s.reload();o.reload();m.reload();}}/></>;
}
function Products({env}:{env:Env}){
  const q=useRead<SKU[]>(`${env.base}/products`,env.token),[edit,setEdit]=useState<SKU|'new'|null>(null),[notice,setNotice]=useState('');
  const finish=()=>{setEdit(null);setNotice('商品配置已保存。');q.reload();};
  const candidates=env.context.brand_products.filter(x=>!q.data?.some(p=>p.product_id===x.product_id));
  return <><Head title="商品管理" sub="维护本店 SKU、售价和上下架状态；调价自动记录版本与历史。" refresh={q.reload}/><Feedback error={q.error} loading={q.loading}/>{notice&&<div className="info">{notice}</div>}<section className="panel"><div className="section-head"><h2>门店商品</h2><button className="primary" disabled={!q.data||!candidates.length} onClick={()=>setEdit('new')}>配置品牌商品</button></div>{q.data&&<Table heads={['SKU / 商品','当前售价','价格范围','库存','版本','状态','操作']} rows={q.data.map(p=>[<>{p.name}<small>{p.sku}</small></>,money(p.price_cents),`${money(p.min_price_cents)}–${money(p.max_price_cents)}`,p.available_qty,p.price_version,p.brand_status!=='ACTIVE'?'品牌停用':p.is_active?'上架':'下架',<button className="link" onClick={()=>setEdit(p)}>编辑</button>])}/>}</section>{edit==='new'&&<Form key="new" title="配置已有品牌商品" close={()=>setEdit(null)} submit={async f=>{await write(env,`${env.base}/products`,'POST',{product_id:num(f,'product'),price_cents:cents(f,'price'),min_price_cents:cents(f,'min'),max_price_cents:cents(f,'max'),is_active:text(f,'active')==='true'});finish();}}><label>品牌 SKU<select name="product" required>{candidates.map(p=><option value={p.product_id} key={p.product_id}>{p.sku} · {p.name}</option>)}</select></label><div className="admin-form-grid"><Field label="售价（元）" name="price" type="number" min={0} step="0.01"/><Field label="最低售价（元）" name="min" type="number" min={0} step="0.01"/><Field label="最高售价（元）" name="max" type="number" min={0} step="0.01"/><Active/></div></Form>}{edit&&edit!=='new'&&<Form key={edit.product_id} title={`编辑 · ${edit.name}`} close={()=>setEdit(null)} submit={async f=>{await write(env,`${env.base}/products/${edit.product_id}`,'PATCH',{expected_price_version:edit.price_version,price_cents:cents(f,'price'),is_active:text(f,'active')==='true',reason:text(f,'reason')});finish();}}><div className="admin-form-grid"><Field label="售价（元）" name="price" type="number" value={yuan(edit.price_cents)} min={edit.min_price_cents/100} max={edit.max_price_cents/100} step="0.01"/><Active value={edit.is_active}/></div><Field label="变更原因" name="reason"/><p className="fine">当前版本 {edit.price_version}，已有订单不受改价影响。</p></Form>}</>;
}
function Bundles({env}:{env:Env}){
  const q=useRead<Package[]>(`${env.base}/bundles`,env.token),p=useRead<SKU[]>(`${env.base}/products`,env.token),[edit,setEdit]=useState<Package|'new'|null>(null),[notice,setNotice]=useState('');
  const names=(parts:Part[])=>parts.map(x=>`${p.data?.find(y=>y.product_id===x.product_id)?.name??'#'+x.product_id} × ${x.quantity}`).join('、');
  return <><Head title="套餐管理" sub="套餐是独立销售项，组成 SKU 用于库存扣减。" refresh={()=>{q.reload();p.reload();}}/><Feedback error={q.error||p.error} loading={q.loading||p.loading}/>{notice&&<div className="info">{notice}</div>}<section className="panel"><div className="section-head"><h2>门店套餐</h2><button className="primary" disabled={!p.data} onClick={()=>setEdit('new')}>新建套餐</button></div>{q.data&&<Table heads={['套餐','组成商品','售价','版本','状态','操作']} rows={q.data.map(b=>[b.name,names(b.components),money(b.price_cents),b.price_version,b.is_active?'上架':'下架',<button className="link" disabled={!p.data} onClick={()=>setEdit(b)}>编辑</button>])}/>}</section>{edit&&p.data&&<BundleEditor key={edit==='new'?'new':edit.bundle_id} env={env} products={p.data} bundle={edit==='new'?undefined:edit} close={()=>setEdit(null)} saved={()=>{setEdit(null);setNotice('套餐已保存。');q.reload();}}/>}</>;
}
function BundleEditor({env,products,bundle,close,saved}:{env:Env;products:SKU[];bundle?:Package;close:()=>void;saved:()=>void}){
  return <Form title={bundle?`编辑 · ${bundle.name}`:'创建套餐'} close={close} submit={async f=>{const components=products.map(p=>({product_id:p.product_id,quantity:num(f,`part-${p.product_id}`)})).filter(p=>p.quantity>0);if(!components.length)throw new Error('至少选择一个组成商品。');const body={name:text(f,'name'),price_cents:cents(f,'price'),is_active:text(f,'active')==='true'};const changed=JSON.stringify(components.slice().sort((a,b)=>a.product_id-b.product_id))!==JSON.stringify(bundle?.components.slice().sort((a,b)=>a.product_id-b.product_id));await write(env,`${env.base}/bundles${bundle?'/'+bundle.bundle_id:''}`,bundle?'PATCH':'POST',bundle?{...body,expected_price_version:bundle.price_version,...(changed?{components}:{})}:{...body,components});saved();}}><div className="admin-form-grid"><Field label="套餐名称" name="name" value={bundle?.name}/><Field label="售价（元）" name="price" type="number" min={0} step="0.01" value={bundle?yuan(bundle.price_cents):undefined}/><Active value={bundle?.is_active}/></div><h3>组成商品（0 表示不选）</h3><div className="admin-form-grid">{products.filter(p=>p.is_active&&p.brand_status==='ACTIVE'||bundle?.components.some(x=>x.product_id===p.product_id)).map(p=><Field key={p.product_id} label={`${p.name}${p.is_active?'':'（已下架）'}`} name={`part-${p.product_id}`} type="number" min={0} max={100} step={1} value={bundle?.components.find(x=>x.product_id===p.product_id)?.quantity??0}/>)}</div></Form>;
}
function Inventory({env}:{env:Env}){
  const q=useRead<Stock[]>(`${env.base}/inventory`,env.token),[edit,setEdit]=useState<Stock|null>(null),[notice,setNotice]=useState('');
  return <><Head title="库存管理" sub="补货和人工调整通过事务写入库存流水。" refresh={q.reload}/><Feedback error={q.error} loading={q.loading}/>{notice&&<div className="info">{notice}</div>}<section className="panel">{q.data&&<Table heads={['SKU','商品','可用库存','状态','操作']} rows={q.data.map(p=>[p.sku,p.name,p.available_qty,p.available_qty===0?'缺货':'有库存',<button className="link" onClick={()=>setEdit(p)}>调整库存</button>])}/>}</section>{edit&&<Form key={edit.product_id} title={`${edit.name} · 当前 ${edit.available_qty}`} close={()=>setEdit(null)} submit={async f=>{const delta=num(f,'delta');if(!delta)throw new Error('调整数量不能为零。');const r=await write<{ledger_id:number;available_qty:number}>(env,`${env.base}/stock-adjustments`,'POST',{product_id:edit.product_id,delta_qty:delta,reason:text(f,'reason')});setNotice(`调整成功 · 当前库存 ${r.available_qty} · 流水 #${r.ledger_id}`);setEdit(null);q.reload();}}><Field label="变动数量（正数补货，负数扣减）" name="delta" type="number" step={1}/><Field label="调整原因" name="reason"/></Form>}</>;
}
function Members({env}:{env:Env}){
  const [page,setPage]=useState(1),[selected,setSelected]=useState<Member|null>(null),[notice,setNotice]=useState('');const q=useRead<Page<Member>>(`${env.base}/members?page=${page}&page_size=20`,env.token);
  return <><Head title="会员与积分" sub="仅展示本店有有效消费的会员；积分为品牌级账户。" refresh={q.reload}/><Feedback error={q.error} loading={q.loading}/>{notice&&<div className="info">{notice}</div>}<section className="panel">{q.data&&<Table heads={['会员 ID','昵称','积分余额','操作']} rows={q.data.items.map(m=>[m.user_id,m.display_name,m.points_balance,<button className="link" onClick={()=>setSelected(m)}>详情 / 调整</button>])}/>}<Pager data={q.data} page={page} setPage={setPage}/></section>{selected&&<MemberEditor key={selected.user_id} env={env} member={selected} close={()=>setSelected(null)} saved={s=>{setSelected(null);setNotice(s);q.reload();}}/>}</>;
}
function MemberEditor({env,member,close,saved}:{env:Env;member:Member;close:()=>void;saved:(s:string)=>void}){
  const q=useRead<MemberDetail>(`${env.base}/members/${member.user_id}`,env.token);
  return <Form title={`${member.display_name} · #${member.user_id}`} close={close} submit={async f=>{if(!q.data)throw new Error('请先加载会员详情。');const delta=num(f,'delta');if(!delta)throw new Error('调整积分不能为零。');const r=await write<{ledger_id:number;balance_before:number;balance_after:number}>(env,`${env.base}/points-adjustments`,'POST',{user_id:member.user_id,delta_points:delta,reason:text(f,'reason')});saved(`积分调整成功 · ${r.balance_before} → ${r.balance_after} · 流水 #${r.ledger_id}`);}}><Feedback error={q.error} loading={q.loading}/>{q.data&&<p className="muted">本店消费 {q.data.paid_orders} 单 · {money(q.data.paid_spend_cents)} · 品牌积分 {q.data.brand_points_balance}</p>}<Field label="积分变动（正数增加，负数扣减）" name="delta" type="number" step={1}/><Field label="调整原因" name="reason"/></Form>;
}
function Coupons({env}:{env:Env}){
  const q=useRead<Template[]>(`${env.base}/coupon-templates`,env.token),
        [edit,setEdit]=useState<Template|'new'|null>(null),
        [issue,setIssue]=useState<Template|null>(null),
        [notice,setNotice]=useState('');
        
  // 1. 这里初始值设为空即可
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');

  return (
    <>
      <Head title="优惠券管理" sub="创建本店券、维护有效期与门槛，并向本店消费会员发放。" refresh={q.reload}/>
      <Feedback error={q.error} loading={q.loading}/>
      {notice&&<div className="info">{notice}</div>}
      
      <section className="panel">
        <div className="section-head">
          <h2>优惠券模板</h2>
          {/* 2. 点击新建时，清空时间 */}
          <button className="primary" onClick={()=>{
            setEdit('new');
            setIssue(null);
            setStartTime('');
            setEndTime('');
          }}>新建门店券</button>
        </div>
        {q.data&&<Table heads={['名称','适用范围','门槛 / 优惠','有效期（北京时间）','状态','操作']} rows={q.data.map(c=>[
          <>{c.name}<small>#{c.id}</small></>,
          c.scope==='STORE'?'本店':'全门店',
          `${money(c.min_spend_cents)} / ${money(c.discount_cents)}`,
          <>{time(c.starts_at)}<small>至 {time(c.ends_at)}</small></>,
          !c.active?'停用':Date.parse(c.ends_at)<=Date.now()?'已过期':'启用',
          c.scope==='STORE'?<div className="admin-buttons">
            {/* 3. 点击编辑时，用 shanghaiLocal 转换时间并赋值给状态 */}
            <button className="link" onClick={()=>{
              setEdit(c);
              setIssue(null);
              setStartTime(shanghaiLocal(c.starts_at));
              setEndTime(shanghaiLocal(c.ends_at));
            }}>编辑</button>
            <button className="link" disabled={!c.active||Date.parse(c.ends_at)<=Date.now()} onClick={()=>{setIssue(c);setEdit(null);}}>发放</button>
          </div>:'总部维护'
        ])}/>
        }
      </section>

      {edit&&<Form 
        key={edit==='new'?'new':edit.id} 
        title={edit==='new'?'创建门店优惠券':`编辑 · ${edit.name}`} 
        close={()=>setEdit(null)} 
        submit={async f=>{
          // 4. 增加空值拦截
          if(!startTime || !endTime) throw new Error('请选择完整的开始和结束时间。');
          
          const body={
            name:text(f,'name'),
            min_spend_cents:cents(f,'min'),
            discount_cents:cents(f,'discount'),
            starts_at: startTime + '+08:00',
            ends_at: endTime + '+08:00',
            active:text(f,'active')==='true'
          };
          if(Date.parse(body.starts_at)>=Date.parse(body.ends_at))throw new Error('结束时间必须晚于开始时间。');
          await write(env,`/admin/coupon-templates${edit==='new'?'':'/'+edit.id}`,edit==='new'?'POST':'PATCH',edit==='new'?{...body,scope:'STORE',store_id:env.context.store.id}:body);
          setEdit(null);
          setNotice('优惠券模板已保存。');
          q.reload();
        }}
      >
        <div className="admin-form-grid">
          <Field label="优惠券名称" name="name" value={edit==='new'?undefined:edit.name}/>
          <Field label="最低消费（元）" name="min" type="number" min={0} step="0.01" value={edit==='new'?undefined:yuan(edit.min_spend_cents)}/>
          <Field label="优惠金额（元）" name="discount" type="number" min={0.01} step="0.01" value={edit==='new'?undefined:yuan(edit.discount_cents)}/>
          <Active value={edit==='new'?true:edit.active}/>
          
          <div className="field-wrapper">
              <label style={{ display: 'block', marginBottom: '8px' }}>开始时间（北京时间）</label>
              <ConfigProvider locale={zhCN}>
                  <DatePicker
                      showTime
                      format="YYYY-MM-DD HH:mm:ss"
                      placeholder="请选择开始时间"
                      value={startTime ? dayjs(startTime) : null}
                      onChange={value => setStartTime(value ? value.format('YYYY-MM-DDTHH:mm:ss') : '')}
                      style={{ width: '100%' }}
                  />
              </ConfigProvider>
          </div>

          <div className="field-wrapper">
              <label style={{ display: 'block', marginBottom: '8px' }}>结束时间（北京时间）</label>
              <ConfigProvider locale={zhCN}>
                  <DatePicker
                      showTime
                      format="YYYY-MM-DD HH:mm:ss"
                      placeholder="请选择结束时间"
                      value={endTime ? dayjs(endTime) : null}
                      onChange={value => setEndTime(value ? value.format('YYYY-MM-DDTHH:mm:ss') : '')}
                      style={{ width: '100%' }}
                  />
              </ConfigProvider>
          </div>
        </div>
      </Form>}

      {issue&&<Form key={issue.id} title={`发放 · ${issue.name}`} close={()=>setIssue(null)} submit={async f=>{const r=await write<{user_coupon_id:number}>(env,'/admin/coupons/issue','POST',{template_id:issue.id,user_id:num(f,'member')});setIssue(null);setNotice(`发放成功 · 用户券 #${r.user_coupon_id}`);}}>
        <MemberPicker env={env} requiredKnown/>
        <p className="fine">发放对象必须在本店有有效消费记录。</p>
      </Form>}
    </>
  );
}
function MemberPicker({env,requiredKnown=false}:{env:Env;requiredKnown?:boolean}){
  const [page,setPage]=useState(1),[id,setId]=useState('');const q=useRead<Page<Member>>(`${env.base}/members?page=${page}&page_size=20`,env.token);
  return <><Feedback error={q.error} loading={q.loading}/><label>选择本店会员<select value="" onChange={e=>setId(e.target.value)}><option value="">从当前页选择会员</option>{q.data?.items.map(m=><option key={m.user_id} value={m.user_id}>{m.display_name} · #{m.user_id} · {m.points_balance} 积分</option>)}</select></label><Pager data={q.data} page={page} setPage={setPage}/><label>{requiredKnown?'本店会员 ID':'消费者 ID（首次到店可直接输入）'}<input name="member" type="number" min={1} step={1} required value={id} onChange={e=>setId(e.target.value)}/></label></>;
}
function Counter({env,onOrder}:{env:Env;onOrder:(o:Order)=>void}){
  const p=useRead<Product[]>(`/stores/${env.context.store.id}/catalog`,env.token),b=useRead<Bundle[]>(`/stores/${env.context.store.id}/bundles`,env.token);
  const offers=[...(p.data??[]).map(x=>({kind:'PRODUCT' as const,id:x.product_id,name:x.name,price:x.price_cents,version:x.price_version,stock:x.available_qty,available:x.available})),...(b.data??[]).map(x=>({kind:'BUNDLE' as const,id:x.bundle_id,name:x.name,price:x.price_cents,version:x.price_version,stock:x.available_qty,available:x.available}))];
  const [quantities,setQuantities]=useState<Record<string,number>>({});
  const keyFor=(o:typeof offers[number])=>`${o.kind}-${o.id}`;
  const gross=offers.reduce((sum,o)=>sum+o.price*(quantities[keyFor(o)]??0),0);
  return <><Head title="柜台代下单" sub="选择消费者与销售项，订单自动归因当前员工；付款前不扣库存。" refresh={()=>{p.reload();b.reload();}}/><Feedback error={p.error||b.error} loading={p.loading||b.loading}/><Form title="柜台订单" submit={async f=>{if(!p.data||!b.data)throw new Error('请先加载商品与套餐。');const items:CreateOrder['items']=offers.filter(o=>(quantities[keyFor(o)]??0)>0).map(o=>({item_type:o.kind,...(o.kind==='PRODUCT'?{product_id:o.id}:{bundle_id:o.id}),quantity:quantities[keyFor(o)],expected_price_version:o.version}));if(!items.length)throw new Error('至少选择一个商品或套餐。');const order=await write<Order>(env,`/stores/${env.context.store.id}/counter-orders`,'POST',{store_id:env.context.store.id,customer_user_id:num(f,'member'),items,user_coupon_id:text(f,'coupon')?num(f,'coupon'):null,points_used:num(f,'points')});onOrder(order);}}><MemberPicker env={env}/><h3>商品与套餐</h3><Table heads={['销售项','售价','可售数量','购买数量']} rows={offers.map(o=>[<>{o.name}<small>{o.kind==='PRODUCT'?'单品':'套餐'} · 版本 {o.version}</small></>,money(o.price),o.stock,<input className="admin-qty" aria-label={`${o.name} 数量`} type="number" min={0} max={Math.min(o.stock,100)} step={1} disabled={!o.available} value={quantities[keyFor(o)]??0} onChange={e=>setQuantities(q=>({...q,[keyFor(o)]:Number(e.target.value)}))}/>])}/><div className="admin-form-grid"><Field label="用户优惠券 ID（选填）" name="coupon" type="number" min={1} step={1} required={false}/><Field label="使用积分" name="points" type="number" min={0} step={1} value={0}/></div><div className="admin-checkout"><span>商品合计（不含权益抵扣）</span><strong>{money(gross)}</strong></div><p className="fine">优惠券 ID 由消费者提供；最终金额、券与积分可用性由服务端计算和校验。</p></Form></>;
}
function Orders({env,initial,onExit}:{env:Env;initial:Order|null;onExit:()=>void}){
  const [page,setPage]=useState(1),[detail,setDetail]=useState<Order|null>(initial),[busy,setBusy]=useState(false),[error,setError]=useState('');const q=useRead<Page<OrderSummary>>(`/orders?page=${page}&page_size=20`,env.token);
  async function open(id:number){setBusy(true);setError('');try{setDetail(await api<Order>(`/orders/${id}`,env.token));}catch(e){setError(errText(e));}finally{setBusy(false);}}
  async function act(kind:'pay'|'cancel'|'complete'){if(!detail)return;const labels={pay:'确认支付？当前环境不发生实际资金扣款。',cancel:'确认取消此订单？',complete:'确认订单已完成制作？'};if(!window.confirm(labels[kind]))return;setBusy(true);setError('');try{setDetail(await write<Order>(env,`/orders/${detail.id}/${kind}`,'POST'));q.reload();}catch(e){setError(errText(e));}finally{setBusy(false);}}
  return <><Head title="订单管理" sub="处理本店线上与柜台订单，已支付订单可确认履约。" refresh={detail?()=>void open(detail.id):q.reload}/><Feedback error={error||(!detail?q.error:'')} loading={!detail&&q.loading}/>{detail?<section className="panel"><div className="section-head"><button className="link" disabled={busy} onClick={()=>{setDetail(null);onExit();q.reload();}}>← 返回订单列表</button><span className={`status ${detail.status.toLowerCase()}`}>{orderStatus(detail.status)}</span></div><h2>订单 #{detail.id}</h2><p className="muted">消费者 #{detail.user_id} · {detail.order_source==='COUNTER'?'柜台':'线上'} · {time(detail.created_at)}{detail.employee_id?` · 员工 #${detail.employee_id}`:''}</p><Table heads={['商品 / 套餐','数量','成交单价','小计']} rows={detail.items.map(i=>[i.item_name,i.quantity,money(i.unit_price_cents),money(i.line_total_cents)])}/><div className="totals detail-totals"><div><span>商品金额</span><b>{money(detail.gross_cents)}</b></div><div><span>优惠券</span><b>−{money(detail.coupon_discount_cents)}</b></div><div><span>积分抵扣</span><b>−{money(detail.points_discount_cents)}</b></div><div className="total"><span>应付金额</span><strong>{money(detail.payable_cents)}</strong></div></div>{detail.paid_at&&<p className="fine">支付时间：{time(detail.paid_at)}</p>}<div className="actions">{detail.status==='PENDING_PAYMENT'&&detail.order_source==='COUNTER'&&<><button className="primary" disabled={busy} onClick={()=>act('pay')}>确认支付</button><button className="secondary" disabled={busy} onClick={()=>act('cancel')}>取消订单</button></>}{detail.status==='PAID'&&<button className="primary" disabled={busy} onClick={()=>act('complete')}>完成制作</button>}</div>{detail.status==='PENDING_PAYMENT'&&detail.order_source==='ONLINE'&&<p className="fine">线上待支付订单由消费者操作。</p>}</section>:<section className="panel">{q.data&&<Table heads={['订单编号','来源','状态','应付金额','创建时间','操作']} rows={q.data.items.map(o=>[`#${o.id}`,o.order_source==='COUNTER'?'柜台':'线上',<span className={`status ${o.status.toLowerCase()}`}>{orderStatus(o.status)}</span>,money(o.payable_cents),time(o.created_at),<button className="link" disabled={busy} onClick={()=>open(o.id)}>查看订单</button>])}/>}<Pager data={q.data} page={page} setPage={setPage}/></section>}</>;
}
type View='dashboard'|'products'|'bundles'|'inventory'|'members'|'coupons'|'counter'|'orders';
const nav: {id:View;label:string}[]=[{id:'dashboard',label:'门店工作台'},{id:'products',label:'商品管理'},{id:'bundles',label:'套餐管理'},{id:'inventory',label:'库存管理'},{id:'members',label:'会员与积分'},{id:'coupons',label:'优惠券管理'},{id:'counter',label:'柜台代下单'},{id:'orders',label:'订单履约'}];
export default function StoreAdmin({token,user,onLogout}:{token:string;user:User;onLogout:()=>void}){
  const q=useRead<Context>('/admin/me/store',token),[view,setView]=useState<View>('dashboard'),[order,setOrder]=useState<Order|null>(null);
  const env=q.data?{token,user,context:q.data,base:`/admin/stores/${q.data.store.id}`}:null;
  function go(v:View){setOrder(null);setView(v);}
  return <div className="shell store-admin"><aside className="sidebar"><div className="brand"><span className="brand-mark">R</span><span>RetailOps<small>连锁饮品 · 门店管理端</small></span></div><div className="nav-caption">门店经营</div><nav>{nav.map((n,i)=><button key={n.id} className={view===n.id?'selected':''} onClick={()=>go(n.id)}><span>{String(i+1).padStart(2,'0')}</span>{n.label}</button>)}</nav><div className="sidebar-footer"><small>RETAILOPS / 0.8</small><p>{q.data?.store.name??'门店经营管理'}</p></div></aside><div className="workspace"><header className="topbar"><div className="breadcrumb">门店管理端 <span>/</span> {nav.find(n=>n.id===view)?.label}</div><div className="user"><span className="avatar small">门</span><b>门店管理员</b><button className="link" onClick={onLogout}>退出</button></div></header><main><Feedback error={q.error} loading={q.loading}/>{q.error&&<button className="secondary" onClick={q.reload}>重新读取本店信息</button>}{env&&<div key={view}>{view==='dashboard'&&<Dashboard env={env} go={go}/>}{view==='products'&&<Products env={env}/>}{view==='bundles'&&<Bundles env={env}/>}{view==='inventory'&&<Inventory env={env}/>}{view==='members'&&<Members env={env}/>}{view==='coupons'&&<Coupons env={env}/>}{view==='counter'&&<Counter env={env} onOrder={o=>{setOrder(o);setView('orders');}}/>}{view==='orders'&&<Orders env={env} initial={order} onExit={()=>setOrder(null)}/>}</div>}</main></div></div>;
}
