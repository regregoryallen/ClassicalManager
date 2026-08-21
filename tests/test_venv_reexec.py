"""Re-entering the virtual environment (v3.11).

rgtag.py hardcoded venv/bin/python, which does not exist on Windows —
running it there reported "No interpreter found" naming a path that is
correctly absent. main.py had no re-exec at all.

These pin the platform split and the guard that stops a genuine import
error being mistaken for a missing environment.
"""

import sys

import pytest

from music_manager._venv import in_venv, reexec, venv_python_path


# ---------------------------------------------------------------------------
# Where the interpreter is
# ---------------------------------------------------------------------------

def test_posix_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    assert venv_python_path(tmp_path) == tmp_path / "venv" / "bin" / "python"


def test_windows_layout(monkeypatch, tmp_path):
    """The bug this was written for: no bin/, and a .exe suffix."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert venv_python_path(tmp_path) == \
        tmp_path / "venv" / "Scripts" / "python.exe"


def test_macos_uses_the_posix_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert venv_python_path(tmp_path) == tmp_path / "venv" / "bin" / "python"


# ---------------------------------------------------------------------------
# Whether we are already inside it
# ---------------------------------------------------------------------------

def test_in_venv_compares_prefixes_not_executables(monkeypatch, tmp_path):
    """venv/bin/python is a symlink to the system interpreter on POSIX.

    Resolving the two executables makes them equal, so a guard written
    that way fires on the first attempt instead of the second.
    """
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
    assert in_venv(tmp_path)


def test_not_in_venv_for_a_different_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", "/usr")
    assert not in_venv(tmp_path)


# ---------------------------------------------------------------------------
# Re-exec
# ---------------------------------------------------------------------------

def test_a_missing_venv_names_the_path_it_looked_for(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        reexec(tmp_path, tmp_path / "main.py")

    assert excinfo.value.code == 1
    assert str(venv_python_path(tmp_path)) in capsys.readouterr().err


def test_windows_waits_for_the_child_rather_than_execv(monkeypatch, tmp_path):
    """execv on Windows lets the shell run on while the child works.

    A .bat wrapper or a redirect would see the command finish
    immediately and out of order, so that path uses subprocess and
    passes the child's exit code back.
    """
    interp = tmp_path / "venv" / "Scripts" / "python.exe"
    interp.parent.mkdir(parents=True)
    interp.write_text("")
    monkeypatch.setattr(sys, "platform", "win32")

    calls = []
    monkeypatch.setattr("subprocess.call",
                        lambda args: calls.append(args) or 3)
    monkeypatch.setattr(sys, "argv", ["main.py", "--cli", "scan"])

    with pytest.raises(SystemExit) as excinfo:
        reexec(tmp_path, tmp_path / "main.py")

    assert excinfo.value.code == 3          # the child's code, not 0
    assert calls[0][0] == str(interp)
    assert calls[0][2:] == ["--cli", "scan"]


def test_explicit_argv_overrides_sys_argv(monkeypatch, tmp_path):
    """main.py strips --cli and --config out of sys.argv before routing.

    A re-exec reading sys.argv afterwards would relaunch with a
    different command than the one that was typed.
    """
    interp = tmp_path / "venv" / "Scripts" / "python.exe"
    interp.parent.mkdir(parents=True)
    interp.write_text("")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["main.py", "scan"])   # already mangled

    calls = []
    monkeypatch.setattr("subprocess.call",
                        lambda args: calls.append(args) or 0)

    with pytest.raises(SystemExit):
        reexec(tmp_path, tmp_path / "main.py",
               argv=["--cli", "scan", "--library", "X"])

    assert calls[0][2:] == ["--cli", "scan", "--library", "X"]


def test_the_remedy_matches_the_platform(monkeypatch, tmp_path, capsys):
    """A POSIX pip path sends a Windows user to a file that is not there.

    That is the same class of mistake as the hardcoded venv/bin/python
    this module was written to fix, so it is worth pinning.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(SystemExit):
        reexec(tmp_path, tmp_path / "main.py")
    err = capsys.readouterr().err
    assert r"venv\Scripts\pip" in err
    assert "venv/bin/pip" not in err

    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SystemExit):
        reexec(tmp_path, tmp_path / "main.py")
    err = capsys.readouterr().err
    assert "venv/bin/pip" in err
