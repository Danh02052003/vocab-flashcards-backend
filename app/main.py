from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import validate_mongo_settings
from app.db import create_indexes, ping_db
from app.routes.analytics import router as analytics_router
from app.routes.ai import router as ai_router
from app.routes.packs import router as packs_router
from app.routes.practice import router as practice_router
from app.routes.review import router as review_router
from app.routes.session import router as session_router
from app.routes.sync import router as sync_router
from app.routes.vocab import router as vocab_router
from app.routes.writing import router as writing_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        validate_mongo_settings()
        await ping_db()
        await create_indexes()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Failed to start backend. Check MongoDB connection and env values (MONGO_URL, MONGO_DB)."
        ) from exc
    yield


app = FastAPI(title="Vocab Flashcards Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vocab_router)
app.include_router(review_router)
app.include_router(session_router)
app.include_router(ai_router)
app.include_router(sync_router)
app.include_router(practice_router)
app.include_router(writing_router)
app.include_router(packs_router)
app.include_router(analytics_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
