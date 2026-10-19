import functools
import logging
import threading

import requests
import ytmusicapi.mixins.playlists as _ytm_playlists
from ytmusicapi import YTMusic

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
    if hasattr(original, "__wrapped__"):
        return  # already wrapped

    @functools.wraps(original)
    def with_views_text(header):
        meta = original(header)
        subtitle = header.get("secondSubtitle") if isinstance(header, dict) else None
        runs = subtitle.get("runs") if isinstance(subtitle, dict) else None
        first = runs[0] if isinstance(runs, list) and len(runs) > 3 else None
        text = first.get("text") if isinstance(first, dict) else None
        meta["viewsText"] = text if isinstance(text, str) else None
        return meta

    _ytm_playlists.parse_playlist_header_meta = with_views_text


_keep_playlist_views_text()

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
