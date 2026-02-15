from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class SessionRegisterRequest(BaseModel):
    anima_session_id: str
    seed: str


class SessionRegisterResponse(BaseModel):
    accepted: bool = True


@router.post("/register", response_model=SessionRegisterResponse)
def register_session(payload: SessionRegisterRequest) -> SessionRegisterResponse:
    print("received /api/session/register payload:", payload.model_dump(mode="json"))
    return SessionRegisterResponse()
