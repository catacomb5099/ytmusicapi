from app.mappers import (
    map_album_detail,
    map_artist_detail,
    map_playlist_detail,
    map_search_item,
    map_search_items,
    map_song_metadata,
)


class TestSearchItemMapping:
    def test_song_item_carries_video_id(self, load_fixture):
        raw = next(i for i in load_fixture("search_mixed") if i["resultType"] == "song")
        item = map_search_item(raw)
        assert item.type == "song"
        assert item.videoId == raw["videoId"]
        assert item.browseId is None
        assert item.artists[0].channelId == raw["artists"][0]["id"]

    def test_album_item_carries_browse_id_and_audio_playlist_id(self, load_fixture):
        raw = next(i for i in load_fixture("search_mixed") if i["resultType"] == "album")
        item = map_search_item(raw)
        assert item.browseId == raw["browseId"]
        assert item.browseId.startswith("MPREb_")
        assert item.playlistId == raw["playlistId"]
        assert item.playlistId.startswith("OLAK5uy_")
        assert item.year == int(raw["year"])

    def test_artist_item_uses_artist_key_as_title(self, load_fixture):
        raw = next(i for i in load_fixture("search_mixed") if i["resultType"] == "artist")
        item = map_search_item(raw)
        assert item.title == raw["artist"]
        assert item.browseId == raw["browseId"]

    def test_playlist_item_strips_vl_prefix(self, load_fixture):
        raw = next(i for i in load_fixture("search_mixed") if i["resultType"] == "playlist")
        item = map_search_item(raw)
        assert raw["browseId"].startswith("VL")
        assert item.browseId == raw["browseId"]
        assert item.playlistId == raw["browseId"][2:]

    def test_top_result_artist_card_falls_back_to_artists_array(self, load_fixture):
        """A bare-name query's "Top result" artist card omits browseId/artist entirely --
        identity lives only in artists[0]."""
        raw = load_fixture("search_item_top_result_artist")
        assert "browseId" not in raw
        assert "artist" not in raw
        item = map_search_item(raw)
        assert item.browseId == raw["artists"][0]["id"]
        assert item.title == raw["artists"][0]["name"]

    def test_unknown_result_type_does_not_raise(self, load_fixture):
        raw = load_fixture("search_item_unknown_type")
        item = map_search_item(raw)
        assert item.type == raw["resultType"]
        assert item.title == raw.get("title")

    def test_mangled_song_item_degrades_gracefully(self, load_fixture):
        raw = load_fixture("search_item_mangled_song")
        item = map_search_item(raw)
        assert item.artists == []
        assert item.thumbnailUrl is None

    def test_mangled_album_item_missing_year_and_artists(self, load_fixture):
        raw = load_fixture("search_item_mangled_album")
        assert "year" not in raw
        item = map_search_item(raw)
        assert item.artists == []
        assert item.browseId is not None
        assert item.year is None

    def test_mangled_playlist_item_missing_author_does_not_raise(self, load_fixture):
        raw = load_fixture("search_item_mangled_playlist")
        item = map_search_item(raw)
        assert item.type == "playlist"

    def test_limit_truncates_results(self, load_fixture):
        raw = load_fixture("search_mixed")
        assert len(raw) > 3
        items = map_search_items(raw, limit=3)
        assert len(items) == 3


class TestAlbumDetailMapping:
    def test_maps_core_fields_and_tracks(self, load_fixture):
        raw = load_fixture("album_detail")
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert detail.browseId == "MPREb_TEST"
        assert detail.title == raw["title"]
        assert detail.audioPlaylistId == raw["audioPlaylistId"]
        assert len(detail.tracks) == len(raw["tracks"])
        first_track = detail.tracks[0]
        assert first_track.videoId == raw["tracks"][0]["videoId"]
        # album track's `album` field is a bare string, not {name, id}
        assert first_track.albumName == raw["tracks"][0]["album"]

    def test_mangled_album_missing_audio_playlist_id_and_track_fields(self, load_fixture):
        raw = load_fixture("album_detail_mangled")
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert detail.audioPlaylistId is None
        assert detail.year is None
        track = detail.tracks[0]
        assert track.durationSeconds is None
        assert track.trackNumber is None


class TestArtistDetailMapping:
    def test_echoes_requested_channel_id_not_upstream_one(self, load_fixture):
        raw = load_fixture("artist_detail")
        requested = raw["requestedChannelId"]
        assert raw["channelId"] != requested  # the library's documented gotcha
        detail = map_artist_detail(raw, requested_channel_id=requested)
        assert detail.channelId == requested

    def test_maps_buckets(self, load_fixture):
        raw = load_fixture("artist_detail")
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        assert detail.name == raw["name"]
        assert len(detail.albums) == len(raw["albums"]["results"])
        assert len(detail.topSongs) == len(raw["songs"]["results"])

    def test_artist_with_no_albums_bucket_returns_empty_list(self, load_fixture):
        raw = load_fixture("artist_detail_no_albums")
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        assert detail.albums == []
        assert detail.singles == []


class TestPlaylistDetailMapping:
    def test_maps_core_fields_and_tracks(self, load_fixture):
        raw = load_fixture("playlist_detail")
        detail = map_playlist_detail(raw)
        assert detail.id == raw["id"]
        assert detail.author.name == raw["author"]["name"]
        assert len(detail.tracks) == len(raw["tracks"])
        # playlist track's `album` field is {name, id}, not a bare string
        first_track_album = raw["tracks"][0]["album"]
        assert detail.tracks[0].albumName == first_track_album["name"]

    def test_mangled_playlist_missing_author_and_degraded_track(self, load_fixture):
        raw = load_fixture("playlist_detail_mangled")
        detail = map_playlist_detail(raw)
        assert detail.author is None
        track = detail.tracks[0]
        assert track.albumName is None
        assert track.artists == []


class TestSongMetadataMapping:
    def test_never_exposes_streaming_data(self, load_fixture):
        raw = load_fixture("song_detail")
        assert "streamingData" in raw  # sanity: the fixture does carry it
        metadata = map_song_metadata(raw)
        assert not hasattr(metadata, "streamingData")
        assert "streamingData" not in metadata.model_dump()

    def test_maps_video_details_fields(self, load_fixture):
        raw = load_fixture("song_detail")
        metadata = map_song_metadata(raw)
        details = raw["videoDetails"]
        assert metadata.videoId == details["videoId"]
        assert metadata.title == details["title"]
        assert metadata.lengthSeconds == int(details["lengthSeconds"])
        assert metadata.viewCount == int(details["viewCount"])
