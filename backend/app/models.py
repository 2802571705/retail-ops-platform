"""映射现有 Alembic DDL；不要调用 metadata.create_all()。"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, ForeignKeyConstraint, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberAccount(Base):
    __tablename__ = "member_accounts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    points_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))


class StoreProduct(Base):
    __tablename__ = "store_products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    price_cents: Mapped[int] = mapped_column(BigInteger)
    estimated_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    min_price_cents: Mapped[int] = mapped_column(BigInteger)
    max_price_cents: Mapped[int] = mapped_column(BigInteger)
    price_version: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean)


class Bundle(Base):
    __tablename__ = "bundles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(120))
    price_cents: Mapped[int] = mapped_column(BigInteger)
    price_version: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean)


class BundleItem(Base):
    __tablename__ = "bundle_items"
    bundle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bundles.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[int] = mapped_column(BigInteger)
    available_qty: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["store_id", "product_id"], ["store_products.store_id", "store_products.product_id"]),
    )


# 第 04 阶段：订单、优惠券、积分及事务流水。字段与初始 Alembic 迁移完全一致。
class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    order_source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="PENDING_PAYMENT")
    gross_cents: Mapped[int] = mapped_column(BigInteger)
    coupon_discount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    points_used: Mapped[int] = mapped_column(BigInteger, default=0)
    points_discount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    payable_cents: Mapped[int] = mapped_column(BigInteger)
    user_coupon_id: Mapped[int | None] = mapped_column(ForeignKey("user_coupons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    item_type: Mapped[str] = mapped_column(String(16))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    bundle_id: Mapped[int | None] = mapped_column(ForeignKey("bundles.id"))
    item_name_snapshot: Mapped[str] = mapped_column(String(120))
    price_version_snapshot: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger)
    line_total_cents: Mapped[int] = mapped_column(BigInteger)


class OrderItemComponent(Base):
    __tablename__ = "order_item_components"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[str] = mapped_column(String(128), unique=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CouponTemplate(Base):
    __tablename__ = "coupon_templates"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(20))
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    min_spend_cents: Mapped[int] = mapped_column(BigInteger)
    discount_cents: Mapped[int] = mapped_column(BigInteger)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean)


class UserCoupon(Base):
    __tablename__ = "user_coupons"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("coupon_templates.id"))
    status: Mapped[str] = mapped_column(String(20))
    redeemed_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryLedger(Base):
    __tablename__ = "inventory_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[int] = mapped_column(BigInteger)
    delta_qty: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(30))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PointsLedger(Base):
    __tablename__ = "points_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("member_accounts.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    delta_points: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(20))
    balance_before: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRequest(Base):
    __tablename__ = "idempotency_requests"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
