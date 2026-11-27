from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.extracta import router as extracta_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.processing import router as processing_router
from app.core.config import get_settings
from app.extracta.batches import recover_interrupted
from app.extracta.storage import recover_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    recover_interrupted(get_settings())
    await recover_database(get_settings())
    yield


settings = get_settings()
app = FastAPI(title="Extracta API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(processing_router)
app.include_router(orders_router)
app.include_router(extracta_router)
