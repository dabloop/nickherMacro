"""
Self-update against GitHub Releases.

Flow
----
1. Ask the GitHub API for the latest release of GITHUB_REPO.
2. Compare its tag to version.__version__.
3. Download the .exe asset plus its .sha256 companion.
4. Verify the digest, then hand off to a helper script that waits for this
   process to exit, swaps the binary, and relaunches it.

Security notes
--------------
This code replaces the running executable, so it is worth being strict:

* HTTPS only — an http:// asset URL is rejected outright.
* The download is verified against a SHA-256 published as a release asset.
  A release with no checksum is refused rather than installed on trust; a
  tampered download would otherwise become whatever runs on the user's machine.
* Nothing is executed until after the digest matches.

Uses only the standard library, so the bundle stays small.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from version import __version__, GITHUB_REPO

API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
ASSET_NAME = "NickherMacro.exe"
USER_AGENT = f"NickherMacro/{__version__}"

TIMEOUT = 15
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024   # refuse anything absurd


class UpdateError(Exception):
    """Raised when an update cannot be checked, downloaded, or verified."""


class UpdateInfo:
    """
    Describes an available release. Carries two possible installation assets:

      * the installer (NickherMacro-Setup-<v>.exe), when present — the reliable
        path, because Inno Setup handles stopping the running app, replacing
        files, and relaunching. Hand-swapping a one-file exe is fragile: antivirus
        can lock a bundled DLL mid-extraction, which surfaces as a cryptic
        "failed to load DLL" on the next launch.
      * the raw exe (NickherMacro.exe) — the fallback for a portable copy that
        was never installed.
    """

    def __init__(self, version, notes,
                 exe_url, exe_sha_url, exe_size,
                 setup_url=None, setup_sha_url=None, setup_size=0):
        self.version = version
        self.notes = notes
        self.exe_url = exe_url
        self.exe_sha_url = exe_sha_url
        self.exe_size = exe_size
        self.setup_url = setup_url
        self.setup_sha_url = setup_sha_url
        self.setup_size = setup_size

    @property
    def has_installer(self) -> bool:
        return bool(self.setup_url and self.setup_sha_url)

    # Back-compat: older call sites read .url/.sha_url/.size for the exe asset.
    @property
    def url(self):
        return self.exe_url

    @property
    def sha_url(self):
        return self.exe_sha_url

    @property
    def size(self):
        return self.exe_size

    def __repr__(self):
        return f"UpdateInfo({self.version!r}, installer={self.has_installer})"


# ─── Version comparison ───────────────────────────────────────────────────────
def parse_version(text: str) -> tuple:
    """
    'v1.2.3' -> (1, 2, 3). Unparseable segments become 0 so a malformed tag
    sorts low instead of raising.
    """
    cleaned = str(text or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in cleaned.split(".")[:4]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# ─── HTTP ─────────────────────────────────────────────────────────────────────
def _open(url: str, accept="application/json"):
    if not url.lower().startswith("https://"):
        raise UpdateError(f"Refusing a non-HTTPS URL: {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        return urllib.request.urlopen(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # A private repo looks identical to a missing one over an
            # unauthenticated request, and that is the likelier mistake.
            raise UpdateError(
                "No published releases found. If the repository is private, "
                "update checks cannot reach it — releases must be public."
            ) from exc
        if exc.code in (403, 429):
            raise UpdateError("GitHub rate limit reached — try again later.") from exc
        raise UpdateError(f"Server returned {exc.code}.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc


# ─── Check ────────────────────────────────────────────────────────────────────
def check(repo: str = GITHUB_REPO, current: str = __version__):
    """Return an UpdateInfo if a newer release exists, else None."""
    if not repo or "/" not in repo:
        raise UpdateError(
            "No GitHub repository configured — set GITHUB_REPO in version.py.")

    with _open(API_LATEST.format(repo=repo)) as response:
        try:
            data = json.loads(response.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UpdateError("GitHub returned something unreadable.") from exc

    tag = data.get("tag_name") or data.get("name") or ""
    if not is_newer(tag, current):
        return None

    assets = {a.get("name"): a for a in data.get("assets", []) if isinstance(a, dict)}
    version = str(tag).lstrip("vV")

    # The installer is the required, verified asset. The app is a one-folder
    # build now, so there is no standalone exe to swap — updates always run the
    # installer, which replaces the whole program folder atomically.
    setup_name = f"NickherMacro-Setup-{version}.exe"
    setup = assets.get(setup_name)
    if not setup:
        raise UpdateError(f"Release {tag} has no installer ({setup_name}) attached.")
    setup_sha = assets.get(setup_name + ".sha256")
    if not setup_sha:
        raise UpdateError(
            f"Release {tag} has no {setup_name}.sha256 checksum. "
            "Refusing to install an unverified download.")

    # A standalone exe may still be published for older clients; it's optional.
    exe = assets.get(ASSET_NAME)
    exe_sha = assets.get(ASSET_NAME + ".sha256")

    return UpdateInfo(
        version=version,
        notes=(data.get("body") or "").strip(),
        exe_url=exe.get("browser_download_url", "") if exe else "",
        exe_sha_url=exe_sha.get("browser_download_url", "") if exe_sha else "",
        exe_size=int(exe.get("size") or 0) if exe else 0,
        setup_url=setup.get("browser_download_url", ""),
        setup_sha_url=setup_sha.get("browser_download_url", ""),
        setup_size=int(setup.get("size") or 0),
    )


# ─── Download and verify ──────────────────────────────────────────────────────
def _expected_digest(sha_url: str) -> str:
    with _open(sha_url, accept="text/plain") as response:
        text = response.read(4096).decode("utf-8", "replace").strip()
    # Accept either a bare digest or the "<digest>  <filename>" sha256sum format
    digest = text.split()[0] if text else ""
    if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise UpdateError("The published checksum is not a valid SHA-256.")
    return digest.lower()


def download(info: UpdateInfo, progress=None, which="auto") -> str:
    """
    Fetch a release asset to a temp file and verify it. Returns the path.

    which : "installer" | "exe" | "auto" (installer when available, else exe)
    progress : called with (bytes_done, bytes_total)
    """
    if which == "installer" or (which == "auto" and info.has_installer):
        url, sha_url, size = info.setup_url, info.setup_sha_url, info.setup_size
        prefix = "NickherMacro-Setup-"
    else:
        url, sha_url, size = info.exe_url, info.exe_sha_url, info.exe_size
        prefix = "NickherMacro-"

    expected = _expected_digest(sha_url)

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".exe.part")
    os.close(fd)

    digest = hashlib.sha256()
    done = 0
    try:
        with _open(url, accept="application/octet-stream") as response:
            total = int(response.headers.get("Content-Length") or size or 0)
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("Download is implausibly large — aborted.")
                digest.update(chunk)
                with open(path, "ab") as handle:
                    handle.write(chunk)
                if progress:
                    progress(done, total)

        actual = digest.hexdigest()
        if actual != expected:
            raise UpdateError(
                "Checksum mismatch — the download does not match the "
                "published release. Update cancelled.")
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise

    final = path[: -len(".part")]
    try:
        os.replace(path, final)
    except OSError as exc:
        raise UpdateError(f"Could not finalise the download: {exc}") from exc
    return final


# ─── Install ──────────────────────────────────────────────────────────────────
def can_self_update() -> bool:
    """Only a frozen (PyInstaller) build can update itself."""
    return bool(getattr(sys, "frozen", False))


def run_installer(setup_exe: str) -> None:
    """
    Launch the downloaded installer and let it do the update. Inno Setup stops
    the running app, replaces the files, and relaunches — none of the one-file
    swap fragility. The installer runs silently with a progress window; the app
    should quit right after this returns so the installer can replace the exe.
    """
    if not os.path.exists(setup_exe):
        raise UpdateError("The installer download went missing.")

    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        # /SILENT shows a progress bar but asks nothing; the installer's own
        # code relaunches the app when it finishes.
        subprocess.Popen([setup_exe, "/SILENT", "/NORESTART"],
                         creationflags=creation, close_fds=True)
    except OSError as exc:
        raise UpdateError(f"Could not start the installer: {exc}") from exc


_SWAP_SCRIPT = """@echo off
rem Wait for Nickher Macro (PID %1) to exit, then swap in the new build.
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

move /y "{target}" "{backup}" >nul 2>&1
move /y "{new}" "{target}" >nul 2>&1
if errorlevel 1 (
    rem Swap failed — put the original back so the app still runs.
    move /y "{backup}" "{target}" >nul 2>&1
)
del "{backup}" >nul 2>&1

start "" "{target}"
(goto) 2>nul & del "%~f0"
"""


def apply_update(new_exe: str) -> None:
    """
    Hand off to a helper that waits for us to exit, swaps the binary, and
    relaunches. Windows will not let a running executable be overwritten, so
    the swap has to happen from another process after this one is gone.
    """
    if not can_self_update():
        raise UpdateError(
            "Running from source — pull the new code with git instead.")

    target = os.path.abspath(sys.executable)
    script = os.path.join(tempfile.gettempdir(), "nickher_update.bat")

    try:
        with open(script, "w", encoding="ascii", errors="replace") as handle:
            handle.write(_SWAP_SCRIPT.format(
                pid=os.getpid(),
                target=target,
                backup=target + ".old",
                new=os.path.abspath(new_exe),
            ))
    except OSError as exc:
        raise UpdateError(f"Could not write the update helper: {exc}") from exc

    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(["cmd", "/c", script],
                         creationflags=creation, close_fds=True)
    except OSError as exc:
        raise UpdateError(f"Could not start the update helper: {exc}") from exc


def cleanup_old_binary() -> None:
    """Remove the previous build left behind by an update. Safe to call always."""
    if not can_self_update():
        return
    stale = os.path.abspath(sys.executable) + ".old"
    if os.path.exists(stale):
        try:
            os.remove(stale)
        except OSError:
            pass  # still locked; it will go on a later run
