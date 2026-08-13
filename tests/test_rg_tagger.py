"""v3.7: work-scoped ReplayGain — gain arithmetic, keys, and selection.

Nothing here shells out or touches audio. The tagger's decisions are all
made in pure functions precisely so they can be pinned without rsgain,
without ffmpeg and without a library.
"""

import math

import pytest

from music_manager.core.database import Album, SourceFolder, Track, Work
from music_manager.loudness import db as work_db
from music_manager.loudness import tags as tagio
from music_manager.loudness.gain import (
    GAIN_VERSION, MA_LIMITER_DBFS, REFERENCE_LUFS, clipping_prediction,
    db_to_linear, format_gain, format_peak, format_reference, gain_for,
    linear_to_db, predicted_peak_dbfs, work_key, work_peak,
)
from music_manager.loudness.measure import TrackMeasurement, WorkMeasurement


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def measurement(loudnesses, peaks=None, album_loudness=None):
    """A WorkMeasurement with the given member loudnesses.

    `album_loudness` defaults to the mean, which is *not* what R128 gives
    — tests that care about the difference pass it explicitly.
    """
    peaks = peaks or [0.5] * len(loudnesses)
    tracks = [
        TrackMeasurement(path=f"/m/{i}.flac", loudness=lufs,
                         gain=gain_for(lufs), peak=peak,
                         peak_db=linear_to_db(peak))
        for i, (lufs, peak) in enumerate(zip(loudnesses, peaks))
    ]
    album = (album_loudness if album_loudness is not None
             else sum(loudnesses) / len(loudnesses))
    return WorkMeasurement(tracks=tracks, album_loudness=album,
                           album_gain=gain_for(album),
                           album_peak=work_peak(peaks))


def make_work(lib, tmp_path, name, files, source="mb_workid",
              album_key="Album", create=True):
    """A work whose members are real (empty) files under tmp_path."""
    folder = SourceFolder.get_or_none(SourceFolder.library == lib,
                                      SourceFolder.root_path == str(tmp_path))
    if folder is None:
        folder = SourceFolder.create(library=lib, root_path=str(tmp_path))
    album = Album.get_or_none(Album.library == lib,
                              Album.album_key == album_key)
    if album is None:
        album = Album.create(library=lib, folder=folder, album_key=album_key,
                             title=album_key)
    work = Work.create(album=album, work_name=name, work_sequence=1,
                       work_source=source)
    for number, relative in enumerate(files, start=1):
        if create:
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        Track.create(library=lib, folder=folder, album=album, work=work,
                     title=relative, relative_path=relative, disc_number=1,
                     track_number=number, duration_ms=60_000)
    return work


# ---------------------------------------------------------------------------
# Gain arithmetic
# ---------------------------------------------------------------------------

def test_gain_moves_loudness_to_the_reference():
    assert gain_for(-24.0) == pytest.approx(6.0)
    assert gain_for(-12.0) == pytest.approx(-6.0)
    assert gain_for(-18.0) == pytest.approx(0.0)


def test_reference_is_configurable():
    """MA re-targets, so -18 is a convention rather than a constraint."""
    assert gain_for(-24.0, reference=-23.0) == pytest.approx(1.0)


def test_a_standalone_work_collapses_to_plain_track_gain():
    """One member means L_work == L_m, so ALBUM_GAIN == TRACK_GAIN.

    This is why one rule covers the library: 3,804 of the works here are
    single tracks and need no special case.
    """
    single = measurement([-21.5], peaks=[0.8])
    values = tagio.tag_values(single.tracks[0], single, "k")

    assert values[tagio.ALBUM_GAIN] == values[tagio.TRACK_GAIN]
    assert values[tagio.ALBUM_PEAK] == values[tagio.TRACK_PEAK]


def test_every_member_gets_the_same_album_gain_and_its_own_track_gain():
    work = measurement([-24.0, -14.0], peaks=[0.3, 0.9], album_loudness=-16.0)
    first, second = (tagio.tag_values(t, work, "k") for t in work.tracks)

    assert first[tagio.ALBUM_GAIN] == second[tagio.ALBUM_GAIN] == "-2.00 dB"
    assert first[tagio.TRACK_GAIN] == "+6.00 dB"
    assert second[tagio.TRACK_GAIN] == "-4.00 dB"


def test_album_peak_is_the_largest_member_peak():
    work = measurement([-20.0, -20.0, -20.0], peaks=[0.2, 0.97, 0.5])
    values = tagio.tag_values(work.tracks[0], work, "k")

    assert values[tagio.ALBUM_PEAK] == "0.970000"
    assert values[tagio.TRACK_PEAK] == "0.200000"


def test_work_loudness_is_not_the_average_of_its_members():
    """R128 gates over the whole program; averaging diverges.

    Real works in this library differ by up to 3 dB between the two, and
    tagging with the average would put the whole work off MA's target.
    """
    gated = measurement([-30.0, -10.0], album_loudness=-13.0)
    averaged = measurement([-30.0, -10.0])

    assert gated.album_gain == pytest.approx(-5.0)
    assert averaged.album_gain == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Tag format — a malformed block is skipped silently, which is
# indistinguishable from "tags ignored"
# ---------------------------------------------------------------------------

def test_gain_carries_an_explicit_sign_two_decimals_and_a_db_suffix():
    assert format_gain(6.0) == "+6.00 dB"
    assert format_gain(-6.0) == "-6.00 dB"
    assert format_gain(0.0) == "+0.00 dB"
    assert format_gain(-0.004) == "-0.00 dB"


def test_peak_is_linear_not_decibels():
    assert format_peak(1.0) == "1.000000"
    assert format_peak(0.5) == "0.500000"
    assert "dB" not in format_peak(0.5)


def test_peak_above_full_scale_is_kept():
    """True peak legitimately exceeds 1.0 on lossy material."""
    assert format_peak(1.024176) == "1.024176"


def test_reference_loudness_names_its_unit():
    assert format_reference(-18.0) == "-18.00 LUFS"


def test_linear_and_db_peaks_round_trip():
    assert linear_to_db(1.0) == pytest.approx(0.0)
    assert db_to_linear(linear_to_db(0.63)) == pytest.approx(0.63)
    assert linear_to_db(0.0) == -math.inf


def test_the_full_tag_set_is_written():
    work = measurement([-20.0])
    values = tagio.tag_values(work.tracks[0], work, "abc123")

    assert set(values) == {
        tagio.TRACK_GAIN, tagio.TRACK_PEAK, tagio.ALBUM_GAIN,
        tagio.ALBUM_PEAK, tagio.REFERENCE, tagio.GAIN_SCOPE,
        tagio.WORK_KEY, tagio.VERSION,
    }
    assert values[tagio.GAIN_SCOPE] == "work"
    assert values[tagio.WORK_KEY] == "abc123"
    assert values[tagio.VERSION] == str(GAIN_VERSION)


def test_track_gain_is_always_present():
    """Without it MA ignores the file's ReplayGain data entirely."""
    work = measurement([-20.0, -25.0], album_loudness=-22.0)
    for track in work.tracks:
        assert tagio.TRACK_GAIN in tagio.tag_values(track, work, "k")


# ---------------------------------------------------------------------------
# The staleness key
# ---------------------------------------------------------------------------

def test_work_key_is_stable():
    assert work_key(["a.flac", "b.flac"]) == work_key(["a.flac", "b.flac"])


def test_work_key_changes_when_membership_changes():
    """A changed grouping must retag; this is how that is detected."""
    original = work_key(["a.flac", "b.flac"])
    assert work_key(["a.flac", "b.flac", "c.flac"]) != original
    assert work_key(["a.flac"]) != original


def test_work_key_changes_when_order_changes():
    assert work_key(["b.flac", "a.flac"]) != work_key(["a.flac", "b.flac"])


def test_work_key_cannot_be_confused_by_separators_in_names():
    """Joining on NUL is what stops two memberships colliding."""
    assert work_key(["a/b.flac"]) != work_key(["a", "b.flac"])


def test_work_key_is_short_enough_for_a_tag():
    assert len(work_key(["a.flac"])) == 16


# ---------------------------------------------------------------------------
# Clipping prediction (handoff §7)
# ---------------------------------------------------------------------------

def test_predicted_peak_follows_ma_retargeting():
    """MA applies `target - loudness`, so a peak moves by that much."""
    assert predicted_peak_dbfs(db_to_linear(-6.0), -20.0, ma_target=-17.0) \
        == pytest.approx(-3.0)


def test_clipping_fires_when_the_work_peak_meets_the_limiter():
    exposed_work = measurement([-25.0], peaks=[db_to_linear(-1.0)],
                               album_loudness=-25.0)
    exposed, peak, _ = clipping_prediction(exposed_work, ma_target=-17.0)

    assert exposed
    assert peak == pytest.approx(7.0)
    assert peak > MA_LIMITER_DBFS


def test_clipping_does_not_fire_with_headroom():
    quiet = measurement([-14.0], peaks=[db_to_linear(-12.0)],
                        album_loudness=-14.0)
    exposed, peak, _ = clipping_prediction(quiet, ma_target=-17.0)

    assert not exposed
    assert peak == pytest.approx(-15.0)


def test_work_gain_reduces_exposure_on_a_quiet_work_with_a_loud_finale():
    """The case handoff §7 corrects: per-track normalization is worse.

    Three quiet movements and a loud finale. Untagged, MA normalizes each
    track and lifts the quiet ones hard; work-scoped, the whole work
    moves together and the loud finale is what sets the peak.
    """
    work = measurement(
        [-30.0, -30.0, -30.0, -14.0],
        peaks=[db_to_linear(-3.0)] * 3 + [db_to_linear(-1.0)],
        album_loudness=-18.0)
    _, work_scoped, per_track = clipping_prediction(work, ma_target=-17.0)

    assert work_scoped < per_track
    assert work_scoped == pytest.approx(0.0)
    assert per_track == pytest.approx(10.0)


def test_work_gain_increases_exposure_on_a_movement_louder_than_its_work():
    """The other half of §7: it pushes up where a member is loud."""
    work = measurement([-30.0, -12.0], peaks=[0.1, db_to_linear(-2.0)],
                       album_loudness=-24.0)
    _, work_scoped, per_track = clipping_prediction(work, ma_target=-17.0)

    assert work_scoped > per_track


# ---------------------------------------------------------------------------
# Selection: provenance, format, and ordering
# ---------------------------------------------------------------------------

def test_guessed_groupings_are_excluded_by_default(lib, tmp_path):
    """A wrong grouping writes a wrong gain into files."""
    make_work(lib, tmp_path, "Trusted", ["a.flac", "b.flac"],
              source="mb_workid")
    make_work(lib, tmp_path, "Guessed", ["c.flac", "d.flac"],
              source="heuristic")

    selection = work_db.collect_works()

    assert [job.work_name for job in selection.jobs] == ["Trusted"]
    refused = selection.skipped_by(work_db.SKIP_PROVENANCE)
    assert [s.work_name for s in refused] == ["Guessed"]


def test_include_heuristic_admits_them(lib, tmp_path):
    make_work(lib, tmp_path, "Guessed", ["c.flac"], source="heuristic")

    selection = work_db.collect_works(include_guessed=True)

    assert [job.work_name for job in selection.jobs] == ["Guessed"]
    assert not selection.skipped


def test_an_unknown_source_is_treated_as_guessed(lib, tmp_path):
    """`import` provenance is unknown, so it goes through the same gate."""
    make_work(lib, tmp_path, "Imported", ["a.flac"], source="import")

    assert not work_db.collect_works().jobs
    assert work_db.collect_works(include_guessed=True).jobs


def test_all_four_trusted_sources_are_admitted(lib, tmp_path):
    for index, source in enumerate(sorted(work_db.TRUSTED_SOURCES)):
        make_work(lib, tmp_path, source, [f"{index}.flac"], source=source)

    assert len(work_db.collect_works().jobs) == len(work_db.TRUSTED_SOURCES)


def test_naming_a_work_overrides_the_provenance_gate(lib, tmp_path):
    """Asking for a work by id is a statement that you mean it."""
    guessed = make_work(lib, tmp_path, "Guessed", ["c.flac"],
                        source="heuristic")

    selection = work_db.collect_works(work_ids=[guessed.id])

    assert [job.work_id for job in selection.jobs] == [guessed.id]


def test_unsupported_formats_are_skipped_not_guessed_at(lib, tmp_path):
    make_work(lib, tmp_path, "Monkey", ["a.ape"])
    make_work(lib, tmp_path, "Apple", ["b.m4a"], album_key="Other")

    selection = work_db.collect_works()

    assert not selection.jobs
    assert {s.work_name for s in selection.skipped_by(work_db.SKIP_FORMAT)} \
        == {"Monkey", "Apple"}


def test_naming_a_work_does_not_override_the_format_gate(lib, tmp_path):
    """Provenance is a judgement; format is a capability."""
    ape = make_work(lib, tmp_path, "Monkey", ["a.ape"])

    selection = work_db.collect_works(work_ids=[ape.id])

    assert not selection.jobs
    assert selection.skipped_by(work_db.SKIP_FORMAT)


def test_a_work_spanning_two_formats_is_skipped(lib, tmp_path):
    """No single tag convention covers both, so guessing is not an option."""
    make_work(lib, tmp_path, "Mixed", ["a.flac", "b.mp3"])

    selection = work_db.collect_works()

    assert not selection.jobs
    assert selection.skipped_by(work_db.SKIP_MIXED)


def test_a_work_with_a_missing_file_is_skipped_whole(lib, tmp_path):
    make_work(lib, tmp_path, "Gone", ["there.flac", "gone.flac"],
              create=False)

    selection = work_db.collect_works()

    assert not selection.jobs
    assert selection.skipped_by(work_db.SKIP_MISSING)


def test_members_are_ordered_by_disc_then_track(lib, tmp_path):
    work = make_work(lib, tmp_path, "Two discs",
                     ["d2t1.flac", "d1t2.flac", "d1t1.flac"])
    order = {"d2t1.flac": (2, 1), "d1t2.flac": (1, 2), "d1t1.flac": (1, 1)}
    for track in Track.select().where(Track.work == work):
        disc, number = order[track.relative_path]
        track.disc_number, track.track_number = disc, number
        track.save()

    job = work_db.collect_works().jobs[0]

    assert job.relative_paths == ["d1t1.flac", "d1t2.flac", "d2t1.flac"]


def test_limit_counts_works_that_will_be_tagged(lib, tmp_path):
    """Not works considered — otherwise --limit 5 could select none."""
    make_work(lib, tmp_path, "Guessed", ["g.flac"], source="heuristic")
    for index in range(3):
        make_work(lib, tmp_path, f"Real {index}", [f"r{index}.flac"])

    selection = work_db.collect_works(limit=2)

    assert len(selection.jobs) == 2


def test_library_filter_selects_one_library(lib, tmp_path):
    from music_manager.core.database import Library

    make_work(lib, tmp_path, "Mine", ["a.flac"])
    other = Library.create(name="Other")
    make_work(other, tmp_path, "Theirs", ["b.flac"], album_key="Theirs")

    assert [j.work_name for j in
            work_db.collect_works(library_name="TestLib").jobs] == ["Mine"]
    assert [j.work_name for j in
            work_db.collect_works(library_name="Other").jobs] == ["Theirs"]


def test_an_unknown_library_is_named_in_the_error(lib, tmp_path):
    with pytest.raises(LookupError, match="Nope"):
        work_db.collect_works(library_name="Nope")


# ---------------------------------------------------------------------------
# Interrupting a run
# ---------------------------------------------------------------------------

def fake_selection(count):
    """A selection of jobs that never touch the disk."""
    return work_db.Selection(jobs=[
        work_db.WorkJob(work_id=index, work_name=f"W{index}",
                        source="mb_workid", album_title="A",
                        paths=[f"/m/{index}.flac"],
                        relative_paths=[f"{index}.flac"])
        for index in range(count)])


def test_an_interrupt_keeps_the_works_that_finished(monkeypatch):
    """Ctrl-C reports a partial run rather than losing it."""
    from music_manager.loudness import runner

    seen = []

    def fake(job, **kwargs):
        seen.append(job)
        if len(seen) == 3:
            raise KeyboardInterrupt
        return runner.WorkOutcome(job=job, tagged=True, tracks_written=1)

    monkeypatch.setattr(runner, "process_work", fake)

    result = runner.run(fake_selection(10), workers=1)

    assert result.interrupted
    assert len(result.outcomes) == 2
    assert result.tracks_written == 2
    assert result.unprocessed == 8


def test_an_interrupt_does_not_wait_for_the_queue(monkeypatch):
    """The pool's own __exit__ waits for every queued job.

    That is why `run` does not use it as a context manager: a Ctrl-C part
    way through the library would otherwise hang until the whole run
    finished, which is the opposite of interrupting it.
    """
    import time

    from music_manager.loudness import runner

    started = []

    def fake(job, **kwargs):
        started.append(job)
        time.sleep(0.05)
        return runner.WorkOutcome(job=job)

    def interrupt(futures):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "process_work", fake)
    monkeypatch.setattr(runner.cf, "as_completed", interrupt)

    began = time.monotonic()
    result = runner.run(fake_selection(200), workers=2)
    elapsed = time.monotonic() - began

    assert result.interrupted
    assert len(started) < 200          # the queue was dropped, not drained
    assert elapsed < 2.0               # 200 jobs at 0.05s would be 5s


def test_an_uninterrupted_run_is_not_marked_interrupted(monkeypatch):
    from music_manager.loudness import runner

    monkeypatch.setattr(runner, "process_work",
                        lambda job, **kw: runner.WorkOutcome(job=job))

    result = runner.run(fake_selection(4), workers=2)

    assert not result.interrupted
    assert result.unprocessed == 0
    assert len(result.outcomes) == 4


def clipping_outcome(work_id, size, today, tagged):
    """An outcome carrying only what the clipping report reads."""
    from music_manager.loudness import runner

    job = work_db.WorkJob(work_id=work_id, work_name=f"W{work_id}",
                          source="mb_workid", album_title="A",
                          paths=[f"/m/{work_id}-{i}.flac" for i in range(size)],
                          relative_paths=[f"{work_id}-{i}.flac"
                                          for i in range(size)])
    return runner.WorkOutcome(
        job=job, measurement=measurement([-20.0] * size),
        exposed=tagged > MA_LIMITER_DBFS, peak_dbfs=tagged,
        per_track_peak_dbfs=today)


def clipping_report(outcomes):
    from music_manager.loudness import report as reporting
    from music_manager.loudness import runner

    result = runner.RunResult(selection=fake_selection(0))
    result.outcomes = outcomes
    return "\n".join(reporting.render(result))


def test_single_track_exposure_is_named_as_pre_existing():
    """Most exposed works are single-track and clip today regardless.

    Reporting them as though tagging caused it made a 2,287-work list
    that hid the ~80 works the decision actually turns on.
    """
    text = clipping_report([clipping_outcome(i, 1, 5.0, 5.0)
                            for i in range(30)])

    assert "30 of those are single-track works" in text
    assert "clip identically today" in text
    assert "Made worse by work-scoping" not in text


def test_the_regression_table_lists_only_works_made_worse():
    text = clipping_report([
        clipping_outcome(1, 3, today=0.0, tagged=4.0),    # worse by 4
        clipping_outcome(2, 3, today=6.0, tagged=1.0),    # better
        clipping_outcome(3, 1, today=9.0, tagged=9.0),    # single track
    ])

    assert "Made worse by work-scoping" in text
    table = text.split("Made worse by work-scoping")[1]
    assert " 1 " in table
    assert "W1" in table
    assert "W2" not in table
    assert "W3" not in table


def test_regressions_are_sorted_by_how_much_worse():
    text = clipping_report([
        clipping_outcome(1, 2, today=0.0, tagged=1.0),
        clipping_outcome(2, 2, today=0.0, tagged=8.0),
        clipping_outcome(3, 2, today=0.0, tagged=4.0),
    ])

    table = text.split("Made worse by work-scoping")[1]
    assert [w for w in ("W1", "W2", "W3") if w in table] == ["W1", "W2", "W3"]
    assert table.index("W2") < table.index("W3") < table.index("W1")


def test_newly_exposed_works_are_called_out():
    """Under the limiter today, over it after tagging.

    The only group where this tool creates a problem rather than
    inheriting or reducing one.
    """
    text = clipping_report([
        clipping_outcome(1, 2, today=-6.0, tagged=2.0),   # newly exposed
        clipping_outcome(2, 2, today=3.0, tagged=5.0),    # already exposed
    ])

    assert "1 of those are newly exposed" in text
    table = text.split("Made worse by work-scoping")[1]
    assert "yes" in table


def test_a_run_with_no_regressions_prints_no_table():
    text = clipping_report([clipping_outcome(1, 3, today=8.0, tagged=2.0)])

    assert "1 peak lower than they do today" in text
    assert "Made worse by work-scoping" not in text


def test_the_report_says_a_run_was_interrupted():
    from music_manager.loudness import report as reporting
    from music_manager.loudness import runner

    result = runner.RunResult(selection=fake_selection(10), wrote=True,
                              interrupted=True, unprocessed=7)

    text = "\n".join(reporting.render(result))

    assert "INTERRUPTED" in text
    assert "7 selected work(s) were never started" in text


def test_rsgain_runs_in_its_own_session(monkeypatch, tmp_path):
    """So the terminal's Ctrl-C cannot kill a measurement in flight.

    SIGINT goes to the whole foreground process group; without this a
    work being measured would die and be reported as a failure rather
    than as the interruption it was.
    """
    from music_manager.loudness import measure

    path = tmp_path / "a.flac"
    path.write_bytes(b"")
    captured = {}

    class Result:
        returncode = 0
        stdout = ("Filename\tL\tG\tPeak\tPeakdB\tType\tClip\n"
                  "a.flac\t-20.00\t2.00\t0.5\t-6.02\tTrue\tN\n"
                  "Album\t-20.00\t2.00\t0.5\t-6.02\tTrue\tN\n")
        stderr = ""

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(measure.subprocess, "run", fake_run)
    measure.measure_work([str(path)])

    assert captured["start_new_session"] is True


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------

def _declared_options():
    """Every option string the typer command actually accepts."""
    import inspect

    from music_manager.loudness.cli import tag

    names = set()
    for parameter in inspect.signature(tag).parameters.values():
        default = parameter.default
        flags = [f for f in getattr(default, "param_decls", None) or []
                 if f.startswith("-")]
        names.update(flags or [f"--{parameter.name.replace('_', '-')}"])
    return names


def test_the_help_documents_every_flag():
    """main.py's help lost -j/--workers once; this stops a repeat.

    That flag decided whether analysis took forty minutes or seven hours,
    and it was missing from the help line for a whole release.
    """
    import rgtag

    undocumented = {flag for flag in _declared_options()
                    if flag not in rgtag._HELP}

    assert not undocumented


def test_the_help_documents_every_tag_written():
    """The tag list in the help is the tool's contract with other players."""
    import rgtag

    for name in (tagio.TRACK_GAIN, tagio.TRACK_PEAK, tagio.ALBUM_GAIN,
                 tagio.ALBUM_PEAK, tagio.REFERENCE, tagio.GAIN_SCOPE,
                 tagio.WORK_KEY, tagio.VERSION):
        assert name in rgtag._HELP


def test_version_is_read_without_importing_the_package():
    """--version must work from an interpreter with no dependencies."""
    import re
    import subprocess
    import sys

    result = subprocess.run([sys.executable, "rgtag.py", "--version"],
                            capture_output=True, text=True)

    from music_manager import __version__
    assert result.returncode == 0
    assert re.search(rf"\b{re.escape(__version__)}$", result.stdout.strip())


# ---------------------------------------------------------------------------
# Finding a work without knowing its id
# ---------------------------------------------------------------------------

def test_works_can_be_selected_by_album_title(lib, tmp_path):
    """CM's GUI shows work ids nowhere, so --work-id alone was unusable."""
    make_work(lib, tmp_path, "Adagietto", ["a.flac"], album_key="Mahler 5")
    make_work(lib, tmp_path, "Prelude", ["b.flac"], album_key="WTC Book II")

    selection = work_db.collect_works(album_like="mahler")

    assert [job.work_name for job in selection.jobs] == ["Adagietto"]


def test_works_can_be_selected_by_name(lib, tmp_path):
    make_work(lib, tmp_path, "Symphony no. 5", ["a.flac"])
    make_work(lib, tmp_path, "Piano Concerto", ["b.flac"], album_key="Other")

    selection = work_db.collect_works(work_like="SYMPHONY")

    assert [job.work_name for job in selection.jobs] == ["Symphony no. 5"]


def test_name_filters_combine(lib, tmp_path):
    make_work(lib, tmp_path, "Symphony no. 1", ["a.flac"], album_key="Brahms")
    make_work(lib, tmp_path, "Symphony no. 2", ["b.flac"], album_key="Mahler")
    make_work(lib, tmp_path, "Quartet", ["c.flac"], album_key="Brahms")

    selection = work_db.collect_works(album_like="brahms", work_like="symphony")

    assert [job.work_name for job in selection.jobs] == ["Symphony no. 1"]


def test_a_filtered_out_work_is_not_reported_as_skipped(lib, tmp_path):
    """It was never in scope. Listing thousands of them would bury the
    works that really were refused, which is what skips are for."""
    make_work(lib, tmp_path, "Wanted", ["a.flac"], album_key="Mahler 5")
    make_work(lib, tmp_path, "Guessed", ["b.flac"], source="heuristic",
              album_key="Elsewhere")

    selection = work_db.collect_works(album_like="mahler")

    assert len(selection.jobs) == 1
    assert not selection.skipped


def test_the_listing_shows_the_id_and_enough_to_recognise_the_work(lib,
                                                                   tmp_path):
    from music_manager.loudness import report as reporting

    work = make_work(lib, tmp_path, "Symphony no. 5", ["a.flac", "b.flac"],
                     source="mb_workid", album_key="Mahler 5")

    text = "\n".join(reporting.render_listing(work_db.collect_works()))

    assert str(work.id) in text
    assert "Symphony no. 5" in text
    assert "Mahler 5" in text
    assert "mb_workid" in text
    assert "flac" in text
    assert "1 work(s), 2 track(s)" in text


def test_the_listing_says_when_nothing_matched(lib, tmp_path):
    from music_manager.loudness import report as reporting

    text = "\n".join(reporting.render_listing(work_db.collect_works()))

    assert "No works selected" in text


def test_absolute_paths_are_built_from_the_source_folder(lib, tmp_path):
    make_work(lib, tmp_path, "W", ["sub/a.flac"])

    job = work_db.collect_works().jobs[0]

    assert job.paths == [str(tmp_path / "sub" / "a.flac")]
    assert job.relative_paths == ["sub/a.flac"]
