import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.errors import register_exception_handlers
from app.routers import albums, artists, health, playlists, search, songs
from app.ytmusic_client import init_client

logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()
    yield


app = FastAPI(
    title="ytmusic-adapter",
    description="Stateless read-only adapter exposing ytmusicapi as a JSON API.",
    version="0.1.0",
    lifespan=lifespan,
)
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(search.router)
app.include_router(albums.router)
app.include_router(artists.router)
app.include_router(playlists.router)
app.include_router(songs.router)
