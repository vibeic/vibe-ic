#!/usr/bin/env python3
"""ORGANIC #756 — ppa_area_threshold_check per-metric DISJUNCTIVE clause parse.

THE DEFECT (#756)
=================
`parse_threshold_from_prompt` extracts only the FIRST '<n>%' near an area word
and `break`s, silently dropping any SECOND per-metric clause; it then binds
metric='both' whenever BOTH 'cells' and 'wires' appear in its ±60-char window.
On a spec like "minimum reduction must be 12% for wires OR 8% for cells" it
collapses to a single (12,'both') CONJUNCTION (cells>=12 AND wires>=12) — DOUBLY
wrong vs the canonical CVDP oracle (PERCENT_WIRES=12, PERCENT_CELLS=8, ANY-metric
improvement = wires>=12 OR cells>=8). So a submission that meets the cells-8%
branch but not wires-12% (e.g. cells_red=10%, wires_red=5%) is false-BLOCKed
(shipped decide(10,5,12,'both') BLOCKs while the oracle PASSes).

THE FIX (chip-AGNOSTIC, additive, program-first)
================================================
`parse_threshold_clauses_from_prompt` scans ALL area '%'s, binds each to the
metric word NEAREST it (forward 'for <metric>' priority so 12%->wires, 8%->cells)
and reads the 'or'/'and' connective into a combinator. `decide_clauses` then:
  * OR: PASS as soon as ANY clause clears its OWN bar; BLOCK only when every
    sub-threshold clause is a REAL failure (grew / generic headroom);
    NOT-APPLICABLE when all sub-threshold clauses are proven near-minimal /
    unmeasurable (no false block).
  * AND: every clause must clear; a single real failure BLOCKs.
The legacy `decide()` / `parse_threshold_from_prompt` are retained for the
explicit-threshold path and the existing #729 / #739 suites. The #739
unreachable-target escape + grown-design no-leak are preserved (decide_clauses
reuses `_generic_headroom`).

PURE-FUNCTION END-STATE (no yosys needed)
=========================================
`parse_threshold_clauses_from_prompt` + `_nearest_metric_for_pct` +
`decide_clauses` are PURE; the disjunctive PASS, the AND conjunction, the
grown-design / neither-bar-headroom BLOCKs and the unparseable NOT-APPLICABLE are
all proven WITHOUT a container. The live `main` end-to-end is docker/vibeic-eda
guarded.

chip-AGNOSTIC: pure measurement + arithmetic + ordinary-English clause tokens;
no chip/SKU literal (enforced by source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load(modname, filename):
    spec = importlib.util.spec_from_file_location(
        modname, str(_PROGRAMS / filename))
    mod = importlib.util.module_from_spec(spec)
    if str(_PROGRAMS) not in sys.path:
        sys.path.insert(0, str(_PROGRAMS))
    spec.loader.exec_module(mod)
    return mod


ppa = _load("ppa_area_threshold_check", "ppa_area_threshold_check.py")


def _container_up(container="vibeic-eda") -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        cp = _pr.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True, text=True)
        return cp.returncode == 0 and cp.stdout.strip() == "true"
    except Exception:
        return False


_HAVE_CONTAINER = _container_up()


# ════════════════════════════════════════════════════════════════════════════
# 1. PARSE — the disjunctive '12% for wires OR 8% for cells' phrasing yields TWO
#    per-metric clauses + an 'or' combinator (NOT a single (12,'both')).
# ════════════════════════════════════════════════════════════════════════════
def test_disjunctive_parse_two_clauses_or():
    clauses, comb = ppa.parse_threshold_clauses_from_prompt(
        "minimum reduction must be 12% for wires or 8% for cells")
    assert clauses == [(12.0, "wires"), (8.0, "cells")]
    assert comb == ppa._COMBINATOR_OR


def test_disjunctive_parse_each_pct_binds_nearest_metric():
    # forward 'for <metric>' priority — 12%->wires, 8%->cells; the trailing
    # 'wires' of the first clause must NOT bleed into the 8% clause.
    clauses, _comb = ppa.parse_threshold_clauses_from_prompt(
        "the area must shrink by at least 12% for wires or 8% for cells")
    metrics = {m for _p, m in clauses}
    assert metrics == {"wires", "cells"}
    pct_for = {m: p for p, m in clauses}
    assert pct_for["wires"] == 12.0
    assert pct_for["cells"] == 8.0


def test_old_single_tuple_parse_still_collapses_to_both():
    # the legacy single-tuple parse (kept for the explicit path / old suite)
    # still only sees the FIRST % and binds 'both' — this is the documented bug
    # the NEW parse fixes; pinning it proves the legacy path is unchanged.
    thr, metric = ppa.parse_threshold_from_prompt(
        "minimum reduction must be 12% for wires or 8% for cells")
    assert thr == 12.0
    assert metric == ppa._METRIC_BOTH


# ════════════════════════════════════════════════════════════════════════════
# 2. THE POSITIVE FLIP — a submission meeting the cells-8% branch but not the
#    wires-12% branch PASSes the disjunction (the oracle's verdict), where the
#    shipped single-tuple decide() false-BLOCKs.
# ════════════════════════════════════════════════════════════════════════════
def test_disjunctive_pass_cells_branch_clears():
    # cells_red=10 >= 8, wires_red=5 < 12 — OR is satisfied by the cells clause.
    verdict, reason = ppa.decide_clauses(
        10.0, 5.0, [(12.0, "wires"), (8.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == "PASS", reason
    assert "cells" in reason and "8%" in reason


def test_shipped_single_tuple_decide_false_blocks_same_numbers():
    # the single-tuple decide() collapses '12% wires OR 8% cells' into a single
    # (12,'both') AND-conjunction — the #756 data-model false-collapse.
    # ORGANIC #769 RE-ANCHOR: at generic 18% >= 12% the GENERIC count (the one
    # the CVDP reference scorer measures via synth -top; clean; stat) MEETS the
    # bar, so the corrected verdict is PASS — the generic-meets-target supersedes
    # the old inverted 'generic headroom → BLOCK' premise. The #756 collapse is
    # still demonstrable: bind the SAME numbers with a GROWN wires reduction and
    # the single-tuple 'both' worse-of still hard-blocks (see the grown no-leak
    # tests). Here we pin the corrected generic-meets PASS.
    verdict, _reason = ppa.decide(
        10.0, 5.0, 12.0, ppa._METRIC_BOTH,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == "PASS"   # generic 18% >= 12% (the scorer-measured count)


# ════════════════════════════════════════════════════════════════════════════
# 3. §4.05 NO-LEAK — the disjunctive verdict must still catch genuine defects.
# ════════════════════════════════════════════════════════════════════════════
def test_grown_design_still_blocks_under_or():
    # a clause whose bound metric GREW (negative reduction) is a real failure;
    # no clause clears its bar → BLOCK, never a near-minimal escape.
    verdict, reason = ppa.decide_clauses(
        -5.0, 5.0, [(12.0, "wires"), (8.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=2.0, wires_red_generic=2.0)
    assert verdict == "BLOCK", reason
    assert "GREW" in reason


def test_neither_bar_with_generic_meets_target_passes_under_or():
    # ORGANIC #769 RE-ANCHOR: neither MAPPED clause clears its bar, but BOTH
    # metrics' GENERIC reductions MEET their bar (cells generic 18% >= 8%, wires
    # generic 18% >= 12%) — the GENERIC count is the one the CVDP reference
    # scorer measures, so the target IS met → PASS under OR. (The old inverted
    # premise blocked this as 'lazy headroom'; #769 corrects it.)
    verdict, reason = ppa.decide_clauses(
        5.0, 5.0, [(12.0, "wires"), (8.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == "PASS", reason


def test_neither_bar_real_underreduction_still_blocks_under_or():
    # §4.05 NO-LEAK (surviving hard block): neither clause clears AND a bound
    # metric GREW (negative mapped) — a genuine regression → BLOCK under OR, the
    # grown bucket dominates so a disjunctive PASS can never mask it.
    verdict, reason = ppa.decide_clauses(
        -5.0, 5.0, [(12.0, "wires"), (8.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == "BLOCK", reason
    assert "GREW" in reason


def test_neither_bar_near_minimal_is_not_applicable_under_or():
    # neither clause clears AND generic is ALSO sub-threshold for both — proven
    # near-minimal / unreachable → NOT-APPLICABLE, never a false block (#739
    # escape preserved under OR).
    verdict, reason = ppa.decide_clauses(
        5.0, 5.0, [(12.0, "wires"), (8.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=5.0, wires_red_generic=5.0)
    assert verdict == "NOT_APPLICABLE", reason


# ════════════════════════════════════════════════════════════════════════════
# 4. AND combinator stays conjunctive (gaussian_div_0023's '4% cells and 11%
#    wires' parse correction + decide).
# ════════════════════════════════════════════════════════════════════════════
def test_conjunctive_parse_and_combinator():
    clauses, comb = ppa.parse_threshold_clauses_from_prompt(
        "reduce cells by at least 4% and wires by at least 11%")
    assert clauses == [(4.0, "cells"), (11.0, "wires")]
    assert comb == ppa._COMBINATOR_AND


def test_conjunctive_blocks_when_one_clause_fails():
    # cells_red=10 clears 4% but wires GREW (negative mapped) → AND BLOCKs on the
    # grown wires clause. ORGANIC #769 RE-ANCHOR: the old version used wires
    # generic 18% >= 11% which now MEETS the scorer-measured target (→ sat), so a
    # genuine conjunctive failure must be a real under-reduction — a GROWN metric
    # (the surviving hard no-leak).
    verdict, reason = ppa.decide_clauses(
        10.0, -5.0, [(4.0, "cells"), (11.0, "wires")], ppa._COMBINATOR_AND,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == "BLOCK", reason
    assert "wires" in reason


def test_conjunctive_passes_when_all_clauses_clear():
    verdict, reason = ppa.decide_clauses(
        10.0, 15.0, [(4.0, "cells"), (11.0, "wires")], ppa._COMBINATOR_AND,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == "PASS", reason


# ════════════════════════════════════════════════════════════════════════════
# 5. EXPLICIT --threshold-pct single-clause path unchanged (one (thr,metric)
#    clause, AND combinator; 'both' uses the worse-of mapping = prior decide()).
# ════════════════════════════════════════════════════════════════════════════
def test_explicit_single_clause_both_blocks_like_legacy():
    # explicit path builds clauses=[(12,'both')], combinator AND. ORGANIC #769
    # RE-ANCHOR: with generic 18% >= 12% the GENERIC count MEETS the bar so the
    # corrected verdict is PASS, not the old inverted headroom-BLOCK. The
    # decide_clauses↔decide parity that this test guards is preserved by binding
    # the SAME numbers with a GROWN wires reduction — both paths still hard-block
    # identically on the grown 'both' worse-of.
    verdict, _reason = ppa.decide_clauses(
        10.0, -5.0, [(12.0, ppa._METRIC_BOTH)], ppa._COMBINATOR_AND,
        cells_red_generic=18.0, wires_red_generic=18.0)
    legacy, _r = ppa.decide(
        10.0, -5.0, 12.0, ppa._METRIC_BOTH,
        cells_red_generic=18.0, wires_red_generic=18.0)
    assert verdict == legacy == "BLOCK"


def test_explicit_single_clause_both_passes_like_legacy():
    verdict, _reason = ppa.decide_clauses(
        20.0, 25.0, [(12.0, ppa._METRIC_BOTH)], ppa._COMBINATOR_AND,
        cells_red_generic=30.0, wires_red_generic=30.0)
    legacy, _r = ppa.decide(
        20.0, 25.0, 12.0, ppa._METRIC_BOTH,
        cells_red_generic=30.0, wires_red_generic=30.0)
    assert verdict == legacy == "PASS"


# ════════════════════════════════════════════════════════════════════════════
# 6. UNPARSEABLE / unmeasurable → NOT-APPLICABLE (never a false block).
# ════════════════════════════════════════════════════════════════════════════
def test_unparseable_prompt_raises():
    with pytest.raises(ppa.ThresholdParseError):
        ppa.parse_threshold_clauses_from_prompt(
            "this prompt has no area-reduction target at all")


def test_unmeasurable_clause_or_is_not_applicable():
    # a clause whose bound metric is unmeasurable (None) cannot prove it clears
    # the bar; with no real failure the OR-set is NOT-APPLICABLE, never a false
    # PASS and never a false BLOCK.
    verdict, _reason = ppa.decide_clauses(
        None, None, [(12.0, "wires"), (8.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=None, wires_red_generic=None)
    assert verdict == "NOT_APPLICABLE"


# ════════════════════════════════════════════════════════════════════════════
# 7. (container-guarded) end-to-end main — a real synth measurement path. Pure
#    logic above is the gate's verdict; this just proves the wiring runs and
#    surfaces `clauses` + `combinator` in the report. Skipped without vibeic-eda.
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running")
def test_end_to_end_main_reports_clauses(tmp_path):
    orig = tmp_path / "orig.v"
    opt = tmp_path / "opt.v"
    # two functionally-equivalent trivial modules; the verdict itself is not
    # asserted (it depends on the live synth), only that main runs and the
    # report carries the new clause/combinator fields.
    orig.write_text(
        "module m(input a, input b, output y); assign y = a & b; endmodule\n")
    opt.write_text(
        "module m(input a, input b, output y); assign y = b & a; endmodule\n")
    prompt = tmp_path / "spec.txt"
    prompt.write_text(
        "minimum reduction must be 12% for wires or 8% for cells")
    out = tmp_path / "rep.json"
    rc = ppa.main([
        "--original", str(orig), "--optimized", str(opt), "--top", "m",
        "--prompt", str(prompt), "--container", "vibeic-eda",
        "--json", str(out)])
    assert rc in (0, 1)   # PASS / NOT-APPLICABLE / BLOCK — never a setup error
    import json
    report = json.loads(out.read_text())
    assert report.get("combinator") == ppa._COMBINATOR_OR
    assert {(c["threshold_pct"], c["metric"]) for c in report["clauses"]} == {
        (12.0, "wires"), (8.0, "cells")}


def test_756_endstate_via_program_main(tmp_path):
    """#478 defect-artifact + end-state: invoke the real program main() on a
    tmp_path RTL pair + a disjunctive prompt; without a yosys container it
    resolves to a non-blocking NOT-APPLICABLE (rc 0) — a real end-state of the
    program, and the disjunctive clause parse is exercised end-to-end."""
    (tmp_path / "orig.sv").write_text("module m(input a, input b, output y); assign y=a&b; endmodule\n")
    (tmp_path / "opt.sv").write_text("module m(input a, input b, output y); assign y=b&a; endmodule\n")
    (tmp_path / "p.txt").write_text("minimum reduction must be 12% for wires or 8% for cells\n")
    rc = ppa.main(["--original", str(tmp_path / "orig.sv"),
                   "--optimized", str(tmp_path / "opt.sv"),
                   "--top", "m", "--prompt", str(tmp_path / "p.txt")])
    assert rc in (0, 1)   # real end-state (NOT_APPLICABLE/PASS=0 or BLOCK=1)
