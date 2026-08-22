"""vibe-ic#1075 — a loop corpus that expands to ZERO must leave a verdict behind.

THE MEASUREMENT
===============
#957 made a loop-driven gate state its denominator, and the landing gate has
printed this on every run since:

    repo_hygiene_gates: loop corpus "published cells carrying a routed DEF"
      expanded over 1 item(s) -> 3 of 74 declared gate(s); those verdicts cover
      1 item(s), NOT the corpus at large

Three of 74 gates decided over a population of ONE. The disclosure is correct
and it is not what this file repairs. What it repairs is the case one step
further down, which the roll-up itself names:

    "expanded over 0 item(s) — it declared 0 gate(s) and NOTHING was checked
     over it; no gate in this run reports that, because none exists"

At ZERO the loop body runs zero times, so zero gates are declared, so the run
costs NOTHING and the script's exit status is unaffected. A corpus that
silently emptied — a glob that stopped matching, a corpus withdrawn from
publication — was therefore indistinguishable from a corpus with nothing wrong
in it.

THIS IS NOT HYPOTHETICAL. Measured on `origin/main`:

    git ls-files -- 'benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def'   -> 1
    the same selector on the withdrawal branch (PR #1028)                  -> 0

So the corpus those three gates stand on is one publishing decision away from
empty, and at empty it took no verdict with it.

WHAT THE REPAIR IS, AND WHAT IT DELIBERATELY IS NOT
===================================================
An empty corpus now records ONE synthetic gate in the `NOT_CHECKED` state.

NOT_CHECKED is not a new tier invented here — `_gate_dispatch.sh` already
defines it as "the gate REFUSED — it could not look (rc 2)", which is exactly
the condition of a gate with nothing to look at.

It is deliberately NOT a FAIL. An empty corpus is not a broken design, and
calling it one would turn every host without published evidence red for a
reason that is about the corpus rather than the code. But it is never a silent
PASS: `NOT_CHECKED` is never folded into `passed` by the roll-up.

NOTHING HERE TYPES A CORPUS SIZE, for the reason #957 gives: a test carrying a
literal count is the next hand-maintained fact to drift.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parents[4]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"


def _drive(body: str) -> str:
    """Source the real dispatcher library and run `body` against it."""
    script = textwrap.dedent(f"""
        HERE="{_REPO}/tools/ci"; ROOT="{_REPO}"; PLUGIN="{_REPO}"; PG="{_REPO}"
        . "{_LIB}"
        {body}
    """)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return p.stdout + p.stderr


def test_the_library_is_where_we_think_it_is():
    assert _LIB.is_file(), f"{_LIB} — the dispatcher this file pins is gone"


# ── the repair ──────────────────────────────────────────────────────────────

def test_an_empty_corpus_records_a_gate():
    out = _drive("""
        _body(){ :; }
        gate_dispatch_over "an empty corpus" _body true
        echo "LABELS=${#GATE_LABELS[@]}"
        echo "STATES=${GATE_STATES[*]}"
    """)
    assert "LABELS=1" in out, (
        f"an empty corpus declared no gate, so nothing in the run speaks for "
        f"it — the exact condition #1075 is about:\n{out}")
    assert "STATES=NOT_CHECKED" in out, out


def test_the_empty_corpus_gate_is_not_a_pass():
    """A silent PASS is the defect; NOT_CHECKED is never folded into passed."""
    out = _drive("""
        _body(){ :; }
        gate_dispatch_over "an empty corpus" _body true
        echo "STATES=${GATE_STATES[*]}"
    """)
    assert "PASS" not in out.split("STATES=")[-1], (
        f"an empty corpus must not record a PASS:\n{out}")


def test_the_empty_corpus_says_so_out_loud():
    out = _drive("""
        _body(){ :; }
        gate_dispatch_over "published cells carrying a routed DEF" _body true
    """)
    assert "EMPTY CORPUS" in out and "routed DEF" in out, (
        f"the empty corpus was recorded but not disclosed:\n{out}")


def test_the_parallel_records_stay_aligned():
    """Every per-gate array is read positionally by the roll-up.

    The first draft of this repair appended to `GATE_CORPUS_OF`, which does not
    exist; the arrays went out of step by one and the roll-up would have
    attributed each gate's state to the wrong label. Pinned so the next
    addition cannot repeat it.
    """
    out = _drive("""
        _body(){ :; }
        gate_dispatch_over "empty one" _body true
        run "a real gate" "$PWD" true
        for a in GATE_LABELS GATE_STATES GATE_SECONDS \
                 GATE_ITEM_CORPUS GATE_ITEM_IDX GATE_ITEM_TOTAL; do
          eval "echo \\"$a=\\${#$a[@]}\\""
        done
    """)
    lens = {ln.split("=")[0]: ln.split("=")[1]
            for ln in out.splitlines() if "=" in ln and ln.startswith("GATE_")}
    assert lens, f"could not read array lengths:\n{out}"
    assert len(set(lens.values())) == 1, (
        f"per-gate arrays are out of step, so the roll-up would misattribute "
        f"states to labels: {lens}")


# ── paired guards: the non-empty path must be untouched ─────────────────────

def test_a_non_empty_corpus_gains_no_synthetic_gate():
    """The repair must not inflate a corpus that actually had items."""
    out = _drive("""
        _body(){ run "gate for $1" "$PWD" true; }
        gate_dispatch_over "one item" _body printf 'x\\n'
        echo "LABELS=${#GATE_LABELS[@]}"
        echo "STATES=${GATE_STATES[*]}"
    """)
    assert "LABELS=1" in out, f"a 1-item corpus must declare exactly 1 gate:\n{out}"
    assert "STATES=PASS" in out, out
    assert "EMPTY CORPUS" not in out, out


def test_a_failed_producer_is_still_told_apart_from_an_empty_corpus():
    """"the producer broke" must not become "the corpus is empty" (#957).

    The repair fires only when the producer SUCCEEDED and printed nothing; a
    producer that failed keeps its own louder disclosure.
    """
    out = _drive("""
        _body(){ :; }
        gate_dispatch_over "a broken producer" _body false
    """)
    assert "CORPUS PRODUCER FAILED" in out, out
    assert "EMPTY CORPUS" not in out, (
        f"a failed producer was reported as an empty corpus, collapsing the "
        f"distinction #957 drew:\n{out}")


# ── the always-fires mutant must kill something ─────────────────────────────

def test_the_guard_is_reachable_at_all(tmp_path):
    """If `gate_dispatch_over` stopped being callable this file would pass by
    never exercising anything; assert the primitive still runs a body."""
    out = _drive("""
        _body(){ echo "BODY_RAN:$1"; }
        gate_dispatch_over "two items" _body printf 'a\\nb\\n'
    """)
    assert out.count("BODY_RAN:") == 2, (
        f"the dispatcher no longer runs its body per item, so every other "
        f"assertion here is vacuous:\n{out}")
