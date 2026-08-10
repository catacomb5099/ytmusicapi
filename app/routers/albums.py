from fastapi import APIRouter, Depends

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import map_album_detail
from app.models.album import AlbumDetail
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/albums", tags=["albums"])


def _get_album(client: YTMusicClient, browse_id: str) -> AlbumDetail:
    raw = client.call("get_album", browse_id)
    if not raw:
        raise NotFoundError(f"No album found for browseId '{browse_id}'")
    return map_album_detail(raw, requested_browse_id=browse_id)


@router.get("/by-audio-playlist/{audio_playlist_id}", response_model=AlbumDetail)
def get_album_by_audio_playlist(
    audio_playlist_id: str, client: YTMusicClient = Depends(get_ytmusic)
) -> AlbumDetail:
    """Bridges an OLAK5uy_... audioPlaylistId to its MPREb_... album browseId, so callers
    never have to perform this two-call resolution themselves."""
    browse_id = client.call("get_album_browse_id", audio_playlist_id)
    if not browse_id:
        raise NotFoundError(f"No album browseId found for audioPlaylistId '{audio_playlist_id}'")
    return _get_album(client, browse_id)


@router.get("/{browse_id}", response_model=AlbumDetail)
def get_album(browse_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> AlbumDetail:
    return _get_album(client, browse_id)
