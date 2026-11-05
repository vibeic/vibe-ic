"""#1410 — two checkers that could not SEE the distinction they were asserting.

Both findings are the same shape and both are FALSE POSITIVES, so both repairs
are to the SCANNER and neither is an exemption:

  * `loop_watchdog_compliance_check` class (b) called
    `gate_host_independence_check.py::_CheckoutClaim.__enter__` an UNBOUNDED
    poll loop. It is a non-blocking flock acquire with
    `deadline = time.monotonic() + self.wait_s` and a `return` on expiry. The
    gate carried zero occurrences of `monotonic` or `deadline`: `loop_guard` was
    the only bound it could recognise.
  * `declaration_searched_only_inside_a_truncated_window` called
    `flow_output_substance.py::_is_probably_binary` a declaration searched
    inside a window. `b"\\x00" in data[:8192]` is git's text/binary heuristic;
    a miss there means "probably text", never "the author declared nothing".

WHAT THIS MODULE PINS is the direction that matters: teaching a scanner to see
a bound must not teach it to stop looking. Every case below is driven in BOTH
directions, and the decisive one is `test_removing_the_deadline_from_the_real_
function_flags_it_again` — the REAL shipped function, with the deadline taken
out together with any independent iteration cap, must redden. That separates
"it learned to see the bound" from
"it learned to ignore that function".

chip-AGNOSTIC: pure AST shapes, no IC / PDK / vendor content.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import loop_watchdog_compliance_check as W          # noqa: E402

WINDOW_PROG = PROGRAMS / "declaration_searched_only_inside_a_truncated_window.py"


def _offenses(src: str):
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "cand.py"
        f.write_text(src, encoding="utf-8")
        return W.scan_file(f)


def _kinds(offs):
    return {o.kind for o in offs}


# ══ the watchdog scanner ═══════════════════════════════════════════════════
#
# (b) THE NEGATIVE CONTROL — a loop with no bound at all is still caught.

_TRULY_UNBOUNDED = '''\
import time


def wait_for(fh):
    while True:
        if fh.ready():
            return True
        time.sleep(0.25)
'''

_UNBOUNDED_WHILE_COND = '''\
import time


def drain(q):
    while not q.empty():
        time.sleep(0.1)
'''


def test_an_unbounded_poll_loop_is_still_caught():
    """THE FALSIFICATION THAT MATTERS MOST: byte-for-byte the shape of the
    bounded acquire minus its clock. No deadline, no exit but a ready flag that
    may never come — it can spin forever and must stay a class (b) offense."""
    offs = _offenses(_TRULY_UNBOUNDED)
    assert "while" in _kinds(offs), offs


def test_an_unbounded_condition_poll_is_still_caught():
    offs = _offenses(_UNBOUNDED_WHILE_COND)
    assert "while" in _kinds(offs), offs


# (b continued) NEAR-MISSES — each is one property short of a bound, and each
# must STILL be flagged. Without these, "recognise a deadline" degrades into
# "recognise the word deadline".

_WALL_CLOCK_NOT_MONOTONIC = '''\
import time


def wait_for(fh):
    deadline = time.time() + 30.0
    while True:
        if fh.ready():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.25)
'''

_DEADLINE_CHECK_ONLY_CONTINUES = '''\
import time


def wait_for(fh):
    deadline = time.monotonic() + 30.0
    while True:
        if time.monotonic() >= deadline:
            continue
        time.sleep(0.25)
'''

_DEADLINE_COMPUTED_INSIDE_THE_LOOP = '''\
import time


def wait_for(fh):
    while True:
        deadline = time.monotonic() + 30.0
        if fh.ready():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
'''

_DEADLINE_ONLY_BREAKS_A_NESTED_LOOP = '''\
import time


def wait_for(shards):
    deadline = time.monotonic() + 30.0
    while True:
        for s in shards:
            if time.monotonic() >= deadline:
                break
        time.sleep(0.25)
'''

_COMPARED_AGAINST_A_FRESH_READING = '''\
import time


def wait_for(fh):
    started = time.monotonic()
    while True:
        if time.monotonic() >= time.monotonic():
            return False
        time.sleep(0.25)
'''


@pytest.mark.parametrize("src,why", [
    (_WALL_CLOCK_NOT_MONOTONIC, "time.time() can jump; it bounds nothing"),
    (_DEADLINE_CHECK_ONLY_CONTINUES, "a `continue` is not an exit"),
    (_DEADLINE_COMPUTED_INSIDE_THE_LOOP, "recomputed each pass = never expires"),
    (_COMPARED_AGAINST_A_FRESH_READING, "no pre-loop reading is in the compare"),
    (_DEADLINE_ONLY_BREAKS_A_NESTED_LOOP,
     "that break leaves the inner for, not the outer while"),
])
def test_a_near_miss_is_not_a_bound(src, why):
    offs = _offenses(src)
    assert "while" in _kinds(offs), f"{why}\n{offs}"


# (a) THE ACCEPT CASES — a real monotonic deadline, spelled several ways.

_DEADLINE_IN_THE_BODY = '''\
import time


def wait_for(fh):
    deadline = time.monotonic() + 30.0
    while True:
        if fh.ready():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
'''

_DEADLINE_IN_THE_WHILE_TEST = '''\
import time


def wait_for(fh):
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if fh.ready():
            return True
        time.sleep(0.25)
    return False
'''

_ORIGIN_MINUS_NOW = '''\
from time import monotonic, sleep


def wait_for(fh):
    t0 = monotonic()
    while True:
        if fh.ready():
            return True
        if monotonic() - t0 > 30.0:
            break
        sleep(0.25)
    return False
'''

#: The identifiers are deliberately absurd. A name-based ruler ("does it say
#: `deadline`?") passes the two above and fails this one; a structural ruler
#: cannot tell them apart, which is the point.
_RENAMED_BEYOND_RECOGNITION = '''\
import time

_now = time.monotonic


def wait_for(fh):
    zzz = _now() + 30.0
    while True:
        if fh.ready():
            return True
        if _now() >= zzz:
            break
        time.sleep(0.25)
    return False
'''

_INFINITE_FOR_WITH_A_DEADLINE = '''\
import itertools
import time


def wait_for(fh):
    stop_at = time.monotonic() + 30.0
    for _ in itertools.count():
        if fh.ready():
            return True
        if time.monotonic() >= stop_at:
            return False
        time.sleep(0.25)
'''


@pytest.mark.parametrize("src", [
    _DEADLINE_IN_THE_BODY,
    _DEADLINE_IN_THE_WHILE_TEST,
    _ORIGIN_MINUS_NOW,
    _RENAMED_BEYOND_RECOGNITION,
    _INFINITE_FOR_WITH_A_DEADLINE,
])
def test_a_monotonic_deadline_is_a_bound(src):
    offs = _offenses(src)
    assert [o for o in offs if o.kind in ("while", "for")] == [], offs


def test_the_bound_survives_renaming_and_is_not_earned_by_naming():
    """A ruler anyone can defeat by renaming a variable is not a ruler.

    Same loop, two spellings: `deadline`/`time.monotonic` and `zzz`/`_now`.
    Both bounded. And the converse — a variable NAMED `deadline` that holds no
    clock reading buys nothing."""
    assert _offenses(_DEADLINE_IN_THE_BODY) == _offenses(
        _RENAMED_BEYOND_RECOGNITION) == []
    fake = _DEADLINE_IN_THE_BODY.replace("time.monotonic() + 30.0", "30.0")
    assert "while" in _kinds(_offenses(fake)), fake


# (c) THE DECISIVE FALSIFICATION — the REAL shipped function, mutated.

def _real_claim_enter() -> str:
    """`_CheckoutClaim.__enter__` lifted from the shipped gate, as a module.

    Read from the tree rather than transcribed, so this test cannot drift away
    from the function it is making a claim about.
    """
    src = (PROGRAMS / "gate_host_independence_check.py").read_text(
        encoding="utf-8")
    lines = src.splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.strip().startswith("def __enter__"))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].strip().startswith("def __exit__"))
    body = "\n".join(ln[4:] if ln.startswith("    ") else ln
                     for ln in lines[start:end])
    return "import fcntl\nimport time\n\n\n" + body + "\n"


def _drop_block(src: str, marker: str) -> str:
    """Delete the statement containing `marker` and everything indented under
    it — an indentation cut, so it stays honest if the function is reformatted.
    """
    lines = src.splitlines()
    i = next(i for i, ln in enumerate(lines) if marker in ln)
    indent = len(lines[i]) - len(lines[i].lstrip())
    j = i + 1
    while j < len(lines) and (not lines[j].strip() or
                              len(lines[j]) - len(lines[j].lstrip()) > indent):
        j += 1
    return "\n".join(lines[:i] + lines[j:]) + "\n"


def test_the_real_bounded_acquire_is_read_as_bounded():
    """THE ACCEPT CASE, on the actual function, not a paraphrase of it."""
    src = _real_claim_enter()
    assert "time.monotonic()" in src and "deadline" in src, src
    assert _offenses(src) == [], _offenses(src)


def test_removing_the_deadline_from_the_real_function_flags_it_again():
    """Removing every independent bound must restore the polling offense.

    The claim now has an iteration cap as well as a deadline. Removing only
    the clock bound must leave that cap effective. Once the cap is removed,
    either a missing pre-loop reading or a missing expiry branch must redden.
    """
    src = _real_claim_enter()
    assert _offenses(src) == [], "a pre-existing offense cannot earn mutation credit"
    guarded = 'for _ in _wd.loop_guard(f"checkout_claim:{word}", max_iter=max_polls):'
    assert guarded in src, "the independent iteration bound is missing"
    clockless = _drop_block(src, "deadline = ")
    clockless = _drop_block(clockless, "started = time.monotonic()")
    assert _offenses(clockless) == [], "the iteration cap must survive clock removal"
    m1 = clockless.replace(guarded, "while True:")
    assert m1 != clockless and "deadline = " not in m1
    assert "while" in _kinds(_offenses(m1)), \
        f"both the pre-loop reading and iteration cap are gone:\n{m1}"

    expiryless = _drop_block(src, "if time.monotonic() >= deadline:")
    assert _offenses(expiryless) == [], "the iteration cap must survive expiry removal"
    m2 = expiryless.replace(guarded, "while True:")
    assert m2 != expiryless and "if time.monotonic() >= deadline:" not in m2
    assert "time.sleep" in m2 and "while True" in m2, m2
    assert "while" in _kinds(_offenses(m2)), \
        f"both the expiry branch and iteration cap are gone:\n{m2}"


def test_the_shipped_programs_tree_is_watchdog_clean():
    offs = W.scan_programs(PROGRAMS)
    assert offs == [], "\n".join(f"{o.file}:{o.line} [{o.kind}] {o.detail}"
                                 for o in offs)


def test_the_claim_iteration_cap_stops_a_frozen_clock(tmp_path, monkeypatch):
    """Recovered lock-repair control, with a finite falsifier on the old loop.

    Count actual failed acquisitions with a frozen producer clock. An old
    unbounded loop fails on its seventh attempt instead of hanging or needing
    a wall kill. The repaired loop must exhaust its own six-iteration guard.
    """
    from types import SimpleNamespace
    import gate_host_independence_check as G

    attempts = []
    guards = []
    real_guard = G._wd.loop_guard

    def deny_lock(*args):
        attempts.append(args)
        assert len(attempts) <= 6, "the claim exceeded its finite polling budget"
        raise BlockingIOError("held by another driver")

    def record_guard(*args, **kwargs):
        guard = real_guard(*args, **kwargs)
        guards.append(guard)
        return guard

    monkeypatch.setattr(G, "time", SimpleNamespace(
        monotonic=lambda: 1000.0, sleep=lambda seconds: None))
    monkeypatch.setattr(G.fcntl, "flock", deny_lock)
    monkeypatch.setattr(G._wd, "loop_guard", record_guard)
    claim = G._CheckoutClaim(tmp_path, True, wait_s=1.0, lock_root=tmp_path)
    with claim as result:
        assert result.held is False
        assert "another driver held a conflicting claim" in result.why
    assert len(guards) == 1 and guards[0].reason == "max_iter"
    assert len(attempts) == guards[0].iterations == guards[0].max_iter == 6


def test_the_claim_still_grants_a_free_lock(tmp_path):
    import gate_host_independence_check as G

    with G._CheckoutClaim(tmp_path, True, wait_s=1.0, lock_root=tmp_path) as claim:
        assert claim.held is True and claim.why == "held"
    assert claim._fh is None


# ══ the truncated-window rule ══════════════════════════════════════════════



_SNIFF = '''\
def _is_probably_binary(data):
    return b"\\x00" in data[:8192]
'''

_SNIFF_TUPLE = '''\
def _is_probably_binary(data):
    return data[:8192].startswith((b"\\x00", b"\\xff\\xfe"))
'''

#: THE SAME SHAPE WITH A WORD FOR A NEEDLE. Byte-identical window, byte-
#: identical search; the needle is something an author writes, so a miss here
#: IS a claim that nothing was declared, and it stays a finding.
_DECLARATION_IN_A_WINDOW = '''\
def declared(data):
    return b"ENFORCEMENT" in data[:8192]
'''

_TEXT_DECLARATION_IN_A_WINDOW = '''\
def declared(text):
    return "ENFORCEMENT" in text[:8192]
'''
