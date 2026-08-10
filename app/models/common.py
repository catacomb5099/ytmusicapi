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


class AlbumStub(BaseModel):
    browseId: str | None = None
    title: str | None = None
    year: int | None = None
    thumbnailUrl: str | None = None


class VideoStub(BaseModel):
    videoId: str | None = None
    title: str | None = None
    thumbnailUrl: str | None = None
