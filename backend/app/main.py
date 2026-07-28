from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.scheduler import start_scheduler
from app.database.connection import engine, Base
import app.models.log  # Import models so Base knows about them


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up the FastAPI backend...")

    # Create MySQL database tables
    Base.metadata.create_all(bind=engine)
    print("MySQL database tables verified/created.")

    start_scheduler()
    yield

    print("Shutting down the FastAPI backend...")


app = FastAPI(
    title="Rasa + RAG + Ollama Backend API",
    description="Backend orchestration for AI chatbot pipeline with "
    "confidence-based routing, RAG scoring, conversation memory, "
    "streaming responses, and document ingestion.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev servers to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers 
from app.api.endpoints import chat, crawl, ingest

app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(crawl.router, prefix="/api/v1", tags=["Crawl"])
app.include_router(ingest.router, prefix="/api/v1", tags=["Ingest"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Backend API v2.0 is running!"}


@app.get("/")
async def root():
    return {
        "message": "Welcome to the AI Chatbot Backend Pipeline v2.0. "
        "See /docs for API documentation."
    }