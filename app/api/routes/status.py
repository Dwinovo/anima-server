from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
def status() -> dict[str, str]:
    return {"status": "ok"}
