"""
Build a release: compile the exe, write its checksum, and print the commands
to publish it.

    python release.py            build the current version
    python release.py 1.2.0      set the version first, then build

The .sha256 file is not optional — the updater refuses any release without a
matching checksum asset, so publishing both files together is the whole point
of this script.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(ROOT, "dist", "NickherMacro.exe")
VERSION_FILE = os.path.join(ROOT, "version.py")


def read_version() -> str:
    with open(VERSION_FILE, encoding="utf-8") as handle:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', handle.read())
    if not match:
        sys.exit("Could not find __version__ in version.py")
    return match.group(1)


def write_version(new: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        sys.exit(f"Version must look like 1.2.3, got {new!r}")
    with open(VERSION_FILE, encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new}"', text, count=1)
    with open(VERSION_FILE, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"version.py -> {new}")


def build() -> None:
    for stale in ("build", "dist"):
        path = os.path.join(ROOT, stale)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    print("Building (this takes a minute)...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "NickherMacro.spec"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        sys.exit("Build failed.")
    if not os.path.exists(EXE):
        sys.exit(f"Build reported success but {EXE} is missing.")


def write_checksum() -> str:
    digest = hashlib.sha256()
    with open(EXE, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    hex_digest = digest.hexdigest()
    with open(EXE + ".sha256", "w", encoding="ascii") as handle:
        handle.write(f"{hex_digest}  NickherMacro.exe\n")
    return hex_digest


def main() -> None:
    if len(sys.argv) > 1:
        write_version(sys.argv[1])

    version = read_version()
    build()
    digest = write_checksum()
    size_mb = os.path.getsize(EXE) / 1e6

    print()
    print(f"  NickherMacro.exe   {size_mb:.1f} MB")
    print(f"  sha256             {digest}")
    print()
    print("Publish it:")
    print(f'  git tag v{version} && git push origin v{version}')
    print(f'  gh release create v{version} "{EXE}" "{EXE}.sha256" '
          f'--title "v{version}" --notes "What changed..."')
    print()
    print("Both files must be attached — the updater rejects a release with")
    print("no checksum rather than installing an unverified binary.")


if __name__ == "__main__":
    main()
