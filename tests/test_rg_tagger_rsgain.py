"""v3.7: measuring works with rsgain, end to end.

rsgain's `custom` mode treats the file list it is given as one album
unit, which is the whole reason this project is an orchestrator rather
than a reimplementation of R128. These tests pin that behaviour, the
parsing of its output, and the rule that a work is written all at once
or not at all.
"""

import os

import pytest

from music_manager.loudness import db as work_db
from music_manager.loudness import runner
from music_manager.loudness import tags as tagio
from music_manager.loudness.gain import GAIN_VERSION, work_key
from music_manager.loudness.measure import (
    MeasurementError, build_command, measure_work, parse_output,
)
from tests.rg_audio import make_audio, needs_rsgain
from tests.test_rg_tagger import make_work

pytestmark = needs_rsgain

LOUD, QUIET = -3.0, -23.0          # a 20 dB difference between movements
MID = -9.0                         # close enough to LOUD to survive gating


def album_gain_of(path):
    return tagio.read_all(path)[tagio.ALBUM_GAIN]


def track_gain_of(path):
    return tagio.read_all(path)[tagio.TRACK_GAIN]


# ---------------------------------------------------------------------------
# The claim the whole project rests on
# ---------------------------------------------------------------------------

def test_the_file_list_is_the_album_unit(tmp_path):
    """Two files given together are measured as one program.

    Scoping is by the *list*, not by the directory: all three files here
    share one folder, and each list gets its own album loudness. This is
    the property the whole project depends on and the reason it is an
    orchestrator rather than a reimplementation of R128.
    """
    loud = make_audio(tmp_path / "loud.flac", level_db=LOUD)
    mid = make_audio(tmp_path / "mid.flac", level_db=MID)

    together = measure_work([loud, mid]).album_loudness
    loud_alone = measure_work([loud]).album_loudness
    mid_alone = measure_work([mid]).album_loudness

    assert mid_alone < together < loud_alone


def test_a_movement_far_below_the_rest_is_gated_out(tmp_path):
    """R128's relative gate drops anything 10 LU below the mean.

    This is the behaviour that makes work-scoped gain right for
    classical: a pianissimo movement does not drag the whole symphony's
    gain upward, which is exactly what an average would do.
    """
    loud = make_audio(tmp_path / "loud.flac", level_db=LOUD)
    quiet = make_audio(tmp_path / "quiet.flac", level_db=QUIET)

    with_quiet = measure_work([loud, quiet]).album_loudness
    without = measure_work([loud]).album_loudness

    assert with_quiet == pytest.approx(without, abs=0.01)


def test_work_loudness_is_gated_not_averaged(tmp_path):
    """R128 gates over the whole program, so the quiet movement barely
    moves the result — an average would land 10 dB away."""
    loud = make_audio(tmp_path / "loud.flac", level_db=LOUD)
    quiet = make_audio(tmp_path / "quiet.flac", level_db=QUIET)

    work = measure_work([loud, quiet])
    mean = sum(t.loudness for t in work.tracks) / 2

    assert abs(work.album_loudness - mean) > 5.0
    assert work.album_loudness > mean


def test_album_gain_is_independent_of_order(tmp_path):
    loud = make_audio(tmp_path / "loud.flac", level_db=LOUD)
    quiet = make_audio(tmp_path / "quiet.flac", level_db=QUIET)

    assert measure_work([loud, quiet]).album_gain == pytest.approx(
        measure_work([quiet, loud]).album_gain)


def test_a_single_track_work_collapses_to_track_gain(tmp_path):
    only = make_audio(tmp_path / "only.flac", level_db=-12.0)

    work = measure_work([only])

    assert work.album_gain == pytest.approx(work.tracks[0].gain)
    assert work.album_peak == pytest.approx(work.tracks[0].peak)


def test_the_reference_is_configurable(tmp_path):
    path = make_audio(tmp_path / "a.flac", level_db=-12.0)

    at_18 = measure_work([path], reference=-18.0)
    at_23 = measure_work([path], reference=-23.0)

    assert at_18.album_gain - at_23.album_gain == pytest.approx(5.0, abs=0.01)


def test_album_peak_is_the_largest_member_peak(tmp_path):
    loud = make_audio(tmp_path / "loud.flac", level_db=LOUD)
    quiet = make_audio(tmp_path / "quiet.flac", level_db=QUIET)

    work = measure_work([loud, quiet])

    assert work.album_peak == pytest.approx(max(t.peak for t in work.tracks))


# ---------------------------------------------------------------------------
# Invocation and parsing
# ---------------------------------------------------------------------------

def test_clipping_protection_is_off():
    """It would silently adjust the gains we are about to write."""
    command = build_command(["a.flac"])

    assert "-c" in command and command[command.index("-c") + 1] == "n"
    assert "-a" in command                      # the file list is one album
    assert "-s" in command and command[command.index("-s") + 1] == "s"


def test_rows_are_matched_positionally_not_by_filename(tmp_path):
    """A multi-disc work genuinely can hold two files called 01.flac."""
    first = tmp_path / "d1"
    second = tmp_path / "d2"
    first.mkdir()
    second.mkdir()
    loud = make_audio(first / "01.flac", level_db=LOUD)
    quiet = make_audio(second / "01.flac", level_db=QUIET)

    work = measure_work([loud, quiet])

    assert work.tracks[0].path == loud
    assert work.tracks[1].path == quiet
    assert work.tracks[0].loudness > work.tracks[1].loudness


def test_a_short_row_count_is_an_error_not_a_silent_mismatch():
    stdout = ("Filename\tLoudness (LUFS)\tGain (dB)\tPeak\tPeak (dB)\n"
              "a.flac\t-20.00\t2.00\t0.5\t-6.02\n"
              "Album\t-20.00\t2.00\t0.5\t-6.02\n")

    with pytest.raises(MeasurementError, match="skipped one"):
        parse_output(stdout, ["a.flac", "b.flac"])


def test_a_clipping_adjustment_is_refused():
    stdout = ("Filename\tLoudness\tGain\tPeak\tPeak dB\tPeak Type\tClipping\n"
              "a.flac\t-20.00\t2.00\t0.5\t-6.02\tTrue\tY\n"
              "Album\t-20.00\t2.00\t0.5\t-6.02\tTrue\tY\n")

    with pytest.raises(MeasurementError, match="clipping adjustment"):
        parse_output(stdout, ["a.flac"])


def test_digital_silence_parses_as_negative_infinity():
    """rsgain prints an INFINITY character, not '-inf'."""
    stdout = ("Filename\tLoudness\tGain\tPeak\tPeak dB\tPeak Type\tClipping\n"
              "a.flac\t-∞\t0.00\t0.000000\t-∞\tTrue\tN\n"
              "Album\t-∞\t0.00\t0.000000\t-∞\tTrue\tN\n")

    work = parse_output(stdout, ["a.flac"])

    assert work.is_silent


def test_a_silent_work_is_refused(tmp_path):
    """No gain is defined for it, and 0.00 dB would be a fabrication."""
    silent = make_audio(tmp_path / "silent.flac", silent=True)

    with pytest.raises(MeasurementError, match="silence"):
        measure_work([silent])


def test_a_silent_member_does_not_stop_the_work(tmp_path):
    """Classical works do contain near-silent movements and long gaps."""
    silent = make_audio(tmp_path / "silent.flac", silent=True)
    loud = make_audio(tmp_path / "loud.flac", level_db=LOUD)

    work = measure_work([silent, loud])

    assert not work.is_silent
    assert work.album_gain == pytest.approx(work.tracks[1].gain, abs=0.5)


def test_a_missing_file_is_reported_before_rsgain_runs(tmp_path):
    with pytest.raises(MeasurementError, match="missing"):
        measure_work([str(tmp_path / "nope.flac")])


def test_an_undecodable_member_fails_the_work(tmp_path):
    good = make_audio(tmp_path / "good.flac", level_db=-12.0)
    broken = tmp_path / "broken.flac"
    broken.write_bytes(b"this is not a flac file")

    with pytest.raises(MeasurementError):
        measure_work([good, str(broken)])


# ---------------------------------------------------------------------------
# Whole runs, through the database
# ---------------------------------------------------------------------------

def build_work(lib, tmp_path, name, members, source="mb_workid",
               album_key="Album"):
    """A work in the database whose members are real audio files."""
    names = []
    for index, level in enumerate(members, start=1):
        relative = f"{name}-{index}.flac"
        make_audio(tmp_path / relative, level_db=level)
        names.append(relative)
    return make_work(lib, tmp_path, name, names, source=source,
                     album_key=album_key, create=False)


def test_every_member_gets_one_album_gain_and_its_own_track_gain(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET, -12.0])

    result = runner.run(work_db.collect_works(), write=True, workers=1)

    outcome = result.outcomes[0]
    assert outcome.tagged and outcome.tracks_written == 3
    paths = outcome.job.paths
    assert len({album_gain_of(p) for p in paths}) == 1
    assert len({track_gain_of(p) for p in paths}) == 3


def test_two_works_on_one_album_get_different_album_gains(lib, tmp_path):
    """The ordinary classical case: a disc holding two symphonies.

    MA applies each file's own ALBUM_GAIN rather than one value per
    album, which was measured, and this is the design depending on it.
    """
    build_work(lib, tmp_path, "Loud work", [LOUD, LOUD], album_key="Disc")
    build_work(lib, tmp_path, "Quiet work", [QUIET, QUIET], album_key="Disc")

    runner.run(work_db.collect_works(), write=True, workers=1)

    gains = {job.work_name: album_gain_of(job.paths[0])
             for job in work_db.collect_works().jobs}
    assert gains["Loud work"] != gains["Quiet work"]


def test_a_dry_run_writes_nothing(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])

    result = runner.run(work_db.collect_works(), write=False, workers=1)

    assert result.tracks_written == 0
    assert not result.tagged
    assert result.outcomes[0].measurement is not None    # still measured
    for path in result.outcomes[0].job.paths:
        assert tagio.read_all(path) == {}


def test_a_second_run_skips_work_that_is_already_current(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    selection = work_db.collect_works()
    runner.run(selection, write=True, workers=1)

    again = runner.run(work_db.collect_works(), write=True, workers=1)

    assert again.already_current
    assert not again.tagged


def test_force_retags_current_work(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    runner.run(work_db.collect_works(), write=True, workers=1)

    again = runner.run(work_db.collect_works(), write=True, force=True,
                       workers=1)

    assert again.tagged and not again.already_current


def test_a_rerun_leaves_the_tags_byte_identical(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    runner.run(work_db.collect_works(), write=True, workers=1)
    paths = work_db.collect_works().jobs[0].paths
    before = [tagio.read_all(p) for p in paths]

    runner.run(work_db.collect_works(), write=True, force=True, workers=1)

    assert [tagio.read_all(p) for p in paths] == before


def test_a_membership_change_triggers_a_retag(lib, tmp_path):
    """The staleness case that matters: the grouping moved."""
    from music_manager.core.database import Track

    work = build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    runner.run(work_db.collect_works(), write=True, workers=1)
    first_key = tagio.read_state(work_db.collect_works().jobs[0].paths[0])[0]

    make_audio(tmp_path / "Symphony-3.flac", level_db=-12.0)
    Track.create(library=lib, folder=work.album.folder, album=work.album,
                 work=work, title="3", relative_path="Symphony-3.flac",
                 disc_number=1, track_number=3, duration_ms=60_000)
    job = work_db.collect_works().jobs[0]
    assert work_key(job.relative_paths) != first_key

    result = runner.run(work_db.collect_works(), write=True, workers=1)

    assert result.tagged
    assert len({tagio.read_state(p)[0] for p in job.paths}) == 1


def test_a_failing_member_leaves_the_whole_work_untouched(lib, tmp_path):
    """A work with some members tagged and some not is worse than none."""
    make_audio(tmp_path / "ok-1.flac", level_db=LOUD)
    (tmp_path / "ok-2.flac").write_bytes(b"not a flac file")
    make_work(lib, tmp_path, "Broken", ["ok-1.flac", "ok-2.flac"],
              create=False)

    result = runner.run(work_db.collect_works(), write=True, workers=1)

    assert result.failed and not result.tagged
    assert not result.outcomes[0].partial
    assert tagio.read_all(str(tmp_path / "ok-1.flac")) == {}


def test_the_written_state_matches_what_the_run_computed(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])

    result = runner.run(work_db.collect_works(), write=True, workers=1)

    outcome = result.outcomes[0]
    for path in outcome.job.paths:
        assert tagio.read_state(path) == (outcome.key, GAIN_VERSION)


def test_mtimes_survive_a_real_run(lib, tmp_path):
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    paths = work_db.collect_works().jobs[0].paths
    before = [os.stat(p).st_mtime_ns for p in paths]

    runner.run(work_db.collect_works(), write=True, workers=1)

    assert [os.stat(p).st_mtime_ns for p in paths] == before


def test_a_sandbox_run_tags_copies_and_leaves_the_library_alone(lib, tmp_path):
    """Handoff §6's round-trip check, as a command rather than a ritual."""
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    originals = work_db.collect_works().jobs[0].paths
    sandbox = tmp_path / "sandbox"

    result = runner.run(work_db.collect_works(), sandbox=str(sandbox),
                        workers=1)

    assert result.tagged and result.tracks_written == 2
    for path in originals:
        assert tagio.read_all(path) == {}
    copies = result.outcomes[0].job.paths
    assert all(str(sandbox) in p for p in copies)
    assert len({album_gain_of(p) for p in copies}) == 1


def test_the_sandbox_key_follows_the_real_work(lib, tmp_path):
    """So a sandbox run predicts what the real run would write."""
    build_work(lib, tmp_path, "Symphony", [LOUD, QUIET])
    job = work_db.collect_works().jobs[0]

    result = runner.run(work_db.collect_works(),
                        sandbox=str(tmp_path / "sandbox"), workers=1)

    assert result.outcomes[0].key == work_key(job.relative_paths)


def test_parallel_and_serial_runs_agree(lib, tmp_path):
    for index in range(4):
        build_work(lib, tmp_path, f"W{index}", [LOUD, QUIET],
                   album_key=f"A{index}")

    serial = runner.run(work_db.collect_works(), workers=1)
    parallel = runner.run(work_db.collect_works(), workers=4)

    by_id = {o.job.work_id: o.measurement.album_gain for o in serial.outcomes}
    assert {o.job.work_id: o.measurement.album_gain
            for o in parallel.outcomes} == by_id
