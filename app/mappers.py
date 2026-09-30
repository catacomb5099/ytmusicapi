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
from app.models.song import CreditsSection, SongDetails, SongMetadata


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
        # Keep the contract (browseId is always "VL"-prefixed); get_playlist prefixes the same way.
        # Strip any VL first so a VL-prefixed raw playlistId can never yield "VLVL...".
        if browse_id is None and isinstance(playlist_id, str) and playlist_id:
            playlist_id = playlist_id.removeprefix("VL")
            browse_id = f"VL{playlist_id}"
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
        views=raw.get("views"),
    )


def map_search_items(raw: list[dict[str, Any]], limit: int | None = None) -> list[SearchResultItem]:
    items: list[SearchResultItem] = []
    # When the "Top result" is an artist, the songs listed inside that card carry no artist of
    # their own (the card's heading is the artist), so ytmusicapi hands them over with no
    # `artists` key and they would render as "Unknown Artist" downstream. ytmusicapi marks those
    # card rows with category None; the next titled shelf ends the card.
    card_artists: list[ArtistRef] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mapped = map_search_item(item)
        if item.get("category") == "Top result":
            card_artists = mapped.artists if mapped.type == "artist" else []
        elif item.get("category") is not None:
            card_artists = []
        elif card_artists and mapped.type in ("song", "video") and not mapped.artists:
            mapped.artists = card_artists
        items.append(mapped)
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


def _top_song_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    bucket = raw.get("songs")
    rows = bucket.get("results") if isinstance(bucket, dict) else None
    return [s for s in rows if isinstance(s, dict)] if isinstance(rows, list) else []


def top_song_album_ids(raw: dict[str, Any]) -> list[str]:
    """get_artist() top songs carry views None but name their album, whose get_album() track rows
    do carry the play count ("1.7B plays"). The distinct albums worth fetching, in order."""
    ids = (album_browse_id(s) for s in _top_song_rows(raw) if s.get("views") is None)
    return list(dict.fromkeys(i for i in ids if i))


def _map_top_song(raw: dict[str, Any], albums: dict[str, Any]) -> TrackDto:
    track = _map_track(raw)
    video_id = raw.get("videoId")
    if track.views is None and isinstance(video_id, str):
        views = pick_album_track(albums.get(album_browse_id(raw) or ""), video_id).get("views")
        track.views = views if isinstance(views, str) else None
    return track


def map_artist_detail(
    raw: dict[str, Any], requested_channel_id: str, albums: dict[str, Any] | None = None
) -> ArtistDetail:
    """`albums` maps a top song's album browseId to its get_album() dict (None when that call
    failed); it only fills topSongs' `views`, which get_artist() leaves null."""
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
            thumbnailUrl=_thumbnail_url(r.get("thumbnails")),
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
        topSongs=[_map_top_song(s, albums or {}) for s in _top_song_rows(raw)],
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


def pick_watch_track(watch_raw: Any, video_id: str) -> dict[str, Any]:
    """get_watch_playlist() normally returns the requested song as tracks[0] plus a radio tail, but
    ytmusicapi's parser silently drops unplayable (e.g. region-blocked) rows -- so match on videoId
    only and return {} when it is absent, never a different song's row."""
    tracks = (watch_raw or {}).get("tracks") if isinstance(watch_raw, dict) else None
    if not tracks or not isinstance(tracks, list):
        return {}
    return next((t for t in tracks if isinstance(t, dict) and t.get("videoId") == video_id), {})


def is_official_video(watch_track: dict[str, Any]) -> bool:
    """An OMV id has no credits panel anywhere, so the credits call is skipped for it."""
    return watch_track.get("videoType") == "MUSIC_VIDEO_TYPE_OMV"


def pick_album_track(album_raw: Any, video_id: str) -> dict[str, Any]:
    """get_album() track rows often list the official-video id while creditsBrowseId carries
    'MPTC' + the canonical album-track id -- so match on either. {} when no row matches."""
    tracks = (album_raw or {}).get("tracks") if isinstance(album_raw, dict) else None
    if not tracks or not isinstance(tracks, list):
        return {}
    return next(
        (
            t
            for t in tracks
            if isinstance(t, dict)
            and (t.get("videoId") == video_id or t.get("creditsBrowseId") == f"MPTC{video_id}")
        ),
        {},
    )


def album_browse_id(watch_track: dict[str, Any]) -> str | None:
    album = _map_album_ref(watch_track.get("album"))
    return album.browseId if album else None


def credits_browse_id(album_track: dict[str, Any], video_id: str) -> str:
    return album_track.get("creditsBrowseId") or f"MPTC{video_id}"


_CREDITS_KEYS = ("performed_by", "written_by", "produced_by", "music_metadata_provided_by")


def _map_credits(raw: Any) -> list[CreditsSection]:
    if not isinstance(raw, dict):
        return []
    other = raw.get("other_sections")
    sections = [raw.get(k) for k in _CREDITS_KEYS] + (other if isinstance(other, list) else [])
    out: list[CreditsSection] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        role = section.get("localized_title")
        if not isinstance(role, str) or not role:
            continue
        names = section.get("data")
        out.append(
            CreditsSection(
                role=role,
                names=[n for n in names if isinstance(n, str)] if isinstance(names, list) else [],
            )
        )
    return out


def map_song_details(
    video_id: str,
    song_raw: dict[str, Any],
    watch_track: dict[str, Any],
    album_raw: Any,
    album_track: dict[str, Any],
    credits_raw: Any,
) -> SongDetails:
    """Reads only get_song()'s videoDetails (never streamingData), one watch-panel track, one
    album track and the credits dict. Duration/viewCount come from videoDetails (exact ints);
    the watch track's 'length' is 'm:ss' and its 'views' is mis-parsed upstream, so neither is read.
    Year comes from the watch track or the album header, never from the video upload date."""
    details = song_raw.get("videoDetails") or {}
    author = details.get("author")
    artists = _map_artists(watch_track.get("artists")) or (
        [ArtistRef(name=author, channelId=details.get("channelId"))] if isinstance(author, str) and author else []
    )
    album_year = album_raw.get("year") if isinstance(album_raw, dict) else None
    explicit = album_track.get("isExplicit")
    return SongDetails(
        videoId=video_id,
        title=details.get("title") or watch_track.get("title"),
        artists=artists,
        album=_map_album_ref(watch_track.get("album")),
        durationSeconds=_to_int(details.get("lengthSeconds")),
        year=_to_int(watch_track.get("year")) or _to_int(album_year),
        viewCount=_to_int(details.get("viewCount")),
        explicit=explicit if isinstance(explicit, bool) else None,
        thumbnailUrl=_thumbnail_url((details.get("thumbnail") or {}).get("thumbnails"))
        or _thumbnail_url(watch_track.get("thumbnail")),
        credits=_map_credits(credits_raw),
    )


def _length_seconds(value: Any) -> int | None:
    """A watch-panel row's `length` is a clock string ("3:56", "1:02:03"), not a number -- _to_int
    would turn "3:56" into 356."""
    if not isinstance(value, str) or not value:
        return None
    parts = value.split(":")
    if not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _map_watch_track(raw: dict[str, Any]) -> TrackDto:
    """A watch-panel (radio) row. Its `views` is not read: it is only set on music-video rows and
    counts that one upload, which is not the combined play count TrackDto.views carries elsewhere."""
    return TrackDto(
        videoId=raw.get("videoId"),
        title=raw.get("title"),
        artists=_map_artists(raw.get("artists")),
        albumName=_album_name(raw.get("album")),
        durationSeconds=_length_seconds(raw.get("length")),
    )


def _song_key(raw: dict[str, Any]) -> tuple[str, str] | None:
    """Title before any bracket or " - " suffix, plus the first artist, lowercased. A radio repeats
    the seed's own songs under other ids ("Human Nature" on Thriller's radio is a different upload),
    so matching on id alone lets them through.
    ponytail: suffix-stripping heuristic; a song whose real title has " - " or "(" collapses with
    its namesake by the same artist, which in a radio only drops one row."""
    title = raw.get("title")
    artists = raw.get("artists")
    if not isinstance(title, str) or not isinstance(artists, list) or not artists:
        return None
    first = artists[0].get("name") if isinstance(artists[0], dict) else None
    if not isinstance(first, str):
        return None
    base = title.split(" (")[0].split(" [")[0].split(" - ")[0].strip().lower()
    return (base, first.strip().lower())


def map_radio(seed_id: str, seed_raw: Any, watch_raw: Any, limit: int) -> PlaylistDetail:
    """A radio built from one song, album or playlist, in the playlist shape so callers read it like
    any other track list. `title`, `author` and `thumbnailUrl` describe the SEED (radios have no
    title of their own upstream). `seed_raw` is get_album()/get_playlist() for those seeds and None
    for a song, whose own row is the watch panel's first track. Songs that are the seed's own are
    dropped, then the rest is cut to exactly `limit`."""
    watch_tracks = (watch_raw or {}).get("tracks") if isinstance(watch_raw, dict) else None
    rows = [t for t in watch_tracks if isinstance(t, dict)] if isinstance(watch_tracks, list) else []

    if isinstance(seed_raw, dict):
        seed_rows = [t for t in seed_raw.get("tracks") or [] if isinstance(t, dict)]
        title = seed_raw.get("title")
        authors = _map_artists(seed_raw.get("artists"))
        author_raw = seed_raw.get("author")
        if isinstance(author_raw, dict):
            authors = [_map_artist_ref(author_raw)]
        elif isinstance(author_raw, str):
            authors = [ArtistRef(name=author_raw, channelId=None)]
        thumbnail = _thumbnail_url(seed_raw.get("thumbnails"))
    else:
        seed_row = pick_watch_track(watch_raw, seed_id)
        seed_rows = [seed_row] if seed_row else []
        title = seed_row.get("title")
        authors = _map_artists(seed_row.get("artists"))
        thumbnail = _thumbnail_url(seed_row.get("thumbnail"))

    seed_ids = {t.get("videoId") for t in seed_rows} | {seed_id}
    seed_keys = {key for key in (_song_key(t) for t in seed_rows) if key}
    tracks = [
        _map_watch_track(t)
        for t in rows
        if t.get("videoId") and t.get("videoId") not in seed_ids and _song_key(t) not in seed_keys
    ][:limit]

    return PlaylistDetail(
        id=seed_id,
        title=title,
        author=authors[0] if authors else None,
        trackCount=len(tracks),
        thumbnailUrl=thumbnail,
        tracks=tracks,
    )
