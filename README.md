# Macronaut

**A free, open-source auto clicker and visual macro recorder for Windows.**

[![tests](https://github.com/gtjevptje/macronaut-source/actions/workflows/tests.yml/badge.svg)](https://github.com/gtjevptje/macronaut-source/actions/workflows/tests.yml)
[![Licence: GPL v3](https://img.shields.io/badge/licence-GPL--3.0--or--later-4f46e5)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-4f46e5)](#installation)
[![Download](https://img.shields.io/badge/download-Macronaut.exe-22c55e)](https://github.com/gtjevptje/Macronaut/releases/latest/download/Macronaut.exe)

A Windows autoclicker and input-automation app built with Python and PySide6 (Qt 6).
The **Sequence** tab is the centrepiece — a friendly builder for recording and
hand-crafting multi-step automations — backed by a classic single-point
**Basic** auto-clicker.

A modern dark **indigo** theme (with an instant light mode), the Windows system
typeface, consistent controls throughout, plain-language descriptions on the
advanced features, and a layout that adapts from a small window to fullscreen.

## Download

### → **[Macronaut.exe](https://github.com/gtjevptje/Macronaut/releases/latest/download/Macronaut.exe)**

Windows 10 or 11. One file, no installer, no account, nothing to configure — run
it and it works. **[macronaut's website](https://gtjevptje.github.io/Macronaut/)**
has screenshots, the full feature list and a published SHA-256 of that download,
plus a [click speed test](https://gtjevptje.github.io/Macronaut/click-speed-test.html)
and how it compares to
[AutoHotkey](https://gtjevptje.github.io/Macronaut/autohotkey-alternative.html)
and [TinyTask](https://gtjevptje.github.io/Macronaut/tinytask-alternative.html).

⚠ **Windows will warn you the first time.** A blue "Windows protected your PC"
box appears — click **More info** → **Run anyway**. That warning is not about
anything found in the file; it is what Windows shows for any executable without
a paid code-signing certificate, which this project does not have yet. Being
able to read the source instead is the honest answer to it, and that is what
this repository is. Your antivirus may flag it for the same reason, plus one
more: it installs a global keyboard hook, because a stop hotkey that only works
when the window is focused would be useless.

To run from source instead, see [Installation](#installation) below.

---

## Features

### Basic clicking
- Left, right, or middle mouse button
- Single click, double click, or hold-down mode (with adjustable hold duration)
- Click at the current cursor position or a fixed coordinate (3-second eyedropper capture)
- Adjustable click interval with millisecond precision
- Optional interval randomisation (±N ms) to vary the rhythm
- Stop after N clicks, after N seconds, or at a specific time of day (auto-wraps to tomorrow)
- Optional countdown delay before clicking starts

### Sequence builder
- Record live mouse clicks and keystrokes into a replayable sequence
  - Modifier chords (e.g. **Ctrl+C**) are captured as a single combo step
  - Rapid same-spot clicks are merged into a double-click step
- One-click action palette: add **Click / Key-or-Combo / Type Text / Wait / Wait-for-Image** steps
- **Drag-and-drop reorder**, or use Move Up / Down
- **Enable / disable** individual steps with a checkbox — skip them without deleting
- **Duplicate**, **copy / paste** (Ctrl+C / Ctrl+V) and **Test this step** from the right-click menu
- Double-click any step to edit it; per-step delay captured on record or set manually
- Live footer summary: step count, active steps, and estimated runtime per loop / total
- Save and load sequences to / from JSON files
- Loop a set number of times or infinitely, with a playback speed multiplier (0.1× – 10×)
- Keyboard shortcuts: **Del** delete · **Ctrl+D** duplicate · **Ctrl+C/V** copy/paste

### Hotkeys & triggers
- A single global hotkey (default **F8**, configurable) starts / stops from anywhere —
  the START/STOP button and tray menu always show the currently bound key
- Holding the hotkey fires once, not repeatedly (no start/stop flicker)
- Optional second "trigger" key that also starts/stops
- **Image trigger** (Basic tab): wait until a target screenshot appears on screen before
  clicking begins (requires `opencv-python`; the option is disabled with a note if it isn't installed)
- **Wait-for-Image** step (Sequence tab): pause until an image appears, then optionally click it

### Smart features
- **Human mode** (Basic tab): randomised intervals and a few pixels of cursor jitter per click
- **Click region constraint**: draw a bounding box on screen; clicks stay inside it
- **Auto-pause on focus loss**: pause automatically when your chosen window isn't focused (needs `pywin32`)
- **Key blacklist**: any key listed here is never sent during sequence playback — a safety net for keys like Win or Alt+F4

### Interface
- Four-tab layout: **Sequence / Basic / Settings / Stats** (Sequence is the default)
- Responsive layout that adapts to small / non-maximised windows
- Context-aware fields — only the inputs relevant to your current selection stay enabled
- Live click counter, keystroke counter, elapsed time, and CPS in the status bar
- System-tray icon with Start / Stop / Show / Quit menu and a colour state (indigo = idle, green = running)
- Closing the window **fully quits** the app — the global hotkey hook and any running automation are stopped, so nothing lingers in the background
- Instant dark / light theme toggle in Settings — no restart

### Stats & logging
- Rolling CPS and KPS display (5-second window)
- Per-session history (start, end, duration, clicks, keys, averages),
  **saved between runs** in `~/.macronaut/sessions.json`
- Export session history to CSV

---

## About this repository

This is the complete source of Macronaut, published under the GPL. Everything
that goes into the released `.exe` is here, and `pyinstaller macronaut.spec`
builds it.

⚠ It will not be the *same file*. PyInstaller writes a timestamp into the
executable and does not order its archive deterministically, so two builds from
this same tree, on this same machine, minutes apart, differ in tens of millions
of bytes and a few kilobytes of length. That is PyInstaller, not something
hidden here — but it means a hash comparison against the published download will
never match, and you should not read that as evidence of anything. What is
checkable is the source, all of which is in this repository.

The commit history starts on the day the project went open source rather than
on the day it began. The private working repository also holds the business
around the program — outreach drafts, traffic numbers, pricing plans — none of
which is part of Macronaut, and rewriting three years of history to strip it was
a worse risk than simply starting here. Nothing about the *program* is withheld.

Issues and pull requests are welcome. It is a one-person project, so replies
are not instant. [CONTRIBUTING.md](CONTRIBUTING.md) covers getting set up,
running the suite, and the three traps that have actually caught people.
Security bugs go to email rather than the issue tracker —
[SECURITY.md](SECURITY.md) says what is in scope and, just as usefully, what is
not.

---

## Installation

### Prerequisites
- Python 3.9+ (64-bit recommended on Windows)
- Windows 10 / 11

### Install dependencies

```powershell
cd Macronaut
pip install -r requirements.txt
```

> `opencv-python` is only needed for the image-matching features (image trigger and
> Wait-for-Image with confidence matching). Without it, those options are disabled
> automatically and everything else works normally.

### Run

```powershell
python main.py
```

---

## Building a standalone .exe

```powershell
pip install pyinstaller
pyinstaller macronaut.spec
```

The output `Macronaut.exe` will be in `dist/`. It bundles all dependencies and
requires no Python installation to run. To brand the executable, run
`python create_shortcut.py` once to generate `assets/icon.ico`, then uncomment the
`icon=` line in `macronaut.spec`.

---

## Quick-start guide

1. **Sequences** — the app opens on the **Sequence** tab. Click **⏺ Record** to capture
   live input, or use the left-hand palette to add steps. Drag rows to reorder, toggle a
   checkbox to enable/disable a step, then press **▶ Play**.
2. **Basic clicking** — switch to the **Basic** tab, set button / action / interval / position,
   then click **START** (or press **F8**).
3. **Fixed position** — choose *A fixed point on screen*, click **Pick a point on screen**,
   and hover the target; the position is captured after a 3-second countdown.
4. **Hotkey** — default is **F8** and works even when minimised. Change it in
   **Settings → Hotkeys**; the button and tray labels update to match.
5. **Human mode** — enable in the **Basic** tab to add timing variation and cursor jitter.
6. **Region constraint** — in **Settings**, click *Select region on screen…* and drag a rectangle.
7. **Image trigger** — in the **Basic** tab, tick *Only start once a target image is on screen*,
   then browse to or capture a PNG/JPEG template.

---

## File structure

```
Macronaut/
├── main.py          Entry point, all UI tabs, single global hotkey listener
├── clicker.py       Mouse click automation engine (QThread worker)
├── keystrokes.py    Key-name tables and conversion/display helpers
├── recorder.py      Live sequence recorder and playback engine
├── settings.py      Persistent JSON settings (stored in ~/.macronaut/)
├── stats.py         CPS/KPS tracking and persistent session history
├── tray.py          System-tray icon
├── requirements.txt Python dependencies
├── macronaut.spec   PyInstaller build configuration
└── assets/          icon.ico for the branded .exe
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Hotkey not triggering | Run as administrator; some games/apps block low-level key hooks |
| Image trigger greyed out | Install OpenCV: `pip install opencv-python` |
| Image not found | Lower the confidence below 0.8; capture the template at the same DPI |
| Window focus detection not working | Install `pywin32` (`pip install pywin32`) |
| App freezes on start | Check Windows Defender / antivirus — pynput hooks can be flagged |

---

## Licence

**Macronaut is free software, under the GNU General Public License v3.0 or
later.** Copyright © 2026 Gerben van Poucke.

`SPDX-License-Identifier: GPL-3.0-or-later`

The full text is in [LICENSE](LICENSE). The components Macronaut is built on,
and their own terms, are in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Run it, read it, change it, pass it on. The one obligation: if you distribute a
modified version — as source or as a built `.exe` — you publish your changes
under the same licence. Nobody gets to take this, close it, and sell it back.

### Why it was opened

Macronaut was proprietary until 30 August 2026. It was opened because the most
common reason people gave for not downloading it was that they could not see
what they were running, which is an entirely fair thing to say about an
unsigned executable that installs a global keyboard hook and asks to be trusted
with your mouse. Every other answer to that objection asks for trust. This one
does not: the code is here, and `pyinstaller macronaut.spec` builds the program
from it.

Builds published before that date remain under the EULA they shipped with.
Everything from here is GPL.

### There is no warranty

Sections 15 and 16 of the licence say this in the legal register. Plainly:
Macronaut sends real keyboard and mouse input, and it is given to you as-is.
Many online games and services forbid automation in their terms of service, and
using it against them can cost you your account. That is your call to make —
read their rules first.

### Pro is free right now

The Pro features — watching the screen, and branching on what it sees — are
built, and they are switched on for everyone. There is no key, no limit and
nothing to buy. See `entitlements.py`, which is where that decision lives and
explains itself.
