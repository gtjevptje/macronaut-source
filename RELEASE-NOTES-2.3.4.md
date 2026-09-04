Saving a flow can no longer destroy it.

**Saving is atomic now, and this is the reason for the release.** Until this
version, saving opened your file and emptied it *before* writing anything back.
If the write did not finish — a full disk, antivirus holding the file open, the
machine going down, or a step containing something the save could not encode —
you were left with a half-written file and no original to fall back on. It is
not a theoretical failure: reproduced here, an interrupted save turned a working
flow into a fragment that would not reload.

Macronaut now writes the new version alongside the old one and swaps them in a
single step. If anything goes wrong, the flow you already had is exactly where
it was.

**Activating a licence is written the same way**, for the same reason. An
interrupted write there used to leave a paid copy quietly back on the free tier.

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

## Also

- Nothing else changed about how flows run, record or play back.
- Some internal tidying: a module the app had stopped using is no longer
  imported, and several pieces of code that no longer run now say so, so that
  anyone reading the source is not misled about which parts are live.

## Notes

- Still unsigned, so SmartScreen will still warn on first run — click
  **More info → Run anyway**. The source is public if you would rather check:
  <https://github.com/gtjevptje/macronaut-source>
- Your flows, settings and licence are untouched by updating.
