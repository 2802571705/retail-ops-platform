"""Store SKU, bundle and inventory maintenance on existing PostgreSQL tables."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.admin_models import StorePriceChange
from app.api.admin_common import audit, require_store
from app.api.orders import claim_key, fail, response
from app.core.database import get_db
from app.core.security import current_user
from app.models import (Bundle, BundleItem, Inventory, InventoryLedger,
                        Product, StoreProduct, User)

router = APIRouter(tags=["门店后台：商品、套餐与库存"])
WriteKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


class AttachProduct(BaseModel):
    product_id: int = Field(gt=0)
    price_cents: int = Field(ge=0)
    min_price_cents: int = Field(ge=0)
    max_price_cents: int = Field(ge=0)
    is_active: bool = True


class EditProduct(BaseModel):
    expected_price_version: int = Field(gt=0)
    price_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    reason: str = Field(min_length=2, max_length=300)


class BundlePart(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class CreateBundle(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_cents: int = Field(ge=0)
    components: list[BundlePart] = Field(min_length=1, max_length=30)
    is_active: bool = True


class EditBundle(BaseModel):
    expected_price_version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    price_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    components: list[BundlePart] | None = Field(default=None, min_length=1, max_length=30)


class StockAdjustment(BaseModel):
    product_id: int = Field(gt=0)
    delta_qty: int
    reason: str = Field(min_length=2, max_length=300)


def _product_view(db: Session, setting: StoreProduct, *, hq: bool) -> dict:
    p = db.get(Product, setting.product_id)
    qty = db.scalar(select(Inventory.available_qty).where(
        Inventory.store_id == setting.store_id,
        Inventory.product_id == setting.product_id))
    data = {"id": setting.id, "store_id": setting.store_id,
            "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category,
            "brand_status": p.status, "price_cents": setting.price_cents,
            "min_price_cents": setting.min_price_cents,
            "max_price_cents": setting.max_price_cents,
            "price_version": setting.price_version, "is_active": setting.is_active,
            "available_qty": qty if qty is not None else 0}
    if hq:
        data["estimated_cost_cents"] = setting.estimated_cost_cents
    return data


@router.get("/admin/stores/{store_id}/products")
def store_products(store_id: int, request: Request,
                   actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    rows = db.scalars(select(StoreProduct).where(StoreProduct.store_id == store_id)
                      .order_by(StoreProduct.product_id)).all()
    return response(request, [_product_view(db, row, hq=actor.role == "HQ_ADMIN") for row in rows])


@router.post("/admin/stores/{store_id}/products", status_code=201)
def attach_product(store_id: int, body: AttachProduct, request: Request,
                   key: WriteKey, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    product = db.get(Product, body.product_id)
    if product is None or product.status != "ACTIVE":
        fail("PRODUCT_NOT_FOUND", "品牌商品不存在或已停用", 404)
    if not body.min_price_cents <= body.price_cents <= body.max_price_cents:
        fail("INVALID_PRICE", "门店售价必须处于最低价与最高价之间", 422)
    marker, replay = claim_key(db, actor.id, f"admin:product:attach:{store_id}", key,
                               body.model_dump(mode="json"))
    if replay:
        setting = db.get(StoreProduct, marker.resource_id)
    else:
        if db.scalar(select(StoreProduct.id).where(
                StoreProduct.store_id == store_id,
                StoreProduct.product_id == body.product_id)) is not None:
            fail("PRODUCT_EXISTS", "该 SKU 已配置于本门店", 409)
        setting = StoreProduct(store_id=store_id, product_id=body.product_id,
                               price_cents=body.price_cents,
                               min_price_cents=body.min_price_cents,
                               max_price_cents=body.max_price_cents,
                               estimated_cost_cents=None, price_version=1,
                               is_active=body.is_active)
        db.add(setting)
        db.flush()
        db.add(Inventory(store_id=store_id, product_id=body.product_id, available_qty=0))
        audit(db, actor, "STORE_PRODUCT_ATTACH", "store_products", setting.id,
              {"store_id": store_id, **body.model_dump(mode="json")})
        marker.resource_id, marker.status = setting.id, "COMPLETED"
        db.commit()
    return response(request, _product_view(db, setting, hq=actor.role == "HQ_ADMIN"))


@router.patch("/admin/stores/{store_id}/products/{product_id}")
def edit_product(store_id: int, product_id: int, body: EditProduct, request: Request,
                 key: WriteKey, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    marker, replay = claim_key(db, actor.id, f"admin:product:edit:{store_id}:{product_id}", key,
                               body.model_dump(mode="json"))
    setting = db.scalar(select(StoreProduct).where(
        StoreProduct.store_id == store_id, StoreProduct.product_id == product_id).with_for_update())
    if setting is None:
        fail("PRODUCT_NOT_FOUND", "本门店未配置该商品", 404)
    if not replay:
        if setting.price_version != body.expected_price_version:
            fail("PRICE_VERSION_CONFLICT", "商品版本已变化，请刷新后重试", 409)
        new_price = body.price_cents if body.price_cents is not None else setting.price_cents
        new_active = body.is_active if body.is_active is not None else setting.is_active
        if not setting.min_price_cents <= new_price <= setting.max_price_cents:
            fail("INVALID_PRICE", "新价格超出本门店 SKU 允许区间", 422)
        if setting.estimated_cost_cents is not None and new_price < setting.estimated_cost_cents:
            fail("INVALID_PRICE", "新价格不能低于当前估算成本", 422)
        old_price, old_version = setting.price_cents, setting.price_version
        changed = new_price != old_price or new_active != setting.is_active
        if changed:
            row = db.execute(text("""
                UPDATE store_products
                SET price_cents = :price, is_active = :active,
                    price_version = price_version + 1,
                    last_price_changed_at = CASE WHEN price_cents <> :price
                                                 THEN now() ELSE last_price_changed_at END
                WHERE id = :id AND price_version = :version
                RETURNING price_version
            """), {"price": new_price, "active": new_active, "id": setting.id,
                   "version": body.expected_price_version}).first()
            if row is None:
                fail("PRICE_VERSION_CONFLICT", "商品版本已变化", 409)
            if new_price != old_price:
                change = StorePriceChange(store_id=store_id, product_id=product_id,
                                          source="MANUAL", recommendation_id=None,
                                          old_price_cents=old_price, new_price_cents=new_price,
                                          old_version=old_version, new_version=row[0],
                                          operator_id=actor.id, reason=body.reason)
                db.add(change)
            audit(db, actor, "STORE_PRODUCT_EDIT", "store_products", setting.id,
                  {"old_price_cents": old_price, "new_price_cents": new_price,
                   "old_version": old_version, "new_version": row[0],
                   "is_active": new_active, "reason": body.reason})
        marker.resource_id, marker.status = setting.id, "COMPLETED"
        db.commit()
        db.refresh(setting)
    return response(request, _product_view(db, setting, hq=actor.role == "HQ_ADMIN"))


def _validate_components(db: Session, store_id: int, components: list[BundlePart]):
    if len({part.product_id for part in components}) != len(components):
        fail("INVALID_BUNDLE", "套餐中不允许重复商品 SKU", 422)
    for part in components:
        product = db.get(Product, part.product_id)
        config = db.scalar(select(StoreProduct).where(
            StoreProduct.store_id == store_id,
            StoreProduct.product_id == part.product_id))
        if product is None or product.status != "ACTIVE" or config is None or not config.is_active:
            fail("INVALID_BUNDLE", "套餐组成商品未在该门店正常上架", 422,
                 product_id=part.product_id)


def _bundle_view(db: Session, bundle: Bundle) -> dict:
    parts = db.scalars(select(BundleItem).where(BundleItem.bundle_id == bundle.id)
                       .order_by(BundleItem.product_id)).all()
    return {"bundle_id": bundle.id, "store_id": bundle.store_id, "name": bundle.name,
            "price_cents": bundle.price_cents, "price_version": bundle.price_version,
            "is_active": bundle.is_active,
            "components": [{"product_id": part.product_id, "quantity": part.quantity} for part in parts]}


@router.get("/admin/stores/{store_id}/bundles")
def admin_bundles(store_id: int, request: Request,
                  actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    rows = db.scalars(select(Bundle).where(Bundle.store_id == store_id).order_by(Bundle.id)).all()
    return response(request, [_bundle_view(db, row) for row in rows])


@router.post("/admin/stores/{store_id}/bundles", status_code=201)
def create_bundle(store_id: int, body: CreateBundle, request: Request,
                  key: WriteKey, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    marker, replay = claim_key(db, actor.id, f"admin:bundle:create:{store_id}", key,
                               body.model_dump(mode="json"))
    if replay:
        bundle = db.get(Bundle, marker.resource_id)
    else:
        _validate_components(db, store_id, body.components)
        bundle = Bundle(store_id=store_id, name=body.name,
                        price_cents=body.price_cents, price_version=1,
                        is_active=body.is_active)
        db.add(bundle)
        db.flush()
        for part in body.components:
            db.add(BundleItem(bundle_id=bundle.id, product_id=part.product_id,
                              quantity=part.quantity))
        audit(db, actor, "BUNDLE_CREATE", "bundles", bundle.id, body.model_dump(mode="json"))
        marker.resource_id, marker.status = bundle.id, "COMPLETED"
        db.commit()
    return response(request, _bundle_view(db, bundle))


@router.patch("/admin/stores/{store_id}/bundles/{bundle_id}")
def edit_bundle(store_id: int, bundle_id: int, body: EditBundle, request: Request,
                key: WriteKey, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    marker, replay = claim_key(db, actor.id, f"admin:bundle:edit:{store_id}:{bundle_id}", key,
                               body.model_dump(mode="json"))
    bundle = db.scalar(select(Bundle).where(Bundle.id == bundle_id,
                                            Bundle.store_id == store_id).with_for_update())
    if bundle is None:
        fail("BUNDLE_NOT_FOUND", "套餐不存在", 404)
    if not replay:
        if bundle.price_version != body.expected_price_version:
            fail("PRICE_VERSION_CONFLICT", "套餐版本已变化，请刷新后重试", 409)
        if body.components is not None:
            _validate_components(db, store_id, body.components)
            db.execute(delete(BundleItem).where(BundleItem.bundle_id == bundle.id))
            for part in body.components:
                db.add(BundleItem(bundle_id=bundle.id, product_id=part.product_id,
                                  quantity=part.quantity))
        if body.name is not None:
            bundle.name = body.name
        if body.price_cents is not None:
            bundle.price_cents = body.price_cents
        if body.is_active is not None:
            bundle.is_active = body.is_active
        bundle.price_version += 1  # 套餐价格/组成变更后，客户端旧版本必须失效
        audit(db, actor, "BUNDLE_EDIT", "bundles", bundle.id, body.model_dump(mode="json"))
        marker.resource_id, marker.status = bundle.id, "COMPLETED"
        db.commit()
    return response(request, _bundle_view(db, bundle))


@router.get("/admin/stores/{store_id}/inventory")
def inventory_list(store_id: int, request: Request,
                   actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    rows = db.execute(select(Inventory, Product).join(Product, Product.id == Inventory.product_id)
                      .where(Inventory.store_id == store_id)
                      .order_by(Inventory.product_id)).all()
    return response(request, [{"product_id": p.id, "sku": p.sku, "name": p.name,
                               "available_qty": stock.available_qty} for stock, p in rows])


@router.post("/admin/stores/{store_id}/stock-adjustments", status_code=201)
def adjust_stock(store_id: int, body: StockAdjustment, request: Request,
                 key: WriteKey, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_store(db, actor, store_id)
    if body.delta_qty == 0:
        fail("INVALID_INPUT", "库存调整数量不能为零", 422)
    marker, replay = claim_key(db, actor.id, f"admin:stock:{store_id}", key,
                               body.model_dump(mode="json"))
    if replay:
        ledger = db.get(InventoryLedger, marker.resource_id)
    else:
        updated = db.execute(text("""
            UPDATE inventory SET available_qty = available_qty + :delta,
                                 updated_at = now()
            WHERE store_id = :store_id AND product_id = :product_id
              AND available_qty + :delta >= 0
            RETURNING available_qty
        """), {"delta": body.delta_qty, "store_id": store_id,
               "product_id": body.product_id}).first()
        if updated is None:
            fail("OUT_OF_STOCK", "库存配置不存在或减少后会产生负库存")
        ledger = InventoryLedger(store_id=store_id, product_id=body.product_id,
                                 delta_qty=body.delta_qty,
                                 reason="RESTOCK" if body.delta_qty > 0 else "ADJUSTMENT",
                                 operator_id=actor.id, order_id=None)
        db.add(ledger)
        db.flush()
        audit(db, actor, "STOCK_ADJUSTMENT", "inventory_ledger", ledger.id,
              {"store_id": store_id, "product_id": body.product_id,
               "delta_qty": body.delta_qty, "reason": body.reason,
               "available_qty_after": updated[0]})
        marker.resource_id, marker.status = ledger.id, "COMPLETED"
        db.commit()
    qty = db.scalar(select(Inventory.available_qty).where(
        Inventory.store_id == store_id, Inventory.product_id == body.product_id))
    return response(request, {"ledger_id": ledger.id, "product_id": body.product_id,
                              "delta_qty": ledger.delta_qty, "available_qty": qty})
