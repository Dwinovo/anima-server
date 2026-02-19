from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.events import EventTickRequest
from app.api.schemas.events import EventTickResponse
from app.api.schemas.events import EventResponse
from app.api.schemas.events import EventRequest
from app.api.schemas.response import APIResponse
from app.services.agent_scheduler import AgentScheduler
from app.services.neo4j_event_store import get_neo4j_driver
from app.services.neo4j_event_store import ingest_event_to_neo4j

router = APIRouter()
_AGENT_SCHEDULER: AgentScheduler | None = None


def _get_agent_scheduler() -> AgentScheduler:
    global _AGENT_SCHEDULER
    if _AGENT_SCHEDULER is None:
        _AGENT_SCHEDULER = AgentScheduler(get_neo4j_driver())
    return _AGENT_SCHEDULER


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


@router.post("/events/tick", response_model=APIResponse[EventTickResponse], status_code=200)
async def run_events_tick(payload: EventTickRequest) -> APIResponse[EventTickResponse]:
    result = await _get_agent_scheduler().run_tick(payload.session_id)
    response_payload = APIResponse[EventTickResponse].success(
        data=result,
        message="tick finished",
    )
    return response_payload
