import functools
import logging
from unittest.mock import MagicMock

import pytest
from ytmusicapi.mixins import playlists as ytm_playlists
from ytmusicapi.parsers import i18n as ytm_i18n
from ytmusicapi.parsers import playlists as ytm_playlist_rows
from ytmusicapi.parsers import search as ytm_search

from app.errors import NotFoundError
from app.ytmusic_client import (
    YTMusicClient,
    _keep_artist_playlists_shelf,
    _keep_playlist_item_plays_text,
    _keep_playlist_row_views_text,
    _keep_playlist_views_text,
)


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


class TestPlaylistRowViewsText:
    """Importing app.ytmusic_client also wraps ytmusicapi's search ROW parser so a playlist row's
    "375K views" survives (the library keeps only the "N songs" form, as itemCount)."""

    @staticmethod
    def _filtered(raw: dict) -> dict:
        # The same row as a community_playlists search sends it: "author • count", no "Playlist" run.
        runs = raw["flexColumns"][1]["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"][2:]
        column = {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": runs}}}
        return {**raw, "flexColumns": [raw["flexColumns"][0], column]}

    @staticmethod
    def _with_last_run(raw: dict, text: str) -> dict:
        import copy

        row = copy.deepcopy(raw)
        row["flexColumns"][1]["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"][-1] = {"text": text}
        return row

    def test_mixed_row_keeps_youtubes_wording(self, load_fixture):
        raw = load_fixture("search_raw_row_playlist_mixed")  # "Playlist • Cristian Torres • 3.1M views"
        row = ytm_search.parse_search_result(raw, None, None)
        assert row["viewsText"] == "3.1M views"
        assert (row["resultType"], row["author"], row["itemCount"]) == ("playlist", "Cristian Torres", None)

    def test_filtered_row_keeps_youtubes_wording(self, load_fixture):
        raw = self._filtered(load_fixture("search_raw_row_playlist_mixed"))  # "Cristian Torres • 3.1M views"
        row = ytm_search.parse_search_result(raw, "playlist", "Community playlists")
        assert row["viewsText"] == "3.1M views"
        assert row["author"] == "Cristian Torres"

    def test_song_count_row_is_not_a_view_count(self, load_fixture):
        raw = load_fixture("search_raw_row_playlist_mixed")
        # YouTube Music's own playlists show "51 songs" in that slot; the library's itemCount owns it
        assert ytm_search.parse_search_result(self._with_last_run(raw, "51 songs"), None, None)["viewsText"] is None
        filtered = self._filtered(self._with_last_run(raw, "214 songs"))
        row = ytm_search.parse_search_result(filtered, "playlist", "Community playlists")
        assert (row["viewsText"], row["itemCount"]) == (None, 214)
        assert ytm_search.parse_search_result(self._with_last_run(raw, "1 song"), None, None)["viewsText"] is None

    def test_row_without_the_count_run_gives_none_not_an_error(self, load_fixture):
        raw = load_fixture("search_raw_row_playlist_mixed")
        runs = raw["flexColumns"][1]["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"]
        short = {**raw, "flexColumns": [raw["flexColumns"][0], {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": runs[:3]}}}]}
        # "Playlist • author" on a mixed row: the library's has_author test fails, so nothing is read
        assert ytm_search.parse_search_result(short, None, None)["viewsText"] is None
        assert ytm_search.parse_search_result(self._with_last_run(raw, "  "), None, None)["viewsText"] is None

    def test_non_playlist_rows_are_left_alone(self, load_fixture):
        raw = load_fixture("search_raw_row_playlist_mixed")
        album = {**raw, "navigationEndpoint": {"browseEndpoint": {"browseId": "MPREb_Hl8XJR59OrY"}}}
        assert "viewsText" not in ytm_search.parse_search_result(album, None, None)

    def test_wrapping_twice_wraps_once(self):
        _keep_playlist_row_views_text()
        assert not hasattr(ytm_search.parse_search_result.__wrapped__, "__wrapped__")

    def test_missing_library_internal_logs_and_skips_instead_of_failing_startup(self, monkeypatch, caplog):
        monkeypatch.delattr(ytm_search, "parse_search_result")
        with caplog.at_level(logging.WARNING):
            _keep_playlist_row_views_text()
        assert "playlist search rows' views will be null" in caplog.text


class TestPlaylistItemPlaysText:
    """Importing app.ytmusic_client also wraps ytmusicapi's playlist ROW parser so an artist's "Top songs"
    playlist keeps each song's "1.7B plays" (the library reads that column only on album pages)."""

    @staticmethod
    def _without_plays(raw: dict) -> dict:
        import copy

        row = copy.deepcopy(raw)
        del row["flexColumns"][2]
        return row

    def test_top_songs_row_keeps_its_play_count(self, load_fixture):
        raw = load_fixture("playlist_raw_row_top_songs")  # Oasis "Top songs", row 1, recorded 20-10-2026
        (song,) = ytm_playlist_rows.parse_playlist_items([{"musicResponsiveListItemRenderer": raw}])
        assert (song["title"], song["views"]) == ("Wonderwall", "1.7B plays")
        assert song["album"]["name"] == "(What's The Story) Morning Glory?"  # the library's own work is untouched

    def test_row_without_a_plays_column_stays_none(self, load_fixture):
        raw = self._without_plays(load_fixture("playlist_raw_row_top_songs"))
        assert ytm_playlist_rows.parse_playlist_item(raw)["views"] is None

    def test_wrapping_twice_wraps_once(self):
        _keep_playlist_item_plays_text()
        assert not hasattr(ytm_playlist_rows.parse_playlist_item.__wrapped__, "__wrapped__")

    def test_missing_library_internal_logs_and_skips_instead_of_failing_startup(self, monkeypatch, caplog):
        monkeypatch.delattr(ytm_playlist_rows, "parse_playlist_item")
        with caplog.at_level(logging.WARNING):
            _keep_playlist_item_plays_text()
        assert "Top songs playlist rows' plays will be null" in caplog.text


class TestArtistPlaylistsShelf:
    """Importing app.ytmusic_client also wraps ytmusicapi's artist-page shelf parser so the "Playlists by
    <artist>" shelf survives (the library looks for a shelf titled exactly "playlists")."""

    @staticmethod
    def _parse(results):
        import gettext

        return ytm_i18n.Parser(gettext.NullTranslations()).parse_channel_contents(results)

    @staticmethod
    def _retitled(shelves, text):
        import copy

        shelves = copy.deepcopy(shelves)
        shelves[-1]["musicCarouselShelfRenderer"]["header"]["musicCarouselShelfBasicHeaderRenderer"]["title"]["runs"][0]["text"] = text
        return shelves

    def test_playlists_by_shelf_becomes_the_playlists_bucket(self, load_fixture):
        shelves = load_fixture("artist_raw_shelves")  # Tame Impala, 20-10-2026: Singles, Videos, Featured on, Playlists by
        artist = self._parse(shelves)
        bucket = artist["playlists"]
        assert (bucket["browseId"], bucket["params"][:6]) == ("UCGz-eguN8tcic5kUG4s1ZgA", "6gPgAU")
        assert bucket["results"][0]["playlistId"] == "PLr9Yx3twkzdK2GF5xVgpsM8PvREBdzf5c"
        assert set(artist) == {"singles", "videos", "playlists"}  # "Featured on" (no title link) is not it

    def test_any_language_title_is_found(self, load_fixture):
        shelves = self._retitled(load_fixture("artist_raw_shelves"), "Playlists von „Tame Impala“")
        assert self._parse(shelves)["playlists"]["results"][0]["title"] == "THE SLOW RUSH"

    def test_a_bucket_the_library_found_itself_is_left_alone(self, load_fixture):
        shelves = self._retitled(load_fixture("artist_raw_shelves"), "Playlists")
        assert len(self._parse(shelves)["playlists"]["results"]) == 3  # parsed once, by the library

    def test_page_without_the_shelf_has_no_bucket(self, load_fixture):
        assert "playlists" not in self._parse(load_fixture("artist_raw_shelves")[:3])

    def test_wrapping_twice_wraps_once(self):
        _keep_artist_playlists_shelf()
        assert not hasattr(ytm_i18n.Parser.parse_channel_contents.__wrapped__.__wrapped__, "__wrapped__")

    def test_missing_library_internal_logs_and_skips_instead_of_failing_startup(self, monkeypatch, caplog):
        monkeypatch.delattr(ytm_i18n.Parser, "parse_channel_contents")
        with caplog.at_level(logging.WARNING):
            _keep_artist_playlists_shelf()
        assert "artists' own playlists will be missing" in caplog.text
