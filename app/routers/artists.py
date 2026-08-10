from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import map_album_stubs_from_artist_albums, map_artist_detail
from app.models.artist import ArtistDetail
from app.models.common import AlbumStub
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/artists", tags=["artists"])

_ORDER_VALUES = {"Recency", "Popularity", "Alphabetical order"}


@router.get("/{channel_id}", response_model=ArtistDetail)
def get_artist(channel_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> ArtistDetail:
    raw = client.call("get_artist", channel_id)
    if not raw:
        raise NotFoundError(f"No artist found for channelId '{channel_id}'")
    return map_artist_detail(raw, requested_channel_id=channel_id)


@router.get("/{channel_id}/albums", response_model=list[AlbumStub])
def get_artist_albums(
    channel_id: str,
    limit: int = Query(100, ge=1, le=200),
    order: Literal["Recency", "Popularity", "Alphabetical order"] | None = None,
    client: YTMusicClient = Depends(get_ytmusic),
) -> list[AlbumStub]:
    """`params` is opaque and only obtainable from get_artist(), so this is always two
    upstream calls: get_artist() to resolve params, then get_artist_albums()."""
    artist_raw = client.call("get_artist", channel_id)
    if not artist_raw:
        raise NotFoundError(f"No artist found for channelId '{channel_id}'")

    albums_bucket = artist_raw.get("albums")
    if not albums_bucket or not albums_bucket.get("params"):
        return []

    kwargs: dict[str, object] = {"limit": limit}
    if order:
        kwargs["order"] = order
    raw_albums = client.call("get_artist_albums", albums_bucket["browseId"], albums_bucket["params"], **kwargs)
    return map_album_stubs_from_artist_albums(raw_albums)
