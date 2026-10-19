import functools
import logging
from unittest.mock import MagicMock

import pytest
from ytmusicapi.mixins import playlists as ytm_playlists

from app.errors import NotFoundError
from app.ytmusic_client import YTMusicClient, _keep_playlist_views_text


def _client_with_mocked_instance(instance: MagicMock) -> YTMusicClient:
    client = YTMusicClient.__new__(YTMusicClient)
    client._ytmusic = instance
    import threading

    client._semaphore = threading.Semaphore(8)
    return client


class TestBrowsePageNotFoundTranslation:
    @pytest.mark.parametrize(
        ("method_name", "missing_key"),
        [
            ("get_album", "contents"),
            ("get_artist", "contents"),
            ("get_playlist", "contents"),
            ("get_song_credits", "sections"),
        ],
    )
    def test_empty_browse_page_keyerror_becomes_not_found(self, method_name, missing_key):
        instance = MagicMock()
        getattr(instance, method_name).side_effect = KeyError(
            f"Unable to find '{missing_key}' using path [...] on {{...}}"
        )
        client = _client_with_mocked_instance(instance)

        with pytest.raises(NotFoundError):
            client.call(method_name, "some-id")

    def test_unrelated_keyerror_on_browse_method_still_propagates(self):
        instance = MagicMock()
        instance.get_album.side_effect = KeyError("Unable to find 'sections'")
        client = _client_with_mocked_instance(instance)

        with pytest.raises(KeyError):
            client.call("get_album", "some-id")

    def test_keyerror_on_non_browse_method_propagates_unchanged(self):
        instance = MagicMock()
        instance.get_song.side_effect = KeyError("Unable to find 'contents' using path [...]")
        client = _client_with_mocked_instance(instance)

        with pytest.raises(KeyError):
            client.call("get_song", "some-id")


class TestPlaylistViewsText:
    """Importing app.ytmusic_client wraps ytmusicapi's playlist header parser so YouTube's display
    string ("6.9M views") survives beside the library's lossy int (69)."""

    @staticmethod
    def _header(*runs: str) -> dict:
        # The three keys parse_playlist_header_meta reads; the runs are what YouTube Music shows.
        return {
            "title": {"runs": [{"text": "100 Best Britpop Songs"}]},
            "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": []}}},
            "secondSubtitle": {"runs": [{"text": r} for r in runs]},
        }

    def test_user_playlist_keeps_youtubes_wording_beside_the_lossy_int(self):
        meta = ytm_playlists.parse_playlist_header_meta(
            self._header("6.9M views", " • ", "100 tracks", " • ", "6+ hours")
        )
        assert meta["viewsText"] == "6.9M views"
        assert meta["views"] == 69  # to_int("6.9M views"): the reason viewsText exists
        assert meta["trackCount"] == 100  # the original parser's work is untouched

    def test_editorial_playlist_header_has_no_count(self):
        meta = ytm_playlists.parse_playlist_header_meta(
            self._header("51 songs", " • ", "4 hours, 5 minutes")
        )
        assert meta["viewsText"] is None
        assert meta["views"] is None

    def test_header_without_runs_gives_none_not_an_error(self):
        header = self._header()
        header["secondSubtitle"] = {}
        assert ytm_playlists.parse_playlist_header_meta(header)["viewsText"] is None

    def test_wrapping_twice_wraps_once(self):
        _keep_playlist_views_text()
        assert not hasattr(ytm_playlists.parse_playlist_header_meta.__wrapped__, "__wrapped__")

    def test_wraps_a_library_parser_that_is_itself_decorated(self, monkeypatch):
        # a future ytmusicapi may decorate the parser (functools.wraps sets __wrapped__): still ours to wrap
        inner = ytm_playlists.parse_playlist_header_meta.__wrapped__
        library = functools.wraps(inner)(lambda header: inner(header))
        monkeypatch.setattr(ytm_playlists, "parse_playlist_header_meta", library)
        _keep_playlist_views_text()
        header = self._header("6.9M views", " • ", "100 tracks", " • ", "6+ hours")
        assert ytm_playlists.parse_playlist_header_meta(header)["viewsText"] == "6.9M views"

    def test_missing_library_internal_logs_and_skips_instead_of_failing_startup(self, monkeypatch, caplog):
        monkeypatch.delattr(ytm_playlists, "parse_playlist_header_meta")
        with caplog.at_level(logging.WARNING):
            _keep_playlist_views_text()
        assert "playlist views will be null" in caplog.text
