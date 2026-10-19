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
    trackCount: int | None = None
    # Kept verbatim like TrackDto.views, never a number. Songs and videos: YouTube's abbreviated play
    # count without a noun ("7.2M"). Playlists: how often the playlist itself was viewed, in YouTube
    # Music's own wording with its noun ("375K views"), user-made playlists only (YouTube Music's own
    # editorial playlists show a song count there instead). Null on the "Top result" card and on
    # albums and artists.
    views: str | None = None


class SearchResponse(BaseModel):
    query: str
    type: str | None = None
    count: int
    items: list[SearchResultItem]
