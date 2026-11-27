"""Insert only the HQ navigation entry and backend router; preserve existing files."""
from pathlib import Path
root=Path(__file__).resolve().parent
p=root/'frontend/src/HqAdmin.tsx'; s=p.read_text(encoding='utf-8-sig')
if "import AgentAdmin from './AgentAdmin';" not in s: s="import AgentAdmin from './AgentAdmin';\n"+s
if "['agent','智能经营']" not in s:
    old="['employee-admin','员工管理']] as const;"
    if s.count(old)!=1: raise SystemExit('无法定位总部导航；请按 README 手动接入，原文件未修改。')
    s=s.replace(old,"['employee-admin','员工管理'],['agent','智能经营']] as const;",1)
old="const analytics=view!=='store-admin'&&view!=='employee-admin';"
new="const analytics=view!=='store-admin'&&view!=='employee-admin'&&view!=='agent';"
if new not in s:
    if s.count(old)!=1: raise SystemExit('无法定位总部筛选分流；原文件未修改。')
    s=s.replace(old,new,1)
if "<AgentAdmin token={token} stores={stores.items}/>" not in s:
    old="{view==='employee-admin'&&<EmployeeManagement token={token} stores={stores.items} write={write}/>}"
    if s.count(old)!=1: raise SystemExit('无法定位总部页面分流；原文件未修改。')
    s=s.replace(old,old+"\n  {view==='agent'&&<AgentAdmin token={token} stores={stores.items}/>}",1)
# distinguish the module description while leaving other views unchanged.
s=s.replace("analytics?'统一经营口径 · 数据来自实际业务记录':'维护品牌组织与授权门店'", "view==='agent'?'只读经营分析 · 人工审批':analytics?'统一经营口径 · 数据来自实际业务记录':'维护品牌组织与授权门店'")
q=root/'backend/app/main.py'; t=q.read_text(encoding='utf-8-sig')
line='from app.api.agent import router as agent_router'
if line not in t:
    old='from app.api.hq_analytics import router as hq_analytics_router'
    if t.count(old)!=1: raise SystemExit('无法定位后端路由；原文件未修改。')
    t=t.replace(old,old+'\n'+line,1)
if 'app.include_router(agent_router)' not in t: t=t.rstrip()+'\napp.include_router(agent_router)\n'
p.write_text(s,encoding='utf-8'); q.write_text(t,encoding='utf-8')
print('Stage 11 智能经营已接入，保留现有三端及连接池配置。')
