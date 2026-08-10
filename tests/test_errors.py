import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ytmusicapi.exceptions import (
    YTMusicError,
    YTMusicGatedError,
    YTMusicServerError,
    YTMusicUserError,
)

from app.errors import NotFoundError, register_exception_handlers


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise exc

    return app


class TestErrorMapping:
    def test_not_found_error_maps_to_404(self):
        client = TestClient(_app_raising(NotFoundError("no such album")))
        resp = client.get("/boom")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"

    def test_user_error_maps_to_400(self):
        client = TestClient(_app_raising(YTMusicUserError("invalid filter/scope combination")))
        resp = client.get("/boom")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_request"

    def test_auth_required_user_error_maps_to_500(self):
        client = TestClient(
            _app_raising(YTMusicUserError("Please provide authentication before using this function"))
        )
        resp = client.get("/boom")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "internal_auth_misuse"

    def test_server_error_400_maps_to_502(self):
        client = TestClient(
            _app_raising(
                YTMusicServerError("Server returned HTTP 400: Bad Request.\nRequest contains an invalid argument.")
            )
        )
        resp = client.get("/boom")
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "upstream_error"

    def test_server_error_429_maps_to_429_with_retry_after(self):
        client = TestClient(_app_raising(YTMusicServerError("Server returned HTTP 429: Too Many Requests.\n")))
        resp = client.get("/boom")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_server_error_5xx_maps_to_502(self):
        client = TestClient(
            _app_raising(YTMusicServerError("Server returned HTTP 503: Service Unavailable.\n"))
        )
        resp = client.get("/boom")
        assert resp.status_code == 502

    def test_gated_error_subclass_maps_to_502(self):
        client = TestClient(_app_raising(YTMusicGatedError("Server returned HTTP 401: Unauthorized.\n")))
        resp = client.get("/boom")
        assert resp.status_code == 502

    def test_read_timeout_maps_to_504(self):
        client = TestClient(_app_raising(requests.exceptions.ReadTimeout("timed out")))
        resp = client.get("/boom")
        assert resp.status_code == 504

    def test_connection_error_maps_to_504(self):
        client = TestClient(_app_raising(requests.exceptions.ConnectionError("connection refused")))
        resp = client.get("/boom")
        assert resp.status_code == 504

    def test_generic_ytmusic_error_maps_to_502(self):
        client = TestClient(_app_raising(YTMusicError("unclassified failure")))
        resp = client.get("/boom")
        assert resp.status_code == 502

    def test_key_error_from_parser_drift_maps_to_502(self):
        client = TestClient(_app_raising(KeyError("albums")))
        resp = client.get("/boom")
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "upstream_error"
