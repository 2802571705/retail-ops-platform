"""显式LangGraph工具调用循环；模型和工具执行器是普通的Python函数。"""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class AgentState(TypedDict):
    messages: list[dict]
    rounds: int
    calls: int
    successful: int
    requested: list[dict]
    answer: str | None
    error: str | None


def run_graph(messages, model_call, execute_tool):
    """调用模型并判断下一步,最多调用模型 4 次"""
    def invoke_model(state: AgentState):
        if state['rounds'] >= 4:
            return {'error': 'ROUND_LIMIT', 'requested': []}
        """调用模型后，取出 tool_calls，并先把 rounds 加一、requested 设为本轮请求。"""
        msg = model_call(state['messages'])
        requested = msg.get('tool_calls') or []
        update = {'rounds': state['rounds'] + 1, 'requested': requested}
        """如果模型直接回答、不再调工具：取 content，转字符串，截断到 6000 字符，再 strip()"""
        if not requested:
            answer = str(msg.get('content') or '')[:6000].strip()
            return {**update, 'answer': answer, 'error': ('NO_TOOL_EVIDENCE' if not state['successful'] else None if answer else 'EMPTY_ANSWER')}
        """最多执行 6 次工具调用，包括失败的调用"""
        if state['calls'] + len(requested) > 6:
            return {**update, 'error': 'TOOL_LIMIT', 'requested': []}
        return {**update, 'messages': state['messages'] + [{'role': 'assistant', 'content': msg.get('content') or '', 'tool_calls': requested}]}

    """执行工具并回填结果"""
    def execute_tools(state: AgentState):
        messages = list(state['messages']); successful = state['successful']
        for call in state['requested']:
            result, ok = execute_tool(call)
            successful += int(ok)
            messages.append(result)
        return {'messages': messages, 'successful': successful,
                'calls': state['calls'] + len(state['requested']), 'requested': []}

    def route(state: AgentState):
        return 'tools' if state['requested'] and not state['error'] else END

    graph = StateGraph(AgentState)
    graph.add_node('model', invoke_model)
    graph.add_node('tools', execute_tools)
    graph.add_edge(START, 'model')
    graph.add_conditional_edges('model', route, {'tools': 'tools', END: END})
    graph.add_edge('tools', 'model')
    return graph.compile().invoke({'messages': messages, 'rounds': 0, 'calls': 0,
                                   'successful': 0, 'requested': [], 'answer': None, 'error': None},
                                  config={'recursion_limit': 12})
