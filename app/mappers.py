"""Raw ytmusicapi dict -> stable DTO translation.

This is the ONLY module that reads raw ytmusicapi shapes. Every accessor here must
coalesce a missing/None/malformed key to a safe default instead of raising -- YouTube's
internal API changes shape without notice (see the `parse_album_header_2024` helper and
the `yt-update` issue label upstream), and a parser-drift KeyError should surface as a
mapped 502, not an unhandled 500 from deep inside this file.
"""

from __future__ import annotations

from typing import Any

from app.models.album import AlbumDetail, RelatedAlbum
from app.models.artist import ArtistDetail, RelatedArtist
from app.models.common import AlbumRef, AlbumStub, ArtistRef, TrackDto, VideoStub
from app.models.playlist import PlaylistDetail
from app.models.search import SearchResultItem
from app.models.song import SongMetadata


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else None
    return None


def _thumbnail_url(thumbnails: Any) -> str | None:
    if not thumbnails or not isinstance(thumbnails, list):
        return None
    last = thumbnails[-1]
    if not isinstance(last, dict):
        return None
    return last.get("url")


def _map_artist_ref(raw: dict[str, Any]) -> ArtistRef:
    return ArtistRef(name=raw.get("name"), channelId=raw.get("id") or raw.get("channelId"))


def _map_artists(raw: Any) -> list[ArtistRef]:
    if not raw or not isinstance(raw, list):
        return []
    return [_map_artist_ref(a) for a in raw if isinstance(a, dict)]


def _map_album_ref(raw: Any) -> AlbumRef | None:
    """`album` shows up as a plain string on some tracks and {name, id} on others."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return AlbumRef(name=raw, browseId=None)
    if isinstance(raw, dict):
        return AlbumRef(name=raw.get("name"), browseId=raw.get("id") or raw.get("browseId"))
    return None


def _album_name(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return raw.get("name")
    return None


def _map_track(raw: dict[str, Any]) -> TrackDto:
    return TrackDto(
        videoId=raw.get("videoId"),
        title=raw.get("title"),
        artists=_map_artists(raw.get("artists")),
        albumName=_album_name(raw.get("album")),
        durationSeconds=_to_int(raw.get("duration_seconds")),
        trackNumber=_to_int(raw.get("trackNumber")),
        isAvailable=raw.get("isAvailable"),
        explicit=raw.get("isExplicit"),
        views=raw.get("views"),
    )


def _map_tracks(raw: Any) -> list[TrackDto]:
    if not raw or not isinstance(raw, list):
        return []
    return [_map_track(t) for t in raw if isinstance(t, dict)]


def _map_album_stub(raw: dict[str, Any]) -> AlbumStub:
    return AlbumStub(
        browseId=raw.get("browseId"),
        title=raw.get("title"),
        year=_to_int(raw.get("year")),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
    )


def _map_album_stubs(raw: Any) -> list[AlbumStub]:
    if not raw or not isinstance(raw, list):
        return []
    return [_map_album_stub(a) for a in raw if isinstance(a, dict)]


def map_album_stubs_from_artist_albums(raw: Any) -> list[AlbumStub]:
    """get_artist_albums() returns the same {browseId, title, year, thumbnails} shape as the
    albums bucket inside get_artist(), just with an extra `playlistId` we don't need here."""
    return _map_album_stubs(raw)


def _map_video_stub(raw: dict[str, Any]) -> VideoStub:
    return VideoStub(
        videoId=raw.get("videoId"),
        title=raw.get("title"),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
    )


def _map_video_stubs(raw: Any) -> list[VideoStub]:
    if not raw or not isinstance(raw, list):
        return []
    return [_map_video_stub(v) for v in raw if isinstance(v, dict)]


def _map_related_album(raw: dict[str, Any]) -> RelatedAlbum:
    return RelatedAlbum(
        browseId=raw.get("browseId"),
        title=raw.get("title"),
        type=raw.get("type"),
        artists=_map_artists(raw.get("artists")),
        audioPlaylistId=raw.get("audioPlaylistId"),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
        explicit=raw.get("isExplicit"),
    )


def _map_related_albums(raw: Any) -> list[RelatedAlbum]:
    """`other_versions` and `related_recommendations` carry an identical item shape."""
    if not raw or not isinstance(raw, list):
        return []
    return [_map_related_album(a) for a in raw if isinstance(a, dict)]


def map_search_item(raw: dict[str, Any]) -> SearchResultItem:
    result_type = raw.get("resultType")

    browse_id: str | None = None
    playlist_id: str | None = None
    title = raw.get("title")
    artists = _map_artists(raw.get("artists"))
    track_count: int | None = None

    if result_type == "artist":
        # A plain "Top result" artist card omits browseId/artist entirely and carries
        # identity only in artists[0] -- fall back to that shape.
        top_result_artist = (raw.get("artists") or [{}])[0] if isinstance(raw.get("artists"), list) else {}
        browse_id = raw.get("browseId") or top_result_artist.get("id")
        title = raw.get("artist") or top_result_artist.get("name") or title
    elif result_type == "album":
        browse_id = raw.get("browseId")
        playlist_id = raw.get("playlistId")  # OLAK5uy_... audioPlaylistId
    elif result_type in ("playlist", "profile", "podcast"):
        raw_browse = raw.get("browseId")
        browse_id = raw_browse
        if isinstance(raw_browse, str) and raw_browse.startswith("VL"):
            playlist_id = raw_browse[2:]
        # A mixed search's "Top result" playlist card carries a bare playlistId and no browseId.
        playlist_id = playlist_id or raw.get("playlistId")
        # Playlist cards carry "author", not "artists" -- a plain string on list rows, a list of
        # {name, id} on "Top result" cards. Fold either into artists so consumers read one shape.
        author = raw.get("author")
        if not artists:
            if isinstance(author, str) and author:
                artists = [ArtistRef(name=author, channelId=None)]
            elif isinstance(author, list):
                artists = _map_artists(author)
        # itemCount (ytmusicapi 1.12.2) is an int when numeric, a display string like "5,000+"
        # when capped, or None -- never an abbreviated "2.2B"-style string -- so _to_int is
        # safe here (see AGENTS.md on display strings).
        track_count = _to_int(raw.get("itemCount"))

    return SearchResultItem(
        type=result_type,
        videoId=raw.get("videoId"),
        browseId=browse_id,
        playlistId=playlist_id,
        title=title,
        artists=artists,
        album=_map_album_ref(raw.get("album")),
        durationSeconds=_to_int(raw.get("duration_seconds")),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
        explicit=raw.get("isExplicit"),
        year=_to_int(raw.get("year")),
        trackCount=track_count,
    )


def map_search_items(raw: list[dict[str, Any]], limit: int | None = None) -> list[SearchResultItem]:
    items = [map_search_item(item) for item in raw if isinstance(item, dict)]
    if limit is not None:
        items = items[:limit]
    return items


def map_album_detail(raw: dict[str, Any], requested_browse_id: str) -> AlbumDetail:
    """get_album()'s response body never contains its own browseId -- it comes back
    only as the path parameter that fetched it, so it is threaded through explicitly."""
    return AlbumDetail(
        browseId=requested_browse_id,
        title=raw.get("title"),
        type=raw.get("type"),
        year=_to_int(raw.get("year")),
        trackCount=_to_int(raw.get("trackCount")),
        durationSeconds=_to_int(raw.get("duration_seconds")),
        audioPlaylistId=raw.get("audioPlaylistId"),
        artists=_map_artists(raw.get("artists")),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
        description=raw.get("description"),
        explicit=raw.get("isExplicit"),
        tracks=_map_tracks(raw.get("tracks")),
        otherVersions=_map_related_albums(raw.get("other_versions")),
        relatedRecommendations=_map_related_albums(raw.get("related_recommendations")),
    )


def map_artist_detail(raw: dict[str, Any], requested_channel_id: str) -> ArtistDetail:
    songs_bucket = raw.get("songs") or {}
    albums_bucket = raw.get("albums") or {}
    singles_bucket = raw.get("singles") or {}
    videos_bucket = raw.get("videos") or {}
    related_bucket = raw.get("related") or {}

    related_raw = related_bucket.get("results") if isinstance(related_bucket, dict) else None
    related = [
        RelatedArtist(
            browseId=r.get("browseId"),
            title=r.get("title"),
            subscribers=r.get("subscribers"),
        )
        for r in (related_raw or [])
        if isinstance(r, dict)
    ]

    return ArtistDetail(
        channelId=requested_channel_id,
        name=raw.get("name"),
        description=raw.get("description"),
        subscribers=raw.get("subscribers"),
        monthlyListeners=raw.get("monthlyListeners"),
        views=raw.get("views"),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
        topSongs=_map_tracks(songs_bucket.get("results") if isinstance(songs_bucket, dict) else None),
        albums=_map_album_stubs(albums_bucket.get("results") if isinstance(albums_bucket, dict) else None),
        singles=_map_album_stubs(singles_bucket.get("results") if isinstance(singles_bucket, dict) else None),
        videos=_map_video_stubs(videos_bucket.get("results") if isinstance(videos_bucket, dict) else None),
        related=related,
    )


def map_playlist_detail(raw: dict[str, Any]) -> PlaylistDetail:
    author_raw = raw.get("author")
    author: ArtistRef | None = None
    if isinstance(author_raw, dict):
        author = _map_artist_ref(author_raw)
    elif isinstance(author_raw, str):
        author = ArtistRef(name=author_raw, channelId=None)

    return PlaylistDetail(
        id=raw.get("id"),
        title=raw.get("title"),
        description=raw.get("description"),
        author=author,
        privacy=raw.get("privacy"),
        trackCount=_to_int(raw.get("trackCount")),
        durationSeconds=_to_int(raw.get("duration_seconds")),
        thumbnailUrl=_thumbnail_url(raw.get("thumbnails")),
        tracks=_map_tracks(raw.get("tracks")),
    )


def map_song_metadata(raw: dict[str, Any]) -> SongMetadata:
    """Deliberately reads only videoDetails. streamingData/playabilityStatus are never touched."""
    details = raw.get("videoDetails") or {}
    return SongMetadata(
        videoId=details.get("videoId"),
        title=details.get("title"),
        author=details.get("author"),
        channelId=details.get("channelId"),
        lengthSeconds=_to_int(details.get("lengthSeconds")),
        viewCount=_to_int(details.get("viewCount")),
        thumbnailUrl=_thumbnail_url((details.get("thumbnail") or {}).get("thumbnails")),
    )
