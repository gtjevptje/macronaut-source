# Macronaut 2.3.3 — open source

Macronaut is now free software under the **GNU General Public License v3.0 or
later**. The complete source is at
**https://github.com/gtjevptje/macronaut-source**.

Nothing about the app changed. Same features, same price of nothing, same
person maintaining it. What changed is that you no longer have to take any of
that on trust.

## Why

The most common reason people gave for not downloading Macronaut was that they
could not see what they were running — and that is a fair thing to say. It is an
unsigned executable that installs a global keyboard hook, and the first thing
Windows tells you about it is that it protected your PC from it.

Every answer this page could previously give to that was a request for trust:
the SHA-256, "one person made this", the promise of no telemetry. Publishing the
code is the only answer that asks for none. You can read exactly what it does
with your keyboard, and you can build this same `.exe` yourself:

```
git clone https://github.com/gtjevptje/macronaut-source
cd macronaut-source
pip install -r requirements.txt
pyinstaller macronaut.spec
```

## What is in this build

- **`LICENSE` is the GPL.** It ships inside the `.exe` as it always has, and
  **Settings → About & legal** opens it.
- **A "Source code" button** sits next to Licence and Third-party notices in
  that same panel — reachable from inside the app, not only from the website,
  because that is where somebody deciding whether to trust it actually is.
- The About panel no longer says "All rights reserved", because that is no
  longer true.

## What this means for you

**Run it, read it, change it, pass it on.** The one obligation is that if you
distribute a modified version — as source or as a built `.exe` — you publish
your changes under the same licence. Nobody gets to take this, close it, and
sell it back.

GPL rather than a permissive licence for exactly that reason. It is not a
restriction on you; it is what keeps the next person's copy as free as yours.

## Pro is still free

Unchanged from 2.2.0 onwards, and worth repeating because "open source" and
"there is a paid tier" arrive in the same release note. Every feature —
including everything marked Pro — is switched on for everyone right now. There
is no key, no limit and nothing to buy. Anything you build now keeps working.

## Notes

- Builds published before 30 August 2026 remain under the licence they shipped
  with. This one and everything after it are GPL.
- Macronaut is still unsigned, so SmartScreen will still warn on first run.
  Click **More info → Run anyway**. A certificate is still on the roadmap — but
  the source being public is a better answer to that warning than a certificate
  would have been on its own.
- The private working repository keeps its own history and the notes around the
  project. What is published is the program, in full.
