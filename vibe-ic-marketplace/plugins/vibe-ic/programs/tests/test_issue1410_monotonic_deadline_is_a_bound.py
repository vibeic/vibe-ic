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
out, must redden. That is what separates "it learned to see the bound" from
"it learned to ignore that function".

chip-AGNOSTIC: pure AST shapes, no IC / PDK / vendor content.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import loop_watchdog_compliance_check as W          # noqa: E402
import declaration_searched_only_inside_a_truncated_window as D  # noqa: E402

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
    """TAKE THE DEADLINE OUT AND THE SCANNER MUST SPEAK AGAIN.

    This is what proves the scanner learned to SEE the bound rather than to
    ignore this function. Two mutations, each removing a different half of the
    bound, and each must redden:
      1. the pre-loop reading is deleted (nothing was computed before the loop);
      2. the whole expiry branch is deleted (the loop retries forever).
    """
    src = _real_claim_enter()

    m1 = "\n".join(ln for ln in src.splitlines()
                   if "deadline = time.monotonic()" not in ln)
    assert "deadline = time.monotonic()" not in m1
    assert "while" in _kinds(_offenses(m1)), \
        f"the pre-loop reading is gone and the loop is unbounded:\n{m1}"

    m2 = _drop_block(_drop_block(src, "deadline = time.monotonic()"),
                     "if time.monotonic() >= deadline:")
    assert "deadline" not in m2, m2
    assert "time.sleep" in m2 and "while True" in m2, m2
    assert "while" in _kinds(_offenses(m2)), \
        f"the expiry branch is gone and the loop retries forever:\n{m2}"


def test_the_shipped_programs_tree_is_watchdog_clean():
    offs = W.scan_programs(PROGRAMS)
    assert offs == [], "\n".join(f"{o.file}:{o.line} [{o.kind}] {o.detail}"
                                 for o in offs)


# ══ the truncated-window rule ══════════════════════════════════════════════

def _window_rc(src: str):
    """Run the rule over a one-file tree and return (rc, stdout)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()
        progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
        progs.mkdir(parents=True)
        (progs / "cand.py").write_text(src, encoding="utf-8")
        inv = root / "inv.json"
        inv.write_text('{"known": []}', encoding="utf-8")
        r = subprocess.run([sys.executable, str(WINDOW_PROG),
                            "--root", str(root), "--inventory", str(inv)],
                           capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout + r.stderr


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


def test_a_content_type_sniff_is_not_a_declaration_search():
    for src in (_SNIFF, _SNIFF_TUPLE):
        rc, out = _window_rc(src)
        assert rc == 0, out
        assert "content-type sniffs:       1" in out, out


@pytest.mark.parametrize("src", [_DECLARATION_IN_A_WINDOW,
                                 _TEXT_DECLARATION_IN_A_WINDOW])
def test_a_declaration_searched_in_a_window_is_still_refused(src):
    """THE FALSIFICATION FOR THE SNIFF: change the needle from a byte class to
    a word and the identical window is a finding again. The exemption is the
    needle's, not the file's and not the window's."""
    rc, out = _window_rc(src)
    assert rc == 1, out
    assert "8192" in out, out


def test_the_real_sniff_and_its_mutation():
    """The shipped `_is_probably_binary`, read from the tree, and the same
    function with its needle turned into a word."""
    src = (PROGRAMS / "flow_output_substance.py").read_text(encoding="utf-8")
    fn = re.search(r"def _is_probably_binary.*?\n\n", src, re.S)
    assert fn, "the measured site is gone; re-measure before editing this test"
    real = fn.group(0)
    assert _window_rc(real)[0] == 0, real
    mutated = real.replace('b"\\x00"', 'b"ENFORCEMENT"')
    assert mutated != real
    assert _window_rc(mutated)[0] == 1, mutated


def test_the_shipped_tree_still_passes_the_window_rule():
    root = PROGRAMS.parents[3]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(WINDOW_PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
