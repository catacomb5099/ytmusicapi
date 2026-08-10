import threading
import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.deps import get_ytmusic
from app.ytmusic_client import YTMusicClient

router = APIRouter(tags=["health"])

_ready_lock = threading.Lock()
_ready_cache: dict[str, float | bool] = {"ok": False, "checked_at": 0.0}


@router.get("/health")
def health() -> dict:
    """Liveness: process is up. Deliberately makes no upstream call."""
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(client: YTMusicClient = Depends(get_ytmusic)) -> dict:
    """Readiness: a cheap upstream search, cached so orchestrator probes can't turn into
    a steady stream of extra load against YouTube."""
    now = time.monotonic()
    with _ready_lock:
        age = now - _ready_cache["checked_at"]
        if age < settings.ready_cache_seconds:
            ok = bool(_ready_cache["ok"])
        else:
            try:
                client.call("search", "test", limit=1)
                ok = True
            except Exception:  # noqa: BLE001 -- any upstream failure means "not ready"
                ok = False
            _ready_cache["ok"] = ok
            _ready_cache["checked_at"] = now

    if not ok:
        raise HTTPException(status_code=503, detail="Upstream not reachable")
    return {"status": "ok"}
