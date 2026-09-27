# ytmusicapi (ytmusic-adapter)

Turning the ytmusicapi python library into an actual usable API.

A stateless FastAPI service that exposes [ytmusicapi](https://github.com/sigma67/ytmusicapi)
(pinned `1.12.2`) as a read-only JSON API for search and detail lookups: songs, videos, albums,
artists, and playlists. Built to be consumed by [naviseerr](../naviseerr) for artist/album/playlist
search, where Last.fm's metadata is thin (no playlists, empty `mbid`s, hardcoded years).

Everything here works **anonymously** — no OAuth, no cookies, no credentials. That is a deliberate
constraint: the moment library/account data is needed, auth becomes mandatory and the
"stateless, no-secrets" property is gone.

## Running locally

```bash
uv sync --group dev
uv run uvicorn app.main:app --reload
```

Then open `http://localhost:8000/docs` for the generated OpenAPI spec.

## Endpoints

All `GET`, read-only, prefix `/v1`.

| Route | Notes |
|---|---|
| `/v1/search?q=&type=&limit=` | `type` ∈ `songs,videos,albums,artists,playlists`. Omit for mixed search. `limit` is enforced as an exact ceiling (ytmusicapi's own `limit` is a floor). Playlist items carry their author as `artists[0]`. `trackCount` is populated only when YouTube's row subtitle shows "N songs" (rare — most rows show views instead, so it is usually null) and is a floor for capped rows (`"5,000+"` → 5000); use `/v1/playlists/{playlistId}.trackCount` for a reliable count. |
| `/v1/search/songs`, `/albums`, `/artists`, `/playlists` | typed sugar routes |
| `/v1/albums/{browseId}` | `browseId` = `MPREb_…` |
| `/v1/albums/by-audio-playlist/{audioPlaylistId}` | resolves an `OLAK5uy_…` id to its album, in one call |
| `/v1/artists/{channelId}` | `channelId` = `UC…`. The response echoes the id you requested — ytmusicapi's `get_artist()` returns a *different* `channelId` internally, which this API does not leak. |
| `/v1/artists/{channelId}/albums?limit=&order=` | two upstream calls under the hood (`get_artist` to resolve `params`, then `get_artist_albums`) |
| `/v1/playlists/{playlistId}?limit=` | accepts both bare ids and `VL`-prefixed ids (as returned by search) |
| `/v1/songs/{videoId}` | metadata only — `streamingData`/`playabilityStatus` are never read or returned. No playback/streaming path is exposed by this service. |
| `/v1/songs/{videoId}/details` | the song page: artists with ids, album, year, exact duration/view count, per-track `explicit`, and `credits[{role, names}]` (performed/written/produced by, label). Up to four upstream calls. Official-video (`OMV`) ids have no album, year, explicit flag or credits on YouTube Music — those come back `null`/`[]`, not as an error. 404 only when the video itself is unknown. |
| `/health` | liveness, no upstream call |
| `/health/ready` | readiness — does a cheap `search("test", limit=1)`, cached for `YTM_READY_CACHE_SECONDS` (default 60s) so probes can't turn into steady load against YouTube |

## Configuration (env vars, no secrets committed)

| Var | Default | Notes |
|---|---|---|
| `YTM_LANGUAGE` | `en` | one of the 16 ytmusicapi-supported values |
| `YTM_LOCATION` | *(empty)* | 2-letter country code; empty lets the server decide |
| `YTM_TIMEOUT_SECONDS` | `10` | per-request timeout (ytmusicapi's own default is 30s) |
| `YTM_MAX_CONCURRENCY` | `8` | semaphore bound on concurrent upstream calls |
| `YTM_READY_CACHE_SECONDS` | `60` | `/health/ready` result cache |
| `YTM_LOG_LEVEL` | `INFO` | |
| `YTM_PROXY_URL` | unset | **dormant fallback.** Set if anonymous requests start getting blocked (datacenter-IP flagging is a real risk — see Caveats). Passed straight to `requests`. |
| `YTM_AUTH_FILE` | unset | **dormant fallback.** Path to a `browser.json`/`oauth.json` for cookie/OAuth auth. Setting this breaks the stateless/no-secrets property — treat it as a last resort, not a default. |

Both fallbacks are single env vars because `YTMusic()`'s constructor already accepts `proxies=` and
`auth=` — no code change needed to flip them on.

## Error contract

Every error response is `{"error": {"code": "<slug>", "message": "<safe text>"}}`.

| Situation | Status |
|---|---|
| Bad query param (unknown `type`, etc.) | 400 |
| Entity not found (unknown/deleted browseId, videoId, playlistId) | 404 |
| Upstream 400/401/403 (YouTube bot detection) or 5xx | 502 |
| Upstream 429 | 429, with `Retry-After` |
| Upstream timeout / connection failure | 504 |
| Unrecognized upstream response shape (parser drift) | 502 |

**A note on 404 vs 502 for browse pages**: `get_album`/`get_artist`/`get_playlist` don't return
`None` for an invalid id — ytmusicapi's own parser raises a bare `KeyError` because YouTube serves
a differently-shaped page for a page that doesn't exist. This adapter recognizes that specific
`KeyError` signature (missing `'contents'` key) on those three methods and maps it to 404; any
other `KeyError`/`IndexError`/`TypeError` is treated as genuine parser drift and mapped to 502. See
`app/ytmusic_client.py`.

## Testing

```bash
uv run pytest              # offline: mappers, routes, error mapping — no network
uv run pytest -m live      # opt-in: hits the real YouTube Music backend
uv run ruff check . && uv run mypy app
```

Behind corporate TLS interception the live suite fails with a certificate error. Point `requests` at
a bundle made of certifi's `cacert.pem` plus the corporate root CA (`cat "$(uv run python -m certifi)"
corp-root.pem > ca-bundle.pem`) via `REQUESTS_CA_BUNDLE=./ca-bundle.pem`; do not commit the bundle.

`tests/fixtures/` holds real recorded JSON from live calls (including a few hand-mangled variants
with missing keys) — `tests/test_mappers.py` is driven entirely by these, so mapper correctness
never depends on network access. `tests/test_contract_live.py` is what actually detects YouTube
shape drift; a failure there means "YouTube changed" or "this IP got flagged", not "the code is
wrong" — re-record the fixtures and update the mapper.

CI (`.github/workflows/ci.yml`) runs lint + offline tests on every push, and the live contract
suite on a daily schedule plus manual dispatch.

## Docker

```bash
docker build -t ytmusic-adapter:local .
docker run -p 8000:8000 ytmusic-adapter:local
```

`python:3.12-slim`, non-root user, 2 gunicorn workers (`uvicorn.workers.UvicornWorker`), a
liveness `HEALTHCHECK` hitting `/health` (no upstream call, no `curl` dependency — the base image
doesn't ship one, so the healthcheck uses Python's own `urllib`).

## Caveats

- **ytmusicapi is unofficial**, mirroring an internal YouTube Music web API that changes shape
  without notice (see the `yt-update` GitHub label on the upstream repo). Version-pinned; the live
  contract suite is the early-warning system, not a guarantee.
- **Datacenter-IP blocking is a real risk**, well corroborated across the yt-dlp/pytubefix
  ecosystem, though not stated verbatim by the ytmusicapi maintainer. If deploying off a
  residential network, expect to need `YTM_PROXY_URL` or `YTM_AUTH_FILE`.
- **Thread safety of the shared `YTMusic` instance is inferred, not documented.** Per-request state
  is passed as call arguments rather than mutated on the shared session, so concurrent reads should
  be safe — except `as_mobile()`, the library's one explicitly-documented non-thread-safe path,
  which this adapter never calls.
- **`limit` semantics**: ytmusicapi's own `limit` is a *floor* (YouTube paginates in chunks of
  20–100 and the library keeps fetching until it has at least `limit`). This adapter truncates to
  an exact ceiling before returning, so the `count` field is always honest.
