# Nickher Macro

A keyboard and mouse macro recorder for Windows. Record what you do, edit the
steps and their timing, then replay it — once, a set number of times, or on a
loop bound to a hotkey.

## Features

- **Records keyboard and mouse** — keys, clicks, side buttons (Back/Forward),
  scroll, and optionally pointer movement
- **True-to-life timing** — plays back at the speed you recorded, with a speed
  multiplier, or at a flat interval if you prefer
- **Step editor** — reorder by dragging, insert keys/waits/text, set how long
  each key is held and how long to pause after it
- **Presets with their own hotkeys** — bind F1 to one macro, F2 to another, and
  fire them from anywhere
- **Panic key** — stops everything instantly (Esc by default)
- **Runs in the tray** so hotkeys keep working with the window closed
- **Jitter** — randomise timing by ±N% so playback isn't robotically uniform

## Install

Download `NickherMacro.exe` from [Releases][releases] and run it. No installer.

Windows may warn that the publisher is unknown — the build isn't code-signed.
Some antivirus tools also flag macro software generally, since hooking the
keyboard globally looks like a keylogger to a scanner.

[releases]: https://github.com/dabloop/nickherMacro/releases

## Run from source

```sh
pip install -r requirements.txt
python main.py
```

## Hotkeys

| Default | Action |
|---------|--------|
| `F6`    | Start / stop recording |
| `F8`    | Start / stop the loop |
| `Esc`   | Panic stop |

All rebindable under **Settings**, along with a hotkey per saved preset.

## Building

```sh
python release.py 1.2.0
```

Sets the version, builds the exe, and writes the `.sha256` that the in-app
updater requires. Build straight from `NickherMacro.spec` — do not add
`--collect-all=PySide6`, which bundles Qt WebEngine (an entire Chromium,
~200 MB) into an app that only uses QtWidgets.

## Where your data lives

`presets.json` and `settings.json` sit next to the executable. They are yours;
updates never overwrite them.
