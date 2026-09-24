"""Small on-demand cache for the map tiles shown in the local planner."""
import os
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()
CACHE = Path(__file__).resolve().parents[2] / ".runtime" / "map-tiles"
MAX_AGE = 7 * 24 * 60 * 60
USER_AGENT = "DachserTransitPlannerHackathon/1.0 (+https://github.com/patelpalash/final-hackathon-project)"


@router.get("/api/map-tiles/{z}/{x}/{y}.png")
def map_tile(z: int, x: int, y: int, request: Request):
    if not 0 <= z <= 19 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        raise HTTPException(404, "Unknown map tile")
    tile = CACHE / str(z) / str(x) / f"{y}.png"
    headers = {"Cache-Control": f"public, max-age={MAX_AGE}"}
    if tile.is_file() and time.time() - tile.stat().st_mtime < MAX_AGE:
        return Response(tile.read_bytes(), media_type="image/png", headers=headers)

    upstream_headers = {"User-Agent": USER_AGENT}
    if request.headers.get("referer"):
        upstream_headers["Referer"] = request.headers["referer"]
    try:
        result = httpx.get(
            f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            headers=upstream_headers, timeout=8,
        )
        result.raise_for_status()
        if not result.headers.get("content-type", "").startswith("image/png"):
            raise ValueError("Map provider did not return a PNG tile")
        tile.parent.mkdir(parents=True, exist_ok=True)
        temporary = tile.with_name(f"{tile.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_bytes(result.content)
        temporary.replace(tile)
        return Response(result.content, media_type="image/png", headers=headers)
    except (httpx.HTTPError, ValueError, OSError):
        if tile.is_file():
            return Response(tile.read_bytes(), media_type="image/png", headers=headers)
        raise HTTPException(503, "Basemap tile temporarily unavailable")
