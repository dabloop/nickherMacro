"""
Records keyboard and mouse activity into v2 events (see core/events.py).

Every event carries an `at` timestamp in seconds from the start of the
recording, so playback can reproduce the original rhythm.
"""

import time
import threading

from pynput import keyboard, mouse

from core import events as ev


class Recorder:
    """
    Parameters
    ----------
    record_mouse       : capture clicks and scrolls
    record_moves       : capture pointer movement (off by default — it is noisy)
    move_min_interval  : seconds between captured move samples
    move_min_distance  : pixels the pointer must travel before a move is kept
    """

    def __init__(self, record_mouse=True, record_moves=False,
                 move_min_interval=0.03, move_min_distance=6):
        self.events = []
        self.recording = False
        self.stop_key = None          # encoded key string, e.g. "<f6>"

        self.record_mouse = record_mouse
        self.record_moves = record_moves
        self.move_min_interval = move_min_interval
        self.move_min_distance = move_min_distance

        self.on_event = None          # callback(event) fired on the listener thread
        self.on_error = None          # callback(Exception) for surfaced failures

        #: Screen rects (x, y, w, h) whose mouse activity is never recorded —
        #: the app's own window, so clicking "Stop Recording" isn't captured.
        self.ignore_rects = []

        self._lock = threading.Lock()
        self._k_listener = None
        self._m_listener = None
        self._start_time = 0.0
        self._held = set()            # keys currently down, for _release_stuck
        self._ignored_buttons = set() # pressed inside an ignored rect
        self._last_move = (0.0, None)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self):
        if self.recording:
            return
        self.events = []
        self._held.clear()
        self._ignored_buttons.clear()
        self._last_move = (0.0, None)
        self._start_time = time.perf_counter()
        self.recording = True

        self._k_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)
        self._k_listener.daemon = True
        self._k_listener.start()

        if self.record_mouse:
            self._m_listener = mouse.Listener(
                on_click=self._on_click,
                on_scroll=self._on_scroll,
                on_move=self._on_move if self.record_moves else None,
            )
            self._m_listener.daemon = True
            self._m_listener.start()

    def stop(self):
        if not self.recording:
            return
        self.recording = False
        for listener in (self._k_listener, self._m_listener):
            try:
                if listener is not None:
                    listener.stop()
            except Exception as exc:
                self._report(exc)
        self._k_listener = self._m_listener = None
        self._release_stuck()
        self._strip_stop_key()
        self._strip_trailing_window_click()
        self._strip_dangling_click()

    # ── internals ────────────────────────────────────────────────────────────
    def _elapsed(self) -> float:
        return time.perf_counter() - self._start_time

    def _report(self, exc):
        if self.on_error:
            try:
                self.on_error(exc)
            except Exception:
                pass

    def _emit(self, event):
        with self._lock:
            self.events.append(event)
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as exc:
                self._report(exc)

    def _release_stuck(self):
        """
        Append key_up events for anything still held when recording stopped,
        so playback can never leave a key latched down.
        """
        at = self._elapsed()
        for encoded in sorted(self._held):
            self.events.append({"t": ev.KEY_UP, "key": encoded, "at": at})
        self._held.clear()

    def _strip_stop_key(self):
        """Drop the hotkey that ended the recording from the sequence."""
        if not self.stop_key:
            return
        with self._lock:
            self.events = [
                e for e in self.events
                if not (e["t"] in (ev.KEY_DOWN, ev.KEY_UP)
                        and e.get("key") == self.stop_key)
            ]

    def _strip_dangling_click(self):
        """
        Drop a trailing mouse_down with no matching mouse_up, so a click that
        was still held as recording ended can't replay as a stuck button.
        """
        with self._lock:
            for i in range(len(self.events) - 1, -1, -1):
                e = self.events[i]
                if e["t"] == ev.MOUSE_UP:
                    return
                if e["t"] == ev.MOUSE_DOWN:
                    button = e.get("button")
                    if not any(later.get("button") == button
                               for later in self.events[i + 1:]
                               if later["t"] == ev.MOUSE_UP):
                        del self.events[i]
                    return

    def _strip_trailing_window_click(self):
        """
        Remove exactly the click that landed on our own window to stop the
        recording. Only the single trailing click is removed, so a real click
        on the target app — even one that happens to overlap the window — is
        never lost. This replaces the old approach of ignoring every click
        inside the window, which silently dropped clicks on apps behind us.
        """
        if not self.ignore_rects:
            return
        with self._lock:
            if not self.events:
                return
            last = self.events[-1]
            if last["t"] == ev.MOUSE_UP and self._in_ignored_rect(
                    last.get("x", -1 << 30), last.get("y", -1 << 30)):
                self.events.pop()
                button = last.get("button")
                for i in range(len(self.events) - 1, -1, -1):
                    if (self.events[i]["t"] == ev.MOUSE_DOWN
                            and self.events[i].get("button") == button):
                        del self.events[i]
                        break
            elif last["t"] == ev.MOUSE_DOWN and self._in_ignored_rect(
                    last.get("x", -1 << 30), last.get("y", -1 << 30)):
                self.events.pop()

    def _in_ignored_rect(self, x, y) -> bool:
        for rx, ry, rw, rh in self.ignore_rects:
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return True
        return False

    # ── keyboard ─────────────────────────────────────────────────────────────
    def _on_press(self, key):
        if not self.recording:
            return
        try:
            encoded = ev.encode_key(key)
        except ev.EventError as exc:
            self._report(exc)
            return

        if self.stop_key and encoded == self.stop_key:
            self.stop()
            return False

        if encoded in self._held:
            return  # swallow OS auto-repeat
        self._held.add(encoded)
        self._emit({"t": ev.KEY_DOWN, "key": encoded, "at": self._elapsed()})

    def _on_release(self, key):
        if not self.recording:
            return
        try:
            encoded = ev.encode_key(key)
        except ev.EventError as exc:
            self._report(exc)
            return

        if self.stop_key and encoded == self.stop_key:
            return
        self._held.discard(encoded)
        self._emit({"t": ev.KEY_UP, "key": encoded, "at": self._elapsed()})

    # ── mouse ────────────────────────────────────────────────────────────────
    def _on_click(self, x, y, button, pressed):
        # Record every click. The one click that stops recording (on our own
        # window) is stripped afterwards by _strip_trailing_window_click, so
        # clicks on the target app are never dropped — even if it sits behind us.
        if not self.recording:
            return
        self._emit(ev.mouse_event(pressed, button, x, y, self._elapsed()))

    def _on_scroll(self, x, y, dx, dy):
        if not self.recording:
            return
        self._emit(ev.scroll_event(x, y, dx, dy, self._elapsed()))

    def _on_move(self, x, y):
        if not self.recording:
            return
        now = self._elapsed()
        last_t, last_pos = self._last_move
        if now - last_t < self.move_min_interval:
            return
        if last_pos is not None:
            if abs(x - last_pos[0]) + abs(y - last_pos[1]) < self.move_min_distance:
                return
        self._last_move = (now, (x, y))
        self._emit(ev.move_event(x, y, now))
