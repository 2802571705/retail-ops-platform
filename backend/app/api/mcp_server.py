"""RetailOps 本机经营工具服务；不对模型开放任何业务写入。"""
from asyncio import Semaphore
from datetime import date
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.admin_common import audit
from app.api.agent import TOOLS, dispatch_tool
from app.api.agent_metrics import scope
from app.api.hq_common import require_hq
from app.core.database import engine
from app.core.security import current_user

# 仅监听本机；无状态 HTTP 请求，每次工具调用独立认证。
mcp = FastMCP('RetailOps', host='127.0.0.1', port=8003,
              stateless_http=True, json_response=True)
query_slots = Semaphore(2)


def query_tool(name, date_from, date_to, store_id, request):
    # 使用现有 JWT 校验，不从模型参数获取身份或角色。
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise ValueError('需要总部管理员登录令牌')
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
    request.state.request_id = uuid4().hex
    try:
        with Session(engine) as db:
            # 数据查询事务禁止写入；审计在独立事务中提交。
            db.execute(text('SET TRANSACTION READ ONLY'))
            actor = current_user(credentials=credentials, db=db)
            require_hq(actor)
            if store_id is not None and store_id <= 0:
                raise ValueError('门店 ID 必须为正整数')
            s = scope(db, date_from, date_to, store_id)
            result = dispatch_tool(db, s, name, request, actor)
            actor_id = actor.id
            db.rollback()
            audit(db, actor, 'MCP_TOOL_READ', 'mcp_tool', actor_id,
                  {'tool_name': name, 'scope': s, 'request_id': request.state.request_id})
            db.commit()
            return {**result, 'mcp_request_id': request.state.request_id}
    except HTTPException as exc:
        raise ValueError('身份、权限或经营范围校验未通过') from None
    except Exception:
        raise ValueError('经营查询或审计失败，请检查服务日志') from None


def make_tool(name):
    # 九个工具共用相同的业务日期与门店参数；工具名称固定在注册阶段。
    async def call(date_from: date, date_to: date, ctx: Context,
                   store_id: int | None = None) -> dict:
        request = ctx.request_context.request
        async with query_slots:
            return await run_in_threadpool(query_tool, name, date_from, date_to, store_id, request)
    return call


for name, description in TOOLS.items():
    mcp.add_tool(make_tool(name), name=name, description=description,
                 annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                             openWorldHint=False))

if __name__ == '__main__':
    mcp.run(transport='streamable-http')
