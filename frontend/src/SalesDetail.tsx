import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, money, time } from './api';
import './sales-detail.css';

type Range = {from:string;to:string;store:string};
type Row = {item_type:string;item_name:string;quantity:number;gross_cents:number;order_count?:number;order_id?:number;line_id?:number;paid_at?:string;store_name?:string;unit_price_cents?:number};
type Result = {paid_order_count:number;paid_sales_cents:number;gross_cents:number;coupon_discount_cents:number;points_discount_cents:number;total:number;items:Row[];page_size:number};
function today(){const p=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());return ['year','month','day'].map(k=>p.find(x=>x.type===k)!.value).join('-');}
const prior=(d:string,n:number)=>new Date(Date.parse(d+'T00:00:00Z')-n*86400000).toISOString().slice(0,10);
const valid=(s:string)=>/^\d{4}-\d{2}-\d{2}$/.test(s)&&!isNaN(Date.parse(s+'T00:00:00Z'))&&new Date(s+'T00:00:00Z').toISOString().slice(0,10)===s;
export default function SalesDetail({token,filter,storeId}:{token:string;filter?:Range;storeId?:number}){
  const [open,setOpen]=useState(false),[local,setLocal]=useState<Range>(()=>({from:prior(today(),29),to:today(),store:String(storeId??'')}));
  const [draft,setDraft]=useState(local),[mode,setMode]=useState<'products'|'lines'>('products'),[page,setPage]=useState(1),[rev,setRev]=useState(0),[inputError,setInputError]=useState('');
  const range=filter??local, store=filter?filter.store:String(storeId??local.store);
  const scope=JSON.stringify([range.from,range.to,store,mode]);
  const [previousScope,setPreviousScope]=useState(scope);
  if(previousScope!==scope){setPreviousScope(scope);setPage(1);}
  const qs=new URLSearchParams({date_from:range.from,date_to:range.to,mode,page:String(previousScope===scope?page:1),page_size:'20'});if(store)qs.set('store_id',store);
  const path='/analytics/sales-detail?'+qs.toString(), key=JSON.stringify([path,token,rev]);
  const [state,setState]=useState<{key:string;data:Result|null;error:string}>({key:'',data:null,error:''});
  useEffect(()=>{if(!open)return;let live=true;api<Result>(path,token).then(data=>{if(live)setState({key,data,error:''});}).catch(e=>{if(live)setState({key,data:null,error:e instanceof Error?e.message:'查询失败'});});return()=>{live=false;};},[open,path,token,key]);
  const data=state.key===key?state.data:null,error=state.key===key?state.error:'';
  function submit(e:FormEvent){e.preventDefault();if(!valid(draft.from)||!valid(draft.to)||draft.from>draft.to||Date.parse(draft.to)-Date.parse(draft.from)>366*86400000){setInputError('请输入有效日期（YYYY-MM-DD），且区间不超过367天。');return;}setInputError('');setLocal(draft);setOpen(true);setPage(1);setRev(v=>v+1);}
  return <section className="panel sales-detail"><div className="sales-detail-head"><div><h2>销售额与商品明细</h2><p className="fine">已支付及已完成订单 · 北京时间</p></div><button className="secondary" onClick={()=>{setOpen(v=>!v);setRev(v=>v+1);}}>{open?'收起明细':'查看销售明细'}</button></div>
    {!filter&&<form className="sales-detail-filters" onSubmit={submit}><label>开始日期<input value={draft.from} placeholder="YYYY-MM-DD" onChange={e=>setDraft(d=>({...d,from:e.target.value}))}/></label><label>结束日期<input value={draft.to} placeholder="YYYY-MM-DD" onChange={e=>setDraft(d=>({...d,to:e.target.value}))}/></label><button type="submit" className="primary">查询</button></form>}{inputError&&<p role="alert" className="notice">{inputError}</p>}
    {open&&<><div className="sales-detail-head"><span className="fine">{range.from} 至 {range.to}</span><div className="actions"><button className={mode==='products'?'primary':'secondary'} onClick={()=>setMode('products')}>商品汇总</button><button className={mode==='lines'?'primary':'secondary'} onClick={()=>setMode('lines')}>逐笔成交明细</button><button className="link" onClick={()=>setRev(v=>v+1)}>刷新</button></div></div>{error?<p role="alert" className="notice">{error}</p>:!data?<p className="fine">正在查询销售数据…</p>:<><div className="sales-detail-metrics"><div><span>实付销售额</span><strong>{money(data.paid_sales_cents)}</strong></div><div><span>订单量</span><strong>{data.paid_order_count}</strong></div><div><span>优惠前金额</span><strong>{money(data.gross_cents)}</strong></div><div><span>优惠券及积分减免</span><strong>{money(data.coupon_discount_cents+data.points_discount_cents)}</strong></div></div><p className="fine">订单级实付金额只统计一次；商品金额为成交快照中的优惠前行金额，套餐不重复计入组成 SKU。商品历史名称发生变化时分组展示。</p><div className="sales-detail-scroll"><table><thead><tr>{(mode==='products'?['销售项','类型','销量','涉及订单数','优惠前金额']:['订单编号','支付时间','门店','销售项','类型','数量','成交单价','优惠前金额']).map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{data.items.map((r,i)=><tr key={r.line_id??i}>{mode==='lines'&&<><td>#{r.order_id}</td><td>{r.paid_at?time(r.paid_at):'—'}</td><td>{r.store_name}</td></>}<td>{r.item_name}</td><td>{r.item_type==='BUNDLE'?'套餐':'单品'}</td><td>{r.quantity}</td>{mode==='products'?<td>{r.order_count}</td>:<td>{money(r.unit_price_cents??0)}</td>}<td>{money(r.gross_cents)}</td></tr>)}</tbody></table></div>{!data.items.length&&<p className="fine">该区间暂无成交记录。</p>}<div className="sales-detail-head"><span className="fine">共 {data.total} 条 · 第 {page} 页</span><div className="actions"><button className="secondary" disabled={page<=1} onClick={()=>setPage(v=>v-1)}>上一页</button><button className="secondary" disabled={page*data.page_size>=data.total} onClick={()=>setPage(v=>v+1)}>下一页</button></div></div></>}</>}
  </section>;
}
