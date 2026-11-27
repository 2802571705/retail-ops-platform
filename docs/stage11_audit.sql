-- 在 DBeaver 连接日常业务数据库 retailops 后运行。全部为只读查询。
-- 1. 问答及工具轨迹、请求 ID
SELECT r.id, r.operator_id, r.question, r.status, r.error_code,
       r.created_at, r.finished_at, a.detail->>'request_id' AS request_id,
       t.tool_name, t.args, t.result, t.duration_ms, t.status AS tool_status
FROM agent_runs r
LEFT JOIN audit_logs a ON a.target_type='agent_runs' AND a.target_id=r.id AND a.action='AGENT_RUN'
LEFT JOIN agent_tool_calls t ON t.run_id=r.id
ORDER BY r.id DESC,t.id;

-- 2. 审批状态、原始依据与实际价格流水
SELECT r.id,s.name AS store_name,p.name AS product_name,r.status,r.agent_run_id,
       r.baseline_price_cents,r.baseline_price_version,r.suggested_price_cents,
       r.metrics_snapshot,r.reviewed_by,r.reviewed_at,
       c.id AS change_id,c.old_price_cents,c.new_price_cents,c.old_version,c.new_version,
       sp.price_cents AS current_price_cents,sp.price_version AS current_price_version
FROM price_recommendations r
JOIN stores s ON s.id=r.store_id JOIN products p ON p.id=r.product_id
JOIN store_products sp ON sp.store_id=r.store_id AND sp.product_id=r.product_id
LEFT JOIN store_price_changes c ON c.recommendation_id=r.id
ORDER BY r.id DESC;

-- 3. 审批不一致记录：预期0行（不以当前价格等于历史价格作为判断条件）
SELECT r.id,r.status,c.id AS change_id
FROM price_recommendations r LEFT JOIN store_price_changes c ON c.recommendation_id=r.id
WHERE (r.status='APPROVED' AND (c.id IS NULL OR c.source<>'RECOMMENDATION'
      OR c.store_id<>r.store_id OR c.product_id<>r.product_id
      OR c.old_price_cents<>r.baseline_price_cents OR c.new_price_cents<>r.suggested_price_cents
      OR c.old_version<>r.baseline_price_version OR c.new_version<>r.baseline_price_version+1
      OR c.operator_id<>r.reviewed_by))
   OR (r.status<>'APPROVED' AND c.id IS NOT NULL);

-- 4. 一条建议多次生效：预期0行；数据库已有 UNIQUE(recommendation_id)
SELECT recommendation_id,COUNT(*) FROM store_price_changes
WHERE recommendation_id IS NOT NULL GROUP BY recommendation_id HAVING COUNT(*)>1;

-- 5. 历史订单价格快照与当前价对照（差异为正常历史记录，不代表错误）
SELECT o.id,o.status,o.created_at,i.item_name_snapshot,i.unit_price_cents,i.price_version_snapshot,
       sp.price_cents AS current_price_cents,sp.price_version AS current_version
FROM orders o JOIN order_items i ON i.order_id=o.id AND i.item_type='PRODUCT'
JOIN store_products sp ON sp.store_id=o.store_id AND sp.product_id=i.product_id
ORDER BY o.id DESC LIMIT 100;
