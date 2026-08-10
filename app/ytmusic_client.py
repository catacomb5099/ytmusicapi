import functools
import logging
import threading

import requests
from ytmusicapi import YTMusic

from app.config import settings
from app.errors import NotFoundError

logger = logging.getLogger(__name__)

# ytmusicapi does not raise a typed "not found" error for an invalid/deleted browseId on
# these browse-page methods -- YouTube serves a differently-shaped page and the library's
# own parser fails with a bare KeyError while looking for the expected 'contents' path.
# That signature is specific enough to distinguish "page not found" from real parser drift.
_BROWSE_METHODS = {"get_album", "get_artist", "get_playlist"}
_EMPTY_BROWSE_PAGE_KEYERROR = "Unable to find 'contents'"


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
            if fn_name in _BROWSE_METHODS and _EMPTY_BROWSE_PAGE_KEYERROR in str(exc):
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
