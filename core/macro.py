"""
The editable macro model that sits behind the step table.

Rows vs events
--------------
A recording is a flat list of events, but a *row* in the editor is usually a
pair: "press A" and "release A" become one row with a hold time. Pairing only
happens when the release immediately follows the press. Overlapping keys — a
chord like Shift+A, where the events interleave — stay as separate rows so the
overlap is visible and can't be silently destroyed by reordering.

Timing
------
Internally the model stores per-event *gaps* rather than absolute timestamps.
A gap travels with its event through a reorder; an absolute timestamp does not,
and reordering on timestamps would produce negative deltas and garbage playback.
`events` rebuilds absolute `at` values on the way out.
"""

from core import events as ev


class Row:
    """One line in the editor. `end` is None for rows that aren't a pair."""

    __slots__ = ("start", "end")

    def __init__(self, start: int, end=None):
        self.start = start
        self.end = end

    @property
    def is_pair(self) -> bool:
        return self.end is not None

    @property
    def indices(self) -> tuple:
        return (self.start,) if self.end is None else (self.start, self.end)

    def __repr__(self):
        return f"Row({self.start}, {self.end})"


class MacroModel:
    def __init__(self, events=None):
        self._events = []
        self._gaps = []
        self._rows = None      # cached row grouping; None means "recompute"
        self.set_events(events or [])

    def _invalidate(self):
        """Call after any change to the event list's structure."""
        self._rows = None

    # ── loading / saving ─────────────────────────────────────────────────────
    def set_events(self, events):
        self._events = [dict(e) for e in events]
        self._gaps = ev.gaps_of(self._events)
        self._invalidate()

    @property
    def events(self) -> list:
        """The macro as a flat event list with `at` rebuilt from the gaps."""
        out = [dict(e) for e in self._events]
        ev.apply_gaps(out, self._gaps)
        return out

    def clear(self):
        self._events = []
        self._gaps = []
        self._invalidate()

    def __len__(self):
        return len(self.rows())

    def is_empty(self) -> bool:
        return not self._events

    def step_count(self) -> int:
        return ev.step_count(self._events)

    # ── rows ─────────────────────────────────────────────────────────────────
    def rows(self) -> list:
        """Group the flat event list into editor rows. Cached — the table asks
        for this once per cell, and recomputing each time is quadratic."""
        if self._rows is not None:
            return self._rows
        rows, consumed = [], set()
        for i, e in enumerate(self._events):
            if i in consumed:
                continue
            end = self._adjacent_partner(i)
            if end is not None:
                consumed.add(end)
                rows.append(Row(i, end))
            else:
                rows.append(Row(i))
        self._rows = rows
        return rows

    def _adjacent_partner(self, i: int):
        """
        The index of the release that immediately follows the press at `i`.
        Returns None when they aren't adjacent — i.e. the keys overlap.
        """
        start = self._events[i]
        t = start.get("t")
        if t == ev.KEY_DOWN:
            want, field = ev.KEY_UP, "key"
        elif t == ev.MOUSE_DOWN:
            want, field = ev.MOUSE_UP, "button"
        else:
            return None

        j = i + 1
        if j < len(self._events):
            nxt = self._events[j]
            if nxt.get("t") == want and nxt.get(field) == start.get(field):
                return j
        return None

    def row_for_event(self, index: int):
        """Which row number contains event `index` — for playback highlighting."""
        for n, row in enumerate(self.rows()):
            if index in row.indices:
                return n
        return None

    def _row_at(self, n: int):
        rows = self.rows()
        return rows[n] if 0 <= n < len(rows) else None

    # ── display ──────────────────────────────────────────────────────────────
    def label(self, n: int) -> str:
        row = self._row_at(n)
        if row is None:
            return ""
        event = self._events[row.start]
        if event.get("t") == ev.DELAY:
            return "Wait"          # the Hold column shows how long
        if row.is_pair:
            return ev.pretty_event(event)

        # Unpaired press/release — show the direction so overlap is visible
        t = event.get("t")
        if t == ev.KEY_DOWN:
            return f"{ev.pretty_key(event.get('key', ''))}  ↓ hold"
        if t == ev.KEY_UP:
            return f"{ev.pretty_key(event.get('key', ''))}  ↑ release"
        if t == ev.MOUSE_DOWN:
            return f"{ev.pretty_button(event.get('button', 'left'))} ↓ hold"
        if t == ev.MOUSE_UP:
            return f"{ev.pretty_button(event.get('button', 'left'))} ↑ release"
        return ev.pretty_event(event)

    def kind(self, n: int) -> str:
        """Coarse category, for row colouring."""
        row = self._row_at(n)
        if row is None:
            return ""
        t = self._events[row.start].get("t")
        if t in (ev.KEY_DOWN, ev.KEY_UP):
            return "key"
        if t in (ev.MOUSE_DOWN, ev.MOUSE_UP, ev.MOUSE_MOVE, ev.SCROLL):
            return "mouse"
        if t == ev.DELAY:
            return "wait"
        return "text"

    # ── timing ───────────────────────────────────────────────────────────────
    def hold_ms(self, n: int):
        """
        How long the step itself lasts: the key/button hold time, or the
        duration of a wait step. None for rows that have no duration.
        """
        row = self._row_at(n)
        if row is None:
            return None
        event = self._events[row.start]
        if event.get("t") == ev.DELAY:
            return int(event.get("ms", 0))
        if not row.is_pair:
            return None
        return int(round(self._gaps[row.end] * 1000))

    def set_hold_ms(self, n: int, ms: int):
        row = self._row_at(n)
        if row is None:
            return
        event = self._events[row.start]
        if event.get("t") == ev.DELAY:
            event["ms"] = max(0, int(ms))
        elif row.is_pair:
            self._gaps[row.end] = max(0, int(ms)) / 1000.0

    def delay_ms(self, n: int) -> int:
        """The pause that runs after this row, independent of its duration."""
        row = self._row_at(n)
        if row is None:
            return 0
        return ev.get_delay(self._events[row.end if row.is_pair else row.start])

    def set_delay_ms(self, n: int, ms: int):
        row = self._row_at(n)
        if row is None:
            return
        ev.set_delay(self._events[row.end if row.is_pair else row.start], ms)

    def gap_ms(self, n: int) -> int:
        """Recorded pause before this row."""
        row = self._row_at(n)
        return 0 if row is None else int(round(self._gaps[row.start] * 1000))

    def set_all_delays(self, ms: int):
        # Safe for wait steps too: their duration lives in hold, not delay.
        for n in range(len(self.rows())):
            self.set_delay_ms(n, ms)

    def has_moves(self) -> bool:
        return any(e.get("t") == ev.MOUSE_MOVE for e in self._events)

    def remove_moves(self) -> int:
        """
        Drop every mouse-movement event, leaving clicks, keys, scrolls and
        waits. The gap a move carried is folded into the next event so the
        overall timing barely changes. Returns how many were removed.
        """
        keep_events, keep_gaps = [], []
        carried = 0.0
        removed = 0
        for e, g in zip(self._events, self._gaps):
            if e.get("t") == ev.MOUSE_MOVE:
                carried += g          # preserve the elapsed time it represented
                removed += 1
                continue
            keep_events.append(e)
            keep_gaps.append(g + carried)
            carried = 0.0
        self._events, self._gaps = keep_events, keep_gaps
        self._invalidate()
        return removed

    # ── structural edits ─────────────────────────────────────────────────────
    def _extract(self, row: Row):
        """Pull a row's events and gaps out of the list."""
        self._invalidate()
        idx = sorted(row.indices, reverse=True)
        block = [(self._events.pop(i), self._gaps.pop(i)) for i in idx]
        return list(reversed(block))

    def _insert_block(self, at_event_index: int, block):
        self._invalidate()
        for offset, (event, gap) in enumerate(block):
            self._events.insert(at_event_index + offset, event)
            self._gaps.insert(at_event_index + offset, gap)

    def delete(self, n: int):
        row = self._row_at(n)
        if row is not None:
            self._extract(row)

    def duplicate(self, n: int):
        row = self._row_at(n)
        if row is None:
            return
        block = [(dict(self._events[i]), self._gaps[i]) for i in row.indices]
        self._insert_block(max(row.indices) + 1, block)

    def move(self, n: int, to: int) -> int:
        """
        Move row `n` so it lands at row position `to`. Returns the new row
        number. The block's own gaps travel with it, so timing stays sane.
        """
        rows = self.rows()
        if not (0 <= n < len(rows)) or n == to:
            return n
        to = max(0, min(to, len(rows) - 1))

        block = self._extract(rows[n])

        # Re-read rows now that the block is gone, then find the insert point
        remaining = self.rows()
        if to >= len(remaining):
            insert_at = len(self._events)
        else:
            insert_at = remaining[to].start
        self._insert_block(insert_at, block)
        return to

    def move_up(self, n: int) -> int:
        return self.move(n, n - 1) if n > 0 else n

    def move_down(self, n: int) -> int:
        return self.move(n, n + 1) if n < len(self.rows()) - 1 else n

    # ── insertion ────────────────────────────────────────────────────────────
    def _insert_event_at_row(self, n, event, gap=0.0) -> int:
        """Insert a single event before row `n` (append when n is None/past end)."""
        rows = self.rows()
        if n is None or n >= len(rows):
            self._insert_block(len(self._events), [(event, gap)])
            return len(self.rows()) - 1
        self._insert_block(rows[n].start, [(event, gap)])
        return n

    def insert_wait(self, n, ms: int) -> int:
        return self._insert_event_at_row(n, ev.delay_event(ms))

    def insert_text(self, n, text: str) -> int:
        return self._insert_event_at_row(n, ev.text_event(text))

    def insert_key(self, n, encoded_key: str, modifiers=(), hold_ms: int = 30,
                   mod_gap_ms: int = 15) -> int:
        """
        Insert a key press, optionally wrapped in modifiers.

        Ctrl+C becomes: Ctrl down, C down, C up, Ctrl up — the same shape a
        real recording produces, so it displays and replays identically.
        """
        block = []
        for mod in modifiers:
            block.append(({"t": ev.KEY_DOWN, "key": mod, "at": 0.0},
                          mod_gap_ms / 1000.0 if block else 0.0))

        block.append(({"t": ev.KEY_DOWN, "key": encoded_key, "at": 0.0},
                      mod_gap_ms / 1000.0 if block else 0.0))
        block.append(({"t": ev.KEY_UP, "key": encoded_key, "at": 0.0},
                      max(0, hold_ms) / 1000.0))

        for mod in reversed(modifiers):
            block.append(({"t": ev.KEY_UP, "key": mod, "at": 0.0},
                          mod_gap_ms / 1000.0))

        rows = self.rows()
        if n is None or n >= len(rows):
            self._insert_block(len(self._events), block)
            return len(self.rows()) - len(block) if modifiers else len(self.rows()) - 1
        self._insert_block(rows[n].start, block)
        return n
