"""Existing member accounts, points ledger, coupons and order fulfillment."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.admin_common import audit, require_member, require_store
from app.api.orders import claim_key, fail, read_order, response
from app.core.database import get_db
from app.core.security import current_user
from app.models import (CouponTemplate, MemberAccount, Order, PointsLedger,
                        User, UserCoupon)

router = APIRouter(tags=["门店后台：会员、优惠券、积分与履约"])
WriteKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


class PointsAdjustment(BaseModel):
    user_id: int = Field(gt=0)
    delta_points: int
    reason: str = Field(min_length=2, max_length=300)


class NewCouponTemplate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(pattern="^(STORE|GLOBAL)$")
    store_id: int | None = Field(default=None, gt=0)
    min_spend_cents: int = Field(ge=0)
    discount_cents: int = Field(gt=0)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    active: bool = True


class EditCouponTemplate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    min_spend_cents: int | None = Field(default=None, ge=0)
    discount_cents: int | None = Field(default=None, gt=0)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    active: bool | None = None


class IssueCoupon(BaseModel):
    template_id: int = Field(gt=0)
    user_id: int = Field(gt=0)


@router.get("/admin/stores/{store_id}/members")
def members(store_id: int, request: Request,
            page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
            actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    ids = select(Order.user_id).where(Order.store_id == store_id,
                                      Order.status.in_(["PAID", "COMPLETED"]))
    query = select(User, MemberAccount.points_balance).outerjoin(
        MemberAccount, MemberAccount.user_id == User.id).where(
        User.role == "CONSUMER", User.id.in_(ids))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(User.id).offset((page - 1) * page_size)
                      .limit(page_size)).all()
    return response(request, {"items": [
        {"user_id": u.id, "display_name": u.display_name,
         "points_balance": balance or 0} for u, balance in rows],
        "page": page, "page_size": page_size, "total": total})


@router.get("/admin/stores/{store_id}/members/{user_id}")
def member_detail(store_id: int, user_id: int, request: Request,
                  actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    customer = require_member(db, actor, store_id, user_id)
    count, spend = db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.payable_cents), 0))
                              .where(Order.user_id == user_id, Order.store_id == store_id,
                                     Order.status.in_(["PAID", "COMPLETED"]))).one()
    balance = db.scalar(select(MemberAccount.points_balance).where(
        MemberAccount.user_id == user_id))
    return response(request, {"user_id": customer.id, "display_name": customer.display_name,
                              "paid_orders": count, "paid_spend_cents": spend,
                              "brand_points_balance": balance or 0})


@router.post("/admin/stores/{store_id}/points-adjustments", status_code=201)
def adjust_points(store_id: int, body: PointsAdjustment, request: Request,
                  key: WriteKey, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    require_member(db, actor, store_id, body.user_id)
    if body.delta_points == 0:
        fail("INVALID_INPUT", "积分调整量不能为 0", 422)
    marker, replay = claim_key(db, actor.id, f"admin:points:{store_id}", key,
                               body.model_dump(mode="json"))
    if replay:
        ledger = db.get(PointsLedger, marker.resource_id)
    else:
        wallet = db.scalar(select(MemberAccount).where(
            MemberAccount.user_id == body.user_id).with_for_update())
        if wallet is None:
            wallet = MemberAccount(user_id=body.user_id, points_balance=0)
            db.add(wallet)
            db.flush()
        before = wallet.points_balance
        after = before + body.delta_points
        if after < 0:
            fail("POINTS_INSUFFICIENT", "积分余额不足，不能扣为负数")
        wallet.points_balance = after
        wallet.updated_at = datetime.now(timezone.utc)
        ledger = PointsLedger(account_id=wallet.id, order_id=None,
                              delta_points=body.delta_points, reason="ADJUST",
                              balance_before=before, balance_after=after,
                              operator_id=actor.id)
        db.add(ledger)
        db.flush()
        audit(db, actor, "POINTS_ADJUSTMENT", "points_ledger", ledger.id,
              {"store_id": store_id, "user_id": body.user_id,
               "reason": body.reason, "before": before, "after": after})
        marker.resource_id, marker.status = ledger.id, "COMPLETED"
        db.commit()
    return response(request, {"ledger_id": ledger.id, "user_id": body.user_id,
                              "delta_points": ledger.delta_points,
                              "balance_before": ledger.balance_before,
                              "balance_after": ledger.balance_after})


def _template_view(template: CouponTemplate) -> dict:
    return {"id": template.id, "name": template.name,
            "scope": template.scope, "store_id": template.store_id,
            "min_spend_cents": template.min_spend_cents,
            "discount_cents": template.discount_cents,
            "starts_at": template.starts_at.isoformat(),
            "ends_at": template.ends_at.isoformat(), "active": template.active}


def _template_access(db: Session, actor: User, template: CouponTemplate):
    if template.scope == "GLOBAL":
        if actor.role != "HQ_ADMIN":
            fail("FORBIDDEN", "只有总部管理员可以维护品牌通用券", 403)
    else:
        require_store(db, actor, template.store_id)


@router.get("/admin/stores/{store_id}/coupon-templates")
def coupon_templates(store_id: int, request: Request,
                     actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    rows = db.scalars(select(CouponTemplate).where(
        (CouponTemplate.scope == "GLOBAL") |
        (CouponTemplate.store_id == store_id)).order_by(CouponTemplate.id)).all()
    return response(request, [_template_view(item) for item in rows])


@router.post("/admin/coupon-templates", status_code=201)
def create_coupon_template(body: NewCouponTemplate, request: Request,
                           key: WriteKey, actor: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    if body.scope == "GLOBAL":
        if actor.role != "HQ_ADMIN" or body.store_id is not None:
            fail("FORBIDDEN", "品牌通用券仅限总部创建，且不填写门店", 403)
    else:
        if body.store_id is None:
            fail("INVALID_INPUT", "门店券必须填写 store_id", 422)
        require_store(db, actor, body.store_id)
    if body.starts_at >= body.ends_at:
        fail("INVALID_INPUT", "优惠券结束时间必须晚于开始时间", 422)
    marker, replay = claim_key(db, actor.id, "admin:coupon_template:create", key,
                               body.model_dump(mode="json"))
    if replay:
        template = db.get(CouponTemplate, marker.resource_id)
    else:
        template = CouponTemplate(**body.model_dump())
        db.add(template)
        db.flush()
        audit(db, actor, "COUPON_TEMPLATE_CREATE", "coupon_templates", template.id,
              {**body.model_dump(mode="json")})
        marker.resource_id, marker.status = template.id, "COMPLETED"
        db.commit()
    return response(request, _template_view(template))


@router.patch("/admin/coupon-templates/{template_id}")
def edit_coupon_template(template_id: int, body: EditCouponTemplate, request: Request,
                         key: WriteKey, actor: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    template = db.scalar(select(CouponTemplate).where(
        CouponTemplate.id == template_id).with_for_update())
    if template is None:
        fail("COUPON_NOT_FOUND", "优惠券模板不存在", 404)
    _template_access(db, actor, template)
    marker, replay = claim_key(db, actor.id, f"admin:coupon_template:edit:{template_id}",
                               key, body.model_dump(mode="json"))
    if not replay:
        updates = body.model_dump(exclude_unset=True)
        starts = updates.get("starts_at", template.starts_at)
        ends = updates.get("ends_at", template.ends_at)
        if starts is None or ends is None or starts >= ends:
            fail("INVALID_INPUT", "优惠券有效期不正确", 422)
        for field, value in updates.items():
            if value is None:
                fail("INVALID_INPUT", f"{field} 不能设置为空", 422)
            setattr(template, field, value)
        audit(db, actor, "COUPON_TEMPLATE_EDIT", "coupon_templates", template.id,
              body.model_dump(mode="json", exclude_unset=True))
        marker.resource_id, marker.status = template.id, "COMPLETED"
        db.commit()
    return response(request, _template_view(template))


@router.post("/admin/coupons/issue", status_code=201)
def issue_coupon(body: IssueCoupon, request: Request, key: WriteKey,
                 actor: User = Depends(current_user), db: Session = Depends(get_db)):
    template = db.get(CouponTemplate, body.template_id)
    if template is None:
        fail("COUPON_NOT_FOUND", "优惠券模板不存在", 404)
    _template_access(db, actor, template)
    if not template.active or template.ends_at <= datetime.now(timezone.utc):
        fail("COUPON_INVALID", "该优惠券已停用或过期")
    if template.scope == "STORE":
        require_member(db, actor, template.store_id, body.user_id)
    else:
        customer = db.get(User, body.user_id)
        if customer is None or customer.role != "CONSUMER" or customer.status != "ACTIVE":
            fail("MEMBER_NOT_FOUND", "目标用户不是有效消费者", 404)
    marker, replay = claim_key(db, actor.id, f"admin:coupon:issue:{body.template_id}",
                               key, body.model_dump(mode="json"))
    if replay:
        coupon = db.get(UserCoupon, marker.resource_id)
    else:
        coupon = UserCoupon(user_id=body.user_id, template_id=template.id,
                            status="AVAILABLE")
        db.add(coupon)
        db.flush()
        audit(db, actor, "COUPON_ISSUE", "user_coupons", coupon.id,
              {"user_id": body.user_id, "template_id": template.id,
               "store_id": template.store_id})
        marker.resource_id, marker.status = coupon.id, "COMPLETED"
        db.commit()
    return response(request, {"user_coupon_id": coupon.id, "user_id": coupon.user_id,
                              "template_id": coupon.template_id, "status": coupon.status})


@router.post("/orders/{order_id}/complete")
def complete_order(order_id: int, request: Request, key: WriteKey,
                   actor: User = Depends(current_user), db: Session = Depends(get_db)):
    base_order = db.get(Order, order_id)
    if base_order is None:
        fail("ORDER_NOT_FOUND", "订单不存在", 404)
    require_store(db, actor, base_order.store_id)
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    marker, replay = claim_key(db, actor.id, f"orders:complete:{order_id}", key,
                               {"order_id": order_id, "action": "complete"})
    if replay:
        if order.status != "COMPLETED":
            fail("ORDER_STATE_CONFLICT", "履约状态与操作记录不一致", 409)
    else:
        if order.status != "PAID":
            fail("ORDER_STATE_CONFLICT", "只有已支付订单可以完成制作", 409,
                 current_status=order.status)
        order.status = "COMPLETED"
        audit(db, actor, "ORDER_COMPLETE", "orders", order.id,
              {"store_id": order.store_id, "previous_status": "PAID"})
        marker.resource_id, marker.status = order.id, "COMPLETED"
        db.commit()
    return response(request, read_order(db, order))
