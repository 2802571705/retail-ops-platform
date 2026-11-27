"""Shared authorization for the actual store-management APIs."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_models import AuditLog
from app.api.orders import fail
from app.models import Employee, Order, Store, User


def require_store(db: Session, actor: User, store_id: int) -> Store:
    if actor.role not in ("STORE_ADMIN", "HQ_ADMIN"):
        fail("FORBIDDEN", "此操作仅限门店或总部管理员", 403)
    store = db.get(Store, store_id)
    if store is None:
        fail("STORE_NOT_FOUND", "门店不存在", 404)
    if actor.role == "STORE_ADMIN" and db.scalar(select(Employee.id).where(
        Employee.user_id == actor.id, Employee.store_id == store_id,
        Employee.status == "ACTIVE")) is None:
        fail("FORBIDDEN", "无权管理该门店", 403)
    return store


def require_member(db: Session, actor: User, store_id: int, user_id: int) -> User:
    customer = db.get(User, user_id)
    if customer is None or customer.role != "CONSUMER" or customer.status != "ACTIVE":
        fail("MEMBER_NOT_FOUND", "会员不存在或已停用", 404)
    if actor.role != "HQ_ADMIN" and db.scalar(select(Order.id).where(
        Order.store_id == store_id, Order.user_id == user_id,
        Order.status.in_(["PAID", "COMPLETED"])).limit(1)) is None:
        fail("FORBIDDEN", "该会员尚无本门店有效消费记录", 403)
    return customer


def audit(db: Session, actor: User, action: str, target: str, target_id: int, detail: dict):
    db.add(AuditLog(actor_id=actor.id, action=action, target_type=target,
                    target_id=target_id, detail=detail))
