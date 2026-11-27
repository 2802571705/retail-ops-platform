from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.orders import router as orders_router
from app.api.membership import router as membership_router
from app.api.admin_catalog import router as admin_catalog_router
from app.api.store_context import router as store_context_router
from app.api.admin_membership import router as admin_membership_router
from app.api.hq_admin import router as hq_admin_router
from app.api.hq_trend import router as hq_trend_router
from app.api.hq_analytics import router as hq_analytics_router
from app.api.agent import router as agent_router
from app.api.sales_detail import router as sales_detail_router


app = FastAPI(title="RetailOps 连锁饮品门店经营与数据分析系统", version="0.5.0")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        error = {"code": detail.get("code", f"HTTP_{exc.status_code}"),
                 "message": detail.get("message", "业务操作失败"),
                 **{k: v for k, v in detail.items() if k not in ("code", "message")}}
    else:
        error = {"code": f"HTTP_{exc.status_code}", "message": detail}
    return JSONResponse(status_code=exc.status_code,
                        content={"data": None, "error": error,
                                 "request_id": request.state.request_id})


@app.exception_handler(RequestValidationError)
async def input_error(request: Request, exc: RequestValidationError):
    fields = [{"field": ".".join(str(x) for x in issue["loc"]), "message": issue["msg"]}
              for issue in exc.errors()]
    return JSONResponse(status_code=422,
                        content={"data": None, "error": {"code": "INVALID_INPUT",
                                                        "message": "输入不符合接口要求", "fields": fields},
                                 "request_id": request.state.request_id})


app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(orders_router)
app.include_router(membership_router)
app.include_router(admin_catalog_router)
app.include_router(admin_membership_router)
app.include_router(store_context_router)
app.include_router(hq_trend_router)
app.include_router(hq_analytics_router)
app.include_router(hq_admin_router)
app.include_router(sales_detail_router)
app.include_router(agent_router)
