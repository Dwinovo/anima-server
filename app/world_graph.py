from __future__ import annotations

import asyncio
import os
import random
from typing import List, TypedDict

from langgraph.graph import END, START, StateGraph

from app.runtime import anima_app
from app.services.agent_registry import list_registered_agent_ids
from app.services.neo4j_event_store import get_neo4j_driver
from app.services.perception_service import PerceptionService


class WorldState(TypedDict):
    """世界级父图状态。

    字段说明：
    - session_id: 当前沙盒世界 ID。
    - pending_agents: 等待执行本轮推理的 Agent 队列（先进先出）。
    - completed_agents: 本轮 Tick 已经执行完成的 Agent 列表。
    """

    session_id: str
    pending_agents: List[str]
    completed_agents: List[str]


_PERCEPTION_SERVICE: PerceptionService | None = None


def _get_perception_service() -> PerceptionService:
    """懒加载感知服务，供父图节点重复复用。"""

    global _PERCEPTION_SERVICE
    if _PERCEPTION_SERVICE is None:
        _PERCEPTION_SERVICE = PerceptionService(
            get_neo4j_driver(),
            database=os.getenv("NEO4J_DATABASE"),
        )
    return _PERCEPTION_SERVICE


def get_active_agents(session_id: str) -> list[str]:
    """模拟 get_active_agents(session_id): 从注册表读取当前 Session 的 Agent UUID 列表。"""

    return list_registered_agent_ids(session_id)


async def init_world_tick(state: WorldState) -> WorldState:
    """初始化世界 Tick。

    这里只做两件事：
    1. 根据 session_id 拉取本轮活跃 Agent 列表，填入 pending_agents。
    2. 清空 completed_agents，确保是“本轮 Tick”的干净状态。
    """

    session_id = state["session_id"]
    active_agents = await asyncio.to_thread(get_active_agents, session_id)
    return {
        "session_id": session_id,
        "pending_agents": active_agents,
        "completed_agents": [],
    }


async def run_next_agent_node(state: WorldState) -> WorldState:
    """串行执行队首 Agent（核心执行器）。

    队列流转逻辑：
    - 从 pending_agents 队首 pop(0) 取出下一个 Agent；
    - 先读取“最新感知”，保证它能看到前一个 Agent 刚落库的变化；
    - 再调用子图 anima_app 完成单 Agent 生命周期；
    - 最后把该 Agent 放入 completed_agents，并返回更新后的队列状态。
    """

    session_id = state["session_id"]
    pending_agents = list(state.get("pending_agents", []))
    completed_agents = list(state.get("completed_agents", []))

    # 队列为空时直接返回，让路由函数决定走向 END。
    if not pending_agents:
        return {
            "session_id": session_id,
            "pending_agents": pending_agents,
            "completed_agents": completed_agents,
        }

    agent_uuid = pending_agents.pop(0)

    # 每次都在当前时刻重取感知，确保串行因果链：后一个 Agent 可以看到前一个 Agent 的新行为。
    recent_memory = await asyncio.to_thread(
        _get_perception_service().get_formatted_perception,
        session_id,
        agent_uuid,
    )

    # 关键点：
    # 1) 不改 anima_app 内部逻辑，只作为子图调用；
    # 2) thread_id 固定为 "session_id:agent_uuid"，用于 checkpointer 记忆持久化与隔离。
    thread_id = f"{session_id}:{agent_uuid}"
    await asyncio.to_thread(
        anima_app.invoke,
        {
            "session_id": session_id,
            "agent_uuid": agent_uuid,
            "recent_memory": recent_memory,
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    # 拟真错峰：模拟真实人类反应时间，降低行为“同毫秒爆发”的机器感。
    await asyncio.sleep(random.uniform(1.5, 3.5))

    completed_agents.append(agent_uuid)
    return {
        "session_id": session_id,
        "pending_agents": pending_agents,
        "completed_agents": completed_agents,
    }


def router_condition(state: WorldState) -> str:
    """路由条件：队列空则结束，否则继续执行下一个 Agent。"""

    if not state.get("pending_agents"):
        return END
    return "run_next_agent_node"


_world_builder = StateGraph(WorldState)
_world_builder.add_node("init_world_tick", init_world_tick)
_world_builder.add_node("run_next_agent_node", run_next_agent_node)
_world_builder.add_edge(START, "init_world_tick")
_world_builder.add_edge("init_world_tick", "run_next_agent_node")
_world_builder.add_conditional_edges("run_next_agent_node", router_condition)

# 父图编译产物：外部通过 world_app.ainvoke(...) 触发整个世界 Tick。
world_app = _world_builder.compile()
