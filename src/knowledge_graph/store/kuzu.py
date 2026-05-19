"""``KGStore`` — open/close + thin write/read pass-through around a Kuzu DB.

Phase A only exposes the Origin-side surface: ``snapshot_file`` and
``source_at``. Phase C will extend this class with Node/Edge writers; the
public ``open`` constructor stays stable.

Kuzu quirks worth noting:

* The python binding lazily imports ``importlib.util`` on first
  parameterised ``execute`` — that import currently fails inside some
  environments. We force the import at module load time below.
* ``Database`` paths are **directories**, not single files, despite
  ``.kuzu`` being conventional.
* Kuzu is single-writer per process; tests get their own ``tmp_path``.
"""

from __future__ import annotations

# Force-import importlib.util before kuzu touches it (binding quirk
# circa 0.11.x where ``importlib.util`` is referenced without an
# explicit import inside the prepared-statement path).
import importlib.util as _importlib_util  # noqa: F401
from pathlib import Path
from typing import Self

import kuzu

from knowledge_graph.schemas import OriginRef
from knowledge_graph.store.schema import init_schema
from knowledge_graph.store.snapshot import snapshot_file as _snapshot_file
from knowledge_graph.store.spans import source_at as _source_at


class KGStore:
    """Kuzu-backed graph store.

    Construct via :meth:`open`; call :meth:`close` (or use as a context
    manager) to release the database lock.
    """

    def __init__(self, db: kuzu.Database, conn: kuzu.Connection, path: Path) -> None:
        self._db = db
        self._conn = conn
        self._path = path

    # ----------------------------------------------------------------- ctor

    @classmethod
    def open(cls, path: str | Path) -> Self:
        """Open (or create) a Kuzu database at ``path`` and init the schema."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        db = kuzu.Database(str(p))
        conn = kuzu.Connection(db)
        init_schema(conn)
        return cls(db, conn, p)

    # ---------------------------------------------------------------- props

    @property
    def conn(self) -> kuzu.Connection:
        """Underlying Kuzu connection (tests and Phase C+ writers use this)."""
        return self._conn

    @property
    def path(self) -> Path:
        return self._path

    # -------------------------------------------------------------- origins

    def snapshot_file(
        self,
        path: str | Path,
        *,
        source: str,
        corpus: str,
        lang: str = "",
        uri: str | None = None,
    ) -> OriginRef:
        """Ingest ``path`` as an ``:Origin`` row. Idempotent on (uri, sha256)."""
        return _snapshot_file(
            self._conn,
            path,
            source=source,
            corpus=corpus,
            lang=lang,
            uri=uri,
        )

    def source_at(self, origin_id: str, start_offset: int, end_offset: int) -> bytes:
        """Return ``content[start_offset:end_offset]`` for the named origin."""
        return _source_at(self._conn, origin_id, start_offset, end_offset)

    # --------------------------------------------------------------- close

    def close(self) -> None:
        # kuzu.Connection has no explicit close in 0.11; drop refs to free
        # the in-process lock when the GC collects.
        self._conn = None  # type: ignore[assignment]
        self._db = None  # type: ignore[assignment]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["KGStore"]
