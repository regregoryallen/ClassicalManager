#!/usr/bin/env python3
"""Work-scoped ReplayGain tagger (v3.7).

A sibling of main.py, not a subcommand of it. This is the only part of
the project that writes to audio files, and the only one that needs an
external scanner binary (rsgain) — keeping it out of the application
answers "does this open the tag-writeback door?" by construction rather
than by argument.

Help and --version are answered here, before typer is imported, so they
work under any interpreter. Everything else needs the virtual
environment, and this script re-executes itself there when run directly
(`./rgtag.py`) rather than failing on an import the user cannot see the
cause of.

Design: internal/archive/CM-rg-tagger-handoff.md; measured MA behaviour,
which is binding: internal/reference/CM-MA-findings.md; what shipped:
internal/active/V3-PLAN.md §v3.7.
"""

import os
import sys
from pathlib import Path

_HELP = """\
Work-scoped ReplayGain tagger

Computes ReplayGain scoped to the *work* rather than the album folder and
writes it into your audio files, so a symphony is normalized as one unit
while its movements keep their relative levels.

Usage:
  venv/bin/python rgtag.py [OPTIONS]
  ./rgtag.py [OPTIONS]              (re-runs itself in venv/)

Dry-run is the default. Nothing is written without --write.

Selecting what to work on:
  --library NAME        Restrict to one library (default: all of them).
  --list                List the selected works with their ids, and stop.
                        Measures nothing. The GUI also shows a work's id at
                        the foot of its Details window, which is easier when
                        you already have the work in front of you.
  --album TEXT          Only works whose album title contains TEXT.
  --work TEXT           Only works whose name contains TEXT.
  --work-id ID          Only this work. Repeatable. Overrides the
                        provenance filter below, but not the format one.
  --limit N             Stop after N selected works.
  --include-heuristic   Also tag works whose grouping was *guessed* by the
                        title-prefix heuristic rather than read from a tag.
                        Excluded by default: a wrong grouping writes a
                        wrong gain into files. Review them in a dry run
                        first — plain -v lists them.
  --force               Retag works that already carry current tags.

Writing:
  --write               Actually write. Required; there is no short form.
  --sandbox DIR         Copy each selected work into DIR and tag the
                        copies, leaving the library untouched. The safe
                        way to check a round trip before the first real
                        write.
  --preserve-mtime      Leave file mtimes alone. OFF by default, and
                        think before turning it on: Music Assistant
                        decides whether to re-read a file from its mtime,
                        so preserving it makes a retag invisible to MA —
                        even after a forced resync. FLAC padding absorbs
                        the new tags, so the file size does not change
                        either, and nothing downstream can tell.

After a real run, follow it with

  python main.py --cli scan-changes --library NAME

so CM's stored mtimes catch up. That path updates track rows in place and
keeps the similarity analyses; a *full* rescan restores analyses only when
mtime and size both match, so it would discard them after a tagging run.

Measurement:
  --reference LUFS      Reference loudness (default -18, ReplayGain 2.0).
                        Decoupled from Music Assistant's target, which can
                        change later without retagging.
  --ma-target LUFS      Music Assistant's normalization target (default
                        -17). Used only to predict clipping; never written.
  -j, --workers N       Parallel measurements (default: 3/4 of the cores).

Common flags:
  -y, --yes             Skip the confirmation prompt before writing.
  -v, --verbose         Include the list of works excluded by provenance.
  -q, --quiet           Suppress progress; report only.
  --config PATH         Use a custom config.json.
  --version             Print the version and exit.

Tags written to every member of a work:

  REPLAYGAIN_TRACK_GAIN           genuine per-track gain
  REPLAYGAIN_TRACK_PEAK           per-track true peak, linear
  REPLAYGAIN_ALBUM_GAIN           the WORK gain, identical across members
  REPLAYGAIN_ALBUM_PEAK           the work peak, linear
  REPLAYGAIN_REFERENCE_LOUDNESS   the reference used
  CM_GAIN_SCOPE                   'work' — marks ALBUM_GAIN as work-scoped
  CM_GAIN_WORK_KEY                membership digest; changes force a retag
  CM_GAIN_VERSION                 computation version

TRACK_GAIN keeps its ordinary meaning, so Kodi and other players are
unaffected. Existing tags this tool does not own are left alone.

Requires rsgain, which the application itself does not:
  sudo apt install rsgain

Examples:
  ./rgtag.py --library MainMusic
  ./rgtag.py --library MainMusic -v
  ./rgtag.py --library MainMusic --limit 5 --sandbox /tmp/rgtest
  ./rgtag.py --library MainMusic --limit 5 --write
"""

_NO_VENV = """\
Error: this tool needs the project's virtual environment.

  No interpreter found at {venv}

Create it, or run the tool with whichever interpreter has the
dependencies installed:

  python3 -m venv venv && venv/bin/pip install -r requirements.txt
  venv/bin/python rgtag.py --help
"""


def _reexec_in_venv():
    """Re-run this script under venv/bin/python.

    Running `./rgtag.py` picks up the system interpreter, which does not
    have typer or peewee. Failing with a bare ModuleNotFoundError puts
    the cause several steps away from the fix, so the venv is used when
    it is there and named plainly when it is not.
    """
    venv_dir = Path(__file__).resolve().parent / "venv"
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        sys.stderr.write(_NO_VENV.format(venv=venv_python))
        raise SystemExit(1)
    # Compare prefixes, not executables: venv/bin/python is a symlink to
    # the system interpreter, so resolving the two paths makes them equal
    # and the guard would fire on the first attempt instead of the second.
    if Path(sys.prefix) == venv_dir:
        raise                       # already there: the real import error
    os.execv(str(venv_python), [str(venv_python), os.path.abspath(__file__)]
             + sys.argv[1:])


def main():
    """Answer help and version directly; hand everything else to typer."""
    if {"-h", "--help", "-?"} & set(sys.argv[1:]):
        print(_HELP)
        return

    if "--version" in sys.argv[1:]:
        # Read without importing the package, so --version works even
        # from an interpreter that has none of the dependencies.
        source = (Path(__file__).resolve().parent / "music_manager"
                  / "__init__.py").read_text()
        version = source.split('__version__ = "')[1].split('"')[0]
        print(f"Classical Manager ReplayGain tagger {version}")
        return

    try:
        from music_manager.loudness.cli import app
    except ModuleNotFoundError:
        _reexec_in_venv()
        return                      # execv does not return; for clarity
    app()


if __name__ == "__main__":
    main()
