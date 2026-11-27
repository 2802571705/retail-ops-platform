"""Only insert sales-detail blocks and router; preserve local changes."""
from pathlib import Path
root=Path(__file__).resolve().parent
changes={}
for filename, component, marker in [
    ('HqAdmin.tsx','<SalesDetail token={token} filter={f}/>','{s.data&&<p className="fine">{s.data.metric_notes}</p>}'),
    ('StoreAdmin.tsx','<SalesDetail token={env.token} storeId={env.context.store.id}/>','<PendingActions env={env} refresh={()=>{p.reload();s.reload();o.reload();m.reload();}}/>')]:
    p=root/'frontend/src'/filename
    s=p.read_text(encoding='utf-8-sig')
    if component not in s:
        if s.count(marker)!=1:
            raise SystemExit(f'无法定位 {filename} 工作台，请按 README 手动接入；未修改任何原文件。')
        s=s.replace(marker,marker+component,1)
    if "import SalesDetail from './SalesDetail';" not in s:
        s="import SalesDetail from './SalesDetail';\n"+s
    changes[p]=s
p=root/'backend/app/main.py'; s=p.read_text(encoding='utf-8-sig')
if 'from app.api.sales_detail import router as sales_detail_router' not in s:
    marker='from app.api.hq_analytics import router as hq_analytics_router'
    if marker not in s: raise SystemExit('无法定位后端路由，未修改任何原文件。')
    s=s.replace(marker,marker+'\nfrom app.api.sales_detail import router as sales_detail_router',1)
if 'app.include_router(sales_detail_router)' not in s:s=s.rstrip()+'\napp.include_router(sales_detail_router)\n'
changes[p]=s
for p,s in changes.items():p.write_text(s,encoding='utf-8')
print('Stage 10 销售明细已接入。')
