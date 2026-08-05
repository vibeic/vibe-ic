"""`_signoff_regen` must cover the PSM/SI sign-off producers, not just STA.

THE DEFECT
==========
`_signoff_regen(artifact, layout)` already exists in `phase3_one_shot_runner`
and already carries the reasoning: a phase-3 sign-off artefact that EXISTS but
predates the layout it claims to describe characterises a DIFFERENT design, so
a guard that asks only `not <artifact>.is_file()` re-uses the previous run's
numbers for a layout they were never computed on. That change converted RC
extraction and every STA artefact (9 call sites) — and stopped there.

Four producers in the same `run()` kept the bare existence guard:

    Step 24/25  IR drop + EM   `_emit_ir_em_reports`
    Step 26     antenna        `_emit_antenna_report`
    Step 27     SI crosstalk   `_emit_si_crosstalk_report`
    Step 27     MCF-bounded SI `si_mcf_sta.py run`

MEASURED, on a real phase-3 tree that had been re-routed once. The artefacts
split into exactly two cohorts along that line:

    19:51  <top>.spef, sta_spef_based.rpt, sta_mcorner_ocv.rpt, drc_signoff.rpt
             -> the `_signoff_regen`-guarded set, correctly refreshed
    19:28  ir_drop.rpt, em.rpt, antenna.rpt, si_crosstalk.rpt, si_mcf_sta.json
             -> the bare-`.is_file()` set, never refreshed

The routed DEF the 19:51 cohort describes carries 663 components / 348 nets.
The PSM log inside the 19:28 `ir_drop.rpt` states, in its own captured stdout,
that it read a DEF of 622 components / 376 nets. The flow reported the power,
reliability and crosstalk axes of a layout it had not analysed, and Steps 25,
26 and 33 were PASSING on it.

The MCF axis is the loudest case because a downstream gate then MISATTRIBUTES
the staleness. `si_mcf_sta_check` re-derives the expected Cc*MCF fold from
whatever sits at the SPEF path NOW and compares it to the bounded SPEF this
producer emitted earlier. With the two files from different extractions the
recount finds 314 setup / 214 hold nets "wrong" and reports
`FOLD_NOT_APPLIED` — a DESIGN defect, "the emitter dropped the fold" — for
what is an unmatched artefact pair. Re-emitting the bounded SPEF from the
current original, changing NOTHING else, takes that gate from FAIL (259 setup
/ 179 hold recount violations) to PASS (0 / 0) with its denominator RISING
from 507 to 558 proofs.

WHAT THIS TEST PINS
===================
Forward (fails against the byte-identical pre-fix file):
  * each of the four producer guards routes through `_signoff_regen`.

Reverse (must STILL pass — these are what catch a "fix" that reaches green by
widening rather than by dating):
  * `_signoff_regen` still DECLINES a fresh artefact. Deleting the guards, or
    replacing them with an unconditional regenerate, would satisfy the forward
    assertion while re-running PSM/OpenSTA on every invocation.
  * the 9 pre-existing extraction/STA call sites still route through it.
  * the fail-closed semantics (missing / unreadable -> regenerate) are intact.

chip-AGNOSTIC: source-shape assertions plus tmp-path files with no design,
PDK, vendor, node or corner literal anywhere.
"""
import ast
import os
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROGRAMS = Path(__file__).resolve().parent.parent
RUNNER_SRC = PROGRAMS / "phase3_one_shot_runner.py"

#: producer -> a token that appears in the guarded BODY, never in the guard.
#: Keyed on the producer actually invoked so the assertion survives any
#: renaming of the local report variables.
_PRODUCERS = {
    "IR drop + EM (Step 24/25)": "_emit_ir_em_reports(",
    "antenna (Step 26)": "_emit_antenna_report(",
    "SI crosstalk (Step 27)": "_emit_si_crosstalk_report(",
    "MCF-bounded SI STA (Step 27)": "si_mcf_sta.py",
}

#: the call sites the original `_signoff_regen` change already converted. If a
#: later edit drops them the disease returns on the axes it was fixed for.
_MIN_EXISTING_SIGNOFF_REGEN_SITES = 9


@lru_cache(maxsize=1)
def _guards():
    """((guard_source, body_source), ...) for every `if` in the runner.

    `ast.unparse`, not `ast.get_source_segment`: the latter re-splits the whole
    file per call and this module is ~34k lines with thousands of `if` nodes
    (quadratic — minutes). `unparse` is also EXACT where a line slice is a
    superset, so a neighbouring statement on the same line cannot leak a
    `_signoff_regen` token into a guard that does not contain one.
    """
    src = RUNNER_SRC.read_text(errors="ignore")
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.If):
            continue
        out.append((ast.unparse(node.test),
                    "\n".join(ast.unparse(st) for st in node.body)))
    return tuple(out)


@pytest.mark.parametrize("label,body_token", sorted(_PRODUCERS.items()))
def test_producer_guard_routes_through_signoff_regen(label, body_token):
    """FORWARD control — fails against the pre-fix file.

    A sign-off producer whose guard cannot tell a stale report from a fresh one
    will hand the next gate the previous layout's numbers.
    """
    guarding = [t for t, b in _guards() if body_token in b]
    assert guarding, (
        f"{label}: no `if` in {RUNNER_SRC.name} guards a call to "
        f"{body_token!r} — this test can no longer see the producer it pins")
    assert any("_signoff_regen" in t for t in guarding), (
        f"{label}: its guard(s) {guarding!r} decide on artefact EXISTENCE. "
        f"Existence is adjacent to freshness: the report is there, and it "
        f"describes a different layout. Route the guard through "
        f"`_signoff_regen(<artefact>, <the layout/SPEF it is derived from>)`.")


def test_existing_extraction_and_sta_sites_still_guarded():
    """REVERSE control — must pass before AND after.

    Catches a 'fix' that satisfies the forward assertion by deleting guards.
    """
    n = RUNNER_SRC.read_text(errors="ignore").count("_signoff_regen(")
    # +1 for the `def _signoff_regen(` definition itself.
    assert n >= _MIN_EXISTING_SIGNOFF_REGEN_SITES + 1, (
        f"only {n} `_signoff_regen(` occurrences remain; the extraction/STA "
        f"call sites this predicate was introduced for have been dropped")


def _touch(p: Path, mtime: float) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    os.utime(p, (mtime, mtime))
    return p


def test_signoff_regen_declines_a_fresh_artifact(tmp_path):
    """REVERSE control — must pass before AND after.

    The load-bearing half. An 'always regenerate' guard would pass the forward
    test and re-run PSM/OpenSTA on every invocation; a report NEWER than the
    layout is the one case the predicate must answer False.
    """
    import phase3_one_shot_runner as R
    layout = _touch(tmp_path / "design.def", 1_000.0)
    fresh = _touch(tmp_path / "report.rpt", 2_000.0)
    assert R._signoff_regen(fresh, layout) is False


def test_signoff_regen_catches_stale_and_fails_closed(tmp_path):
    """REVERSE control — must pass before AND after."""
    import phase3_one_shot_runner as R
    layout = _touch(tmp_path / "design.def", 2_000.0)
    stale = _touch(tmp_path / "stale.rpt", 1_000.0)
    assert R._signoff_regen(stale, layout) is True
    assert R._signoff_regen(tmp_path / "absent.rpt", layout) is True
    # No layout to date against: leave an existing artefact alone.
    assert R._signoff_regen(stale, tmp_path / "no_such.def") is False
