"""消费者在结算前读取自己的积分与可用券。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import current_user
from app.models import CouponTemplate, MemberAccount, User, UserCoupon

router = APIRouter(tags=["我的会员权益"])


@router.get("/me/points")
def my_points(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    account = db.scalar(select(MemberAccount).where(MemberAccount.user_id == user.id))
    return {"data": {"points_balance": account.points_balance if account else 0},
            "error": None, "request_id": request.state.request_id}


@router.get("/me/coupons")
def my_coupons(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(UserCoupon, CouponTemplate)
        .join(CouponTemplate, CouponTemplate.id == UserCoupon.template_id)
        .where(UserCoupon.user_id == user.id)
        .order_by(UserCoupon.id.desc())
    ).all()
    data = [{"user_coupon_id": coupon.id, "name": template.name,
             "status": coupon.status, "scope": template.scope,
             "store_id": template.store_id, "min_spend_cents": template.min_spend_cents,
             "discount_cents": template.discount_cents,
             "starts_at": template.starts_at.isoformat(),
             "ends_at": template.ends_at.isoformat()}
            for coupon, template in rows]
    return {"data": data, "error": None, "request_id": request.state.request_id}
