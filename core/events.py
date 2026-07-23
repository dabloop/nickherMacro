"""
Event schema for Nickher Macro.

An event is a plain dict so it round-trips through JSON without any eval().

    {"t": "key_down",   "key": "a",            "at": 1.234, "delay": 0}
    {"t": "key_up",     "key": "<shift>",      "at": 1.301, "delay": 0}
    {"t": "mouse_down", "button": "left", "x": 100, "y": 200, "at": 2.0}
    {"t": "mouse_up",   "button": "left", "x": 100, "y": 200, "at": 2.1}
    {"t": "mouse_move", "x": 100, "y": 200,      "at": 2.5}
    {"t": "scroll",     "x": 100, "y": 200, "dx": 0, "dy": -1, "at": 3.0}
    {"t": "delay",      "ms": 500}                     # manually inserted
    {"t": "text",       "text": "hello world"}         # manually inserted

Common optional fields on every event:
    at    : seconds since the recording started (absent on manual events)
    delay : extra milliseconds to wait *after* this event (user-editable)

Key encoding
------------
    "a"          a printable character
    "<f6>"       a named pynput Key
    "<vk:96>"    a raw virtual key code (numpad etc.)

Never store str(key) — that is a repr, and reversing it needs eval().
"""

from pynput import keyboard
from pynput.mouse import Button

SCHEMA_VERSION = 2

KEY_DOWN   = "key_down"
KEY_UP     = "key_up"
MOUSE_DOWN = "mouse_down"
MOUSE_UP   = "mouse_up"
MOUSE_MOVE = "mouse_move"
SCROLL     = "scroll"
DELAY      = "delay"
TEXT       = "text"

#: Event types that represent a discrete user action worth showing as a chip.
STEP_TYPES = (KEY_DOWN, MOUSE_DOWN, SCROLL, DELAY, TEXT)

#: Event types that *complete* a step — where a "delay between keys" belongs.
STEP_END_TYPES = (KEY_UP, MOUSE_UP, SCROLL, DELAY, TEXT)


class EventError(ValueError):
    """Raised when an event cannot be encoded or decoded."""


# ─── Key encoding ─────────────────────────────────────────────────────────────
def encode_key(key) -> str:
    """pynput key object -> portable string."""
    if isinstance(key, keyboard.Key):
        return f"<{key.name}>"
    char = getattr(key, "char", None)
    if char:
        return char
    vk = getattr(key, "vk", None)
    if vk is not None:
        return f"<vk:{vk}>"
    raise EventError(f"cannot encode key: {key!r}")


def decode_key(s: str):
    """Portable string -> pynput key object. Never evaluates anything."""
    if not isinstance(s, str) or not s:
        raise EventError(f"bad key value: {s!r}")

    if s.startswith("<") and s.endswith(">") and len(s) > 2:
        body = s[1:-1]
        if body.startswith("vk:"):
            try:
                return keyboard.KeyCode.from_vk(int(body[3:]))
            except ValueError:
                raise EventError(f"bad vk in key: {s!r}")
        try:
            return keyboard.Key[body]
        except KeyError:
            raise EventError(f"unknown named key: {s!r}")

    if len(s) == 1:
        return keyboard.KeyCode.from_char(s)

    raise EventError(f"unrecognised key: {s!r}")


def encode_button(button) -> str:
    """
    pynput button -> portable name.

    Taken from the enum member rather than a fixed list, so side buttons
    (x1/x2 on Windows, button8/button9 on X11) survive instead of being
    silently rewritten as a left click.
    """
    name = getattr(button, "name", None)
    if not name:
        name = str(button).rsplit(".", 1)[-1]
    return name


def decode_button(name: str):
    button = getattr(Button, str(name), None)
    if isinstance(button, Button):
        return button
    raise EventError(f"unknown mouse button: {name!r}")


#: Side buttons are "back"/"forward" on almost every mouse that has them.
_PRETTY_BUTTON = {
    "left": "Left", "right": "Right", "middle": "Middle",
    "x1": "Back", "x2": "Forward",
    "button8": "Back", "button9": "Forward",
}


def pretty_button(name: str) -> str:
    return _PRETTY_BUTTON.get(name, str(name).replace("_", " ").title())


def available_buttons() -> list:
    """Names of every mouse button this platform's pynput exposes."""
    return [b.name for b in Button if b.name != "unknown"]


# ─── Event constructors ───────────────────────────────────────────────────────
def key_event(down: bool, key, at: float) -> dict:
    return {"t": KEY_DOWN if down else KEY_UP, "key": encode_key(key), "at": at}


def mouse_event(down: bool, button, x: int, y: int, at: float) -> dict:
    return {
        "t": MOUSE_DOWN if down else MOUSE_UP,
        "button": encode_button(button),
        "x": int(x), "y": int(y), "at": at,
    }


def move_event(x: int, y: int, at: float) -> dict:
    return {"t": MOUSE_MOVE, "x": int(x), "y": int(y), "at": at}


def scroll_event(x: int, y: int, dx: int, dy: int, at: float) -> dict:
    return {"t": SCROLL, "x": int(x), "y": int(y),
            "dx": int(dx), "dy": int(dy), "at": at}


def delay_event(ms: int) -> dict:
    return {"t": DELAY, "ms": max(0, int(ms))}


def text_event(text: str) -> dict:
    return {"t": TEXT, "text": str(text)}


# ─── Introspection ────────────────────────────────────────────────────────────
def is_step(event: dict) -> bool:
    """True for events the user thinks of as one 'step' in the macro."""
    return event.get("t") in STEP_TYPES


def step_count(events) -> int:
    return sum(1 for e in events if is_step(e))


def gaps_of(events) -> list:
    """
    Convert absolute `at` timestamps into per-event gaps (seconds before each
    event). Gaps survive reordering; absolute timestamps do not.
    """
    gaps = []
    previous = None
    for e in events:
        at = e.get("at")
        if at is None or previous is None:
            gaps.append(0.0)
        else:
            gaps.append(max(0.0, at - previous))
        if at is not None:
            previous = at
    return gaps


def apply_gaps(events, gaps) -> None:
    """Rewrite `at` from a gap list, in place. Inverse of gaps_of()."""
    clock = 0.0
    for e, gap in zip(events, gaps):
        clock += max(0.0, gap)
        if e.get("t") in (DELAY, TEXT):
            continue  # manual events carry no timestamp of their own
        e["at"] = clock


def ends_step(event: dict) -> bool:
    """True if a per-step delay belongs *after* this event."""
    return event.get("t") in STEP_END_TYPES


def step_indices(events) -> list:
    """Indices of the events shown to the user as steps."""
    return [i for i, e in enumerate(events) if is_step(e)]


def paired_end_index(events, i: int) -> int:
    """
    Index of the event that finishes the step starting at `i`.

    For a key_down that is its matching key_up; for a mouse_down, its
    mouse_up. Standalone steps (delay, text, scroll) are their own end.
    If no partner is found, the step's own index is returned.
    """
    if i < 0 or i >= len(events):
        return i
    start = events[i]
    t = start.get("t")

    if t == KEY_DOWN:
        want, field = KEY_UP, "key"
    elif t == MOUSE_DOWN:
        want, field = MOUSE_UP, "button"
    else:
        return i

    target = start.get(field)
    for j in range(i + 1, len(events)):
        if events[j].get("t") == want and events[j].get(field) == target:
            return j
    return i


def get_delay(event: dict) -> int:
    """Extra milliseconds to wait after this event."""
    try:
        return max(0, int(event.get("delay", 0) or 0))
    except (TypeError, ValueError):
        return 0


def set_delay(event: dict, ms: int) -> None:
    ms = max(0, int(ms))
    if ms:
        event["delay"] = ms
    else:
        event.pop("delay", None)


# ─── Display names ────────────────────────────────────────────────────────────
_PRETTY_NAMED = {
    "space": "Space", "enter": "Enter", "backspace": "Backspace",
    "tab": "Tab", "esc": "Escape",
    "shift": "Shift", "shift_l": "Shift", "shift_r": "Shift R",
    "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl R",
    "alt": "Alt", "alt_l": "Alt", "alt_gr": "AltGr", "alt_r": "Alt R",
    "cmd": "Win", "cmd_l": "Win", "cmd_r": "Win R",
    "delete": "Delete", "home": "Home", "end": "End",
    "page_up": "Page Up", "page_down": "Page Down",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
    "caps_lock": "Caps Lock", "num_lock": "Num Lock", "scroll_lock": "Scroll Lock",
    "insert": "Insert", "print_screen": "PrtSc", "pause": "Pause",
    "menu": "Menu",
}

_PRETTY_VK = {
    96: "Num 0", 97: "Num 1", 98: "Num 2", 99: "Num 3", 100: "Num 4",
    101: "Num 5", 102: "Num 6", 103: "Num 7", 104: "Num 8", 105: "Num 9",
    106: "Num *", 107: "Num +", 109: "Num -", 110: "Num .", 111: "Num /",
}


def pretty_key(encoded: str) -> str:
    """Human label for an encoded key string."""
    if not isinstance(encoded, str) or not encoded:
        return "?"
    if encoded.startswith("<") and encoded.endswith(">") and len(encoded) > 2:
        body = encoded[1:-1]
        if body.startswith("vk:"):
            try:
                vk = int(body[3:])
            except ValueError:
                return body
            return _PRETTY_VK.get(vk, f"vk{vk}")
        if body in _PRETTY_NAMED:
            return _PRETTY_NAMED[body]
        if len(body) > 1 and body[0] == "f" and body[1:].isdigit():
            return body.upper()
        return body.replace("_", " ").title()
    return encoded.upper() if len(encoded) == 1 else encoded


def pretty_event(event: dict) -> str:
    """Human label for a whole event — used on the chips."""
    t = event.get("t")
    if t in (KEY_DOWN, KEY_UP):
        return pretty_key(event.get("key", ""))
    if t in (MOUSE_DOWN, MOUSE_UP):
        btn = pretty_button(event.get("button", "left"))
        return f"{btn} Click ({event.get('x', 0)}, {event.get('y', 0)})"
    if t == MOUSE_MOVE:
        return f"Move ({event.get('x', 0)}, {event.get('y', 0)})"
    if t == SCROLL:
        direction = "↑" if event.get("dy", 0) > 0 else "↓"
        return f"Scroll {direction}"
    if t == DELAY:
        return f"Wait {event.get('ms', 0)} ms"
    if t == TEXT:
        text = event.get("text", "")
        return f'Type "{text[:18]}…"' if len(text) > 18 else f'Type "{text}"'
    return str(t)


# ─── Legacy migration ─────────────────────────────────────────────────────────
def _decode_legacy_key(raw: str) -> str:
    """
    Convert a v1 str(key) repr into the v2 encoding, without eval().

    Handles:  "Key.f6"  "'n'"  "<96>"  "KeyCode(vk=96)"  "KeyCode(char='n')"
    """
    if not isinstance(raw, str) or not raw:
        raise EventError(f"bad legacy key: {raw!r}")

    if raw.startswith("Key."):
        return f"<{raw[4:]}>"

    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 3:
        return raw[1:-1][:1]

    if "vk=" in raw:
        digits = ""
        for ch in raw.split("vk=", 1)[1]:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            return f"<vk:{digits}>"

    if "char=" in raw:
        tail = raw.split("char=", 1)[1].lstrip()
        if tail.startswith(("'", '"')) and len(tail) >= 2:
            return tail[1]

    if raw.startswith("<") and raw.endswith(">") and raw[1:-1].isdigit():
        return f"<vk:{raw[1:-1]}>"

    if len(raw) == 1:
        return raw

    raise EventError(f"unrecognised legacy key: {raw!r}")


def normalize_key_string(raw: str, fallback: str = "") -> str:
    """
    Accept either a v2 encoded key or a v1 str(key) repr and return the v2 form.
    Used to upgrade hotkeys stored in settings.json. Falls back on failure.
    """
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        decode_key(raw)
        return raw          # already valid v2
    except EventError:
        pass
    try:
        return _decode_legacy_key(raw)
    except EventError:
        return fallback


def migrate_events(events) -> list:
    """
    Upgrade a v1 event list — [("down", "'n'", 1.29), ...] — to v2 dicts.
    Already-v2 events pass through untouched. Unparseable entries are dropped.
    """
    out = []
    for ev in events or []:
        if isinstance(ev, dict):
            if ev.get("t"):
                out.append(ev)
            continue

        if not isinstance(ev, (list, tuple)) or len(ev) < 2:
            continue

        kind, data = ev[0], ev[1]
        at = float(ev[2]) if len(ev) > 2 and isinstance(ev[2], (int, float)) else 0.0

        try:
            if kind in ("down", "up"):
                out.append({
                    "t": KEY_DOWN if kind == "down" else KEY_UP,
                    "key": _decode_legacy_key(data),
                    "at": at,
                })
            elif kind == "click" and isinstance(data, (list, tuple)) and len(data) == 4:
                x, y, btn_str, pressed = data
                name = str(btn_str).rsplit(".", 1)[-1].strip("'\"")
                out.append({
                    "t": MOUSE_DOWN if pressed else MOUSE_UP,
                    "button": name if hasattr(Button, name) else "left",
                    "x": int(x), "y": int(y), "at": at,
                })
        except (EventError, TypeError, ValueError):
            continue  # drop entries we cannot understand rather than crash

    return out
