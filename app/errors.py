"""Exception -> HTTP status mapping, registered as FastAPI exception handlers.

Every response uses the same envelope: {"error": {"code": "<slug>", "message": "<safe text>"}}.
Raw upstream payloads are logged at ERROR, never returned in the body.
"""

from __future__ import annotations

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
    @app.exception_handler(requests.exceptions.ConnectionError)
    def handle_timeout(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Upstream timeout/connection error: %s", exc)
        return JSONResponse(status_code=504, content=_envelope("upstream_timeout", "Upstream request timed out"))

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
