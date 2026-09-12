"""The mirror withholds what it is supposed to withhold.

⚠ `publish_source.PRIVATE` is the entire mechanism keeping this repo's private
half out of the public one. CLAUDE.md says so in as many words, and adds the
failure mode: *"Add a private document to the repo without adding it to that
tuple and the next publish ships it."*

Nothing tested that. `test_packaging.py` reads `PRIVATE`, but only to check the
*opposite* direction — that a README image is not accidentally withheld. A file
that should be private and is not would have passed every test in this suite,
and the first sign of it would have been the document itself on GitHub.

So this asks the question that actually matters: **is each document that must
never ship covered by `PRIVATE`?** Plus a second check that fails when somebody
adds a new top-level document and classifies it neither way, because the whole
point is that silence is the dangerous answer.

⚠ **`PRIVATE` is read with `ast`, never by importing the module** — the same
rule, and the same reason, as `test_packaging.py`: `publish_source.py`
reconfigures `sys.stdout` and `sys.stderr` at import time, which inside pytest
are the capture objects, and importing it once cost an hour of a silently
hanging suite. A publishing tool is a program, not a library. Read it.

⚠ Both tests skip in a public clone, where `tools/publish_source.py` is itself
one of the withheld files.
"""
import ast
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "publish_source.py")

# Documents and directories whose contents would be damaging in public. Each
# entry says *why*, because a list of paths with no reasons is a list somebody
# eventually prunes.
MUST_NOT_SHIP = [
    # The agent's own working files and the reasoning archive.
    (".claude/", "session state, hooks, agents, the progress bookmark"),
    ("CLAUDE.md", "the reasoning archive, including unreleased decisions"),
    # The business half.
    ("GROWTH.md", "the SEO plan and the real download numbers"),
    ("NEXT-STEPS-MONETIZATION.md", "pricing and grandfathering plans"),
    ("outreach/", "would read as evidence of astroturfing"),
    ("ROADMAP.md", "unshipped plans"),
    ("BRAND-macronaut.md", "positioning notes"),
    ("FIXES.md", "internal defect list"),
    # Process and early-stage planning.
    ("design/", "early-stage design documents"),
    ("TESTING.md", "the process, not the program"),
    ("scratchpad/", "working files, screenshots and the mutation audit"),
    # The marketing site and the tools that build it.
    ("site/", "the marketing site"),
    ("tools/build_site.py", "the site generator, including the FAQ copy"),
    ("tools/make_hero.py", "site asset generation"),
    ("tools/demo_flow.py", "site asset generation"),
    # Business and signing tooling.
    ("tools/fulfil.py", "order fulfilment"),
    ("tools/traffic_check.py", "traffic measurement"),
    ("tools/mint_license.py", "the licence signer"),
    ("tools/make_selftest_vector.py", "selftest vector generation"),
    # ⚠ And the publisher itself. Its docstring is a map of what is being
    # withheld — publishing the censor's notes advertises the existence and
    # contents of the private half to a reader who would otherwise never have
    # wondered. It was public for a day once.
    ("tools/publish_source.py", "names and describes every withheld file"),
]

# Top-level documents that are meant to be read by the public. Anything else at
# the top level must be covered by PRIVATE, or this suite says so.
PUBLIC_TOP_LEVEL_DOCS = {
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "THIRD-PARTY-NOTICES.md",
}

# Release history is public and stays public: it is the record of what shipped.
PUBLIC_DOC_PREFIXES = ("RELEASE-NOTES-", "NOTES-")


def _private_tuple():
    """The literal strings in `publish_source.PRIVATE`, read without importing."""
    with open(TOOL, "rb") as fh:
        tree = ast.parse(fh.read().decode("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "PRIVATE" for t in node.targets):
            return tuple(e.value for e in node.value.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return ()


def _withheld(path, private):
    """Would `path` be held back? Matches PRIVATE's own prefix semantics."""
    return any(path == p or path.startswith(p) for p in private)


needs_publisher = pytest.mark.skipif(
    not os.path.isfile(TOOL),
    reason="tools/publish_source.py is itself withheld — this is a public clone")


@needs_publisher
def test_every_document_that_must_not_ship_is_withheld():
    private = _private_tuple()
    assert private, "could not read PRIVATE out of publish_source.py"

    missing = [f"{path}  ({why})"
               for path, why in MUST_NOT_SHIP
               if not _withheld(path, private)]

    assert not missing, (
        "publish_source.PRIVATE no longer covers these, so the next publish "
        "ships them:\n  " + "\n  ".join(missing))


@needs_publisher
def test_every_tracked_top_level_document_is_classified():
    """A new document at the top level is public unless somebody says otherwise.

    That default is the dangerous one, so it is the one that has to be noisy.
    """
    private = _private_tuple()
    assert private, "could not read PRIVATE out of publish_source.py"

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.splitlines()
    top_level_docs = [f for f in tracked
                      if "/" not in f and f.lower().endswith(".md")]
    assert top_level_docs, "no top-level markdown found — is this a git checkout?"

    unclassified = [
        f for f in top_level_docs
        if f not in PUBLIC_TOP_LEVEL_DOCS
        and not f.startswith(PUBLIC_DOC_PREFIXES)
        and not _withheld(f, private)
    ]

    assert not unclassified, (
        "these top-level documents would be published and nothing says they "
        "should be:\n  " + "\n  ".join(unclassified)
        + "\n\nAdd each to publish_source.PRIVATE, or to PUBLIC_TOP_LEVEL_DOCS "
          "in this file if it really is meant for the public repo.")
