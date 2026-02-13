from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Meta(BaseModel):
    authToken: str
    protocolVersion: str


class When(BaseModel):
    iso8601: str
    epochMillis: int
    gameTime: int


class Where(BaseModel):
    dimension: str
    x: float
    y: float
    z: float


class Who(BaseModel):
    observerId: str
    observerName: str
    perspective: str


class Actor(BaseModel):
    id: str | None = None
    name: str | None = None
    type: str | None = None


class Details(BaseModel):
    damageType: str | None = None
    damageSourceEntityType: str | None = None
    deathMessage: str | None = None


class Event(BaseModel):
    subject: Actor | None = None
    action: str
    object: Actor | None = None
    details: Details | None = None


class GameEventEnvelope(BaseModel):
    meta: Meta
    when: When
    where: Where
    who: Who
    event: Event


class StepResponse(BaseModel):
    accepted: bool = True


@router.post("/step", response_model=StepResponse)
def step(payload: GameEventEnvelope) -> StepResponse:
    print("received /step payload:", payload.model_dump(mode="json"))
    return StepResponse()
