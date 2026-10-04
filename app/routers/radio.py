from typing import Any

from fastapi import APIRouter, Depends, Query
from ytmusicapi.exceptions import YTMusicServerError

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import map_radio
from app.models.playlist import PlaylistDetail
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/radio", tags=["radio"])

# ytmusicapi's own message when YouTube sends a watch page with no queue in it, which is what an
# unknown video id or a radio YouTube cannot build gets. Any other server error is a real failure.
_NO_RADIO = "No content returned by the server"


def _watch(client: YTMusicClient, seed_id: str, **kwargs: Any) -> Any:
    try:
        return client.call("get_watch_playlist", **kwargs)
    except YTMusicServerError as exc:
        if _NO_RADIO in str(exc):
            raise NotFoundError(f"No radio found for '{seed_id}'") from exc
        raise


@router.get("/{seed_id}", response_model=PlaylistDetail)
def get_radio(
    seed_id: str,
    limit: int = Query(25, ge=1, le=100),
    client: YTMusicClient = Depends(get_ytmusic),
) -> PlaylistDetail:
    """YouTube Music's own radio ("mix") for a song (11-character videoId), an album (`MPREb_…`
    browseId) or a playlist (bare or `VL`-prefixed id). YouTube builds it fresh on every call, so
    two calls a minute apart share only some of their songs; store the answer if you need it again.

    A song's radio is `RDAMVM` + its videoId; an album's and a playlist's is `RDAMPL` + its playlist
    id. ytmusicapi's own `radio=True` flag is not used: on an album or playlist it only replays the
    seed. Two upstream calls for an album or playlist (the seed, for its title and songs), one for a song.
    """
    if seed_id.startswith("MPREb_"):
        seed_raw = client.call("get_album", seed_id)
        audio_playlist_id = seed_raw.get("audioPlaylistId") if isinstance(seed_raw, dict) else None
        if not audio_playlist_id:
            raise NotFoundError(f"No radio found for album '{seed_id}'")
        watch_raw = _watch(client, seed_id, playlistId="RDAMPL" + audio_playlist_id, limit=limit)
    elif len(seed_id) == 11:
        seed_raw = None
        # +1: the seed's own row comes first and is dropped.
        watch_raw = _watch(client, seed_id, videoId=seed_id, limit=limit + 1)
    else:
        bare_id = seed_id.removeprefix("VL")
        seed_raw = client.call("get_playlist", bare_id, limit=100)
        if not seed_raw:
            raise NotFoundError(f"No playlist found for id '{seed_id}'")
        watch_raw = _watch(client, seed_id, playlistId="RDAMPL" + bare_id, limit=limit)
    return map_radio(seed_id, seed_raw, watch_raw, limit)
