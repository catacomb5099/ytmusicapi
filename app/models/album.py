from pydantic import BaseModel

from app.models.common import ArtistRef, TrackDto


class RelatedAlbum(BaseModel):
    """One entry from get_album()'s `other_versions` or `related_recommendations` buckets.

    Both buckets carry an identical shape upstream, so they share this model.
    """

    browseId: str | None = None
    title: str | None = None
    type: str | None = None
    artists: list[ArtistRef] = []
    audioPlaylistId: str | None = None
    thumbnailUrl: str | None = None
    explicit: bool | None = None


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
    description: str | None = None
    explicit: bool | None = None
    tracks: list[TrackDto] = []
    otherVersions: list[RelatedAlbum] = []
    relatedRecommendations: list[RelatedAlbum] = []
