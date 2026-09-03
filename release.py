"""Cut a Macronaut release: bump the version, build the .exe, write the manifest.

The whole point is that the version in `version.py`, the version baked into the
built .exe, and the version the updater advertises are produced by one command
and cannot disagree.

    python release.py --bump patch --notes "Fixed the thing"
    python release.py --publish            # after checking dist/ looks right

Typical flow:

    1. Write RELEASE-NOTES-<new version>.md, then
       python release.py --bump patch
         (the notes file is found by name — --notes / --notes-file override it)
         → bumps version.py, builds dist/Macronaut.exe, writes dist/update.json
         (add --sign once a code-signing certificate exists; it must run before
         the manifest, because signing changes the bytes the hash describes)
    2. Test dist/Macronaut.exe by hand, and rehearse the swap:
         python tools/rehearse_swap.py --new dist/Macronaut.exe --old <previous>
    3. python release.py --publish
         → git tag + `gh release create`, uploading the .exe and the manifest to
           the PUBLIC releases repo (version.UPDATE_REPO).

`--publish` needs the GitHub CLI (`gh auth login` once). If you'd rather upload
by hand, run steps 1-2 and drag both files onto the GitHub release page — the
manifest must be attached as `update.json` or the updater won't find it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys as _sys

# ⚠ This script prints ⚠ and — , and a Windows console (or anything that pipes
# it) hands Python a cp1252 stdout, where those raise UnicodeEncodeError. That
# killed a publish *between* the pre-flight checks and `gh release create`: the
# release was never created, and the traceback pointed at a print statement
# rather than at anything to do with releasing. Reconfigure rather than strip
# the characters — the notes are the user's text and may hold anything at all.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import version as _v  # noqa: E402  (after sys.path setup)

DIST = ROOT / "dist"
EXE = DIST / "Macronaut.exe"
MANIFEST = DIST / "update.json"
VERSION_FILE = ROOT / "version.py"


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=ROOT, **kw)


# ── Version bumping ───────────────────────────────────────────────────────────
def bump(kind: str) -> str:
    """Raise the version in version.py. `kind` is major|minor|patch or a literal
    version string. -> the new version."""
    current = _v.__version__
    if kind in ("major", "minor", "patch"):
        major, minor, patch = _v.as_tuple(current)
        if kind == "major":
            major, minor, patch = major + 1, 0, 0
        elif kind == "minor":
            minor, patch = minor + 1, 0
        else:
            patch += 1
        new = f"{major}.{minor}.{patch}"
    else:
        new = kind.lstrip("vV")
        if _v.parse(new) is None:
            raise SystemExit(f"error: {kind!r} is not a usable version")
        if not _v.is_newer(new, current):
            raise SystemExit(
                f"error: {new} is not newer than the current {current} — "
                "users on the current build would never be offered it")

    text = VERSION_FILE.read_text(encoding="utf-8")
    patched, n = re.subn(r'^__version__\s*=\s*".*?"',
                         f'__version__ = "{new}"', text,
                         count=1, flags=re.MULTILINE)
    if n != 1:
        raise SystemExit("error: could not find __version__ in version.py")
    VERSION_FILE.write_text(patched, encoding="utf-8")
    print(f"  version.py: {current} -> {new}")
    return new


# ── Build ─────────────────────────────────────────────────────────────────────
def build() -> Path:
    """Run PyInstaller. -> the built .exe."""
    print("Building (this takes a couple of minutes)…")
    for stale in (DIST / "Macronaut.exe",):
        if stale.exists():
            stale.unlink()
    r = _run([sys.executable, "-m", "PyInstaller", "macronaut.spec", "--noconfirm"])
    if r.returncode != 0:
        raise SystemExit("error: PyInstaller failed")
    if not EXE.exists():
        raise SystemExit(f"error: expected {EXE} but it wasn't produced")
    print(f"  built {EXE} ({EXE.stat().st_size:,} bytes)")
    return EXE


# ── Code signing ──────────────────────────────────────────────────────────────
# The certificate is referenced by thumbprint, never by .pfx-plus-password: the
# key then stays in the Windows certificate store or on the hardware token (which
# publicly-trusted code-signing certificates have required since 2023), and no
# secret ever appears in a command line, a script, or this repository.
SIGN_THUMBPRINT_ENV = "MACRONAUT_SIGN_SHA1"
TIMESTAMP_URL = "http://timestamp.digicert.com"


def find_signtool() -> Path | None:
    """Locate signtool.exe. It ships with the Windows SDK and is not on PATH."""
    found = shutil.which("signtool")
    if found:
        return Path(found)
    roots = [Path(r"C:\Program Files (x86)\Windows Kits\10\bin"),
             Path(r"C:\Program Files\Windows Kits\10\bin")]
    best = None
    for root in roots:
        if not root.exists():
            continue
        for cand in root.glob("*/x64/signtool.exe"):
            # Sort by SDK version directory so the newest wins.
            if best is None or cand.parent.parent.name > best.parent.parent.name:
                best = cand
    return best


def sign(exe: Path) -> None:
    """Authenticode-sign the build in place. Raises SystemExit on failure.

    Must run BEFORE the manifest is written: signing rewrites the file, so a
    manifest made first would carry the hash of the unsigned bytes and every
    download would fail its integrity check. main() enforces that ordering, and
    publish() re-checks the hash as a backstop.
    """
    import os

    thumb = (os.environ.get(SIGN_THUMBPRINT_ENV) or "").replace(" ", "").strip()
    if not thumb:
        raise SystemExit(
            f"error: --sign needs the certificate thumbprint in ${SIGN_THUMBPRINT_ENV}.\n"
            "  Find it with: certutil -store My\n"
            "  Then: set MACRONAUT_SIGN_SHA1=<thumbprint>")
    tool = find_signtool()
    if tool is None:
        raise SystemExit(
            "error: signtool.exe not found — install the Windows SDK "
            "(Signing Tools for Desktop Apps).")

    print(f"Signing with {tool}…")
    # A timestamp is what keeps already-published builds valid after the
    # certificate expires; without it every release dies with the cert.
    r = _run([str(tool), "sign", "/sha1", thumb, "/fd", "SHA256",
              "/tr", TIMESTAMP_URL, "/td", "SHA256", "/v", str(exe)])
    if r.returncode != 0:
        raise SystemExit("error: signtool failed")

    sys.path.insert(0, str(ROOT))
    import updater
    trusted, reason = updater.signature_status(exe)
    if not trusted:
        raise SystemExit(f"error: signed, but the result does not verify ({reason})")
    print(f"  signature verifies: {reason}")


# ── Manifest ──────────────────────────────────────────────────────────────────
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_manifest(ver: str, notes: str = "", mandatory: bool = False) -> Path:
    if not EXE.exists():
        raise SystemExit(f"error: {EXE} not found — build first")
    if "OWNER/" in _v.UPDATE_REPO:
        print("  ⚠ version.UPDATE_REPO is still the placeholder — the published "
              "manifest will point at a repo that doesn't exist.")
    data = {
        "version": ver,
        "url": (f"https://github.com/{_v.UPDATE_REPO}/releases/download/"
                f"v{ver}/Macronaut.exe"),
        "sha256": sha256(EXE),
        "size": EXE.stat().st_size,
        "notes": notes,
        "mandatory": mandatory,
        "published": time.strftime("%Y-%m-%d"),
    }
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {MANIFEST}")
    print(f"    sha256 {data['sha256']}")
    print(f"    url    {data['url']}")
    return MANIFEST


# ── Publish ───────────────────────────────────────────────────────────────────
def notes_file_for(ver: str) -> Path:
    """The conventional notes file for a version: `RELEASE-NOTES-<ver>.md`.

    ⚠ This exists because the warning below was not enough. Eight of the first
    twenty-six releases went out with a body of `Macronaut 2.0.14` and nothing
    else — the page a person lands on to download, saying nothing about what
    changed. `publish()` printed a warning every time and the release
    succeeded anyway, which is what a warning buys you.

    So the file is now *found* rather than passed. Every release since 2.1.1
    has written one under this name; looking for it costs nothing and removes
    the only step in the flow that had to be remembered.
    """
    return ROOT / f"RELEASE-NOTES-{ver}.md"


def publish(ver: str, notes: str = "") -> None:
    if shutil.which("gh") is None:
        raise SystemExit(
            "error: the GitHub CLI (gh) isn't installed.\n"
            "Install it, run `gh auth login`, or upload dist/Macronaut.exe and "
            "dist/update.json to the release page by hand.")
    if not (EXE.exists() and MANIFEST.exists()):
        raise SystemExit("error: build and write the manifest first")

    manifest_ver = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    if manifest_ver != ver:
        raise SystemExit(
            f"error: dist/update.json says {manifest_ver} but you're publishing "
            f"{ver} — rebuild so they match")
    # Guard against shipping a manifest whose hash doesn't describe this .exe.
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]
    if sha256(EXE) != expected:
        raise SystemExit(
            "error: dist/update.json's sha256 doesn't match dist/Macronaut.exe. "
            "The .exe changed after the manifest was written — rebuild.")

    # Say it out loud at the one moment it matters. An unsigned release makes
    # SmartScreen warn every new user, and that reputation resets with each
    # unsigned build — so it compounds for an app that updates often.
    sys.path.insert(0, str(ROOT))
    import updater
    trusted, reason = updater.signature_status(EXE)
    if not trusted:
        print(f"  ⚠ publishing an UNSIGNED build ({reason}) — SmartScreen will "
              "warn every new user.")

    # The terms travel with the download: the releases repo is public and holds
    # no source, so without these a buyer has no visible licence at all.
    legal = [p for p in (ROOT / "LICENSE", ROOT / "THIRD-PARTY-NOTICES.md")
             if p.exists()]
    if len(legal) < 2:
        print("  ⚠ LICENSE / THIRD-PARTY-NOTICES.md missing — publishing without them")

    # ⚠ Fall back to the manifest's notes, not to the version number.
    #
    # `--publish` is a separate invocation from `--manifest`, so it is entirely
    # natural to pass --notes-file to one and forget it on the other — which is
    # exactly what happened publishing 2.3.0. The old fallback made that
    # succeed quietly: the in-app update dialog showed the full notes while the
    # GitHub release page, which is what a human actually reads, said
    # "Macronaut 2.3.0" and nothing else. Nothing failed and nothing warned.
    #
    # The manifest has already been checked to describe this exact .exe two
    # guards above, so its notes are the right notes by construction.
    if not notes:
        notes = json.loads(MANIFEST.read_text(encoding="utf-8")).get("notes", "")
        if notes:
            print("  · no --notes given; using the notes already in "
                  "dist/update.json")
    # Third source, and the one that needs no remembering: the conventional
    # file. See notes_file_for() for why a warning was not sufficient.
    if not notes:
        conventional = notes_file_for(ver)
        if conventional.is_file():
            notes = conventional.read_text(encoding="utf-8")
            print(f"  · no --notes given; using {conventional.name}")
    if not notes:
        print("  ⚠ publishing with NO release notes. The release page will be "
              f"empty — write {notes_file_for(ver).name}, pass --notes-file, "
              "or fix it afterwards with\n"
              f"      gh release edit v{ver} --repo {_v.UPDATE_REPO} "
              f"--notes-file {notes_file_for(ver).name}")

    tag = f"v{ver}"
    r = _run(["gh", "release", "create", tag,
              str(EXE), str(MANIFEST), *[str(p) for p in legal],
              "--repo", _v.UPDATE_REPO,
              "--title", f"Macronaut {ver}",
              "--notes", notes or f"Macronaut {ver}"])
    if r.returncode != 0:
        raise SystemExit("error: gh release create failed")
    print(f"\nPublished {tag}. Existing installs will find it within 6 hours, "
          "or immediately via Settings → Updates → Check now.")


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bump", metavar="KIND",
                    help="major | minor | patch | an explicit version")
    ap.add_argument("--build", action="store_true", help="run PyInstaller")
    ap.add_argument("--sign", action="store_true",
                    help=f"Authenticode-sign the .exe (cert thumbprint in "
                         f"${SIGN_THUMBPRINT_ENV})")
    ap.add_argument("--manifest", action="store_true",
                    help="write dist/update.json for the current build")
    ap.add_argument("--publish", action="store_true",
                    help="create the GitHub release and upload the assets")
    ap.add_argument("--notes", default="", help="release notes text")
    ap.add_argument("--notes-file", help="read release notes from a file")
    ap.add_argument("--mandatory", action="store_true",
                    help="mark this update as required in the manifest")
    args = ap.parse_args(argv)

    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")

    # Bare invocation = the common path: bump nothing, build, write manifest.
    if not any((args.bump, args.build, args.manifest, args.publish)):
        args.build = args.manifest = True

    ver = _v.__version__
    # ⚠ Resolve the conventional notes file here too, not only in publish().
    # The manifest is what the *in-app* update dialog shows, and it is written
    # by --manifest, which can run in a separate invocation from --publish. If
    # only publish() found the file, the release page would carry the notes
    # while every user's update dialog showed nothing — which is the same bug
    # as the empty release page, pointed at the other audience.
    if not notes and not args.bump:
        conventional = notes_file_for(ver)
        if conventional.is_file():
            notes = conventional.read_text(encoding="utf-8")
    if args.bump:
        ver = bump(args.bump)
        # Re-exec so the build below picks up the new version rather than the
        # one this process imported at startup.
        rest = [a for a in argv if a not in ("--bump", args.bump)]
        return subprocess.run([sys.executable, __file__] + rest, cwd=ROOT).returncode

    if args.build:
        build()
    # Signing rewrites the .exe, so it has to happen before the hash is taken.
    if args.sign:
        sign(EXE)
    if args.manifest:
        write_manifest(ver, notes, args.mandatory)
    if args.publish:
        publish(ver, notes)

    if args.build or args.manifest:
        print(f"\nReady: Macronaut {ver}")
        print("  Test dist/Macronaut.exe, then: python release.py --publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
