from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from app.api.schemas.events import EventTickAcceptedData
from app.api.schemas.events import EventTickRequest
from app.api.schemas.events import EventResponse
from app.api.schemas.events import EventRequest
from app.api.schemas.response import APIResponse
from app.services.neo4j_event_store import get_neo4j_driver
from app.services.neo4j_event_store import ingest_event_to_neo4j
from app.world_graph import WorldState
from app.world_graph import world_app

router = APIRouter()


@router.post("/events", response_model=APIResponse[EventResponse], status_code=201)
def process_event(payload: EventRequest) -> APIResponse[EventResponse]:
    session_id = payload.session_id
    ingest_event_to_neo4j(get_neo4j_driver(), payload)

    response_payload = APIResponse[EventResponse].success(
        data=EventResponse(
            session_id=session_id,
        ),
        message="event created",
    )
    return response_payload


async def _run_world_tick_in_background(session_id: str) -> None:
    """后台触发世界级父图，不阻塞 API 响应。"""

    initial_state: WorldState = {
        "session_id": session_id,
        "pending_agents": [],
        "completed_agents": [],
    }
    await world_app.ainvoke(initial_state)


@router.post(
    "/events/tick",
    response_model=APIResponse[EventTickAcceptedData],
    status_code=202,
)
async def run_events_tick(
    payload: EventTickRequest,
    background_tasks: BackgroundTasks,
) -> APIResponse[EventTickAcceptedData]:
    """极速接入点：仅受理 Tick，请求立即返回 accepted。"""

    background_tasks.add_task(_run_world_tick_in_background, payload.session_id)
    return APIResponse[EventTickAcceptedData].success(
        data=EventTickAcceptedData(
            status="accepted",
            session_id=payload.session_id,
        ),
        message="tick accepted",
    )
