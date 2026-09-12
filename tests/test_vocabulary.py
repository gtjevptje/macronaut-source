"""
One object, one name — and a guard so it stays that way.

⚠ Settled 12 September 2026 by the maintainer: the thing you build, save and
run is a **script**. Not a flow, not a macro, not a sequence. `GROWTH.md` §2g
has the counts that prompted it; the short version is that a new user met four
words for one object before doing anything, and one string in the library
taught the contradiction outright — "No saved scripts yet — save a flow, or
import one."

⚠ **This test exists because the rename changed 28 user-visible strings and the
entire suite stayed green.** Nothing pinned the app's own vocabulary, so the
four words had drifted apart over a year without a single failure. A naming
decision that nothing enforces is a naming decision that comes back.

What this checks is deliberately narrow: **user-visible string literals only**,
in the modules that draw the UI. Docstrings and comments are excluded, because
they explain the code to a reader who already knows the history — `flow.py` is
still called `flow.py`, `FlowGraph` is still `FlowGraph`, and renaming those is
churn with real risk and no user-facing benefit. The file on disk is also still
`~/.macronaut/scripts/`, which is what makes *script* the cheap answer: the
word and the storage already agree.
"""
import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The modules that put words in front of a person.
UI_MODULES = [
    "main.py",
    "compact.py",
    "flow.py",
    "flow_dialogs.py",
    "licensing_ui.py",
    "entitlements.py",
    "updater_ui.py",
    "selftest.py",
]

# The retired words, as whole words, any case.
RETIRED = re.compile(r"\b(flows?|macros?|sequences?)\b", re.IGNORECASE)

# ⚠ Legitimate uses, each one a different word that happens to collide.
# Add to this list only when the word genuinely is not naming a Macronaut
# script — and say which meaning it carries.
ALLOWED = [
    # Logitech/Razer G-keys. "Macro key" is the hardware's name for them and
    # has nothing to do with a saved script.
    "Macro keys (G1, G2",
]


def _visible_strings(path):
    """Every string literal a person could end up reading, with docstrings left out.

    Line endings are not normalised — the repo is mixed (``core.autocrlf`` is
    true, and some files sit in the tree as LF), and reading in binary keeps
    this test from caring either way.
    """
    with open(path, "rb") as fh:
        source = fh.read().decode("utf-8")
    tree = ast.parse(source)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body and isinstance(node.body[0], ast.Expr):
                docstrings.add(id(node.body[0].value))

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        text = node.value
        # Internal keys, dotted names and path fragments are not UI copy. A
        # string a person reads is a phrase: it has a space in it.
        if " " not in text.strip():
            continue
        yield node.lineno, text


@pytest.mark.parametrize("module", UI_MODULES)
def test_the_ui_calls_a_script_a_script(module):
    path = os.path.join(REPO, module)
    if not os.path.exists(path):
        pytest.skip(f"{module} is not in this tree")

    offenders = []
    for lineno, text in _visible_strings(path):
        if any(ok in text for ok in ALLOWED):
            continue
        found = RETIRED.search(text)
        if found:
            offenders.append(f"{module}:{lineno}  {found.group(0)!r} in {text[:90]!r}")

    assert not offenders, (
        "User-visible text still calls a script something else:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe object is a script. If this really is a different meaning of the "
          "word (hardware macro keys, say), add it to ALLOWED with the reason."
    )

# ── The documentation people actually read ──────────────────────────────
#
# ⚠ These ship. `publish_source.PRIVATE` withholds CLAUDE.md, GROWTH.md,
# ROADMAP.md and the rest, but README.md, SECURITY.md, CONTRIBUTING.md and
# packaging/README.md go out with the source, and README.md is the first thing
# a visitor reads.
PUBLIC_DOCS = [
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    os.path.join("packaging", "README.md"),
]

# ⚠ Release notes and NOTES-*.md are deliberately NOT in that list. They are a
# record of what shipped on a date, and rewriting them to match a later naming
# decision would falsify the history rather than tidy it.

DOC_ALLOWED = [
    # The market's word, kept on purpose in the headline and the site's meta
    # description. Nobody searches for "visual script recorder".
    "visual macro recorder",
    # Licence compatibility, in THIRD-PARTY-NOTICES' sense of the word.
    "flow into",
]

# Built with chr(10) rather than an escape so that whatever rewrites this file
# next cannot mangle it the way a heredoc once did.
_NL = chr(10)


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_public_docs_call_a_script_a_script(doc):
    path = os.path.join(REPO, doc)
    if not os.path.exists(path):
        pytest.skip(doc + " is not in this tree")

    with open(path, "rb") as fh:
        lines = fh.read().decode("utf-8").splitlines()

    offenders = []
    for n, line in enumerate(lines, 1):
        if any(ok in line for ok in DOC_ALLOWED):
            continue
        found = RETIRED.search(line)
        if found:
            offenders.append("%s:%d  %r in %r" % (doc, n, found.group(0), line.strip()[:90]))

    assert not offenders, (
        "Public documentation still calls a script something else:"
        + _NL + "  " + (_NL + "  ").join(offenders)
        + _NL + _NL
        + "The object is a script. Genuine other meanings go in DOC_ALLOWED."
    )


def test_the_readme_only_names_tabs_that_exist():
    """⚠ The README claimed a "Four-tab layout: Sequence / Basic / Settings /
    Stats" until 12 September 2026 — a UI that stopped existing with the
    2.0 redesign in June, when `MainWindow` became a two-face `_FaceStack` and
    Settings/Stats moved behind the gear. It was wrong on the public repo for
    three months because nothing compared the prose to the code.

    The app has exactly two tabs, both inside the gear panel. Everything else
    is a *face*, reached with the Advanced and Basic links. So: every
    "**X** tab" the README claims must be a real tab.
    """
    with open(os.path.join(REPO, "main.py"), "rb") as fh:
        app = fh.read().decode("utf-8")
    real_tabs = set(re.findall(r'addTab\([^,]+,\s*"([^"]+)"\)', app))
    assert real_tabs, "no addTab calls found - this test needs rewriting for the new UI"

    with open(os.path.join(REPO, "README.md"), "rb") as fh:
        readme = fh.read().decode("utf-8")

    claimed = set(re.findall(r"\*\*([A-Za-z][A-Za-z /-]{0,30}?)\*\*\s+tab", readme))
    invented = sorted(c for c in claimed if c not in real_tabs)

    assert not invented, (
        "README names tabs the app does not have: %r" % (invented,)
        + _NL + "The app's real tabs are: %r" % (sorted(real_tabs),)
        + _NL + "Everything else is a face - say face, or name the control that opens it."
    )


# ⚠ Pages that are *copied* rather than rendered. `build_site.py` renders every
# page in `PAGES` from the app's own constants, so a rename reaches them for
# free — and that is exactly why this one was missed. `site/root/` is pushed to
# the user-pages repo verbatim, so nothing regenerates it and nothing compared
# it to anything. It sat live on https://gtjevptje.github.io/ saying "edit it
# as a flow" for the whole of the rename, and was found by curl'ing the
# deployed page rather than by any test in this file.
#
# The lesson generalises past this one page: the guard has to follow what is
# *published*, not what is *generated*.
HAND_MAINTAINED_PAGES = [
    os.path.join("site", "root", "index.html"),
]


@pytest.mark.parametrize("page", HAND_MAINTAINED_PAGES)
def test_hand_maintained_pages_call_a_script_a_script(page):
    """A published page nothing regenerates still has to use the word.

    Skips rather than fails when the file is absent: `site/` is withheld from
    the public mirror, so on a clean clone this page does not exist and the
    test must not turn a correct absence into a red build.
    """
    path = os.path.join(REPO, page)
    if not os.path.exists(path):
        pytest.skip(page + " is not in this tree (site/ is withheld)")

    with open(path, "rb") as fh:
        lines = fh.read().decode("utf-8").splitlines()

    offenders = []
    for n, line in enumerate(lines, 1):
        if any(ok in line for ok in DOC_ALLOWED):
            continue
        found = RETIRED.search(line)
        if found:
            offenders.append("%s:%d  %r in %r"
                             % (page, n, found.group(0), line.strip()[:90]))

    assert not offenders, (
        "A published page that nothing regenerates still calls a script "
        "something else:"
        + _NL + "  " + (_NL + "  ").join(offenders)
        + _NL + _NL
        + "This page is copied verbatim by build_site.py, so no rename "
          "reaches it on its own."
    )
