from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Bundle, BundleItem, Inventory, Product, Store, StoreProduct

router = APIRouter(tags=["门店与商品"])


def require_open_store(db: Session, store_id: int) -> Store:
    store = db.get(Store, store_id)
    if store is None or store.status != "OPEN":
        raise HTTPException(404, "门店不存在或暂停营业")
    return store


@router.get("/stores")
def stores(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Store).where(Store.status == "OPEN").order_by(Store.id)).all()
    data = [{"id": row.id, "name": row.name, "city": row.city, "address": row.address} for row in rows]
    return {"data": data, "error": None, "request_id": request.state.request_id}


@router.get("/stores/{store_id}/catalog")
def catalog(store_id: int, request: Request, db: Session = Depends(get_db)):
    require_open_store(db, store_id)
    rows = db.execute(
        select(Product, StoreProduct, Inventory.available_qty)
        .join(StoreProduct, StoreProduct.product_id == Product.id)
        .outerjoin(Inventory, and_(Inventory.store_id == StoreProduct.store_id,
                                   Inventory.product_id == StoreProduct.product_id))
        .where(StoreProduct.store_id == store_id, Product.status == "ACTIVE", StoreProduct.is_active.is_(True))
        .order_by(Product.id)
    ).all()
    data = [{"product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category,
             "unit": p.unit, "price_cents": sp.price_cents, "price_version": sp.price_version,
             "available_qty": qty or 0, "available": (qty or 0) > 0} for p, sp, qty in rows]
    return {"data": data, "error": None, "request_id": request.state.request_id}


@router.get("/stores/{store_id}/bundles")
def bundles(store_id: int, request: Request, db: Session = Depends(get_db)):
    require_open_store(db, store_id)
    package_rows = db.scalars(select(Bundle).where(Bundle.store_id == store_id,
                                                  Bundle.is_active.is_(True)).order_by(Bundle.id)).all()
    components = db.execute(
        select(BundleItem, Product, StoreProduct, Inventory.available_qty)
        .join(Bundle, Bundle.id == BundleItem.bundle_id)
        .join(Product, Product.id == BundleItem.product_id)
        .outerjoin(StoreProduct, and_(StoreProduct.store_id == store_id,
                                      StoreProduct.product_id == BundleItem.product_id))
        .outerjoin(Inventory, and_(Inventory.store_id == store_id,
                                   Inventory.product_id == BundleItem.product_id))
        .where(Bundle.store_id == store_id, Bundle.is_active.is_(True))
    ).all()
    grouped = {}
    for item, product, store_product, qty in components:
        grouped.setdefault(item.bundle_id, []).append((item, product, store_product, qty))
    data = []
    for bundle in package_rows:
        rows = grouped.get(bundle.id, [])
        sellable = [r for r in rows if r[1].status == "ACTIVE" and r[2] is not None and r[2].is_active]
        available_qty = min(((r[3] or 0) // r[0].quantity for r in sellable), default=0)
        if len(rows) != len(sellable):
            available_qty = 0
        data.append({"bundle_id": bundle.id, "name": bundle.name, "price_cents": bundle.price_cents,
                     "price_version": bundle.price_version, "available_qty": available_qty,
                     "available": available_qty > 0,
                     "components": [{"product_id": r[1].id, "name": r[1].name,
                                     "quantity": r[0].quantity} for r in rows]})
    return {"data": data, "error": None, "request_id": request.state.request_id}
