from fastapi import APIRouter, Depends

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import map_song_metadata
from app.models.song import SongMetadata
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/songs", tags=["songs"])


@router.get("/{video_id}", response_model=SongMetadata)
def get_song(video_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> SongMetadata:
    """Metadata only. streamingData/playabilityStatus are never read by the mapper and
    never reach this response -- no playback/streaming path is exposed by this adapter."""
    raw = client.call("get_song", video_id)
    if not raw or not raw.get("videoDetails"):
        raise NotFoundError(f"No song found for videoId '{video_id}'")
    return map_song_metadata(raw)
