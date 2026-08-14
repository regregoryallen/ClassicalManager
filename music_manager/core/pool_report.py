"""v3.8: what a shuffled pool will actually sound like (Stage C6).

Every profile shuffles, and the profile is capped at playback length —
a 250-track pool yields a ~50-track playlist. Two consequences shape
everything here.

**Sequence statistics are meaningless; pool statistics are exact.** There
is no ordering to describe, because the ordering is different every
night. What can be described is the pool, and every reachable ordering is
made of its pairs.

**The ceiling is probabilistic.** The pool's worst track appears on
roughly one night in five, so stating a flat "worst case 14 LU" overstates
the problem. "6 tracks exceed the threshold; expect 1.2 a night; 70% of
nights contain at least one" is the honest form and the actionable one.

The framing worth keeping in view: **under shuffle, seam control is
variance control of the pool.** If the levels are homogeneous every
reachable ordering is safe, and no ordering logic is needed at all —
which is why Stage D is separable and may prove unnecessary.
"""

import math
from dataclasses import dataclass, field

# A seam bigger than this is worth counting. Not a threshold on what is
# acceptable — that is the listener's call — but the granularity the
# report speaks in.
DEFAULT_SEAM_LU = 8.0

# Above this startle score a track is called disruptive in the ceiling
# figures. Chosen from A3's distribution: p75 was 10.9 and p95 18.3, so
# 15 sits where the tail begins rather than in the middle of the pack.
DEFAULT_STARTLE_LU = 15.0

# How many drop-suggestions the contribution ranking offers.
CONTRIBUTION_DEPTH = 3


@dataclass
class PoolTrack:
    """One pool member, reduced to what the seam arithmetic needs."""

    track_id: int
    title: str
    startle_local: float = None
    head_level: float = None
    tail_level: float = None
    playback_offset: float = None

    @property
    def has_seam_data(self):
        """Both edges measured, and a playback level to place them at.

        All three are required. head_level and tail_level are relative to
        their own track's body, so without the offset there is nothing to
        make two tracks comparable.
        """
        return (self.head_level is not None
                and self.tail_level is not None
                and self.playback_offset is not None)

    @property
    def head_abs(self):
        """Where this track's opening sits, in dB at the speaker."""
        return self.head_level + self.playback_offset

    @property
    def tail_abs(self):
        """Where this track's ending sits, in dB at the speaker."""
        return self.tail_level + self.playback_offset


@dataclass
class PoolReport:
    pool_size: int = 0
    playlist_length: int = 0

    # Seam figures cover only the tracks that can be placed on the axis.
    seam_eligible: int = 0
    seam_excluded: int = 0

    worst_seam: float = None
    worst_seam_from: str = ""
    worst_seam_to: str = ""
    expected_seams: float = 0.0
    seam_threshold: float = DEFAULT_SEAM_LU

    startle_measured: int = 0
    startle_unmeasured: int = 0
    loud_tracks: list = field(default_factory=list)
    expected_loud_per_playlist: float = 0.0
    chance_of_any_loud: float = 0.0
    startle_threshold: float = DEFAULT_STARTLE_LU

    contributions: list = field(default_factory=list)


def seam(previous: PoolTrack, following: PoolTrack) -> float:
    """The level jump a listener hears between two tracks, in dB.

    Both edge levels are relative to their own track's body, and under
    work-scoped ReplayGain two bodies do not play at the same level: a
    track plays at `reference + offset`. So the offsets do not cancel and
    dropping them is a real error, not a simplification.

    The case that makes it concrete: a quiet slow movement (offset -6)
    followed by a finale (offset +5), both perfectly even so both
    scoring head = tail = 0. Without the offsets that reads as a zero
    seam. It arrives as 11 dB.

    The file's own integrated loudness is *not* a term — Music Assistant
    normalises it away, which is the whole reason the offset is what
    survives.
    """
    return following.head_abs - previous.tail_abs


def _chance_at_least_one(pool_size, drawn, marked):
    """P(at least one marked track is drawn), sampling without replacement.

    The complement of drawing none of them, which is the hypergeometric
    tail. Exact rather than approximated: the pools are a few hundred
    tracks and `math.comb` is instant at that size.
    """
    if marked <= 0 or drawn <= 0 or pool_size <= 0:
        return 0.0
    if drawn >= pool_size:
        return 1.0
    if marked >= pool_size:
        return 1.0
    unmarked = pool_size - marked
    if drawn > unmarked:
        return 1.0
    return 1.0 - math.comb(unmarked, drawn) / math.comb(pool_size, drawn)


def build_report(tracks, playlist_length,
                 seam_threshold=DEFAULT_SEAM_LU,
                 startle_threshold=DEFAULT_STARTLE_LU):
    """Describe what this pool can produce under shuffle.

    `tracks` is a list of PoolTrack. `playlist_length` is how many of
    them a night actually draws — the cap is what makes the ceiling
    probabilistic rather than certain.
    """
    report = PoolReport(
        pool_size=len(tracks),
        playlist_length=min(playlist_length, len(tracks)),
        seam_threshold=seam_threshold,
        startle_threshold=startle_threshold,
    )
    if not tracks:
        return report

    # --- the startle ceiling -------------------------------------------
    measured = [t for t in tracks if t.startle_local is not None]
    report.startle_measured = len(measured)
    report.startle_unmeasured = len(tracks) - len(measured)
    report.loud_tracks = sorted(
        (t for t in measured if t.startle_local > startle_threshold),
        key=lambda t: -t.startle_local)

    drawn = report.playlist_length
    if measured and drawn:
        # Expected count is linear in the sampling fraction and needs no
        # combinatorics; the probability of *any* does.
        report.expected_loud_per_playlist = (
            len(report.loud_tracks) * drawn / len(tracks))
        report.chance_of_any_loud = _chance_at_least_one(
            len(tracks), drawn, len(report.loud_tracks))

    # --- seams ----------------------------------------------------------
    eligible = [t for t in tracks if t.has_seam_data]
    report.seam_eligible = len(eligible)
    report.seam_excluded = len(tracks) - len(eligible)
    if len(eligible) < 2:
        return report

    # The worst ordering the shuffle can reach is the loudest opening
    # after the quietest ending. A hard bound over every permutation,
    # found without enumerating any of them.
    loudest_head = max(eligible, key=lambda t: t.head_abs)
    quietest_tail = min(eligible, key=lambda t: t.tail_abs)
    report.worst_seam = loudest_head.head_abs - quietest_tail.tail_abs
    report.worst_seam_from = quietest_tail.title
    report.worst_seam_to = loudest_head.title

    # Expected count of bad seams in one night. Adjacent pairs in a
    # shuffle are ordered pairs drawn from the pool, so the count scales
    # with playlist length and not with pool size — a longer night has
    # more joins, a bigger pool just has more candidates for each.
    heads = sorted(t.head_abs for t in eligible)
    over = 0
    total_pairs = 0
    for previous in eligible:
        floor = previous.tail_abs + seam_threshold
        # heads is sorted, so everything past the insertion point exceeds
        # the threshold: O(n log n) rather than O(n^2) over the pairs.
        from bisect import bisect_right
        count = len(heads) - bisect_right(heads, floor)
        # A track cannot follow itself.
        if previous.head_abs > floor:
            count -= 1
        over += max(0, count)
        total_pairs += len(eligible) - 1
    if total_pairs:
        report.expected_seams = (
            max(0, report.playlist_length - 1) * over / total_pairs)

    report.contributions = _contributions(eligible, seam_threshold)
    return report


def _contributions(eligible, seam_threshold, depth=CONTRIBUTION_DEPTH):
    """Which tracks to drop, and what dropping them buys.

    "Drop these three and the worst case goes 14 to 8 LU" is the line
    that is actually actionable, and the report's reason for existing.

    Greedy, and cheap because the worst seam is decided entirely by two
    extremes: only the track holding the highest head, or the one holding
    the lowest tail, can be worth removing. Greedy is not provably
    optimal for a set of k removals, but it is what a person does by
    hand, and the report's job is to point at the offenders rather than
    to solve a combinatorial problem exactly.
    """
    remaining = list(eligible)
    out = []
    for _ in range(depth):
        if len(remaining) < 3:
            break
        before = (max(t.head_abs for t in remaining)
                  - min(t.tail_abs for t in remaining))
        best_track, best_after = None, before
        for candidate in (max(remaining, key=lambda t: t.head_abs),
                          min(remaining, key=lambda t: t.tail_abs)):
            rest = [t for t in remaining if t is not candidate]
            if len(rest) < 2:
                continue
            after = (max(t.head_abs for t in rest)
                     - min(t.tail_abs for t in rest))
            if after < best_after:
                best_track, best_after = candidate, after
        if best_track is None:
            break
        remaining = [t for t in remaining if t is not best_track]
        out.append({
            "track_id": best_track.track_id,
            "title": best_track.title,
            "worst_before": round(before, 1),
            "worst_after": round(best_after, 1),
        })
    return out


def describe(report: PoolReport) -> list[str]:
    """The report as lines of plain English, for the panel.

    Kept out of the UI so it can be asserted in a test, and so the
    wording of a probabilistic claim is decided once.
    """
    lines = []
    if not report.pool_size:
        return ["No tracks accepted yet."]

    lines.append(f"Pool: {report.pool_size} tracks; "
                 f"about {report.playlist_length} play each time.")

    if report.startle_unmeasured:
        lines.append(f"{report.startle_unmeasured} not measured for startle "
                     f"— run Measure quietness to include them.")
    if report.loud_tracks:
        lines.append(
            f"{len(report.loud_tracks)} exceed "
            f"{report.startle_threshold:.0f} LU startle. Expect "
            f"{report.expected_loud_per_playlist:.1f} per playlist; "
            f"{report.chance_of_any_loud * 100:.0f}% of nights contain "
            f"at least one.")
    elif report.startle_measured:
        lines.append(f"No track exceeds {report.startle_threshold:.0f} LU "
                     f"startle.")

    if report.seam_excluded:
        lines.append(f"{report.seam_excluded} excluded from the seam figures "
                     f"(not measured, or no ReplayGain).")

    # Say why there are no seam numbers, rather than just omitting them.
    # A seam is a property of a *pair*, so one eligible track produces
    # nothing — and a pool of two with one unmeasured looked like the
    # report had quietly failed.
    if report.worst_seam is None:
        if report.seam_eligible < 2:
            need = 2 - report.seam_eligible
            lines.append(
                f"No seam figures yet: they compare one track's ending "
                f"with the next one's opening, so at least two measured "
                f"tracks are needed ({need} more).")
    else:
        lines.append(
            f"Worst reachable seam: {report.worst_seam:.1f} dB — "
            f"“{report.worst_seam_from}” into “{report.worst_seam_to}”.")
        lines.append(
            f"Expect {report.expected_seams:.1f} jumps over "
            f"{report.seam_threshold:.0f} dB per playlist.")
    for item in report.contributions:
        lines.append(
            f"Drop “{item['title']}” → worst case "
            f"{item['worst_before']:.1f} → {item['worst_after']:.1f} dB.")
    return lines
