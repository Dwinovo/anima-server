from __future__ import annotations

import json
import os
import traceback
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import AnyMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from app.api.schemas.events import ActionData
from app.api.schemas.events import ActionDecision
from app.api.schemas.events import NoopActionPayload

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - depends on optional dependency
    ChatOpenAI = None  # type: ignore[assignment]


class AnimaState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _passthrough_node(_: AnimaState) -> dict[str, Any]:
    return {}


memory = MemorySaver()
_graph_builder = StateGraph(AnimaState)
_graph_builder.add_node("passthrough", _passthrough_node)
_graph_builder.add_edge(START, "passthrough")
_graph_builder.add_edge("passthrough", END)
anima_app = _graph_builder.compile(checkpointer=memory)

_system_prompt = (
    "你是一个社交平台行为决策代理。"
    "根据输入事件，为当前角色选择一个动作：post/like/comment/repost/noop。"
    "必须严格按给定结构化 schema 输出。"
)


def _build_model():
    if ChatOpenAI is None:
        print("[runtime] langchain_openai is not installed, fallback to noop action.")
        return None

    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        print("[runtime] MOONSHOT_API_KEY is not set, fallback to noop action.")
        return None

    model = ChatOpenAI(
        model=os.getenv("MOONSHOT_MODEL", "kimi-k2-turbo-preview"),
        api_key=api_key,
        base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
        temperature=float(os.getenv("MOONSHOT_TEMPERATURE", "0.6")),
    )
    return model


_action_model = _build_model()


def infer_action(*, thread_id: str, event_5w: dict[str, Any]) -> ActionData:
    global _action_model
    if _action_model is None:
        _action_model = _build_model()

    if _action_model is None:
        return ActionData(type="noop", noop=NoopActionPayload(reason="model_not_configured"))

    system_prompt = os.getenv("ANIMA_ACTION_SYSTEM_PROMPT", _system_prompt)
    input_text = json.dumps(event_5w, ensure_ascii=False)
    print(f"[runtime] Starting action inference thread_id={thread_id} event_5w={input_text}")
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=input_text),
    ]
    config = {"configurable": {"thread_id": thread_id}}

    try:
        ai_msg = _action_model.invoke(messages, config=config)
        raw_content = getattr(ai_msg, "content", ai_msg)
        print(
            f"[runtime] Raw model response thread_id={thread_id} "
            f"raw={json.dumps(raw_content, ensure_ascii=False, default=str)}"
        )

        if isinstance(raw_content, str):
            decision_obj = ActionDecision.model_validate_json(raw_content)
        else:
            decision_obj = ActionDecision.model_validate(raw_content)

        action = decision_obj.action
        print(
            f"[runtime] Action inference succeeded thread_id={thread_id} "
            f"decision={decision_obj.model_dump_json(ensure_ascii=False)}"
        )

        anima_app.update_state(config, {"messages": [HumanMessage(content=input_text)]})
        anima_app.update_state(
            config,
            {"messages": [AIMessage(content=decision_obj.model_dump_json(ensure_ascii=False))]},
        )
        return action
    except Exception as exc:  # pragma: no cover - external model failure
        print(f"[runtime] Action inference failed: {exc}")
        print(traceback.format_exc())
        return ActionData(type="noop", noop=NoopActionPayload(reason="action_inference_failed"))
