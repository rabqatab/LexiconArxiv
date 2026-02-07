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
from fastapi.responses import FileResponse

from src.api.dependencies import get_services
from src.api.routes import graph

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Pre-builds the ReverseCitationIndex at startup for fast subgraph queries.
    This takes ~10-30 seconds for a 150K node graph.
    """
    logger.info("Starting Graph Visualization API...")

    # Pre-build the citation index
    services = get_services()
    try:
        services.build_index(include_metadata=True)
        logger.info("Citation index built successfully")
    except Exception as e:
        logger.error(f"Failed to build citation index: {e}")
        logger.warning("API will start but subgraph queries will fail until index is ready")

    yield

    # Cleanup on shutdown
    logger.info("Shutting down Graph Visualization API...")


# Create FastAPI app
app = FastAPI(
    title="LexiconArxiv Graph API",
    description="REST API for interactive citation graph exploration",
    version="0.1.0",
    lifespan=lifespan,
)

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

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    """Serve the visualization UI."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {
        "name": "LexiconArxiv Graph API",
        "version": "0.1.0",
        "docs": "/docs",
        "visualization": "/static/index.html",
        "endpoints": {
            "health": "/graph/health",
            "stats": "/graph/stats",
            "paper": "/graph/paper/{paper_id}",
            "subgraph": "/graph/subgraph/{paper_id}?hops=1&direction=both",
        },
    }
