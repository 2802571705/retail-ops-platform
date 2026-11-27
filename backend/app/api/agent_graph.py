"""显式 LangGraph 工具调用循环；模型异步请求，数据库工具由执行器调度。"""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

MAX_ROUNDS = 4
MAX_TOOLS = 6


class AgentState(TypedDict):
    messages: list[dict]
    rounds: int
    calls: int
    successful: int
    requested: list[dict]
    answer: str | None
    error: str | None


async def run_graph(messages, model_call, execute_tool):
    async def invoke_model(state: AgentState):
        # 最后一轮或工具预算耗尽时只允许总结，不再执行无法总结的工具。
        final = state['rounds'] >= MAX_ROUNDS - 1 or state['calls'] >= MAX_TOOLS
        msg = await model_call(state['messages'], final=final)
        requested = msg.get('tool_calls') or []
        update = {'rounds': state['rounds'] + 1, 'requested': requested}
        if not requested:
            answer = str(msg.get('content') or '')[:6000].strip()
            return {**update, 'answer': answer, 'error': ('NO_TOOL_EVIDENCE' if not state['successful'] else None if answer else 'EMPTY_ANSWER')}
        if final:
            return {**update, 'error': 'ROUND_LIMIT' if state['rounds'] >= MAX_ROUNDS - 1 else 'TOOL_LIMIT', 'requested': []}
        return {**update, 'messages': state['messages'] + [{'role': 'assistant', 'content': msg.get('content') or '', 'tool_calls': requested}]}

    async def execute_tools(state: AgentState):
        # 返回完整的新消息列表，避免原地修改共享状态。超额工具不执行，但补齐协议要求的响应。
        messages = list(state['messages']); successful = state['successful']; calls = state['calls']
        for call in state['requested']:
            if calls < MAX_TOOLS:
                result, ok = await execute_tool(call)
                successful += int(ok); calls += 1
            else:
                result = {'role': 'tool', 'tool_call_id': call['id'], 'content': '{"error":"TOOL_LIMIT","message":"工具预算已耗尽，请根据已有证据总结"}'}
            messages.append(result)
        return {'messages': messages, 'successful': successful, 'calls': calls, 'requested': []}

    def route(state: AgentState):
        return 'tools' if state['requested'] and not state['error'] else END

    graph = StateGraph(AgentState)
    graph.add_node('model', invoke_model)
    graph.add_node('tools', execute_tools)
    graph.add_edge(START, 'model')
    graph.add_conditional_edges('model', route, {'tools': 'tools', END: END})
    graph.add_edge('tools', 'model')
    return await graph.compile().ainvoke({'messages': messages, 'rounds': 0, 'calls': 0,
                                         'successful': 0, 'requested': [], 'answer': None, 'error': None},
                                        config={'recursion_limit': 2 * MAX_ROUNDS + 2})
