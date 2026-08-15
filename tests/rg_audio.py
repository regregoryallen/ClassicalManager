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

def _have_ffmpeg():
    """True when find_ffmpeg() would succeed — a system binary OR the
    imageio-ffmpeg wheel. Mirroring production means these tests run on a
    Windows box that has only the wheel, not just where ffmpeg is on PATH."""
    from music_manager.core.quietness import MeasurementError, find_ffmpeg
    try:
        find_ffmpeg()
        return True
    except MeasurementError:
        return False


HAVE_FFMPEG = _have_ffmpeg()
HAVE_RSGAIN = shutil.which("rsgain") is not None

needs_ffmpeg = pytest.mark.skipif(
    not HAVE_FFMPEG, reason="ffmpeg is needed to generate test audio")
needs_rsgain = pytest.mark.skipif(
    not (HAVE_RSGAIN and HAVE_FFMPEG),
    reason="rsgain and ffmpeg are needed for measurement tests")


def make_envelope(path, segments, *, freq=440, sample_rate=44100):
    """Write a WAV whose level follows a list of `(seconds, from_db, to_db)`.

    v3.8. The quietness metrics are defined over the loudness *envelope*,
    so their fixtures have to state an envelope — a step, a crescendo, a
    transient — and `make_audio` only makes flat tones.

    Written with the stdlib rather than lavfi: an `aevalsrc` expression
    for a ramp needs its commas escaped past two levels of ffmpeg
    parsing, and the result states the shape far less clearly than the
    segment list does. These are read by tests that assert on the shape,
    so the shape should be legible in the call.

    Each segment interpolates linearly in dB, which is what "crescendo"
    means to a listener. dBFS refers to the peak of the tone.
    """
    import wave

    import numpy as np

    channels = []
    elapsed = 0.0
    for seconds, from_db, to_db in segments:
        count = int(round(seconds * sample_rate))
        if count <= 0:
            continue
        t = elapsed + np.arange(count) / sample_rate
        db = np.linspace(from_db, to_db, count, endpoint=False)
        channels.append(10.0 ** (db / 20.0) * np.sin(2 * np.pi * freq * t))
        elapsed += count / sample_rate

    signal = (np.concatenate(channels) if channels
              else np.zeros(0, dtype=float))
    # int16 with a whisker of headroom, so a 0 dBFS segment does not clip
    # to a square wave and change the very level it is there to state.
    pcm = np.clip(signal, -1.0, 1.0) * 32767.0
    stereo = np.repeat(pcm.astype("<i2")[:, None], 2, axis=1)

    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(stereo.tobytes())
    return str(path)


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
    from music_manager.core.quietness import find_ffmpeg

    amplitude = 10.0 ** (level_db / 20.0)
    channel = f"{amplitude:.6f}*sin(2*PI*{freq}*t)"
    source = ("anullsrc=r=44100:cl=stereo" if silent
              else f"aevalsrc={channel}|{channel}:s=44100:d={seconds}")
    # find_ffmpeg() rather than a bare "ffmpeg": on Windows the binary comes
    # from the imageio-ffmpeg wheel and is not on PATH.
    command = [find_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", source,
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
