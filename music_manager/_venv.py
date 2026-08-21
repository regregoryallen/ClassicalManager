"""Finding and re-entering the project's virtual environment.

Used by the two entry scripts (main.py, rgtag.py) when the interpreter
running them cannot import the dependencies. Deliberately stdlib-only:
this is the code that runs *because* the environment is wrong, so it
must not need anything from that environment to work.
"""

import os
import sys
from pathlib import Path


def venv_python_path(project_root):
    """Where this project's virtual-environment interpreter lives.

    The layout differs by platform and nothing bridges the two: POSIX
    puts it at venv/bin/python, Windows at venv\\Scripts\\python.exe.
    Hardcoding the POSIX form is why rgtag.py on Windows reported "No
    interpreter found" naming a path that is correctly absent.
    """
    venv_dir = Path(project_root) / "venv"
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def in_venv(project_root):
    """True when the running interpreter is already the project's venv.

    Compares prefixes rather than executables: on POSIX venv/bin/python
    is a symlink to the system interpreter, so resolving both paths
    makes them equal and a re-exec guard would fire on the first attempt
    instead of the second.
    """
    return Path(sys.prefix) == Path(project_root) / "venv"


def reexec(project_root, script, argv=None):
    """Re-run *script* under the venv interpreter. Does not return.

    Raises SystemExit(1) with an explanation on stderr when there is no
    venv to re-enter — a missing interpreter named plainly beats a
    ModuleNotFoundError several steps from its cause.
    """
    venv_python = venv_python_path(project_root)
    if not venv_python.exists():
        sys.stderr.write(NO_VENV.format(venv=venv_python,
                                        create=_create_hint()))
        raise SystemExit(1)

    args = [str(venv_python), os.path.abspath(script)] + list(
        sys.argv[1:] if argv is None else argv)
    if sys.platform == "win32":
        # execv on Windows is not a replacement: the parent exits at
        # once and the shell regains control while the child is still
        # running, so a .bat wrapper or a redirect sees the command
        # "finish" immediately and out of order. Wait for it instead.
        import subprocess
        raise SystemExit(subprocess.call(args))
    os.execv(str(venv_python), args)


def _create_hint():
    """The commands that create the venv, for the platform in hand.

    Printing the POSIX form to a Windows user sends them to a pip that
    is not there — the exact class of mistake this module exists to fix.
    """
    if sys.platform == "win32":
        return ("  python -m venv venv\n"
                "  venv\\Scripts\\pip install -r requirements.txt")
    return ("  python3 -m venv venv\n"
            "  venv/bin/pip install -r requirements.txt")


NO_VENV = """\
Error: this tool needs the project's virtual environment.

  No interpreter found at {venv}

Create it with:

{create}

or run the tool with whichever interpreter already has the
dependencies installed.
"""
