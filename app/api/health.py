from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import session_factory

router = APIRouter(tags=["infra"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str | bool]:
    async with session_factory() as session:
        await session.execute(text("select 1"))

    settings = get_settings()
    return {
        "status": "ready",
        "database": True,
        "llm_provider": settings.llm_provider,
        "llm_configured": bool(settings.nvidia_api_key),
    }
