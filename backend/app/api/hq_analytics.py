"""总部经营统计：所有销售指标来自有效支付订单，直接复用当前 PostgreSQL。"""
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.api.hq_common import (business_window, check_store_filter, order_filters,
                               period_meta, require_hq)
from app.api.orders import response
from app.core.database import get_db
from app.core.security import current_user
from app.models import (CouponTemplate, Employee, Inventory, Order, OrderItem,
                        Product, Store, StoreProduct, User, UserCoupon)

router = APIRouter(prefix="/hq/analytics", tags=["总部经营分析"])


def avg_cents(total: int, count: int) -> int | None:
    if not count:
        return None
    return int((Decimal(total) / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def query_scope(db: Session, actor: User, store_id: int | None):
    require_hq(actor)
    check_store_filter(db, store_id)


@router.get("/sales")
def sales(request: Request, window: dict = Depends(business_window),
          store_id: int | None = Query(None, gt=0),
          actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    count, net, gross, coupons, points = db.execute(select(
        func.count(Order.id), func.coalesce(func.sum(Order.payable_cents), 0),
        func.coalesce(func.sum(Order.gross_cents), 0),
        func.coalesce(func.sum(Order.coupon_discount_cents), 0),
        func.coalesce(func.sum(Order.points_discount_cents), 0),
    ).where(*order_filters(window, store_id))).one()
    return response(request, {"period": period_meta(window, store_id),
                              "paid_order_count": count, "paid_sales_cents": net,
                              "gross_order_amount_cents": gross,
                              "coupon_discount_cents": coupons,
                              "points_discount_cents": points,
                              "avg_order_value_cents": avg_cents(net, count),
                              "metric_notes": "金额均为整数分；客单价四舍五入至分；营收只计 PAID/COMPLETED 订单实付金额"})


@router.get("/stores")
def store_performance(request: Request, window: dict = Depends(business_window),
                      store_id: int | None = Query(None, gt=0),
                      page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    conditions = [Store.id == store_id] if store_id is not None else []
    total = db.scalar(select(func.count(Store.id)).where(*conditions))
    rows = db.execute(select(
        Store.id, Store.name, Store.city,
        func.count(Order.id).label("paid_orders"),
        func.coalesce(func.sum(Order.payable_cents), 0).label("net_sales"),
    ).select_from(Store).outerjoin(Order, and_(Order.store_id == Store.id,
                                              *order_filters(window)))
     .where(*conditions).group_by(Store.id, Store.name, Store.city)
     .order_by(func.coalesce(func.sum(Order.payable_cents), 0).desc(), Store.id)
     .offset((page - 1) * page_size).limit(page_size)).all()
    items = [{"store_id": sid, "store_name": name, "city": city,
              "paid_order_count": count, "paid_sales_cents": net,
              "avg_order_value_cents": avg_cents(net, count)}
             for sid, name, city, count, net in rows]
    return response(request, {"period": period_meta(window, store_id), "items": items,
                              "page": page, "page_size": page_size, "total": total})


@router.get("/products")
def product_performance(request: Request, window: dict = Depends(business_window),
                        store_id: int | None = Query(None, gt=0),
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    base = (select(OrderItem.item_type.label("item_type"),
                   OrderItem.product_id.label("product_id"),
                   OrderItem.bundle_id.label("bundle_id"),
                   func.max(OrderItem.item_name_snapshot).label("display_name"),
                   func.sum(OrderItem.quantity).label("sold_qty"),
                   func.sum(OrderItem.line_total_cents).label("gross_line_amount_cents"),
                   func.count(func.distinct(OrderItem.order_id)).label("order_count"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(*order_filters(window, store_id))
            .group_by(OrderItem.item_type, OrderItem.product_id, OrderItem.bundle_id))
    data = base.subquery()
    total = db.scalar(select(func.count()).select_from(data))
    rows = db.execute(select(data).order_by(data.c.sold_qty.desc(), data.c.item_type,
                                            data.c.product_id, data.c.bundle_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return response(request, {"period": period_meta(window, store_id),
                              "items": [dict(row._mapping) for row in rows],
                              "page": page, "page_size": page_size, "total": total,
                              "metric_notes": "单品(PRODUCT)与套餐(BUNDLE)独立统计；gross_line_amount_cents 为优惠前的订单行原价，不是实付营收；套餐成分不能重复计入销售"})


@router.get("/members")
def member_performance(request: Request, window: dict = Depends(business_window),
                       store_id: int | None = Query(None, gt=0),
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    aggregated = (select(User.id.label("user_id"),
                         User.display_name.label("display_name"),
                         func.count(Order.id).label("paid_order_count"),
                         func.sum(Order.payable_cents).label("paid_spend_cents"),
                         func.max(Order.paid_at).label("last_paid_at"))
                  .join(Order, Order.user_id == User.id)
                  .where(User.role == "CONSUMER", *order_filters(window, store_id))
                  .group_by(User.id, User.display_name)).subquery()
    total = db.scalar(select(func.count()).select_from(aggregated))
    rows = db.execute(select(aggregated).order_by(aggregated.c.paid_spend_cents.desc(),
                                                   aggregated.c.user_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return response(request, {"period": period_meta(window, store_id),
                              "items": [{**dict(row._mapping),
                                         "last_paid_at": row.last_paid_at.isoformat()}
                                        for row in rows],
                              "page": page, "page_size": page_size, "total": total,
                              "metric_notes": "消费金额按 orders.payable_cents 逐订单汇总，不连接订单明细以免重复计额"})


@router.get("/employees")
def employee_performance(request: Request, window: dict = Depends(business_window),
                         store_id: int | None = Query(None, gt=0),
                         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                         actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    conditions = [Employee.store_id == store_id] if store_id is not None else []
    total = db.scalar(select(func.count(Employee.id)).where(*conditions))
    rows = db.execute(select(
        Employee.id, Employee.name, Employee.status, Employee.store_id,
        Store.name.label("store_name"),
        func.count(Order.id).label("counter_paid_orders"),
        func.coalesce(func.sum(Order.payable_cents), 0).label("counter_paid_sales_cents"),
    ).select_from(Employee).join(Store, Store.id == Employee.store_id)
     .outerjoin(Order, and_(Order.employee_id == Employee.id, Order.order_source == "COUNTER",
                            *order_filters(window)))
     .where(*conditions).group_by(Employee.id, Employee.name, Employee.status,
                                  Employee.store_id, Store.name)
     .order_by(func.coalesce(func.sum(Order.payable_cents), 0).desc(), Employee.id)
     .offset((page - 1) * page_size).limit(page_size)).all()
    return response(request, {"period": period_meta(window, store_id),
                              "items": [dict(row._mapping) for row in rows],
                              "page": page, "page_size": page_size, "total": total,
                              "metric_notes": "仅有员工归因的 COUNTER 已支付订单计入业绩；ONLINE 订单不分摊给员工"})


@router.get("/promotions")
def promotion_performance(request: Request, window: dict = Depends(business_window),
                          store_id: int | None = Query(None, gt=0),
                          page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                          actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    scoped = ([or_(CouponTemplate.store_id == store_id, CouponTemplate.scope == "GLOBAL")]
              if store_id is not None else [])
    total = db.scalar(select(func.count(CouponTemplate.id)).where(*scoped))
    templates = db.scalars(select(CouponTemplate).where(*scoped).order_by(CouponTemplate.id)
                           .offset((page - 1) * page_size).limit(page_size)).all()
    template_ids = [item.id for item in templates]
    if not template_ids:
        return response(request, {"period": period_meta(window, store_id), "items": [],
                                  "page": page, "page_size": page_size, "total": total})
    issue_conditions = [UserCoupon.issued_at >= window["start"],
                        UserCoupon.issued_at < window["end"],
                        UserCoupon.template_id.in_(template_ids)]
    if store_id is not None:
        issue_conditions.extend([CouponTemplate.scope == "STORE",
                                 CouponTemplate.store_id == store_id])
    cohort = db.execute(select(
        UserCoupon.template_id,
        func.count(UserCoupon.id).label("issued_count"),
        func.sum(case((and_(UserCoupon.status == "REDEEMED",
                                 UserCoupon.redeemed_at < window["end"]), 1), else_=0))
        .label("redeemed_count"),
    ).join(CouponTemplate, CouponTemplate.id == UserCoupon.template_id)
     .where(*issue_conditions).group_by(UserCoupon.template_id)).all()
    issued = {template_id: (n, r) for template_id, n, r in cohort}

    redemptions = db.execute(select(
        UserCoupon.template_id,
        func.count(Order.id).label("paid_redemptions"),
        func.coalesce(func.sum(Order.coupon_discount_cents), 0).label("discount_cost_cents"),
    ).join(UserCoupon, UserCoupon.id == Order.user_coupon_id)
     .where(UserCoupon.template_id.in_(template_ids), *order_filters(window, store_id))
     .group_by(UserCoupon.template_id)).all()
    paid = {template_id: (count, cost) for template_id, count, cost in redemptions}
    results = []
    for template in templates:
        local_cohort = store_id is None or template.scope == "STORE"
        n, r = issued.get(template.id, (0, 0)) if local_cohort else (None, None)
        redemptions_count, discount_cost = paid.get(template.id, (0, 0))
        rate = (str((Decimal(r) * 100 / Decimal(n)).quantize(Decimal("0.01")))
                if n else None)
        results.append({"template_id": template.id, "name": template.name,
                        "scope": template.scope, "template_store_id": template.store_id,
                        "issued_in_period": n, "issue_cohort_redeemed_by_period_end": r,
                        "cohort_redemption_rate_percent": rate,
                        "paid_redemptions_in_period": redemptions_count,
                        "paid_coupon_discount_cents": discount_cost})
    return response(request, {"period": period_meta(window, store_id),
                              "items": results, "page": page, "page_size": page_size,
                              "total": total,
                              "metric_notes": "核销率按本期发放的券实例队列计算，统计期结束前核销数/本期发放数；优惠成本按本期支付订单计算，两者并非同一队列。按门店筛选时，全局券无法归属发放门店，因此其发券数和核销率显示 null，仅统计本店使用的优惠成本。"})


@router.get("/inventory")
def inventory_analysis(request: Request, store_id: int | None = Query(None, gt=0),
                       threshold: int = Query(10, ge=0),
                       page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                       actor: User = Depends(current_user), db: Session = Depends(get_db)):
    query_scope(db, actor, store_id)
    conditions = [Inventory.store_id == store_id] if store_id is not None else []
    total, low_count = db.execute(select(
        func.count(Inventory.id),
        func.coalesce(func.sum(case((Inventory.available_qty < threshold, 1), else_=0)), 0),
    ).where(*conditions)).one()
    rows = db.execute(select(
        Inventory.store_id, Store.name.label("store_name"),
        Inventory.product_id, Product.sku, Product.name.label("product_name"),
        StoreProduct.price_cents, StoreProduct.is_active,
        Inventory.available_qty,
    ).join(Store, Store.id == Inventory.store_id)
     .join(Product, Product.id == Inventory.product_id)
     .join(StoreProduct, and_(StoreProduct.store_id == Inventory.store_id,
                              StoreProduct.product_id == Inventory.product_id))
     .where(*conditions).order_by(Inventory.available_qty, Inventory.store_id,
                                  Inventory.product_id)
     .offset((page - 1) * page_size).limit(page_size)).all()
    items = [{**dict(row._mapping), "low_stock": row.available_qty < threshold}
             for row in rows]
    return response(request, {"store_id": store_id, "as_of": "当前库存余额（非历史时点）",
                              "low_stock_threshold": threshold,
                              "total_sku_rows": total, "low_stock_sku_rows": low_count,
                              "items": items, "page": page, "page_size": page_size})
