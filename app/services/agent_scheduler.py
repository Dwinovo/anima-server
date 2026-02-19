from __future__ import annotations

import asyncio
import os

from neo4j import Driver

from app.api.schemas.events import EventTickResponse
from app.api.schemas.events import TickAgentResult
from app.runtime import run_agent_social_cycle
from app.services.perception_service import PerceptionService


class AgentScheduler:
    """按 Session 并发调度所有 Agent 执行一轮推理。"""

    def __init__(
        self,
        driver: Driver,
        *,
        database: str | None = None,
        perception_service: PerceptionService | None = None,
    ) -> None:
        self._driver = driver
        self._database = database if database is not None else os.getenv("NEO4J_DATABASE")
        self._perception_service = (
            perception_service
            if perception_service is not None
            else PerceptionService(driver, database=self._database)
        )

    def _list_active_agent_uuids(self, session_id: str) -> list[str]:
        """从 Neo4j 获取当前 Session 的所有 Agent UUID。"""

        query = """
        MATCH (e:Entity {session_id: $session_id})
        RETURN DISTINCT e.entity_id AS agent_uuid
        ORDER BY agent_uuid
        """
        params = {"session_id": session_id}
        with self._driver.session(database=self._database) as session:
            records = session.execute_read(lambda tx: list(tx.run(query, params)))

        agent_uuids: list[str] = []
        for record in records:
            value = record.get("agent_uuid")
            if isinstance(value, str) and value.strip():
                agent_uuids.append(value)
        return agent_uuids

    async def _run_single_agent(self, session_id: str, agent_uuid: str) -> TickAgentResult:
        """单 Agent 执行链路：感知采集 -> LangGraph 推理。"""

        try:
            memory_text = await asyncio.to_thread(
                self._perception_service.get_formatted_perception,
                session_id,
                agent_uuid,
            )
            thread_id = f"{session_id}:{agent_uuid}"
            action_result = await asyncio.to_thread(
                run_agent_social_cycle,
                thread_id=thread_id,
                recent_memory=memory_text,
            )
            result_text = str(action_result)
            is_success = not result_text.startswith("Error:")
            return TickAgentResult(
                agent_uuid=agent_uuid,
                success=is_success,
                message=result_text,
            )
        except Exception as exc:
            return TickAgentResult(
                agent_uuid=agent_uuid,
                success=False,
                message=f"Agent tick failed: {exc}",
            )

    async def run_tick(self, session_id: str) -> EventTickResponse:
        """并发执行整个 Session 的 Agent tick，不因单点失败中断整体。"""

        agent_uuids = await asyncio.to_thread(self._list_active_agent_uuids, session_id)
        if not agent_uuids:
            return EventTickResponse(
                session_id=session_id,
                total_agents=0,
                succeeded=0,
                failed=0,
                results=[],
            )

        results = await asyncio.gather(
            *(self._run_single_agent(session_id, agent_uuid) for agent_uuid in agent_uuids)
        )
        succeeded = sum(1 for item in results if item.success)
        failed = len(results) - succeeded

        return EventTickResponse(
            session_id=session_id,
            total_agents=len(agent_uuids),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )
