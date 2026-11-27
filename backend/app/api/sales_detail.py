"""Shared sales drill-down for HQ and authorized stores."""
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.admin_common import require_store
from app.api.hq_common import business_window, check_store_filter, period_meta
from app.api.orders import fail, response
from app.core.database import get_db
from app.core.security import current_user
from app.models import User

router = APIRouter(tags=['销售明细'])


def report_sql(scoped: bool, mode: str):
    # Only server-selected SQL fragments; all user values are bound parameters.
    scope = 'AND o.store_id = :store_id' if scoped else ''
    if mode == 'products':
        rows = '''SELECT i.item_type, i.product_id, i.bundle_id,
          i.item_name_snapshot AS item_name, sum(i.quantity) AS quantity,
          sum(i.line_total_cents) AS gross_cents, count(DISTINCT i.order_id) AS order_count
          FROM paid p JOIN order_items i ON i.order_id=p.id
          GROUP BY i.item_type,i.product_id,i.bundle_id,i.item_name_snapshot'''
        ordering = 'quantity DESC, item_type, product_id, bundle_id, item_name'
    else:
        rows = '''SELECT i.id AS line_id, p.id AS order_id, p.paid_at, s.name AS store_name,
          i.item_type,i.item_name_snapshot AS item_name,i.quantity,i.unit_price_cents,
          i.line_total_cents AS gross_cents
          FROM paid p JOIN order_items i ON i.order_id=p.id JOIN stores s ON s.id=p.store_id'''
        ordering = 'paid_at DESC, order_id DESC, line_id'
    return f'''WITH paid AS MATERIALIZED (
        SELECT o.id,o.store_id,o.paid_at,o.gross_cents,o.payable_cents,
               o.coupon_discount_cents,o.points_discount_cents
        FROM orders o WHERE o.status IN ('PAID','COMPLETED')
          AND o.paid_at >= :start AND o.paid_at < :end {scope}
      ), totals AS (
        SELECT count(*) AS paid_order_count,coalesce(sum(payable_cents),0) AS paid_sales_cents,
          coalesce(sum(gross_cents),0) AS gross_cents,
          coalesce(sum(coupon_discount_cents),0) AS coupon_discount_cents,
          coalesce(sum(points_discount_cents),0) AS points_discount_cents FROM paid
      ), detail_rows AS ({rows}), page_rows AS (
        SELECT * FROM detail_rows ORDER BY {ordering} LIMIT :limit OFFSET :offset
      ) SELECT totals.*, (SELECT count(*) FROM detail_rows) AS total,
         coalesce((SELECT jsonb_agg(to_jsonb(page_rows) ORDER BY {ordering}) FROM page_rows),'[]'::jsonb) AS items
      FROM totals'''


@router.get('/analytics/sales-detail')
def sales_detail(request: Request, window: dict = Depends(business_window),
                 store_id: int | None = Query(None, gt=0),
                 mode: Literal['products','lines'] = 'products',
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if actor.role == 'STORE_ADMIN':
        if store_id is None:
            fail('FORBIDDEN', '请选择已授权的门店', 403)
        require_store(db, actor, store_id)
    elif actor.role == 'HQ_ADMIN':
        check_store_filter(db, store_id)
    else:
        fail('FORBIDDEN', '仅管理人员可以查询销售明细', 403)
    result = db.execute(text(report_sql(store_id is not None, mode)),
        {'start': window['start'], 'end': window['end'], 'store_id': store_id,
         'limit': page_size, 'offset': (page-1)*page_size}).mappings().one()
    return response(request, {**dict(result), 'period': period_meta(window, store_id),
                               'page': page, 'page_size': page_size, 'mode': mode})
