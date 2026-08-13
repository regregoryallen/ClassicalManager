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


def render_listing(selection):
    """The selected works and their ids, for `--list`.

    CM's GUI shows work ids nowhere, so without this there is no
    practical way to name the work you are looking at for `--work-id`.
    Measures nothing, so it answers in a second on the whole library.
    """
    if not selection.jobs:
        return ["No works selected."]

    lines = [f"{'work':>7}  {'trk':>3}  {'fmt':<4}  {'source':<10}  "
             f"{'album':<34}  work"]
    for job in selection.jobs:
        suffix = job.relative_paths[0].rsplit(".", 1)[-1].lower()
        lines.append(
            f"{job.work_id:7d}  {job.size:3d}  {suffix:<4}  {job.source:<10}  "
            f"{_truncate(job.album_title, 34):<34}  "
            f"{_truncate(job.work_name, 46)}")
    lines.append("")
    lines.append(f"{len(selection.jobs)} work(s), "
                 f"{sum(j.size for j in selection.jobs)} track(s)")
    skipped = len(selection.skipped)
    if skipped:
        lines.append(f"{skipped} work(s) not selected — run without --list "
                     f"to see why")
    return lines


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
    """Works whose playback peak meets MA's limiter.

    Sorting this by absolute peak buries the only part that is a
    decision. Most exposed works are single-track, where work gain *is*
    track gain and MA already normalizes them exactly this way — they
    clip today and will clip identically after tagging. What this tool
    changes is the multi-track works, and what matters among those is the
    ones it makes worse.
    """
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

    single = [o for o in exposed if o.job.size == 1]
    if single:
        lines.append(f"  {len(single)} of those are single-track works that MA "
                     f"already normalizes this way —")
        lines.append("    they clip identically today; tagging changes "
                     "nothing for them")

    multi = [o for o in measured if o.job.size > 1]
    changed = [o for o in multi
               if abs(o.peak_dbfs - o.per_track_peak_dbfs) > 0.05]
    worse = sorted((o for o in changed if o.peak_dbfs > o.per_track_peak_dbfs),
                   key=lambda o: o.peak_dbfs - o.per_track_peak_dbfs,
                   reverse=True)
    better = [o for o in changed if o.peak_dbfs < o.per_track_peak_dbfs]

    lines.append("")
    lines.append(f"  Multi-track works, where work-scoping changes the "
                 f"answer: {len(multi)}")
    lines.append(f"    {len(better):5d} peak lower than they do today")
    lines.append(f"    {len(worse):5d} peak higher than they do today")

    # The sharpest category: under the limiter today, over it after
    # tagging. This is the only group where the tool creates a problem
    # rather than inheriting or reducing one.
    newly = [o for o in worse
             if o.per_track_peak_dbfs <= MA_LIMITER_DBFS
             and o.peak_dbfs > MA_LIMITER_DBFS]
    if newly:
        lines.append(f"    {len(newly):5d} of those are newly exposed — under "
                     f"the limiter today, over it after tagging")

    if not worse:
        return lines

    lines.append("")
    lines.append("  Made worse by work-scoping (worst first):")
    lines.append(f"  {'work':>6}  {'today':>6}  {'tagged':>7}  {'change':>7}  "
                 f"{'new?':>4}  name")
    newly_ids = {id(o) for o in newly}
    for outcome in worse[:max_rows]:
        delta = outcome.peak_dbfs - outcome.per_track_peak_dbfs
        flag = "yes" if id(outcome) in newly_ids else ""
        lines.append(
            f"  {outcome.job.work_id:6d}  {outcome.per_track_peak_dbfs:+6.1f}  "
            f"{outcome.peak_dbfs:+7.1f}  {delta:+7.1f}  {flag:>4}  "
            f"{_truncate(outcome.job.work_name, 40)}")
    if len(worse) > max_rows:
        lines.append(f"  ... and {len(worse) - max_rows} more")
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
