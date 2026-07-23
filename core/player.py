"""
Plays back a v2 event list (see core/events.py).

Two timing modes:
    "recorded" — reproduce the original rhythm from the `at` timestamps,
                 scaled by `speed` (2.0 = twice as fast).
    "fixed"    — ignore timestamps, wait `fixed_interval_ms` between events.

On top of either mode, any event may carry a `delay` (extra milliseconds to
wait after it). That delay is literal and is never scaled by `speed`.
"""

import random
import time

from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Controller as MouseController

from core import events as ev

#: Longest single sleep. Longer waits are sliced so stop() stays responsive.
_SLEEP_SLICE = 0.02

#: Ceiling on a single recorded gap, so a pause while recording doesn't
#: turn into a minutes-long stall on playback.
MAX_RECORDED_GAP = 10.0


class Player:
    """
    Parameters
    ----------
    events            : v2 event list
    timing_mode       : "recorded" or "fixed"
    speed             : multiplier applied to recorded gaps (0.1 – 20)
    fixed_interval_ms : gap between events in "fixed" mode
    repeat            : number of runs, 0 = infinite
    loop_gap_ms       : pause between consecutive runs
    step_delay_ms     : extra pause after *every* step, on top of per-event
                        delays — the global "delay between keys" setting
    jitter_pct        : randomise every wait by ±N% (0 = exact)
    on_done           : callback() when playback ends
    on_cycle          : callback(run, total) after each run
    on_step           : callback(index) before each event is dispatched
    on_error          : callback(Exception) for events that failed to play
    """

    def __init__(self, events, timing_mode="recorded", speed=1.0,
                 fixed_interval_ms=50, repeat=0, loop_gap_ms=0,
                 step_delay_ms=0, jitter_pct=0,
                 on_done=None, on_cycle=None, on_step=None, on_error=None):
        self.events = list(events or [])
        self.timing_mode = timing_mode
        self.speed = min(20.0, max(0.1, float(speed)))
        self.fixed_interval = max(0.0, fixed_interval_ms / 1000.0)
        self.repeat = max(0, int(repeat))
        self.loop_gap = max(0.0, loop_gap_ms / 1000.0)
        self.step_delay = max(0.0, step_delay_ms / 1000.0)
        self.jitter = min(0.9, max(0.0, jitter_pct / 100.0))

        self.running = False
        self.on_done = on_done
        self.on_cycle = on_cycle
        self.on_step = on_step
        self.on_error = on_error

        self._kb = KeyboardController()
        self._mouse = MouseController()
        self._held_keys = set()
        self._held_buttons = set()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def play(self):
        self.running = True
        run = 0
        try:
            while self.running:
                run += 1
                self._play_once()
                if not self.running:
                    break

                if self.on_cycle:
                    self._safe(self.on_cycle, run, self.repeat)

                if self.repeat and run >= self.repeat:
                    break
                if self.loop_gap:
                    self._sleep(self.loop_gap)
        finally:
            self.running = False
            self._release_all()
            if self.on_done:
                self._safe(self.on_done)

    def stop(self):
        self.running = False

    # ── internals ────────────────────────────────────────────────────────────
    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception as exc:
            self._report(exc)

    def _report(self, exc):
        if self.on_error:
            try:
                self.on_error(exc)
            except Exception:
                pass

    def _play_once(self):
        for i, event in enumerate(self.events):
            if not self.running:
                return
            if self.on_step:
                self._safe(self.on_step, i)
            self._dispatch(event)
            wait = self._gap_after(i) + ev.get_delay(event) / 1000.0
            if self.step_delay and ev.ends_step(event):
                wait += self.step_delay
            if wait > 0:
                self._sleep(wait)

    def _gap_after(self, i: int) -> float:
        """Seconds to wait between event i and event i+1."""
        if i + 1 >= len(self.events):
            return 0.0

        if self.timing_mode == "fixed":
            return self.fixed_interval

        here = self.events[i].get("at")
        nxt = self.events[i + 1].get("at")
        if here is None or nxt is None:
            return 0.0  # manual events have no timestamp of their own
        return min(MAX_RECORDED_GAP, max(0.0, nxt - here)) / self.speed

    def _sleep(self, seconds: float):
        """Sleep in slices so stop() takes effect promptly."""
        if self.jitter:
            seconds *= 1.0 + random.uniform(-self.jitter, self.jitter)
        deadline = time.perf_counter() + seconds
        while self.running:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            time.sleep(min(_SLEEP_SLICE, remaining))

    def _release_all(self):
        """Never leave a key or button latched down after playback ends."""
        for encoded in list(self._held_keys):
            try:
                self._kb.release(ev.decode_key(encoded))
            except Exception:
                pass
        self._held_keys.clear()

        for name in list(self._held_buttons):
            try:
                self._mouse.release(ev.decode_button(name))
            except Exception:
                pass
        self._held_buttons.clear()

    def _dispatch(self, event):
        t = event.get("t")
        try:
            if t == ev.KEY_DOWN:
                encoded = event["key"]
                self._kb.press(ev.decode_key(encoded))
                self._held_keys.add(encoded)

            elif t == ev.KEY_UP:
                encoded = event["key"]
                self._kb.release(ev.decode_key(encoded))
                self._held_keys.discard(encoded)

            elif t == ev.MOUSE_DOWN:
                name = event.get("button", "left")
                self._mouse.position = (event["x"], event["y"])
                self._mouse.press(ev.decode_button(name))
                self._held_buttons.add(name)

            elif t == ev.MOUSE_UP:
                name = event.get("button", "left")
                self._mouse.position = (event["x"], event["y"])
                self._mouse.release(ev.decode_button(name))
                self._held_buttons.discard(name)

            elif t == ev.MOUSE_MOVE:
                self._mouse.position = (event["x"], event["y"])

            elif t == ev.SCROLL:
                self._mouse.position = (event["x"], event["y"])
                self._mouse.scroll(event.get("dx", 0), event.get("dy", 0))

            elif t == ev.DELAY:
                self._sleep(event.get("ms", 0) / 1000.0)

            elif t == ev.TEXT:
                self._kb.type(event.get("text", ""))

        except (KeyError, ev.EventError, ValueError) as exc:
            self._report(exc)
        except Exception as exc:
            self._report(exc)
