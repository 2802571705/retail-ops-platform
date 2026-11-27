"""正式订单 API：只在确认模拟支付时扣库存、核券、抵扣/发放积分。"""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import current_user
from app.models import (Bundle, BundleItem, CouponTemplate, Employee, IdempotencyRequest,
                        Inventory, InventoryLedger, MemberAccount, Order, OrderItem,
                        OrderItemComponent, Payment, PointsLedger, Product, Store,
                        StoreProduct, User, UserCoupon)

router = APIRouter(tags=["订单与模拟支付"])


class CartItem(BaseModel):
    item_type: Literal["PRODUCT", "BUNDLE"]
    product_id: int | None = Field(default=None, gt=0)
    bundle_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(gt=0, le=100)
    expected_price_version: int = Field(gt=0)


class CreateOrderBody(BaseModel):
    store_id: int = Field(gt=0)
    items: list[CartItem] = Field(min_length=1, max_length=30)
    user_coupon_id: int | None = Field(default=None, gt=0)
    points_used: int = Field(default=0, ge=0)


class CounterOrderBody(CreateOrderBody):
    customer_user_id: int = Field(gt=0)


def fail(code: str, message: str, status: int = 409, **details):
    raise HTTPException(status_code=status, detail={"code": code, "message": message, **details})


def response(request: Request, data, *, error=None):
    return {"data": data, "error": error, "request_id": request.state.request_id}


def claim_key(db: Session, actor_id: int, scope: str, key: str, payload: dict):
    """唯一键在同一个事务中入库；重试只返回已经提交的业务对象。"""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()
    inserted_id = db.scalar(
        pg_insert(IdempotencyRequest)
        .values(actor_id=actor_id, scope=scope, request_key=key,
                payload_hash=digest, status="IN_PROGRESS")
        .on_conflict_do_nothing(index_elements=["actor_id", "scope", "request_key"])
        .returning(IdempotencyRequest.id)
    )
    if inserted_id is not None:
        return db.get(IdempotencyRequest, inserted_id), False
    old = db.scalar(select(IdempotencyRequest).where(
        IdempotencyRequest.actor_id == actor_id,
        IdempotencyRequest.scope == scope,
        IdempotencyRequest.request_key == key,
    ))
    if old.payload_hash != digest:
        fail("IDEMPOTENCY_CONFLICT", "同一幂等键对应不同请求内容")
    if old.status != "COMPLETED" or old.resource_id is None:
        fail("ORDER_STATE_CONFLICT", "请求尚未完成，请稍后查询结果")
    return old, True


def store_admin_employee(db: Session, actor: User, store_id: int) -> Employee:
    if actor.role != "STORE_ADMIN":
        fail("FORBIDDEN", "只有门店管理员可以代下单", 403)
    employee = db.scalar(select(Employee).where(Employee.user_id == actor.id,
                                                Employee.store_id == store_id,
                                                Employee.status == "ACTIVE"))
    if employee is None:
        fail("FORBIDDEN", "你没有该门店的操作权限", 403)
    return employee


def accessible(db: Session, actor: User, order: Order, *, operation: str = "read"):
    if actor.role == "CONSUMER" and actor.id == order.user_id:
        return
    if operation == "read" and actor.role == "HQ_ADMIN":
        return
    if actor.role == "STORE_ADMIN":
        employee = db.scalar(select(Employee).where(Employee.user_id == actor.id,
                                                     Employee.store_id == order.store_id,
                                                     Employee.status == "ACTIVE"))
        if employee is not None and (operation == "read" or order.order_source == "COUNTER"):
            return
    fail("FORBIDDEN", "无权操作该订单", 403)


def read_order(db: Session, order: Order) -> dict:
    lines = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)
                       .order_by(OrderItem.id)).all()
    components = db.scalars(select(OrderItemComponent).where(
        OrderItemComponent.order_item_id.in_([line.id for line in lines])
    )).all() if lines else []
    by_item = defaultdict(list)
    for component in components:
        by_item[component.order_item_id].append({"product_id": component.product_id,
                                                  "quantity": component.quantity})
    return {
        "id": order.id, "user_id": order.user_id, "store_id": order.store_id,
        "employee_id": order.employee_id, "order_source": order.order_source,
        "status": order.status, "gross_cents": order.gross_cents,
        "coupon_discount_cents": order.coupon_discount_cents,
        "points_used": order.points_used,
        "points_discount_cents": order.points_discount_cents,
        "payable_cents": order.payable_cents,
        "user_coupon_id": order.user_coupon_id,
        "created_at": order.created_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "items": [{"id": line.id, "item_type": line.item_type,
                   "product_id": line.product_id, "bundle_id": line.bundle_id,
                   "item_name": line.item_name_snapshot,
                   "price_version_snapshot": line.price_version_snapshot,
                   "quantity": line.quantity,
                   "unit_price_cents": line.unit_price_cents,
                   "line_total_cents": line.line_total_cents,
                   "components": sorted(by_item[line.id], key=lambda c: c["product_id"])}
                  for line in lines],
    }


def coupon_discount(db: Session, coupon_id: int, user_id: int, store_id: int,
                    gross: int, *, locked: bool = False) -> int:
    query = select(UserCoupon).where(UserCoupon.id == coupon_id,
                                     UserCoupon.user_id == user_id)
    coupon = db.scalar(query.with_for_update() if locked else query)
    if coupon is None or coupon.status != "AVAILABLE":
        fail("COUPON_INVALID", "优惠券不存在或已核销")
    template_query = select(CouponTemplate).where(CouponTemplate.id == coupon.template_id)
    template = db.scalar(template_query.with_for_update(read=True) if locked else template_query)
    now = datetime.now(timezone.utc)
    if (template is None or not template.active or not template.starts_at <= now < template.ends_at
            or gross < template.min_spend_cents
            or (template.scope == "STORE" and template.store_id != store_id)):
        fail("COUPON_INVALID", "优惠券不满足有效期、门槛或门店条件")
    return min(template.discount_cents, gross)


def create_business_order(db: Session, actor: User, body: CreateOrderBody,
                          customer_id: int, source: str, employee_id: int | None, key: str):
    marker, replay = claim_key(db, actor.id, f"orders:create:{source}", key,
                               {**body.model_dump(mode="json"), "customer_id": customer_id})
    if replay:
        return db.get(Order, marker.resource_id)

    store = db.get(Store, body.store_id)
    if store is None or store.status != "OPEN":
        fail("STORE_UNAVAILABLE", "门店不存在或暂停营业")

    snapshots = []
    gross = 0
    for item in body.items:
        if item.item_type == "PRODUCT":
            if item.product_id is None or item.bundle_id is not None:
                fail("INVALID_ITEM", "单品必须只填写 product_id", 422)
            product = db.get(Product, item.product_id)
            setting = db.scalar(select(StoreProduct).where(
                StoreProduct.store_id == body.store_id,
                StoreProduct.product_id == item.product_id).with_for_update(read=True))
            if product is None or product.status != "ACTIVE" or setting is None or not setting.is_active:
                fail("PRODUCT_UNAVAILABLE", "商品未在该门店上架")
            price, version, title = setting.price_cents, setting.price_version, product.name
            parts = [(product.id, item.quantity)]
        else:
            if item.bundle_id is None or item.product_id is not None:
                fail("INVALID_ITEM", "套餐必须只填写 bundle_id", 422)
            bundle = db.scalar(select(Bundle).where(Bundle.id == item.bundle_id,
                                                      Bundle.store_id == body.store_id)
                               .with_for_update(read=True))
            if bundle is None or not bundle.is_active:
                fail("PRODUCT_UNAVAILABLE", "套餐未在该门店上架")
            composition = db.scalars(select(BundleItem).where(BundleItem.bundle_id == bundle.id)
                                     .order_by(BundleItem.product_id).with_for_update(read=True)).all()
            if not composition:
                fail("PRODUCT_UNAVAILABLE", "套餐没有有效组成商品")
            parts = []
            for part in composition:
                product = db.get(Product, part.product_id)
                setting = db.scalar(select(StoreProduct).where(
                    StoreProduct.store_id == body.store_id,
                    StoreProduct.product_id == part.product_id).with_for_update(read=True))
                if product is None or product.status != "ACTIVE" or setting is None or not setting.is_active:
                    fail("PRODUCT_UNAVAILABLE", "套餐内商品未在该门店上架")
                parts.append((part.product_id, part.quantity * item.quantity))
            price, version, title = bundle.price_cents, bundle.price_version, bundle.name
        if version != item.expected_price_version:
            fail("PRICE_CHANGED", "商品或套餐售价版本已变化，请刷新购物车")
        gross += price * item.quantity
        snapshots.append((item, price, version, title, parts))

    discount = (coupon_discount(db, body.user_coupon_id, customer_id, body.store_id, gross)
                if body.user_coupon_id is not None else 0)
    wallet = db.scalar(select(MemberAccount).where(MemberAccount.user_id == customer_id))
    if wallet is None or body.points_used > wallet.points_balance:
        fail("POINTS_INSUFFICIENT", "可用积分不足")
    if body.points_used > gross - discount:
        fail("POINTS_INSUFFICIENT", "积分抵扣不能超过优惠券折扣后的金额")

    order = Order(user_id=customer_id, store_id=body.store_id, employee_id=employee_id,
                  order_source=source, status="PENDING_PAYMENT", gross_cents=gross,
                  coupon_discount_cents=discount, points_used=body.points_used,
                  points_discount_cents=body.points_used,
                  payable_cents=gross - discount - body.points_used,
                  user_coupon_id=body.user_coupon_id)
    db.add(order)
    db.flush()
    for item, price, version, title, parts in snapshots:
        line = OrderItem(order_id=order.id, item_type=item.item_type,
                         product_id=item.product_id, bundle_id=item.bundle_id,
                         item_name_snapshot=title, price_version_snapshot=version,
                         quantity=item.quantity, unit_price_cents=price,
                         line_total_cents=price * item.quantity)
        db.add(line)
        db.flush()
        for product_id, quantity in parts:
            db.add(OrderItemComponent(order_item_id=line.id, product_id=product_id,
                                       quantity=quantity))
    marker.resource_id, marker.status = order.id, "COMPLETED"
    db.flush()
    return order


@router.post("/orders", status_code=201)
def create_order(body: CreateOrderBody, request: Request,
                 key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
                 actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if actor.role != "CONSUMER":
        fail("FORBIDDEN", "线上下单仅支持消费者账号", 403)
    try:
        order = create_business_order(db, actor, body, actor.id, "ONLINE", None, key)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response(request, read_order(db, order))


@router.post("/stores/{store_id}/counter-orders", status_code=201)
def create_counter_order(store_id: int, body: CounterOrderBody, request: Request,
                         key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
                         actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if store_id != body.store_id:
        fail("INVALID_INPUT", "路径门店与订单门店不一致", 422)
    employee = store_admin_employee(db, actor, store_id)
    customer = db.get(User, body.customer_user_id)
    if customer is None or customer.role != "CONSUMER" or customer.status != "ACTIVE":
        fail("INVALID_CUSTOMER", "柜台单必须关联有效消费者", 422)
    try:
        order = create_business_order(db, actor, body, customer.id, "COUNTER", employee.id, key)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response(request, read_order(db, order))


@router.get("/orders")
def list_orders(request: Request, page: int = 1, page_size: int = 20,
                actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if page < 1 or not 1 <= page_size <= 50:
        fail("INVALID_INPUT", "page 必须大于 0，page_size 需在 1—50", 422)
    query = select(Order)
    if actor.role == "CONSUMER":
        query = query.where(Order.user_id == actor.id)
    elif actor.role == "STORE_ADMIN":
        store_ids = select(Employee.store_id).where(Employee.user_id == actor.id,
                                                     Employee.status == "ACTIVE")
        query = query.where(Order.store_id.in_(store_ids))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    orders = db.scalars(query.order_by(Order.id.desc()).offset((page - 1) * page_size)
                        .limit(page_size)).all()
    data = {"items": [{"id": o.id, "store_id": o.store_id, "order_source": o.order_source,
                       "status": o.status, "payable_cents": o.payable_cents,
                       "created_at": o.created_at.isoformat()} for o in orders],
            "page": page, "page_size": page_size, "total": total}
    return response(request, data)


@router.get("/orders/{order_id}")
def get_order(order_id: int, request: Request,
              actor: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        fail("ORDER_NOT_FOUND", "订单不存在", 404)
    accessible(db, actor, order)
    return response(request, read_order(db, order))


def lock_order(db: Session, order_id: int, actor: User, operation: str):
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        fail("ORDER_NOT_FOUND", "订单不存在", 404)
    accessible(db, actor, order, operation=operation)
    return order


@router.post("/orders/{order_id}/pay")
def pay_order(order_id: int, request: Request,
              key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
              actor: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        order = lock_order(db, order_id, actor, "pay")
        marker, replay = claim_key(db, actor.id, f"orders:pay:{order_id}", key,
                                   {"order_id": order_id, "action": "pay"})
        if replay:
            if order.status not in ("PAID", "COMPLETED"):
                fail("ORDER_STATE_CONFLICT", "支付结果和订单状态不一致", current_status=order.status)
        else:
            if order.status != "PENDING_PAYMENT":
                fail("ORDER_STATE_CONFLICT", "当前订单不可支付", current_status=order.status)
            store = db.get(Store, order.store_id)
            if store is None or store.status != "OPEN":
                fail("STORE_UNAVAILABLE", "门店已暂停营业")
            lines = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
            components = db.scalars(select(OrderItemComponent).where(
                OrderItemComponent.order_item_id.in_([line.id for line in lines]))).all()
            consumed = defaultdict(int)
            for item in components:
                consumed[item.product_id] += item.quantity
            if not consumed:
                fail("ORDER_STATE_CONFLICT", "订单缺少库存消耗明细")
            for product_id, qty in sorted(consumed.items()):
                product = db.get(Product, product_id)
                setting = db.scalar(select(StoreProduct).where(
                    StoreProduct.store_id == order.store_id,
                    StoreProduct.product_id == product_id))
                if product is None or product.status != "ACTIVE" or setting is None or not setting.is_active:
                    fail("PRODUCT_UNAVAILABLE", "商品已下架，无法确认支付")
                result = db.execute(update(Inventory)
                                    .where(Inventory.store_id == order.store_id,
                                           Inventory.product_id == product_id,
                                           Inventory.available_qty >= qty)
                                    .values(available_qty=Inventory.available_qty - qty,
                                            updated_at=func.now()))
                if result.rowcount != 1:
                    fail("OUT_OF_STOCK", "库存不足，本次模拟支付未成功", product_id=product_id)
                db.add(InventoryLedger(store_id=order.store_id, product_id=product_id,
                                       delta_qty=-qty, reason="SALE", order_id=order.id,
                                       operator_id=actor.id))
            paid_time = datetime.now(timezone.utc)
            if order.user_coupon_id is not None:
                discount = coupon_discount(db, order.user_coupon_id, order.user_id,
                                           order.store_id, order.gross_cents, locked=True)
                if discount != order.coupon_discount_cents:
                    fail("COUPON_INVALID", "优惠券额度已变化，不能按旧折扣支付")
                coupon = db.get(UserCoupon, order.user_coupon_id)
                coupon.status, coupon.redeemed_order_id = "REDEEMED", order.id
                coupon.redeemed_at = paid_time
            wallet = db.scalar(select(MemberAccount).where(
                MemberAccount.user_id == order.user_id).with_for_update())
            if wallet is None or wallet.points_balance < order.points_used:
                fail("POINTS_INSUFFICIENT", "积分余额不足，本次支付已回滚")
            if order.points_used:
                before = wallet.points_balance
                wallet.points_balance -= order.points_used
                db.add(PointsLedger(account_id=wallet.id, order_id=order.id,
                                    delta_points=-order.points_used, reason="REDEEM",
                                    balance_before=before, balance_after=wallet.points_balance,
                                    operator_id=actor.id))
            earned = order.payable_cents // 100  # 实付满 1 元得 1 积分
            if earned:
                before = wallet.points_balance
                wallet.points_balance += earned
                db.add(PointsLedger(account_id=wallet.id, order_id=order.id,
                                    delta_points=earned, reason="EARN",
                                    balance_before=before, balance_after=wallet.points_balance,
                                    operator_id=actor.id))
            wallet.updated_at = paid_time
            payment_key = hashlib.sha256(f"{actor.id}:pay:{order_id}:{key}".encode()).hexdigest()
            db.add(Payment(order_id=order.id, amount_cents=order.payable_cents,
                           status="SUCCEEDED", request_key=payment_key, paid_at=paid_time))
            order.status, order.paid_at = "PAID", paid_time
            marker.resource_id, marker.status = order.id, "COMPLETED"
            db.commit()  # 订单、库存、券、积分、支付流水只在这里统一提交
    except Exception:
        db.rollback()
        raise
    return response(request, read_order(db, order))


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, request: Request,
                 key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
                 actor: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        order = lock_order(db, order_id, actor, "cancel")
        marker, replay = claim_key(db, actor.id, f"orders:cancel:{order_id}", key,
                                   {"order_id": order_id, "action": "cancel"})
        if replay:
            if order.status != "CANCELLED":
                fail("ORDER_STATE_CONFLICT", "取消记录和订单状态不一致", current_status=order.status)
        else:
            if order.status != "PENDING_PAYMENT":
                fail("ORDER_STATE_CONFLICT", "仅未支付订单可以取消", current_status=order.status)
            order.status = "CANCELLED"  # 创建订单未预扣库存，无需反向库存流水
            marker.resource_id, marker.status = order.id, "COMPLETED"
            db.commit()
    except Exception:
        db.rollback()
        raise
    return response(request, read_order(db, order))
