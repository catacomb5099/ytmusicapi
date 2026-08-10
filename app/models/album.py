from pydantic import BaseModel

from app.models.common import ArtistRef, TrackDto


class AlbumDetail(BaseModel):
    browseId: str | None = None
    title: str | None = None
    type: str | None = None
    year: int | None = None
    trackCount: int | None = None
    durationSeconds: int | None = None
    audioPlaylistId: str | None = None
    artists: list[ArtistRef] = []
    thumbnailUrl: str | None = None
    tracks: list[TrackDto] = []
