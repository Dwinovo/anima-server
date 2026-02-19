from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import AnyMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from app.domain.action_tools import SocialAction
from app.domain.action_types import ActionType
from app.services.neo4j_event_store import get_neo4j_driver
from app.services.social_graph_repository import SocialGraphRepository

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - 依赖可选
    ChatOpenAI = None  # type: ignore[assignment]


class AgentState(TypedDict):
    """单个 Agent 的 LangGraph 状态。

    设计重点：
    - session_id / agent_uuid 只放在 State，由系统写入与维护；
    - LLM 仅接触 recent_memory 和历史 messages，不直接接触底层系统 ID；
    - messages 使用 add_messages reducer，便于持续追加 AI/Tool 轨迹。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    agent_uuid: str
    recent_memory: str


_RUNTIME_DECISION_PROMPT = """你是 Minecraft 社交平台中的 Agent 决策器。
你必须调用一次 SocialAction 工具，并严格按 schema 输出参数。
禁止输出或伪造任何系统底层字段（例如 session_id、agent_uuid），这些由系统注入。
先写 inner_monologue，再给 action_type 和必要参数。"""

_SOCIAL_LLM: Runnable | None = None
_SOCIAL_GRAPH_REPO: SocialGraphRepository | None = None


def _get_social_llm() -> Runnable:
    """懒加载并缓存已绑定 SocialAction schema 的 LLM。"""

    global _SOCIAL_LLM
    if _SOCIAL_LLM is not None:
        return _SOCIAL_LLM

    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed.")

    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY must be set.")

    model_kwargs: dict[str, Any] = {
        "model": (
            os.getenv("ANIMA_LLM_MODEL")
            or os.getenv("MOONSHOT_MODEL")
            or "kimi-k2-turbo-preview"
        ),
        "api_key": api_key,
        # 按业务约定固定使用 Moonshot 网关地址。
        "base_url": "https://api.moonshot.cn/v1",
        "temperature": float(os.getenv("ANIMA_LLM_TEMPERATURE", "0.2")),
    }

    # 关键点：只绑定 SocialAction schema，让模型只产生“动作参数”，不碰系统底层 ID。
    _SOCIAL_LLM = ChatOpenAI(**model_kwargs).bind_tools(
        [SocialAction],
        tool_choice="required",
    )
    return _SOCIAL_LLM


def _get_social_graph_repo() -> SocialGraphRepository:
    """懒加载社交图谱仓储，复用全局 Neo4j Driver。"""

    global _SOCIAL_GRAPH_REPO
    if _SOCIAL_GRAPH_REPO is None:
        _SOCIAL_GRAPH_REPO = SocialGraphRepository(get_neo4j_driver())
    return _SOCIAL_GRAPH_REPO


def think_node(state: AgentState) -> dict[str, list[AnyMessage]]:
    """思考节点：读取 recent_memory，让 LLM 产出结构化动作参数。"""

    llm = _get_social_llm()
    recent_memory = state.get("recent_memory", "").strip() or "暂无近期记忆。"
    history_messages = state.get("messages", [])
    invoke_messages: list[AnyMessage] = [
        *history_messages,
        SystemMessage(content=_RUNTIME_DECISION_PROMPT),
        HumanMessage(
            content=(
                "以下是你此刻观察到的近期事件与社交动态：\n"
                f"{recent_memory}"
            )
        ),
    ]
    ai_message = llm.invoke(invoke_messages)
    return {"messages": [ai_message]}


def execute_action_node(state: AgentState) -> dict[str, list[ToolMessage]]:
    """执行节点：从 State 安全注入系统上下文，并组合 LLM 参数路由业务动作。"""

    messages = state.get("messages", [])
    if not messages:
        return {
            "messages": [
                ToolMessage(
                    content="Error: execute_action_node received empty messages.",
                    tool_call_id="missing_tool_call",
                    name="SocialAction",
                )
            ]
        }

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage):
        return {
            "messages": [
                ToolMessage(
                    content="Error: last message is not an AIMessage.",
                    tool_call_id="missing_tool_call",
                    name="SocialAction",
                )
            ]
        }

    if not last_message.tool_calls:
        return {
            "messages": [
                ToolMessage(
                    content="Error: no tool_calls found in AIMessage.",
                    tool_call_id="missing_tool_call",
                    name="SocialAction",
                )
            ]
        }

    tool_call = last_message.tool_calls[0]
    tool_call_id = tool_call.get("id") or "missing_tool_call"
    raw_args = tool_call.get("args", {})
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}

    # 关键安全点：
    # 底层上下文只从 LangGraph State 取，绝不信任/依赖 LLM 生成的系统字段。
    session_id = state.get("session_id", "")
    agent_uuid = state.get("agent_uuid", "")
    content = args.get("content")
    target_post_id = args.get("target_post_id")

    # 可观测性：打印每次 Agent 决策出的动作 payload，便于线上追踪行为选择。
    print(
        (
            "[AgentActionPayload] "
            f"session_id={session_id} agent_uuid={agent_uuid} payload={args!r}"
        ),
        flush=True,
    )

    try:
        action_type = ActionType(args.get("action_type"))
    except ValueError:
        result = f"Error: Unsupported action_type={args.get('action_type')!r}."
        return {
            "messages": [
                ToolMessage(
                    content=result,
                    tool_call_id=tool_call_id,
                    name="SocialAction",
                )
            ]
        }

    if action_type == ActionType.POST:
        if not isinstance(content, str) or not content.strip():
            result = "Error: POST action requires content."
        else:
            try:
                post_id = _get_social_graph_repo().create_post(
                    session_id=session_id,
                    agent_uuid=agent_uuid,
                    content=content,
                )
                result = f"Success: POST executed. New Post ID: {post_id}"
            except Exception as exc:
                result = f"Error: POST execution failed: {exc}"
    elif action_type == ActionType.LIKE:
        if not isinstance(target_post_id, str) or not target_post_id.strip():
            result = "Error: LIKE action requires target_post_id."
        else:
            try:
                created = _get_social_graph_repo().like_post(
                    session_id=session_id,
                    agent_uuid=agent_uuid,
                    target_post_id=target_post_id,
                )
                result = (
                    "Success: LIKE executed. New like recorded."
                    if created
                    else "Success: LIKE executed. Already liked before."
                )
            except Exception as exc:
                result = f"Error: LIKE execution failed: {exc}"
    elif action_type == ActionType.COMMENT:
        if not isinstance(target_post_id, str) or not target_post_id.strip():
            result = "Error: COMMENT action requires target_post_id."
        elif not isinstance(content, str) or not content.strip():
            result = "Error: COMMENT action requires content."
        else:
            try:
                post_id = _get_social_graph_repo().create_comment(
                    session_id=session_id,
                    agent_uuid=agent_uuid,
                    target_post_id=target_post_id,
                    content=content,
                )
                result = f"Success: COMMENT executed. New Post ID: {post_id}"
            except Exception as exc:
                result = f"Error: COMMENT execution failed: {exc}"
    elif action_type == ActionType.NOOP:
        result = "Success: NOOP action executed."
    else:  # pragma: no cover - ActionType 枚举兜底
        result = f"Error: Unsupported action_type={action_type.value!r}."

    return {
        "messages": [
            ToolMessage(
                content=result,
                tool_call_id=tool_call_id,
                name="SocialAction",
            )
        ]
    }


def should_continue(state: AgentState) -> str:
    """路由函数：若 LLM 产生 tool_calls，就进入执行节点。"""

    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "execute_action"
    return END


# LangGraph 内存型 checkpointer：按 thread_id 维护每个 Agent 的完整状态。
memory = MemorySaver()
_graph_builder = StateGraph(AgentState)
_graph_builder.add_node("think", think_node)
_graph_builder.add_node("execute_action", execute_action_node)
_graph_builder.add_edge(START, "think")
_graph_builder.add_conditional_edges("think", should_continue)
_graph_builder.add_edge("execute_action", END)
anima_app = _graph_builder.compile(checkpointer=memory)


def run_agent_social_cycle(*, thread_id: str, recent_memory: str) -> str:
    """对单个 Agent 执行一轮“思考 -> 执行”。

    返回执行节点写回的 ToolMessage 文本，便于上层服务记录或调试。
    """

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = anima_app.get_state(config)
    values = snapshot.values if isinstance(snapshot.values, dict) else {}

    # 若历史状态中没有基础上下文，则从 thread_id 回退解析，保证流程可运行。
    session_id = values.get("session_id")
    agent_uuid = values.get("agent_uuid")
    if not isinstance(session_id, str) or not session_id:
        session_id = thread_id.split(":", 1)[0]
    if not isinstance(agent_uuid, str) or not agent_uuid:
        agent_uuid = thread_id.split(":", 1)[1] if ":" in thread_id else ""

    final_state = anima_app.invoke(
        {
            "session_id": session_id,
            "agent_uuid": agent_uuid,
            "recent_memory": recent_memory,
        },
        config=config,
    )
    messages = final_state.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            return str(message.content)
    return "Error: Agent cycle finished without ToolMessage."


def list_thread_ids_by_session(session_id: str) -> list[str]:
    prefix = f"{session_id}:"
    thread_ids: set[str] = set()

    for checkpoint in memory.list(None):
        configurable = checkpoint.config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id.startswith(prefix):
            thread_ids.add(thread_id)

    return sorted(thread_ids)
