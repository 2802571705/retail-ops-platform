-- 连接日常业务库 retailops，查询总部确认的补货及原始库存流水。
SELECT a.id AS audit_id,a.actor_id,l.id AS ledger_id,l.store_id,l.product_id,
       l.delta_qty,l.reason,a.detail,a.created_at
FROM audit_logs a JOIN inventory_ledger l ON l.id=a.target_id
WHERE a.action='AGENT_REPLENISHMENT' AND a.target_type='inventory_ledger'
ORDER BY a.id DESC;

-- 补货幂等记录及对应流水。
SELECT i.actor_id,i.request_key,i.status,l.id,l.delta_qty
FROM idempotency_requests i LEFT JOIN inventory_ledger l ON l.id=i.resource_id
WHERE i.scope='agent:replenishment' ORDER BY i.id DESC;

-- 问答运行期间观察同库两个全局槽位；正常结束后应释放。
SELECT pid,classid,objid,granted FROM pg_locks
WHERE locktype='advisory' AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND classid=731109 AND objid IN (1,2);

-- 调价审批状态及实际生效记录，409 后可查 STALE。
SELECT r.id,r.status,r.baseline_price_version,r.suggested_price_cents,
       r.reviewed_by,r.reviewed_at,c.id AS change_id,c.new_version
FROM price_recommendations r LEFT JOIN store_price_changes c ON c.recommendation_id=r.id
ORDER BY r.id DESC;
