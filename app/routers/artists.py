import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import map_album_stubs_from_artist_albums, map_artist_detail, top_song_album_ids
from app.models.artist import ArtistDetail
from app.models.common import AlbumStub
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/artists", tags=["artists"])

logger = logging.getLogger(__name__)

_ORDER_VALUES = {"Recency", "Popularity", "Alphabetical order"}


def _album_or_none(client: YTMusicClient, album_id: str) -> Any:
    try:
        return client.call("get_album", album_id)
    except Exception as exc:  # noqa: BLE001 -- a missing play count never fails the artist
        logger.warning("get_album(%s) for top-song plays failed: %r", album_id, exc)
        return None


@router.get("/{channel_id}", response_model=ArtistDetail)
def get_artist(channel_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> ArtistDetail:
    """get_artist() plus one get_album per distinct album among the top songs (YouTube lists five
    top songs, so up to five extra calls, run in parallel): top songs carry no play count, their
    album's track rows do. Best-effort -- an album that fails to load leaves its songs' `views`
    null and never fails the artist response."""
    raw = client.call("get_artist", channel_id)
    if not raw:
        raise NotFoundError(f"No artist found for channelId '{channel_id}'")
    album_ids = top_song_album_ids(raw)
    # The client's semaphore still bounds total upstream concurrency across requests.
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = pool.map(lambda album_id: _album_or_none(client, album_id), album_ids)
        albums = dict(zip(album_ids, found, strict=True))
    return map_artist_detail(raw, requested_channel_id=channel_id, albums=albums)


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
