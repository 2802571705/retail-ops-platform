"""Read-only context for the authenticated store manager."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin_common import require_store
from app.api.orders import fail, response
from app.core.database import get_db
from app.core.security import current_user
from app.models import Employee, Product, User

router = APIRouter(tags=["门店后台：工作台"])


@router.get("/admin/me/store")
def my_store(request: Request, actor: User = Depends(current_user),
             db: Session = Depends(get_db)):
    if actor.role != "STORE_ADMIN":
        fail("FORBIDDEN", "仅门店管理员可访问本店工作台", 403)
    employee = db.scalar(select(Employee).where(
        Employee.user_id == actor.id, Employee.status == "ACTIVE"))
    if employee is None:
        fail("FORBIDDEN", "账号未绑定有效门店员工", 403)
    store = require_store(db, actor, employee.store_id)
    products = db.scalars(select(Product).where(Product.status == "ACTIVE")
                          .order_by(Product.id)).all()
    return response(request, {
        "store": {"id": store.id, "name": store.name, "city": store.city,
                  "address": store.address, "status": store.status},
        "employee_id": employee.id,
        "brand_products": [{"product_id": p.id, "sku": p.sku, "name": p.name}
                           for p in products],
    })
