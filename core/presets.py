"""
Preset storage.

File format (v2):

    {
      "version": 2,
      "presets": {
        "My Macro": {"events": [ ... ], "saved": 1721692800.0}
      }
    }

A v1 file — a flat {name: [legacy events]} mapping — is migrated on first load
and written back in the new format. Failures raise PresetError rather than
disappearing, so the UI can tell the user what went wrong.
"""

import json
import os
import time

from core import events as ev
from core import paths


class PresetError(Exception):
    """Raised when presets cannot be read from or written to disk."""


def _path() -> str:
    return paths.data_file("presets.json")


# ─── Read ─────────────────────────────────────────────────────────────────────
def _read_raw() -> dict:
    p = _path()
    if not os.path.exists(p):
        return {"version": ev.SCHEMA_VERSION, "presets": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PresetError(f"Could not read presets.json: {exc}") from exc

    if not isinstance(data, dict):
        raise PresetError("presets.json is not a JSON object.")
    return data


def load_all() -> dict:
    """Return {name: [events]}, migrating a v1 file in place if needed."""
    data = _read_raw()

    if data.get("version") == ev.SCHEMA_VERSION and isinstance(data.get("presets"), dict):
        return {
            name: list(entry.get("events", []))
            for name, entry in data["presets"].items()
            if isinstance(entry, dict)
        }

    # v1: flat {name: [legacy tuples]}
    migrated = {
        name: ev.migrate_events(raw)
        for name, raw in data.items()
        if isinstance(raw, list)
    }
    if migrated:
        _write({
            name: {"events": evts, "saved": time.time()}
            for name, evts in migrated.items()
        })
    return migrated


def get_preset(name: str) -> list:
    return load_all().get(name, [])


def names() -> list:
    return list(load_all().keys())


# ─── Write ────────────────────────────────────────────────────────────────────
def _write(presets: dict) -> None:
    payload = {"version": ev.SCHEMA_VERSION, "presets": presets}
    p = _path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, p)  # atomic — a crash mid-write can't truncate presets
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise PresetError(f"Could not write presets.json: {exc}") from exc


def _entries() -> dict:
    """Full {name: entry} mapping, post-migration."""
    data = _read_raw()
    if data.get("version") == ev.SCHEMA_VERSION and isinstance(data.get("presets"), dict):
        return dict(data["presets"])
    return {
        name: {"events": ev.migrate_events(raw), "saved": time.time()}
        for name, raw in data.items()
        if isinstance(raw, list)
    }


def save_preset(name: str, events: list) -> None:
    entries = _entries()
    entries[name] = {"events": list(events), "saved": time.time()}
    _write(entries)


def delete_preset(name: str) -> None:
    entries = _entries()
    if entries.pop(name, None) is not None:
        _write(entries)


def rename_preset(old: str, new: str) -> None:
    entries = _entries()
    if old in entries:
        entries[new] = entries.pop(old)
        _write(entries)


# ─── Import / export ──────────────────────────────────────────────────────────
def export_preset(name: str, path: str) -> None:
    """Write one preset to a standalone .nmacro file."""
    events = get_preset(name)
    payload = {"version": ev.SCHEMA_VERSION, "name": name, "events": events}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError as exc:
        raise PresetError(f"Could not export '{name}': {exc}") from exc


def import_preset(path: str) -> str:
    """Read a standalone macro file into the preset store. Returns its name."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PresetError(f"Could not import '{path}': {exc}") from exc

    if not isinstance(data, dict) or "events" not in data:
        raise PresetError("That file is not a Nickher macro.")

    name = str(data.get("name") or os.path.splitext(os.path.basename(path))[0])
    events = data["events"]
    if data.get("version") != ev.SCHEMA_VERSION:
        events = ev.migrate_events(events)

    existing = _entries()
    unique, n = name, 2
    while unique in existing:
        unique, n = f"{name} ({n})", n + 1

    save_preset(unique, events)
    return unique
