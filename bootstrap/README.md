# Bootstrap installers

A small download that fetches the current source from GitHub, runs the real
installer, and removes what it downloaded.

These are what the user guide links to. They are the only files in the project
meant to be downloaded on their own, so they are self-contained: no imports, no
helper files, nothing from the repository they are about to fetch.

| File | Platform |
|------|----------|
| `install-classical-manager.sh` | Linux, macOS |
| `install-classical-manager.bat` | Windows — the file to double-click |
| `install-classical-manager.ps1` | Windows — where the work happens |

Windows takes two files because a `.ps1` cannot be started by double-clicking,
and a first-time user who tries meets the execution-policy wall instead of an
installer. The `.bat` exists only to launch the `.ps1` with
`-ExecutionPolicy Bypass`, which applies to that one process and changes no
machine setting.

## What they do, and deliberately do not

Each one:

1. Checks for Python 3.12+ and **stops with instructions if it is missing** —
   installing Python is a system-wide change a bootstrap should not make
   unasked.
2. Downloads the zipball/tarball for a ref (default `master`, overridable with
   `--ref` / `-Ref`), so Git is not required.
3. Verifies the archive extracts and contains `install.sh`/`install.bat`,
   `main.py` and `requirements.txt` before executing anything out of it.
4. Runs the real installer, which is what asks the configuration questions and
   creates the launchers.
5. Deletes the temporary directory — on success, on failure, and on Ctrl-C.

Updating is the same command: `install.sh` and `install.bat` both handle an
existing installation.

## Changing them

They are duplicated by design — a shared helper would defeat "one file to
download". If you change the behaviour of one, change the other to match; the
step order above is the contract they both keep.

Test the Linux one without installing anything by replacing the `bash
install.sh` line with an `echo`, which exercises the download, the layout
detection and the verification but stops at the handover.
