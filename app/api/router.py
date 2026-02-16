from fastapi import APIRouter

from app.api.routes.agents import router as agents_router
from app.api.routes.events import router as events_router
from app.api.routes.session import router as session_router
from app.api.routes.status import router as status_router

router = APIRouter()
router.include_router(status_router, tags=["status"])
router.include_router(session_router, prefix="/api", tags=["sessions"])
router.include_router(agents_router, prefix="/api", tags=["agents"])
router.include_router(events_router, prefix="/api", tags=["events"])
