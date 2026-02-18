from __future__ import annotations

import json
import operator
from typing_extensions import Annotated, TypedDict

from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

import app.runtime as runtime
from app.api.schemas.actions import ActionData
from app.api.schemas.events import EventRequest
from app.api.schemas.posts import PostItem
from app.services.action_executor import apply_action
from app.services.action_executor import get_posts


class InferredActionItem(TypedDict):
    thread_id: str
    action: ActionData


class EventWorkflowState(TypedDict):
    session_id: str
    event_payload: EventRequest
    target_thread_ids: list[str]
    social_posts: list[PostItem]
    thread_id: str
    # 多个并发 infer 节点会各自返回一条动作，使用 list + reducer 合并。
    inferred_actions: Annotated[list[InferredActionItem], operator.add]
    posts: list[PostItem]


def _fanout_infer(state: EventWorkflowState) -> str | list[Send]:
    # 无目标线程时直接进入提交节点，返回空帖子列表。
    if not state.get("target_thread_ids"):
        return "apply_actions"
    return [
        Send(
            "infer_action",
            {
                "thread_id": thread_id,
                "event_payload": state["event_payload"],
                "social_posts": state["social_posts"],
            },
        )
        for thread_id in state["target_thread_ids"]
    ]


def _infer_action_node(state: EventWorkflowState) -> dict[str, list[InferredActionItem]]:
    thread_id = state["thread_id"]
    action = runtime.infer_action(
        thread_id=thread_id,
        event_payload=state["event_payload"],
        social_posts=state["social_posts"],
    )
    print(
        f"[events] Inferred action thread_id={thread_id} "
        f"action={json.dumps(action.model_dump(), ensure_ascii=False)}"
    )
    return {"inferred_actions": [{"thread_id": thread_id, "action": action}]}


def _apply_actions_node(state: EventWorkflowState) -> dict[str, list[PostItem]]:
    # 并发推理后统一串行提交，避免多个 Agent 同时写帖子池带来顺序不确定性。
    action_by_thread = {item["thread_id"]: item["action"] for item in state.get("inferred_actions", [])}
    posts: list[PostItem] = []
    for thread_id in state["target_thread_ids"]:
        action = action_by_thread.get(thread_id)
        if action is None:
            continue
        _, _, actor_id = thread_id.partition(":")
        posts = apply_action(session_id=state["session_id"], actor_id=actor_id, action=action)
    return {"posts": posts}


_graph_builder = StateGraph(EventWorkflowState)
_graph_builder.add_node("fanout_infer", lambda _: {})
_graph_builder.add_node("infer_action", _infer_action_node)
_graph_builder.add_node("apply_actions", _apply_actions_node)
_graph_builder.add_edge(START, "fanout_infer")
_graph_builder.add_conditional_edges("fanout_infer", _fanout_infer)
_graph_builder.add_edge("infer_action", "apply_actions")
_graph_builder.add_edge("apply_actions", END)
_event_workflow_app = _graph_builder.compile()


def run_event_workflow(
    *,
    session_id: str,
    event_payload: EventRequest,
    target_thread_ids: list[str],
) -> list[PostItem]:
    # 固定本轮可见帖子快照：同一轮并发 Agent 看到一致的社交平台上下文。
    social_posts = get_posts(session_id)
    final_state = _event_workflow_app.invoke(
        {
            "session_id": session_id,
            "event_payload": event_payload,
            "target_thread_ids": target_thread_ids,
            "social_posts": social_posts,
            "thread_id": "",
            "inferred_actions": [],
            "posts": [],
        }
    )
    posts = final_state.get("posts", [])
    return posts if isinstance(posts, list) else []
