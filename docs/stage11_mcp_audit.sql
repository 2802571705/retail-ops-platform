-- 在日常业务数据库 retailops 中执行，核对 MCP 的服务端审计与 Host 工具证据。
SELECT id, actor_id, detail->>'tool_name' AS tool_name,
       detail->'scope' AS scope, detail->>'request_id' AS mcp_request_id, created_at
FROM audit_logs WHERE action='MCP_TOOL_READ' ORDER BY id DESC;

-- 查询实际使用 MCP 的 Agent 工具轨迹，并关联 MCP 服务端审计。
SELECT t.run_id, t.tool_name, t.status, t.duration_ms,
       t.args->>'transport' AS transport,
       t.args->>'mcp_request_id' AS mcp_request_id,
       a.id AS server_audit_id, a.actor_id, t.result
FROM agent_tool_calls t
LEFT JOIN audit_logs a ON a.action='MCP_TOOL_READ'
  AND a.detail->>'request_id'=t.args->>'mcp_request_id'
WHERE t.args->>'transport'='MCP'
ORDER BY t.id DESC;
