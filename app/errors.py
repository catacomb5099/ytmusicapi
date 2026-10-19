"""Exception -> HTTP status mapping, registered as FastAPI exception handlers.

Every response uses the same envelope: {"error": {"code": "<slug>", "message": "<safe text>"}}.
Raw upstream payloads are logged at ERROR, never returned in the body.
"""

from __future__ import annotations

import json
import logging
import re

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ytmusicapi.exceptions import YTMusicError, YTMusicServerError, YTMusicUserError

logger = logging.getLogger(__name__)

_AUTH_REQUIRED_MESSAGE = "Please provide authentication before using this function"
_UPSTREAM_STATUS_RE = re.compile(r"Server returned HTTP (\d+)")


class NotFoundError(Exception):
    """Raised by routers/mappers for missing entities (e.g. an unknown browseId)."""

    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message)


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _extract_upstream_status(message: str) -> int | None:
    match = _UPSTREAM_STATUS_RE.search(message)
    return int(match.group(1)) if match else None


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    def handle_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=_envelope("not_found", str(exc)))

    @app.exception_handler(YTMusicUserError)
    def handle_user_error(_: Request, exc: YTMusicUserError) -> JSONResponse:
        message = str(exc)
        if _AUTH_REQUIRED_MESSAGE in message:
            logger.error("Adapter attempted an auth-requiring ytmusicapi call: %s", message)
            return JSONResponse(
                status_code=500,
                content=_envelope("internal_auth_misuse", "Internal error: attempted an auth-required call"),
            )
        return JSONResponse(status_code=400, content=_envelope("invalid_request", message))

    @app.exception_handler(YTMusicServerError)
    def handle_server_error(_: Request, exc: YTMusicServerError) -> JSONResponse:
        message = str(exc)
        logger.error("YTMusicServerError from upstream: %s", message)
        status = _extract_upstream_status(message)
        if status == 429:
            return JSONResponse(
                status_code=429,
                content=_envelope("rate_limited", "Upstream rate limit exceeded"),
                headers={"Retry-After": "30"},
            )
        # 400/401/403 (bot detection) and any 5xx -> we could not get a valid upstream answer
        return JSONResponse(status_code=502, content=_envelope("upstream_error", "Upstream request failed"))

    @app.exception_handler(requests.exceptions.ReadTimeout)
    def handle_timeout(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Upstream read timeout: %s", exc)
        return JSONResponse(status_code=504, content=_envelope("upstream_timeout", "Upstream request timed out"))

    # DNS failure, connection refused, TLS, proxy, connect timeout: YouTube was never reached. Until
    # 19-10-2026 this shared the 504 above and read "timed out" in every log, which sent a
    # self-hoster looking for a slow YouTube when their container had no DNS. The class name is the
    # one safe, useful word (NameResolutionError, ProxyError, SSLError); the text may hold a URL.
    # requests chains urllib3's MaxRetryError, whose `reason` is the error that matters.
    @app.exception_handler(requests.exceptions.ConnectionError)
    def handle_unreachable(_: Request, exc: Exception) -> JSONResponse:
        cause = exc.__cause__ or exc.__context__
        cause = getattr(cause, "reason", None) or cause
        kind = type(cause).__name__ if cause is not None else type(exc).__name__
        logger.error("Could not reach YouTube Music (%s): %s", kind, exc)
        return JSONResponse(
            status_code=502,
            content=_envelope("upstream_unreachable", f"Could not reach YouTube Music ({kind})"),
        )

    # ytmusicapi decodes the body before it looks at the status, so a non-JSON answer (an HTML
    # "sorry" page, an empty body after a stall) surfaced as FastAPI's plain-text 500 until 19-10-2026.
    @app.exception_handler(json.JSONDecodeError)
    def handle_unreadable_answer(_: Request, exc: json.JSONDecodeError) -> JSONResponse:
        logger.error("Upstream answer was not JSON: %s", exc)
        return JSONResponse(
            status_code=502,
            content=_envelope("upstream_error", "YouTube Music sent an unreadable answer"),
        )

    @app.exception_handler(YTMusicError)
    def handle_generic_ytmusic_error(_: Request, exc: YTMusicError) -> JSONResponse:
        logger.error("Unclassified YTMusicError: %s", exc)
        return JSONResponse(status_code=502, content=_envelope("upstream_error", "Upstream request failed"))

    @app.exception_handler(KeyError)
    @app.exception_handler(IndexError)
    @app.exception_handler(TypeError)
    def handle_parser_drift(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Parser drift while mapping upstream response: %r", exc)
        return JSONResponse(status_code=502, content=_envelope("upstream_error", "Upstream response was unrecognized"))
