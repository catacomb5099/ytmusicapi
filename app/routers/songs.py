from typing import Any

from fastapi import APIRouter, Depends
from ytmusicapi.exceptions import YTMusicServerError

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import (
    album_browse_id,
    credits_browse_id,
    is_official_video,
    map_song_details,
    map_song_metadata,
    pick_album_track,
    pick_watch_track,
)
from app.models.song import SongDetails, SongMetadata
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/songs", tags=["songs"])


def _get_song_or_404(client: YTMusicClient, video_id: str) -> dict[str, Any]:
    # An unknown id is not an exception upstream: playabilityStatus ERROR and no videoDetails.
    raw = client.call("get_song", video_id)
    if not raw or not raw.get("videoDetails"):
        raise NotFoundError(f"No song found for videoId '{video_id}'")
    return raw


@router.get("/{video_id}", response_model=SongMetadata)
def get_song(video_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> SongMetadata:
    """Metadata only. streamingData/playabilityStatus are never read by the mapper and
    never reach this response -- no playback/streaming path is exposed by this adapter."""
    return map_song_metadata(_get_song_or_404(client, video_id))


@router.get("/{video_id}/details", response_model=SongDetails)
def get_song_details(video_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> SongDetails:
    """Up to four upstream calls: get_song (404 gate, exact duration/views), get_watch_playlist
    (artists with ids, album, year), get_album (per-track explicit flag; only when the watch
    track names an album) and get_song_credits (skipped for official-video ids, which never have
    a credits panel). A not-found or upstream server error on any call after the first degrades
    to null/[] instead of failing the whole view -- an official-video id has no album, no year,
    no explicit flag and no credits, and that is the honest answer, not an error."""
    song_raw = _get_song_or_404(client, video_id)

    try:
        watch_raw = client.call("get_watch_playlist", videoId=video_id, limit=1)
    except YTMusicServerError:
        watch_raw = None
    watch_track = pick_watch_track(watch_raw, video_id)

    album_raw = None
    album_id = album_browse_id(watch_track)
    if album_id:
        try:
            album_raw = client.call("get_album", album_id)
        except (NotFoundError, YTMusicServerError):
            album_raw = None
    album_track = pick_album_track(album_raw, video_id)

    credits_raw = None
    if not is_official_video(watch_track):
        try:
            credits_raw = client.call("get_song_credits", credits_browse_id(album_track, video_id))
        except (NotFoundError, YTMusicServerError):
            credits_raw = None

    return map_song_details(video_id, song_raw, watch_track, album_raw, album_track, credits_raw)
