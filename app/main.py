import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cards import router as cards_router
from app.api.exception_handlers import register_exception_handlers
from app.config import settings
from app.services.exceptions import ExtractionServiceUnavailableError
from app.services.llm.model import load_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_model(settings.llm_model_path)
    except ExtractionServiceUnavailableError as exc:
        logger.warning("LLM model failed to load at startup: %s", exc)
    yield


app = FastAPI(title="Business Card Extractor API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(cards_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
