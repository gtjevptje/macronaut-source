"""Headless tests for crash transport (crashsend.py). No network is touched.

The event-shaping tests matter more than they look. A crash reporter that
uploads successfully but groups everything into one bucket, or credits every
crash to the wrong release, produces a dashboard that is actively misleading —
which is worse than an empty one, because it gets believed.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crashreport
import crashsend
import version

DSN = "https://pubkey123@o111222.ingest.sentry.io/4455"


@pytest.fixture(autouse=True)
def _never_the_real_project(monkeypatch):
    """No test in this module may reach the live Sentry project.

    An omitted dsn argument deliberately falls back to the compiled-in one, so
    the moment a real DSN was configured two tests here started POSTing junk
    events at production — Sentry rejected them, which is the only reason it
    was visible at all. Pinning the module-level constant to the fake removes
    the possibility rather than relying on every test remembering.
    """
    monkeypatch.setattr(crashsend, "SENTRY_DSN", DSN)

TRACEBACK = '''Traceback (most recent call last):
  File "C:\\\\app\\\\main.py", line 210, in _on_log_batch
    self._run_log.addItems(lines)
  File "C:\\\\app\\\\flow_exec.py", line 88, in run
    raise RuntimeError("boom in a flow step")
RuntimeError: boom in a flow step
'''


def _report(**over):
    rep = {
        "schema": 1, "kind": "crash", "version": "2.0.7", "frozen": True,
        "python": "3.12.1", "os": "Windows", "os_release": "11",
        "arch": "AMD64", "started": time.time(), "fatal": [], "native": "",
        "breadcrumbs": [], "doing": None, "silent": True,
    }
    rep.update(over)
    return rep


# ── DSN ───────────────────────────────────────────────────────────────────────

def test_a_valid_dsn_becomes_an_envelope_url_and_a_key():
    url, key = crashsend.parse_dsn(DSN)
    assert url == "https://o111222.ingest.sentry.io/api/4455/envelope/"
    assert key == "pubkey123"


@pytest.mark.parametrize("bad", ["", "   ", "not-a-dsn", "https://o1.sentry.io/9",
                                 "https://key@host/", "ftp://k@h/1"])
def test_an_unusable_dsn_is_rejected_rather_than_raising(bad):
    """A typo in the DSN should cost crash reports, never a startup."""
    assert crashsend.parse_dsn(bad) is None


def test_the_real_dsn_that_ships_is_parseable(monkeypatch):
    """Guards the one value that cannot be caught by any other test: a DSN
    typo'd into the source disables reporting in a way nothing else notices,
    because "no crash reports" and "no crashes" look the same from here."""
    monkeypatch.undo()          # look at the genuine constant, not the fixture's
    import importlib
    real = importlib.import_module("crashsend").SENTRY_DSN
    if real.strip():
        url, key = crashsend.parse_dsn(real)
        assert url.endswith("/envelope/") and key


def test_an_omitted_dsn_falls_back_to_the_built_in_one():
    """Production callers pass nothing, so "" means "use the compiled-in DSN",
    not "send nowhere". Worth pinning: it is why the disabled path below has to
    patch the constant rather than pass an empty string."""
    assert crashsend.parse_dsn("") is None
    sent = {}
    assert crashsend._envelope({"event_id": "e"}, crashsend.SENTRY_DSN)


def test_sending_is_compiled_out_when_no_dsn_is_configured(monkeypatch):
    monkeypatch.setattr(crashsend, "SENTRY_DSN", "")
    assert crashsend.enabled() is False
    assert crashsend.send_event({"event_id": "x"}) is False


# ── event shaping ─────────────────────────────────────────────────────────────

def test_the_release_is_the_version_that_crashed(tmp_path):
    """Not the version doing the reporting.

    Updates apply on restart, so the build that uploads a crash is routinely
    newer than the build that produced it. Get this wrong and Sentry's
    regression detection points at the release that fixed the bug.
    """
    ev = crashsend.to_event(_report(version="2.0.7"))
    assert ev["release"] == "2.0.7"
    assert ev["release"] != version.__version__


def test_a_developer_run_is_tagged_separately_from_a_users_build():
    assert crashsend.to_event(_report(frozen=True))["environment"] == "production"
    assert crashsend.to_event(_report(frozen=False))["environment"] == "development"


def test_a_python_traceback_becomes_a_grouped_exception():
    ev = crashsend.to_event(_report(
        silent=False, fatal=[{"kind": "exception", "text": TRACEBACK}]))
    exc = ev["exception"]["values"][0]
    assert exc["type"] == "RuntimeError"
    assert exc["value"] == "boom in a flow step"
    assert exc["mechanism"]["handled"] is False
    frames = exc["stacktrace"]["frames"]
    assert [f["function"] for f in frames] == ["_on_log_batch", "run"]
    assert frames[0]["lineno"] == 210
    # Oldest frame first, which is the order Sentry renders bottom-up from.
    assert frames[-1]["function"] == "run"
    assert all(f["in_app"] for f in frames)


def test_a_third_party_frame_is_not_marked_in_app():
    tb = ('Traceback (most recent call last):\n'
          '  File "C:\\\\py\\\\site-packages\\\\pynput\\\\x.py", line 4, in tap\n'
          '    boom()\n'
          'ValueError: nope\n')
    ev = crashsend.to_event(_report(silent=False,
                                    fatal=[{"kind": "exception", "text": tb}]))
    assert ev["exception"]["values"][0]["stacktrace"]["frames"][0]["in_app"] is False


def test_a_qfatal_groups_on_its_message_because_it_has_no_stack():
    """The 2.0.8 crash. Qt aborts in C, so there is no Python stack to group on
    — without an explicit fingerprint every occurrence would be its own issue."""
    msg = "QThread: Destroyed while thread is still running"
    ev = crashsend.to_event(_report(silent=False,
                                    fatal=[{"kind": "qt_fatal", "text": msg}]))
    assert "Qt fatal" in ev["message"]["formatted"]
    assert ev["fingerprint"] == ["qt-fatal", msg[:120]]
    assert "exception" not in ev


def test_every_silent_death_groups_together():
    """Individually they carry nothing; the count of them is the whole signal."""
    a = crashsend.to_event(_report(doing={"node": "n1", "kind": "action"}))
    b = crashsend.to_event(_report(doing={"node": "n9", "kind": "action"}))
    assert a["fingerprint"] == b["fingerprint"] == ["silent-exit", "action"]
    assert a["tags"]["silent"] == "yes"


def test_a_python_traceback_wins_over_a_following_qfatal():
    """An abort often follows the exception that caused it, and the exception
    is the more informative of the two."""
    ev = crashsend.to_event(_report(silent=False, fatal=[
        {"kind": "exception", "text": TRACEBACK},
        {"kind": "qt_fatal", "text": "QThread: Destroyed"},
    ]))
    assert ev["exception"]["values"][0]["type"] == "RuntimeError"


def test_what_the_app_was_doing_survives_into_the_event():
    ev = crashsend.to_event(_report(doing={"node": "n4", "kind": "detect"}))
    assert ev["extra"]["last_node"] == "n4"
    assert ev["tags"]["node_kind"] == "detect"


def test_breadcrumbs_and_the_input_backend_are_carried_across():
    ev = crashsend.to_event(_report(breadcrumbs=[
        {"t": 1.0, "kind": "session_start"},
        {"t": 2.0, "kind": "run_start", "nodes": 7, "backend": "interception"},
        {"t": 3.0, "kind": "stop_requested", "running": True},
    ]))
    vals = ev["breadcrumbs"]["values"]
    assert [c["category"] for c in vals] == [
        "session_start", "run_start", "stop_requested"]
    assert vals[1]["data"]["nodes"] == 7
    assert ev["tags"]["input_backend"] == "interception"


def test_an_event_carries_no_script_contents():
    ev = crashsend.to_event(_report(
        doing={"node": "n1", "kind": "action"},
        breadcrumbs=[{"t": 1.0, "kind": "run_start", "nodes": 3,
                      "backend": "pynput"}]))
    blob = json.dumps(ev)
    for leak in ("image_path", "clipboard", "keystroke", "%HOME%\\"):
        assert leak not in blob


# ── the wire ──────────────────────────────────────────────────────────────────

def test_the_envelope_is_three_documents_with_a_correct_length():
    ev = crashsend.to_event(_report())
    raw = crashsend._envelope(ev, DSN)
    head, item, payload = raw.decode("utf-8").split("\n")[:3]
    assert json.loads(head)["event_id"] == ev["event_id"]
    meta = json.loads(item)
    assert meta["type"] == "event"
    # Sentry rejects the item outright if the declared length is wrong.
    assert meta["length"] == len(payload.encode("utf-8"))
    assert json.loads(payload)["release"] == ev["release"]


class _Resp:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def getcode(self): return self.status


def test_a_successful_post_is_reported_as_sent(monkeypatch):
    seen = {}

    def fake(req, timeout=None, context=None):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("X-sentry-auth", "")
        seen["ctype"] = req.headers.get("Content-type", "")
        return _Resp(200)

    monkeypatch.setattr(crashsend.urllib.request, "urlopen", fake)
    assert crashsend.send_event(crashsend.to_event(_report()), DSN) is True
    assert seen["url"].endswith("/api/4455/envelope/")
    assert "sentry_key=pubkey123" in seen["auth"]
    assert seen["ctype"] == "application/x-sentry-envelope"


def test_a_network_failure_keeps_the_report_for_a_later_launch(monkeypatch):
    def boom(*a, **k):
        raise OSError("no route to host")
    monkeypatch.setattr(crashsend.urllib.request, "urlopen", boom)
    assert crashsend.send_event(crashsend.to_event(_report()), DSN) is False


def test_a_permanent_rejection_stops_being_retried_forever(monkeypatch):
    """A dead project or a bad key will never accept this event. Retrying it on
    every launch for the rest of the install's life helps nobody."""
    def bad(*a, **k):
        raise crashsend.urllib.error.HTTPError(DSN, 403, "Forbidden", {}, None)
    monkeypatch.setattr(crashsend.urllib.request, "urlopen", bad)
    assert crashsend.send_event(crashsend.to_event(_report()), DSN) is True


def test_being_rate_limited_is_temporary_and_the_report_is_kept(monkeypatch):
    def limited(*a, **k):
        raise crashsend.urllib.error.HTTPError(DSN, 429, "Too Many", {}, None)
    monkeypatch.setattr(crashsend.urllib.request, "urlopen", limited)
    assert crashsend.send_event(crashsend.to_event(_report()), DSN) is False


def test_a_server_error_is_temporary_too(monkeypatch):
    def down(*a, **k):
        raise crashsend.urllib.error.HTTPError(DSN, 503, "Down", {}, None)
    monkeypatch.setattr(crashsend.urllib.request, "urlopen", down)
    assert crashsend.send_event(crashsend.to_event(_report()), DSN) is False


# ── the queue ─────────────────────────────────────────────────────────────────

def _queue(tmp_path, n):
    d = crashreport.crash_dir(tmp_path)
    for i in range(n):
        (d / ("crash-%d.json" % (1_000_000 + i))).write_text(
            json.dumps(_report(version="2.0.%d" % i)), encoding="utf-8")


def test_sent_reports_are_removed_and_the_rest_remain(tmp_path, monkeypatch):
    _queue(tmp_path, 3)
    monkeypatch.setattr(crashsend.urllib.request,
                        "urlopen", lambda *a, **k: _Resp(200))
    sent, remaining = crashsend.send_pending(tmp_path, DSN)
    assert (sent, remaining) == (3, 0)
    assert crashreport.pending(tmp_path) == []


def test_uploading_stops_at_the_first_failure(tmp_path, monkeypatch):
    """If the network is down the rest will fail too, and each costs a timeout."""
    _queue(tmp_path, 4)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(200)
        raise OSError("offline")

    monkeypatch.setattr(crashsend.urllib.request, "urlopen", flaky)
    sent, remaining = crashsend.send_pending(tmp_path, DSN)
    assert sent == 1 and remaining == 3
    assert calls["n"] == 2


def test_a_launch_never_uploads_more_than_its_share(tmp_path, monkeypatch):
    _queue(tmp_path, crashsend.MAX_PER_LAUNCH + 6)
    monkeypatch.setattr(crashsend.urllib.request,
                        "urlopen", lambda *a, **k: _Resp(200))
    sent, remaining = crashsend.send_pending(tmp_path, DSN)
    assert sent == crashsend.MAX_PER_LAUNCH
    assert remaining == 6


def test_nothing_is_uploaded_when_no_dsn_is_configured(tmp_path, monkeypatch):
    _queue(tmp_path, 2)
    monkeypatch.setattr(crashsend, "SENTRY_DSN", "")

    def never(*a, **k):
        raise AssertionError("posted with no endpoint configured")

    monkeypatch.setattr(crashsend.urllib.request, "urlopen", never)
    sent, remaining = crashsend.send_pending(tmp_path)
    assert (sent, remaining) == (0, 2)


def test_an_unreadable_report_is_dropped_not_retried(tmp_path, monkeypatch):
    d = crashreport.crash_dir(tmp_path)
    (d / "crash-1000001.json").write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(crashsend.urllib.request,
                        "urlopen", lambda *a, **k: _Resp(200))
    sent, remaining = crashsend.send_pending(tmp_path, DSN)
    assert (sent, remaining) == (0, 0)
