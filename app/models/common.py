from pydantic import BaseModel


class ArtistRef(BaseModel):
    name: str | None = None
    channelId: str | None = None


class AlbumRef(BaseModel):
    name: str | None = None
    browseId: str | None = None


class TrackDto(BaseModel):
    videoId: str | None = None
    title: str | None = None
    artists: list[ArtistRef] = []
    albumName: str | None = None
    durationSeconds: int | None = None
    trackNumber: int | None = None
    isAvailable: bool | None = None
    explicit: bool | None = None
    # Upstream sends an already-abbreviated display string ("2.2B plays"), not a number.
    # Kept verbatim on purpose -- do NOT run it through _to_int, which strips non-digits
    # and would silently turn "2.2B plays" into 22. Only get_song()'s SongMetadata.viewCount
    # carries an exact integer. Populated on album tracks; null on playlist/topSongs tracks.
    views: str | None = None


class AlbumStub(BaseModel):
    browseId: str | None = None
    title: str | None = None
    year: int | None = None
    thumbnailUrl: str | None = None


class VideoStub(BaseModel):
    videoId: str | None = None
    title: str | None = None
    thumbnailUrl: str | None = None
