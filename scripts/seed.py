"""向正式业务表导入可重入的多门店演示基础数据（不创建数据库结构）。"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.database import engine  # noqa: E402
from app.core.security import password_hash  # noqa: E402
from app.models import (Bundle, BundleItem, CouponTemplate, Employee, Inventory, MemberAccount,
                        Product, Store, StoreProduct, User, UserCoupon)  # noqa: E402

password = os.getenv("DEMO_ADMIN_PASSWORD", "")
if len(password) < 8:
    raise SystemExit("请先在根目录 .env 设置至少 8 字符的 DEMO_ADMIN_PASSWORD")

store_defs = [
    ("上海南京西路店", "上海",
     "上海市静安区南京西路"),
    ("北京中关村店", "北京",
     "北京市海淀区中关村"),
]
product_defs = [
    ("DRINK-001", "茉莉奶绿", "奶茶", 1500),
    ("DRINK-002", "珍珠奶茶", "奶茶", 1800),
    ("DRINK-003", "柠檬绿茶", "果茶", 1400),
    ("DRINK-004", "抹茶拿铁", "奶茶", 2200),
]

with Session(engine) as db:
    store_ids = []
    for name, city, address in store_defs:
        store = db.scalar(select(Store).where(Store.name == name))
        if store is None:
            store = Store(name=name, city=city, address=address, status="OPEN")
            db.add(store)
            db.flush()
        store_ids.append(store.id)

    products = {}
    for sku, name, category, cents in product_defs:
        product = db.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            product = Product(sku=sku, name=name, category=category, unit="杯", status="ACTIVE")
            db.add(product)
            db.flush()
        products[sku] = product
        for store_id in store_ids:
            configured = db.scalar(select(StoreProduct).where(StoreProduct.store_id == store_id,
                                                              StoreProduct.product_id == product.id))
            if configured is None:
                db.add(StoreProduct(store_id=store_id, product_id=product.id,
                                    price_cents=cents + (100 if store_id == store_ids[1] else 0),
                                    estimated_cost_cents=cents // 2,
                                    min_price_cents=cents // 2 + 100,
                                    max_price_cents=cents * 2,
                                    price_version=1, is_active=True))
                db.flush()
            inventory = db.scalar(select(Inventory).where(Inventory.store_id == store_id,
                                                          Inventory.product_id == product.id))
            if inventory is None:
                db.add(Inventory(store_id=store_id, product_id=product.id, available_qty=100))

    for store_id in store_ids:
        bundle = db.scalar(select(Bundle).where(Bundle.store_id == store_id, Bundle.name == "双杯畅饮套餐"))
        if bundle is None:
            bundle = Bundle(store_id=store_id, name="双杯畅饮套餐", price_cents=2800,
                            price_version=1, is_active=True)
            db.add(bundle)
            db.flush()
        for sku in ("DRINK-001", "DRINK-003"):
            if db.get(BundleItem, (bundle.id, products[sku].id)) is None:
                db.add(BundleItem(bundle_id=bundle.id, product_id=products[sku].id, quantity=1))

    identities = [
        ("consumer@retailops.com", "普通用户", "CONSUMER"),
        ("store@retailops.com", "门店管理员", "STORE_ADMIN"),
        ("hq@retailops.com", "总部管理员", "HQ_ADMIN"),
    ]
    account_ids = {}
    for email, display_name, role in identities:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=display_name, role=role,
                        password_hash=password_hash(password), status="ACTIVE")
            db.add(user)
            db.flush()
        account_ids[role] = user.id
        if role == "CONSUMER" and db.scalar(select(MemberAccount).where(MemberAccount.user_id == user.id)) is None:
            db.add(MemberAccount(user_id=user.id, points_balance=0))

    store_admin_id = account_ids["STORE_ADMIN"]
    if db.scalar(select(Employee).where(Employee.user_id == store_admin_id)) is None:
        db.add(Employee(store_id=store_ids[0], user_id=store_admin_id,
                        name="门店管理员", status="ACTIVE"))
    # 正式结算会使用到的演示优惠券；重复运行不会重复发券或重置已经核销的券。
    coupon = db.scalar(select(CouponTemplate).where(CouponTemplate.name == "演示满20减3券",
                                                     CouponTemplate.scope == "GLOBAL"))
    if coupon is None:
        now = datetime.now(timezone.utc)
        coupon = CouponTemplate(name="演示满20减3券", scope="GLOBAL", store_id=None,
                                min_spend_cents=2000, discount_cents=300,
                                starts_at=now - timedelta(days=1),
                                ends_at=now + timedelta(days=365), active=True)
        db.add(coupon)
        db.flush()
    demo_consumer = account_ids["CONSUMER"]
    issued = db.scalar(select(UserCoupon).where(UserCoupon.user_id == demo_consumer,
                                                UserCoupon.template_id == coupon.id))
    if issued is None:
        db.add(UserCoupon(user_id=demo_consumer, template_id=coupon.id, status="AVAILABLE"))
    db.commit()

print("门店、商品、库存、套餐及三个角色账号已写入数据库。重复执行不会重置库存或覆盖业务数据。")
print("角色邮箱：" + " / ".join(
    email for email, _, _ in identities
))
