"""Opt-in tests that hit the real YouTube Music backend.

Excluded from the default run (see `addopts` in pyproject.toml). Run explicitly with:
    pytest -m live

A failure here means "YouTube changed the response shape, or this IP got flagged" --
not "the code is wrong". When one fails: re-record the fixture with the script used to
seed tests/fixtures/ (see the plan's execution-order step 2) and update the mapper.
Run from an environment resembling production so IP-based blocking is caught early.
"""

import pytest
from ytmusicapi import YTMusic

from app.mappers import (
    map_album_detail,
    map_artist_detail,
    map_playlist_detail,
    map_search_item,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def yt() -> YTMusic:
    return YTMusic()


class TestSearchContract:
    def test_mixed_search_contains_expected_id_fields_per_type(self, yt):
        results = yt.search("Oasis Wonderwall", limit=20)
        by_type = {}
        for item in results:
            by_type.setdefault(item.get("resultType"), item)

        assert "song" in by_type, "expected at least one song result"
        assert by_type["song"].get("videoId")

        if "album" in by_type:
            assert by_type["album"].get("browseId", "").startswith("MPREb_")
            assert by_type["album"].get("playlistId", "").startswith("OLAK5uy_")

        if "artist" in by_type:
            assert by_type["artist"].get("browseId")

        if "playlist" in by_type:
            assert by_type["playlist"].get("browseId", "").startswith("VL")

        # every item must survive the mapper without raising
        for item in results:
            map_search_item(item)

    def test_album_filtered_search_feeds_get_album(self, yt):
        results = yt.search("Oasis Definitely Maybe", filter="albums", limit=5)
        assert results, "expected at least one album result"
        browse_id = results[0]["browseId"]

        album = yt.get_album(browse_id)
        assert album.get("audioPlaylistId")
        assert album.get("tracks")
        assert album["tracks"][0].get("videoId")
        assert album.get("duration_seconds") is not None

        # keys behind description / explicit / recommendations / per-track play counts --
        # all label-supplied, so a rename or removal upstream is real drift, not a bug here
        assert "description" in album
        assert "isExplicit" in album
        assert "other_versions" in album
        assert "related_recommendations" in album
        assert "views" in album["tracks"][0]

        detail = map_album_detail(album, requested_browse_id=browse_id)
        assert detail.tracks
        assert detail.audioPlaylistId == album["audioPlaylistId"]
        assert detail.description
        assert detail.relatedRecommendations
        assert detail.relatedRecommendations[0].browseId

    def test_audio_playlist_id_round_trips_to_album_browse_id(self, yt):
        results = yt.search("Oasis Definitely Maybe", filter="albums", limit=5)
        audio_playlist_id = results[0]["playlistId"]

        resolved = yt.get_album_browse_id(audio_playlist_id)
        assert resolved is not None
        assert resolved.startswith("MPREb_")

    def test_artist_filtered_search_feeds_get_artist_and_get_artist_albums(self, yt):
        results = yt.search("Oasis", filter="artists", limit=5)
        assert results, "expected at least one artist result"
        channel_id = results[0]["browseId"]

        artist = yt.get_artist(channel_id)
        assert artist.get("songs") or artist.get("albums")
        assert "monthlyListeners" in artist
        assert "views" in artist

        detail = map_artist_detail(artist, requested_channel_id=channel_id)
        assert detail.channelId == channel_id
        assert detail.monthlyListeners
        assert detail.views

        albums_bucket = artist.get("albums")
        if albums_bucket and albums_bucket.get("params"):
            artist_albums = yt.get_artist_albums(albums_bucket["browseId"], albums_bucket["params"])
            assert isinstance(artist_albums, list)

    def test_community_playlist_search_feeds_get_playlist(self, yt):
        results = yt.search("indie rock hits", filter="community_playlists", limit=5)
        assert results, "expected at least one playlist result"
        browse_id = results[0]["browseId"]
        assert browse_id.startswith("VL")
        bare_id = browse_id[2:]

        playlist = yt.get_playlist(bare_id, limit=25)
        assert playlist.get("tracks")
        assert playlist["tracks"][0].get("videoId")
        assert playlist.get("trackCount") is not None

        detail = map_playlist_detail(playlist)
        assert detail.tracks

    def test_song_metadata_mapper_never_leaks_streaming_data(self, yt):
        results = yt.search("Oasis Wonderwall", filter="songs", limit=1)
        video_id = results[0]["videoId"]

        song = yt.get_song(video_id)
        assert "streamingData" in song  # sanity: the live response does carry it

        from app.mappers import map_song_metadata

        metadata = map_song_metadata(song)
        assert "streamingData" not in metadata.model_dump()
        assert metadata.videoId == video_id
