"""Shared Postgres state with atomic manager updates; local JSON remains supported."""
import json
import os
import threading
import time
import zlib
import hashlib
import contextvars
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

_connection = ContextVar("planner_database_connection", default=None)
_writing = ContextVar("planner_database_write", default=False)
_versions = {}
# Saved journeys are stored one row per journey ("ship/<id>"), so a manager action
# writes only the journey it changed instead of every journey's route geometry.
SHIP_PREFIX = "ship/"
SHIPS_MIGRATED = "ships.migrated"
_ship_digests = {}  # row name -> digest of the JSON last read or written for it
# Reuse database connections inside a warm server instance. Opening a new TLS
# connection to a remote Postgres costs hundreds of milliseconds, and one page
# view triggers several requests; this was the main cause of slow hosted pages.
_pool = []
_pool_lock = threading.Lock()
POOL_SIZE = 4
IDLE_CHECK_SECONDS = 30


class StorageUnavailable(RuntimeError):
    pass


def database_url():
    supabase_url = os.environ.get("DACHSER_POSTGRES_URL")
    if not supabase_url:
        return os.environ.get("DATABASE_URL")
    url = urlsplit(supabase_url)
    # Supabase's Marketplace adds a client-specific tag that libpq rejects.
    parameters = [(key, value) for key, value in parse_qsl(url.query, keep_blank_values=True) if key != "supa"]
    return url._replace(query=urlencode(parameters)).geturl()


def configured():
    return bool(database_url())

def writing():
    return _writing.get()


def document_key(path):
    root = Path(os.environ.get("STORE_DIR", "store")).resolve()
    return str(Path(path).resolve().relative_to(root)).replace("\\", "/")


@lru_cache(maxsize=1)
def initialize(url):
    import psycopg
    try:
        with psycopg.connect(url, connect_timeout=15, prepare_threshold=None) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS dachser_state (name text PRIMARY KEY, payload bytea NOT NULL, version bigint NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now())")
    except psycopg.Error:
        raise StorageUnavailable("Shared storage could not be reached. Please try again.") from None


def _acquire(url):
    """An idle pooled connection (checked if it sat unused for a while), else a new one."""
    import psycopg
    while True:
        with _pool_lock:
            item = _pool.pop() if _pool else None
        if item is None:
            return psycopg.connect(url, connect_timeout=15, prepare_threshold=None), False
        connection, idle_since = item
        if connection.closed or connection.broken:
            continue
        if time.monotonic() - idle_since > IDLE_CHECK_SECONDS:
            try:
                connection.execute("SELECT 1")
                connection.rollback()
            except psycopg.Error:
                connection.close()
                continue
        return connection, True


def reset_pool():
    """Drop every pooled connection, e.g. after the database closed them."""
    with _pool_lock:
        items, _pool[:] = list(_pool), []
    for connection, _ in items:
        try:
            connection.close()
        except Exception:
            pass


def _release(connection, reusable):
    import psycopg.pq
    if reusable and not connection.closed and not connection.broken and connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
        with _pool_lock:
            if len(_pool) < POOL_SIZE:
                _pool.append((connection, time.monotonic()))
                return
    try:
        connection.close()
    except Exception:
        pass


@contextmanager
def session(write=False):
    if not configured() or _connection.get() is not None:
        yield
        return
    import psycopg
    url = database_url()
    initialize(url)
    try:
        connection, pooled = _acquire(url)
        if write:
            try:
                # Serializes approvals and capacity reservations across server instances.
                connection.execute("SELECT pg_advisory_xact_lock(684918257)")
            except psycopg.OperationalError:
                if not pooled:
                    raise
                # The database dropped this idle connection; start again on a fresh one.
                connection.close()
                reset_pool()
                connection, pooled = _acquire(url)
                connection.execute("SELECT pg_advisory_xact_lock(684918257)")
        reusable = False
        token = _connection.set(connection)
        write_token = _writing.set(write)
        try:
            yield
            # Commit explicitly; commit() raises if the connection was lost, so a
            # save that never happened is never reported as successful.
            connection.commit()
            reusable = True
        except BaseException:
            # A rolled-back request may already have changed the worker's
            # in-memory objects; force their next read back from Postgres.
            _forget()
            try:
                if not connection.closed:
                    connection.rollback()
                    reusable = True
            except psycopg.Error:
                reusable = False
            raise
        finally:
            _writing.reset(write_token)
            _connection.reset(token)
            _release(connection, reusable)
    except psycopg.Error:
        # The failure may come from the commit itself, after save() already
        # recorded a version that never landed. Forget every cached version so
        # the next read reloads committed state instead of trusting memory.
        _forget()
        raise StorageUnavailable("Shared storage could not complete this request. No successful save was confirmed; please try again.") from None


def _forget():
    _versions.clear()
    _ship_digests.clear()


def encode(value):
    # Route geometries repeat across comparison snapshots. Compressing them keeps
    # the existing prototype records small without discarding approved evidence.
    return zlib.compress(json.dumps(value, separators=(",", ":"), default=str).encode(), 6)


def load(key, fallback, force=False):
    if not configured(): return fallback if force else None
    with session():
        connection = _connection.get()
        row = connection.execute("SELECT version FROM dachser_state WHERE name=%s", (key,)).fetchone()
        if row is None:
            connection.execute("INSERT INTO dachser_state(name,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING", (key, encode(fallback)))
            row = connection.execute("SELECT version FROM dachser_state WHERE name=%s", (key,)).fetchone()
        if not force and _versions.get(key) == row[0]: return None
        payload, version = connection.execute(
            "SELECT payload,version FROM dachser_state WHERE name=%s", (key,), binary=True
        ).fetchone()
        _versions[key] = version
        return json.loads(zlib.decompress(bytes(payload)))


# Keys whose version this request already checked (set by the API middleware), so
# later code in the same request does not ask the database again.
refreshed = contextvars.ContextVar("refreshed", default=frozenset())


def load_many(fallbacks, prefix=None):
    """Like load() for several keys, in one round trip when nothing changed.

    Returns {key: payload} only for keys whose stored version differs from the one
    this worker last read (all keys on the first call)."""
    if not configured(): return {}
    keys = list(fallbacks)
    with session():
        connection = _connection.get()
        if prefix:
            # Fixed keys and every row of the collection in the same round trip.
            versions = dict(connection.execute("SELECT name,version FROM dachser_state WHERE name = ANY(%s) OR name LIKE %s", (keys, prefix + "%")).fetchall())
        else:
            versions = dict(connection.execute("SELECT name,version FROM dachser_state WHERE name = ANY(%s)", (keys,)).fetchall())
        present = {name for name in versions if prefix and name.startswith(prefix)}
        for key in keys:
            if key not in versions:
                connection.execute("INSERT INTO dachser_state(name,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING", (key, encode(fallbacks[key])))
                versions[key] = None
        changed = [k for k in [*keys, *present] if versions[k] is None or _versions.get(k) != versions[k]]
        out = {}
        if changed:
            # The binary result avoids PostgreSQL hex-encoding every compressed payload.
            rows = connection.execute(
                "SELECT name,payload,version FROM dachser_state WHERE name = ANY(%s)", (changed,), binary=True
            ).fetchall()
            for name, payload, version in rows:
                _versions[name] = version
                raw = zlib.decompress(bytes(payload))
                if prefix and name.startswith(prefix):
                    _ship_digests[name] = hashlib.blake2b(raw, digest_size=16).digest()
                out[name] = json.loads(raw)
        if prefix:
            # Rows deleted by another server instance.
            for name in [n for n in _versions if n.startswith(prefix) and n not in present]:
                _versions.pop(name, None); _ship_digests.pop(name, None)
                out[name] = None
        return out


def load_ships(fallback):
    """All saved journeys, one row each. Splits the legacy single record once."""
    with session(write=True):
        connection = _connection.get()
        if connection.execute("SELECT 1 FROM dachser_state WHERE name=%s", (SHIPS_MIGRATED,)).fetchone() is None:
            row = connection.execute(
                "SELECT payload FROM dachser_state WHERE name='shipments.json'", binary=True
            ).fetchone()
            legacy = json.loads(zlib.decompress(bytes(row[0]))) if row else fallback
            for sid, ship in (legacy or {}).items():
                connection.execute("INSERT INTO dachser_state(name,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                                   (SHIP_PREFIX + sid, zlib.compress(json.dumps(ship, separators=(",", ":"), default=str).encode(), 1)))
            connection.execute("INSERT INTO dachser_state(name,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING", (SHIPS_MIGRATED, encode({"at": time.time()})))
        rows = load_many({}, prefix=SHIP_PREFIX)
        return {name[len(SHIP_PREFIX):]: ship for name, ship in rows.items() if ship is not None}


def save_ships(data):
    """Write only journeys whose content changed; delete removed ones."""
    if not configured(): return False
    with session(write=True):
        connection = _connection.get()
        present = set()
        for sid, ship in data.items():
            name = SHIP_PREFIX + sid; present.add(name)
            raw = json.dumps(ship, separators=(",", ":"), default=str).encode()
            digest = hashlib.blake2b(raw, digest_size=16).digest()
            if _ship_digests.get(name) == digest:
                continue
            row = connection.execute("INSERT INTO dachser_state(name,payload) VALUES(%s,%s) ON CONFLICT(name) DO UPDATE SET payload=EXCLUDED.payload, version=dachser_state.version+1, updated_at=now() RETURNING version",
                                     (name, zlib.compress(raw, 1))).fetchone()
            _versions[name] = row[0]; _ship_digests[name] = digest
        for name in [n for n in _versions if n.startswith(SHIP_PREFIX) and n not in present]:
            connection.execute("DELETE FROM dachser_state WHERE name=%s", (name,))
            _versions.pop(name, None); _ship_digests.pop(name, None)
    return True


def save(key, value):
    if not configured(): return False
    with session(write=True):
        row = _connection.get().execute("INSERT INTO dachser_state(name,payload) VALUES(%s,%s) ON CONFLICT(name) DO UPDATE SET payload=EXCLUDED.payload, version=dachser_state.version+1, updated_at=now() RETURNING version", (key, encode(value))).fetchone()
        _versions[key] = row[0]
    return True


def exists(key):
    with session():
        return _connection.get().execute("SELECT 1 FROM dachser_state WHERE name=%s", (key,)).fetchone() is not None
