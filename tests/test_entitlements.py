"""The Free/Pro line: where it falls, and that pressing Play respects it.

`test_licensing.py` proves a key cannot be forged. This file proves the key is
*consulted* — which is the other half, and the half that fails silently. A gate
that never runs looks exactly like a gate nobody has tried to get past.
"""
import ast
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import entitlements
import flow
import licensing

# ⚠ `site/` and `tools/build_site.py` are the marketing website and its
# generator. They are not part of the program and are held back from the public
# repository, so on a contributor's checkout the tests below have nothing to
# read. They skip rather than fail: a red suite nobody outside can fix is worse
# than a test that says plainly why it did not run.
_SITE = Path(__file__).resolve().parent.parent / "site"
_BUILD_SITE = Path(__file__).resolve().parent.parent / "tools" / "build_site.py"
needs_site = pytest.mark.skipif(
    not (_SITE.is_dir() and _BUILD_SITE.is_file()),
    reason="site/ and tools/build_site.py are the website, not the program, "
           "and are not in this checkout")



# ── Building flows to test against ────────────────────────────────────────────

def _graph(*specs):
    """A flow from a shorthand: "click" is an action kind, "if" a node type."""
    g = flow.FlowGraph()
    g.add_node(flow.N_START)
    for spec in specs:
        if spec in (flow.N_IF, flow.N_LOOP, flow.N_SETVAR, flow.N_GOTO,
                    flow.N_LABEL, flow.N_COMMENT, flow.N_REROUTE, flow.N_FRAME):
            g.add_node(spec)
        else:
            g.add_node(flow.N_ACTION, {"step": {"kind": spec}})
    return g


@pytest.fixture(autouse=True)
def tier_switched_on(monkeypatch):
    """Every test in this file exercises the paid tier as though it were live.

    ⚠ `entitlements.ENFORCED` is **False** in the shipped build — nothing is
    gated today, on purpose, because the only users there are would have
    working automations taken away from them. The split is still the product's
    design and the thing that will eventually be sold, so it stays under test
    at full strength; a tier that stopped being exercised the day it was
    switched off would have quietly rotted by the day it is switched back on.

    The few tests that pin the *unenforced* behaviour opt out by setting it
    back to False themselves.
    """
    monkeypatch.setattr(entitlements, "ENFORCED", True)


@pytest.fixture(autouse=True)
def free_by_default(monkeypatch, tmp_path):
    """Every test starts on the free tier, whatever this machine is licensed as.

    ⚠ Without this, the suite passes on the developer's activated machine and
    fails nowhere else — or worse, passes everywhere while testing nothing,
    because a licensed copy is allowed to run all of it.
    """
    import settings
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)
    licensing.refresh()
    yield
    licensing.refresh()


@pytest.fixture
def licensed(monkeypatch):
    monkeypatch.setattr(licensing, "_cached",
                        licensing.License(tier=licensing.APP_TIER_PRO,
                                          email="buyer@example.com"))


# ── Where the line falls ──────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["click", "move", "drag", "scroll", "key",
                                  "combo", "text", "wait", "autoclick"])
def test_every_open_loop_step_is_free(kind):
    """The free tier has to be a real auto-clicker, not a demo — this is the
    list that makes it one, pinned so a refactor cannot quietly move a step
    behind the paywall."""
    allowed, reason, _ = entitlements.check(_graph(kind))
    assert allowed, f"{kind} should be free: {reason}"


@pytest.mark.parametrize("kind", ["wait_image", "wait_text", "wait_pixel"])
def test_every_detect_step_needs_pro(kind):
    allowed, reason, features = entitlements.check(_graph(kind))
    assert not allowed
    assert features and reason


@pytest.mark.parametrize("ntype", [flow.N_IF, flow.N_LOOP, flow.N_SETVAR,
                                   flow.N_GOTO])
def test_every_branching_node_needs_pro(ntype):
    allowed, _, features = entitlements.check(_graph(ntype))
    assert not allowed
    assert features


@pytest.mark.parametrize("ntype", [flow.N_LABEL, flow.N_COMMENT,
                                   flow.N_REROUTE, flow.N_FRAME])
def test_annotation_and_scaffolding_nodes_are_free(ntype):
    """Charging for the ability to tidy a diagram would be a petty way to meet
    someone, and a Label is useless without the Go to that is already gated."""
    allowed, _, _ = entitlements.check(_graph("click", ntype))
    assert allowed


def test_the_detect_list_is_taken_from_flow_not_copied():
    """A fourth detector must not ship free by omission. `entitlements` imports
    the tuple rather than restating it; this fails if someone inlines it."""
    assert entitlements.PRO_ACTION_KINDS == frozenset(flow.DETECT_KINDS)


# ── The step limit ────────────────────────────────────────────────────────────

def test_a_flow_at_the_limit_runs_and_one_past_it_does_not():
    at = _graph(*["click"] * entitlements.FREE_MAX_STEPS)
    over = _graph(*["click"] * (entitlements.FREE_MAX_STEPS + 1))
    assert entitlements.check(at)[0] is True
    assert entitlements.check(over)[0] is False


def test_the_limit_counts_what_the_footer_counts():
    """⚠ The number in the refusal must match the number on screen. Counting
    all nodes instead of working ones would tell someone they have 24 steps
    while their flow plainly shows 20, which reads as a broken product rather
    than a limit."""
    g = _graph("click", "click", flow.N_COMMENT, flow.N_FRAME, flow.N_LABEL)
    assert entitlements.step_count(g) == 2


def test_the_step_limit_and_a_pro_step_are_reported_together():
    """Someone over the limit *and* using Detect should not fix one, press
    Play, and be refused again for the other."""
    g = _graph(*(["click"] * 25 + ["wait_image"]))
    allowed, reason, _ = entitlements.check(g)
    assert not allowed
    assert "Wait for image" in reason and "26 steps" in reason


# ── A licence lifts all of it ─────────────────────────────────────────────────

def test_a_licensed_copy_runs_everything(licensed):
    g = _graph(*(["click"] * 50 + ["wait_image", "wait_text", "wait_pixel",
                                   flow.N_IF, flow.N_LOOP, flow.N_GOTO]))
    allowed, reason, _ = entitlements.check(g)
    assert allowed, reason


def test_pro_features_are_still_named_for_a_licensed_copy(licensed):
    """The canvas badges them either way — a paying customer is entitled to see
    which of their steps are the paid ones."""
    assert entitlements.pro_features_used(_graph("wait_image")) == ["Wait for image"]


# ── How it reads ──────────────────────────────────────────────────────────────

def test_the_reason_names_the_features_not_the_pricing():
    _, reason, _ = entitlements.check(_graph("wait_image", flow.N_IF))
    assert "Wait for image" in reason and "If / Else" in reason
    for salesy in ("upgrade", "unlock", "just", "only €", "buy now"):
        assert salesy.lower() not in reason.lower(), salesy


def test_features_are_listed_once_and_read_as_a_sentence():
    g = _graph("wait_image", "wait_image", "wait_text", flow.N_IF)
    names = entitlements.pro_features_used(g)
    assert names == ["Wait for image", "Wait for text", "If / Else"]
    _, reason, _ = entitlements.check(g)
    assert "Wait for image, Wait for text and If / Else" in reason


def test_an_empty_flow_is_allowed():
    """Play already refuses an empty flow for its own reasons; the licence gate
    must not be the thing that speaks first, or a brand-new install opens with
    a sales dialog."""
    assert entitlements.check(flow.FlowGraph())[0] is True


# ── The gate, at the place it actually runs ───────────────────────────────────

@pytest.fixture
def tab(qapp):
    import main as main_mod
    t = main_mod.SequenceTab(main_mod.SettingsManager())
    yield t
    t.hide()


def test_play_refuses_a_pro_flow_on_a_free_copy(tab, monkeypatch):
    """THE test in this file. Everything else is policy; this is enforcement.

    `start_playback` must return before it builds a worker — not stop early,
    not fail mid-run. A flow that starts and then aborts has already moved the
    mouse across somebody's desktop.
    """
    shown = []
    monkeypatch.setattr("licensing_ui.prompt_for_upgrade",
                        lambda *a, **k: shown.append(a) or False)
    tab._graph = _graph("wait_image")
    assert tab.start_playback() is None
    assert shown, "the user was refused with no explanation"
    assert not tab.is_playing()
    assert tab._worker is None and tab._thread is None


def test_play_runs_a_free_flow_without_ever_asking(tab, monkeypatch):
    """The free tier must never see this dialog. A clicker that asks about
    money when you press Play is one people uninstall.

    ⚠ Asserts on `start_playback`'s return value rather than on `tab._worker`.
    The worker is cleared again the moment the run finishes, and a stubbed
    `run()` finishes immediately — so reading the attribute afterwards reports
    None for a run that started perfectly well, and the test fails on its own
    tidying-up.
    """
    monkeypatch.setattr("licensing_ui.prompt_for_upgrade",
                        lambda *a, **k: pytest.fail("prompted on a free flow"))
    # The worker must not actually reach a real mouse; conftest blocks the
    # backends, and stubbing run() keeps even the loop out of this session.
    monkeypatch.setattr("flow_exec.FlowWorker.run", lambda self: None)
    tab._graph = _graph("click")
    try:
        assert tab.start_playback() is not None, "a free flow should have run"
    finally:
        tab.stop_playback()


def test_activating_during_the_prompt_lets_the_run_continue(tab, monkeypatch):
    """Making someone press Play a second time after paying is a poor
    thank-you, so the gate re-checks instead of giving up."""
    def activate(*_a, **_k):
        monkeypatch.setattr(licensing, "_cached",
                            licensing.License(tier=licensing.APP_TIER_PRO))
        return True
    monkeypatch.setattr("licensing_ui.prompt_for_upgrade", activate)
    monkeypatch.setattr("flow_exec.FlowWorker.run", lambda self: None)
    tab._graph = _graph("wait_image")
    tab.start_playback()
    try:
        assert tab._worker is not None, "an activated copy should have run"
    finally:
        tab.stop_playback()


def test_a_launcher_hotkey_run_is_gated_too(tab, monkeypatch):
    """⚠ A detached run takes its graph as an argument and skips most of the
    canvas bookkeeping — an easy place for a second, ungated code path to
    appear. It goes through the same call, so it goes through the same gate."""
    monkeypatch.setattr("licensing_ui.prompt_for_upgrade", lambda *a, **k: False)
    assert tab.start_playback(_graph("wait_text")) is None
    assert not tab.is_playing()


# ── The dialogs ───────────────────────────────────────────────────────────────

def test_the_licence_dialogs_have_no_black_boxes(qapp):
    """The blanket `background: $bg` rule paints any plain layout-only QWidget
    over the card behind it — the bug that put a black square in the If editor
    and an invisible text field in the comment prompt."""
    from test_gui_offscreen import opaque_containers
    import licensing_ui

    for dlg in (licensing_ui.ActivateDialog(),
                licensing_ui.UpgradeDialog(reason="because", features=["x"])):
        try:
            assert not opaque_containers(dlg), type(dlg).__name__
        finally:
            dlg.hide()


def test_a_refused_key_can_be_read_in_full(qapp):
    """The one label in the app that a paying customer reads while stuck.

    ⚠ `licensing_ui._wrap` pins a minimum height measured from the label's
    text at the time — and this one is built empty, so the floor it sets is a
    single line. The refusal message wraps to two. If the layout ever stops
    growing it (a fixed dialog height, a stretch above it), the tail is
    silently not drawn and someone who has just paid €29 is told half of why
    their key did not work. Nothing about the string can see that.
    """
    import licensing_ui
    dlg = licensing_ui.ActivateDialog()
    try:
        dlg.show()
        dlg._field.setPlainText("MN1-NOT-A-REAL-KEY")
        dlg._activate()
        qapp.processEvents()
        assert dlg._status.text(), "a refused key said nothing at all"
        assert dlg._help.isVisible(), "no way out was offered"
        assert entitlements.CONTACT_EMAIL in dlg._help.text(), (
            "the way out does not say where to write")
        for what, lbl in (("refusal", dlg._status), ("offer of help", dlg._help)):
            needed = lbl.heightForWidth(lbl.width())
            assert lbl.height() >= needed, (
                f"the {what} is clipped: {lbl.height()}px shown, "
                f"{needed}px of text")
    finally:
        dlg.hide()


def test_the_price_is_on_the_button(qapp):
    """It is not behind a click, and it is not in prose the eye skips. Someone
    deciding whether to buy should see the number on the thing they press."""
    from PySide6.QtWidgets import QPushButton
    import licensing_ui
    dlg = licensing_ui.UpgradeDialog(reason="r")
    try:
        labels = [b.text() for b in dlg.findChildren(QPushButton)]
        assert any(licensing_ui.PRICE in t for t in labels), labels
    finally:
        dlg.hide()


@needs_site
@pytest.mark.parametrize("name", ["index.html", "README.md"])
def test_the_app_and_the_site_quote_one_price_and_one_limit(name):
    """A second copy of either number is a customer being shown two answers.
    Both artefacts are generated from the app's own constants by
    `tools/build_site.py` for exactly this reason — this fails if someone edits
    a built file by hand, or changes a constant without rebuilding."""
    built = Path(__file__).resolve().parent.parent / "site" / name
    if not built.exists():
        pytest.skip(f"{name} not built in this checkout")
    text = built.read_text(encoding="utf-8")
    assert entitlements.PRICE in text
    assert str(entitlements.FREE_MAX_STEPS) in text


@needs_site
def test_the_published_page_never_ships_an_unfilled_token():
    """A `{{PRICE}}` left visible on the pricing page is the most expensive
    typo this project could make."""
    import re
    site = Path(__file__).resolve().parent.parent / "site"
    names = [n for _s, n, _p, _f in _build_site_module().PAGES] + ["README.md"]
    for name in names:
        built = site / name
        if built.exists():
            assert not re.findall(r"\{\{[A-Z_]+\}\}",
                                  built.read_text(encoding="utf-8")), name


# ── What the shipped build actually does: nothing is gated ───────────────────

def test_the_shipped_build_does_not_enforce_the_tier():
    """⚠ Pins the *shipped* value, which every other test in this file
    overrides. Turning enforcement on is a pricing decision with a
    consequence — it retroactively stops flows people already have — so it
    should never happen as a side effect of an unrelated edit.

    ⚠ Read out of the source with `ast`, not off the imported module: the
    autouse fixture at the top of this file patches `ENFORCED` to True for
    everything here, so an assertion against the attribute would be testing
    the fixture. This is the one test that has to see what actually ships.
    """
    import ast
    src = (Path(__file__).resolve().parent.parent / "entitlements.py"
           ).read_text(encoding="utf-8")
    shipped = [n.value.value
               for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == "ENFORCED" for t in n.targets)
               and isinstance(n.value, ast.Constant)]
    assert shipped == [False], (
        f"entitlements.ENFORCED ships as {shipped}. If switching the paid "
        "tier on is deliberate, read section 0 of "
        "NEXT-STEPS-MONETIZATION.md first: existing users lose working "
        "automations unless they are grandfathered.")


@pytest.fixture
def not_enforced(monkeypatch):
    monkeypatch.setattr(entitlements, "ENFORCED", False)


def test_nothing_is_refused_while_the_tier_is_off(not_enforced):
    """Everything, at once: every detector, every branching node, and well
    past the step limit."""
    g = _graph(*(["click"] * (entitlements.FREE_MAX_STEPS + 20)
                 + ["wait_image", "wait_text", "wait_pixel",
                    flow.N_IF, flow.N_LOOP, flow.N_SETVAR, flow.N_GOTO]))
    allowed, reason, _ = entitlements.check(g)
    assert allowed, reason
    assert reason == ""


def test_nothing_is_badged_while_the_tier_is_off(not_enforced):
    """⚠ A PRO chip means "pressing Play here will stop and ask you for
    money". With nothing enforced that does not happen, so the chip would be
    marking a step that works perfectly as one that does not — and a label
    people have learned to disbelieve is worse than no label at all on the
    day it starts being true."""
    g = _graph("wait_image", flow.N_LOOP)
    for node in g.nodes.values():
        assert not entitlements.show_pro_badge(node), node.type


def test_the_policy_still_knows_which_half_is_paid(not_enforced):
    """⚠ The switch gates enforcement only. If it also silenced the policy,
    the whole split would rot behind the flag until the day it is turned on —
    and the tests above, which are the only thing keeping it honest, would be
    exercising nothing."""
    g = _graph("wait_image", flow.N_LOOP)
    assert entitlements.pro_features_used(g) == ["Wait for image", "Loop"]
    assert not entitlements.runs_on_free(g)
    assert entitlements.PRO_ACTION_KINDS == frozenset(flow.DETECT_KINDS)


def test_play_runs_a_pro_flow_while_the_tier_is_off(tab, monkeypatch,
                                                    not_enforced):
    """The one that matters: not policy, enforcement, at the only place it is
    ever applied. An existing user's Wait-for-image flow has to still run."""
    asked = []
    monkeypatch.setattr("licensing_ui.prompt_for_upgrade",
                        lambda *a, **k: asked.append(a) or False)
    tab._graph = _graph("wait_image", flow.N_LOOP)
    tab.start_playback()
    try:
        assert not asked, "the user was asked to pay while the tier is off"
        assert tab.is_playing()
    finally:
        tab.stop_playback()


def _delivery_email_or_skip() -> str:
    """The delivery e-mail's text, whitespace-normalised — or skip.

    ⚠ Read as text rather than imported: `tools/fulfil.py` pulls in
    `mint_license`, which is the signing tool, and a test suite has no business
    anywhere near the private key.

    ⚠ And it is skipped rather than failed when the file is absent, because it
    is **deliberately absent from the public repository**. `fulfil.py` turns a
    paid order into a licence key and the e-mail that delivers it; that is
    business operations rather than part of the program, so `publish_source.py`
    holds it back. Without this guard a contributor cloning the public repo
    meets two red tests that cannot pass for them and are not about anything
    they can see -- the same welcome three other tests gave before CI caught
    them.
    """
    fulfil = Path(__file__).resolve().parent.parent / "tools" / "fulfil.py"
    if not fulfil.is_file():
        pytest.skip("tools/fulfil.py is private and not in this checkout")
    return " ".join(fulfil.read_text(encoding="utf-8").split())


def test_the_delivery_email_describes_controls_that_exist():
    """The one piece of copy a paying customer follows step by step.

    ⚠ Read as text rather than imported: `tools/fulfil.py` pulls in
    `mint_license`, which is the signing tool, and a test suite has no business
    anywhere near the private key.

    The failure this pins is silent and expensive. Rename the button and the
    delivery e-mail keeps confidently telling everyone who buys Pro to click
    something that is not there — and nobody finds out except the customer,
    who is already holding a key that will not go in.
    """
    # ⚠ Whitespace-normalised: the template wraps at 79 columns, so a label can
    # sit across a line break and read perfectly while matching no literal at
    # all. "Wait for text" is split that way today. The first version of the
    # test below failed on exactly that, and it was the test that was wrong.
    email = _delivery_email_or_skip()
    app = (Path(__file__).resolve().parent.parent
           / "main.py").read_text(encoding="utf-8")
    for control in ("Your licence", "Enter a licence key"):
        assert control in email, f"the e-mail stopped mentioning {control!r}"
        assert control in app, (
            f"the e-mail sends buyers to {control!r}, which main.py no longer "
            "has")


def test_the_delivery_email_sells_every_detector_that_exists():
    """`PRO_ACTION_KINDS` is imported from `flow.DETECT_KINDS` so that a fourth
    detector cannot ship free by omission. The delivery e-mail lists them by
    hand, so the same fourth detector would arrive unmentioned — a customer
    told they bought three things when they bought four."""
    email = _delivery_email_or_skip()
    for kind in entitlements.PRO_ACTION_KINDS:
        label = entitlements._label_for_kind(kind)
        assert label in email, (
            f"the delivery e-mail never mentions {label!r}, which is a Pro "
            "feature the customer has just paid for")


def test_the_address_the_page_promises_a_reply_at_is_reachable_in_the_app():
    """⚠ This used to pin `CONTACT_EMAIL` against the EULA's CONTACT block,
    because a shop and a contract naming different sellers is a real problem.

    That EULA is gone — `LICENSE` is the GNU GPL as of 30 August 2026, and the
    GPL names no seller and carries no address, correctly: it is a grant of
    freedoms, not a contract with a vendor.

    The thing the old test was protecting did not go away with it. The address
    is the only route by which a lost licence key is resent and the only way a
    refund can be asked for, and the page promises both. An address that lives
    solely on a web page is one the user cannot reach from the app they have
    already downloaded, which is exactly the moment they need it. So the
    assertion moves to what still ships it.
    """
    root = Path(__file__).resolve().parent.parent
    licence = (root / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in licence

    ui = (root / "licensing_ui.py").read_text(encoding="utf-8")
    assert "CONTACT_EMAIL" in ui, (
        "nothing inside the app tells a user where to write; the address is "
        "on the website only, and the website is not what they have open")


@needs_site
def test_the_page_can_be_replied_to():
    """⚠ The page promises "e-mail me and I will refund you" and, until now,
    carried no address anywhere on it. A refund offer nobody can act on is
    worse than none — it is read at the moment somebody is deciding whether to
    send €29 to a stranger, and it is also the only route by which a lost
    licence key can ever be resent (`tools/fulfil.py --resend`)."""
    root = Path(__file__).resolve().parent.parent
    for name in ("index.html", "README.md"):
        built = root / "site" / name
        if not built.exists():
            pytest.skip(f"{name} not built in this checkout")
        text = built.read_text(encoding="utf-8")
        assert entitlements.CONTACT_EMAIL in text, f"{name} has no address"
        assert f"mailto:{entitlements.CONTACT_EMAIL}" in text, (
            f"{name} prints the address but does not make it clickable")


@needs_site
def test_the_smartscreen_warning_reaches_the_person_downloading():
    """⚠ Placement is the whole value of this sentence, so it is what is pinned.

    The .exe is unsigned, so Windows meets every new user with a blue box whose
    only obvious button is *Don't run*. The page has always explained how to
    get past it — in the last section before the footer, on a page whose
    Download button is above the fold. A visitor clicks, leaves, hits the box,
    and never scrolls back to the one sentence that would have saved them.

    So the instruction has to sit at the point of the decision. This asserts it
    appears before the first `<section>` (i.e. inside the hero, under the
    button) rather than merely appearing somewhere.

    ⚠ Anchor on the visible element, not on the words. "Run anyway" already
    appears at byte 5501 of the old page — inside the FAQ's JSON-LD in the
    <head>, which no human reads — so a test that merely looked for the phrase
    early in the file passed against the exact layout it was written to
    forbid. The first draft of this test did exactly that.
    """
    root = Path(__file__).resolve().parent.parent
    for name, marker, first_section in (
            ("index.html", 'class="under heads-up"', "<section"),
            ("README.md", "on first run", "## What it is")):
        built = root / "site" / name
        if not built.exists():
            pytest.skip(f"{name} not built in this checkout")
        text = built.read_text(encoding="utf-8")
        assert marker in text, (
            f"{name} lost the heads-up under the download button")
        assert "Run anyway" in text[text.index(marker):
                                    text.index(marker) + 400], (
            f"{name}: the heads-up no longer says what to click")
        assert text.index(marker) < text.index(first_section), (
            f"{name}: the SmartScreen instruction has drifted below the fold, "
            "where the people who need it have already left")


@needs_site
def test_the_page_only_points_at_pictures_that_exist():
    """A hero that 404s is a page that looks broken above the fold.

    The screenshot is generated (`tools/make_hero.py`) into a gitignored
    folder, so nothing in a diff would ever show it missing — and `--publish`
    used to copy only the HTML, which meant regenerating or renaming it broke
    the live page silently.
    """
    import re
    site = Path(__file__).resolve().parent.parent / "site"
    page = site / "index.html"
    if not page.exists():
        pytest.skip("index.html not built in this checkout")
    refs = re.findall(r'(?:src|href)="(?!https?:|#|mailto:)([^"]+)"',
                      page.read_text(encoding="utf-8"))

    # ⚠ `site/assets/` is gitignored on purpose — it is a local copy pulled
    # down so the page can be previewed with relative paths, and the real
    # images live in the public repo beside the published page. So a clean
    # checkout (CI, a contributor, a second machine) legitimately has no
    # `site/assets/` at all, and failing there would be reporting a deliberate
    # arrangement as a bug. It is the *screenshots being regenerated or
    # renamed* this guards against, which is a thing that only happens on a
    # machine that has them.
    #
    # Absent the whole directory, skip only the references into it. Present it,
    # and every one of them is checked as before. Everything outside it is
    # checked either way, because that is all tracked.
    have_assets = (site / "assets").is_dir()
    missing = [r for r in refs
               if not (site / r).exists()
               and (have_assets or not r.startswith("assets/"))]
    assert not missing, missing
    if not have_assets:
        pytest.skip("site/assets/ is not in this checkout — hero images "
                    "unchecked; the rest of the page's links were verified")


@needs_site
def test_the_hero_is_declared_at_the_size_it_actually_is():
    """`width`/`height` reserve the box before the picture loads. Wrong ones
    squash it into someone else's aspect ratio — which is what happened when
    they were typed by hand, and is invisible in the markup."""
    import re
    import struct
    root = Path(__file__).resolve().parent.parent
    page, hero = root / "site" / "index.html", root / "site" / "assets" / "hero.png"
    if not (page.exists() and hero.exists()):
        pytest.skip("site not built in this checkout")
    head = hero.read_bytes()[:24]
    w, h = struct.unpack(">II", head[16:24])
    m = re.search(r'class="shot"[^>]*width="(\d+)"[^>]*height="(\d+)"',
                  page.read_text(encoding="utf-8"))
    assert m, "no <img class=shot> with dimensions"
    assert (int(m.group(1)), int(m.group(2))) == (w, h)


@needs_site
def test_publishing_carries_every_file_the_page_needs():
    """The copy step and the `git add` list are two places that have to agree.
    They did not: assets were copied nowhere and added nowhere, and the live
    page kept an image only because an earlier hand-push had left one there.

    The pages themselves are no longer named here — they come from
    `build_site.PAGES`, which the next test checks reaches every step.
    """
    source = (Path(__file__).resolve().parent.parent
              / "tools" / "build_site.py").read_text(encoding="utf-8")
    added = source.split('"git", "add"', 1)[1].split("+ [k.name", 1)[0]
    for name in ("README.md", ".nojekyll", "assets", "page_paths"):
        assert name in added, name


def _build_site_module():
    """`tools/` is not a package, so it is loaded by path."""
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "tools" / "build_site.py"
    spec = importlib.util.spec_from_file_location("_build_site_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_site
def test_every_page_reaches_the_sitemap():
    """⚠ The failure this exists for is silent, which is why it is pinned.

    Adding a page used to mean editing four separate lists — render it, copy
    it into the clone, `git add` it, and put it in the sitemap. Miss the
    sitemap and the page publishes perfectly, opens perfectly in a browser,
    and is never crawled by anything: for a page whose entire purpose is
    search traffic, it does not exist. Nothing about that is visible in a
    diff, on the live site, or to anyone clicking around.

    So `PAGES` is the one definition, and this asserts it actually reaches the
    two places that cannot be checked by looking at the page.
    """
    bs = _build_site_module()
    site = Path(__file__).resolve().parent.parent / "site"

    assert bs.PAGES, "the site has no pages at all"
    xml = bs.sitemap()
    for src, name, _prio, _freq in bs.PAGES:
        assert (site / src).exists(), f"{name}: template {src} is missing"
        # The home page is the bare directory URL; everything else is named.
        expected = bs.SITE_URL if name == "index.html" else bs.SITE_URL + name
        assert f"<loc>{expected}</loc>" in xml, f"{name} is not in the sitemap"

    # ⚠ index.html must never appear as a URL of its own. Two spellings of the
    # home page split its ranking between them and make the canonical tag a lie.
    assert f"{bs.SITE_URL}index.html" not in xml
    assert xml.count("<url>") == len(bs.PAGES)


@needs_site
def test_the_sitemap_is_advertised_from_the_domain_root():
    """⚠⚠ The bug this exists for cost the site its first month of indexing.

    A crawler fetches `robots.txt` from the **domain root** and nowhere else.
    This site lives at `gtjevptje.github.io/Macronaut/`, so the `robots.txt`
    published beside the pages was never fetched by anything — and the only
    thing in it that mattered was the `Sitemap:` line. A sitemap is discovered
    through the root robots.txt or through a Search Console account, and there
    is no third way; with neither, nothing ever asked for it. Measured on
    29 August 2026: `site:gtjevptje.github.io/Macronaut` returned **zero**
    results on Bing, a month after launch.

    `site/root/` is published to the user-pages repo to fix that. Nothing about
    the failure is visible from the site itself — every page 200s either way —
    so it is pinned here.
    """
    bs = _build_site_module()
    robots = bs.ROOT_DIR / "robots.txt"
    assert robots.exists(), (
        "site/root/robots.txt is gone — the sitemap is undiscoverable again")
    text = robots.read_text(encoding="utf-8")
    assert f"Sitemap: {bs.SITE_URL}sitemap.xml" in text, (
        "the root robots.txt no longer names the sitemap, which is the only "
        "reason it exists")
    assert "Disallow: /" not in text, "the root robots.txt blocks the crawler"

    # It must actually be published, or the file is a note to nobody.
    src = (Path(__file__).resolve().parent.parent
           / "tools" / "build_site.py").read_text(encoding="utf-8")
    assert "publish_root" in src.split("def publish(", 1)[1], (
        "publish() no longer publishes the root site")


def test_nothing_sells_a_node_type_the_palette_cannot_create():
    """⚠ Variables are implemented, priced, and unreachable. Do not advertise them.

    `flow.N_SETVAR`, `flow.apply_set_var` and the `var` condition kind are all
    live in the engine and all run. But the palette in `main.py` is nine
    buttons and Set Var is not one of them, and
    `flow_dialogs.ConditionWidget.TYPES` offers image / text / pixel / always —
    so a user cannot create a node that sets a variable, nor a condition that
    reads one. The feature exists only for flows written by hand against
    `flow.py`.

    Three user-facing places said otherwise: this module's own docstring, the
    pricing table on the site, and — worst — `licensing_ui`'s upgrade dialog,
    which is the screen where somebody is asked for money. Selling a feature
    nobody can reach is the kind of claim that is checkable by the person who
    paid for it.

    The test is written the general way round: *if* the palette gains Set Var,
    it stops caring, so putting the feature back does not leave a stale
    assertion behind to be deleted in confusion.
    """
    root = Path(__file__).resolve().parent.parent
    main_src = (root / "main.py").read_text(encoding="utf-8")

    # The palette block is the definitive list of what a user can add.
    palette = main_src.split("for icon, label, emit, family in [", 1)
    assert len(palette) == 2, "the palette block moved — this test cannot see it"
    palette = palette[1].split("]", 1)[0]
    set_var_is_creatable = "N_SETVAR" in palette or "set_var" in palette

    if set_var_is_creatable:
        return          # the feature is real; advertising it is fine

    promises = {
        "entitlements.py": (root / "entitlements.py"),
        "licensing_ui.py": (root / "licensing_ui.py"),
    }
    site_tpl = root / "site" / "template.html"
    if site_tpl.is_file():
        promises["site/template.html"] = site_tpl

    def displayable_strings(text):
        """Every string literal that could reach a user, docstrings excluded.

        ⚠ Parsed with `ast`, not grepped, and that is load-bearing. The
        comment and the docstring explaining *why* this word is absent both
        contain the word, so a textual scan finds the explanation and fails on
        it — the same trap `test_flow`'s `monotonic` clock guard documents.
        Comments and docstrings are never shown to anybody; string literals
        can be.
        """
        tree = ast.parse(text)
        docs = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) and body:
                first = body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docs.add(id(first.value))
        out = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and id(node) not in docs
                    and isinstance(node.value, str)
                    and "variable" in node.value.lower()
                    # A label for a node in somebody's old saved flow is not
                    # a sale; `entitlements` still prices the type so that
                    # such a flow is costed correctly.
                    and node.value.strip().lower() != "set variable"):
                out.append(" ".join(node.value.split())[:120])
        return out

    for name, path in promises.items():
        text = path.read_text(encoding="utf-8")
        if name.endswith(".py"):
            found = displayable_strings(text)
        else:
            # The pricing table: only what a visitor reads as a bullet.
            found = [" ".join(li.split()) for li
                     in re.findall(r"<li>(.*?)</li>", text, re.S)
                     if "variable" in li.lower()]
        assert not found, (
            f"{name} offers 'variables' but the palette cannot create a Set "
            "Var node, so nobody can use one:\n    " + "\n    ".join(found))


@needs_site
def test_the_page_says_nothing_rather_than_publishing_a_wrong_checksum(monkeypatch):
    """⚠ A checksum that does not match the download is worse than none.

    The one visitor who bothers to check gets a mismatch, and a mismatch on an
    unsigned binary reads as tampering rather than as a stale web page. So
    every path that cannot establish the *published* digest has to render
    nothing at all — not an empty code block, not the word "unavailable", and
    above all not a hash taken from a local build.

    That last one is the real trap. PyInstaller is not byte-reproducible, so
    `dist/Macronaut.exe` rebuilt from an unchanged tree hashes differently from
    the file people download, and `release.py` rewrites `dist/update.json` on
    every build. Reading the digest from there would be correct until the next
    local build and silently wrong afterwards.
    """
    bs = _build_site_module()

    monkeypatch.setattr(bs, "released_sha256", lambda: ("", ""))
    assert bs._sha256_block() == "", (
        "the page renders a checksum element with no checksum in it")

    digest = "a" * 64
    monkeypatch.setattr(bs, "released_sha256", lambda: ("9.9.9", digest))
    block = bs._sha256_block()
    assert digest in block, "the digest is not in the block that announces it"
    assert "9.9.9" in block, (
        "the block does not say which release the digest belongs to — a hash "
        "for an unnamed version cannot be checked against anything")
    assert "Get-FileHash" in block, (
        "no command to check it with; 'verify the checksum' that a reader "
        "cannot act on is decoration")

    # The template must tolerate the empty string without leaving a label
    # stranded behind it.
    monkeypatch.setattr(bs, "released_sha256", lambda: ("", ""))
    page = (Path(__file__).resolve().parent.parent
            / "site" / "template.html").read_text(encoding="utf-8")
    assert "{{SHA256_BLOCK}}" in page, "the template no longer has the slot"
    before = page.split("{{SHA256_BLOCK}}")[0]
    assert not before.rstrip().endswith(("<p>", "<h2>", ":")), (
        "the slot is preceded by a dangling label that would be left behind "
        "when the block is empty")


@needs_site
def test_the_domain_root_serves_a_sitemap_too():
    """⚠ Search Console resolves a submitted sitemap path against the PROPERTY.

    The ownership file is published to both the domain root and the
    `/Macronaut/` prefix on purpose (see the test below), which means either
    can be the verified property. In a root property, submitting "sitemap.xml"
    means `https://gtjevptje.github.io/sitemap.xml` — and that was a 404, while
    the real sitemap sat one directory down. Google reports that as "Sitemap
    could not be read", which reads like a problem with the XML and sends you
    to validate a file that was correct all along. It happened on
    3 September 2026.

    An index rather than a second copy of the URLs: two sitemaps listing the
    same pages is a thing to keep in sync, and an index cannot drift because it
    names no page at all.
    """
    bs = _build_site_module()
    xml = bs.sitemap_index()

    assert "<sitemapindex" in xml, "the root sitemap is not an index"
    assert f"<loc>{bs.SITE_URL}sitemap.xml</loc>" in xml, (
        "the root sitemap does not point at the real one")
    # It must list no pages of its own — that is the whole point of an index.
    assert "<url>" not in xml

    src = (Path(__file__).resolve().parent.parent
           / "tools" / "build_site.py").read_text(encoding="utf-8")
    root_fn = src.split("def publish_root(", 1)[1].split("\ndef ", 1)[0]
    assert "sitemap_index()" in root_fn, (
        "publish_root no longer writes a sitemap to the domain root, so a root "
        "Search Console property cannot find one")


@needs_site
def test_ownership_files_are_published_to_both_locations():
    """⚠ Google re-checks its verification file and SILENTLY unverifies the
    property when it stops resolving — taking the Search Console data with it,
    which is the only measurement this project has of whether the site reaches
    anybody (GROWTH.md §2a). Nothing about that failure is visible from here.

    Both locations, deliberately: Google fetches the file from the property's
    own prefix, so a property registered as `…/Macronaut/` needs it at that
    path and one registered as the bare domain needs it at the root. Which was
    registered is a choice made in a browser and is not recoverable from this
    repo, so both get it.
    """
    bs = _build_site_module()
    files = bs._verify_files()
    if not files:
        pytest.skip("no ownership files staged in site/verify/")

    src = (Path(__file__).resolve().parent.parent
           / "tools" / "build_site.py").read_text(encoding="utf-8")
    root_fn = src.split("def publish_root(", 1)[1].split("\ndef ", 1)[0]
    site_fn = src.split("\ndef publish(", 1)[1].split("\ndef ", 1)[0]
    assert "_verify_files()" in root_fn, (
        "publish_root no longer copies the ownership files — the domain-root "
        "property will unverify")
    assert "_verify_files()" in site_fn, (
        "publish no longer copies the ownership files — the /Macronaut/ "
        "property will unverify")
    # ⚠ Copied into the clone but never `git add`ed looks exactly like a
    # successful publish, and is the failure this second assertion exists for.
    added = site_fn.split('"git", "add"', 1)[1].split("cwd=work", 1)[0]
    assert "_verify_files()" in added, (
        "the ownership files are copied but not staged, so they are never "
        "committed")


@needs_site
def test_every_page_is_reachable_from_another_page():
    """A page nothing links to is a page search engines discount and visitors
    never find. The sitemap gets a crawler there; an internal link is what
    makes it worth ranking."""
    bs = _build_site_module()
    site = Path(__file__).resolve().parent.parent / "site"
    names = [name for _src, name, _p, _f in bs.PAGES]
    built = {n: (site / n) for n in names}
    if not all(p.exists() for p in built.values()):
        pytest.skip("site not fully built in this checkout")

    for name in names:
        if name == "index.html":
            continue  # reached as the bare directory URL, from every page
        linked_from = [other for other in names
                       if other != name
                       and f'{name}"' in built[other].read_text(encoding="utf-8")]
        assert linked_from, f"{name} is an orphan — nothing links to it"


def test_a_bad_key_leaves_the_activation_dialog_open(qapp):
    """They pasted half of it. Closing the dialog makes them find it again."""
    import licensing_ui
    dlg = licensing_ui.ActivateDialog()
    try:
        dlg._field.setPlainText("MN1-NOTAREALKEY")
        dlg._activate()
        assert dlg.isVisible() or dlg.result() == 0
        assert dlg._status.text(), "refused with no message"
    finally:
        dlg.hide()


# ── The PRO chip on the canvas ────────────────────────────────────────────────

def _render(item, w=200, h=100):
    """Paint a QGraphicsItem into an image and hand back the raw bytes.

    Rendering, not inspecting attributes: a badge that is computed correctly and
    painted under something else, or off the edge, or in the background colour,
    passes every assertion about state. This project has already shipped a
    half-dark header band and an invisible text field that way.
    """
    from PySide6.QtGui import QImage, QPainter
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    item.paint(p, None, None)
    p.end()
    return img.constBits().tobytes()


def _node_item(spec):
    import flow_canvas
    g = _graph(spec)
    node = [n for n in g.nodes.values() if n.type != flow.N_START][0]
    return flow_canvas.NodeItem(node)


@pytest.mark.parametrize("spec", ["wait_image", flow.N_IF, flow.N_LOOP])
def test_a_pro_node_looks_different_when_unlicensed(qapp, spec, monkeypatch):
    """The chip is actually painted. Compare the same node drawn under both
    licence states — if they are byte-identical, nothing was drawn."""
    free = _render(_node_item(spec))
    monkeypatch.setattr(licensing, "_cached",
                        licensing.License(tier=licensing.APP_TIER_PRO))
    licensed = _render(_node_item(spec))
    assert free != licensed, f"{spec} draws no PRO chip on a free copy"


@pytest.mark.parametrize("spec", ["click", "text", "wait"])
def test_a_free_node_looks_the_same_either_way(qapp, spec, monkeypatch):
    """⚠ The other half, and the one that would go unnoticed: a chip on a free
    step is a lie about what the flow needs, and would send someone to a
    checkout for something they already have."""
    free = _render(_node_item(spec))
    monkeypatch.setattr(licensing, "_cached",
                        licensing.License(tier=licensing.APP_TIER_PRO))
    assert free == _render(_node_item(spec)), f"{spec} changes with the licence"


def test_the_chip_is_gone_once_licensed(licensed):
    import flow_canvas          # noqa: F401  (import order: needs a QApplication)
    g = _graph("wait_image", flow.N_IF)
    for node in g.nodes.values():
        assert entitlements.show_pro_badge(node) is False


# ── The palette ───────────────────────────────────────────────────────────────

def test_every_pro_feature_on_the_palette_is_marked_as_one(tab):
    """⚠ The test that matters here is not "Detect says Pro" — it is that
    *nothing* on the palette is a paid feature without saying so. A new palette
    button for a new gated node type would otherwise ship silently, and the
    first sign of it would be a user refused at Play with no warning."""
    import main as main_mod
    marked, gated = [], []
    for b in tab._palette_btns:
        emit = b._ntype
        if main_mod._palette_entry_is_pro(emit):
            gated.append(emit)
            if "Pro" in b.toolTip():
                marked.append(emit)
    assert gated, "no Pro features on the palette at all — has the policy moved?"
    assert set(marked) == set(gated), f"unmarked: {set(gated) - set(marked)}"


def test_free_palette_buttons_do_not_mention_pro(tab):
    import main as main_mod
    for b in tab._palette_btns:
        if not main_mod._palette_entry_is_pro(b._ntype):
            assert "Pro" not in b.toolTip(), b.text()


def test_palette_labels_are_untouched_by_the_licence(tab):
    """⚠ The label feeds `_label_width`, and the palette's sizing has caused
    four separate clipped-label bugs. The Pro marking lives in the tooltip
    precisely so that it can never take a letter off a button."""
    before = [b.text() for b in tab._palette_btns]
    tab.refresh_licence_state()
    assert [b.text() for b in tab._palette_btns] == before


def test_refreshing_twice_does_not_stack_the_tooltip(tab):
    """`refresh_licence_state` rebuilds tooltips by splitting off the suffix;
    a sloppy version appends instead and the tip grows every time."""
    tab.refresh_licence_state()
    tab.refresh_licence_state()
    for b in tab._palette_btns:
        assert b.toolTip().count("Macronaut Pro") <= 1, b.text()


@needs_site
def test_every_page_declares_a_favicon_that_is_actually_published():
    """⚠ Another silent one, and it went unnoticed for a month.

    The site shipped with no favicon at all. Every page rendered correctly,
    every link worked, and the browser tab showed a blank sheet — there is no
    error, no console warning and no broken image, so nothing surfaces it. It
    is not cosmetic either: a blank tab icon is one of the few things a
    stranger reads as "abandoned" before reading a word, on a site whose job
    is convincing that stranger to run an .exe.

    Two halves, and each is useless without the other: the tag has to be on
    every page (hand-copied <link> tags are how the fifth page ends up
    without one), and the file it points at has to be in `site/icons/`, which
    is what `publish` copies and stages.
    """
    bs = _build_site_module()
    site = Path(__file__).resolve().parent.parent / "site"

    published = {f.name for f in bs._icon_files()}
    assert published, "site/icons/ is empty — no page can have a tab icon"

    for _src, name, _prio, _freq in bs.PAGES:
        page = site / name
        if not page.exists():          # not built in this checkout
            continue
        html = page.read_text(encoding="utf-8")
        hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*'
                           r'href="([^"]+)"', html)
        assert hrefs, f"{name} declares no icon at all"
        for href in hrefs:
            assert href.startswith(bs.SITE_URL), (
                f"{name}: icon {href!r} is not absolute — it resolves against "
                f"the page, and these pages are served from two prefixes")
            assert href[len(bs.SITE_URL):] in published, (
                f"{name}: points at {href!r}, which is not in site/icons/ and "
                f"so is never published — a 404 renders as no icon at all")
