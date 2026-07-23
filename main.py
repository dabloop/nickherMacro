import sys
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Handle fractional display scaling (125%, 150%) cleanly. Without PassThrough,
# Qt rounds the scale factor and control heights can come out a pixel short,
# which clips button text on some machines.
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

from main_window import MainWindow

#: One running copy only. A macro tool that hooks the keyboard must never run in
#: duplicate — each copy adds its own global hotkeys and its own playback thread,
#: so pressing the loop key would start several loops at once and stopping one
#: window would leave the others typing with no way to reach them.
SINGLE_INSTANCE_KEY = "NickherMacro-single-instance-v1"

#: Kernel object that decides who is the one running copy. Local\ scopes it to
#: the logged-in user, so two people on the same PC each get their own copy.
#: Windows releases it when the process dies, so a crash never locks us out.
_MUTEX_NAME = "Local\\NickherMacro-single-instance-v1"
_ERROR_ALREADY_EXISTS = 183

#: Held for the process lifetime; dropping it would hand the claim to a racer.
_instance_mutex = None


def resource_path(relative: str) -> str:
    """Return correct path whether running from source or PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _claim_single_instance() -> bool:
    """True if this process is the one running copy.

    The claim has to be atomic and it has to happen before any slow startup
    work. Checking first and claiming later leaves a gap, and spam-launching
    fires copies straight into it: they all look, all see nothing, all keep
    going. A named mutex has no gap — the kernel hands it to exactly one
    caller and tells everyone else it already existed.

    Note QLocalServer cannot do this job: on Windows a second listen() on a
    name already in use still returns true, so it never reports the clash.
    """
    global _instance_mutex
    if sys.platform != "win32":
        return _claim_via_lockfile()

    import ctypes
    from ctypes import wintypes
    # use_last_error is the whole ballgame: plain windll saves and restores the
    # thread's last-error code around each call, so a later GetLastError() can
    # read 0 and a copy that lost the race would think it won.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPCVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE   # not c_int; would truncate
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        # No mutex means no way to arbitrate. A working macro beats a window
        # that refuses to open, so carry on unguarded.
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _instance_mutex = handle
    return True


def _claim_via_lockfile() -> bool:
    """Same claim for non-Windows: an exclusive lock the OS drops on exit."""
    global _instance_mutex
    import fcntl
    import tempfile
    lock = open(os.path.join(tempfile.gettempdir(),
                             SINGLE_INSTANCE_KEY + ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return False
    _instance_mutex = lock          # closing it would release the lock
    return True


def _ping_running_copy(attempts: int = 10) -> bool:
    """Ask the running copy to show itself. True if one answered.

    Retried because losing the race is not the same as the winner being ready:
    when several copies start at once the winner still has to open the channel,
    and a single immediate probe would find nothing and give up.
    """
    probe = QLocalSocket()
    for _ in range(attempts):
        probe.connectToServer(SINGLE_INSTANCE_KEY)
        if probe.waitForConnected(300):
            break
        probe.abort()
    else:
        return False
    probe.write(b"show")
    probe.waitForBytesWritten(300)
    # Hold the connection until the owner closes it. It may still be building
    # its window and not reading yet; dropping early can lose the ping.
    probe.waitForDisconnected(2000)
    return True


def _open_ping_channel() -> QLocalServer:
    """Listen for pings from copies that stood down. Winner of the mutex only."""
    # A crash can leave a stale socket that blocks listen() on POSIX. Only the
    # mutex holder gets here, so there is no live server to knock off the name.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)
    return server


def _serve(server: QLocalServer, window) -> None:
    """Surface the window whenever another copy pings the channel."""
    def _on_connection():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            conn.readAll()
            window.surface_from_anywhere()
            conn.disconnectFromServer()

    server.newConnection.connect(_on_connection)
    # Pings that landed while the window was still being built are already
    # queued and will never re-emit newConnection; drain them once.
    _on_connection()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Nickher Macro")
    # Closing the window must not quit the app while it lives in the tray; we
    # decide when to actually exit.
    app.setQuitOnLastWindowClosed(False)

    # Claim before any slow startup work — see _claim_single_instance.
    if not _claim_single_instance():
        # Another copy owns the slot. Ask it to show itself and leave quietly.
        _ping_running_copy()
        sys.exit(0)

    server = _open_ping_channel()  # kept alive for the process lifetime

    icon_path = resource_path("ncicon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    if os.path.exists(icon_path):
        win.setWindowIcon(QIcon(icon_path))

    _serve(server, win)
    win.show()
    sys.exit(app.exec())
