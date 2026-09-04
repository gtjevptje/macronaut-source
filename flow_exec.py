"""
Real executor + Qt worker for the Macronaut flow engine.

`FlowWorker` runs a FlowInterpreter on a background QThread and is itself the
*executor* the interpreter calls into. It performs the actual side effects
(clicking, typing, image/text/pixel detection) and relays a structured run log
to the UI via Qt signals.

Detection / input logic is shared with the legacy linear player in recorder.py.
"""
import os
import time
import ctypes
import inspect
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QObject, Signal, Slot

from pynput.mouse import Button, Controller as MouseCtrl

from keystrokes import parse_key
import flow
import input_backends

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    _PYAUTOGUI = True
except Exception:
    _PYAUTOGUI = False

try:
    import matcher
    _HAS_MATCHER = True
except Exception:
    _HAS_MATCHER = False

try:
    import ocr as _ocr
    _HAS_OCR = True
except Exception:
    _HAS_OCR = False


_BTN = {"left": Button.left, "right": Button.right, "middle": Button.middle}
_color_tuple = flow.color_tuple  # shared with recorder.py


# A tight loop drives the interpreter at roughly 700,000 log events per second.
# One queued signal per event allocates a QMetaCallEvent per event, and the GUI
# thread drains a few hundred a second at best — so the event queue, and the
# process's memory, grew without bound until the app died. That is the "it
# crashes when running a script" report.
#
# Events are batched here instead: at most one delivery every LOG_FLUSH_S, and
# at most LOG_BATCH_MAX events in it. Anything past that inside one window is
# counted rather than kept, and the count is reported in the log, because a
# silently shortened log is worse than a visibly shortened one.
LOG_FLUSH_S   = 0.15
LOG_BATCH_MAX = 400
# ...except these, which are never dropped however full the window is. They are
# rare by nature, and losing one loses the shape of the run: the very first
# batching attempt here dropped its own "run ended" line, because a tight loop
# had filled the window before the run finished.
LOG_KEEP_ALWAYS = ("run_start", "run_end", "abort", "error", "backend")

# Workers with at least one key still pressed by a Hold-down node.
#
# A worker releases its own keys when its run ends, by whichever path — that is
# the normal safety net and it is inside run()'s finally. This set exists for
# the one exit that never reaches a finally: MainWindow.closeEvent and
# _quit_app both end in os._exit(0), which runs no atexit handler and gives the
# worker thread no chance to unwind. A key left down there outlives Macronaut
# itself, so the GUI thread calls release_all_held() before it pulls the plug.
_HOLDERS: set = set()


def release_all_held():
    """Panic release, callable from any thread. Safe when nothing is held."""
    for w in list(_HOLDERS):
        # Mouse first. A held button is the one that makes the desktop
        # unusable rather than merely wrong, and each release is guarded
        # separately so a backend that fails on one still gets asked the other.
        try:
            w._release_mouse()
        except Exception:
            pass
        try:
            w._release_keys(None)
        except Exception:
            pass
    _HOLDERS.clear()

# Typing rate for a text step saved without one (older flows, recorded steps).
# 0 = as fast as the target can actually read, which is the engine's own pace.
DEFAULT_TEXT_CPS = 0.0

# Two different numbers, and confusing them is what made the speed box lie.
#
# SAFE_TEXT_CPS (~33) is as fast as typing goes while every key is still held
# across a 60 Hz frame, which is what lets a game see it. It is what a step set
# to 0 — "as fast as possible" — delivers.
#
# TYPE_MAX_CPS (200) is as far as the dial goes. Between the two, the extra
# speed is taken out of the key hold: the user is trading reliability for rate,
# knowingly, and a dropped character is visible and fixed by lowering it.
#
# ⚠ Both derived, never literals here. TYPE_MAX_CPS used to be a hardcoded
# 200.0 while the engine could not exceed 33, so every rate above 33 silently
# became 33.
SAFE_TEXT_CPS = input_backends.safe_type_cps()
TYPE_MAX_CPS = input_backends.MAX_TYPE_CPS


class FlowWorker(QObject):
    """Owns the interpreter; emits progress + log events to the UI thread."""

    node_started   = Signal(str)    # node id (for canvas highlighting)
    log_batch      = Signal(list)   # structured run-log entries, coalesced
    status_changed = Signal(str)
    finished       = Signal(str)    # final status: done|stopped|error
    error_occurred = Signal(str)
    # [(key name, id of the node that pressed it), ...] — emitted only when the
    # set actually changes, which is once per Hold-down or Release node. Cheap
    # by construction: unlike node progress, this cannot fire in a tight loop.
    held_changed   = Signal(list)
    # node id -> mean ms per visit, once, at the end of a run. Feeds runstats,
    # which is what turns the timeline's guesses into measurements.
    timings_ready  = Signal(dict)
    progress       = Signal(int)    # cumulative auto-click count (live CPS)

    def __init__(self, graph: "flow.FlowGraph", speed_factor: float = 1.0,
                 blacklist: Optional[List[str]] = None):
        super().__init__()
        self.graph        = graph
        self.speed_factor = speed_factor
        self._blockset    = {b.lower() for b in (blacklist or [])}
        self._running     = False
        # Sticky, unlike _running. run() is a queued slot, so Stop can land
        # between thread.start() and the slot being dispatched — see run().
        self._stop_requested = False
        self._mouse, self._mouse_backend, self._mouse_warning = \
            input_backends.make_mouse()
        self._kb, self._kb_backend, self._kb_warning = input_backends.make_keyboard()
        try:
            from settings import SettingsManager
            self._key_hold_s = max(0, int(getattr(SettingsManager(), "key_hold_ms", 60))) / 1000.0
        except Exception:
            self._key_hold_s = 0.06
        self._interp: Optional[flow.FlowInterpreter] = None
        # Keys a Hold-down node left pressed: name -> the parsed key object.
        # Keyed by *name* rather than by the parsed key because a backend may
        # hand back a fresh object each time and two of them being equal (let
        # alone hashable) is not something any backend promises.
        # Insertion-ordered, so releasing in reverse is releasing in the order
        # a person would.
        self._held: Dict[str, Any] = {}
        # Which node pressed each held key, so the canvas can keep that node lit
        # for as long as its effect is still live rather than only while it ran.
        self._held_by: Dict[str, str] = {}
        # The mouse button a drag currently has pressed, or None. A stuck mouse
        # button is worse than a stuck key: the user cannot click the Stop
        # button to fix it, because every click they make is part of a
        # drag-select they never started. So it is tracked here rather than
        # only in _do_drag's finally, which the os._exit(0) quit path skips.
        self._held_btn = None
        self._cur_node: Optional[str] = None
        # node id -> [total ms, visits]. Averaged per visit at the end: a loop
        # body entered 40 times should report what one pass costs, not the sum.
        self._timings: Dict[str, List[float]] = {}

    # ── control ───────────────────────────────────────────────────────
    def request_stop(self):
        self._stop_requested = True
        self._running = False

    def _release_keys(self, names: Optional[List[str]] = None):
        """Take keys back up. ``names=None`` releases everything still down.

        A named key that is not currently held is still released. "Release: W"
        should release W — the alternative is a node that silently does nothing
        because the state it expected drifted, which is the harder bug to see.
        """
        before = dict(self._held)
        if names is None:
            items = [(n, self._held[n]) for n in reversed(list(self._held))]
            self._held.clear()
        else:
            items = []
            for n in reversed(list(names)):
                n = str(n).lower()
                key = self._held.pop(n, None)
                items.append((n, key if key is not None else parse_key(n)))
        for n, _k in items:
            self._held_by.pop(n, None)
        # ⚠ Both, not just the keys: this worker is also in _HOLDERS while a
        # drag has a button down, and dropping it here would take the mouse
        # button out of the panic path's reach.
        if not self._held and self._held_btn is None:
            _HOLDERS.discard(self)
        for _name, key in items:
            if key is None:
                continue
            try:
                self._kb.release(key)
            except Exception:
                pass    # a dying backend must not strand the rest of the keys
        if self._held != before:
            self._emit_held()

    def _release_mouse(self):
        """Let go of the button a drag is holding. Safe when none is.

        Idempotent, and it clears the field *before* the release so a backend
        that throws cannot leave the worker thinking it still owns a button it
        will never try to release again.
        """
        btn, self._held_btn = self._held_btn, None
        if btn is None:
            return
        if not self._held:
            _HOLDERS.discard(self)
        try:
            self._mouse.release(btn)
        except Exception:
            pass

    def _emit_held(self):
        """Announce what is still down, and which node put it there.

        Emitted after the keys have actually moved, never before: the canvas
        lights a node because a key *is* held, and a signal sent ahead of the
        release would leave it lit for a key that is already up.
        """
        try:
            self.held_changed.emit([(n, self._held_by.get(n, ""))
                                    for n in self._held])
        except RuntimeError:
            pass    # the receiving side went away mid-run

    # ── executor protocol (called by the interpreter) ─────────────────
    def running(self) -> bool:
        return self._running

    def sleep(self, secs: float):
        """Interruptible sleep — Stop cuts it short within ~10 ms.

        ⚠ perf_counter, **not** monotonic. On Windows under Python ≤ 3.12
        `time.monotonic()` is GetTickCount64, whose resolution is 15.625 ms, so
        every deadline here quantised up to the next tick: a 5 ms wait took
        15.6, a 19 ms wait took 31.2, a 50 ms wait took 62.5. That put a
        ~15.6 ms floor under every interval the engine can ask for — typing
        arrived at 16 ch/s when 20 was selected, and it caps click rate at
        ~64 CPS however low the interval goes. `time.sleep` itself was never
        the problem; it is accurate to well under a millisecond here.
        """
        deadline = time.perf_counter() + max(0.0, secs)
        while self._running:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            time.sleep(min(0.01, remaining))

    def _blocked(self, key_str: str) -> bool:
        return key_str.lower() in self._blockset

    def _type(self, text: str, key_positions: str = "", stoppable: bool = False,
              cps: float = 0.0, send_as: str = ""):
        """Type through the backend, passing only the extras it understands.

        pynput's own Controller.type() takes neither a stop callback nor a key
        layout, so the capability has to be probed. Probed by *signature*, not
        by catching TypeError: a TypeError raised from inside a half-finished
        injection would otherwise be read as "unsupported" and the whole string
        typed a second time.
        """
        fn = self._kb.type
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):     # C-implemented callable
            params = {}
        kwargs = {}
        if stoppable and "should_continue" in params:
            # A scancode backend is a real per-key loop capped near 33 ch/s, so
            # a long string is seconds of typing rather than an instant.
            kwargs["should_continue"] = lambda: self._running
        if key_positions and "key_positions" in params:
            kwargs["key_positions"] = key_positions
        if cps and "cps" in params:
            # Only ever *shortens* the per-key timing, and only above the safe
            # pace — below it this loop waits out the rest of each period
            # instead, which keeps a slow rate slow without stretching the key
            # press itself into something no keyboard would produce.
            kwargs["cps"] = cps
        if send_as and send_as != flow.SEND_AUTO and "send_as" in params:
            # Only ever passed when the step actually chose one. "auto" is the
            # absence of an opinion, and a backend that has never heard of this
            # argument must keep behaving exactly as it did.
            kwargs["send_as"] = send_as
        fn(text, **kwargs)

    # ── interpreter entry point on the worker thread ──────────────────
    @Slot()
    def run(self):
        # Stop can arrive before this slot is dispatched: stop_playback() calls
        # request_stop() on the GUI thread while the worker thread is still
        # spinning up its event loop. Setting _running = True unconditionally
        # discarded that stop, and the flow then ran with nothing able to halt
        # it — stop_playback() had already cleared self._worker, so pressing
        # Stop again reached nobody.
        if self._stop_requested:
            self.status_changed.emit("idle")
            self.finished.emit("stopped")
            return
        self._running = True
        self.status_changed.emit("running")

        buf: List[dict] = []
        # Mutable cell rather than locals, because the closures below assign.
        st = {"last": 0.0, "node": None, "sent": None, "dropped": 0,
              "t0": None}

        def flush(force: bool = False):
            now = time.monotonic()
            if not force and now - st["last"] < LOG_FLUSH_S:
                return
            st["last"] = now
            # The canvas only ever shows one node lit, so every highlight but
            # the newest in a window is work nobody sees.
            if st["node"] is not None and st["node"] != st["sent"]:
                st["sent"] = st["node"]
                self.node_started.emit(st["node"])
            if st["dropped"]:
                buf.append({"t": time.time(), "kind": "dropped",
                            "n": st["dropped"]})
                st["dropped"] = 0
            if buf:
                self.log_batch.emit(list(buf))
                buf.clear()

        def close_timing(now: float):
            """Bank the time the node we are leaving actually took.

            perf_counter, not monotonic: monotonic is GetTickCount64 on Windows
            under Python 3.12 and quantises to 15.625 ms, which would round a
            50 ms node up to 62.5 and put that fiction straight into runstats —
            the very number the timeline is supposed to make honest.
            """
            prev, t0 = st["node"], st["t0"]
            if prev is None or t0 is None:
                return
            slot = self._timings.setdefault(prev, [0.0, 0])
            slot[0] += (now - t0) * 1000.0
            slot[1] += 1

        def on_log(ev: dict):
            if ev.get("kind") == "node_enter" and ev.get("id"):
                now = time.perf_counter()
                close_timing(now)
                st["t0"] = now
                self._cur_node = ev["id"]
                st["node"] = ev["id"]
            if (len(buf) >= LOG_BATCH_MAX
                    and ev.get("kind") not in LOG_KEEP_ALWAYS):
                st["dropped"] += 1
            else:
                buf.append(ev)
            flush()

        # Say which backends actually ran, every time — not only when one fell
        # back. A working Interception run and a silent fallback to pynput
        # looked identical in the log, and the difference between them is the
        # entire reason the setting exists.
        on_log({"t": time.time(), "kind": "backend",
                "keyboard": self._kb_backend, "mouse": self._mouse_backend})
        for _what, _warn in (("keyboard", self._kb_warning),
                             ("mouse", self._mouse_warning)):
            if _warn:
                on_log({"t": time.time(), "kind": "error",
                        "msg": f"{_what} backend: {_warn}"})

        try:
            self._interp = flow.FlowInterpreter(self.graph, self, on_log=on_log)
            status = self._interp.run()
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            status = "error"
        finally:
            # The safety net under Hold-down. A run can end three ways — it
            # finishes, Stop cuts it, or a node raises — and a key the flow
            # never got to release stays down in the game afterwards, with
            # Macronaut showing "idle" and no way to guess what to press. So
            # every path comes through here, and it is a finally rather than
            # three call sites for the same reason the per-node release is.
            if self._held:
                names = ", ".join(self._held)
                self._release_keys(None)
                on_log({"t": time.time(), "kind": "error",
                        "msg": f"run ended with keys still held — released: {names}"})
            close_timing(time.perf_counter())   # the last node never gets a next
        flush(force=True)     # the run_end entry must not be left in the buffer
        # Per *visit*, not per run: a loop body entered 40 times should report
        # what one pass costs, which is the number a timeline can draw a box
        # from. Emitted after the flush so the run log is already settled.
        self.timings_ready.emit({nid: total / n
                                 for nid, (total, n) in self._timings.items()
                                 if n})
        self.status_changed.emit("idle")
        self.finished.emit(status)

    # ── action execution ──────────────────────────────────────────────
    def do_action(self, step: dict, variables: Dict[str, Any]) -> bool:
        """Run one action node. Returns success (False on timeout/failure)."""
        if not step or not step.get("data", {}).get("enabled", True):
            return True

        # Pre-step delay
        delay = (float(step.get("delay_ms", 0)) / 1000.0) * self.speed_factor
        if delay > 0:
            self.sleep(delay)
        if not self._running:
            return True

        kind = step.get("kind", "")
        d = step.get("data", {})

        try:
            if kind == "autoclick":
                return self._do_autoclick(d, variables)

            if kind == "click":
                x, y = d.get("x", 0), d.get("y", 0)
                btn = _BTN.get(d.get("button", "left"), Button.left)
                self._mouse.position = (x, y)
                if d.get("hold"):
                    self._mouse.press(btn)
                    self.sleep(max(0, d.get("hold_ms", 1000)) / 1000.0)
                    self._mouse.release(btn)
                else:
                    self._mouse.click(btn, d.get("clicks", 1))
                return True

            if kind == "move":
                self._mouse.position = (d.get("x", 0), d.get("y", 0))
                return True

            if kind == "drag":
                return self._do_drag(d)

            if kind == "scroll":
                return self._do_scroll(d)

            if kind in ("key", "combo"):
                keys = d.get("keys", [])
                if any(self._blocked(k) for k in keys):
                    return True
                mode = flow.key_mode(d)

                if mode == flow.KEY_UP:
                    # No keys captured means "whatever is still down". That is
                    # the only way to undo a Hold whose keys you have since
                    # forgotten, and it is what the panic path uses too.
                    self._release_keys(keys or None)
                    return True

                if mode == flow.KEY_DOWN:
                    changed = False
                    for k in keys:
                        key = parse_key(k)
                        if key is None or str(k).lower() in self._held:
                            continue    # already down: pressing again is noise
                        self._kb.press(key)
                        self._held[str(k).lower()] = key
                        self._held_by[str(k).lower()] = self._cur_node or ""
                        _HOLDERS.add(self)
                        changed = True
                        # let the game's per-frame poll see this key before the
                        # next one arrives — W and A a frame apart still read
                        # as "both down" to anything that polls state.
                        self.sleep(self._key_hold_s)
                    if changed:
                        self._emit_held()
                    return True

                # tap / hold — pressed and released inside this node.
                # hold_ms is gameplay-semantic real time ("hold W for 3s") and is
                # NOT scaled by speed_factor, unlike other delays in this engine.
                hold_ms = int(d.get("hold_ms", 0) or 0)
                # repeat was written by the editor from the beginning and read
                # by nobody, so a step set to 5 pressed once.
                repeat = max(1, int(d.get("repeat", 1) or 1))
                for i in range(repeat):
                    if not self._running:
                        break
                    if i:
                        # Without a gap between them, two presses of the same
                        # key arrive as one long press — the receiver sees no
                        # up-then-down, so five taps land as one.
                        self.sleep(self._key_hold_s)
                    held = []
                    try:
                        for k in keys[:-1]:
                            key = parse_key(k)
                            if key:
                                self._kb.press(key)
                                held.append(key)
                                self.sleep(self._key_hold_s)
                        if keys:
                            last = parse_key(keys[-1])
                            if last:
                                self._kb.press(last)
                                held.append(last)
                                if mode == flow.KEY_HOLD and hold_ms > 0:
                                    self.sleep(hold_ms / 1000.0)
                                else:
                                    # a 0ms tap falls between the game's frame
                                    # polls; hold so it is seen
                                    self.sleep(self._key_hold_s)
                    finally:
                        # Guaranteed release: every pressed key (modifiers + the
                        # final key) must come back up even if the run is stopped
                        # or an exception interrupts the hold — a stuck-down W in
                        # a game is the worst failure mode of this feature.
                        for k in reversed(held):
                            self._kb.release(k)
                return True

            if kind == "text":
                text = flow.substitute_vars(d.get("text", ""), variables)
                # The Type editor has always stored a "ch/s" rate (StepDialog
                # writes speed_cps) and this loop has always ignored it, so text
                # went out as fast as the backend would take it — thousands of
                # characters a second. Targets drop what they cannot keep up
                # with, and a per-character shift (every capital) is the first
                # thing to get lost, which is why capitals suffered worst.
                cps = float(d.get("speed_cps", DEFAULT_TEXT_CPS) or 0)
                text = "".join(c for c in text if not self._blocked(c))
                kp = str(d.get("key_positions", "") or "")
                sa = flow.send_as(d)
                if cps <= 0:
                    # "As fast as possible" means as fast as a target can still
                    # read, not as fast as Windows will accept: the backend's
                    # own pace, ~33 ch/s, with every key held across a 60 Hz
                    # frame. Faster is available but has to be asked for.
                    self._type(text, kp, stoppable=True, send_as=sa)
                    return True
                # One call for the whole string, at every rate. ⚠ Do not go back
                # to a per-character loop. A typing call releases its modifiers
                # when it ends, so calling it once per character taps SHIFT for
                # each character rather than holding it across a run: it pays a
                # ~20 ms settle every time, so a rate below the safe pace never
                # arrived, and it puts a modifier release between every pair of
                # characters — the shape that lost 2.0.16 its text. The backend
                # paces itself (input_backends.type_timing) and polls
                # should_continue per character, so Stop still cuts within one.
                #
                # speed_factor scales delays, so it divides the rate: x2 slower
                # is half the characters per second.
                sf = self.speed_factor or 1.0
                self._type(text, kp, stoppable=True, cps=cps / sf, send_as=sa)
                return True

            if kind == "wait":
                self.sleep(d.get("ms", 0) / 1000.0)
                return True

            if kind == "wait_image":
                return self._do_wait_image(d, variables)

            if kind == "wait_text":
                return self._do_wait_text(d, variables)

            if kind == "wait_pixel":
                return self._do_wait_pixel(d, variables)

        except Exception as exc:
            self.error_occurred.emit(f"Action error: {exc}")
            return False

        return True

    # ── auto-click node (ported from clicker.ClickWorker) ─────────────
    def _autoclick_focus_ok(self, focus_window: str) -> bool:
        if not focus_window:
            return True
        try:
            import win32gui
            title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
            return focus_window.lower() in title.lower()
        except Exception:
            return True

    def _autoclick_image_gate(self, image_path: str, confidence: float) -> bool:
        # If matching is unavailable or the image is missing we can't check —
        # don't block the automation (otherwise it would wait forever).
        import os
        if not image_path or not os.path.exists(image_path):
            return True
        if not (_HAS_MATCHER and matcher.ENABLED):
            return True
        try:
            return matcher.present(image_path, confidence)
        except Exception:
            return False

    def _do_drag(self, d: dict) -> bool:
        """Press at one point, travel there while held, release at the other.

        The shape is settle-press-settle-travel-settle-release, and every one of
        those settles is load-bearing rather than polite. A receiver samples the
        pointer once a frame and works out the gesture from where it has *been*:
        put the button-down and the first movement in the same sample and it
        reads a click at the far end; skip the intermediate moves entirely and
        it reads a click at the near one. Neither is a drag, and neither reports
        an error — the flow carries on believing it swiped. See flow.drag_moves
        for why the move count is derived rather than offered.

        ⚠ The release is a `finally`, and the button is registered in _HOLDERS
        for the duration. A key left down by a stopped run is bad; a mouse
        button left down is worse, because the user cannot click Stop to fix it
        — every click they try becomes part of a drag they never started.
        """
        btn = _BTN.get(d.get("button", "left"), Button.left)
        settle = flow.DRAG_SETTLE_MS / 1000.0
        path = flow.drag_path(d)
        # Spread over the moves rather than per-move-from-a-fixed-tick, so the
        # gesture takes the time the editor asked for whatever the count is.
        period = (flow.drag_duration_ms(d) / 1000.0 / len(path)) if path else 0.0

        self._mouse.position = (int(d.get("x", 0) or 0), int(d.get("y", 0) or 0))
        self.sleep(settle)
        if not self.running():
            return False

        self._mouse.press(btn)
        self._held_btn = btn
        _HOLDERS.add(self)
        try:
            self.sleep(settle)
            deadline = time.perf_counter()
            for pt in path:
                if not self.running():
                    return False
                self._mouse.position = pt
                if period:
                    # Same deadline idiom as scrolling and typing: spend the gap
                    # as "wait until this step's slot is up", so two sleep
                    # overshoots per move don't accumulate into a drag that
                    # takes half again as long as it says it does.
                    deadline += period
                    self.sleep(max(0.0, deadline - time.perf_counter()))
            self.sleep(settle)
        finally:
            self._release_mouse()
        return True

    def _do_scroll(self, d: dict) -> bool:
        """Turn the wheel `amount` notches, optionally somewhere in particular.

        The cursor is moved first when the step names a position, because the
        wheel goes to whatever is *under the pointer* — a scroll step that did
        not move would quietly scroll whichever window the user last left the
        mouse over, which is the kind of bug that looks like the script working
        on one machine and not another.

        Notch by notch, and paced when a speed is set. This is the same lesson
        typing paid for four times over: Windows accepts a whole roll in one
        event, and a receiver that reads input once a frame and takes a bounded
        amount per pass still only sees part of it. `speed_nps` 0 means "as fast
        as the backend will send them", which is right for a short flick and
        wrong for scrolling a list to its end.
        """
        if not d.get("at_cursor", True):
            self._mouse.position = (int(d.get("x", 0) or 0),
                                    int(d.get("y", 0) or 0))
        dx, dy = flow.scroll_vector(d)
        n = flow.scroll_notches(d)
        cps = flow.scroll_cps(d)
        period = 1.0 / cps if cps > 0 else 0.0
        deadline = time.perf_counter()
        for i in range(n):
            if not self.running():
                return False
            self._mouse.scroll(dx, dy)
            if period:
                # Spend the gap as "wait until this notch's slot is up" rather
                # than a fixed sleep, so sleep's overshoot doesn't accumulate
                # into a rate slower than the one that was asked for.
                deadline += period
                if i < n - 1:
                    self.sleep(max(0.0, deadline - time.perf_counter()))
        return True

    def _do_autoclick(self, d: dict, variables) -> bool:
        """Run a Basic-style auto-clicker as one long-lived, internally-looping
        node. Mirrors clicker.ClickWorker.run() and respects self.running()."""
        import random
        button     = _BTN.get(d.get("button", "left"), Button.left)
        click_type = d.get("click_type", "single")
        hold_ms    = d.get("hold_duration_ms", d.get("hold_ms", 100))
        max_speed  = bool(d.get("max_speed"))
        use_fixed  = bool(d.get("use_fixed", d.get("position") == "fixed"))
        fixed_x    = int(d.get("fixed_x", 0))
        fixed_y    = int(d.get("fixed_y", 0))
        interval_ms = 0 if max_speed else d.get("interval_ms", 1000)
        randomize  = bool(d.get("randomize", False))
        rand_ms    = d.get("random_range_ms", 100)
        click_limit = int(d.get("click_limit", 0) or 0)
        stop_after  = float(d.get("stop_after_secs", 0) or 0)
        human      = bool(d.get("human_mode", False))
        jitter_px  = int(d.get("jitter_px", 5) or 0)
        use_region = bool(d.get("use_region", False))
        region     = d.get("region", (0, 0, 1920, 1080))
        pause_focus = bool(d.get("pause_on_focus", False))
        focus_win  = d.get("focus_window", "")
        wait_img   = bool(d.get("wait_for_image", False))
        image_path = d.get("image_path", "")
        confidence = d.get("image_confidence", d.get("confidence", 0.8))

        floor = 0.001 if max_speed else 0.005
        count = 0
        t0 = time.monotonic()
        last_emit = t0
        while self._running:
            if pause_focus and not self._autoclick_focus_ok(focus_win):
                self.sleep(0.1)
                continue
            if wait_img and not self._autoclick_image_gate(image_path, confidence):
                self.sleep(0.3)
                continue

            # position (+ optional human jitter, region clamp)
            if use_fixed:
                x, y = fixed_x, fixed_y
            else:
                cx, cy = self._mouse.position
                x, y = int(cx), int(cy)
            if human and jitter_px > 0:
                x += random.randint(-jitter_px, jitter_px)
                y += random.randint(-jitter_px, jitter_px)
            if use_region:
                rx, ry, rw, rh = region
                x = max(rx, min(rx + rw - 1, x))
                y = max(ry, min(ry + rh - 1, y))
            if use_fixed:
                self._mouse.position = (x, y)

            if click_type == "single":
                self._mouse.click(button)
            elif click_type == "double":
                self._mouse.click(button, 2)
            else:  # hold
                dur = hold_ms / 1000.0
                if human:
                    dur *= random.uniform(0.7, 1.3)
                self._mouse.press(button)
                self.sleep(dur)
                self._mouse.release(button)

            count += 1
            now = time.monotonic()
            if now - last_emit >= 0.2:
                self.progress.emit(count)
                last_emit = now

            if click_limit > 0 and count >= click_limit:
                break
            if stop_after > 0 and (now - t0) >= stop_after:
                break

            base = interval_ms / 1000.0
            if randomize or human:
                rng = rand_ms / 1000.0
                if human:
                    rng = max(rng, base * 0.15)
                base += random.uniform(-rng, rng)
            self.sleep(max(floor, base))

        self.progress.emit(count)
        return True

    # ── sensor evaluation (one-shot, for If/While/Until conditions) ───
    def eval_sensor(self, cond: dict, variables: Dict[str, Any]) -> bool:
        t = cond.get("type", "always")
        if t == "image":
            return self._sense_image(cond)
        if t == "text":
            return self._sense_text(cond, variables)
        if t == "pixel":
            return self._sense_pixel(cond)
        return False

    # ── detection internals ───────────────────────────────────────────
    def _grab(self):
        from PIL import ImageGrab
        return ImageGrab.grab(all_screens=True).convert("RGB")

    def _warn_missing_template(self, image_path: str) -> None:
        """Put one line in the run log when a template file is not on disk.

        ⚠ Goes through the interpreter's own `on_log`, the same channel the
        backend and error lines at the top of `run()` use — the worker has no
        logger of its own, and inventing one here would be a second way to say
        the same thing.

        Never raises: this is a diagnostic, and a step must not fail because
        the note about it could not be written.
        """
        try:
            if not image_path or os.path.exists(image_path):
                return
            interp = getattr(self, "_interp", None)
            on_log = getattr(interp, "on_log", None)
            if on_log:
                on_log({"t": time.time(), "kind": "error",
                        "msg": f"image file not found: {image_path} — this step "
                               "cannot match anything until it is back"})
        except Exception:
            pass

    def _do_wait_image(self, d: dict, variables) -> bool:
        if not _PYAUTOGUI:
            return True
        from PIL import Image
        image_path = d.get("image_path", "")
        confidence = d.get("confidence", 0.8)
        timeout_s  = d.get("timeout_s", 0)
        do_click   = d.get("click", False)
        region_logical = d.get("region")
        deadline = (time.monotonic() + timeout_s) if timeout_s > 0 else None

        # ⚠ Say so once, up front, if the template file is not there.
        #
        # Every matcher path degrades to "not found" rather than raising — a
        # missing file, a file that is not an image, a zero-byte one — which is
        # the right behaviour for a step that is *supposed* to tolerate not
        # finding things. The cost is that it makes a moved or deleted image
        # indistinguishable from "the thing is not on screen": the step waits
        # out its whole timeout and takes the not-found branch, exactly as it
        # would if the flow were working. Somebody who reorganised a folder
        # then has a flow that quietly stopped working and a run log that
        # blames the screen.
        #
        # One line, before the loop, so it cannot become a per-poll flood.
        self._warn_missing_template(image_path)

        while self._running:
            try:
                shot = self._grab()
                # The search area is stored in LOGICAL virtual-desktop coords
                # (what the overlay emits); everything below is in screenshot
                # pixels. `shot` itself stays whole either way — the click maths
                # and _click_physical both measure against the full grab.
                region_phys = (_ocr.to_physical_region(region_logical, shot)
                               if (region_logical and _HAS_OCR) else None)
                if _HAS_MATCHER and matcher.ENABLED:
                    box = matcher.find(image_path, confidence, screenshot=shot,
                                       region=region_phys)
                else:
                    needle = Image.open(image_path).convert("RGB")
                    sub, dx, dy = (shot, 0, 0)
                    if region_phys:
                        rx, ry, rw, rh = region_phys
                        sub, dx, dy = shot.crop((rx, ry, rx + rw, ry + rh)), rx, ry
                    box = pyautogui.locate(needle, sub, confidence=confidence)
                    if box is not None and (dx or dy):
                        box = type(box)(box.left + dx, box.top + dy,
                                        box.width, box.height)
                if box is not None:
                    if do_click:
                        px = box.left + box.width // 2 + d.get("offset_x", 0)
                        py = box.top + box.height // 2 + d.get("offset_y", 0)
                        self._click_physical(px, py, shot, d.get("button", "left"),
                                             d.get("clicks", 1))
                    return True
            except Exception:
                pass
            if deadline and time.monotonic() >= deadline:
                return False     # timed out → step "failed"
            self.sleep(0.3)
        return False

    def _do_wait_text(self, d: dict, variables) -> bool:
        if not (_HAS_OCR and _ocr.available()):
            return True
        engine = _ocr.get_engine()
        target = flow.substitute_vars(d.get("text", ""), variables)
        case_s = d.get("case_sensitive", False)
        min_sc = d.get("min_score", 0.5)
        timeout_s = d.get("timeout_s", 0)
        do_click = d.get("click", False)
        region_logical = d.get("region")
        fuzzy = d.get("fuzzy", True)
        store_var = d.get("store_var")
        deadline = (time.monotonic() + timeout_s) if timeout_s > 0 else None
        while self._running and target:
            try:
                shot = self._grab()
                region_phys = _ocr.to_physical_region(region_logical, shot)
                tm = engine.find_text(target, shot, region=region_phys,
                                      case_sensitive=case_s, min_score=min_sc,
                                      fuzzy=fuzzy)
                if tm is not None:
                    if store_var:
                        variables[store_var] = getattr(tm, "text", target)
                    if do_click:
                        px = tm.left + tm.width // 2 + d.get("offset_x", 0)
                        py = tm.top + tm.height // 2 + d.get("offset_y", 0)
                        self._click_physical(px, py, shot, d.get("button", "left"),
                                             d.get("clicks", 1))
                    return True
            except Exception:
                pass
            if deadline and time.monotonic() >= deadline:
                return False
            self.sleep(0.5)
        return False

    def _do_wait_pixel(self, d: dict, variables) -> bool:
        """Poll a screen pixel until it matches the target colour (within
        tolerance) or the timeout elapses. Optionally clicks the point."""
        timeout_s = float(d.get("timeout_s", 0) or 0)
        deadline = (time.monotonic() + timeout_s) if timeout_s > 0 else None
        cond = {"x": d.get("x", 0), "y": d.get("y", 0),
                "color": d.get("color"), "tolerance": d.get("tolerance", 10)}
        while self._running:
            if self._sense_pixel(cond):
                if d.get("click"):
                    shot = self._grab()
                    self._click_physical(int(d.get("x", 0)), int(d.get("y", 0)),
                                         shot, d.get("button", "left"),
                                         d.get("clicks", 1))
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            self.sleep(0.2)
        return False

    def _sense_image(self, cond: dict) -> bool:
        """One condition check. If cond['timeout_s']>0 (If/Else), actively poll
        until the image appears or the timeout elapses; a timeout -> False."""
        if not _PYAUTOGUI:
            return False
        timeout_s = float(cond.get("timeout_s", 0) or 0)
        deadline = (time.monotonic() + timeout_s) if timeout_s > 0 else None
        region = cond.get("region")
        while True:
            found = False
            try:
                shot = self._grab()
                if region and _HAS_OCR:
                    rp = _ocr.to_physical_region(region, shot)
                    if rp:
                        x, y, w, h = rp
                        shot = shot.crop((x, y, x + w, y + h))
                if _HAS_MATCHER and matcher.ENABLED:
                    found = matcher.find(cond.get("image_path", ""),
                                         cond.get("confidence", 0.8),
                                         screenshot=shot) is not None
                else:
                    from PIL import Image
                    needle = Image.open(cond.get("image_path", "")).convert("RGB")
                    found = pyautogui.locate(
                        needle, shot, confidence=cond.get("confidence", 0.8)) is not None
            except Exception:
                found = False
            if found:
                return True
            if deadline is None or not self.running() or time.monotonic() >= deadline:
                return False
            self.sleep(0.3)

    def _sense_text(self, cond: dict, variables) -> bool:
        """One condition check. If cond['timeout_s']>0 (If/Else), actively poll
        until the text appears or the timeout elapses; a timeout -> False."""
        if not (_HAS_OCR and _ocr.available()):
            return False
        timeout_s = float(cond.get("timeout_s", 0) or 0)
        deadline = (time.monotonic() + timeout_s) if timeout_s > 0 else None
        target = flow.substitute_vars(cond.get("text", ""), variables)
        if not target:
            return False
        while True:
            tm = None
            try:
                engine = _ocr.get_engine()
                shot = self._grab()
                region_phys = _ocr.to_physical_region(cond.get("region"), shot)
                tm = engine.find_text(target, shot, region=region_phys,
                                      case_sensitive=cond.get("case_sensitive", False),
                                      min_score=cond.get("min_score", 0.5),
                                      fuzzy=cond.get("fuzzy", True))
                if tm is not None and cond.get("store_var"):
                    variables[cond["store_var"]] = getattr(tm, "text", target)
            except Exception:
                tm = None
            if tm is not None:
                return True
            if deadline is None or not self.running() or time.monotonic() >= deadline:
                return False
            self.sleep(0.5)

    def _sense_pixel(self, cond: dict) -> bool:
        try:
            want = _color_tuple(cond.get("color"))
            if want is None:
                return False
            tol = int(cond.get("tolerance", 10))
            from PIL import ImageGrab
            shot = ImageGrab.grab(all_screens=True).convert("RGB")
            x, y = int(cond.get("x", 0)), int(cond.get("y", 0))
            if not (0 <= x < shot.width and 0 <= y < shot.height):
                return False
            r, g, b = shot.getpixel((x, y))
            return (abs(r - want[0]) <= tol and abs(g - want[1]) <= tol
                    and abs(b - want[2]) <= tol)
        except Exception:
            return False

    # ── physical click (multi-monitor / mixed-DPI safe) ───────────────
    def _click_physical(self, phys_x, phys_y, screenshot, btn_str="left", clicks=1):
        u32 = ctypes.windll.user32
        vd_x = u32.GetSystemMetrics(76); vd_y = u32.GetSystemMetrics(77)
        vd_w = u32.GetSystemMetrics(78); vd_h = u32.GetSystemMetrics(79)
        scale_x = screenshot.width / vd_w
        scale_y = screenshot.height / vd_h
        lx = vd_x + phys_x / scale_x
        ly = vd_y + phys_y / scale_y
        norm_x = int((lx - vd_x) * 65535 / (vd_w - 1))
        norm_y = int((ly - vd_y) * 65535 / (vd_h - 1))

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

        MOVE = 0x0001 | 0x8000 | 0x4000
        _DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
        _UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}
        d_flag = _DOWN.get(btn_str, 0x0002) | 0x8000 | 0x4000
        u_flag = _UP.get(btn_str, 0x0004) | 0x8000 | 0x4000

        def mk(flags):
            inp = INPUT(); inp.type = 0
            inp.mi.dx = norm_x; inp.mi.dy = norm_y; inp.mi.mouseData = 0
            inp.mi.dwFlags = flags; inp.mi.time = 0; inp.mi.dwExtraInfo = None
            return inp

        u32.SendInput(1, ctypes.byref(mk(MOVE)), ctypes.sizeof(INPUT))
        time.sleep(0.05)
        for _ in range(max(1, clicks)):
            u32.SendInput(1, ctypes.byref(mk(d_flag)), ctypes.sizeof(INPUT))
            u32.SendInput(1, ctypes.byref(mk(u_flag)), ctypes.sizeof(INPUT))
