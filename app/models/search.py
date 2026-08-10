from pydantic import BaseModel

from app.models.common import AlbumRef, ArtistRef


class SearchResultItem(BaseModel):
    type: str | None = None
    videoId: str | None = None
    browseId: str | None = None
    playlistId: str | None = None
    title: str | None = None
    artists: list[ArtistRef] = []
    album: AlbumRef | None = None
    durationSeconds: int | None = None
    thumbnailUrl: str | None = None
    explicit: bool | None = None
    year: int | None = None


class SearchResponse(BaseModel):
    query: str
    type: str | None = None
    count: int
    items: list[SearchResultItem]
