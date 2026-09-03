"""Where the line between Free and Pro is drawn, and what happens at it.

`licensing.py` answers "is this copy licensed?". This module answers "does that
matter for what is about to run?" — the whole commercial policy in one file, so
it can be re-argued by editing a tuple rather than by hunting for checks
scattered through the UI.

## The split

**Free is a complete auto-clicker, not a demo.** Clicking, typing, key presses,
drags, scrolls, waits, and short sequences of them — all unlimited, no
watermark, no nag on a timer, no expiry. That is a better tool than the
ad-riddled free autoclickers it is competing with for the same search terms,
and it has to be, because it *is* the marketing: someone whose problem is fully
solved by the free tier tells other people about it, and some of those people
have the other problem.

**Pro is the automation half.** Two families, and the boundary between them is
not arbitrary:

- **Seeing the screen** — Wait-for-Image, Wait-for-Text (OCR), Wait-for-Pixel.
- **Reacting to what it sees** — If/Else, Loop, Go to.

⚠ **Variables are engine-only and must not be advertised.** `flow.N_SETVAR`,
`flow.apply_set_var` and the `var` condition kind are all implemented and all
run, but nothing in the UI can create either one: the palette is nine buttons
and Set Var is not among them, and `flow_dialogs.ConditionWidget.TYPES` offers
image / text / pixel / always. `PRO_NODE_TYPES` still lists the node so that an
old saved flow containing one is priced correctly — that is the only reason.
Three user-facing places said "variables" and no longer do (this file, the
upgrade dialog, the pricing table). If Set Var comes back to the palette, they
go back too; until then, selling it is selling something nobody can reach.

Those are the same line, drawn twice. Everything free is *open-loop*: it
happens on a timer whether or not it worked. Everything paid is *closed-loop*:
the flow looks at the screen and decides. That is the difference between a
clicker and an automation tool, it is the difference in what the two are worth,
and it is a line a user can feel the shape of without reading a pricing table.

**Plus a length limit**, because a long open-loop sequence is real work even
with no branching in it — `FREE_MAX_STEPS` is the point where "I am clicking a
few things" becomes "I have built a process".

## How it is enforced

At the moment Play is pressed, and nowhere else. Specifically **not**:

- **Not when a flow is loaded or edited.** Someone on Free must be able to
  open, read, edit and save a flow that uses Pro steps — a colleague's script,
  or their own from a machine where they are licensed. A gate that refused to
  open a file would destroy the user's own work to protect a feature.
- **Not per node, mid-run.** A flow that stops halfway with an upgrade prompt
  has already moved the mouse around someone's screen for thirty seconds and
  then abandoned it in an unknown state. The check is up-front and total: it
  runs, or it does not start.
- **Not by hiding the features.** The Pro steps stay in the palette, openable
  and configurable, marked. Someone has to be able to build the thing they
  would be buying — the demand for Pro is created by a user discovering they
  want Wait-for-Image, which cannot happen if Wait-for-Image is invisible.
"""
from __future__ import annotations

from typing import List, Tuple

import flow
import licensing

# Detect steps: the flow looks at the screen. `flow.DETECT_KINDS` is the same
# tuple, and is imported rather than copied so that adding a fourth detector
# cannot silently ship it as a free feature.
PRO_ACTION_KINDS = frozenset(flow.DETECT_KINDS)

# Control flow: the flow decides. `N_LABEL` is deliberately absent — a label is
# a name for a place, useless on its own, and only reachable by the Go to that
# is gated. `N_REROUTE`, `N_COMMENT` and `N_FRAME` are absent for the same kind
# of reason: they are drawing, and charging for the ability to tidy a diagram
# would be a petty way to meet someone.
PRO_NODE_TYPES = frozenset({flow.N_IF, flow.N_LOOP, flow.N_SETVAR, flow.N_GOTO})

# How many working steps a free flow may run.
#
# Chosen from what the free tier is *for*: an open-loop sequence someone
# recorded to save themselves a repetitive minute. Twenty is comfortably more
# than any such recording and comfortably less than a process. It is a soft
# number and moving it is a pricing decision, not an engineering one — but move
# it *up* rather than down, because tightening it later takes a working flow
# away from someone who already had it.
FREE_MAX_STEPS = 20

BUY_URL = "https://gtjevptje.github.io/Macronaut/#buy"

# Where the source is. Macronaut went GPL-3.0-or-later on 30 August 2026,
# and this is the link that makes that claim checkable rather than a
# sentence on a page.
#
# ⚠ It earns its place in the *app* — Settings ▸ About links to it —
# because of what Macronaut is: an unsigned .exe that installs a global
# keyboard hook and is downloaded by people who have just been shown a
# SmartScreen warning about it. "Read the code" is the only answer to
# that which does not ask for trust, and it has to be reachable from
# inside the thing being distrusted, not only from the site that sold it.
SOURCE_URL = "https://github.com/gtjevptje/macronaut-source"

# What Pro costs, and the promise printed next to it. One definition, read by
# the dialogs, the Settings card, the landing page and the public README — a
# customer who sees two different numbers has been told that at least one of
# them is a lie.
#
# ⚠ Lives here rather than in `licensing_ui` so that reading the price does not
# require importing Qt. `tools/build_site.py` renders the shop from these, and
# a build script that needs a GUI toolkit to know a price is a build script
# that breaks the first time it runs anywhere without one.
PRICE = "€9.99"
TERMS = "One payment. Yours forever, on every computer you own."

# Where a customer reaches a human. Not a new disclosure — it is on the public
# site and in the app's own licence dialog.
#
# ⚠ It used to be the CONTACT block of the EULA as well, which is what a test
# pinned it against. `LICENSE` is the GPL now and names no address at all, so
# `licensing_ui.py` is the only shipped copy — see
# test_the_address_the_page_promises_a_reply_at_is_reachable_in_the_app.
#
# ⚠ It has to be on the page, because the page makes a promise that needs it:
# "e-mail me and I will refund you", with no address anywhere on it. A refund
# offer nobody can act on is worse than no refund offer, and it is read at the
# exact moment somebody is deciding whether to hand €29 to a stranger. The
# same address is what `tools/fulfil.py --resend` exists to answer.
#
# ⚠ Pinned against the LICENSE by a test. These two disagreeing would mean the
# contract and the shop name different sellers.
CONTACT_EMAIL = "gerbenvanpoucke0@gmail.com"

# ⚠⚠ THE PAID TIER IS BUILT BUT NOT ENFORCED. Everything below still says
# which features are Pro; this decides whether saying so costs anyone
# anything, and right now it does not. Every feature is free for everyone.
#
# The reason is distribution, not charity. Macronaut has had about 45
# downloads. The people who would be gated are the handful who have already
# built something real with it — and 2.1.1, which is what they are running,
# ships no licence check at all, so switching this on would take working
# automations away from the only users there are. Measured against the
# developer's own library at the time this was written: 8 scripts, 8 refusals.
# Growing the audience is worth more than converting a dozen people, and it
# only stays worth more until there is an audience.
#
# ⚠ Flipping this to True is a *pricing* decision and it is not free of
# consequence: it retroactively gates flows people already have. Do it in a
# release whose notes lead with it, and grandfather anyone who was already
# here — see §0 of NEXT-STEPS-MONETIZATION.md, which is written up and still
# the plan.
#
# ⚠ It gates enforcement ONLY, never policy. `pro_features_used`,
# `is_node_pro`, `runs_on_free` and `PRO_*` go on answering "is this the paid
# half?" exactly as before, so the whole split stays live and under test
# rather than rotting behind a flag until the day it is turned on.
ENFORCED = False


def _label_for_kind(kind: str) -> str:
    return {"wait_image": "Wait for image", "wait_text": "Wait for text",
            "wait_pixel": "Wait for pixel"}.get(kind, kind)


def _label_for_type(ntype: str) -> str:
    return {flow.N_IF: "If / Else", flow.N_LOOP: "Loop",
            flow.N_SETVAR: "Set variable", flow.N_GOTO: "Go to"}.get(ntype, ntype)


def pro_features_used(graph) -> List[str]:
    """The Pro features this flow contains, named the way the palette names
    them, de-duplicated, in a stable order. Empty for a flow that runs free.

    Reports *what is in the flow*, not what the licence permits — so the same
    call can label the canvas for a licensed user, who is entitled to see which
    of their steps are the paid ones.
    """
    found = []
    for node in graph.nodes.values():
        if node.type in PRO_NODE_TYPES:
            found.append(_label_for_type(node.type))
        elif flow.action_kind(node) in PRO_ACTION_KINDS:
            found.append(_label_for_kind(flow.action_kind(node)))
    seen, ordered = set(), []
    for name in found:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def step_count(graph) -> int:
    """Working steps, by the same definition Play already uses for "is this
    flow empty?" — so the number the limit counts is the number the footer
    shows, and a user is never told they have 21 steps while looking at 19."""
    return sum(1 for n in graph.nodes.values() if n.type in flow.WORK_TYPES)


def is_node_pro(node) -> bool:
    """Whether this node is a paid feature. True regardless of licence."""
    return (node.type in PRO_NODE_TYPES
            or flow.action_kind(node) in PRO_ACTION_KINDS)


def show_pro_badge(node) -> bool:
    """Whether the canvas should mark this node PRO right now.

    ⚠ The licence check is half the answer and the important half. A permanent
    "PRO" chip on a step someone has already paid for is an advert shown to a
    customer, which is the one audience it can only annoy.

    ⚠ And nothing is badged while `ENFORCED` is False. The chip's whole meaning
    is "pressing Play on this will stop and ask you for money"; with nothing
    enforced that does not happen, so the badge would be marking a step that
    works perfectly as one that does not. A label people learn to disbelieve
    is worse than no label on the day it starts being true.
    """
    return ENFORCED and is_node_pro(node) and not licensing.is_pro()


def runs_on_free(graph) -> bool:
    """Whether the free tier could run this flow — regardless of any licence.

    ⚠ Deliberately licence-blind, unlike `check`. It answers a question about
    the *flow* ("is this inside the free tier?"), which is what a build script
    counting free starters and a test pinning one need — and both would report
    every flow as free when run on a machine that happens to hold a key.

    `check` is the licence-aware caller and shares this definition, so the
    boundary is stated once.
    """
    return not pro_features_used(graph) and step_count(graph) <= FREE_MAX_STEPS


def check(graph) -> Tuple[bool, str, List[str]]:
    """(may it run, why not, which features are responsible).

    The message is written to be shown to a person as-is. It names what they
    built rather than what they lack, because "Wait for image needs Pro" is a
    fact about their flow and "upgrade to unlock" is a fact about our pricing,
    and only one of those tells them anything.
    """
    # ⚠ The gate is switched off at the top, not wired away lower down. Every
    # call site, every dialog and every test below this line goes on working
    # exactly as written, so turning the tier on later is this one constant and
    # not an archaeology exercise. See `ENFORCED`.
    if not ENFORCED:
        return True, "", []

    if licensing.is_pro():
        return True, "", []

    if runs_on_free(graph):
        return True, "", []

    features = pro_features_used(graph)
    steps = step_count(graph)
    over = steps > FREE_MAX_STEPS

    reasons = []
    if features:
        reasons.append(
            f"This flow uses {_join(features)}, which "
            f"{'are' if len(features) > 1 else 'is'} part of Macronaut Pro.")
    if over:
        reasons.append(
            f"It has {steps} steps; the free tier runs up to {FREE_MAX_STEPS}.")
    return False, " ".join(reasons), features


def _join(names: List[str]) -> str:
    """"A", "A and B", "A, B and C" — the shape a sentence needs."""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]
