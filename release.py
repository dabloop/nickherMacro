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
    # build/ is pure output and is safe to wipe.
    build_dir = os.path.join(ROOT, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)

    # dist/ is NOT: it is where the app actually runs, so presets.json and
    # settings.json accumulate beside the exe. Only remove what we regenerate.
    for name in ("NickherMacro.exe", "NickherMacro.exe.sha256"):
        stale = os.path.join(ROOT, "dist", name)
        if os.path.exists(stale):
            os.remove(stale)

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


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum(path: str) -> str:
    """Write '<digest>  <filename>' next to the file, sha256sum style."""
    hex_digest = sha256_of(path)
    with open(path + ".sha256", "w", encoding="ascii") as handle:
        handle.write(f"{hex_digest}  {os.path.basename(path)}\n")
    return hex_digest


def find_iscc():
    """Locate the Inno Setup compiler, or None if it isn't installed."""
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                     "Inno Setup 6", "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return shutil.which("ISCC.exe")


def build_installer(version: str):
    """Compile the installer. Returns its path, or None if Inno isn't present."""
    iscc = find_iscc()
    if not iscc:
        print("Inno Setup not found — skipping the installer.")
        print("  winget install --id JRSoftware.InnoSetup")
        return None

    # Stale installers would otherwise pile up in dist/ across versions
    for old in os.listdir(os.path.join(ROOT, "dist")):
        if old.startswith("NickherMacro-Setup-"):
            os.remove(os.path.join(ROOT, "dist", old))

    print("Compiling installer...")
    result = subprocess.run(
        [iscc, f"/DAppVersion={version}", "installer.iss"],
        cwd=ROOT, stdout=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        sys.exit("Installer compilation failed.")

    path = os.path.join(ROOT, "dist", f"NickherMacro-Setup-{version}.exe")
    if not os.path.exists(path):
        sys.exit(f"Inno reported success but {path} is missing.")
    return path


def main() -> None:
    if len(sys.argv) > 1:
        write_version(sys.argv[1])

    version = read_version()
    build()
    exe_digest = write_checksum(EXE)
    installer = build_installer(version)

    assets = [EXE, EXE + ".sha256"]
    print()
    print(f"  NickherMacro.exe             {os.path.getsize(EXE)/1e6:6.1f} MB")
    print(f"    sha256  {exe_digest}")
    if installer:
        write_checksum(installer)
        assets += [installer, installer + ".sha256"]
        print(f"  {os.path.basename(installer):<28} "
              f"{os.path.getsize(installer)/1e6:6.1f} MB")
        print(f"    sha256  {sha256_of(installer)}")

    quoted = " ".join(f'"{a}"' for a in assets)
    print()
    print("Publish it:")
    print(f"  git tag v{version} && git push origin v{version}")
    print(f'  gh release create v{version} {quoted} '
          f'--title "v{version}" --notes "What changed..."')
    print()
    print("NickherMacro.exe and its .sha256 must both be attached — the updater")
    print("rejects a release with no checksum rather than installing unverified.")


if __name__ == "__main__":
    main()
