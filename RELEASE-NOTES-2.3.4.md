Your work is no longer lost by saving it, or by closing the window.

**Closing Macronaut no longer throws away what is on the canvas.** This was the
worse of the two, because you did not have to be unlucky to hit it — you just
had to close the app. Build something for half an hour, close the window, and it
was gone: no prompt, no autosave, nothing to reopen.

Macronaut now keeps a private copy of the canvas as you work, and if you quit —
or crash — with a flow that was never saved, it offers it back the next time you
start. One question, Yes or No, and then it is done with: answering it retires
the copy, and so does saving the flow yourself.

It is deliberately quiet. You are not asked about a canvas that matches a script
already saved on disk, so opening something from the Library, looking at it and
quitting asks you nothing. And it is not a replacement for saving — it holds one
flow, the last one you had open.

**And Macronaut reopens the script you had open.** If you pick a script and
quit, it is there again when you come back, instead of dropping you at "— no
script —" every morning. Choosing "— no script —" is remembered too, so it does
not undo itself overnight. If you have only ever used the plain auto-clicker,
nothing changes for you: there is no script to remember.

**Saving is atomic now, and this is the other half of the same problem.** Until this
version, saving opened your file and emptied it *before* writing anything back.
If the write did not finish — a full disk, antivirus holding the file open, the
machine going down, or a step containing something the save could not encode —
you were left with a half-written file and no original to fall back on. It is
not a theoretical failure. Two of them were reproduced here. A save interrupted
part-way turned a working flow into a fragment that would not reload; and when
the file was simply *locked* — which is what antivirus does while it scans, and
what a sync client or an open editor does — the old save emptied it to nothing
and **then** reported "Permission denied", which reads as though it had refused
and changed nothing.

Macronaut now writes the new version alongside the old one and swaps them in a
single step. If anything goes wrong, the flow you already had is exactly where
it was.

**Activating a licence is written the same way**, for the same reason. An
interrupted write there used to leave a paid copy quietly back on the free tier.

**And so is settings.json**, which is the one most people would actually have
noticed. If that file was locked while Macronaut saved it — antivirus scanning,
a sync client, an editor left open — it was emptied, and the next launch quietly
started from defaults: every launcher key you had bound, your input backend and
your theme, gone with no message. It keeps what was there now.

**Errors about your files now say what happened.** A flow that will not open
used to report `Expecting value: line 1 column 20 (char 19)`, which tells you
neither what is wrong nor that the problem is the file rather than the program.
It now names the file, says it looks cut short, and — the part that matters —
tells you the file is still on disk and nothing has been changed. A save that
fails says the version already saved has not been touched and your flow is still
open on the canvas.

If you have a flow that stopped opening at some point, that is very likely this
bug. The file is still there; open it in Notepad and you will usually find it
ends mid-word. Nothing in this release can repair one, but nothing after this
release should create one.

**And if you have edited a flow by hand, the app now tells you where to look.**
Macronaut's flows are plain JSON on purpose — you are meant to be able to open
one — but a mistyped key used to come back as `KeyError: 'type'`, which is not
help of any kind. It now says which file, that it is valid JSON but not shaped
like a flow, and that a node needs an `id` and a `type` while an edge needs
`src` and `dst`.

A flow saved by a *newer* Macronaut than the one you are running still opens.
That is deliberate: refusing it would be a worse problem than the one being
solved here.

**A step that watches for an image now says when the image is missing.** If you
move or delete a picture a Detect step was looking for, that step used to wait
out its whole timeout and report "not found" — exactly what it reports when the
thing simply is not on screen. An If / Else was worse: it just kept taking the
same branch, so the flow looked like it was working. The run log names the file
now, once, when the step starts.

## Also

- Nothing else changed about how flows run, record or play back.
- Some internal tidying: a module the app had stopped using is no longer
  imported, and several pieces of code that no longer run now say so, so that
  anyone reading the source is not misled about which parts are live.

## Verified before release

Every release goes through three gates, and this one was put through them
during development as well: the frozen binary self-tests itself (12 of 12,
including image matching, Windows OCR and the licensing check), a launch probe
confirms it actually shows a window, and an in-place upgrade from the previously
published version is rehearsed against real binaries with the installed result
passing its own self-test afterwards. `release.py` runs the first of those again
as part of cutting the release, so the file you are downloading is the file that
passed.

## Notes

- Still unsigned, so SmartScreen will still warn on first run — click
  **More info → Run anyway**. The source is public if you would rather check:
  <https://github.com/gtjevptje/macronaut-source>
- Your flows, settings and licence are untouched by updating.
