"""Licence keys: that a real one works, and that nothing else does.

The second half is the one that matters. A licence check has an asymmetric
failure mode — if it wrongly *rejects*, a paying customer complains within the
hour; if it wrongly *accepts*, nobody ever tells you, and the revenue simply
does not arrive. So most of this file is forgeries.
"""
import json
import secrets
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import ed25519
import licensing

# ⚠ `tools/mint_license.py` is the SIGNING half of the licence scheme, and it is
# deliberately absent from the public repository -- it is a developer tool that
# never ships inside the app, and publishing it would put the whole minting
# procedure next to the verifier for no benefit to anyone building Macronaut.
#
# Nearly every test below needs it: the `seed` fixture mints the keys that the
# forgery tests then try to break. So on a public checkout this module skips
# whole rather than failing to import, which would be a collection error naming
# innocent files -- exactly the shape of the `pytest.ini` trap this project
# already documents.
#
# ⚠ The cost is real and worth stating: a contributor therefore has NO coverage
# of `licensing.py`. The hand-rolled crypto underneath it is still covered, by
# `tests/test_ed25519.py`, which runs the official RFC 8032 vectors and needs
# nothing private.
mint_license = pytest.importorskip(
    "mint_license",
    reason="tools/mint_license.py is the private signing tool and is not in "
           "this checkout; licensing tests need it to mint keys to verify")


@pytest.fixture
def seed():
    """The real signing key if it is on this machine, otherwise a fresh one.

    Deliberately not *always* the real key: the suite has to pass on a clean
    checkout, on CI, and on a second machine — none of which have
    `~/.macronaut-dev/signing-key.json`, and none of which should need it.
    """
    try:
        return mint_license.load_seed()
    except SystemExit:
        return secrets.token_bytes(32)


@pytest.fixture
def pub(seed):
    return mint_license.public_key(seed).hex()


@pytest.fixture
def key(seed):
    return mint_license.issue("buyer@example.com", "GR-1234", seed=seed)


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Point `settings.data_dir()` at a temp folder and clear the cache.

    ⚠ Without the `refresh()` either side, a test that activates a licence
    leaves the module-level cache set to Pro and every later test in the
    session silently runs as a licensed copy — which is precisely the state
    that would make a broken gate look like a working one.
    """
    import settings
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)
    licensing.refresh()
    yield tmp_path
    licensing.refresh()


# ── The happy path ────────────────────────────────────────────────────────────

def test_a_minted_key_parses_back_to_what_was_minted(key, pub):
    lic = licensing.parse_key(key, pub)
    assert lic is not None
    assert lic.is_pro
    assert lic.email == "buyer@example.com"
    assert lic.order_id == "GR-1234"
    assert lic.issued == date.today()


def test_the_shipped_public_key_matches_the_signing_key():
    """`mint` warns about this, but only when someone is watching it run.

    Skipped where the private key is absent, since off the developer's machine
    there is nothing to compare against.
    """
    try:
        seed = mint_license.load_seed()
    except SystemExit:
        pytest.skip("no signing key on this machine")
    assert mint_license.public_key(seed).hex() == licensing.PUBLIC_KEY_HEX


def test_a_key_survives_however_it_was_pasted(key, pub):
    """It arrives out of an e-mail client, a chat window, or retyped. Every one
    of these was a support ticket waiting to happen."""
    for mangled in (
        key.lower(),
        key.replace("-", ""),
        key.replace("-", " "),
        f"  {key}  ",
        key[:40] + "\n" + key[40:],          # wrapped by a mail client
        f"Your key:\n{key}\n",               # pasted with its label
    ):
        assert licensing.parse_key(mangled, pub) is not None, mangled[:30]


def test_unicode_in_the_buyers_name_round_trips(seed, pub):
    k = mint_license.issue("gerben.van.poucke+café@example.be", "ø-99", seed=seed)
    lic = licensing.parse_key(k, pub)
    assert lic.email == "gerben.van.poucke+café@example.be"
    assert lic.order_id == "ø-99"


# ── Forgeries ─────────────────────────────────────────────────────────────────

def test_a_key_from_a_different_signing_key_is_rejected(pub):
    """THE test. Anyone can run the minting tool; only one keypair counts."""
    attacker = secrets.token_bytes(32)
    forged = mint_license.issue("thief@example.com", "none", seed=attacker)
    assert licensing.parse_key(forged, pub) is None


def test_editing_the_email_invalidates_the_key(seed, pub):
    """The payload is human-readable inside the base32, so someone will try."""
    payload = licensing.encode_payload("pro", "buyer@example.com", "GR-1")
    sig = mint_license.sign(payload, seed)
    tampered = licensing.encode_payload("pro", "thief@example.com", "GR-1")
    assert len(tampered) == len(payload)     # same length: nothing else changed
    assert licensing.parse_key(licensing.format_key(tampered + sig), pub) is None


def test_every_single_byte_is_covered_by_the_signature(seed, pub):
    """Flip each bit position of each byte in turn. A gap here would be a field
    an attacker could edit freely — the tier byte being the obvious prize."""
    payload = licensing.encode_payload("pro", "b@e.com", "1")
    raw = bytearray(payload + mint_license.sign(payload, seed))
    assert licensing.parse_key(licensing.format_key(bytes(raw)), pub) is not None
    for i in range(len(raw)):
        raw[i] ^= 0x80
        assert licensing.parse_key(licensing.format_key(bytes(raw)), pub) is None, i
        raw[i] ^= 0x80


def test_rubbish_returns_none_rather_than_raising():
    """Someone will paste their order confirmation, a URL, or nothing at all,
    into a dialog that must stay standing."""
    for junk in ("", "   ", None, "hello", "MN1", "MN1-", "MN1-AAAA",
                 "MN2-AEAQB3YM-IZHVKTSE", "MN1-!!!!!!!!", "MN1-" + "A" * 400,
                 "\x00\x01\x02", "MN1-AAAAAAAA-11111111"):
        assert licensing.parse_key(junk) is None


def test_a_truncated_key_is_rejected(key, pub):
    for cut in (10, 40, 100, len(key) - 1):
        assert licensing.parse_key(key[:cut], pub) is None


def test_a_payload_with_no_signature_at_all_is_rejected(pub):
    payload = licensing.encode_payload("pro", "b@e.com", "1")
    assert licensing.parse_key(licensing.format_key(payload), pub) is None
    assert licensing.parse_key(licensing.format_key(payload + b"\x00" * 64), pub) is None


def test_an_unknown_tier_byte_is_rejected(seed, pub):
    """A future tier must not silently read as Pro on an older build."""
    payload = bytearray(licensing.encode_payload("pro", "b@e.com", "1"))
    payload[1] = 0x7F
    signed = bytes(payload) + mint_license.sign(bytes(payload), seed)
    assert licensing.parse_key(licensing.format_key(signed), pub) is None


def test_a_declared_field_length_past_the_end_is_rejected(seed, pub):
    """The length prefixes are attacker-supplied; a decoder that trusted one
    would read past the buffer or raise into the caller."""
    payload = bytearray(licensing.encode_payload("pro", "b@e.com", "1"))
    payload[4] = 0xFF                        # order_id claims 255 bytes
    signed = bytes(payload) + mint_license.sign(bytes(payload), seed)
    assert licensing.parse_key(licensing.format_key(signed), pub) is None


def test_an_appended_tail_still_verifies(seed, pub):
    """Forward compatibility, exercised rather than assumed: a key minted by a
    future version with extra fields must still unlock Pro on today's build."""
    payload = licensing.encode_payload("pro", "b@e.com", "1") + b"\x09future"
    signed = payload + mint_license.sign(payload, seed)
    lic = licensing.parse_key(licensing.format_key(signed), pub)
    assert lic is not None and lic.is_pro and lic.email == "b@e.com"


# ── Storage ───────────────────────────────────────────────────────────────────

def test_activate_persists_and_survives_a_restart(isolated_data_dir, key, pub,
                                                 monkeypatch):
    # ⚠ `pub`, not a conditional on whether the real signing key is present.
    # This used to swap in the real public key only when ~/.macronaut-dev held
    # the seed -- which is the one case where the shipped constant already
    # matches. Everywhere else (CI, a clean checkout, a second machine) `key`
    # is signed by the fixture's random seed and left the production constant
    # in place, so activation could not verify and this failed. `pub` is
    # derived from whatever seed `key` was actually signed with, which is what
    # the fixture exists for.
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    assert licensing.is_pro() is False
    ok, message = licensing.activate(key)
    assert ok, message
    assert licensing.is_pro() is True
    licensing.refresh()                      # the next launch re-reads from disk
    assert licensing.is_pro() is True
    assert licensing.current().email == "buyer@example.com"


def test_deactivate_returns_this_copy_to_free(isolated_data_dir, key):
    licensing.activate(key)
    assert licensing.deactivate() is True
    assert licensing.is_pro() is False
    assert not (isolated_data_dir / "license.json").exists()


def test_a_bad_key_is_not_written_to_disk(isolated_data_dir):
    ok, message = licensing.activate("MN1-NONSENSE")
    assert ok is False
    assert "MN1-" in message                 # tells them what a key looks like
    assert not (isolated_data_dir / "license.json").exists()


@pytest.mark.parametrize("content", [
    "", "{", "null", "[]", '{"key": null}', '{"key": 12}', '{"other": "x"}',
    '{"key": "MN1-AAAAAAAA"}',
])
def test_a_corrupt_license_file_is_the_free_tier_not_a_crash(
        isolated_data_dir, content):
    """⚠ This file is read during startup. Anything that raises here does not
    downgrade someone to Free, it stops Macronaut from opening at all."""
    (isolated_data_dir / "license.json").write_text(content, encoding="utf-8")
    licensing.refresh()
    assert licensing.is_pro() is False


def test_an_unreadable_license_file_is_the_free_tier(isolated_data_dir, monkeypatch):
    """A locked or permission-denied file — the same requirement as above, by a
    route that no amount of valid JSON covers."""
    def boom(*_a, **_k):
        raise PermissionError("locked by another process")
    monkeypatch.setattr("builtins.open", boom)
    licensing.refresh()
    assert licensing.is_pro() is False


def test_the_stored_key_is_the_canonical_form(isolated_data_dir, key, pub,
                                             monkeypatch):
    """However it was pasted, what lands on disk is the tidy version — so a
    support request that asks the customer to open the file gets one back."""
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    ok, message = licensing.activate(key.lower().replace("-", ""))
    assert ok, message                       # otherwise the failure below is a
                                             # missing file, which reads as an
                                             # unrelated bug
    stored = json.loads((isolated_data_dir / "license.json").read_text())
    assert stored["key"] == key
    assert stored["activated"] == date.today().isoformat()


# ── The scheme's own promises ─────────────────────────────────────────────────

def test_nothing_in_the_shipped_app_can_sign():
    """The app must hold no private key and no way to use one. If `licensing`
    or `ed25519` ever grows a signing function, the scheme is decorative —
    anyone with a copy of the .exe could mint their own keys.

    ⚠ Parsed with `ast`, never grepped, for the reason this codebase already
    learned once with the `monotonic` clock guard: both modules *discuss*
    secrets and signing at length in their docstrings, precisely in order to
    explain why they contain neither. A text search fails on the explanation.
    """
    import ast
    import inspect

    for module in (licensing, ed25519):
        tree = ast.parse(inspect.getsource(module))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not {n for n in names if "sign" in n and "signature" not in n}, module
        # A private seed would have to be stored somewhere to be used.
        assigned = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        assert not {a for a in assigned
                    if "SEED" in a.upper() or "PRIVATE" in a.upper()}, module
        # And nothing may import the minting tool, which does hold one.
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                    for a in n.names}
        imported |= {n.module for n in ast.walk(tree)
                     if isinstance(n, ast.ImportFrom) and n.module}
        assert "mint_license" not in imported, module


def test_verification_is_fast_enough_to_call_on_startup(key, pub):
    """Pure-Python scalar multiplication is the one performance risk here, and
    it runs before the window appears."""
    import time
    t0 = time.perf_counter()
    for _ in range(5):
        licensing.parse_key(key, pub)
    per_call_ms = (time.perf_counter() - t0) / 5 * 1000
    assert per_call_ms < 150, f"{per_call_ms:.0f} ms per verification"


# ── Fulfilment ────────────────────────────────────────────────────────────────

@pytest.fixture
def dev_dir(tmp_path, monkeypatch):
    """Redirect the signing key and the ledger to a temp folder.

    ⚠ Not optional. These tests mint keys and write ledger rows; against the
    real `~/.macronaut-dev/` they would file imaginary customers alongside real
    ones, and `--resend` would later hand one of them a key.
    """
    monkeypatch.setattr(mint_license, "KEY_DIR", tmp_path)
    monkeypatch.setattr(mint_license, "KEY_FILE", tmp_path / "signing-key.json")
    monkeypatch.setattr(mint_license, "LEDGER_FILE", tmp_path / "issued-keys.jsonl")
    mint_license.cmd_keygen(type("A", (), {"force": True})())
    return tmp_path


def _fulfil_or_skip():
    """Import `tools/fulfil.py`, or skip — it is not in the public repository.

    `fulfil` turns a paid order into a licence key and the e-mail that delivers
    it, which is business operations rather than part of the program, so
    `publish_source.py` holds it back.

    ⚠ Today this is belt and braces: the module-level `importorskip` on
    `mint_license` already skips this whole file on a public checkout, and
    `fulfil` imports `mint_license` anyway. It is here so that the three tests
    below fail *gracefully* rather than with a ModuleNotFoundError if the
    signing tool is ever published again while `fulfil` is not — which is
    exactly the pairing CI caught once, when a bare `import fulfil` turned
    three tests red on a clean runner.
    """
    return pytest.importorskip(
        "fulfil",
        reason="tools/fulfil.py is private and not in this checkout")


def test_a_key_handed_to_a_person_is_always_recorded(dev_dir, monkeypatch):
    """The bug this pins: `fulfil` minted keys without writing the ledger, so
    its own `--resend` could never find one. A customer who loses their key six
    months later is then unrecoverable — the store holds the order, but nothing
    anywhere holds the key."""
    fulfil = _fulfil_or_skip()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX",
                        mint_license.public_key(mint_license.load_seed()).hex())
    licensing.refresh()

    key = fulfil.fulfil("buyer@example.com", "ORD-1")
    assert fulfil._existing("buyer@example.com")["key"] == key


def test_resending_gives_back_the_same_key(dev_dir, monkeypatch):
    """Two keys for one customer makes "which one did I send you?"
    unanswerable, which is the real cost of a support request."""
    fulfil = _fulfil_or_skip()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX",
                        mint_license.public_key(mint_license.load_seed()).hex())
    licensing.refresh()

    first = fulfil.fulfil("buyer@example.com", "ORD-1")
    again = fulfil.fulfil("BUYER@example.com", "ORD-2")   # they retyped the case
    assert again == first
    assert len(fulfil._ledger()) == 1


def test_fulfilment_refuses_to_hand_out_a_key_the_app_would_reject(
        dev_dir, monkeypatch):
    """⚠ The failure this catches is silent and total: if the shipped
    PUBLIC_KEY_HEX ever stops matching the signing key, every key minted is
    dead on arrival and the *customer* is the one who finds out."""
    fulfil = _fulfil_or_skip()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", "aa" * 32)
    licensing.refresh()
    with pytest.raises(SystemExit):
        fulfil.fulfil("buyer@example.com", "ORD-1")


def test_keygen_refuses_to_overwrite_an_existing_signing_key(dev_dir):
    """Regenerating orphans every licence already sold, with no way to reach
    the people holding them. It has to be an explicit --force."""
    assert mint_license.cmd_keygen(type("A", (), {"force": False})()) == 1
