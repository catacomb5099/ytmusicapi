from pydantic import BaseModel

from app.models.common import ArtistRef, TrackDto


class PlaylistDetail(BaseModel):
    id: str | None = None
    title: str | None = None
    description: str | None = None
    author: ArtistRef | None = None
    privacy: str | None = None
    trackCount: int | None = None
    durationSeconds: int | None = None
    thumbnailUrl: str | None = None
    tracks: list[TrackDto] = []
    # YouTube Music's own wording with its noun ("6.9M views"), verbatim: user-made playlists only.
    # None on YouTube Music's editorial playlists (which show no count), on radios, and when the
    # header carries none. A display string, never a number (see AGENTS.md on play counts).
    views: str | None = None
