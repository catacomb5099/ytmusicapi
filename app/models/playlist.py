from pydantic import BaseModel

from app.models.common import ArtistRef, TrackDto


class PlaylistDetail(BaseModel):
    id: str | None = None
    title: str | None = None
    description: str | None = None
    author: ArtistRef | None = None
    privacy: str | None = None
    trackCount: int | None = None
    durationSeconds: int | None = None
    thumbnailUrl: str | None = None
    tracks: list[TrackDto] = []
