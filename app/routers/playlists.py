from fastapi import APIRouter, Depends, Query

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import map_playlist_detail
from app.models.playlist import PlaylistDetail
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/playlists", tags=["playlists"])


@router.get("/{playlist_id}", response_model=PlaylistDetail)
def get_playlist(
    playlist_id: str,
    limit: int = Query(100, ge=1, le=500),
    client: YTMusicClient = Depends(get_ytmusic),
) -> PlaylistDetail:
    # Search results carry the "VL"-prefixed browseId; get_playlist wants the bare id.
    bare_id = playlist_id.removeprefix("VL")
    raw = client.call("get_playlist", bare_id, limit=limit)
    if not raw:
        raise NotFoundError(f"No playlist found for id '{playlist_id}'")
    return map_playlist_detail(raw)
