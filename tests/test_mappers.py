from app.mappers import (
    album_browse_id,
    credits_browse_id,
    is_official_video,
    map_album_detail,
    map_artist_detail,
    map_playlist_detail,
    map_search_item,
    map_search_items,
    map_song_details,
    map_song_metadata,
    pick_album_track,
    pick_watch_track,
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

    def test_songs_inside_top_result_artist_card_inherit_the_card_artist(self, load_fixture):
        """Recorded for "bad omens": the card's three songs have no `artists` key at all."""
        raw = load_fixture("search_mixed_artist_card")
        card_songs = [i for i in raw if i["resultType"] == "song"]
        assert len(card_songs) == 3 and all("artists" not in i for i in card_songs)
        items = map_search_items(raw)
        for item in items:
            if item.type == "song":
                assert [a.name for a in item.artists] == ["Bad Omens"]
                assert item.artists[0].channelId == raw[0]["artists"][0]["id"]
        # Rows with their own artist, or in a later titled shelf, are left alone.
        albums = [i for i in items if i.type == "album"]
        assert albums and all(a.artists for a in albums)
        shelved = [dict(i, category="Songs") if "artists" not in i else i for i in raw]
        assert all(not i.artists for i in map_search_items(shelved) if i.type == "song")

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

    def test_playlist_item_folds_author_into_artists(self, load_fixture):
        """Playlist cards carry a plain-string "author" and no "artists" -- the mapper
        folds it into artists[0] so every result type exposes the same shape."""
        for fixture in ("search_playlists", "search_mixed"):
            raw = next(i for i in load_fixture(fixture) if i["resultType"] == "playlist")
            assert isinstance(raw["author"], str)
            assert not raw.get("artists")
            item = map_search_item(raw)
            assert item.artists[0].name == raw["author"]
            assert item.artists[0].channelId is None

    def test_top_result_playlist_card_folds_author_list_and_bare_playlist_id(self, load_fixture):
        """A mixed search's "Top result" playlist card carries author as [{name, id}] and a
        bare playlistId with no browseId. Fixture recorded live from a mixed search for
        "Indie Rock Essentials" (ytmusicapi 1.12.2)."""
        raw = load_fixture("search_item_playlist_top_result")
        assert isinstance(raw["author"], list)
        assert "browseId" not in raw
        item = map_search_item(raw)
        assert item.artists[0].name == raw["author"][0]["name"]
        assert item.artists[0].channelId == raw["author"][0]["id"]
        assert item.playlistId == raw["playlistId"]
        assert item.browseId == "VL" + raw["playlistId"]
        # mangled variants degrade, never raise
        assert map_search_item({**raw, "author": []}).artists == []
        assert map_search_item({**raw, "author": [1, "x"]}).artists == []
        no_id = map_search_item({k: v for k, v in raw.items() if k != "playlistId"})
        assert no_id.playlistId is None
        assert no_id.browseId is None
        # a VL-prefixed raw playlistId must never yield "VLVL..."
        vl = map_search_item({**raw, "playlistId": "VL" + raw["playlistId"]})
        assert (vl.browseId, vl.playlistId) == ("VL" + raw["playlistId"], raw["playlistId"])

    def test_playlist_item_maps_item_count_to_track_count(self, load_fixture):
        """ytmusicapi hands over itemCount as an int when numeric and as a display string
        like "5,000+" when capped. Fixture recorded live from a community_playlists search
        for "Indie Rock Essentials" (ytmusicapi 1.12.2); most rows carry itemCount: null."""
        raw = load_fixture("search_item_playlist_with_item_count")
        assert map_search_item(raw).trackCount == raw["itemCount"] == 165
        assert map_search_item({**raw, "itemCount": "5,000+"}).trackCount == 5000

    def test_mangled_playlist_item_missing_author_does_not_raise(self, load_fixture):
        raw = load_fixture("search_item_mangled_playlist")
        assert "author" not in raw
        item = map_search_item(raw)
        assert item.type == "playlist"
        assert item.artists == []
        assert item.trackCount is None

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

    def test_maps_description_and_album_level_explicit(self, load_fixture):
        raw = load_fixture("album_detail")
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert detail.description == raw["description"]
        assert detail.explicit == raw["isExplicit"]

    def test_maps_other_versions_and_related_recommendations(self, load_fixture):
        """Both buckets share one item shape upstream, so both map through RelatedAlbum."""
        raw = load_fixture("album_detail")
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert len(detail.otherVersions) == len(raw["other_versions"])
        assert len(detail.relatedRecommendations) == len(raw["related_recommendations"])
        rec = detail.relatedRecommendations[0]
        raw_rec = raw["related_recommendations"][0]
        assert rec.browseId == raw_rec["browseId"]
        assert rec.audioPlaylistId == raw_rec["audioPlaylistId"]
        assert rec.type == raw_rec["type"]
        assert rec.explicit == raw_rec["isExplicit"]
        assert rec.artists[0].channelId == raw_rec["artists"][0]["id"]
        assert rec.thumbnailUrl == raw_rec["thumbnails"][-1]["url"]

    def test_track_views_kept_verbatim_as_display_string(self, load_fixture):
        """Upstream sends "27M plays" -- an abbreviation, not a number. Parsing it to an
        int would silently read "2.2B plays" as 22, so it stays a string."""
        raw = load_fixture("album_detail")
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert detail.tracks[0].views == raw["tracks"][0]["views"]
        assert isinstance(detail.tracks[0].views, str)

    def test_mangled_album_missing_audio_playlist_id_and_track_fields(self, load_fixture):
        raw = load_fixture("album_detail_mangled")
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert detail.audioPlaylistId is None
        assert detail.year is None
        track = detail.tracks[0]
        assert track.durationSeconds is None
        assert track.trackNumber is None

    def test_mangled_album_missing_new_fields_degrades_gracefully(self, load_fixture):
        raw = load_fixture("album_detail_mangled")
        assert "description" not in raw
        assert "isExplicit" not in raw
        assert "other_versions" not in raw
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert detail.description is None
        assert detail.explicit is None
        assert detail.otherVersions == []
        assert detail.tracks[0].views is None

    def test_malformed_recommendation_entries_are_skipped_not_raised(self, load_fixture):
        """The bucket holds a dict missing every optional key plus a non-dict entry."""
        raw = load_fixture("album_detail_mangled")
        assert any(not isinstance(r, dict) for r in raw["related_recommendations"])
        detail = map_album_detail(raw, requested_browse_id="MPREb_TEST")
        assert len(detail.relatedRecommendations) == 1  # the non-dict is dropped
        only = detail.relatedRecommendations[0]
        assert only.browseId == "MPREb_MANGLED"
        assert only.thumbnailUrl is None
        assert only.artists == []
        assert only.type is None


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

    def test_maps_monthly_listeners_and_views(self, load_fixture):
        """Both are upstream display strings ("51.2M", "4,883,414,620 views"), mapped
        verbatim for the same reason `subscribers` already is."""
        raw = load_fixture("artist_detail")
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        assert detail.monthlyListeners == raw["monthlyListeners"]
        assert detail.views == raw["views"]

    def test_artist_with_no_albums_bucket_returns_empty_list(self, load_fixture):
        raw = load_fixture("artist_detail_no_albums")
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        assert detail.albums == []
        assert detail.singles == []

    def test_artist_missing_listener_stats_degrades_gracefully(self, load_fixture):
        raw = load_fixture("artist_detail_no_albums")
        assert "monthlyListeners" not in raw
        assert "views" not in raw
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        assert detail.monthlyListeners is None
        assert detail.views is None

    def test_related_artists_carry_their_largest_thumbnail(self, load_fixture):
        raw = load_fixture("artist_detail")
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        raw_related = raw["related"]["results"]
        assert len(detail.related) == len(raw_related)
        for mapped, r in zip(detail.related, raw_related, strict=True):
            assert mapped.browseId == r["browseId"]
            assert mapped.thumbnailUrl == r["thumbnails"][-1]["url"]

    def test_related_artist_without_thumbnails_maps_to_none(self, load_fixture):
        raw = load_fixture("artist_detail")
        del raw["related"]["results"][0]["thumbnails"]
        raw["related"]["results"][1]["thumbnails"] = []
        detail = map_artist_detail(raw, requested_channel_id=raw["requestedChannelId"])
        assert detail.related[0].thumbnailUrl is None
        assert detail.related[1].thumbnailUrl is None
        assert detail.related[2].thumbnailUrl  # the rest are untouched


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


class TestSongDetailsMapping:
    VIDEO_ID = "DntZ3-yCaFs"

    def _full(self, load_fixture):
        song = load_fixture("song_details_song")
        watch_track = pick_watch_track(load_fixture("song_details_watch"), self.VIDEO_ID)
        album = load_fixture("song_details_album")
        album_track = pick_album_track(album, self.VIDEO_ID)
        return map_song_details(
            self.VIDEO_ID, song, watch_track, album, album_track, load_fixture("song_details_credits")
        )

    def test_album_track_maps_every_field(self, load_fixture):
        d = self._full(load_fixture)
        assert d.videoId == self.VIDEO_ID
        assert d.title == "Manchild"
        assert d.artists[0].name == "Sabrina Carpenter"
        assert d.artists[0].channelId == "UCz51ZodJbYUNfkdPHOjJKKw"
        assert d.album is not None and d.album.browseId == "MPREb_msfRVJDqlXJ"
        assert d.year == 2025
        assert d.durationSeconds == 214  # exact, from videoDetails -- not the watch track's "3:34"
        assert d.viewCount == 86376035
        assert d.explicit is True  # per-track flag; the album header says False
        assert d.thumbnailUrl and d.thumbnailUrl.startswith("https://")
        assert [c.role for c in d.credits] == [
            "Performed by",
            "Written by",
            "Produced by",
            "Music metadata provided by",
        ]
        assert d.credits[1].names == ["Sabrina Carpenter", "Jack Antonoff", "Amy Allen"]

    def test_never_exposes_streaming_data(self, load_fixture):
        assert "streamingData" in load_fixture("song_details_song")
        assert "streamingData" not in self._full(load_fixture).model_dump()

    def test_album_track_is_matched_by_credits_id_when_row_lists_the_omv_id(self, load_fixture):
        album = load_fixture("song_details_album")
        assert album["tracks"][0]["videoId"] != self.VIDEO_ID
        track = pick_album_track(album, self.VIDEO_ID)
        assert track["creditsBrowseId"] == f"MPTC{self.VIDEO_ID}"
        assert credits_browse_id(track, self.VIDEO_ID) == f"MPTC{self.VIDEO_ID}"
        assert pick_album_track(album, "nope") == {}
        assert credits_browse_id({}, "nope") == "MPTCnope"

    def test_official_video_has_no_album_year_explicit_or_credits(self, load_fixture):
        watch_track = pick_watch_track(load_fixture("song_details_watch_omv"), "tM1RS_5IAiE")
        assert album_browse_id(watch_track) is None
        song = load_fixture("song_details_song")
        d = map_song_details("tM1RS_5IAiE", song, watch_track, None, {}, None)
        assert d.album is None and d.year is None and d.explicit is None and d.credits == []
        assert d.artists[0].name == "Oasis"
        assert d.viewCount == int(song["videoDetails"]["viewCount"])

    def test_missing_watch_panel_falls_back_to_video_details_author(self, load_fixture):
        song = load_fixture("song_details_song")
        assert pick_watch_track(None, self.VIDEO_ID) == {}
        d = map_song_details(self.VIDEO_ID, song, {}, None, {}, None)
        assert d.artists[0].name == song["videoDetails"]["author"]
        assert d.artists[0].channelId == song["videoDetails"]["channelId"]
        assert d.album is None
        # A non-string author must not reach pydantic as an ArtistRef name.
        assert map_song_details(self.VIDEO_ID, {"videoDetails": {"author": 123}}, {}, None, {}, None).artists == []

    def test_watch_panel_without_the_requested_id_is_never_guessed_from_another_row(self, load_fixture):
        # The upstream parser drops unplayable rows, so the panel can come back without the
        # requested song. The first remaining row is a different song: its album/year must not leak.
        panel = load_fixture("song_details_watch_mangled")
        assert panel["tracks"][0]["videoId"] != self.VIDEO_ID
        watch_track = pick_watch_track(panel, self.VIDEO_ID)
        assert watch_track == {}
        assert not is_official_video(watch_track)
        song = load_fixture("song_details_song")
        d = map_song_details(self.VIDEO_ID, song, watch_track, None, {}, None)
        assert d.album is None and d.year is None
        assert d.artists[0].name == song["videoDetails"]["author"]
        assert is_official_video(pick_watch_track(load_fixture("song_details_watch_omv"), "tM1RS_5IAiE"))

    def test_mangled_credits_keep_only_well_formed_sections(self, load_fixture):
        d = map_song_details(
            self.VIDEO_ID, {}, {}, None, {}, load_fixture("song_details_credits_mangled")
        )
        assert [(c.role, c.names) for c in d.credits] == [
            ("Performed by", []),
            ("Mixed by", ["Serban Ghenea"]),
        ]
        assert d.title is None and d.durationSeconds is None
