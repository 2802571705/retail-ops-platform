-- Candidate only. The acceptance script automatically tests it in the isolated database.
-- Do not execute on the main database unless a representative plan supports it.
-- In DBeaver use autocommit; CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orders_paid_at_cover
ON public.orders(paid_at) INCLUDE(id,payable_cents)
WHERE status IN ('PAID','COMPLETED');
ANALYZE public.orders;
-- If verified and retained in the main DB, record it in the next Alembic migration as well.
