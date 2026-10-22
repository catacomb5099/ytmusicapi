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
    # carries an exact integer. Populated on album tracks and on artist topSongs (read from each
    # song's album) and on an artist's "Top songs" playlist rows; null on other playlists' tracks.
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


class PlaylistStub(BaseModel):
    playlistId: str | None = None  # bare "PL...", the id /v1/playlists opens
    title: str | None = None
    thumbnailUrl: str | None = None
    # YouTube Music's own wording with its noun ("2.1M views"), verbatim, as the card shows it; None when it shows none.
    views: str | None = None
