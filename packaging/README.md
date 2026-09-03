# Packaging manifests

Submissions to the Windows package managers. These became possible on
30 August 2026: all three repositories below want a licence they can name, and
until then Macronaut did not have one.

Nothing here is submitted automatically. Each one is a pull request to somebody
else's repository, under a real name, and that is the maintainer's call to make.
What is stored here is the finished, validated artefact so that submitting is a
copy, not an authoring job.

Both manifests below were checked against the published release, not against a
local build: `Macronaut.exe` was downloaded from the release URL that appears in
them and hashed, and the digest matched
`8a23143a1878753a33e289bcd924e6f39429a3c8c44faf284f16f38900371a69`. That digest
is the single most common reason a package-manager PR fails, so it is worth
re-doing on every version bump rather than trusting the local `dist/`.

## winget — `winget/`

Three files in the layout `microsoft/winget-pkgs` expects:

    manifests/g/GerbenvanPoucke/Macronaut/2.3.3/
      GerbenvanPoucke.Macronaut.yaml               (version)
      GerbenvanPoucke.Macronaut.locale.en-US.yaml  (defaultLocale)
      GerbenvanPoucke.Macronaut.installer.yaml     (installer)

Verified with the real client, `winget v1.29.290`:

    winget validate --manifest packaging/winget/manifests/g/GerbenvanPoucke/Macronaut/2.3.3
    Manifest validation succeeded.

`InstallerType: portable` is the one that fits: Macronaut is a single .exe with
no installer, and winget's own portable handling places it and puts an alias on
PATH. This sidesteps the rule that every package must install unattended — there
is nothing to install. It also means no Start Menu entry, which is normal for
portable packages.

⚠ Two things this has **not** been through, and both are worth knowing before
opening the PR:

- **A local install.** `winget install --manifest` needs the `LocalManifestFiles`
  admin setting, which is off here. The manifest is schema-valid; whether the
  install works end to end is unproven.
- **The winget-pkgs CI.** It downloads the installer into a sandbox and scans it.
  An unsigned 77 MB PyInstaller binary that installs a global keyboard hook is a
  realistic false positive. If it trips, that is a *scanner* verdict, not a
  manifest bug, and the fix is a signed binary rather than a manifest edit.

  ✅ **Measured 3 September 2026, and it is better news than this note assumed.**
  The published 2.3.3 binary — downloaded from the release URL in `update.json`,
  SHA-256 verified against the manifest first — was scanned with Windows
  Defender directly:

      MpCmdRun.exe -Scan -ScanType 3 -File Macronaut.exe -DisableRemediation
      → "found no threats", exit 0

  That is the engine family the winget sandbox runs, so the specific failure
  this note worried about is not currently happening. It is one engine on one
  machine with one set of definitions, so it is evidence rather than a
  guarantee — definitions change, and a *reputation*-based verdict (which is
  what an unsigned binary with no download history actually risks) is not the
  same thing as a signature hit and would not show up here.

- ⚠ **There is no VirusTotal record for the shipped binary at all** — checked
  3 September, the hash returns "Item not found", meaning nobody has ever
  submitted it. Worth deciding deliberately rather than leaving to chance:

  Submitting it would establish a public, checkable verdict across ~70 engines,
  which is a far stronger answer to "why does my antivirus complain" than any
  paragraph on the website, and it would surface any false positive **before**
  a winget reviewer or a user finds it, while there is still time to appeal.

  Against: a VT submission is public and permanent — the sample is shared with
  vendors and subscribers, and it cannot be withdrawn. Today there is no record;
  after submitting there is one, and if an engine does false-positive, that
  record is what a searcher finds. The file is already public on GitHub, so
  nothing is being disclosed — the question is only whether to create the
  record. **This is the maintainer's call, not something to do in passing.**

`PackageIdentifier` is `GerbenvanPoucke.Macronaut`. No `g/GerbenvanPoucke`
publisher folder exists upstream yet and no package matches "Macronaut", so the
name is free. It is permanent once merged — a rename means a new package.

## Scoop — `scoop/macronaut.json`

Goes to the **Extras** bucket (`ScoopInstaller/Extras`), which is where GUI
applications live; Main is for command-line tools only. Extras already carries
`autoclicker.json`, so the category is established there — that entry is
CC-BY-NC and hosted on SourceForge, so a GPL one on GitHub releases compares
well.

Validated against Scoop's own `schema.json` with `jsonschema`: no errors.

`checkver`/`autoupdate` point at the GitHub releases repo, so Scoop's Excavator
bot bumps the version and hash by itself after each release and no manual PR is
needed for updates. Note that means the release tag format `v$version` is now
load-bearing for something outside this repo.

No `persist` block, deliberately: Macronaut keeps macros and settings in
`~/.macronaut`, outside the install directory, so an update cannot lose them.

## Keeping these current

Both files pin version 2.3.3, the URL and the SHA-256. On the next release:

- **Scoop** updates itself via Excavator — nothing to do.
- **winget** needs a new version folder. `wingetcreate update GerbenvanPoucke.Macronaut`
  does it in one command once the package exists upstream.
