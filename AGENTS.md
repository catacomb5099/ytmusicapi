# Agent guidance for ytmusic-adapter

Durable decisions and constraints. Keep this current — if you change behavior this file
describes, update the doc in the same change.

When the owner works through their `/naviseerr` command, that command decides how to plan, demo, open PRs and merge, and it wins over this file on those points. This file covers the code.

## What this service is

A stateless FastAPI adapter around `ytmusicapi`, exposing read-only search + detail lookups
(songs, videos, albums, artists, playlists) as JSON. It exists so [naviseerr](../naviseerr) can
get artist/album/playlist metadata that Last.fm can't provide (no playlists, empty `mbid`s,
hardcoded years/albumIds in the current mapper).

## Hard constraints

- **Anonymous only.** No OAuth, no `browser.json`, no cookies, by default. `YTM_AUTH_FILE` exists
  as a dormant escape hatch, not a default — setting it breaks the stateless/no-secrets property,
  so treat any PR that flips it on as a service-boundary decision, not a config tweak.
- **No playback/streaming surface.** `get_song()`'s `streamingData`/`playabilityStatus` must never
  be read by a mapper or reach a response. `map_song_metadata()` only reads `videoDetails`; keep it
  that way even if you're tempted to expose more of `get_song()`'s payload.
- **`mappers.py` is the only file that reads raw ytmusicapi dicts.** Every field access there must
  coalesce a missing/malformed key to a safe default rather than raise. If you add a new detail
  lookup, add its mapper here, not inline in a router. One exception: the ytmusicapi parser wrappers
  in `ytmusic_client.py`, which read a raw playlist header or row before the library discards its
  count string; see the play-counts bullet below.
- **No new dependencies without a reason.** No Redis, no DB driver, no resilience library. The
  service is stateless by design; caching lives on naviseerr's side, not here.

## Testing

- `tests/test_mappers.py` is fixture-driven from real recorded JSON in `tests/fixtures/` — no
  network. When you add a lookup, record its fixture with a throwaway script calling the real
  `YTMusic()` once (see the git history of `tests/fixtures/` for the pattern), then write the
  mapper against the real shape, not against assumptions.
- Add a deliberately mangled variant of any new fixture (missing keys, empty lists) so the mapper
  test proves graceful degradation, not just the happy path.
- `tests/test_contract_live.py` (`@pytest.mark.live`, excluded from the default run) is what
  detects real YouTube shape drift. A failure there means "YouTube changed" or "this IP got
  flagged" — re-record fixtures and fix the mapper, don't just loosen the live test's assertions.
- Run `uv run pytest && uv run ruff check . && uv run mypy app` before considering any change done.

## Known gotchas (don't rediscover these)

- `get_album()`'s response body never contains its own `browseId` — it only comes back as the path
  parameter that fetched it. Same idea for `get_artist()`: its returned `channelId` is *not* the one
  you requested (it's only valid for `subscribe_artists`) — always echo the caller's original id.
- `get_album`/`get_artist`/`get_playlist` raise a bare `KeyError` (missing `'contents'` key), not a
  typed not-found error, for an invalid/deleted id. `YTMusicClient.call()` recognizes this specific
  signature on those methods and converts it to `NotFoundError` → 404. Same for `get_song_credits`,
  whose signature is a missing `'sections'` key — YouTube answers with a credits dialog that only
  says "Lyrics not available". Any other `KeyError` is real parser drift → 502. Don't widen that
  KeyError-to-404 translation to other methods without checking their actual failure signature first.
- **Song credits, album, year, `explicit` and `plays` exist only for album-track (`ATV`) ids.** An
  official-video (`OMV`) id — the kind a "(Official Video)" title carries — has none of them
  anywhere in ytmusicapi, and there is no public way to hop to its album-track twin. `/details`
  reports them as `null`/`[]` rather than guessing via a title search. The `explicit` flag lives
  only on `get_album()` track rows (not `get_song`, not the watch panel), and those rows often list
  the OMV id while `creditsBrowseId` is `'MPTC' + <ATV id>` — `pick_album_track` matches on either.
  Never take a song's year from `get_song()`'s `publishDate` (that is the video upload date) or its
  duration from the watch track's `length` (an `m:ss` string that `_to_int` would mangle).
  ytmusicapi's watch parser models a `counterpart` (song/video twin) field, but it is absent on
  anonymous requests for every OMV id probed — don't rediscover it. The same parser silently drops
  unplayable (region-blocked) rows, so the watch panel can come back *without* the requested id;
  `pick_watch_track` then returns `{}`, never the first radio row (that would attribute another
  song's album and year). `/details` also skips the credits call outright for an OMV `videoType`
  (two upstream calls, not four); the `MPTC + videoId` fallback stays for ATV ids whose panel failed.
- A search result's `album` field is sometimes a plain string, sometimes `{name, id}` — depends on
  which endpoint it came from. `_map_album_ref`/`_album_name` in `mappers.py` handle both; don't
  assume a shape.
- A bare-name query's "Top result" artist card omits `browseId`/`artist` entirely — identity lives
  only in `artists[0]`. `map_search_item`'s artist branch falls back to that; don't remove the
  fallback thinking it's dead code.
- **Play counts and listener stats are display strings, not numbers.** `views` on album tracks
  (`"2.2B plays"`), `views` on song/video search results (`"7.2M"`, no noun; null on the mixed
  search's "Top result" card), `views` on playlist search rows (`"375K views"`, noun kept), `monthlyListeners` (`"181M"`), `subscribers` (`"20.3M"`) and artist
  `views` (`"12,715,572,299 views"`) are already abbreviated/formatted upstream. They are mapped verbatim
  as `str`. Do NOT route them through `_to_int()` — it strips non-digits, so `"2.2B plays"` becomes
  `22`. The only exact integer available is `viewCount` from `get_song()` (on `SongMetadata` and
  `SongDetails`), and it counts that one upload only. `SongDetails.plays` is the album track's
  `views`, YouTube Music's combined count: Wonderwall `hpSrLjc5SMs` has `viewCount` 97,645,262 but
  `plays` `"1.7B plays"`. They are different numbers; never fill one from the other. Track
  `views` is populated on `get_album()` tracks and on an artist's "Top songs" playlist
  (`VLOLAK5uy_…`, the `songs.browseId` of `get_artist()`), whose rows print "1.7B plays" in a plain
  column that ytmusicapi reads only on album pages: `app/ytmusic_client.py` wraps
  `ytmusicapi.parsers.playlists.parse_playlist_item` (the third library wrap) to keep it. Other
  playlists' tracks have no such column and stay null; `TrackDto` is shared, so null there is
  expected, not drift. `get_artist()` top songs also arrive with `views: None`, so
  `/v1/artists/{channelId}` reads its ten top songs from that "Top songs" playlist instead; only
  when that call fails does it keep the page's five and fill them from each song's album (one `get_album` per distinct album,
  in parallel, matched via `pick_album_track`, else the one album row with the same title via
  `pick_album_track_by_title` -- Bicep "Glue" lists a third upload id). That is best-effort: an album that fails to load
  logs a warning and leaves its songs null; it never fails the artist response.
  **A playlist's own view count is the worst case of this:** `get_playlist()["views"]` is
  `to_int("6.9M views")` = 69 (ytmusicapi 1.12.2 `parsers/playlists.py`), lossy and never exposed.
  `app/ytmusic_client.py` wraps `ytmusicapi.mixins.playlists.parse_playlist_header_meta` once at
  import so the raw header's first run survives as `viewsText`, which `map_playlist_detail` exposes
  as `PlaylistDetail.views` (`"6.9M views"`, verbatim, localised by `YTM_LANGUAGE`). YouTube Music's
  own editorial playlists (`RDCLAK5uy_…`) have no count in their header (3 runs, not 5), so `views`
  is None there; radios (`map_radio`) never set it. That wrapper is the one place outside
  `mappers.py` that reads a raw ytmusicapi dict (a header, before the library discards the string);
  if a library bump drops the name it logs a WARN and skips, so `views` goes null and startup is
  unaffected. Upstream `main` still has the same lossy line, so do not expect a bump to fix it.
- **An artist's own playlists ("Playlists by Tame Impala").** ytmusicapi 1.12.2's
  `Parser.parse_channel_contents` matches shelf titles exactly against "playlists", and YouTube now
  titles that row "Playlists by <artist>", so `get_artist()` has no `playlists` bucket. The fourth
  library wrap (`_keep_artist_playlists_shelf` in `app/ytmusic_client.py`) adds it from the shelf
  whose title links to a full list and whose first card opens a playlist (`VL…`); that rule works in
  any language. "Featured on" has no title link and is never picked. The title link's `params` go
  stale within minutes, so read the full list (`get_user_playlists`) with the params of the same
  `get_artist()` answer, never cached ones (a stale one answers `[]`).
- **Album-level `isExplicit` disagrees with its own tracks.** `good kid, m.A.A.d city` returns
  album `isExplicit: false` while all 14 tracks are `explicit: true`. It's mapped faithfully as
  `AlbumDetail.explicit`, but don't render it as a badge — prefer the per-track flag.
- `get_album()`'s `other_versions` (deluxe/alt editions) and `related_recommendations` carry an
  identical item shape, so both map through the one `RelatedAlbum` model via `_map_related_albums`.
- **Album and artist `description` is Wikipedia text under CC-BY-SA 3.0.** The attribution and
  licence URL are part of the description string itself — a consumer that trims or summarizes it
  drops a licence obligation. `descriptionRuns` holds the same text with real hyperlinks and is
  deliberately not exposed yet.
- Playlist search items carry `author` and no `artists`: a plain string on list rows, a list of
  `{name, id}` on a mixed search's "Top result" card (which also has a bare `playlistId` and no
  `browseId`). `map_search_item` folds either into `artists` so consumers read one shape, and
  synthesizes `browseId = "VL" + playlistId` on the card so `browseId` is always `VL`-prefixed. Their
  `itemCount` is an `int` when numeric, a display string like `"5,000+"` when capped, or `None`;
  `_to_int` handles all three (it is never an abbreviated `"2.2B"`-style string, so the warning
  above does not apply). Upstream only sets `itemCount` when the row subtitle literally reads
  `"N songs"`, which is rare (most rows show views), so `trackCount` is usually `None` on search
  results — point consumers at `/v1/playlists/{id}.trackCount` instead. The view count those rows
  show instead ("375K views", the last subtitle run) is what ytmusicapi drops: `app/ytmusic_client.py`
  wraps `ytmusicapi.parsers.search.parse_search_result` (the second library wrap, same shape as the
  header one) and adds `viewsText` to playlist rows, which `map_search_item` exposes as
  `SearchResultItem.views` with its noun kept. A row shows a view count or a song count, never both
  (measured 19-10-2026 on 80 rows: user-made rows "375K views", editorial rows "51 songs"), so a
  row whose last run is `"N songs"` keeps `viewsText` None; that English test is the library's own
  `itemCount` test, so with another `YTM_LANGUAGE` an editorial row's "51 Titel" would come through
  as the count YouTube shows there. Raw row shape in `tests/fixtures/search_raw_row_playlist_mixed.json`. Both shapes are recorded live in `tests/fixtures/search_item_playlist_*.json`. `filter="featured_playlists"` rows (YouTube Music's editorial playlists) share the list-row shape with `RDCLAK5uy_…` ids and author `"YouTube Music"`; `get_playlist` opens them like any playlist (verified live, `tests/fixtures/search_featured_playlists.json`).
- **Radios (`/v1/radio`).** A song's radio is `get_watch_playlist(videoId=…)` (ytmusicapi fills in
  `RDAMVM` + id); an album's or playlist's is `get_watch_playlist(playlistId="RDAMPL" + <OLAK…/PL…/RDCLAK…>)`.
  ytmusicapi's `radio=True` flag looks like the obvious switch and is not: on an album or playlist id it
  only replays the seed. `get_playlist()` cannot open any `RD…` radio id (KeyError → 404), so a radio is
  never reachable through `/v1/playlists`. A radio is rebuilt on every call: measured 2026-10-04, the
  same seed two minutes apart kept 18/25 (song), 7/25 (album) and 5/25 (playlist) of its songs; calls
  in the same second agree. Consumers that show a radio and later act on it must store it. An unknown
  video id answers `YTMusicServerError("No content returned by the server…")`, translated to 404 in
  the radio router only. A radio started from a music-video (`OMV`) id comes back all music videos.
- **ytmusicapi decodes the body before it checks the status** (`_send_request`: `json.loads(response.text)`
  first). A YouTube 429 or 403 with an HTML body therefore raises `json.JSONDecodeError`, never
  `YTMusicServerError`, and reaches `app/errors.py` as "unreadable answer" (502), not as a rate limit.
  The 429 branch only ever sees a JSON-bodied 429. Don't "fix" this by parsing the HTML.
- **A `requests.ConnectionError` is not a timeout.** It covers DNS failure, refused, TLS, proxy and
  connect timeout, and is answered 502 `upstream_unreachable` naming the chained cause's class;
  only `ReadTimeout` (YouTube reached, slow) is 504 `upstream_timeout`. On 12-10-2026 both read
  "Upstream request timed out" and a DNS failure inside the container was taken for a rate limit.
- `limit` on ytmusicapi's own methods is a floor, not a ceiling. This adapter truncates to an exact
  count in the router/mapper layer — keep doing that so the API contract stays honest.

## Where the boundary with naviseerr sits

This repo has no dependency on naviseerr and naviseerr has no Java code consuming it yet — that
integration is a separate, deliberately deferred piece of work. Don't add Java-side coupling here.
