from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_ytmusic
from app.mappers import map_search_items
from app.models.search import SearchResponse
from app.ytmusic_client import YTMusicClient

router = APIRouter(prefix="/v1/search", tags=["search"])

# Public `type` values -> ytmusicapi `filter` values. `scope` is never exposed:
# uploads/library require auth and are out of scope for this anonymous adapter.
_TYPE_TO_FILTER = {
    "songs": "songs",
    "videos": "videos",
    "albums": "albums",
    "artists": "artists",
    "playlists": "community_playlists",
    # YouTube Music's own editorial playlists (RDCLAK5uy_... ids) -- the ones an artist is
    # *featured in*, as opposed to user-made playlists named after the artist.
    "featured_playlists": "featured_playlists",
}


def _do_search(client: YTMusicClient, q: str, filter_: str | None, limit: int) -> SearchResponse:
    # ytmusicapi's `limit` is a floor (it keeps paginating until it has at least this many);
    # we truncate to `limit` so callers get an exact, predictable count.
    raw = client.call("search", q, filter=filter_, limit=limit)
    items = map_search_items(raw, limit=limit)
    return SearchResponse(query=q, type=filter_, count=len(items), items=items)


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    type: str | None = Query(None, description="One of: " + ", ".join(_TYPE_TO_FILTER)),
    limit: int = Query(20, ge=1, le=100),
    client: YTMusicClient = Depends(get_ytmusic),
) -> SearchResponse:
    filter_: str | None = None
    if type is not None:
        if type not in _TYPE_TO_FILTER:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported type '{type}'. Must be one of: {', '.join(_TYPE_TO_FILTER)}",
            )
        filter_ = _TYPE_TO_FILTER[type]
    return _do_search(client, q, filter_, limit)


def _typed_search(type_key: str):
    def handler(
        q: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=100),
        client: YTMusicClient = Depends(get_ytmusic),
    ) -> SearchResponse:
        return _do_search(client, q, _TYPE_TO_FILTER[type_key], limit)

    return handler


router.add_api_route("/songs", _typed_search("songs"), methods=["GET"], response_model=SearchResponse)
router.add_api_route("/albums", _typed_search("albums"), methods=["GET"], response_model=SearchResponse)
router.add_api_route("/artists", _typed_search("artists"), methods=["GET"], response_model=SearchResponse)
router.add_api_route("/playlists", _typed_search("playlists"), methods=["GET"], response_model=SearchResponse)
router.add_api_route(
    "/featured_playlists", _typed_search("featured_playlists"), methods=["GET"], response_model=SearchResponse
)
