# Agent guidance for ytmusic-adapter

Durable decisions and constraints. Keep this current — if you change behavior this file
describes, update the doc in the same change.

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
  lookup, add its mapper here, not inline in a router.
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
  signature on those three methods and converts it to `NotFoundError` → 404. Any other `KeyError` is
  real parser drift → 502. Don't widen that KeyError-to-404 translation to other methods without
  checking their actual failure signature first.
- A search result's `album` field is sometimes a plain string, sometimes `{name, id}` — depends on
  which endpoint it came from. `_map_album_ref`/`_album_name` in `mappers.py` handle both; don't
  assume a shape.
- A bare-name query's "Top result" artist card omits `browseId`/`artist` entirely — identity lives
  only in `artists[0]`. `map_search_item`'s artist branch falls back to that; don't remove the
  fallback thinking it's dead code.
- `limit` on ytmusicapi's own methods is a floor, not a ceiling. This adapter truncates to an exact
  count in the router/mapper layer — keep doing that so the API contract stays honest.

## Where the boundary with naviseerr sits

This repo has no dependency on naviseerr and naviseerr has no Java code consuming it yet — that
integration is a separate, deliberately deferred piece of work. Don't add Java-side coupling here.
