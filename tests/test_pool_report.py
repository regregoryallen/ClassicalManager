"""v3.8: pool statistics for a shuffled, length-capped profile (C6).

The plan asks for these to be asserted exactly, because they are
arithmetic rather than judgement: a hand-built pool with known levels has
one right answer for its worst seam and its expected count.
"""

import pytest

from music_manager.core.pool_report import (
    PoolTrack,
    _chance_at_least_one,
    build_report,
    describe,
    seam,
)


def track(track_id, title="t", startle=None, head=None, tail=None,
          offset=None):
    return PoolTrack(track_id=track_id, title=title, startle_local=startle,
                     head_level=head, tail_level=tail,
                     playback_offset=offset)


# ---------------------------------------------------------------------------
# The seam quantity
# ---------------------------------------------------------------------------

def test_the_seam_carries_both_offsets():
    """The correction that started all of this.

    A quiet slow movement (offset -6) into a finale (offset +5), both
    perfectly even so both scoring head = tail = 0. Head and tail alone
    read a zero seam. It arrives as 11 dB.
    """
    quiet = track(1, "slow movement", head=0.0, tail=0.0, offset=-6.0)
    loud = track(2, "finale", head=0.0, tail=0.0, offset=+5.0)

    assert seam(quiet, loud) == pytest.approx(11.0)
    # And the naive version, for contrast.
    assert loud.head_level - quiet.tail_level == 0.0


def test_the_seam_is_directional():
    """Loud-into-quiet is a drop, not a jump. Shuffle reaches both."""
    quiet = track(1, head=0.0, tail=0.0, offset=-6.0)
    loud = track(2, head=0.0, tail=0.0, offset=+5.0)

    assert seam(quiet, loud) == pytest.approx(11.0)
    assert seam(loud, quiet) == pytest.approx(-11.0)


def test_offsets_cancel_when_both_tracks_are_standalone():
    """Two standalone works both play at reference; only the edges differ."""
    a = track(1, head=-2.0, tail=-8.0, offset=0.0)
    b = track(2, head=+1.0, tail=-3.0, offset=0.0)
    assert seam(a, b) == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# Worst reachable seam
# ---------------------------------------------------------------------------

def test_worst_seam_is_the_loudest_head_after_the_quietest_tail():
    """A hard bound over every ordering the shuffle can reach."""
    tracks = [
        track(1, "quiet ending", head=0.0, tail=-12.0, offset=0.0),
        track(2, "loud opening", head=+3.0, tail=0.0, offset=+2.0),
        track(3, "middling", head=-1.0, tail=-2.0, offset=0.0),
    ]
    report = build_report(tracks, playlist_length=3)

    # head_abs of the loudest is 3 + 2 = 5; tail_abs of the quietest is -12.
    assert report.worst_seam == pytest.approx(17.0)
    assert report.worst_seam_from == "quiet ending"
    assert report.worst_seam_to == "loud opening"


def test_a_homogeneous_pool_has_no_seam_worth_reporting():
    """The framing: under shuffle, seam control is variance control.

    If the levels are uniform, every reachable ordering is safe and no
    ordering logic is needed — which is why Stage D is separable.
    """
    tracks = [track(i, head=0.0, tail=0.0, offset=0.0) for i in range(1, 11)]
    report = build_report(tracks, playlist_length=5)

    assert report.worst_seam == pytest.approx(0.0)
    assert report.expected_seams == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Expected seams
# ---------------------------------------------------------------------------

def test_expected_seams_scales_with_playlist_length_not_pool_size():
    """(n-1) x P(a random ordered pair exceeds the threshold).

    A longer playlist has more joins; a bigger pool just has more
    candidates for each one.
    """
    # Every track ends at 0, so a seam is decided entirely by what opens
    # next: only track 3, at +10, clears the 8 dB threshold. Three of the
    # 4x3 = 12 ordered pairs therefore qualify — anything into track 3,
    # and a track cannot follow itself.
    tracks = [
        track(1, head=0.0, tail=0.0, offset=0.0),
        track(2, head=0.0, tail=0.0, offset=0.0),
        track(3, head=+10.0, tail=0.0, offset=0.0),
        track(4, head=0.0, tail=0.0, offset=0.0),
    ]
    p = 3 / 12

    short = build_report(tracks, playlist_length=2, seam_threshold=8.0)
    long = build_report(tracks, playlist_length=4, seam_threshold=8.0)

    assert short.expected_seams == pytest.approx(1 * p)
    assert long.expected_seams == pytest.approx(3 * p)


def test_a_track_cannot_follow_itself():
    """Self-pairs are not reachable and must not inflate the estimate."""
    tracks = [
        track(1, head=+5.0, tail=-5.0, offset=0.0),
        track(2, head=0.0, tail=0.0, offset=0.0),
    ]
    # Track 1 into itself would be a 10 dB seam; it is not a real pair.
    report = build_report(tracks, playlist_length=2, seam_threshold=8.0)
    # Only 1->1 would qualify, and it is excluded, so nothing is expected.
    assert report.expected_seams == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# The probabilistic ceiling
# ---------------------------------------------------------------------------

def test_the_ceiling_is_stated_probabilistically():
    """Stating a flat worst case would overstate the problem.

    The plan's own worked example: 6 loud tracks in a 250-track pool that
    draws 50 gives 1.2 per playlist and roughly 70% containing one.
    """
    tracks = [track(i, head=0.0, tail=0.0, offset=0.0, startle=2.0)
              for i in range(1, 245)]
    tracks += [track(1000 + i, head=0.0, tail=0.0, offset=0.0, startle=25.0)
               for i in range(6)]

    report = build_report(tracks, playlist_length=50, startle_threshold=15.0)

    assert len(report.loud_tracks) == 6
    assert report.expected_loud_per_playlist == pytest.approx(1.2, abs=0.05)
    assert report.chance_of_any_loud == pytest.approx(0.70, abs=0.05)


def test_chance_of_any_is_exact_not_approximated():
    """Hypergeometric, computed with comb rather than a 1-(1-p)^k estimate."""
    # 1 marked track in a pool of 4, drawing 2: exactly half the time.
    assert _chance_at_least_one(4, 2, 1) == pytest.approx(0.5)
    # Drawing the whole pool is certain.
    assert _chance_at_least_one(10, 10, 1) == pytest.approx(1.0)
    # Nothing marked, nothing to fear.
    assert _chance_at_least_one(10, 5, 0) == 0.0


def test_drawing_the_whole_pool_makes_the_ceiling_certain():
    """With no cap, the worst track is on every playlist."""
    tracks = [track(i, head=0.0, tail=0.0, offset=0.0, startle=2.0)
              for i in range(1, 10)]
    tracks.append(track(99, head=0.0, tail=0.0, offset=0.0, startle=25.0))

    report = build_report(tracks, playlist_length=999)
    assert report.playlist_length == 10
    assert report.chance_of_any_loud == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Contribution ranking — the actionable line
# ---------------------------------------------------------------------------

def test_contributions_name_the_tracks_that_own_the_worst_case():
    """"Drop these and the worst case goes 14 to 8" is the point of C6."""
    tracks = [track(i, f"ordinary {i}", head=0.0, tail=-2.0, offset=0.0)
              for i in range(1, 8)]
    tracks.append(track(90, "shouts", head=+8.0, tail=0.0, offset=0.0))
    tracks.append(track(91, "fades away", head=0.0, tail=-6.0, offset=0.0))

    report = build_report(tracks, playlist_length=5)
    assert report.worst_seam == pytest.approx(14.0)

    titles = [c["title"] for c in report.contributions]
    assert "shouts" in titles
    first = report.contributions[0]
    assert first["worst_after"] < first["worst_before"]


def test_contributions_stop_when_nothing_more_helps():
    """A homogeneous pool has no offender to name."""
    tracks = [track(i, head=0.0, tail=0.0, offset=0.0) for i in range(1, 8)]
    assert build_report(tracks, playlist_length=5).contributions == []


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

def test_a_track_without_an_offset_is_excluded_from_the_seam_figures():
    """An untagged file receives no gain, so it is not on this axis.

    Counted and reported rather than dropped silently — and never scored
    as zero, which would place the least-known track in the safest spot.
    """
    tracks = [
        track(1, head=0.0, tail=-10.0, offset=0.0),
        track(2, head=+2.0, tail=0.0, offset=0.0),
        track(3, "untagged", head=+40.0, tail=-40.0, offset=None),
    ]
    report = build_report(tracks, playlist_length=3)

    assert report.seam_eligible == 2
    assert report.seam_excluded == 1
    # The wild untagged values must not reach the worst case.
    assert report.worst_seam == pytest.approx(12.0)


def test_an_unmeasured_track_is_excluded_from_both_sets():
    tracks = [
        track(1, head=0.0, tail=0.0, offset=0.0, startle=3.0),
        track(2, head=None, tail=None, offset=0.0, startle=None),
    ]
    report = build_report(tracks, playlist_length=2)

    assert report.startle_measured == 1
    assert report.startle_unmeasured == 1
    assert report.seam_eligible == 1
    assert report.seam_excluded == 1


def test_an_empty_pool_says_so_rather_than_dividing_by_zero():
    report = build_report([], playlist_length=50)
    assert report.pool_size == 0
    assert report.worst_seam is None
    assert describe(report) == ["No tracks accepted yet."]


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

def test_describe_states_the_ceiling_as_a_frequency_not_a_certainty():
    tracks = [track(i, head=0.0, tail=0.0, offset=0.0, startle=2.0)
              for i in range(1, 245)]
    tracks += [track(1000 + i, head=0.0, tail=0.0, offset=0.0, startle=25.0)
               for i in range(6)]

    text = " ".join(describe(build_report(tracks, playlist_length=50)))
    assert "A typical playlist draws" in text
    assert "contain at least one" in text
    # Not a bare "worst case", which would overstate a capped draw.
    assert "6 exceed" in text
    # And nothing about nights: sleep prompted this, it does not define it.
    assert "night" not in text.lower()


def test_describe_reports_exclusions_so_they_are_not_silent():
    tracks = [track(1, head=0.0, tail=0.0, offset=0.0, startle=1.0),
              track(2, head=0.0, tail=0.0, offset=None, startle=None)]
    text = " ".join(describe(build_report(tracks, playlist_length=2)))

    assert "not measured" in text
    assert "excluded from the seam figures" in text


def test_absent_seam_figures_explain_themselves(tmp_path=None):
    """One measured track produces no seam, and must say why.

    A seam compares one track's ending with the next one's opening, so it
    is a property of a pair. With a two-track pool and one of them
    unmeasured the report simply omitted every seam line, which read as a
    silent failure rather than as "not enough data yet".
    """
    tracks = [track(1, "measured", head=0.0, tail=0.0, offset=0.0,
                    startle=3.0),
              track(2, "unmeasured", startle=None)]
    report = build_report(tracks, playlist_length=2)
    text = " ".join(describe(report))

    assert report.seam_eligible == 1
    assert report.worst_seam is None
    assert "No seam figures yet" in text
    assert "1 more" in text


def test_seam_figures_appear_as_soon_as_two_tracks_qualify():
    tracks = [track(1, "a", head=0.0, tail=-4.0, offset=0.0),
              track(2, "b", head=+2.0, tail=0.0, offset=0.0)]
    text = " ".join(describe(build_report(tracks, playlist_length=2)))

    assert "No seam figures yet" not in text
    assert "Worst reachable seam" in text


def test_the_worst_seam_is_never_a_track_following_itself():
    """A two-track pool named "Pavane into Pavane" as its worst case.

    The worst seam was taken as max(head) - min(tail) over the pool, with
    no check that those were two different tracks. When one piece holds
    both extremes — easy with a small pool — the answer is an ordering
    the shuffle can never produce. `expected_seams` had always excluded
    self-pairs; this now agrees with it.
    """
    # One track owns both the highest head and the lowest tail.
    tracks = [
        track(1, "Pavane", head=+5.0, tail=-9.0, offset=0.0),
        track(2, "Nocturne", head=-1.0, tail=-2.0, offset=0.0),
    ]
    report = build_report(tracks, playlist_length=2)

    assert report.worst_seam_from != report.worst_seam_to
    # Reachable orderings are Pavane->Nocturne (-1 - -9 = 8) and
    # Nocturne->Pavane (5 - -2 = 7). The worst is 8.
    assert report.worst_seam == pytest.approx(8.0)
    assert report.worst_seam_from == "Pavane"
    assert report.worst_seam_to == "Nocturne"


def test_the_worst_seam_still_finds_the_true_extremes_when_they_differ():
    """The common case must not be disturbed by the self-pair guard."""
    tracks = [
        track(1, "fades out", head=0.0, tail=-12.0, offset=0.0),
        track(2, "bursts in", head=+4.0, tail=0.0, offset=0.0),
        track(3, "ordinary", head=-1.0, tail=-3.0, offset=0.0),
    ]
    report = build_report(tracks, playlist_length=3)

    assert report.worst_seam == pytest.approx(16.0)
    assert report.worst_seam_from == "fades out"
    assert report.worst_seam_to == "bursts in"


def test_the_report_is_not_written_only_for_sleep():
    """Sleep prompted the feature; it does not define it.

    The same figures describe any listening where an abrupt jump in level
    is unwelcome — reading, dining, working, a long drive — and wording
    that assumes bedtime makes the panel read as belonging to someone
    else's use case.
    """
    tracks = [track(i, f"t{i}", head=0.0, tail=-3.0, offset=0.0, startle=20.0)
              for i in range(1, 6)]
    text = " ".join(describe(build_report(tracks, playlist_length=3))).lower()

    for word in ("night", "sleep", "asleep", "bedtime", "wake"):
        assert word not in text, f"pool report still says {word!r}"
