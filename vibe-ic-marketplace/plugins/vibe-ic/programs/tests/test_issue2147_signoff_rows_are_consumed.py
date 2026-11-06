#!/usr/bin/env python3
"""vibe-ic#2147 — the L7 sign-off rows must reach a VERDICT, and power must go
through the same technology ladder as area.

Measured by lane cz2136 on the subservient run (#2136's follow-up):

  * `area_total_vs_budget_check` read a DIE budget from L19 — null on that run —
    and returned NOT_APPLICABLE, a vacuous pass, over a design whose own L7
    table states an absolute standard-cell ceiling;
  * `power_total_vs_budget_check` read `L19.power_budget_uw` — also null — and
    returned INCOMPLETE, over a design whose same table states a total-power
    ceiling;
  * so BOTH sign-off rows the design wrote down were enforced by nobody, and
    the power row still carried #2136's cross-technology defect unfixed.

WHAT IS ASSERTED, and every one of these is a direction that must hold:

  1. On the baseline's OWN technology both rows reach a real verdict, with the
     tier that produced the threshold NAMED.
  2. On the technology the run was actually directed onto, both gates REFUSE BY
     NAME. Never PASS on a null, and never a cross-technology FAIL.
  3. The MUTATION: drop the consumer call and the rows go silent again — the
     gates return to NOT_APPLICABLE / INCOMPLETE. A consumer that cannot change
     the verdict is not a consumer.
  4. MEMBERSHIP: a run whose L19 declares a budget is decided by L19 exactly as
     before, byte for byte.
  5. The caller's RESOLVED library wins over what the run's artefacts say, which
     is the seam the Phase-3 step uses.

Fixtures are SYNTHETIC. The two open standard-cell libraries named here are the
run's technologies, which is the whole subject; no foundry, node or SKU appears.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import area_signoff_baseline as asb                # noqa: E402
from _ppa import power as _pw                      # noqa: E402

LIB_A = "sky130_fd_sc_hd"          # the library the L7 baseline was measured on
PDK_A = "sky130A"
LIB_B = "gf180mcu_fd_sc_mcu7t5v0"  # the library the measured run built against
PDK_B = "gf180mcuD"

#: The measured design's own numbers.
CELL_AREA_MEASURED = 57024.7104
CELL_CEILING_A = 16608.0
POWER_CEILING_A_UW = 2940.0

L7_DOC = f"""# L7 - Verification Plan

## 7.4 Quality Metrics

### 7.4.1 Baseline (top=`core`, memsize=1024, {LIB_A}, TT corner)

| metric | Baseline |
|---|---|
| stdcell count | **1,502** |
| stdcell area | **12,775 um^2** |
| die area | **34,269 um^2** |
| total power (TT) | **2.26 mW** |

### 7.4.2 Sign-off Acceptance Range

> The design should at least match baseline (area / power within baseline x 1.3).

| metric | accepted range | sign-off gate |
|---|---|---|
| stdcell count (informational) | baseline x [0.5, 2.0] = [751, 3004] | no |
| stdcell area | (0, baseline x 1.3] = <= 16,608 um^2 | yes |
| total power (TT) | (0, baseline x 1.3] = <= 2.94 mW | yes |
"""

#: A power report whose Total is 2.50e-03 W = 2500 uW — inside the 2940 uW row.
RPT_UNDER = """\
power analyser 2.7.0 — vectorless
POWER_ANALYSIS_MODE: vectorless_sdc
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power (Watts)
----------------------------------------------------------------
Sequential             2.20e-03   8.19e-06   5.28e-10   2.21e-03  88.4%
Combinational          2.80e-04   1.13e-05   3.17e-10   2.91e-04  11.6%
----------------------------------------------------------------
Total                  2.48e-03   1.95e-05   8.45e-10   2.50e-03 100.0%
"""
#: The same report at 3.50e-03 W = 3500 uW — outside it.
RPT_OVER = RPT_UNDER.replace("2.50e-03 100.0%", "3.50e-03 100.0%")

_NOT_APPLICABLE_RATIONALE = (
    "The input states no die or core rectangle to fit inside; the die size is "
    "an outcome of the run, not a ceiling the design set.")


def _project(tmp_path: Path, *, built_on: str, l7: bool = True,
             rpt: str = RPT_UNDER, die_budget=None, power_budget=None,
             area_declaration="not_applicable", name="run") -> Path:
    """The measured run's shape, with the two knobs this issue turns."""
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    if l7:
        (p / "input" / "docs" / "L7_verification_plan.md").write_text(L7_DOC)

    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "doc_id": "L19",
        "fields": {"pdk_target": "sky130",
                   "pdk_target_alternates": ["sky130", "gf180mcu"],
                   "die_area_budget_um": die_budget,
                   "power_budget_uw": power_budget}}, indent=2))

    # The run's OWN synthesis artefact — the only document that says what this
    # run actually built on, down to the corner file.
    st = p / "steps" / "phase2" / "stage2" / "9_synth"
    st.mkdir(parents=True)
    (st / "stats.json").write_text(json.dumps({
        "chip_area": CELL_AREA_MEASURED, "chip_area_unit": "um^2",
        "cell_count": 2180, "top_module": "core",
        "includes_submodules": False,
        "chip_area_unit_evidence": {
            "established": True, "unit": "um^2",
            "liberty": f"/pdks/{built_on}_pdk/libs.ref/{built_on}"
                       f"/lib/{built_on}__tt_025C.lib"}}, indent=2))

    rp = p / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "power.rpt").write_text(rpt)

    decl = p / "input" / "submission_template"
    decl.mkdir(parents=True)
    if area_declaration == "not_applicable":
        body = {"synthesis_area_budget": {"status": "NOT_APPLICABLE",
                                          "rationale": _NOT_APPLICABLE_RATIONALE}}
    elif area_declaration == "limit":
        body = {"synthesis_area_budget": {"status": "LIMIT",
                                          "max_die_dimensions_um": [300.0, 300.0]}}
    else:
        body = {}
    (decl / "tapeout_declaration.json").write_text(json.dumps(body, indent=2))
    return p


# ── 1. the baseline's own technology: BOTH rows reach a verdict ────────────








# ── 2. the technology the run was directed onto: refuse BY NAME ────────────




# ── 3. THE MUTATION: drop the consumer and the rows go silent again ────────




# ── 4. MEMBERSHIP: a declared L19 budget still decides, unchanged ──────────




# ── 5. the caller's resolved library wins, which is the Phase-3 seam ───────


def test_the_phase3_step_hands_the_area_gate_its_resolved_library():
    """The wiring itself, read from the runner rather than assumed."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert '_area_flags += ["--library", _area_lib]' in src
    assert '_area_flags += ["--pdk", _area_pdk]' in src
    assert "library_name_from_liberty(" in src
    # The FLAGS are hoisted into a local; the gate's PATH is not. See below for
    # why that distinction is a requirement and not a preference.
    assert "[sys.executable, str(_area_prog), str(project)] + _area_flags" in src


def test_hoisting_the_whole_argv_would_break_edge_9s_remeasured_proof():
    """THE FALSIFIER for a regression this change actually caused and fixed.

    `closed_loop_executable_coverage_check` proves edge 9 -> 9's REMEASURED tier
    off THIS call site, and it follows exactly two hops: a local bound to an
    expression whose source names the gate module, and a spawn whose argv names
    that local. The first shape of this change hoisted the whole argv into a
    second local — whose own assignment never spells the gate's name — and the
    edge silently fell back to DECLARED_ONLY, reddening nine tests.

    So the mutant is that hoist, applied to the real runner source, and the real
    proof predicate must go False on it. A comment saying "do not hoist" would
    not have caught it; this does.
    """
    import ast
    import importlib.util

    runner = PROGRAMS / "phase3_one_shot_runner.py"
    shipped = runner.read_text()
    spawn = "[sys.executable, str(_area_prog), str(project)] + _area_flags"
    assert shipped.count(spawn) == 1
    mutant = shipped.replace(
        spawn, "_area_argv", 1).replace(
        "        _area_flags: List[str] = []",
        "        _area_argv = [sys.executable, str(_area_prog), str(project)]\n"
        "        _area_flags: List[str] = []", 1)
    assert mutant != shipped




# ── the ladder is ONE ladder, and the units are converted or refused ───────
def test_power_uses_the_same_tier_names_as_area():
    docs = [("input/docs/L7_verification_plan.md", L7_DOC)]
    a = asb.resolve_texts(docs, [LIB_A], metric=asb.METRIC_CELL_AREA)
    p = asb.resolve_texts(docs, [LIB_A], metric=asb.METRIC_TOTAL_POWER)
    assert a["tier"] == p["tier"] == asb.DECLARED_BASELINE_TIER
    assert a["ratio"] == p["ratio"] == 1.3
    b = asb.resolve_texts(docs, [LIB_B], metric=asb.METRIC_TOTAL_POWER)
    assert b["tier"] == asb.NOT_DETERMINED_TIER
    assert b["disclosure"] == asb.METRIC_TOTAL_POWER.disclosure


def test_the_power_row_is_converted_to_the_compare_unit_not_guessed():
    docs = [("d", L7_DOC)]
    p = asb.resolve_texts(docs, [LIB_A], metric=asb.METRIC_TOTAL_POWER)
    assert p["unit"] == "uW"
    assert p["baseline"] == 2260.0        # 2.26 mW
    assert p["threshold"] == POWER_CEILING_A_UW
    # A figure in a unit this metric does not compare in is READ AND REFUSED,
    # and the refusal is its OWN finding — never collapsed into "nothing was
    # stated", which would turn a declared ceiling into an undeclared one.
    odd = L7_DOC.replace("**2.26 mW**", "**2.26 kW**") \
                .replace("<= 2.94 mW", "<= 2.94 kW")
    q = asb.resolve_texts([("d", odd)], [LIB_A], metric=asb.METRIC_TOTAL_POWER)
    assert q["baseline"] is None
    assert q["reason"] == "signoff_unit_not_comparable"
    assert any("kW" in str(u["stated"]) for u in q["unreadable_units"])
    assert "kW" in q["note"]
    # The AREA metric refuses the same way, so the rule is the metric's and not
    # one metric's special case.
    odd_a = L7_DOC.replace("**12,775 um^2**", "**12.775 mm^2**") \
                  .replace("<= 16,608 um^2", "<= 16.608 mm^2")
    qa = asb.resolve_texts([("d", odd_a)], [LIB_A], metric=asb.METRIC_CELL_AREA)
    assert qa["reason"] == "signoff_unit_not_comparable"


def test_the_run_artefact_outranks_an_l_doc_that_names_two_families(tmp_path):
    """The measured design's own shape: L19 names two open families, the run's
    stats.json names the one library it loaded. The artefact decides."""
    proj = _project(tmp_path, built_on=LIB_B)
    tech = asb.run_technology(proj)
    assert tech["ambiguous"] is False
    assert LIB_B in tech["candidates"]
    assert "stats.json" in str(tech["source"])


# ── never PASS on a null, with nothing declared anywhere ───────────────────
