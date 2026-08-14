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


# ---------------------------------------------------------------------------
# C5 — auditioning the loud moment
# ---------------------------------------------------------------------------

def test_the_excerpt_starts_before_the_loud_moment(tmp_path, step):
    """Two seconds of lead, because the jump is only startling in context.

    The same fortissimo is alarming or unremarkable depending on what
    preceded it, so an excerpt that begins at the moment itself would
    show the one thing that cannot be judged alone.
    """
    import wave

    from music_manager.core.quietness import (
        AUDITION_LEAD_S, AUDITION_LENGTH_S, extract_excerpt,
    )

    # The step fixture jumps at 40 s.
    excerpt = extract_excerpt(step, at_ms=40_000, out_dir=tmp_path)
    assert excerpt.exists()

    with wave.open(str(excerpt)) as handle:
        seconds = handle.getnframes() / handle.getframerate()
    assert seconds == pytest.approx(AUDITION_LENGTH_S, abs=0.5)

    # It really does span the transition: quiet at the start, loud after.
    #
    # Measured from the samples rather than from head_level/tail_level.
    # Those windows are 10 s each and the excerpt is 12 s, so they overlap
    # almost completely and cannot differ — the metrics are built for
    # whole tracks, and an excerpt is not one.
    import array

    with wave.open(str(excerpt)) as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        samples = array.array("h", handle.readframes(handle.getnframes()))

    def rms(seconds_from, seconds_to):
        lo = int(seconds_from * rate) * channels
        hi = int(seconds_to * rate) * channels
        window = samples[lo:hi]
        return (sum(float(s) * s for s in window) / max(len(window), 1)) ** 0.5

    quiet = rms(0.0, AUDITION_LEAD_S - 0.2)
    loud = rms(AUDITION_LEAD_S + 0.2, AUDITION_LEAD_S + 4.0)
    assert loud > quiet * 5, f"quiet={quiet:.0f} loud={loud:.0f}"


def test_a_loud_moment_in_the_first_seconds_does_not_seek_negative(tmp_path):
    """Clamped at zero. ffmpeg treats a negative -ss as an error."""
    from music_manager.core.quietness import extract_excerpt

    path = tmp_path / "early.wav"
    make_envelope(path, [(1, -30, -30), (30, -6, -6)])
    excerpt = extract_excerpt(path, at_ms=500, out_dir=tmp_path)
    assert excerpt.exists()


def test_the_excerpt_is_wav_so_no_encoder_is_required(tmp_path, step):
    """A build without libmp3lame must still be able to audition."""
    from music_manager.core.quietness import extract_excerpt

    excerpt = extract_excerpt(step, at_ms=40_000, out_dir=tmp_path)
    assert excerpt.suffix == ".wav"
    assert excerpt.read_bytes()[:4] == b"RIFF"


def test_auditioning_the_same_moment_twice_reuses_one_file(tmp_path, step):
    """Otherwise a review session litters the temp directory."""
    from music_manager.core.quietness import extract_excerpt

    first = extract_excerpt(step, at_ms=40_000, out_dir=tmp_path)
    second = extract_excerpt(step, at_ms=40_000, out_dir=tmp_path)
    assert first == second
    assert len(list(tmp_path.glob("*.wav"))) == 1


def test_extracting_from_a_file_ffmpeg_cannot_read_raises(tmp_path):
    from music_manager.core.quietness import MeasurementError, extract_excerpt

    bad = tmp_path / "notaudio.wav"
    bad.write_bytes(b"nope")
    with pytest.raises(MeasurementError):
        extract_excerpt(bad, at_ms=1000, out_dir=tmp_path)


def test_prune_removes_stale_excerpts_but_not_fresh_ones(tmp_path):
    """Excerpts are swept by age, not deleted after playing.

    Deleting on completion would pull the file out from under the
    external player, which is how an audition becomes silence.
    """
    import os
    import time

    from music_manager.core.quietness import prune_auditions

    old = tmp_path / "old.wav"
    new = tmp_path / "new.wav"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    stale = time.time() - 7200
    os.utime(old, (stale, stale))

    import music_manager.core.quietness as q
    original = q.audition_dir
    q.audition_dir = lambda: tmp_path
    try:
        assert prune_auditions(older_than_s=3600) == 1
    finally:
        q.audition_dir = original

    assert not old.exists()
    assert new.exists()


def test_trailing_silence_does_not_become_the_tail_level(tmp_path):
    """The A3 finding that changed a specification, not a parameter.

    Over a 300-track sample, tail_level ran to -62 LU with 69 of 299
    tracks below -20, while head_level bottomed out at -27 with only 7
    below -20. That asymmetry is not musical — it is trailing silence in
    the rips. Ungated it made the pool report's worst reachable seam
    65.7 LU: a statement about ripping, and not one curation could fix
    by dropping tracks.

    Two files with identical music, one with fifteen seconds of digital
    silence appended. Their tail levels must agree.
    """
    from music_manager.core.quietness import measure

    music = [(30, -20, -20), (20, -14, -14)]
    clean = make_envelope(tmp_path / "clean.wav", music)
    padded = make_envelope(tmp_path / "padded.wav",
                           music + [(15, -120, -120)])

    a, b = measure(clean), measure(padded)
    assert a.measured and b.measured
    assert a.tail_level == pytest.approx(b.tail_level, abs=1.5)
    # And the gate has not simply thrown the tail away.
    assert b.tail_level is not None
    assert b.tail_level > -20.0


def test_a_leading_silence_does_not_become_the_head_level(tmp_path):
    """Same treatment at the other end, for the same reason."""
    from music_manager.core.quietness import measure

    music = [(20, -14, -14), (30, -20, -20)]
    clean = make_envelope(tmp_path / "clean2.wav", music)
    padded = make_envelope(tmp_path / "padded2.wav",
                           [(15, -120, -120)] + music)

    a, b = measure(clean), measure(padded)
    assert a.head_level == pytest.approx(b.head_level, abs=1.5)


# ---------------------------------------------------------------------------
# SIGTTIN — the freeze that was not a deadlock
# ---------------------------------------------------------------------------

def test_ffmpeg_never_inherits_the_terminal():
    """ffmpeg reading stdin suspended the whole application.

    ffmpeg watches stdin for interactive keys (`q` to quit), and
    `capture_output=True` redirects stdout and stderr but leaves stdin
    inherited. Start the GUI as a background job — `python main.py &`,
    which is how it is launched from a terminal — and a background
    process reading the controlling terminal takes SIGTTIN. SIGTTIN
    suspends the entire process group.

    The application then stops dead: no repaint, no response, windows
    still draggable because that is the window manager. It presents
    exactly as a deadlock, and `jobs` reports the truth — Stopped.

    Both defences are asserted. `-nostdin` asks ffmpeg not to read the
    terminal; `stdin=DEVNULL` makes it unable to. The failure mode is the
    whole application freezing, which is worth two locks.
    """
    import pathlib
    import re

    source = pathlib.Path("music_manager/core/quietness.py").read_text()

    for command_builder in ("build_command", "extract_excerpt"):
        start = source.index(f"def {command_builder}")
        body = source[start:start + 2000]
        assert '"-nostdin"' in body, f"{command_builder} omits -nostdin"

    calls = re.findall(r"subprocess\.run\((.*?)\)\n", source, re.S)
    assert calls, "no subprocess calls found — has this module moved?"
    for call in calls:
        assert "stdin=subprocess.DEVNULL" in call, (
            "subprocess.run without stdin=DEVNULL:\n" + call[:200])


def test_the_measure_command_carries_nostdin(tmp_path):
    """Asserted on the built command, not only on the source."""
    from music_manager.core.quietness import build_command

    assert "-nostdin" in build_command(tmp_path / "x.flac", "ffmpeg")


def test_launching_a_player_does_not_inherit_the_terminal():
    """Same defect, same consequence — and C5's audition uses this path.

    A media player that reads stdin would suspend the GUI exactly as
    ffmpeg did.
    """
    import pathlib

    source = pathlib.Path(
        "music_manager/interfaces/gui/app.py").read_text()
    start = source.index("def _open_in_player")
    body = source[start:start + 1600]

    assert "stdin=subprocess.DEVNULL" in body
    for launcher in ('"open"', '"xdg-open"'):
        assert launcher in body
        assert "**detached" in body
