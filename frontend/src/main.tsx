import StoreAdmin from './StoreAdmin';
import HqAdmin from './HqAdmin';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { api, ApiError, message, money, statusText, time } from './api';
import type { User, Session, Store, Product, Bundle, Coupon, Order, OrderSummary, Page, CreateOrder } from './api';
import './style.css';

const roleLabels: Record<string, string> = {
    CONSUMER: '普通用户',
    STORE_ADMIN: '门店管理员',
    HQ_ADMIN: '总部管理员',
};

const TOKEN = 'retailops.consumer.token';
type View = 'shop' | 'orders' | 'member';
const pendingKey = (id: number) => `retailops.consumer.create.${id}`;
type Pending = { key: string; body: CreateOrder };
const getPending = (id: number): Pending | null => { const raw = localStorage.getItem(pendingKey(id)); return raw ? JSON.parse(raw) as Pending : null; };
function Notice({children}: {children: string}) { return children ? <div className="notice" role="alert">{children}</div> : null; }
function Status({value}: {value: string}) { return <span className={`status ${value.toLowerCase()}`}>{statusText(value)}</span>; }
function Brand() { return <div className="brand"><span className="brand-mark">R</span><span>RetailOps<small>连锁饮品经营平台</small></span></div>; }
function Auth({onLogin, initialError}: {onLogin: (s: Session)=>void; initialError: string}) {
  const [register, setRegister] = useState(false), [email,setEmail] = useState(''), [password,setPassword] = useState(''), [name,setName] = useState(''), [busy,setBusy] = useState(false), [error,setError] = useState(initialError);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      if (register) { await api<User>('/auth/register',undefined,{method:'POST',body:{email,password,display_name:name}}); setRegister(false); setError('注册成功，请使用该账号登录。'); return; }
      const session = await api<Session>('/auth/login',undefined,{method:'POST',body:{email,password}});
      if(!['CONSUMER','STORE_ADMIN','HQ_ADMIN'].includes(session.user.role)) { setError('总部管理端将在下一阶段接入。'); return; }
      onLogin(session);
    } catch(e) {setError(message(e));} finally {setBusy(false);}
  }
  return <div className="auth-shell"><div className="auth-hero"><Brand/><div><span className="eyebrow light">RETAIL OPERATIONS PLATFORM</span><h1>连锁饮品，<br/>一站式经营管理。</h1><p>选择门店、享受会员权益，在线完成点单。</p><div className="auth-rule">门店数据 · 支付 · 订单可追溯</div></div><small>RetailOps · 连锁门店经营平台</small></div><section className="auth-form"><div className="eyebrow">ACCOUNT ACCESS</div><h2>{register?'创建会员账号':'欢迎回来'}</h2><p className="muted">{register?'注册后即可使用消费者服务。':'使用普通用户或门店管理员账号登录。'}</p><Notice>{error}</Notice><form onSubmit={submit}>{register&&<label>昵称<input required maxLength={80} value={name} onChange={e=>setName(e.target.value)} autoComplete="nickname"/></label>}<label>邮箱<input type="email" required value={email} onChange={e=>setEmail(e.target.value)} autoComplete="email" placeholder="name@example.com"/></label><label>密码<input type="password" required minLength={register?8:undefined} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete={register?'new-password':'current-password'}/></label><button className="primary wide" disabled={busy}>{busy?'正在处理…':register?'注册':'登录'}</button></form><button className="link" disabled={busy} onClick={()=>{setRegister(!register);setError('');}}>{register?'已有账号？返回登录':'没有账号？注册会员'}</button></section></div>;
}

type Offer = {
    kind: 'PRODUCT' | 'BUNDLE';
    id: number;
    name: string;
    price: number;
    version: number;
    stock: number;
    category: string;
    description: string;
    available: boolean;
    image: string;
};
type CartLine = Offer & {quantity: number};
const offerKey = (o: Offer)=>`${o.kind}-${o.id}`;

async function getOffers(id: number) {
    const [products, bundles] = await Promise.all([
        api<Product[]>(`/stores/${id}/catalog`),
        api<Bundle[]>(`/stores/${id}/bundles`)
    ]);

    return [
        ...products.map(p => ({
            kind: 'PRODUCT' as const,
            id: p.product_id,
            name: p.name,
            price: p.price_cents,
            version: p.price_version,
            stock: p.available_qty,
            category: p.category,
            description: `${p.sku} · ${p.unit}`,
            available: p.available,
            image: `/products/${p.sku}.jpg`
        })),
        ...bundles.map(b => ({
            kind: 'BUNDLE' as const,
            id: b.bundle_id,
            name: b.name,
            price: b.price_cents,
            version: b.price_version,
            stock: b.available_qty,
            category: '套餐',
            description: b.components.map(
                c => `${c.name} ×${c.quantity}`
            ).join(' + '),
            available: b.available,
            image: `/products/BUNDLE-${b.bundle_id}.jpg`
        }))
    ];
}

function Shop({token,user,stores,onOrder,activeView}: {token:string;user:User;stores:Store[];onOrder:(o:Order)=>void;activeView:boolean}) {
  const [storeId,setStoreId] = useState(stores[0]?.id??0), [offers,setOffers] = useState<Offer[]>([]), [cart,setCart] = useState<CartLine[]>([]), [category,setCategory] = useState('全部'), [query,setQuery] = useState(''), [couponId,setCouponId] = useState(0), [points,setPoints] = useState(0), [coupons,setCoupons] = useState<Coupon[]>([]), [balance,setBalance] = useState(0), [loading,setLoading] = useState(false), [rightsReady,setRightsReady] = useState(false), [error,setError] = useState(''), [info,setInfo] = useState(''), [busy,setBusy] = useState(false), [pending,setPending] = useState<Pending|null>(()=>getPending(user.id));
  useEffect(()=>{ if(!storeId && stores.length) setStoreId(stores[0].id); },[stores,storeId]);
  useEffect(()=>{ let active=true; if(!activeView||!storeId) return; setOffers([]); setLoading(true); getOffers(storeId).then(v=>{if(active)setOffers(v);}).catch(e=>{if(active)setError(message(e));}).finally(()=>{if(active)setLoading(false);}); return()=>{active=false;}; },[storeId,activeView]);
  async function rights() { setRightsReady(false); try { const [p,c]=await Promise.all([api<{points_balance:number}>('/me/points',token),api<Coupon[]>('/me/coupons',token)]);setBalance(p.points_balance);setCoupons(c);setRightsReady(true); }catch(e){setError(message(e));} }
  useEffect(()=>{if(activeView)void rights();},[token,activeView]);
  const gross = cart.reduce((s,c)=>s+c.price*c.quantity,0);
  const now=Date.now();
  const eligible = coupons.filter(c=>c.status==='AVAILABLE' && Date.parse(c.starts_at)<=now && now<Date.parse(c.ends_at) && (c.scope==='GLOBAL'||c.store_id===storeId) && c.min_spend_cents<=gross);
  const coupon=eligible.find(c=>c.user_coupon_id===couponId);
  const discount=coupon?Math.min(coupon.discount_cents,gross):0;
  const maxPoints=Math.min(balance,gross-discount), used=Math.min(Math.max(0,points),maxPoints);
  const locked=busy||!!pending||loading;
  const selected=stores.find(s=>s.id===storeId);
  function changeStore(id:number){ if(id===storeId)return; if(cart.length&&!window.confirm('更换门店会清空当前购物车，是否继续？'))return; setCart([]);setCouponId(0);setPoints(0);setCategory('全部');setQuery('');setError('');setInfo('');setStoreId(id); }
  function add(o:Offer, delta:number){ setError(''); setInfo(''); setCart(old=>{ const found=old.find(c=>offerKey(c)===offerKey(o));const qty=(found?.quantity??0)+delta; if(qty<=0)return old.filter(c=>offerKey(c)!==offerKey(o)); if(qty>Math.min(o.stock,100)||!o.available||(!found&&old.length>=30))return old; return found?old.map(c=>offerKey(c)===offerKey(o)?{...c,quantity:qty}:c):[...old,{...o,quantity:qty}]; }); }
  async function refresh(){setLoading(true);setError('');setInfo('');try{const fresh=await getOffers(storeId);setOffers(fresh);setCart(old=>old.flatMap(c=>{const match=fresh.find(o=>offerKey(o)===offerKey(c));return match&&match.available?[{...match,quantity:Math.min(c.quantity,match.stock,100)}]:[];}));setInfo('已刷新售价、库存和购物车，请重新确认金额后下单。');await rights();}catch(e){setError(message(e));}finally{setLoading(false);}}
  async function create(){
    if(busy)return; setError('');setInfo('');setBusy(true);
    try {
      let task=pending;
      if(!task){ if(!cart.length)return; const body:CreateOrder={store_id:storeId,items:cart.map(c=>({item_type:c.kind,...(c.kind==='PRODUCT'?{product_id:c.id}:{bundle_id:c.id}),quantity:c.quantity,expected_price_version:c.version})),user_coupon_id:coupon?.user_coupon_id??null,points_used:used};task={key:crypto.randomUUID(),body};localStorage.setItem(pendingKey(user.id),JSON.stringify(task));setPending(task); }
      const order=await api<Order>('/orders',token,{method:'POST',body:task.body,key:task.key});
      localStorage.removeItem(pendingKey(user.id));setPending(null);setCart([]);setCouponId(0);setPoints(0);onOrder(order);
    }catch(e){
      if(e instanceof ApiError && e.status>=400&&e.status<500&&![401,408,429].includes(e.status)&&e.code!=='IDEMPOTENCY_CONFLICT'){localStorage.removeItem(pendingKey(user.id));setPending(null);}
      setError(message(e));
    }finally{setBusy(false);}
  }
  const categories=['全部',...Array.from(new Set(offers.map(o=>o.category)))];
  const visible=offers.filter(o=>(category==='全部'||o.category===category)&&`${o.name} ${o.description}`.toLowerCase().includes(query.toLowerCase()));
  return <><div className="page-head"><div><span className="eyebrow">ORDER ONLINE</span><h1>门店点单</h1><p className="muted">挑选心仪的饮品与套餐，以门店实际售价为准。</p></div><button className="secondary" disabled={locked||!storeId} onClick={refresh}>刷新商品与权益</button></div>
    <Notice>{error}</Notice>{info&&<div className="info">{info}</div>}{pending&&<div className="notice">有一笔建单请求结果尚未确认（门店 #{pending.body.store_id}）。请使用下方“恢复原建单请求”，不要重新提交一笔新订单。</div>}
    <div className="shop-grid"><div><section className="store-panel"><div><span className="eyebrow light">SELECTED STORE</span><h2>{selected?.name??'暂无营业门店'}</h2><p>{selected?`${selected.city} · ${selected.address}`:'等待门店数据'}</p></div><label className="store-select">切换门店<select value={storeId} disabled={locked||!stores.length} onChange={e=>changeStore(Number(e.target.value))}>{!stores.length&&<option value={0}>暂无门店</option>}{stores.map(s=><option key={s.id} value={s.id}>{s.city} · {s.name}</option>)}</select></label></section>
    <div className="catalog-tools"><div className="tabs">{categories.map(c=><button className={c===category?'active':''} key={c} onClick={()=>setCategory(c)}>{c}</button>)}</div><input className="search" aria-label="搜索商品" placeholder="搜索商品或套餐" value={query} onChange={e=>setQuery(e.target.value)}/></div>
    <div className="catalog-grid">{loading?<p className="muted">正在加载商品…</p>:visible.length===0?<div className="empty">暂无符合条件的在售商品。</div>:visible.map(o=>{const count=cart.find(c=>offerKey(c)===offerKey(o))?.quantity??0;return <article className="product" key={offerKey(o)}>
<div className={`product-art ${o.kind==='BUNDLE'?'bundle':''}`}>
    <span>
        {o.kind==='BUNDLE'?'组合套餐':o.category||'饮品'}
    </span>
    <div className="cup">
        {o.kind==='BUNDLE'?'Ⅱ':'Ⅰ'}
    </div>
    <small>
        {o.kind==='BUNDLE'?'BUNDLE':'DRINK MENU'}
    </small>
    <img
        src={o.image}
        alt={o.name}
        className="product-image"
        onError={e => {
            e.currentTarget.style.display = 'none';
        }}
    />
</div>
<div className="product-body"><div className="product-title"><h3>{o.name}</h3><span className="fine">{o.available?`可售 ${o.stock}`:'售罄'}</span></div><p className="muted product-desc">{o.description}</p><div className="product-bottom"><strong>{money(o.price)}</strong><button className="add" aria-label={`添加${o.name}`} disabled={locked||!o.available||count>=Math.min(o.stock,100)||(cart.length>=30&&count===0)} onClick={()=>add(o,1)}>＋</button></div></div></article>;})}</div></div>
    <aside className="cart panel"><div className="section-head"><h2>购物车</h2><span className="fine">{cart.reduce((s,c)=>s+c.quantity,0)} 件</span></div>{!cart.length?<div className="empty compact">购物车暂无商品</div>:cart.map(c=><div className="cart-line" key={offerKey(c)}><div><strong>{c.name}</strong><small>{money(c.price)} / 件</small></div><div className="qty"><button disabled={locked} onClick={()=>add(c,-1)}>−</button><span>{c.quantity}</span><button disabled={locked||c.quantity>=Math.min(c.stock,100)} onClick={()=>add(c,1)}>＋</button></div></div>)}
    <label>优惠券<select disabled={locked||!rightsReady} value={coupon?.user_coupon_id??0} onChange={e=>setCouponId(Number(e.target.value))}><option value={0}>不使用优惠券</option>{eligible.map(c=><option key={c.user_coupon_id} value={c.user_coupon_id}>{c.name} · 减{money(c.discount_cents)}</option>)}</select></label><label>积分抵扣 <small>余额 {rightsReady?balance:'—'}，100 积分抵 1 元</small><input type="number" min={0} max={maxPoints} step={1} disabled={locked||!rightsReady} value={used} onChange={e=>setPoints(Math.max(0,Math.min(maxPoints,Math.trunc(Number(e.target.value)||0))))}/></label>
    <div className="totals"><div><span>商品合计</span><b>{money(gross)}</b></div><div><span>优惠券减免</span><b>−{money(discount)}</b></div><div><span>积分抵扣</span><b>−{money(used)}</b></div><div className="total"><span>预计应付</span><strong>{money(gross-discount-used)}</strong></div></div><button className="primary wide" disabled={busy||(!pending&&(!cart.length||loading||!rightsReady))} onClick={create}>{busy?'正在创建订单…':pending?'恢复原建单请求':'提交订单'}</button><p className="fine">实际金额、优惠及库存以服务端为准。提交订单不会扣库存，确认支付时才扣减。</p></aside></div></>;
}

function OrderDetail({token,order,onChange,close,stores}: {token:string;order:Order;onChange:(o:Order)=>void;close:()=>void;stores:Store[]}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function refresh(){setBusy(true);setError('');try{onChange(await api<Order>(`/orders/${order.id}`,token));}catch(e){setError(message(e));}finally{setBusy(false);}}
  async function action(kind:'pay'|'cancel'){if(!window.confirm(kind==='pay'?'确认支付？':'确定取消该待支付订单？'))return;setBusy(true);setError('');try{onChange(await api<Order>(`/orders/${order.id}/${kind}`,token,{method:'POST',key:`retailops-web-${kind}-${order.id}`}));}catch(e){setError(`${message(e)}。如结果不明确，请刷新订单状态；重试将使用原幂等键。`);}finally{setBusy(false);}}
  return <section className="panel detail"><div className="section-head"><button className="link" disabled={busy} onClick={close}>← 返回订单列表</button><button className="secondary" disabled={busy} onClick={refresh}>刷新状态</button></div><div className="detail-head"><div><span className="eyebrow">ORDER #{order.id}</span><h1>{statusText(order.status)}</h1><p className="muted">{stores.find(s=>s.id===order.store_id)?.name??`门店 #${order.store_id}`} · {time(order.created_at)}</p></div><Status value={order.status}/></div><Notice>{error}</Notice><div className="order-items">{order.items.map(i=><div key={i.id} className="order-item"><div><strong>{i.item_name}</strong><small>{i.item_type==='BUNDLE'?'套餐':'单品'} · 成交价 {money(i.unit_price_cents)} × {i.quantity} · 价格版本 {i.price_version_snapshot}</small></div><b>{money(i.line_total_cents)}</b></div>)}</div><div className="totals detail-totals"><div><span>商品金额</span><b>{money(order.gross_cents)}</b></div><div><span>优惠券</span><b>−{money(order.coupon_discount_cents)}</b></div><div><span>积分抵扣（{order.points_used} 积分）</span><b>−{money(order.points_discount_cents)}</b></div><div className="total"><span>订单应付金额</span><strong>{money(order.payable_cents)}</strong></div></div>{order.paid_at&&<p className="muted">支付时间：{time(order.paid_at)}</p>}{order.status==='PENDING_PAYMENT'&&<div className="actions"><button className="primary" disabled={busy} onClick={()=>action('pay')}>{busy?'处理中…':'确认支付'}</button><button className="secondary" disabled={busy} onClick={()=>action('cancel')}>取消订单</button></div>}{(order.status==='PAID'||order.status==='COMPLETED')&&<div className="info">支付已成功，订单金额使用创建时保存的快照。</div>}<p className="fine">已支付订单不可取消或退款。</p></section>;
}
function Orders({token,stores,onOrder}: {token:string;stores:Store[];onOrder:(o:Order)=>void}){
  const [page,setPage]=useState(1),[data,setData]=useState<Page<OrderSummary>|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0),[opening,setOpening]=useState(false);
  useEffect(()=>{let active=true;setLoading(true);setError('');api<Page<OrderSummary>>(`/orders?page=${page}&page_size=20`,token).then(d=>{if(active)setData(d);}).catch(e=>{if(active){setData(null);setError(message(e));}}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[token,page,refresh]);
  async function open(id:number){setOpening(true);setError('');try{onOrder(await api<Order>(`/orders/${id}`,token));}catch(e){setError(message(e));}finally{setOpening(false);}}
  return <><div className="page-head"><div><span className="eyebrow">MY ORDERS</span><h1>我的订单</h1><p className="muted">查看订单状态、历史成交金额与支付结果。</p></div><button className="secondary" disabled={loading||opening} onClick={()=>setRefresh(x=>x+1)}>刷新订单</button></div><Notice>{error}</Notice><section className="panel"><div className="section-head"><h2>订单记录</h2><span className="fine">{data?`共 ${data.total} 笔`:'—'}</span></div>{loading?<div className="empty">正在读取订单…</div>:data?.items.length?<div className="order-list">{data.items.map(o=><button className="order-row" key={o.id} disabled={opening} onClick={()=>open(o.id)}><div><strong>订单 #{o.id}</strong><small>{stores.find(s=>s.id===o.store_id)?.name??`门店 #${o.store_id}`} · {time(o.created_at)} · {o.order_source==='COUNTER'?'柜台':'线上'}</small></div><Status value={o.status}/><b>{money(o.payable_cents)}</b><span>›</span></button>)}</div>:!error&&<div className="empty">暂无订单记录，欢迎前往门店点单。</div>}<div className="pagination"><button className="secondary" disabled={loading||page<=1} onClick={()=>setPage(p=>p-1)}>上一页</button><span>第 {page} 页</span><button className="secondary" disabled={loading||!data||page*data.page_size>=data.total} onClick={()=>setPage(p=>p+1)}>下一页</button></div></section></>;
}
function Member({token,user}: {token:string;user:User}){
  const [points,setPoints]=useState<number|null>(null),[coupons,setCoupons]=useState<Coupon[]|null>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[loading,setLoading]=useState(false);
  useEffect(()=>{let active=true;setLoading(true);setError('');Promise.all([api<{points_balance:number}>('/me/points',token),api<Coupon[]>('/me/coupons',token)]).then(([p,c])=>{if(active){setPoints(p.points_balance);setCoupons(c);}}).catch(e=>{if(active)setError(message(e));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[token,refresh]);
  return <><div className="page-head"><div><span className="eyebrow">MEMBERSHIP</span><h1>会员中心</h1><p className="muted">我的账户、积分与优惠券。</p></div><button className="secondary" disabled={loading} onClick={()=>setRefresh(x=>x+1)}>刷新权益</button></div><Notice>{error}</Notice><div className="member-grid"><section className="panel profile"><div className="avatar">{user.display_name.slice(0,1)}</div><h2>{user.display_name}</h2><p>{user.email}</p><span className="status available">消费者会员 · #{user.id}</span></section><section className="points-card"><span className="eyebrow light">POINTS BALANCE</span><div className="points-value">{points??'—'} <small>积分</small></div><p>实付每满 1 元获得 1 积分<br/>100 积分可抵 1 元</p></section></div><section className="panel"><div className="section-head"><h2>我的优惠券</h2><span className="fine">{coupons?`${coupons.length} 张`:'—'}</span></div>{loading?<div className="empty">正在读取权益…</div>:coupons?.length?<div className="coupon-grid">{coupons.map(c=>{const s=c.status==='AVAILABLE'&&Date.parse(c.ends_at)<=Date.now()?'EXPIRED':c.status;return <article className="coupon" key={c.user_coupon_id}><div className="coupon-value"><strong>{money(c.discount_cents)}</strong><small>满 {money(c.min_spend_cents)} 可用</small></div><div><h3>{c.name}</h3><Status value={s}/><p className="fine">{c.scope==='GLOBAL'?'全门店':`门店 #${c.store_id}`} · #{c.user_coupon_id}</p><p className="fine">{time(c.starts_at)} 至 {time(c.ends_at)}</p></div></article>;})}</div>:!error&&<div className="empty">暂无优惠券。</div>}<p className="fine">券状态和使用条件以结算时服务端校验为准。</p></section></>;
}
function App(){
  const [token,setToken]=useState(()=>sessionStorage.getItem(TOKEN)??''),[user,setUser]=useState<User|null>(null),[checking,setChecking]=useState(!!token),[authError,setAuthError]=useState(''),[view,setView]=useState<View>('shop'),[stores,setStores]=useState<Store[]>([]),[storeError,setStoreError]=useState(''),[detail,setDetail]=useState<Order|null>(null);
  function logout(note=''){sessionStorage.removeItem(TOKEN);setToken('');setUser(null);setDetail(null);setView('shop');setAuthError(note);setChecking(false);}
  useEffect(()=>{const handler=(event:Event)=>{if((event as CustomEvent<string>).detail===token)logout('登录已失效，请重新登录。');};window.addEventListener('retailops:unauthorized',handler);return()=>window.removeEventListener('retailops:unauthorized',handler);},[token]);
  useEffect(()=>{if(!token)return;let active=true;setChecking(true);api<User>('/auth/me',token).then(u=>{if(active){if(!['CONSUMER','STORE_ADMIN','HQ_ADMIN'].includes(u.role))logout('总部管理端将在下一阶段接入。');else setUser(u);}}).catch(e=>{if(active)logout(message(e));}).finally(()=>{if(active)setChecking(false);});return()=>{active=false;};},[token]);
  function login(s:Session){sessionStorage.setItem(TOKEN,s.access_token);setUser(s.user);setToken(s.access_token);setAuthError('');setView('shop');}
  async function loadStores(){setStoreError('');try{setStores(await api<Store[]>('/stores'));}catch(e){setStoreError(message(e));}}
  useEffect(()=>{if(user)void loadStores();},[user?.id]);
  if(checking)return <div className="centered"><Brand/><p>正在确认登录身份…</p></div>;
  if(!user||!token)return <Auth onLogin={login} initialError={authError}/>;
  if(user.role==='STORE_ADMIN')return <StoreAdmin token={token} user={user} onLogout={()=>logout()}/>;
  if(user.role==='HQ_ADMIN')return <HqAdmin token={token} user={user} onLogout={()=>logout()}/>;
  const currentUser=user;
  function navigate(v:View){setDetail(null);setView(v);}
  function openOrder(o:Order){setDetail(o);setView('orders');}
  return <div className="shell"><aside className="sidebar"><Brand/><div className="nav-caption">消费服务</div><nav>{([{id:'shop',label:'门店点单',number:'01'},{id:'orders',label:'我的订单',number:'02'},{id:'member',label:'会员中心',number:'03'}] as const).map(n=><button key={n.id} className={view===n.id?'selected':''} onClick={()=>navigate(n.id)}><span>{n.number}</span>{n.label}</button>)}</nav><div className="sidebar-footer"><small>RETAILOPS / 0.7</small><p>支付系统</p></div></aside><div className="workspace"><header className="topbar"><div className="breadcrumb">消费者端 <span>/</span> {view==='shop'?'门店点单':view==='orders'?'我的订单':'会员中心'}</div><div className="user"><span className="avatar small">
    {roleLabels[currentUser.role].slice(0, 1)}</span><b>{roleLabels[currentUser.role]}</b><button className="link" onClick={()=>logout()}>退出</button></div></header><main>{storeError&&<div className="notice">{storeError} <button className="link" onClick={loadStores}>重新加载门店</button></div>}<div hidden={view!=='shop'}><Shop token={token} user={currentUser} stores={stores} onOrder={openOrder} activeView={view==='shop'}/></div>{view==='orders'&&(detail?<OrderDetail key={detail.id} token={token} order={detail} onChange={setDetail} close={()=>setDetail(null)} stores={stores}/>:<Orders token={token} stores={stores} onOrder={openOrder}/>)}{view==='member'&&<Member token={token} user={currentUser}/>}</main></div></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
