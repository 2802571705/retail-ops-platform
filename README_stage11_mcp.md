# 第11阶段扩展：MCP 经营工具服务

## 接入前提

已经安装第11阶段原版、优化版、学校大模型 API 补丁，并执行过 `apply_stage11.py`。本补丁基于学校 API 版本的 `agent.py` 和 `AgentAdmin.tsx`，不会修改 `.env`、支付代码、数据库配置、LangGraph 状态图或原有审批接口。

## 安装

将 ZIP 解压到 `E:\retail-ops-platform`。PowerShell 在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-stage11-mcp.txt
.\.venv\Scripts\python.exe apply_stage11_mcp.py
```

补丁先检查两个文件的原始代码锚点，再写入。若本地 Agent 改过对应段落而无法匹配，脚本停止，不覆盖原有文件。新增注释为中文。

## 运行

保持 PostgreSQL 和 React 服务不变。在新的 PowerShell 终端启动 MCP 服务：

```powershell
cd E:\retail-ops-platform\backend
..\.venv\Scripts\python.exe -m app.api.mcp_server
```

本机固定监听 `http://127.0.0.1:8003/mcp`。保留终端运行。FastAPI 主应用仍使用原有 8000 端口（若已运行，确保重载或重启）：

```powershell
cd E:\retail-ops-platform\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

无需重新配置学校 API Key、模型 ID；无需 Alembic、seed、npm install。当前 MCP 服务仅用于本机开发/部署；不要改成 0.0.0.0 或直接暴露公网。远程部署需单独设计 TLS、认证及网络边界。

## 工作原理

- RetailOps FastAPI / LangGraph 是 Host，使用官方 Python MCP SDK 的 ClientSession 进行 initialize、tools/list、tools/call。
- MCP Server 动态注册原九个工具，复用原 dispatch_tool 和经营规则。MCP 工具参数为 date_from、date_to、store_id（可选）。Host 向学校模型暴露空参数工具 schema，实际日期与门店由已校验的页面范围注入。
- Client 只向固定本机地址转发当前登录 Bearer JWT，不走环境代理，不跟随重定向；JWT 不进入模型提示词。Server 每次查询重新验证 JWT、ACTIVE 状态和 HQ_ADMIN 权限。
- 数据查询事务使用 SET TRANSACTION READ ONLY。查询完成后才在独立事务写入服务端审计。库存确认、调价审批及其他写操作不是 MCP 工具。现有审批事务不变。
- Agent 执行预算和 PostgreSQL 全局问答槽位仍由 Host 控制。MCP Server 单进程异步信号量最多允许两个查询同时进入数据库。独立服务有自己的连接池；多进程部署时需计算总连接容量。外部本地 MCP 客户端的查询不计入 Agent 问答预算，但仍受 Server 查询限流与总部 JWT 授权限制。
- Host 保留 agent_tool_calls 完整结构化证据；服务端成功读取另记 audit_logs 的 MCP_TOOL_READ。通过 mcp_request_id 对应两侧轨迹。模型只能依据已返回的真实经营数据进行总结。
- MCP v1 SDK 与 Chat Completions 是不同协议：学校模型无需自身实现 MCP。Host 完成二者桥接。服务端采用 Streamable HTTP 的无状态 JSON 模式，不依赖 Windows 自动重载进程启动子进程。

## 正式业务验收

使用总部账号进入智能经营页面，选择截至昨天的1至30个完整北京时间业务日（近7天快捷按钮），执行：

1. 查询销售总览、商品及套餐销量，并与总部报表相同范围对账。
2. 查询库存预警及补货量，查看工具结果和实际调用记录。
3. 查询调价候选；如果业务数据满足条件，通过既有审批页面批准或驳回，验证价格版本与历史订单快照。没有符合条件的候选时不应强行制造。
4. 用 DBeaver 运行 `docs/stage11_mcp_audit.sql`，核对成功工具的 MCP 请求编号与服务器审计编号。无权限账号不得通过 MCP 读取经营数据。

第三方本地 MCP Host 可配置 URL `http://127.0.0.1:8003/mcp` 及 `Authorization: Bearer <总部用户登录JWT>`（不是学校 API Key），其工具参数需显式给出业务日期。现有 JWT 有有效期，不应硬编码到公开配置或提交 Git。工具发现只展示元数据，实际调用逐次认证。本补丁未配置面向公网的 OAuth 授权服务器，不应直接作为远程通用 MCP 服务开放。

## 交付边界

已核对原九个工具源码与学校 API 补丁，核对 SDK v1.26 的接口，并做了 Python 语法检查及原始合并副本的补丁定位检查。当前构建环境缺少 MCP、LangGraph、psycopg 和运行中的 PostgreSQL，未运行真实 MCP/模型联调；不宣称性能提升或验收已通过。
