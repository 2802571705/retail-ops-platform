"""总部管理门店与员工：基于 Stage 02 原表，不改 Alembic DDL。"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.admin_common import audit
from app.api.hq_common import require_hq
from app.api.orders import claim_key, fail, response
from app.core.database import get_db
from app.core.security import current_user, password_hash
from app.models import Employee, Store, User

router = APIRouter(prefix="/hq", tags=["总部管理：门店与员工"])
WriteKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


class NewStore(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=255)
    status: Literal["OPEN", "CLOSED"] = "OPEN"


class EditStore(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    status: Literal["OPEN", "CLOSED"] | None = None


class NewEmployee(BaseModel):
    store_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def login_account_pair(self):
        if (self.email is None) != (self.password is None):
            raise ValueError("email 和 password 必须同时提供，或都不提供")
        return self


class EditEmployee(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    status: Literal["ACTIVE", "INACTIVE"] | None = None


def _store_data(item: Store):
    return {"id": item.id, "name": item.name, "city": item.city,
            "address": item.address, "status": item.status,
            "created_at": item.created_at.isoformat()}


def _employee_data(item: Employee, store: Store, account: User | None):
    return {"id": item.id, "store_id": store.id, "store_name": store.name,
            "name": item.name, "status": item.status,
            "user_id": item.user_id, "login_email": account.email if account else None}


@router.get("/stores")
def list_stores(request: Request, city: str | None = None,
                status: Literal["OPEN", "CLOSED"] | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hq(actor)
    statement = select(Store)
    if city:
        statement = statement.where(Store.city == city)
    if status:
        statement = statement.where(Store.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    items = db.scalars(statement.order_by(Store.id)
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return response(request, {"items": [_store_data(item) for item in items],
                              "total": total, "page": page, "page_size": page_size})


@router.post("/stores", status_code=201)
def create_store(body: NewStore, request: Request, key: WriteKey,
                 actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hq(actor)
    marker, replay = claim_key(db, actor.id, "hq:stores:create", key, body.model_dump(mode="json"))
    if replay:
        store = db.get(Store, marker.resource_id)
    else:
        store = Store(**body.model_dump())
        db.add(store)
        db.flush()
        audit(db, actor, "HQ_STORE_CREATE", "stores", store.id, body.model_dump())
        marker.resource_id, marker.status = store.id, "COMPLETED"
        db.commit()
    return response(request, _store_data(store))


@router.patch("/stores/{store_id}")
def edit_store(store_id: int, body: EditStore, request: Request, key: WriteKey,
               actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hq(actor)
    marker, replay = claim_key(db, actor.id, f"hq:stores:edit:{store_id}", key,
                               body.model_dump(mode="json"))
    store = db.scalar(select(Store).where(Store.id == store_id).with_for_update())
    if store is None:
        fail("STORE_NOT_FOUND", "门店不存在", 404)
    if not replay:
        changes = body.model_dump(exclude_unset=True)
        if not changes or any(value is None for value in changes.values()):
            fail("INVALID_INPUT", "请提供至少一个非空修改字段", 422)
        for field, value in changes.items():
            setattr(store, field, value)
        audit(db, actor, "HQ_STORE_EDIT", "stores", store.id, changes)
        marker.resource_id, marker.status = store.id, "COMPLETED"
        db.commit()
    return response(request, _store_data(store))


@router.get("/employees")
def list_employees(request: Request, store_id: int | None = Query(None, gt=0),
                   status: Literal["ACTIVE", "INACTIVE"] | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hq(actor)
    statement = (select(Employee, Store, User)
                 .join(Store, Store.id == Employee.store_id)
                 .outerjoin(User, User.id == Employee.user_id))
    if store_id:
        statement = statement.where(Employee.store_id == store_id)
    if status:
        statement = statement.where(Employee.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(Employee.id).offset((page - 1) * page_size)
                      .limit(page_size)).all()
    return response(request, {"items": [_employee_data(e, s, u) for e, s, u in rows],
                              "total": total, "page": page, "page_size": page_size})


@router.post("/employees", status_code=201)
def create_employee(body: NewEmployee, request: Request, key: WriteKey,
                    actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hq(actor)
    store = db.get(Store, body.store_id)
    if store is None:
        fail("STORE_NOT_FOUND", "目标门店不存在", 404)
    marker, replay = claim_key(db, actor.id, "hq:employees:create", key,
                               body.model_dump(mode="json"))
    if replay:
        employee = db.get(Employee, marker.resource_id)
    else:
        account = None
        if body.email is not None:
            email = str(body.email).lower()
            if db.scalar(select(User.id).where(User.email == email)) is not None:
                fail("EMAIL_EXISTS", "该邮箱已被使用", 409)
            account = User(email=email, password_hash=password_hash(body.password),
                           display_name=body.name, role="STORE_ADMIN", status="ACTIVE")
            db.add(account)
            db.flush()
        employee = Employee(store_id=body.store_id, name=body.name,
                            status=body.status, user_id=account.id if account else None)
        db.add(employee)
        db.flush()
        audit(db, actor, "HQ_EMPLOYEE_CREATE", "employees", employee.id,
              {"store_id": body.store_id, "name": body.name, "status": body.status,
               "account_created": account is not None})
        marker.resource_id, marker.status = employee.id, "COMPLETED"
        db.commit()
    return response(request, _employee_data(employee, db.get(Store, employee.store_id),
                                            db.get(User, employee.user_id) if employee.user_id else None))


@router.patch("/employees/{employee_id}")
def edit_employee(employee_id: int, body: EditEmployee, request: Request, key: WriteKey,
                  actor: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hq(actor)
    marker, replay = claim_key(db, actor.id, f"hq:employees:edit:{employee_id}", key,
                               body.model_dump(mode="json"))
    employee = db.scalar(select(Employee).where(Employee.id == employee_id).with_for_update())
    if employee is None:
        fail("EMPLOYEE_NOT_FOUND", "员工不存在", 404)
    if not replay:
        changes = body.model_dump(exclude_unset=True)
        if not changes or any(value is None for value in changes.values()):
            fail("INVALID_INPUT", "请提供至少一个非空修改字段", 422)
        for field, value in changes.items():
            setattr(employee, field, value)
        audit(db, actor, "HQ_EMPLOYEE_EDIT", "employees", employee.id, changes)
        marker.resource_id, marker.status = employee.id, "COMPLETED"
        db.commit()
    return response(request, _employee_data(employee, db.get(Store, employee.store_id),
                                            db.get(User, employee.user_id) if employee.user_id else None))
