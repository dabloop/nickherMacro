"""
Where Nickher Macro keeps its data.

An installed build lives in a program directory that a standard user cannot
write to, so presets and settings cannot sit next to the exe. They go to
%APPDATA%\\NickherMacro instead.

Three modes:

* dev (running from source) — the project folder, so a checkout stays
  self-contained and never touches your installed app's real data.
* portable — drop a file named ``portable.txt`` beside the exe and data stays
  beside the exe, for running off a USB stick.
* installed — %APPDATA%\\NickherMacro.

Data written by an older build (which always used the exe folder) is migrated
on first run so nobody loses their presets to an upgrade.
"""

import os
import shutil
import sys

APP_DIR_NAME = "NickherMacro"
PORTABLE_MARKER = "portable.txt"

#: Files carried over from a pre-installer build.
_MIGRATABLE = ("presets.json", "settings.json")

_cached_dir = None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> str:
    """The folder the running program lives in."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_portable() -> bool:
    return os.path.exists(os.path.join(exe_dir(), PORTABLE_MARKER))


def data_dir() -> str:
    """
    The writable folder for presets.json and settings.json.
    Created if missing. Falls back to the exe folder if it cannot be made.
    """
    global _cached_dir
    if _cached_dir:
        return _cached_dir

    if not is_frozen() or is_portable():
        _cached_dir = exe_dir()
        return _cached_dir

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    target = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        _cached_dir = exe_dir()   # better than losing data entirely
        return _cached_dir

    _migrate_legacy(target)
    _cached_dir = target
    return _cached_dir


def _migrate_legacy(target: str) -> None:
    """
    Copy data written by a pre-installer build into the new location.
    Only fills gaps — an existing file in the new location always wins, so
    this can run on every launch without clobbering anything.
    """
    source = exe_dir()
    if os.path.normcase(source) == os.path.normcase(target):
        return

    for name in _MIGRATABLE:
        old = os.path.join(source, name)
        new = os.path.join(target, name)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.copy2(old, new)
            except OSError:
                pass  # unreadable or locked; the app still starts with defaults


def data_file(name: str) -> str:
    return os.path.join(data_dir(), name)
