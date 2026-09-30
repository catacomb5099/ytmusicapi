from pydantic import BaseModel

from app.models.common import AlbumRef, ArtistRef


class SongMetadata(BaseModel):
    """Metadata-only view of get_song(). Never carries streamingData/playabilityStatus."""

    videoId: str | None = None
    title: str | None = None
    author: str | None = None
    channelId: str | None = None
    lengthSeconds: int | None = None
    viewCount: int | None = None
    thumbnailUrl: str | None = None


class CreditsSection(BaseModel):
    """One block of the 'Song credits' panel, e.g. role='Written by', names=['Noel Gallagher'].
    `role` is the localized title YouTube shows (follows YTM_LANGUAGE)."""

    role: str
    names: list[str] = []


class SongDetails(BaseModel):
    """GET /v1/songs/{videoId}/details -- stitched from up to four ytmusicapi calls.

    `explicit` and `album`/`year` are only knowable for album ("ATV") ids; an official-video
    ("OMV") id honestly reports them as null. `credits` is [] when YouTube has none, never an error.
    """

    videoId: str
    title: str | None = None
    artists: list[ArtistRef] = []
    album: AlbumRef | None = None
    durationSeconds: int | None = None
    year: int | None = None
    # Exact plays of this one upload (get_song()). Not the number YouTube Music shows: see `plays`.
    viewCount: int | None = None
    # YouTube Music's combined play count in its own wording ("1.7B plays"), read from the song's
    # album track row and kept verbatim (never _to_int'd). Null for official-video ids and whenever
    # the album track is not found. Usually much bigger than `viewCount`.
    plays: str | None = None
    explicit: bool | None = None
    thumbnailUrl: str | None = None
    credits: list[CreditsSection] = []
