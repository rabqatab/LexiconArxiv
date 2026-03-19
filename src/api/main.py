"""FastAPI application for Graph Visualization API.

Provides REST endpoints for interactive citation graph exploration.
The API serves D3.js-compatible JSON for subgraph neighborhoods around papers.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from src.api.dependencies import get_services
from src.api.routes import graph, search, trends

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Pre-builds the ReverseCitationIndex at startup for fast subgraph queries.
    This takes ~10-30 seconds for a 150K node graph.
    """
    logger.info("Starting LexiconArxiv API...")

    services = get_services()

    # Build citation index
    try:
        services.build_index(include_metadata=True)
        logger.info("Citation index built successfully")
    except Exception as e:
        logger.error(f"Failed to build citation index: {e}")
        logger.warning("API will start but subgraph queries will fail")

    # Initialize search service
    try:
        await services.init_search_service()
    except Exception as e:
        logger.error(f"Failed to init search service: {e}")
        logger.warning("Search API will be unavailable")

    yield

    await services.shutdown_search_service()
    logger.info("Shutting down LexiconArxiv API...")


# Create FastAPI app
app = FastAPI(
    title="LexiconArxiv API",
    description="Search and citation graph API for AI research papers",
    version="0.2.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Configure CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(graph.router)
app.include_router(search.router)
app.include_router(trends.router)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )


@app.get("/")
async def root():
    """Serve the visualization UI."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {
        "name": "LexiconArxiv API",
        "version": "0.2.0",
        "docs": "/docs",
        "visualization": "/static/index.html",
        "endpoints": {
            "health": "/graph/health",
            "graph_stats": "/graph/stats",
            "paper": "/graph/paper/{paper_id}",
            "subgraph": "/graph/subgraph/{paper_id}?hops=1&direction=both",
            "search": "/api/search",
            "paper_detail": "/api/paper/{paper_id}",
            "corpus_stats": "/api/stats",
        },
    }


@app.get("/search")
async def search_page():
    """Serve the search UI."""
    search_path = STATIC_DIR / "search.html"
    if search_path.exists():
        return FileResponse(search_path)
    return {"message": "Search UI not yet available", "api_docs": "/docs"}


@app.get("/trends")
async def trends_page():
    """Serve the trends dashboard UI."""
    trends_path = STATIC_DIR / "trends.html"
    if trends_path.exists():
        return FileResponse(trends_path)
    return {"message": "Trends UI not yet available", "api_docs": "/docs"}
