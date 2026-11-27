# RetailOps Stage 11 · 智能经营与人工调价审批

## 接入
前提：Stage 10 已经完成，保留本地 .env、database.py 信号量及用户自定义文件。
解压至项目根目录，运行：

```powershell
cd E:\retail-ops-platform
.\.venv\Scripts\python.exe apply_stage11.py
```

无需 npm 新依赖、无需 Alembic 迁移，不运行 seed.py。四张表在 Stage 02 已创建。安装 LangGraph：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-stage11.txt
```

采用 LangGraph StateGraph 显式编排，而非高层 create_agent；原生 HTTP 模型适配器、白名单工具分发、审计与审批事务自行实现。`agent_graph.py` 定义 State、model/tools 节点和条件边，最多4轮模型请求、6次工具调用。人工审批由持久化业务状态及独立 API 实现，不使用内存 checkpointer 跨请求审批。
在项目根 `.env` 新增两行（实际密钥不要提交 Git、不要放在前端）：

```dotenv
DEEPSEEK_API_KEY=你的真实API密钥
DEEPSEEK_MODEL=deepseek-flash
```

通过 https://platform.deepseek.com/ 管理密钥和账户余额。接口使用官方 `https://api.deepseek.com/chat/completions`，非思考模式 function calling；模型名采用官方文档当前名称 `deepseek-flash`。模型 API 独立计费，配置缺失或调用失败时确定性规则分析仍可使用。官方文档：https://api-docs.deepseek.com/zh-cn/guides/tool_calls/

重新启动后端（.env 修改不保证热加载），前端保持运行即可：

```powershell
cd E:\retail-ops-platform\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端若已关闭：
```powershell
cd E:\retail-ops-platform\frontend
npm.cmd run dev
```

总部管理员账号进入“智能经营”，选择业务窗口和门店，再运行规则查询或智能经营问答。

## 业务规则（明确假设）
- 只使用 PAID/COMPLETED，按 paid_at 归属北京时间业务日。分析区间1—30个完整日，默认截至昨天的近7天；上期是紧邻的等长区间。调价必须截至昨天，历史建议次日可能失效。补货与当前库存快照对应，历史窗口仅反映历史消耗速度。
- 单品销量：订单行 PRODUCT 数量；SKU 消耗：订单组件快照数量（已包含购买倍数），包括套餐，不重复乘数量。补货缺口 = max(0,ceil(消耗量×7/区间天数)−当前库存)。无消耗不预测补货需求，库存覆盖天数显示空；并非缺货概率预测。
- 涨价筛选：本期至少5份单品、上期销量>0、同比相邻期增长至少20%、有消耗且当前库存覆盖≤3天。降价筛选：上期至少5份、销量下跌≥20%、有库存且覆盖≥14天或无消耗。只评估营业门店的在售 SKU。
- 建议按当前价格±5%四舍五入到整数分，若价格不变、成本缺失、价格范围不符、毛利<20%、幅度>10%、距上次调价<24小时，则不产生候选。毛利率=(建议价−估算成本)/建议价，未分摊优惠；上述阈值为固定工程初值，不是经验最优定价。
- 新建门店商品可能没有 estimated_cost_cents，未录入有效成本不推荐调价。现阶段不新增成本维护 UI；由授权总部维护真实成本，禁止为制造候选填虚构成本。
- 独立提案接口重新查询真实经营数据，验证客户端提交的版本和建议价，使用现有幂等机制；同版本仅允许一个待审批建议（锁定门店 SKU）。
- 审批事务先锁定建议，再锁定 store_products，重算经营依据和规则；版本或条件变化则保存 STALE 并返回409。批准写价格、版本、last_price_changed_at、store_price_changes 和建议状态、audit_logs 同一事务。重复批准返回原状态，不重复写；驳回不改价。允许同一总部管理员创建和审核（课程方案未要求职责分离）。
- 变价效果采用前后等长完整业务日（默认最多7日），排除变价当日，使用订单行金额及审批时估算成本（人工调价记录仅有当前成本），不能视为历史真实毛利或因果效应。

## Agent 工具
九个工具：get_sales_summary、get_store_performance、get_low_stock_products、get_product_sales、get_promotion_effect、get_pricing_candidates、get_price_change_history、get_replenishment、get_sku_sales。
门店/日期范围由页面提交并由后端校验，模型参数固定为空 JSON 对象；报表复用现有 hq_analytics，候选与补货为固定参数化 SQL。单次至多4轮模型请求、6次工具调用，工具最多50行，价格历史最多10行，历史区间明确。低库存工具阈值10。模型不能扩大范围、执行任意 SQL 或调用写入接口。每个实际工具调用记录名称、经过校验的范围、结果、耗时和状态；问答 request_id 在 audit_logs 中关联。模型文本不作为事实或写操作依据，页面展示结构化工具证据。

外部 API 仅接收问题及范围内汇总数据，包括门店、SKU 名称、销售及价格等经营信息；不传账号、个人会员明细和原始成本，价格历史工具也排除毛利额。请确认符合组织的数据出境及供应商政策，不在问题中输入隐私或机密。单次网络调用设置20秒 socket 超时，最多4轮；最多2个问答请求同时占用 Stage10 请求准入槽位，网络期间不保持数据库事务。故障返回 FAILED 和提示，不影响规则入口和人工维护。没有 API key 不会虚构回答。

## 接口与实际功能验收
|接口|用途|
|---|---|
|POST /hq/agent/runs|总部问答，保存运行及工具审计|
|GET /hq/agent/runs|最近50次问答|
|GET /hq/agent/runs/{id}|完整工具轨迹|
|GET /hq/agent/rules|指定范围规则分析，mode=replenishment/sku_sales/price_candidates|
|GET/POST /hq/agent/recommendations|分页审核列表、创建待审建议（POST需要Idempotency-Key）|
|POST /hq/agent/recommendations/{id}/review|批准或驳回，重复同决策安全|
|GET /hq/agent/price-history|价格历史分页|
|GET /hq/agent/price-history/{id}/effect|真实订单前后对比|

正式使用路径：总部选择范围 → 查看补货/调价候选 → 调用 DeepSeek 并查看工具轨迹 → 从真实候选创建建议 → 审批 → 消费者刷新目录 → 在原订单页面查看历史快照。拒绝、版本冲突、重复审批检查使用同一正式接口。若真实数据不足，空候选是正确业务结果；不要修改生产订单时间或伪造销量来强行触发建议。可以在独立验收库通过实际业务流程准备跨业务日的合法数据后完成该路径。DBeaver 对账执行 `docs/stage11_audit.sql`。

若补丁因本地修改较大不能定位：在 `backend/app/main.py` 导入 `from app.api.agent import router as agent_router` 并在底部 `app.include_router(agent_router)`；`frontend/src/HqAdmin.tsx` 导入 `AgentAdmin`，在 nav 增加 `['agent','智能经营']`，从 analytics 条件中排除 agent，并在内容区插入 `{view==='agent'&&<AgentAdmin token={token} stores={stores.items}/>}`。保留所有其他代码。

当前交付做了源码契约核对、Python语法及 TypeScript 转译语法检查、08—11补丁接入检查。当前环境无可用 PostgreSQL/psycopg、LangGraph 运行库和 DeepSeek 密钥，未完成图运行、实际 API 联调或完整 npm build；审批结果及 Agent 工具选择须在真实环境记录。未应用 Stage10 候选索引。
