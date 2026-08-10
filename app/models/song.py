from pydantic import BaseModel


class SongMetadata(BaseModel):
    """Metadata-only view of get_song(). Never carries streamingData/playabilityStatus."""

    videoId: str | None = None
    title: str | None = None
    author: str | None = None
    channelId: str | None = None
    lengthSeconds: int | None = None
    viewCount: int | None = None
    thumbnailUrl: str | None = None
