"""v3.7: synthetic audio for the ReplayGain tagger tests.

Generated with ffmpeg rather than committed as binary fixtures, so the
level of every test file is stated in the test that needs it and a
20 dB difference between two movements is visible in the source.

ffmpeg is used only to *make* the fixtures. The tagger itself does not
need it — it measures with rsgain and writes with mutagen.
"""

import shutil
import subprocess

import pytest

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
HAVE_RSGAIN = shutil.which("rsgain") is not None

needs_ffmpeg = pytest.mark.skipif(
    not HAVE_FFMPEG, reason="ffmpeg is needed to generate test audio")
needs_rsgain = pytest.mark.skipif(
    not (HAVE_RSGAIN and HAVE_FFMPEG),
    reason="rsgain and ffmpeg are needed for measurement tests")


def make_audio(path, *, level_db=-6.0, seconds=2.0, freq=440, silent=False):
    """Write a stereo test file that peaks at `level_db` dBFS.

    The amplitude is set in the source expression rather than by a
    `volume` filter over lavfi's `sine`: that source has a fixed
    amplitude of about -18 dBFS, so a `volume` offset would make
    `level_db` a relative figure that does not match its name. `aevalsrc`
    takes the amplitude directly, so a file asked for at -3 dBFS really
    peaks at -3.00.

    The extension chooses the format. Pink noise would model real music
    better, but a tone is deterministic across ffmpeg builds, which
    matters more for a test that asserts on tag *values*.
    """
    amplitude = 10.0 ** (level_db / 20.0)
    channel = f"{amplitude:.6f}*sin(2*PI*{freq}*t)"
    source = ("anullsrc=r=44100:cl=stereo" if silent
              else f"aevalsrc={channel}|{channel}:s=44100:d={seconds}")
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
               "-t", str(seconds), "-ac", "2"]
    if str(path).endswith(".mp3"):
        command += ["-c:a", "libmp3lame", "-b:a", "128k"]
    elif str(path).endswith(".flac"):
        command += ["-c:a", "flac"]
    command.append(str(path))

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")
    return str(path)
