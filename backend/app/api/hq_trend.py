"""总部销售趋势：按北京时间业务日聚合已支付订单。"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session
from app.api.hq_common import business_window, order_filters, period_meta
from app.api.hq_analytics import query_scope
from app.api.orders import response
from app.core.database import get_db
from app.core.security import current_user
from app.models import Order, User

router = APIRouter(prefix='/hq/analytics', tags=['总部经营分析'])

@router.get('/sales-trend')
def sales_trend(request: Request, window: dict = Depends(business_window),
                store_id: int | None = Query(None, gt=0),
                actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    day = cast(func.timezone('Asia/Shanghai', Order.paid_at), Date)
    rows = db.execute(select(day, func.count(Order.id), func.sum(Order.payable_cents))
                      .where(*order_filters(window, store_id)).group_by(day)).all()
    values = {d: (int(n), int(s)) for d, n, s in rows}
    start, end = date.fromisoformat(window['date_from']), date.fromisoformat(window['date_to'])
    items = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        n, s = values.get(d, (0, 0))
        items.append({'date': d.isoformat(), 'paid_order_count': n, 'paid_sales_cents': s})
    return response(request, {'period': period_meta(window, store_id), 'items': items})
