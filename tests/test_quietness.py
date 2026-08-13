"""v3.8: the quietness metrics, against envelopes with known shapes.

The four cases the plan names, plus the two gates. The crescendo/step
pair is the important one: it is what proves `rise_rate` and
`startle_local` measure different things and that shipping both is not
shipping the same slider twice.

Tolerances are loose on purpose. These assert the *shape* of each metric
— which signal scores higher, and roughly by how much — not ffmpeg's
arithmetic, which is not ours to test.
"""

import pytest

from music_manager.core.quietness import (
    ABSOLUTE_GATE_LUFS,
    FRAME_PERIOD,
    LOUDNESS_VERSION,
    MOMENTARY_WINDOW,
    SHORT_TERM_WINDOW,
    LoudnessSeries,
    MeasurementError,
    QuietnessMetrics,
    build_command,
    measure,
    metrics_from_series,
    parse_frames,
)
from tests.rg_audio import make_audio, make_envelope, needs_ffmpeg

pytestmark = needs_ffmpeg


# ---------------------------------------------------------------------------
# Fixtures: one envelope each, named for what it is meant to prove
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def constant(tmp_path_factory):
    """40 s at one level. Every contrast metric should be ~0."""
    path = tmp_path_factory.mktemp("q") / "constant.wav"
    return make_envelope(path, [(40, -20, -20)])


@pytest.fixture(scope="module")
def step(tmp_path_factory):
    """40 s quiet, then 40 s 20 dB louder, instantly."""
    path = tmp_path_factory.mktemp("q") / "step.wav"
    return make_envelope(path, [(40, -30, -30), (40, -10, -10)])


@pytest.fixture(scope="module")
def crescendo(tmp_path_factory):
    """The same 20 dB rise, spread over 60 s instead of no time at all."""
    path = tmp_path_factory.mktemp("q") / "crescendo.wav"
    return make_envelope(path, [(40, -30, -30), (60, -30, -10), (20, -10, -10)])


@pytest.fixture(scope="module")
def transient(tmp_path_factory):
    """One 200 ms crack in an otherwise even 80 s."""
    path = tmp_path_factory.mktemp("q") / "transient.wav"
    return make_envelope(
        path, [(40, -20, -20), (0.2, -1, -1), (40, -20, -20)])


# ---------------------------------------------------------------------------
# The window-fill ramp — the gate that fires on every file
# ---------------------------------------------------------------------------

def test_short_term_is_invalid_until_its_window_fills(constant):
    """S reads the sentinel until t=2.9s, and that must not be data.

    Not an edge case: it happens on every track in the library, and it
    lands in the first ten seconds, which is exactly the head level a
    seam is made of.
    """
    from music_manager.core.quietness import find_ffmpeg
    import subprocess

    result = subprocess.run(build_command(constant, find_ffmpeg()),
                            capture_output=True, text=True)
    series = parse_frames(result.stdout)

    # The raw series really does start with the sentinel...
    assert series.short_term[0] < ABSOLUTE_GATE_LUFS
    # ...and the gated view really does start after the window fills.
    times, values = series.valid_short_term()
    assert times[0] == pytest.approx(SHORT_TERM_WINDOW - FRAME_PERIOD, abs=0.05)
    assert all(v > ABSOLUTE_GATE_LUFS for v in values)

    m_times, m_values = series.valid_momentary()
    assert m_times[0] == pytest.approx(MOMENTARY_WINDOW - FRAME_PERIOD,
                                       abs=0.05)
    assert all(v > ABSOLUTE_GATE_LUFS for v in m_values)


def test_the_ramp_does_not_reach_any_metric(constant):
    """A flat tone must score ~0 on everything, ramp included.

    If the sentinel leaked into the series, the median of the preceding
    30 s would collapse and `startle_local` would report ~100 LU on the
    most boring signal there is.
    """
    m = measure(constant)
    assert m.measured
    assert m.startle_delta == pytest.approx(0.0, abs=0.5)
    assert m.startle_local == pytest.approx(0.0, abs=0.5)
    assert m.rise_rate == pytest.approx(0.0, abs=0.5)
    assert m.lra == pytest.approx(0.0, abs=1.0)
    assert m.head_level == pytest.approx(0.0, abs=1.0)
    assert m.tail_level == pytest.approx(0.0, abs=1.0)


def test_head_level_sees_an_attack_inside_the_short_term_window():
    """A loud entry 1 s in is a seam risk, and S cannot see it.

    This is why head/tail come from the momentary window. Measured from
    S, the first 2.9 s are invisible and this file's head would read as
    its quiet body.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "attack.wav"
        # Loud for 2 s, then quiet for the rest.
        make_envelope(path, [(2, -6, -6), (60, -30, -30)])
        m = measure(path)

    assert m.measured
    # The head is well above the body, which is nearly all quiet material.
    assert m.head_level > 5.0


# ---------------------------------------------------------------------------
# The four signals
# ---------------------------------------------------------------------------

def test_constant_tone_scores_zero_contrast(constant):
    m = measure(constant)
    assert m.startle_delta == pytest.approx(0.0, abs=0.5)
    assert m.startle_local == pytest.approx(0.0, abs=0.5)
    assert m.rise_rate == pytest.approx(0.0, abs=0.5)


def test_step_registers_on_both_startle_and_rise(step):
    """An instant 20 dB step is loud against its history and it is fast."""
    m = measure(step)
    assert m.startle_local == pytest.approx(20.0, abs=3.0)
    assert m.rise_rate == pytest.approx(20.0, abs=3.0)
    # And it happens where it was put, not somewhere else.
    assert m.loud_at_ms == pytest.approx(40_000, abs=5_000)


def test_crescendo_and_step_separate_rise_rate_from_startle(crescendo, step):
    """The pair that justifies shipping both metrics.

    Same 20 dB rise, same endpoints, different speed. `startle_local`
    contrasts against the last 30 s and so scores the slow rise well
    below the instant one; `rise_rate` is explicitly a 10 s climb and
    collapses on a 60 s ramp. If these two moved together, one of them
    would be redundant and A3 would drop it.
    """
    slow = measure(crescendo)
    fast = measure(step)

    # A 20 dB rise over 60 s is about 3.3 dB per 10 s.
    assert slow.rise_rate == pytest.approx(3.3, abs=2.0)
    assert slow.rise_rate < fast.rise_rate - 10.0

    # The slow rise still registers as contrast against recent listening,
    # but nothing like the step.
    assert slow.startle_local > 2.0
    assert slow.startle_local < fast.startle_local - 5.0


def test_a_brief_transient_is_attenuated_by_the_window_not_by_the_percentile(
        transient):
    """The plan expected p99 to ignore a transient. It does not, and the
    reason is worth having written down.

    A 200 ms crack is 0.25% of an 80 s track, so p99 ought to discard it.
    But S is a 3 s window, so those 200 ms raise *thirty* frames — 3.75%
    of the series — and p99 lands inside them.

    What actually attenuates the crack is the window's own averaging:
    0.2 s at -1 dBFS mixed with 2.8 s at -20 gives -12.06, so a 19 dB
    peak arrives as ~8 LU. Attenuated by 11 dB, not ignored. That is
    arguably the behaviour wanted — one cymbal crash is damped but not
    pretended away — but it is not the behaviour the plan assumed, and
    anything relying on percentiles to reject short events needs to know
    it.
    """
    m = measure(transient)
    assert m.startle_delta == pytest.approx(7.9, abs=1.5)


def test_startle_delta_inverts_on_a_sustained_passage(tmp_path):
    """The case that argues `startle_delta` should not ship at all.

    Same peak, same track length: a 200 ms crack against a 30 s blast.
    The blast is the one that keeps a listener awake.

    `startle_delta` is `p99(S) - integrated`, and R128's integrated
    loudness is *gated*: with 30 s at -1 dBFS and 50 s at -20, the
    ungated mean is -5.17 LUFS, the relative gate sits 10 LU below at
    -15.17, and every quiet block falls outside it. Integrated therefore
    converges on the loud passage itself — measured -1.72 — and p99 minus
    it is zero.

    So the metric does not merely lose sensitivity as the loud passage
    grows. It *inverts*: the harmless crack scores ~7 LU and the blast
    ~0. A slider built on it would rank the dangerous track as the safer
    one.

    `startle_local` has no such failure, because it contrasts against the
    preceding 30 s rather than against a gated whole-track average — 19 LU
    for the blast against 8 for the crack, in the right order. This is the
    plan's stated reason for preferring it, but sharper than the plan put
    it, and it is A3's merge/drop question answered without needing the
    sample.

    Pinned as a test so nobody "fixes" the arithmetic later without
    meeting the reason it is like this.
    """
    crack = make_envelope(tmp_path / "crack.wav",
                          [(40, -20, -20), (0.2, -1, -1), (40, -20, -20)])
    sustained = make_envelope(tmp_path / "sustained.wav",
                              [(25, -20, -20), (30, -1, -1), (25, -20, -20)])

    brief = measure(crack)
    long = measure(sustained)

    # The defect, stated as an assertion.
    assert long.startle_delta == pytest.approx(0.0, abs=1.0)
    assert brief.startle_delta > long.startle_delta + 5.0

    # And the metric that gets it right.
    assert long.startle_local > brief.startle_local + 8.0
    assert long.startle_local == pytest.approx(19.0, abs=2.0)


# ---------------------------------------------------------------------------
# Silence
# ---------------------------------------------------------------------------

def test_digital_silence_is_marked_not_scored(tmp_path):
    """Silence must not come back as a well-behaved quiet track.

    A measured zero would sort a file we know nothing about into the
    safest part of a sleep pool.
    """
    path = tmp_path / "silent.flac"
    make_audio(path, seconds=20.0, silent=True)
    m = measure(path)

    assert m.silent is True
    assert m.measured is False
    assert m.startle_delta is None
    assert m.startle_local is None
    assert m.rise_rate is None


def test_a_track_shorter_than_the_window_is_marked_not_scored(tmp_path):
    """Under 3 s there is no valid short-term frame at all."""
    path = tmp_path / "blink.wav"
    make_envelope(path, [(1.0, -20, -20)])
    m = measure(path)

    assert m.measured is False
    assert m.startle_delta is None


def test_a_long_silent_lead_in_does_not_blow_up_the_range(tmp_path):
    """The gate that exists because six real tracks reported 150-186 dB.

    Digital silence in the first half of the file must not put the low
    percentile in the floor.
    """
    path = tmp_path / "leadin.wav"
    make_envelope(path, [(30, -120, -120), (30, -20, -20)])
    m = measure(path)

    assert m.measured
    assert m.lra < 25.0


# ---------------------------------------------------------------------------
# Parsing and plumbing
# ---------------------------------------------------------------------------

def test_parse_frames_reads_every_window_from_one_pass(constant):
    """One ffmpeg invocation yields M, S, I and LRA — no second pass."""
    from music_manager.core.quietness import find_ffmpeg
    import subprocess

    result = subprocess.run(build_command(constant, find_ffmpeg()),
                            capture_output=True, text=True)
    series = parse_frames(result.stdout)

    assert len(series.times) > 300           # 40 s at 10 Hz
    assert len(series.momentary) == len(series.times)
    assert len(series.short_term) == len(series.times)
    assert series.integrated is not None
    assert series.ffmpeg_lra is not None
    assert series.duration == pytest.approx(40.0, abs=1.0)


def test_parse_frames_drops_unparseable_values_rather_than_defaulting():
    """A fabricated frame is worse than a missing one."""
    series = parse_frames(
        "frame:0    pts:0       pts_time:0.0\n"
        "lavfi.r128.M=-20.0\n"
        "lavfi.r128.S=-21.0\n"
        "lavfi.r128.I=-22.0\n"
        "frame:1    pts:4410    pts_time:0.1\n"
        "lavfi.r128.M=nonsense\n"
        "lavfi.r128.S=-21.5\n"
        "frame:2    pts:8820    pts_time:0.2\n"
        "lavfi.r128.M=-inf\n"
        "lavfi.r128.S=-21.5\n"
    )
    # Frame 0 is complete; 1 and 2 are missing a usable M and are dropped.
    assert series.times == [0.0]
    assert series.momentary == [-20.0]
    assert series.integrated == -22.0


def test_metrics_from_series_needs_no_audio():
    """The reduction is testable without decoding anything.

    A hand-built series: 60 s flat at -20, then 30 s flat at -5.
    """
    series = LoudnessSeries()
    for i in range(900):
        t = i * FRAME_PERIOD
        level = -20.0 if t < 60.0 else -5.0
        series.times.append(round(t, 1))
        series.momentary.append(level)
        series.short_term.append(level)
    series.integrated = -16.0

    m = metrics_from_series(series)
    assert m.startle_local == pytest.approx(15.0, abs=0.5)
    assert m.rise_rate == pytest.approx(15.0, abs=0.5)
    assert m.loud_at_ms == pytest.approx(60_000, abs=200)
    assert m.head_level == pytest.approx(-4.0, abs=0.5)   # -20 against -16
    assert m.tail_level == pytest.approx(11.0, abs=0.5)   # -5 against -16


def test_unmeasured_metrics_are_none_never_zero():
    """The invariant the whole dataclass exists to hold."""
    m = QuietnessMetrics()
    assert m.startle_delta is None
    assert m.startle_local is None
    assert m.rise_rate is None
    assert m.head_level is None
    assert m.measured is False
    assert m.loudness_version == LOUDNESS_VERSION


def test_a_file_ffmpeg_cannot_read_raises(tmp_path):
    path = tmp_path / "notaudio.wav"
    path.write_bytes(b"this is not a wav file")
    with pytest.raises(MeasurementError):
        measure(path)
