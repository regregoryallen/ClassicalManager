"""The run summary, in CM's existing report style.

The clipping table prints the predicted peak beside what the same
material does *untagged*, where MA measures and normalizes each track on
its own. That comparison is the point: `CM-MA-findings.md` §3 warns that
work gain "lifts quiet movements" toward MA's limiter, and it points the
wrong way. Under work gain the difference from per-track normalization is
`L_m - L_work`, which is positive only for movements *louder* than their
work's average — so work gain reduces peak exposure on quiet movements
and increases it on loud ones. Printing both figures is what stops that
being argued about again.
"""

from music_manager.loudness import db as work_db
from music_manager.loudness.gain import MA_LIMITER_DBFS

_REASON_LABELS = [
    (work_db.SKIP_PROVENANCE, "grouping not trusted"),
    (work_db.SKIP_FORMAT, "unsupported format"),
    (work_db.SKIP_MIXED, "mixed formats in one work"),
    (work_db.SKIP_MISSING, "file missing"),
]


def _truncate(text, width):
    return text if len(text) <= width else text[:width - 1] + "…"


def render(result, verbose=False, max_rows=20):
    """Build the summary as a list of lines."""
    selection = result.selection
    lines = ["", "--- ReplayGain Report ---"]

    if result.interrupted:
        lines.append("INTERRUPTED — this is a partial run.")
        if result.unprocessed:
            lines.append(f"  {result.unprocessed} selected work(s) were "
                         f"never started.")
        if result.wrote:
            lines.append("  Works already written are complete and will be "
                         "skipped on the next run.")
        lines.append("")

    considered = len(selection.jobs) + len(selection.skipped)
    lines.append(f"Works considered:   {considered}")
    lines.append(f"Works selected:     {len(selection.jobs)}")

    for reason, label in _REASON_LABELS:
        rows = selection.skipped_by(reason)
        if rows:
            lines.append(f"  skipped, {label}: {len(rows)}")

    current = result.already_current
    if current:
        lines.append(f"  skipped, already current: {len(current)}")

    lines.append(f"Works tagged:       {len(result.tagged)}")
    lines.append(f"Tracks written:     {result.tracks_written}")
    if not result.wrote:
        lines.append("  (dry run — nothing was written; pass --write)")

    failures = result.failed
    if failures:
        lines.append("")
        lines.append(f"Failed, not tagged: {len(failures)}")
        for outcome in failures[:max_rows]:
            lines.append(f"  work {outcome.job.work_id}: "
                         f"{_truncate(outcome.job.work_name, 48)}")
            lines.append(f"    {outcome.error}")
            if outcome.partial:
                # A work half-written is the one state this tool must
                # never leave behind quietly.
                lines.append(f"    ⚠ {len(outcome.partial)} member(s) were "
                             f"already written before this failed:")
                for path in outcome.partial:
                    lines.append(f"      {path}")
        if len(failures) > max_rows:
            lines.append(f"  ... and {len(failures) - max_rows} more")

    lines.extend(_clipping_section(result, max_rows))

    if verbose:
        lines.extend(_provenance_detail(selection, max_rows))

    return lines


def _clipping_section(result, max_rows):
    """Works whose playback peak meets MA's limiter."""
    measured = [o for o in result.outcomes if o.measurement is not None]
    if not measured:
        return []

    exposed = result.exposed
    lines = ["",
             f"Predicted clipping at MA target {result.ma_target:g} LUFS "
             f"(limiter {MA_LIMITER_DBFS:g} dBFS):",
             f"  {len(exposed)} of {len(measured)} measured work(s) exposed"]
    if not exposed:
        return lines

    # Only multi-track works can differ: a standalone work's gain *is*
    # its track gain, so work-scoped and per-track are the same number.
    multi = [o for o in exposed if o.job.size > 1]
    better = sum(1 for o in multi if o.peak_dbfs < o.per_track_peak_dbfs - 0.05)
    worse = sum(1 for o in multi if o.peak_dbfs > o.per_track_peak_dbfs + 0.05)
    if multi:
        lines.append(
            f"  of the {len(multi)} multi-track work(s) among them, "
            f"{better} peak lower than they do today untagged and {worse} "
            f"higher — MA normalizes per track now")
        lines.append("  (single-track works are identical either way)")
    lines.append("")
    lines.append(f"  {'work':>6}  {'work-scoped':>11}  {'per-track':>9}  name")
    for outcome in exposed[:max_rows]:
        lines.append(
            f"  {outcome.job.work_id:6d}  {outcome.peak_dbfs:+10.1f}  "
            f"{outcome.per_track_peak_dbfs:+8.1f}  "
            f"{_truncate(outcome.job.work_name, 44)}")
    if len(exposed) > max_rows:
        lines.append(f"  ... and {len(exposed) - max_rows} more")
    return lines


def _provenance_detail(selection, max_rows):
    """Which works the provenance gate refused — the -v review list."""
    rows = selection.skipped_by(work_db.SKIP_PROVENANCE)
    if not rows:
        return []
    lines = ["", "Excluded by provenance (pass --include-heuristic to tag "
                 "these, after reviewing them):"]
    for row in rows[:max_rows]:
        lines.append(f"  work {row.work_id:6d}  {row.source:<10} "
                     f"{_truncate(row.work_name, 52)}")
    if len(rows) > max_rows:
        lines.append(f"  ... and {len(rows) - max_rows} more")
    return lines
