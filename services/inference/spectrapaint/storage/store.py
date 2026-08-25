"""The library: Bundles, Consultations and Renders, kept on disk.

    Bundle (renameable) -> Consultation -> Render

A single SQLite database plus the images themselves as files beside it — see storage/README.md.
The database is metadata and nothing else: a row names a PNG by its path relative to the store
directory, because Customer photographs are megabytes and a BLOB column would make every listing
read drag them through the database.

Two properties this module exists to keep:

* **Nothing is deleted automatically.** No code path here removes a Consultation or a Render row,
  and ending a session (api/sessions.py) touches only memory. Deleting a *Bundle* is the Dealer's
  explicit act, and even then its Consultations move to the default Bundle rather than going with
  it.
* **Reopening replays what was stored, never a regeneration.** The render PNG written at render
  time is byte-for-byte what reopening serves.

Writes go through short explicit transactions (the catalogue/database.py pattern); reads are plain
queries. ``check_same_thread`` is off because FastAPI runs synchronous endpoints in a worker thread
pool — safe for the same reason as the Catalogue database, and safer still with WAL mode, which
lets a read run while a write commits.
"""

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

DATABASE_FILENAME = "library.sqlite3"

# Subdirectories of the store, one kind of image each. Named for what they hold, not how they are
# encoded — every image in all three is a lossless PNG.
_PHOTO_DIR = "photos"
_MATTE_DIR = "mattes"
_RENDER_DIR = "renders"

# The Bundle every Consultation belongs to until the Dealer says otherwise, and the one a deleted
# Bundle's Consultations fall back to. Created lazily, so an empty library has no rows at all.
DEFAULT_BUNDLE_NAME = "Consultations"

_CREATE_BUNDLES = """
CREATE TABLE IF NOT EXISTS bundles (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_CONSULTATIONS = """
CREATE TABLE IF NOT EXISTS consultations (
    id           TEXT PRIMARY KEY,
    bundle_id    TEXT NOT NULL REFERENCES bundles(id),
    original_path TEXT NOT NULL,
    photo_path   TEXT,
    planes_json  TEXT,
    created_at   TEXT NOT NULL
)
"""

_CREATE_RENDERS = """
CREATE TABLE IF NOT EXISTS renders (
    id                TEXT PRIMARY KEY,
    consultation_id   TEXT NOT NULL REFERENCES consultations(id),
    created_at        TEXT NOT NULL,
    execution_profile TEXT NOT NULL,
    mode              TEXT NOT NULL,
    assignments_json  TEXT NOT NULL,
    resolved_lab_json TEXT NOT NULL,
    catalogue_id      TEXT NOT NULL,
    catalogue_name    TEXT NOT NULL,
    catalogue_version TEXT NOT NULL,
    png_path          TEXT NOT NULL,
    width             INTEGER NOT NULL,
    height            INTEGER NOT NULL
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS consultations_by_bundle ON consultations (bundle_id)",
    "CREATE INDEX IF NOT EXISTS renders_by_consultation ON renders (consultation_id)",
)


def _now() -> str:
    """One timestamp format everywhere, always UTC, so listings sort honestly."""
    return datetime.now(UTC).isoformat()


class Store:
    """The on-disk library. One per process; built once at launch."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _PHOTO_DIR).mkdir(exist_ok=True)
        (directory / _MATTE_DIR).mkdir(exist_ok=True)
        (directory / _RENDER_DIR).mkdir(exist_ok=True)

        self._connection = sqlite3.connect(directory / DATABASE_FILENAME, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        # WAL lets a render being saved and a list being browsed happen at once, which a
        # counter-side app does constantly: save one render, show the previous one.
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self._connection:
            self._connection.execute(_CREATE_BUNDLES)
            self._connection.execute(_CREATE_CONSULTATIONS)
            self._connection.execute(_CREATE_RENDERS)
            for statement in _CREATE_INDEXES:
                self._connection.execute(statement)
        self._ensure_bundles_schema()

    # -- bundles -------------------------------------------------------------------------------

    def _ensure_bundles_schema(self) -> None:
        """Migrate existing databases to the is_default column (review item #4)."""
        columns = {
            row["name"] for row in self._connection.execute("PRAGMA table_info(bundles)").fetchall()
        }
        if "is_default" not in columns:
            with self._lock, self._connection:
                self._connection.execute(
                    "ALTER TABLE bundles ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0"
                )
                # Backfill: the oldest bundle named Consultations becomes the default.
                # If the default was renamed under the old name-matching code, no row
                # matches the name — fall back to the oldest bundle overall, which is
                # the renamed default (reproduced in review: Renamed by dealer + Sharma house).
                cursor = self._connection.execute(
                    """
                    UPDATE bundles SET is_default = 1 WHERE id = (
                        SELECT id FROM bundles WHERE name = ? ORDER BY created_at LIMIT 1
                    )
                    """,
                    (DEFAULT_BUNDLE_NAME,),
                )
                if cursor.rowcount == 0:
                    self._connection.execute(
                        """
                        UPDATE bundles SET is_default = 1 WHERE id = (
                            SELECT id FROM bundles ORDER BY created_at LIMIT 1
                        ) AND NOT EXISTS (SELECT 1 FROM bundles WHERE is_default = 1)
                        """
                    )

    def create_bundle(self, name: str, *, is_default: bool = False) -> dict:
        bundle_id = f"bundle_{os.urandom(12).hex()}"
        created_at = _now()
        is_default_int = 1 if is_default else 0
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO bundles (id, name, created_at, is_default) VALUES (?, ?, ?, ?)",
                (bundle_id, name, created_at, is_default_int),
            )
        return {
            "bundle_id": bundle_id,
            "name": name,
            "created_at": created_at,
            "is_default": is_default_int,
        }

    def rename_bundle(self, bundle_id: str, name: str) -> bool:
        if self.is_default_bundle(bundle_id):
            return False
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE bundles SET name = ? WHERE id = ?", (name, bundle_id)
            )
        return cursor.rowcount > 0

    def delete_bundle(self, bundle_id: str) -> bool:
        """Remove one Bundle. Its Consultations move to the default Bundle — deleting a grouping
        is not deciding that the work inside it stops existing."""

        if not self._bundle_exists(bundle_id):
            return False

        if self.is_default_bundle(bundle_id):
            return False

        default_id = self._default_bundle_id()

        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE consultations SET bundle_id = ? WHERE bundle_id = ?",
                (default_id, bundle_id),
            )
            self._connection.execute("DELETE FROM bundles WHERE id = ?", (bundle_id,))
        return True

    def list_bundles(self) -> list[dict]:
        self._default_bundle_id()
        with self._lock:
            rows = self._connection.execute(
                "SELECT b.id AS bundle_id, b.name, b.created_at, b.is_default, "
                "(SELECT count(*) FROM consultations c WHERE c.bundle_id = b.id) "
                "AS consultation_count FROM bundles b ORDER BY b.created_at"
            ).fetchall()
            return [dict(row) for row in rows]

    def _bundle_exists(self, bundle_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM bundles WHERE id = ?", (bundle_id,)
            ).fetchone()
            return row is not None

    def is_default_bundle(self, bundle_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT is_default FROM bundles WHERE id = ?", (bundle_id,)
            ).fetchone()
            return bool(row and row["is_default"])

    def _default_bundle_id(self) -> str:
        """The default Bundle's id, creating it if this is the first ask."""
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM bundles WHERE is_default = 1 ORDER BY created_at LIMIT 1",
            ).fetchone()
            if row is not None:
                return str(row["id"])
            # Fallback for databases predating is_default: look up by legacy name.
            legacy = self._connection.execute(
                "SELECT id FROM bundles WHERE name = ? ORDER BY created_at LIMIT 1",
                (DEFAULT_BUNDLE_NAME,),
            ).fetchone()
            if legacy is not None:
                with self._connection:
                    self._connection.execute(
                        "UPDATE bundles SET is_default = 1 WHERE id = ?", (str(legacy["id"]),)
                    )
                return str(legacy["id"])
            return str(self.create_bundle(DEFAULT_BUNDLE_NAME, is_default=True)["bundle_id"])

    def require_bundle(self, bundle_id: str) -> bool:
        return self._bundle_exists(bundle_id)

    # -- consultations -------------------------------------------------------------------------

    def register_consultation(self, consultation_id: str, original_photo: bytes) -> None:
        """A Consultation starts the moment a photo is uploaded — before any render exists — so
        walking away mid-consultation cannot lose the Room Photo."""
        relative = f"{_PHOTO_DIR}/{consultation_id}.orig"
        self._write_bytes(relative, original_photo)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO consultations (id, bundle_id, original_path, created_at)"
                " VALUES (?, ?, ?, ?)",
                (consultation_id, self._default_bundle_id(), relative, _now()),
            )

    def save_preparation(
        self, consultation_id: str, photo_png: bytes, mattes: list[tuple[str, bytes]]
    ) -> None:
        """Record what preparation produced, as the images reopening will load.

        The photo is stored at preview scale — the scale every render so far has been made at —
        and one Alpha Matte per Wall Plane. Together they are everything "try another Shade"
        needs, which is why a reopened Consultation skips preparation entirely.
        """

        photo_relative = f"{_PHOTO_DIR}/{consultation_id}.png"
        self._write_bytes(photo_relative, photo_png)

        planes = []
        for plane_id, matte_png in mattes:
            relative = f"{_MATTE_DIR}/{consultation_id}_{plane_id}.png"
            self._write_bytes(relative, matte_png)
            planes.append({"plane_id": plane_id, "matte_path": relative})

        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE consultations SET photo_path = ?, planes_json = ? WHERE id = ?",
                (photo_relative, json.dumps(planes), consultation_id),
            )

    def preparation_of(self, consultation_id: str) -> tuple[bytes, list[tuple[str, bytes]]] | None:
        """The stored photo and Alpha Mattes, or None when this Consultation was never prepared
        (its session ended before preparation finished)."""
        with self._lock:
            row = self._connection.execute(
                "SELECT photo_path, planes_json FROM consultations WHERE id = ?", (consultation_id,)
            ).fetchone()
            if row is None or row["photo_path"] is None or row["planes_json"] is None:
                return None

            photo = self._read_bytes(str(row["photo_path"]))
            if photo is None:
                return None

            planes: list[tuple[str, bytes]] = []
            for plane in json.loads(row["planes_json"]):
                matte = self._read_bytes(str(plane["matte_path"]))
                if matte is None:
                    return None
                planes.append((str(plane["plane_id"]), matte))
            return photo, planes

    def consultation_exists(self, consultation_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM consultations WHERE id = ?", (consultation_id,)
            ).fetchone()
            return row is not None

    def place_consultation_in_bundle(self, consultation_id: str, bundle_id: str) -> None:
        """File one Consultation under one Bundle — how a job's photos travel together."""

        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE consultations SET bundle_id = ? WHERE id = ?",
                (bundle_id, consultation_id),
            )

    def list_consultations(self, bundle_id: str) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT c.id AS consultation_id, c.created_at,"
                " (SELECT count(*) FROM renders r WHERE r.consultation_id = c.id) AS render_count"
                " FROM consultations c WHERE c.bundle_id = ? ORDER BY c.created_at DESC",
                (bundle_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # -- renders ---------------------------------------------------------------------------------

    def save_render(
        self,
        *,
        consultation_id: str,
        png: bytes,
        width: int,
        height: int,
        execution_profile: str,
        mode: str,
        assignments: dict[str, str],
        resolved_lab: dict[str, list[float]],
        catalogue_id: str,
        catalogue_name: str,
        catalogue_version: str,
    ) -> str:
        """One repaint, kept whole: the pixels and everything needed to say later what produced
        them. The identity stamp matters because a shade code alone cannot survive a Catalogue
        changing underneath it (docs/design-decisions.md §7)."""

        render_id = os.urandom(16).hex()
        relative = f"{_RENDER_DIR}/{render_id}.png"
        self._write_bytes(relative, png)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO renders ("
                " id, consultation_id, created_at, execution_profile, mode,"
                " assignments_json, resolved_lab_json,"
                " catalogue_id, catalogue_name, catalogue_version, png_path, width, height"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    render_id,
                    consultation_id,
                    _now(),
                    execution_profile,
                    mode,
                    json.dumps(assignments),
                    json.dumps(resolved_lab),
                    catalogue_id,
                    catalogue_name,
                    catalogue_version,
                    relative,
                    width,
                    height,
                ),
            )
        return render_id

    def list_renders(self, consultation_id: str) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id AS render_id, created_at, execution_profile, mode,"
                " assignments_json, resolved_lab_json,"
                " catalogue_id, catalogue_name, catalogue_version, width, height"
                " FROM renders WHERE consultation_id = ? ORDER BY created_at",
                (consultation_id,),
            ).fetchall()
            results = []
            for row in rows:
                entry = dict(row)
                entry["assignments"] = json.loads(entry.pop("assignments_json"))
                entry["resolved_lab"] = json.loads(entry.pop("resolved_lab_json"))
                results.append(entry)
            return results

    def render_png(self, render_id: str) -> bytes | None:
        """The stored render, exactly the bytes that were written — never re-encoded."""
        with self._lock:
            row = self._connection.execute(
                "SELECT png_path FROM renders WHERE id = ?", (render_id,)
            ).fetchone()
            if row is None:
                return None
            return self._read_bytes(str(row["png_path"]))

    def render_consultation(self, render_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT consultation_id FROM renders WHERE id = ?", (render_id,)
            ).fetchone()
            return None if row is None else str(row["consultation_id"])

    # -- image plumbing --------------------------------------------------------------------------

    def _write_bytes(self, relative_path: str, contents: bytes) -> None:
        path = self.directory / relative_path
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(contents)
        os.replace(temporary, path)

    def _read_bytes(self, relative_path: str) -> bytes | None:
        path = self.directory / relative_path
        if not path.is_file():
            return None
        return path.read_bytes()
