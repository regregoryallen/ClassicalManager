"""Copy a whole library between database backends.

Deliberately not a JSON export/import round trip. export_library() is a
curation backup: it drops every TrackAnalysis, the file mtime/size that
incremental scanning depends on, and half a dozen Track columns. Migrating
through it would silently cost the librosa analysis and force a full
rescan.

This copies table by table, preserving primary keys, so foreign keys stay
valid without remapping and the target is row-for-row the source. Reads go
through raw SQL rather than the ORM so values move across untranslated —
the point is fidelity, not interpretation.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import peewee as pw

from music_manager.core.database import (
    Album, Composer, Library, Override, PlaylistProfile, ProfileSelection,
    SourceFolder, Track, Work, _ensure_track_indexes, _make_database, database,
)

logger = logging.getLogger(__name__)

# Parents before children, so foreign keys resolve as rows land and the
# constraints stay switched on to catch a genuinely broken source.
def _ordered_models():
    from music_manager.core.similarity import AnalysisSnapshot, TrackAnalysis
    return [Library, SourceFolder, Composer, Album, Work, Track,
            PlaylistProfile, ProfileSelection, Override,
            TrackAnalysis, AnalysisSnapshot]


# Rows per INSERT. The server's max_allowed_packet is 16 MB; the widest row
# here is a TrackAnalysis at ~630 bytes of JSON, so 500 rows is ~0.3 MB —
# two orders of magnitude of headroom.
BATCH_ROWS = 500


@dataclass
class TableResult:
    table: str
    source_rows: int = 0
    copied: int = 0
    target_rows: int = 0
    verified: bool | None = None
    mismatch: str = ""


@dataclass
class MigrationReport:
    source: str = ""
    target: str = ""
    dry_run: bool = False
    tables: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and all(
            t.verified is not False for t in self.tables)

    @property
    def total_rows(self) -> int:
        return sum(t.copied for t in self.tables)


def _quoted(db, name):
    """Identifier quoting differs per backend: "col" on SQLite, `col` on
    MySQL. db.quote is a two-character open/close pair."""
    return f"{db.quote[0]}{name}{db.quote[1]}"


def _columns(model):
    """Physical column names, in a fixed order for both read and write."""
    return [f.column_name for f in model._meta.sorted_fields]


def _count(db, table):
    return db.execute_sql(f"SELECT COUNT(*) FROM {_quoted(db, table)}").fetchone()[0]


def _read_rows(db, model):
    """Every row, oldest id first, as plain tuples."""
    cols = ", ".join(_quoted(db, c) for c in _columns(model))
    table = _quoted(db, model._meta.table_name)
    pk = _quoted(db, model._meta.primary_key.column_name)
    return db.execute_sql(f"SELECT {cols} FROM {table} ORDER BY {pk}").fetchall()


def _insert_rows(db, model, rows):
    """Insert preserving primary keys, in batches."""
    if not rows:
        return 0
    columns = _columns(model)
    cols = ", ".join(_quoted(db, c) for c in columns)
    table = _quoted(db, model._meta.table_name)
    placeholder = ", ".join([db.param] * len(columns))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholder})"
    written = 0
    for start in range(0, len(rows), BATCH_ROWS):
        batch = rows[start:start + BATCH_ROWS]
        db.cursor().executemany(sql, batch)
        written += len(batch)
    return written


def _as_utc_naive(moment: datetime) -> datetime:
    """Compare timestamps as instants, not as spellings.

    Every timestamp here is written as datetime.now(timezone.utc), and
    SQLite keeps that as text carrying "+00:00". MySQL's DATETIME has no
    timezone, so the same instant comes back naive. Sub-second precision
    also goes, DATETIME storing whole seconds.
    """
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.replace(microsecond=0)


def _normalize(value):
    """Make a value comparable across backends.

    Only differences in representation are smoothed out — a value that
    actually changed must still register, which is how the FLOAT-precision
    loss in file_mtime was caught.
    """
    if isinstance(value, datetime):
        return _as_utc_naive(value).isoformat(sep=" ")
    if isinstance(value, str):
        # A datetime that SQLite stored as text.
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return _as_utc_naive(parsed).isoformat(sep=" ")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _checksum(rows):
    """Content hash over normalized values, so a corrupted charset or a
    dropped column shows up as a mismatch rather than a matching count."""
    digest = hashlib.sha256()
    for row in rows:
        digest.update(repr(tuple(_normalize(v) for v in row)).encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def _first_difference(source_rows, target_rows, model):
    """Locate the first differing row, for an error message worth reading."""
    columns = _columns(model)
    for index, (a, b) in enumerate(zip(source_rows, target_rows)):
        na = tuple(_normalize(v) for v in a)
        nb = tuple(_normalize(v) for v in b)
        if na != nb:
            for col, va, vb in zip(columns, na, nb):
                if va != vb:
                    return (f"row {index + 1}, column {col!r}: "
                            f"source {va!r} != target {vb!r}")
    if len(source_rows) != len(target_rows):
        return f"row count {len(source_rows)} != {len(target_rows)}"
    return ""


def migrate_database(source_settings, target_settings, *, dry_run=False,
                     force=False, progress=None) -> MigrationReport:
    """Copy every table from source to target.

    The source is only ever read. The target must be empty unless force is
    set, since overwriting someone's database is not a thing to do quietly.
    """
    report = MigrationReport(source=source_settings.describe(),
                             target=target_settings.describe(),
                             dry_run=dry_run)

    def say(message):
        logger.info("%s", message)
        if progress:
            progress(message)

    source_db = _make_database(source_settings)
    source_db.connect()
    target_db = _make_database(target_settings)
    target_db.connect()

    models = _ordered_models()
    try:
        # Point the ORM at the target so create_tables and the index helpers
        # build the schema there. The source is touched only by raw SELECTs.
        database.initialize(target_db)
        if not dry_run:
            target_db.create_tables(models)
            from music_manager.core.similarity import ensure_table
            ensure_table()

        existing = {}
        for model in models:
            table = model._meta.table_name
            try:
                existing[table] = _count(target_db, table)
            except Exception:
                existing[table] = 0
        occupied = {t: n for t, n in existing.items() if n}
        if occupied and not force:
            report.error = (
                "Target already contains data: "
                + ", ".join(f"{t}={n}" for t, n in sorted(occupied.items()))
                + ". Refusing to write into it. Use --force to overwrite, "
                  "which DELETES those rows first.")
            return report

        for model in models:
            table = model._meta.table_name
            result = TableResult(table=table)
            try:
                result.source_rows = _count(source_db, table)
            except Exception as exc:
                # A table the source predates (e.g. no analysis yet).
                logger.info("Source has no %s (%s); skipping", table, exc)
                report.tables.append(result)
                continue

            if dry_run:
                result.target_rows = existing.get(table, 0)
                report.tables.append(result)
                say(f"would copy {result.source_rows:>6} rows -> {table}")
                continue

            rows = _read_rows(source_db, model)
            with target_db.atomic():
                if force and existing.get(table):
                    target_db.execute_sql(
                        f"DELETE FROM {_quoted(target_db, table)}")
                result.copied = _insert_rows(target_db, model, rows)
            result.target_rows = _count(target_db, table)
            say(f"copied {result.copied:>6} rows -> {table}")

            # Verify by re-reading the target, so a value mangled on the way
            # in (a charset mismatch is the obvious one) is caught here and
            # not months later.
            written = _read_rows(target_db, model)
            if _checksum(rows) == _checksum(written):
                result.verified = True
            else:
                result.verified = False
                result.mismatch = _first_difference(rows, written, model)
                logger.error("Verification failed for %s: %s",
                             table, result.mismatch)
            report.tables.append(result)

        return report
    finally:
        for db in (source_db, target_db):
            if not db.is_closed():
                db.close()
