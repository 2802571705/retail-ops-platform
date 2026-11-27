-- DBeaver: choose the actual database (public schema). These statements are read-only.
-- Case-specific IDs are generated in tests/results/<run>/reconcile.sql.
SELECT current_database(), version(), current_setting('transaction_isolation');

-- 1. Paid orders with missing payment or mismatched amount; unpaid orders with payment.
SELECT o.id,o.status,o.payable_cents,p.amount_cents
FROM orders o LEFT JOIN payments p ON p.order_id=o.id
WHERE (o.status IN ('PAID','COMPLETED') AND (p.id IS NULL OR p.amount_cents<>o.payable_cents))
   OR (o.status NOT IN ('PAID','COMPLETED') AND p.id IS NOT NULL);

-- 2. Stock and points nonnegative; expected empty.
SELECT * FROM inventory WHERE available_qty<0;
SELECT * FROM member_accounts WHERE points_balance<0;

-- 3. SKU consumption snapshots vs actual sale ledger (no repeated join multiplication).
WITH expected AS (
 SELECT o.id AS order_id,o.store_id,c.product_id,SUM(c.quantity) AS qty
 FROM orders o JOIN order_items i ON i.order_id=o.id
 JOIN order_item_components c ON c.order_item_id=i.id
 WHERE o.status IN ('PAID','COMPLETED') GROUP BY o.id,o.store_id,c.product_id
), actual AS (
 SELECT order_id,store_id,product_id,-SUM(delta_qty) AS qty
 FROM inventory_ledger WHERE reason='SALE' GROUP BY order_id,store_id,product_id
)
SELECT * FROM expected e FULL JOIN actual a USING(order_id,store_id,product_id)
WHERE e.qty IS DISTINCT FROM a.qty;

-- 4. Successful coupon redemption must reference its paid order and the same user coupon.
SELECT c.id,c.status,c.redeemed_order_id,o.status AS order_status
FROM user_coupons c LEFT JOIN orders o ON o.id=c.redeemed_order_id
WHERE c.status='REDEEMED' AND (o.id IS NULL OR o.status NOT IN ('PAID','COMPLETED')
 OR o.user_coupon_id IS DISTINCT FROM c.id OR o.user_id<>c.user_id);

-- 5. Sales and product details for the same business window (edit dates and optional store ID).
-- Date_to is inclusive. The end timestamp is exclusive midnight of next day.
WITH p AS (
 SELECT * FROM orders WHERE status IN ('PAID','COMPLETED')
 AND paid_at >= (DATE '2026-11-01'::timestamp AT TIME ZONE 'Asia/Shanghai')
 AND paid_at < ((DATE '2026-11-30'+1)::timestamp AT TIME ZONE 'Asia/Shanghai')
 -- AND store_id=1
)
SELECT COUNT(*) AS orders,COALESCE(SUM(payable_cents),0)/100.0 AS net_sales_yuan,
 COALESCE(SUM(gross_cents),0)/100.0 AS gross_yuan,
 COALESCE(SUM(coupon_discount_cents+points_discount_cents),0)/100.0 AS discount_yuan
FROM p;

SELECT i.item_type,i.product_id,i.bundle_id,i.item_name_snapshot,
 SUM(i.quantity) AS sold_qty,SUM(i.line_total_cents)/100.0 AS gross_yuan
FROM orders o JOIN order_items i ON i.order_id=o.id
WHERE o.status IN ('PAID','COMPLETED')
 AND o.paid_at >= (DATE '2026-11-01'::timestamp AT TIME ZONE 'Asia/Shanghai')
 AND o.paid_at < ((DATE '2026-11-30'+1)::timestamp AT TIME ZONE 'Asia/Shanghai')
 -- AND o.store_id=1
GROUP BY i.item_type,i.product_id,i.bundle_id,i.item_name_snapshot ORDER BY sold_qty DESC;

-- 6. Real query plans. Use the same date range and data set before/after.
EXPLAIN (ANALYZE, BUFFERS)
SELECT (paid_at AT TIME ZONE 'Asia/Shanghai')::date AS business_date,
 COUNT(id),SUM(payable_cents)
FROM orders WHERE status IN ('PAID','COMPLETED')
 AND paid_at >= (DATE '2026-11-01'::timestamp AT TIME ZONE 'Asia/Shanghai')
 AND paid_at < ((DATE '2026-11-30'+1)::timestamp AT TIME ZONE 'Asia/Shanghai')
GROUP BY business_date ORDER BY business_date;

-- 7. Inspect indexes and their sizes. No index is added by this read-only script.
SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='orders';
SELECT indexrelname,idx_scan,pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes WHERE relname='orders' ORDER BY indexrelname;
