"""#573 — a DRV check that was ASKED FOR and printed no table read as clean.

`extract_drv` reported `violations: {}` for two different facts and the R5 rule
could not tell them apart:

    a table with zero violator rows   the check ran over a real population and
                                      found nothing            -> a genuine zero
    no table at all                   the check had nothing to
                                      report ON                -> UNMEASURED

MEASURED on `caravel_user_project x sky130A`: the sign-off SDC declares
`set_max_fanout 16 [current_design]`, `report_check_types -max_fanout
-violators` prints no fanout table whatsoever, and the design's tie-off net
carries 30 loads against that limit.

The cause is in OpenSTA and was confirmed at source level — `CheckFanouts::
checkPin` excludes a pin when `sim()->isConstant(pin)`, and `Sim::
ensureConstantFuncPins()` records constant-function pins ONCE behind
`const_func_pins_valid_`, which only `Sim::clear()` resets. So a tie cell linked
in from disk is excluded and a structurally identical one created after
`link_design` is checked. Proven by a positive control inside ONE session: the
post-link tie reports `16 20 -4 (VIOLATED)` while the linked-in one is absent,
with `slew_max == 0.000000` on both.

CORPUS, swept before landing — 97 STA reports under `benchmark-data/`:

    queried                36
    not queried            61
    with violations        17
    requested, no table    12   (max_slew 6, max_capacitance 6)

so the shape is not specific to max_fanout; it is what any DRV kind looks like
when the tool has nothing to report on. `max_fanout` is 0 there only because
those runs predate the check-types marker.

DISCLOSED, NOT BLOCKING. The cause is in the tool, so blocking would fail every
design with a tie-off — a gate people switch off rather than answer. The fix
belongs in `vibeic/OpenSTA`; until it lands, the honest record is that the limit
was declared, the check was requested, and nothing was measured.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "sta_corner_record_completeness_check.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "sta_corner_record_completeness_check_probe", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sta_corner_record_completeness_check_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

_MARKER = ("SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew "
           "min_pulse_width max_capacitance max_fanout\n")

_SLEW_TABLE = """\
max slew
Pin                    Limit  Slew  Slack
-----------------------------------------
u1/A                   1.500  0.20  1.30
"""

_FANOUT_TABLE_EMPTY = """\
max fanout
Pin                 Limit Fanout Slack
--------------------------------------
"""

_FANOUT_TABLE_VIOLATED = """\
max fanout
Pin                 Limit Fanout Slack
--------------------------------------
tie_drv/LO             16     30   -14 (VIOLATED)
"""


# ── the discriminator ────────────────────────────────────────────────────────
def test_a_requested_kind_with_no_table_is_named():
    """The defect: the marker says max_fanout was asked for, no table appears."""
    res = M.extract_drv(_MARKER + _SLEW_TABLE)
    assert "max_fanout" in res["kinds_without_table"], res
    assert res["violations"] == {}, res


def test_a_present_but_empty_table_is_NOT_named():
    """The accept case, and the whole point of the distinction.

    A table that printed with zero violator rows IS a genuine zero — the check
    ran over a real population. Flagging it would make the finding meaningless
    by firing on every clean design.
    """
    res = M.extract_drv(_MARKER + _SLEW_TABLE + _FANOUT_TABLE_EMPTY)
    assert "max_fanout" not in res["kinds_without_table"], res


def test_a_table_with_a_violation_is_NOT_named():
    res = M.extract_drv(_MARKER + _SLEW_TABLE + _FANOUT_TABLE_VIOLATED)
    assert "max_fanout" not in res["kinds_without_table"], res
    assert res["violations"].get("max_fanout") == 1, res


def test_nothing_queried_names_nothing():
    """No marker and no tables — `queried` False, which R5 already fails on as
    R5_DRV_UNQUERIED. The new field must not double-report it."""
    res = M.extract_drv("some unrelated report body\n")
    assert res["queried"] is False
    assert res["kinds_without_table"] == [], res


# ── the finding must reach a reader, and must not block ──────────────────────
def _axis(silent):
    return [{
        "axis": "setup", "report": "sta_ss.rpt",
        "drv": {"queried": True, "kinds_without_table": silent,
                "violations": {}, "total": 0, "kinds_queried": ["max_fanout"]},
    }]


def test_the_finding_is_emitted_and_the_rule_is_not_a_blocker():
    """DISCLOSED, not blocking — asserted on BOTH halves.

    The rule name must be absent from the ordered blocking list (so it cannot
    fail a landing) AND the text must be produced (so it is not silent). A
    disclosure that blocks nothing and says nothing is the defect, not the fix.
    """
    src = PROG.read_text(encoding="utf-8")
    ordered = src.split("ordered = [r for r in", 1)[1].split("]", 1)[0]
    assert "R5_DRV_KIND_UNMEASURED" not in ordered, (
        "the disclosure became a blocker; every design with a tie-off would "
        "fail it, and a gate that must be bypassed enforces nothing")
    body = src.split("# ---- R5:", 1)[1].split("\n    ordered", 1)[0]
    assert "R5_DRV_KIND_UNMEASURED" in body, "the rule is never appended"
    assert "printed no table" in body, "the finding text never states the fact"


def test_the_finding_precedes_the_violation_branch():
    """A record can carry real max_slew violations AND a silently absent
    max_fanout table. Reporting only the former lets a reader conclude the rest
    was checked and clean, which is the inference this whole issue is about."""
    src = PROG.read_text(encoding="utf-8")
    body = src.split("# ---- R5:", 1)[1].split("\n    ordered", 1)[0]
    assert body.index("R5_DRV_KIND_UNMEASURED") < body.index("R5_DRV_VIOLATION"), (
        "the unmeasured disclosure is emitted after the violation branch, so a "
        "record with both reports only the violation")


# ── the corpus number, so a regression in the parser is visible ──────────────
@needs_corpus
def test_the_shape_exists_in_the_corpus():
    """Guards against a parser change that makes `kinds_without_table` always
    empty — which would satisfy every test above except this one.

    Skipped when the PUBLISHED corpus is not readable here.

    The old guard was `(<repo>/benchmark-data).is_dir()`, and that stopped being
    the right question when the results moved to `vibeic/benchmark-data`: the
    directory of that name is still here — it carries the design INPUTS — so the
    guard was satisfied while there was not one STA report to read, and the
    sweep below then reported `0 > 0`, i.e. a regression in the parser. There is
    no regression; there is nothing to parse. `@needs_corpus` asks whether a
    published CELL is readable, which is what this test needs, and renders a "no"
    as a skip naming the corpus instead of as a finding about `extract_drv`.
    """
    # Still never a home directory: `corpus_root()` reads its location from THIS
    # file plus `VIBE_IC_BENCHMARK_DATA`, so the shipped-path portability gate
    # keeps holding and no checkout is hard-coded into the source.
    root = corpus_root()
    assert root is not None, "@needs_corpus should have skipped before this point"
    seen = 0
    for p in root.rglob("sta*.rpt"):
        try:
            res = M.extract_drv(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if res["kinds_without_table"]:
            seen += 1
    assert seen > 0, (
        "no report in the corpus shows a requested-but-untabled DRV kind; "
        "measured at 12 when this landed, so either the corpus changed or the "
        "predicate stopped firing")
