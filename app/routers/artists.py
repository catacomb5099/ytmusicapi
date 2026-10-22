import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.mappers import (
    TOP_SONGS_LIMIT,
    map_album_stubs_from_artist_albums,
    map_artist_detail,
    top_song_album_ids,
    top_song_rows,
)
from app.models.artist import ArtistDetail
from app.models.common import AlbumStub
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/artists", tags=["artists"])

logger = logging.getLogger(__name__)

_ORDER_VALUES = {"Recency", "Popularity", "Alphabetical order"}


# ytmusicapi's own default page; the artist page shows a scrolling row, so more is noise.
ALL_ALBUMS_LIMIT = 100


def _all_releases_or_none(client: YTMusicClient, artist_raw: dict[str, Any], shelf: str, **order: str) -> Any:
    """get_artist()'s albums and singles buckets are YouTube's artist-page shelves: ten releases,
    newest first, so for an old act the albums are all reissues and EPs (Black Sabbath's shows no
    'Paranoid') and a busy one shows ten of its 92 singles (Taylor Swift). The same bucket carries
    `params` for the full list, which YouTube can also order by popularity."""
    bucket = artist_raw.get(shelf)
    if not isinstance(bucket, dict) or not bucket.get("params"):
        return None
    try:
        return client.call("get_artist_albums", bucket["browseId"], bucket["params"], limit=ALL_ALBUMS_LIMIT, **order)
    except Exception as exc:  # noqa: BLE001 -- the artist-page shelf is a fine fallback
        logger.warning("get_artist_albums for all %s failed, keeping the page shelf: %r", shelf, exc)
        return None


def _all_playlists_or_none(client: YTMusicClient, artist_raw: dict[str, Any]) -> Any:
    """The "Playlists by <artist>" shelf shows ten; its title link opens them all (Taylor Swift: 17)."""
    bucket = artist_raw.get("playlists")
    if not isinstance(bucket, dict) or not bucket.get("browseId") or not bucket.get("params"):
        return None
    try:
        return client.call("get_user_playlists", bucket["browseId"], bucket["params"])
    except Exception as exc:  # noqa: BLE001 -- the shelf's ten are a fine fallback
        logger.warning("get_user_playlists for the artist's own playlists failed, keeping the shelf: %r", exc)
        return None


def _top_songs_or_none(client: YTMusicClient, artist_raw: dict[str, Any]) -> Any:
    """get_artist()'s songs bucket lists five; its browseId is YouTube's own "Top songs" playlist
    (`VLOLAK5uy_...`, about 150 songs), whose first rows are those five in the same order and whose
    rows carry the play count (app.ytmusic_client keeps it)."""
    bucket = artist_raw.get("songs")
    browse_id = bucket.get("browseId") if isinstance(bucket, dict) else None
    if not isinstance(browse_id, str) or not browse_id:
        return None
    try:
        return client.call("get_playlist", browse_id.removeprefix("VL"), limit=TOP_SONGS_LIMIT)
    except Exception as exc:  # noqa: BLE001 -- the page's five top songs are a fine fallback
        logger.warning("get_playlist for the Top songs playlist failed, keeping the page's top songs: %r", exc)
        return None


def _album_or_none(client: YTMusicClient, album_id: str) -> Any:
    try:
        return client.call("get_album", album_id)
    except Exception as exc:  # noqa: BLE001 -- a missing play count never fails the artist
        logger.warning("get_album(%s) for top-song plays failed: %r", album_id, exc)
        return None


@router.get("/{channel_id}", response_model=ArtistDetail)
def get_artist(channel_id: str, client: YTMusicClient = Depends(get_ytmusic)) -> ArtistDetail:
    """get_artist(), plus in parallel: get_artist_albums() for the full discography by popularity
    (replaces the ten-newest shelf in `albums`), get_artist_albums() for every single, newest first
    (replaces the ten-newest shelf in `singles`), get_user_playlists() for the artist's own playlists
    (replaces that shelf's ten in `playlists`), and get_playlist() on the "Top songs" playlist (its
    first ten rows, with their play counts, replace the page's five `topSongs`). Only when that
    playlist gives nothing: one get_album per distinct album among the page's five top songs, which
    carry no play count while their album's track rows do. All best-effort -- a failed call leaves
    the shelf as YouTube's page shows it or a song's `views` null, and never fails the artist response."""
    raw = client.call("get_artist", channel_id)
    if not raw:
        raise NotFoundError(f"No artist found for channelId '{channel_id}'")
    # The client's semaphore still bounds total upstream concurrency across requests.
    with ThreadPoolExecutor(max_workers=4) as pool:
        all_albums = pool.submit(_all_releases_or_none, client, raw, "albums", order="Popularity")
        # Newest first, YouTube's own order for singles: its first ten are exactly the page shelf.
        all_singles = pool.submit(_all_releases_or_none, client, raw, "singles")
        all_playlists = pool.submit(_all_playlists_or_none, client, raw)
        top_songs = pool.submit(_top_songs_or_none, client, raw).result()
        album_ids = [] if top_song_rows(top_songs) else top_song_album_ids(raw)
        found = pool.map(lambda album_id: _album_or_none(client, album_id), album_ids)
        albums = dict(zip(album_ids, found, strict=True))
    return map_artist_detail(
        raw,
        requested_channel_id=channel_id,
        albums=albums,
        all_albums=all_albums.result(),
        all_singles=all_singles.result(),
        all_playlists=all_playlists.result(),
        top_songs=top_songs,
    )


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
