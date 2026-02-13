from fastapi import APIRouter

from app.api.routes.status import router as status_router
from app.api.routes.step import router as step_router

router = APIRouter()
router.include_router(status_router, tags=["status"])
router.include_router(step_router, tags=["step"])
