"""v3.10: find_ffmpeg resolution order — system PATH, then the imageio-ffmpeg wheel.

The imageio-ffmpeg fallback is the Windows answer (its wheel bundles a
binary), kept optional so a Linux box with system ffmpeg pays nothing. These
tests fake both layers so they run identically everywhere, whether or not
imageio-ffmpeg happens to be installed.
"""

import shutil
import sys
import types

import pytest

from music_manager.core.quietness import MeasurementError, find_ffmpeg


def test_a_system_ffmpeg_on_path_wins(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    # Even with imageio-ffmpeg importable, the system binary is preferred.
    fake = types.ModuleType("imageio_ffmpeg")
    fake.get_ffmpeg_exe = lambda: "/wheel/ffmpeg"
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", fake)
    assert find_ffmpeg() == "/usr/bin/ffmpeg"


def test_falls_back_to_the_imageio_binary_when_path_is_empty(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    fake = types.ModuleType("imageio_ffmpeg")
    fake.get_ffmpeg_exe = lambda: "/wheel/ffmpeg.exe"
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", fake)
    assert find_ffmpeg() == "/wheel/ffmpeg.exe"


def test_raises_when_neither_is_available(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    # Setting the module to None makes `import imageio_ffmpeg` raise ImportError,
    # regardless of whether the package is actually installed on this box.
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)
    with pytest.raises(MeasurementError, match="ffmpeg is not installed"):
        find_ffmpeg()
