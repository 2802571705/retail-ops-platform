"""Agent Host 的 MCP Client；固定本机服务地址，不将身份凭证传给模型。"""
import json
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = 'http://127.0.0.1:8003/mcp'


@asynccontextmanager
async def open_mcp(authorization):
    # 不走系统代理、不跟随重定向，避免将本地登录令牌发送到其他主机。
    async with httpx.AsyncClient(headers={'Authorization': authorization},
                                 timeout=20, trust_env=False, follow_redirects=False) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as session:
                await session.initialize()
                yield session


async def discover_tools(session, allowed):
    # 从 MCP Server 动态发现工具，Host 只暴露已有九个白名单工具。
    listing = await session.list_tools()
    if listing.nextCursor:
        raise RuntimeError('MCP_TOOLSET_MISMATCH')
    tools = {tool.name: tool for tool in listing.tools if tool.name in allowed}
    if set(tools) != set(allowed):
        raise RuntimeError('MCP_TOOLSET_MISMATCH')
    # 模型不选择日期或门店：Host 使用页面已校验的范围补齐 MCP 参数。
    return [{'type': 'function', 'function': {'name': name,
             'description': tool.description or allowed[name],
             'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}
            for name, tool in tools.items()]


async def call_mcp_tool(session, name, scope):
    result = await session.call_tool(name, arguments={k: scope[k] for k in
                                                     ('date_from', 'date_to', 'store_id')})
    if result.isError:
        raise RuntimeError('MCP_TOOL_FAILED')
    data = result.structuredContent
    if data is None:
        # 兼容返回 JSON 文本的 MCP 工具。
        blocks = [block.text for block in result.content if block.type == 'text']
        if len(blocks) != 1:
            raise RuntimeError('MCP_INVALID_RESULT')
        data = json.loads(blocks[0])
    if not isinstance(data, dict) or data.get('scope') != scope or not data.get('mcp_request_id'):
        raise RuntimeError('MCP_INVALID_RESULT')
    return data
