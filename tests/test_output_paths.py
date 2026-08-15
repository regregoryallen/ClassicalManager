"""Output paths: a quoted "~" must reach the filesystem expanded.

`cron.m3u_output_dir` defaults to `~/Playlists`, and both the cron script
and the webhook pass it quoted, so the shell never expands it. Python does
not either — without this, the tilde became a literal directory under the
process's working directory.
"""

from pathlib import Path

from music_manager.core.engine import EngineResult
from music_manager.interfaces.cli import _output_result


def _empty_result():
    return EngineResult(playlist=[], profile_name="P", shuffle_mode="none",
                        work_integrity="strict", length_mode="none",
                        length_value=None, seed=None)


def _fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # os.path.expanduser("~") reads USERPROFILE on Windows, not HOME.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    home_dir = tmp_path / "Playlists"
    home_dir.mkdir()
    return home_dir


def test_a_leading_tilde_is_expanded_to_the_home_directory(tmp_path,
                                                           monkeypatch):
    playlists = _fake_home(tmp_path, monkeypatch)

    _output_result(None, _empty_result(), format="json",
                   output="~/Playlists/p.json", quiet=True)

    assert (playlists / "p.json").is_file()
    assert not Path("~").exists()  # not a literal directory under the cwd


def test_an_ordinary_path_is_left_alone(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    output = tmp_path / "elsewhere.json"

    _output_result(None, _empty_result(), format="json",
                   output=str(output), quiet=True)

    assert output.is_file()
