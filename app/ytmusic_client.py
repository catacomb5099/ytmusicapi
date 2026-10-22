import functools
import logging
import threading

import requests
import ytmusicapi.mixins.playlists as _ytm_playlists
import ytmusicapi.parsers.i18n as _ytm_i18n
import ytmusicapi.parsers.playlists as _ytm_playlist_rows
import ytmusicapi.parsers.search as _ytm_search
from ytmusicapi import YTMusic
from ytmusicapi.navigation import CAROUSEL, CAROUSEL_TITLE, NAVIGATION_BROWSE, TITLE, nav
from ytmusicapi.parsers.browsing import parse_content_list, parse_playlist

from app.config import settings
from app.errors import NotFoundError

logger = logging.getLogger(__name__)


def _keep_playlist_views_text() -> None:
    """Keep YouTube's own "6.9M views" beside ytmusicapi's lossy playlist header count.

    ytmusicapi 1.12.2 reads a user playlist's header line ("6.9M views • 100 tracks • 6+ hours")
    and stores `views = to_int("6.9M views")` = 69. The display string exists only in that raw
    header, so this wraps the module-global the playlist mixin calls by name and adds `viewsText`:
    the first run, verbatim, when the header has more than three runs; None otherwise, which is
    what YouTube Music's own editorial playlists send ("51 songs • 4 hours"). This is the one place
    outside mappers.py that reads a raw ytmusicapi dict. If the name ever vanishes from the library,
    log and skip: a cosmetic number must never stop the adapter from starting.
    """
    original = getattr(_ytm_playlists, "parse_playlist_header_meta", None)
    if original is None:
        logger.warning("ytmusicapi has no parse_playlist_header_meta; playlist views will be null")
        return
    if getattr(original, "_keeps_views_text", False):
        return  # already wrapped (any other __wrapped__ is the library's own decorator: wrap it)

    @functools.wraps(original)
    def with_views_text(header):
        meta = original(header)
        subtitle = header.get("secondSubtitle") if isinstance(header, dict) else None
        runs = subtitle.get("runs") if isinstance(subtitle, dict) else None
        first = runs[0] if isinstance(runs, list) and len(runs) > 3 else None
        text = first.get("text") if isinstance(first, dict) else None
        meta["viewsText"] = text if isinstance(text, str) else None
        return meta

    with_views_text._keeps_views_text = True  # type: ignore[attr-defined]
    _ytm_playlists.parse_playlist_header_meta = with_views_text


def _keep_playlist_row_views_text() -> None:
    """Keep YouTube's own "375K views" on playlist SEARCH ROWS, which ytmusicapi reads past.

    A playlist row's subtitle ends in one count run: "375K views" on a user-made playlist, "51 songs"
    on one of YouTube Music's own ("Playlist • author • count" on a mixed search, "author • count"
    on a filtered one). ytmusicapi 1.12.2 keeps only the "N songs" form (as `itemCount`) and drops
    a view count on the floor. This wraps the row parser `parse_search_results` calls by name and
    adds `viewsText`: the count run verbatim when the row has an author and the run is not a song
    count, None otherwise. The author/offset arithmetic is the library's own (`default_offset` and
    `has_author` in parsers/search.py), so an author name is never mistaken for a count. Same
    safety net as `_keep_playlist_views_text`: log and skip if the name is gone.
    """
    original = getattr(_ytm_search, "parse_search_result", None)
    if original is None:
        logger.warning("ytmusicapi has no parse_search_result; playlist search rows' views will be null")
        return
    if getattr(original, "_keeps_views_text", False):
        return

    @functools.wraps(original)
    def with_views_text(data, *args, **kwargs):
        result = original(data, *args, **kwargs)  # pass-through: a library signature change cannot break search
        if isinstance(result, dict) and result.get("resultType") == "playlist":
            result_type = args[0] if args else kwargs.get("result_type")
            offset = (not result_type or result_type == "album") * 2  # ytmusicapi's default_offset
            result["viewsText"] = _row_count_text(data, offset)
        return result

    with_views_text._keeps_views_text = True  # type: ignore[attr-defined]
    _ytm_search.parse_search_result = with_views_text


def _row_count_text(data, offset: int) -> str | None:
    """The trailing count run of a playlist row's subtitle, unless it is the song count."""
    try:
        runs = data["flexColumns"][1]["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(runs, list) or len(runs) != offset + 3:  # the library's has_author test
        return None
    text = runs[-1].get("text") if isinstance(runs[-1], dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    # ponytail: English "songs", the same literal ytmusicapi tests for itemCount; with another
    # YTM_LANGUAGE an editorial row's "51 Titel" would come through as the count YouTube shows there.
    words = text.split(" ")
    if len(words) >= 2 and words[1] in ("song", "songs"):
        return None
    return text


def _keep_playlist_item_plays_text() -> None:
    """Keep the "1.7B plays" column on playlist ROWS, which ytmusicapi reads only on album pages.

    An artist's "Top songs" playlist (the `songs.browseId` of get_artist(), `VLOLAK5uy_...`) prints
    each song's combined play count in a plain-text flex column. ytmusicapi 1.12.2's
    `parse_playlist_item` sets `views` only when `is_album` is true, so on a playlist the count is
    lost. This wraps that row parser (which `parse_playlist_items` calls by name from the same module)
    and, when the library left `views` None, sets it to the first single-run, non-clickable column
    whose text ends in " plays". Other playlists have no such column and stay None. Same safety net as
    the two wrappers above: log and skip if the name is gone.
    """
    original = getattr(_ytm_playlist_rows, "parse_playlist_item", None)
    if original is None:
        logger.warning("ytmusicapi has no parse_playlist_item; Top songs playlist rows' plays will be null")
        return
    if getattr(original, "_keeps_views_text", False):
        return

    @functools.wraps(original)
    def with_plays_text(data, *args, **kwargs):
        song = original(data, *args, **kwargs)
        if isinstance(song, dict) and song.get("views") is None:
            song["views"] = _plays_column_text(data)
        return song

    with_plays_text._keeps_views_text = True  # type: ignore[attr-defined]
    _ytm_playlist_rows.parse_playlist_item = with_plays_text


def _plays_column_text(data) -> str | None:
    columns = data.get("flexColumns") if isinstance(data, dict) else None
    for column in columns if isinstance(columns, list) else []:
        try:
            runs = column["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"]
        except (KeyError, TypeError):
            continue
        if not isinstance(runs, list) or len(runs) != 1 or not isinstance(runs[0], dict):
            continue
        text = runs[0].get("text")
        # ponytail: English " plays", like the "songs" literal above; another YTM_LANGUAGE leaves views None.
        if "navigationEndpoint" not in runs[0] and isinstance(text, str) and text.endswith(" plays"):
            return text
    return None


def _keep_artist_playlists_shelf() -> None:
    """Keep an artist page's "Playlists by <artist>" shelf, which ytmusicapi no longer finds.

    ytmusicapi 1.12.2's `Parser.parse_channel_contents` matches each shelf's title exactly against
    the word "playlists"; YouTube now titles it "Playlists by Tame Impala" ("Playlists von ..." in
    German), so get_artist() never has a `playlists` bucket. This wraps that method and, when the
    library found none, adds one from the shelf that works in any language: its title links to a
    full list, and its first card opens a playlist (`VL...`). Albums and singles cards open
    `MPREb_...`, videos a watch page, "Featured on" has no title link, fans-might-also-like opens
    `UC...`. The bucket has the library's own shape ({browseId, params, results}), so
    get_user_playlists(browseId, params) reads the full list. Same safety net as the wrappers above.
    """
    parser = getattr(_ytm_i18n, "Parser", None)
    original = getattr(parser, "parse_channel_contents", None)
    if original is None:
        logger.warning("ytmusicapi has no Parser.parse_channel_contents; artists' own playlists will be missing")
        return
    if getattr(original, "_keeps_views_text", False):
        return

    @functools.wraps(original)
    def with_playlists(self, results, *args, **kwargs):
        artist = original(self, results, *args, **kwargs)
        if isinstance(artist, dict) and "playlists" not in artist:
            try:
                shelf = _playlists_shelf(results)
            except Exception as exc:  # noqa: BLE001 -- one missing row must never fail the artist page
                logger.warning("Could not read an artist's playlists shelf: %r", exc)
                shelf = None
            if shelf:
                artist["playlists"] = shelf
        return artist

    with_playlists._keeps_views_text = True  # type: ignore[attr-defined]
    parser.parse_channel_contents = with_playlists  # type: ignore[union-attr]


def _playlists_shelf(results) -> dict | None:
    for row in results if isinstance(results, list) else []:
        title = nav(row, CAROUSEL + CAROUSEL_TITLE, True)
        if not isinstance(title, dict) or "navigationEndpoint" not in title:
            continue
        carousel = row["musicCarouselShelfRenderer"]
        first = nav(carousel, ["contents", 0, "musicTwoRowItemRenderer", *TITLE, "navigationEndpoint", "browseEndpoint", "browseId"], True)
        if isinstance(first, str) and first.startswith("VL"):
            link = nav(title, NAVIGATION_BROWSE)
            return {
                "browseId": link.get("browseId"),
                "params": link.get("params"),
                "results": parse_content_list(carousel["contents"], parse_playlist),
            }
    return None


_keep_playlist_views_text()
_keep_playlist_row_views_text()
_keep_playlist_item_plays_text()
_keep_artist_playlists_shelf()

# ytmusicapi does not raise a typed "not found" error for an invalid/deleted id on these
# methods -- YouTube serves a differently-shaped page and the library's own parser fails with
# a bare KeyError while looking for the expected path. Each signature is specific enough to
# distinguish "nothing there" from real parser drift. get_song_credits hits it for any song
# without a credits panel (every official-video id), not just invalid ones.
_NOT_FOUND_KEYERRORS = {
    "get_album": "Unable to find 'contents'",
    "get_artist": "Unable to find 'contents'",
    "get_playlist": "Unable to find 'contents'",
    "get_song_credits": "Unable to find 'sections'",
}


class YTMusicClient:
    """Owns one shared YTMusic instance for this worker process.

    Per-request state (headers, proxies, cookies) is passed as call arguments inside
    ytmusicapi rather than mutated on the shared session, so concurrent reads on one
    instance are safe -- except `as_mobile()`, the library's one documented non-thread-safe
    path. We never call it.
    """

    def __init__(self) -> None:
        session = requests.Session()
        session.request = functools.partial(session.request, timeout=settings.timeout_seconds)  # type: ignore[method-assign]

        proxies = {"http": settings.proxy_url, "https": settings.proxy_url} if settings.proxy_url else None

        self._ytmusic = YTMusic(
            auth=settings.auth_file,
            requests_session=session,
            proxies=proxies,
            language=settings.language,
            location=settings.location,
        )
        self._semaphore = threading.Semaphore(settings.max_concurrency)

    @property
    def instance(self) -> YTMusic:
        return self._ytmusic

    def call(self, fn_name: str, *args, **kwargs):
        """Invoke a bound YTMusic method under the concurrency bound."""
        method = getattr(self._ytmusic, fn_name)
        try:
            with self._semaphore:
                return method(*args, **kwargs)
        except KeyError as exc:
            signature = _NOT_FOUND_KEYERRORS.get(fn_name)
            if signature and signature in str(exc):
                raise NotFoundError(f"{fn_name} found no page for the given id") from exc
            raise


_client: YTMusicClient | None = None


def init_client() -> YTMusicClient:
    global _client
    _client = YTMusicClient()
    logger.info("YTMusic client initialized (language=%s, location=%s)", settings.language, settings.location)
    return _client


def get_client() -> YTMusicClient:
    if _client is None:
        raise RuntimeError("YTMusicClient not initialized -- app lifespan did not run")
    return _client
