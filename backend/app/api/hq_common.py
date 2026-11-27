"""总部权限及按 Asia/Shanghai 业务日计算的已支付订单查询区间。"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.api.orders import fail
from app.models import Order, Store, User

CHINA_TZ = ZoneInfo("Asia/Shanghai")
PAID_STATUSES = ("PAID", "COMPLETED")


def require_hq(actor: User) -> None:
    if actor.role != "HQ_ADMIN":
        fail("FORBIDDEN", "只有总部管理员能够操作总部管理及经营报表", 403)


def business_window(
    date_from: date = Query(..., description="中国业务日，起始日期（含）"),
    date_to: date = Query(..., description="中国业务日，截止日期（含）"),
):
    if date_to < date_from or (date_to - date_from).days > 366:
        fail("INVALID_DATE_RANGE", "日期范围必须有序且不能超过 367 天", 422)
    start = datetime.combine(date_from, time.min, tzinfo=CHINA_TZ)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=CHINA_TZ)
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "start": start, "end": end}


def order_filters(window: dict, store_id: int | None = None):
    conditions = [Order.status.in_(PAID_STATUSES),
                  Order.paid_at >= window["start"], Order.paid_at < window["end"]]
    if store_id is not None:
        conditions.append(Order.store_id == store_id)
    return conditions


def check_store_filter(db: Session, store_id: int | None) -> None:
    if store_id is not None and db.get(Store, store_id) is None:
        fail("STORE_NOT_FOUND", "所筛选的门店不存在", 404)


def period_meta(window: dict, store_id: int | None) -> dict:
    return {"date_from": window["date_from"], "date_to": window["date_to"],
            "timezone": "Asia/Shanghai", "end_exclusive": window["end"].isoformat(),
            "store_id": store_id, "paid_statuses": list(PAID_STATUSES)}
