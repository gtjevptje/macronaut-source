"""The click interval has to be the interval the user asked for.

⚠ **The bug these exist for.** `clicker._sleep` timed its deadline with
`time.monotonic()`, which on Windows is GetTickCount64 at **15.625 ms**
resolution, so every wait quantised up to the next tick. `time.sleep` was
never at fault — it is accurate to well under a millisecond here. Measured as
the gap between consecutive clicks, mouse stubbed:

    interval   promised     was       now
      50 ms     20 /s     16.0 /s   19.9 /s
      10 ms    100 /s     91.7 /s   95.1 /s
    Max speed             61.5 /s  181.4 /s

Every "was" figure is an exact multiple of 15.625 ms, which is what gave it
away. The website publishes that interval table, so these are numbers a visitor
can check with a stopwatch.

⚠ `flow_exec.Executor.sleep` had already been fixed for this, and its comment
even predicted the number — "it caps click rate at ~64 CPS however low the
interval goes". The fix was never carried across to the Basic clicker. So the
most valuable test here is not the timing one, it is
`test_no_pacing_loop_reads_the_coarse_clock`, which pins the rule everywhere at
once rather than in the one place it was noticed.
"""
import ast
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import clicker


class _DeadMouse:
    """Nothing here may reach the real desktop — same rule as conftest."""
    position = (100, 100)

    def __init__(self):
        self.t = []

    def click(self, button, count=1):
        self.t.append(time.perf_counter())

    def press(self, button):
        pass

    def release(self, button):
        pass


def _worker(interval_ms, seconds):
    w = clicker.ClickWorker()
    w._mouse = _DeadMouse()
    w.interval_ms = interval_ms
    w.stop_after_secs = seconds
    return w


# ── the rule, pinned everywhere ──────────────────────────────────────────────

# Functions that legitimately read the coarse clock while also sleeping. Each
# one measures WHOLE SECONDS, where 15.625 ms is 0.05% and nobody can tell.
#
# ⚠ Every entry is asserted to still match something, so a rename or a deletion
# fails this test rather than quietly leaving a permanent exemption behind.
_COARSE_IS_FINE = {
    ("clicker.py", "run"):
        "t0 is a start time for stop_after_secs, a whole-seconds limit; its "
        "sleeps are 50/100/300 ms guard polls where a tick does not matter",
    ("updater.py", "_wait_for_exit"):
        "waits seconds for another process to exit",
    ("interception_backend.py", "_cli"):
        "a __main__ diagnostic that times whole seconds",
}


def test_no_pacing_loop_reads_the_coarse_clock():
    """A function that both sleeps and reads `time.monotonic()` is pacing on a
    15.625 ms clock, whatever it thinks it is doing.

    This is the test that would have caught the original: the flow engine was
    fixed, the clicker was not, and nothing connected the two.
    """
    offenders = []
    seen = set()
    for name in sorted(os.listdir(ROOT)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            try:
                tree = ast.parse(fh.read())
            except SyntaxError:                 # not ours to police
                continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sleeps = coarse = False
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                f = sub.func
                if not isinstance(f, ast.Attribute) or \
                        not isinstance(f.value, ast.Name) or f.value.id != "time":
                    continue
                if f.attr == "sleep":
                    sleeps = True
                elif f.attr == "monotonic":
                    coarse = True
            if not (sleeps and coarse):
                continue
            key = (name, node.name)
            seen.add(key)
            if key not in _COARSE_IS_FINE:
                offenders.append(f"  {name}:{node.lineno}  {node.name}()")

    assert not offenders, (
        "these pace a sleep against time.monotonic(), which on Windows has "
        "15.625 ms resolution — every wait quantises up to the next tick:\n"
        + "\n".join(offenders)
        + "\nUse time.perf_counter() for the deadline, or add it to "
          "_COARSE_IS_FINE with a reason if it only measures whole seconds.")

    stale = sorted(k for k in _COARSE_IS_FINE if k not in seen)
    assert not stale, (
        "these are exempted but no longer match anything — renamed, deleted, "
        f"or already fixed:\n  {stale}\nDrop them from _COARSE_IS_FINE, or "
        "the next function to take that name inherits the exemption.")


# ── the behaviour ────────────────────────────────────────────────────────────

def _typical(fn, tries=9):
    """Median of N.

    ⚠ This was best-of-N first, on the reasoning that a loaded machine can
    make a sample slow but not fast, so the minimum is the honest floor. That
    is right for overhead and **wrong for quantisation**, which is the bug
    here: where the deadline lands relative to the next 15.625 ms tick is
    uniform, so the coarse clock produces gaps from nearly 0 up to 15.6 ms and
    the minimum is *fast*. Both tests using it passed with the bug deliberately
    reinstated. The median moves under quantisation and shrugs off load spikes,
    so it is the statistic that actually distinguishes the two.
    """
    xs = []
    for _ in range(tries):
        t0 = time.perf_counter()
        fn()
        xs.append(time.perf_counter() - t0)
    return sorted(xs)[len(xs) // 2]


@pytest.mark.parametrize("ms,ceiling_ms", [(5, 12), (20, 30), (50, 60)])
def test_a_short_wait_is_not_rounded_up_to_the_next_tick(ms, ceiling_ms):
    """⚠ The ceilings are set below what the tick would force, and above what
    a correct implementation costs. Quantised, a 5 ms wait took 16.00 ms, a
    20 ms wait 31.25, a 50 ms wait 62.50 — every ceiling here is under the
    corresponding tick multiple, so the old code fails all three, while a
    correct one has room for `time.sleep`'s own ~0.5 ms of overhead.
    """
    w = clicker.ClickWorker()
    w._mouse = _DeadMouse()
    w._running = True
    took = _typical(lambda: w._sleep(ms / 1000.0))
    assert took * 1000 < ceiling_ms, (
        f"_sleep({ms} ms) took {took * 1000:.2f} ms; "
        f"{ms} ms rounded up to a 15.625 ms tick would be about "
        f"{15.625 * (int(ms / 15.625) + 1):.2f} ms")


def test_max_speed_is_no_longer_capped_at_the_tick_rate():
    """Interval 0 is floored at 5 ms by `_interval`, so ~180 clicks/second is
    the shape of the answer. Quantisation put a hard ceiling near 64."""
    w = _worker(0, 0.6)
    w.run()
    t = w._mouse.t
    assert len(t) > 20, f"only {len(t)} clicks in 0.6 s"
    gaps = sorted(b - a for a, b in zip(t, t[1:]))
    median_ms = gaps[len(gaps) // 2] * 1000
    assert median_ms < 10.0, (
        f"{median_ms:.2f} ms between clicks = {1000 / median_ms:.0f}/s; "
        "the 15.625 ms tick used to hold this at about 64/s")


def test_the_interval_the_user_asks_for_is_the_interval_they_get():
    """50 ms is the row of the published table that was worst: 16.0/s against
    a promised 20/s. This checks the app against its own advertising."""
    w = _worker(50, 1.2)
    w.run()
    t = w._mouse.t
    assert len(t) > 8, f"only {len(t)} clicks in 1.2 s"
    gaps = sorted(b - a for a, b in zip(t, t[1:]))
    median_ms = gaps[len(gaps) // 2] * 1000    # see _typical: not the minimum
    assert 48 <= median_ms < 58, (
        f"median gap {median_ms:.2f} ms for a 50 ms interval "
        "(quantised, this was 62.50)")


# ── the property the rewrite had to preserve ─────────────────────────────────

def test_stop_still_cuts_a_long_wait_short():
    """`_sleep` is interruptible on purpose — Stop must not wait out a
    ten-second interval. The rewrite changed the loop's shape, so this is the
    thing it could plausibly have broken."""
    import threading

    w = clicker.ClickWorker()
    w._mouse = _DeadMouse()
    w._running = True
    threading.Timer(0.05, w.request_stop).start()

    t0 = time.perf_counter()
    w._sleep(10.0)
    took = time.perf_counter() - t0

    assert took < 1.0, f"_sleep ignored request_stop for {took:.2f} s"
    assert took >= 0.04, "returned before the stop could have been requested"
