import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ytmusicapi.exceptions import YTMusicServerError

from app.deps import get_ytmusic
from app.errors import NotFoundError
from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


class FakeYTMusicClient:
    """Stands in for YTMusicClient.call(method_name, *args, **kwargs) in route tests."""

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.calls: list[tuple] = []

    def call(self, fn_name: str, *args, **kwargs):
        self.calls.append((fn_name, args, kwargs))
        value = self._responses.get(fn_name)
        if callable(value):
            return value(*args, **kwargs)
        return value


@pytest.fixture
def client_with(monkeypatch):
    """Yields a function that installs a FakeYTMusicClient and returns a TestClient."""

    def _install(**responses):
        fake = FakeYTMusicClient(responses)
        app.dependency_overrides[get_ytmusic] = lambda: fake
        return TestClient(app), fake

    yield _install
    app.dependency_overrides.pop(get_ytmusic, None)


class TestSearchRoutes:
    def test_mixed_search_returns_items(self, client_with):
        client, fake = client_with(search=lambda *a, **k: _load("search_mixed"))
        resp = client.get("/v1/search", params={"q": "Oasis Wonderwall"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "Oasis Wonderwall"
        assert body["count"] == len(body["items"])
        assert fake.calls[0][0] == "search"

    def test_type_maps_to_filter(self, client_with):
        client, fake = client_with(search=lambda *a, **k: _load("search_playlists"))
        resp = client.get("/v1/search", params={"q": "indie", "type": "playlists"})
        assert resp.status_code == 200
        _, _args, kwargs = fake.calls[0]
        assert kwargs["filter"] == "community_playlists"

    def test_unknown_type_returns_400(self, client_with):
        client, _ = client_with(search=lambda *a, **k: [])
        resp = client.get("/v1/search", params={"q": "x", "type": "bogus"})
        assert resp.status_code == 400

    def test_limit_truncates_result_count(self, client_with):
        client, _ = client_with(search=lambda *a, **k: _load("search_mixed"))
        resp = client.get("/v1/search", params={"q": "Oasis", "limit": 2})
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_typed_sugar_route_presets_filter(self, client_with):
        client, fake = client_with(search=lambda *a, **k: _load("search_albums"))
        resp = client.get("/v1/search/albums", params={"q": "Definitely Maybe"})
        assert resp.status_code == 200
        _, _args, kwargs = fake.calls[0]
        assert kwargs["filter"] == "albums"

    def test_featured_playlists_type_and_sugar_route_share_filter(self, client_with):
        client, fake = client_with(search=lambda *a, **k: _load("search_featured_playlists"))
        for url, params in (
            ("/v1/search", {"q": "Oasis", "type": "featured_playlists"}),
            ("/v1/search/featured_playlists", {"q": "Oasis"}),
        ):
            resp = client.get(url, params=params)
            assert resp.status_code == 200
            assert fake.calls[-1][2]["filter"] == "featured_playlists"
            body = resp.json()
            assert body["type"] == "featured_playlists"
            assert body["items"][0]["playlistId"].startswith("RDCLAK5uy_")


class TestAlbumRoutes:
    def test_get_album_by_browse_id(self, client_with):
        raw = _load("album_detail")
        client, _ = client_with(get_album=lambda browse_id: raw)
        resp = client.get("/v1/albums/MPREb_TEST")
        assert resp.status_code == 200
        body = resp.json()
        assert body["browseId"] == "MPREb_TEST"
        assert body["title"] == raw["title"]

    def test_get_album_not_found(self, client_with):
        client, _ = client_with(get_album=lambda browse_id: None)
        resp = client.get("/v1/albums/MPREb_MISSING")
        assert resp.status_code == 404

    def test_audio_playlist_bridge_resolves_then_fetches(self, client_with):
        raw = _load("album_detail")
        client, fake = client_with(
            get_album_browse_id=lambda audio_playlist_id: "MPREb_RESOLVED",
            get_album=lambda browse_id: raw,
        )
        resp = client.get("/v1/albums/by-audio-playlist/OLAK5uy_SOMETHING")
        assert resp.status_code == 200
        assert resp.json()["browseId"] == "MPREb_RESOLVED"
        assert fake.calls[0] == ("get_album_browse_id", ("OLAK5uy_SOMETHING",), {})
        assert fake.calls[1] == ("get_album", ("MPREb_RESOLVED",), {})

    def test_audio_playlist_bridge_not_found_when_unresolvable(self, client_with):
        client, _ = client_with(get_album_browse_id=lambda audio_playlist_id: None)
        resp = client.get("/v1/albums/by-audio-playlist/OLAK5uy_UNKNOWN")
        assert resp.status_code == 404


class TestArtistRoutes:
    def test_get_artist_echoes_requested_channel_id(self, client_with):
        raw = _load("artist_detail")
        client, _ = client_with(get_artist=lambda channel_id: raw)
        resp = client.get("/v1/artists/UCEXAMPLE")
        assert resp.status_code == 200
        body = resp.json()
        assert body["channelId"] == "UCEXAMPLE"
        assert body["channelId"] != raw["channelId"]

    def test_get_artist_not_found(self, client_with):
        client, _ = client_with(get_artist=lambda channel_id: None)
        resp = client.get("/v1/artists/UCMISSING")
        assert resp.status_code == 404

    def test_get_artist_albums_two_call_bridge(self, client_with):
        artist_raw = _load("artist_detail")
        albums_raw = _load("artist_albums")
        client, fake = client_with(
            get_artist=lambda channel_id: artist_raw,
            get_artist_albums=lambda browse_id, params, **kw: albums_raw,
        )
        resp = client.get("/v1/artists/UCEXAMPLE/albums")
        assert resp.status_code == 200
        assert len(resp.json()) == len(albums_raw)
        assert fake.calls[0][0] == "get_artist"
        assert fake.calls[1][0] == "get_artist_albums"

    def test_get_artist_albums_empty_when_no_albums_bucket(self, client_with):
        artist_raw = _load("artist_detail_no_albums")
        client, fake = client_with(get_artist=lambda channel_id: artist_raw)
        resp = client.get("/v1/artists/UCEXAMPLE/albums")
        assert resp.status_code == 200
        assert resp.json() == []
        assert len(fake.calls) == 1  # never calls get_artist_albums without params


class TestPlaylistRoutes:
    def test_get_playlist_strips_vl_prefix(self, client_with):
        raw = _load("playlist_detail")
        client, fake = client_with(get_playlist=lambda bare_id, limit: raw)
        resp = client.get("/v1/playlists/VLPLEXAMPLE123")
        assert resp.status_code == 200
        assert fake.calls[0][1][0] == "PLEXAMPLE123"

    def test_get_playlist_accepts_bare_id(self, client_with):
        raw = _load("playlist_detail")
        client, fake = client_with(get_playlist=lambda bare_id, limit: raw)
        resp = client.get("/v1/playlists/PLEXAMPLE123")
        assert resp.status_code == 200
        assert fake.calls[0][1][0] == "PLEXAMPLE123"

    def test_get_playlist_not_found(self, client_with):
        client, _ = client_with(get_playlist=lambda bare_id, limit: None)
        resp = client.get("/v1/playlists/PLMISSING")
        assert resp.status_code == 404


class TestSongRoutes:
    def test_get_song_never_exposes_streaming_data(self, client_with):
        raw = _load("song_detail")
        client, _ = client_with(get_song=lambda video_id: raw)
        resp = client.get("/v1/songs/VIDEOID")
        assert resp.status_code == 200
        assert "streamingData" not in resp.json()
        assert "playabilityStatus" not in resp.json()

    def test_get_song_not_found(self, client_with):
        client, _ = client_with(get_song=lambda video_id: {})
        resp = client.get("/v1/songs/MISSING")
        assert resp.status_code == 404


def _raise(exc):
    def _inner(*args, **kwargs):
        raise exc

    return _inner


class TestSongDetailsRoute:
    def test_full_sequence_for_an_album_track(self, client_with):
        client, fake = client_with(
            get_song=lambda video_id: _load("song_details_song"),
            get_watch_playlist=lambda **kw: _load("song_details_watch"),
            get_album=lambda browse_id: _load("song_details_album"),
            get_song_credits=lambda browse_id: _load("song_details_credits"),
        )
        resp = client.get("/v1/songs/DntZ3-yCaFs/details")
        assert resp.status_code == 200
        body = resp.json()
        assert body["explicit"] is True
        assert body["album"]["browseId"] == "MPREb_msfRVJDqlXJ"
        assert len(body["credits"]) == 4
        assert "streamingData" not in body
        assert [c[0] for c in fake.calls] == [
            "get_song",
            "get_watch_playlist",
            "get_album",
            "get_song_credits",
        ]
        assert fake.calls[2][1] == ("MPREb_msfRVJDqlXJ",)
        assert fake.calls[3][1] == ("MPTCDntZ3-yCaFs",)

    def test_official_video_skips_album_and_reports_empty_credits(self, client_with):
        client, fake = client_with(
            get_song=lambda video_id: _load("song_details_song"),
            get_watch_playlist=lambda **kw: _load("song_details_watch_omv"),
            get_song_credits=_raise(NotFoundError("no credits panel")),
        )
        resp = client.get("/v1/songs/tM1RS_5IAiE/details")
        assert resp.status_code == 200
        body = resp.json()
        assert body["album"] is None and body["explicit"] is None and body["credits"] == []
        # Two calls, not four: no album to look up, and an OMV never has a credits panel.
        assert [c[0] for c in fake.calls] == ["get_song", "get_watch_playlist"]

    def test_watch_panel_failure_degrades_instead_of_502(self, client_with):
        client, _ = client_with(
            get_song=lambda video_id: _load("song_details_song"),
            get_watch_playlist=_raise(YTMusicServerError("No content returned by the server")),
            get_song_credits=_raise(YTMusicServerError("Server returned HTTP 500")),
        )
        resp = client.get("/v1/songs/DntZ3-yCaFs/details")
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Manchild"
        assert body["artists"] == [{"name": "Sabrina Carpenter", "channelId": "UCz51ZodJbYUNfkdPHOjJKKw"}]
        assert body["credits"] == []

    def test_album_5xx_degrades_like_the_other_calls(self, client_with):
        client, fake = client_with(
            get_song=lambda video_id: _load("song_details_song"),
            get_watch_playlist=lambda **kw: _load("song_details_watch"),
            get_album=_raise(YTMusicServerError("Server returned HTTP 503")),
            get_song_credits=lambda browse_id: _load("song_details_credits"),
        )
        resp = client.get("/v1/songs/DntZ3-yCaFs/details")
        assert resp.status_code == 200
        body = resp.json()
        assert body["explicit"] is None and body["year"] == 2025  # year still comes from the watch track
        assert len(body["credits"]) == 4
        assert fake.calls[3][1] == ("MPTCDntZ3-yCaFs",)  # falls back to MPTC + videoId

    def test_unknown_video_is_404_before_any_other_call(self, client_with):
        client, fake = client_with(get_song=lambda video_id: {"playabilityStatus": {"status": "ERROR"}})
        resp = client.get("/v1/songs/MISSING/details")
        assert resp.status_code == 404
        assert len(fake.calls) == 1
