import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.profiles import router as profiles_router
from app.api.v1.sessions import router as sessions_router
from app.core.database import Base, engine
from app.core.logging import configure_logging
from app.models import outbox as outbox_model
from app.models import session as session_model
from app.services.outbox import run_outbox_worker

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    worker = asyncio.create_task(run_outbox_worker(), name="frappe-outbox-worker")
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


app = FastAPI(title="AI STEM Teaching Engine", version="0.1.0", lifespan=lifespan)
app.include_router(sessions_router)
app.include_router(profiles_router)


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    logging.exception("Unhandled request failure", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal_error", "message": "The request could not be completed"}},
    )


@app.get("/api/v1/health", tags=["health"])
def health():
    return {"status": "ok"}
