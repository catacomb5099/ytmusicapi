from pydantic import BaseModel

from app.models.common import AlbumStub, TrackDto, VideoStub


class RelatedArtist(BaseModel):
    browseId: str | None = None
    title: str | None = None
    subscribers: str | None = None
    thumbnailUrl: str | None = None


class ArtistDetail(BaseModel):
    channelId: str  # echoes the requested id verbatim -- ytmusicapi's own channelId differs
    name: str | None = None
    description: str | None = None
    subscribers: str | None = None
    monthlyListeners: str | None = None
    views: str | None = None
    thumbnailUrl: str | None = None
    topSongs: list[TrackDto] = []
    albums: list[AlbumStub] = []
    singles: list[AlbumStub] = []
    videos: list[VideoStub] = []
    related: list[RelatedArtist] = []
