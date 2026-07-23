"""
Hotkeys with modifier support — e.g. Shift+5, Ctrl+Shift+F5.

A hotkey is stored as a canonical string: zero or more modifiers followed by
one main key, joined by '+':

    "<f8>"                a bare key
    "shift+5"             Shift held, then 5
    "ctrl+shift+<f5>"     two modifiers, then F5

Modifiers are normalised so left/right variants collapse: shift_l and shift_r
both become "shift". Matching is exact on the modifier set, so "5" and
"shift+5" are different hotkeys and never trigger each other.
"""

from pynput import keyboard

from core import events as ev

MODIFIERS = ("ctrl", "shift", "alt", "win")
_MOD_ORDER = {m: i for i, m in enumerate(MODIFIERS)}

#: pynput Key -> canonical modifier name.
_MOD_FROM_KEY = {
    keyboard.Key.ctrl: "ctrl", keyboard.Key.ctrl_l: "ctrl", keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.shift: "shift", keyboard.Key.shift_l: "shift", keyboard.Key.shift_r: "shift",
    keyboard.Key.alt: "alt", keyboard.Key.alt_l: "alt", keyboard.Key.alt_r: "alt",
    keyboard.Key.cmd: "win", keyboard.Key.cmd_l: "win", keyboard.Key.cmd_r: "win",
}
if hasattr(keyboard.Key, "alt_gr"):
    _MOD_FROM_KEY[keyboard.Key.alt_gr] = "alt"

_PRETTY_MOD = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}


def modifier_of(key):
    """Canonical modifier name if `key` is a modifier, else None."""
    return _MOD_FROM_KEY.get(key)


def is_modifier_encoded(encoded: str) -> bool:
    """True if an encoded key string is itself a modifier key."""
    try:
        return modifier_of(ev.decode_key(encoded)) is not None
    except ev.EventError:
        return False


def make(mods, main_key: str) -> str:
    """Build a canonical hotkey string from modifier names and a main key."""
    ordered = sorted({m for m in mods if m in _MOD_ORDER}, key=_MOD_ORDER.get)
    return "+".join(ordered + [main_key])


def split(hotkey: str):
    """
    Canonical string -> (frozenset(mods), main_key).

    The main key is always the final token; everything before it is a modifier.
    Robust to a main key that has no '+' in it (the common case).
    """
    if not hotkey:
        return frozenset(), ""
    parts = hotkey.split("+")
    # Peel leading tokens that are known modifiers; the remainder is the key.
    mods = []
    i = 0
    while i < len(parts) - 1 and parts[i] in _MOD_ORDER:
        mods.append(parts[i])
        i += 1
    main = "+".join(parts[i:])   # rejoin in case the key itself was "+"
    return frozenset(mods), main


def pretty(hotkey: str) -> str:
    """Human label, e.g. 'Shift + 5' or 'Ctrl + Shift + F5'."""
    if not hotkey:
        return "Unset"
    mods, main = split(hotkey)
    ordered = sorted(mods, key=_MOD_ORDER.get)
    labels = [_PRETTY_MOD[m] for m in ordered] + [ev.pretty_key(main)]
    return " + ".join(labels)


def normalize(hotkey: str, fallback: str = "") -> str:
    """
    Validate/repair a stored hotkey. Accepts a bare v2 key, a legacy repr, or a
    canonical chord. Returns a canonical string, or `fallback` if unusable.
    """
    if not isinstance(hotkey, str) or not hotkey:
        return fallback
    mods, main = split(hotkey)
    main = ev.normalize_key_string(main, "")
    if not main:
        return fallback
    return make(mods, main)


class ChordTracker:
    """
    Tracks which modifiers are currently held, so the global listener can tell
    Shift+5 from a plain 5. Feed it every press and release.
    """

    def __init__(self):
        self._down = set()

    def press(self, key):
        """Record a press. Returns the canonical hotkey if `key` is a main key."""
        mod = modifier_of(key)
        if mod:
            self._down.add(mod)
            return None
        try:
            main = ev.encode_key(key)
        except ev.EventError:
            return None
        return make(self._down, main)

    def release(self, key):
        mod = modifier_of(key)
        if mod:
            self._down.discard(mod)

    def reset(self):
        self._down.clear()
