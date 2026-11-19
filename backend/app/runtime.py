"""Hosting defaults and restoration of an explicitly uploaded baseline dataset."""
import os
import tempfile
import gzip
import json
from pathlib import Path
from .persistence import configured


def configure_runtime():
    if os.environ.get("VERCEL")=="1":
        root=Path(tempfile.gettempdir())/"dachser-transit-demo"
        os.environ.setdefault("STORE_DIR",str(root/"store"))
        os.environ.setdefault("MAP_TILE_CACHE_DIR",str(root/"map-tiles"))
        os.environ.setdefault("SEED_DEMO_SHIPMENTS","0")
        restore_snapshot(Path(os.environ["STORE_DIR"]))


def restore_snapshot(target,source=None):
    source=Path(source) if source else Path(__file__).resolve().parents[2]/"data"/"hosted_snapshot.json.gz"
    if not source.is_file():return
    records=json.loads(gzip.decompress(source.read_bytes()))
    for name,record in records.items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts:raise ValueError("Invalid snapshot path")
        destination=target/relative
        if destination.exists():continue
        destination.parent.mkdir(parents=True,exist_ok=True)
        # Link a complete file atomically; a second worker must never see a
        # partially written JSON document or replace an existing warm store.
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=destination.parent,delete=False) as file:
                temporary=Path(file.name)
                json.dump(record,file,separators=(",",":"))
            os.link(temporary,destination)
        except FileExistsError:pass
        finally:
            if temporary:temporary.unlink(missing_ok=True)


def deployment_info():
    cloud=os.environ.get("VERCEL")=="1"
    manifest=Path(__file__).resolve().parents[2]/"data"/"hosted_snapshot.manifest.json"
    snapshot=json.loads(manifest.read_text(encoding="utf-8")) if cloud and manifest.exists() else None
    if configured():
        return {"hosting":"vercel" if cloud else "local","storage":"postgres","snapshot":snapshot,"message":None}
    return {"hosting":"vercel" if cloud else "local","storage":"ephemeral" if cloud else "local","snapshot":snapshot,
            "message":("Previous dataset restored. New changes may reset to that snapshot or differ across server instances; shared persistent storage is not connected." if snapshot else "Temporary hosted demo: saved journeys and scenarios may reset or differ across server instances. Use local storage for persistent prototype records.") if cloud else None}
