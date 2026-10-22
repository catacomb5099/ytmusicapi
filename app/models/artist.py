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
    # YouTube's own "Top songs" playlist ("VLOLAK5uy_..."), verbatim; opens through /v1/playlists. None for
    # artists whose page has no songs shelf (tiny or new acts).
    songsPlaylistId: str | None = None
    albums: list[AlbumStub] = []
    singles: list[AlbumStub] = []
    videos: list[VideoStub] = []
    related: list[RelatedArtist] = []
