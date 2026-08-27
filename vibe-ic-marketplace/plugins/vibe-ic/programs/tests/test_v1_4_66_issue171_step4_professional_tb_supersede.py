"""ORGANIC #171 (A11) — Step-4 Simulation must accept a REAL professional_tb
functional PASS as simulation evidence.

Root cause: the Step-4 gate's artifact sub-gate is
    files_exist: [phase2/stage1/sim/results.xml, phase2/stage1/sim/pass.flag]
    any_of: true
A design whose functional oracle IS derivable (e.g. the spm bit-serial
multiplier) gets a real cocotb streaming-scoreboard PASS from
``professional_tb_gen`` written under
``phase2/stage1/sim_professional/<top>/results.xml`` (failures=0), but the runner
does not ALSO emit the canonical ``sim/results.xml`` / ``pass.flag`` for that
class — so the ``files_exist`` sub-gate hard-FAILed Step-4 even though functional
verification actually CLOSED (spm ASAP7 step-4 FAIL).

Fix: ``flow_compliance_check._evaluate_gate`` ``files_exist`` branch now consults
``_sim_files_superseded_by_professional_tb`` — which, ONLY for the sim
functional-evidence gate (its missing set names ``phase2/stage1/sim/results.xml``)
AND ONLY when ``_srb.find_professional_tb_pass`` returns a REAL PASS, promotes the
gate to a clean PASS (plain reason → not a skip/vacuous promotion).

§4.05 NEGATIVE no-leak (critical):
  * a project WITHOUT a professional-TB pass reaches EXACTLY its prior FAIL;
  * a FAILING / vacuous professional result does NOT leak a pass;
  * a NON-sim files_exist gate is never affected (scoped to the sim signature);
  * the canonical sim/results.xml present path passes clean, unchanged.

chip-AGNOSTIC: structural paths + JUnit structure only, no chip / vendor / SKU
literal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as FCC  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────
def _pro_dir(tmp_path, top="dut"):
    d = tmp_path / "phase2" / "stage1" / "sim_professional" / top
    d.mkdir(parents=True)
    return d


_JUNIT_PASS = """\
<testsuites>
  <testsuite name="cocotb" tests="208" failures="0" errors="0" skipped="0">
    <testcase name="stream_scoreboard" classname="dut"/>
  </testsuite>
</testsuites>
"""

_JUNIT_FAIL = """\
<testsuites>
  <testsuite name="cocotb" tests="208" failures="3" errors="0" skipped="0">
    <testcase name="stream_scoreboard" classname="dut"/>
  </testsuite>
</testsuites>
"""

_JUNIT_VACUOUS = """\
<testsuites>
  <testsuite name="cocotb" tests="0" failures="0" errors="0" skipped="0"/>
</testsuites>
"""

# The connectivity bridge the WAIVED reference TB writes — NOT a JUnit doc.
_CONNECTIVITY_BRIDGE = "<results><verdict>CONNECTIVITY_PASS</verdict></results>\n"


def _sim_gate():
    # The exact Step-4 artifact sub-gate shape from the flow YAML.
    return {"files_exist": ["phase2/stage1/sim/results.xml",
                            "phase2/stage1/sim/pass.flag"],
            "any_of": True}


# ── (1) the fix: a real professional PASS supersedes the absent canonical sim ─
def test_professional_pass_supersedes_absent_canonical_sim(tmp_path):
    (_pro_dir(tmp_path) / "results.xml").write_text(_JUNIT_PASS)
    passed, reasons = FCC._evaluate_gate(tmp_path, _sim_gate())
    assert passed is True, reasons
    # clean PASS — NOT a skip/vacuous/waiver promotion.
    assert not any(r.startswith(FCC._SKIP_HINT_PREFIX) for r in reasons), reasons
    assert not any(r.startswith(FCC._VACUOUS_HINT_PREFIX) for r in reasons), reasons
    assert not any(r.startswith(FCC._WAIVER_HINT_PREFIX) for r in reasons), reasons
    assert any("professional_tb functional PASS" in r for r in reasons), reasons


# ── (2..5) §4.05 no-leak negatives ───────────────────────────────────────────
def test_no_professional_pass_still_fails_identically(tmp_path):
    """No professional result at all → the gate FAILs EXACTLY as before."""
    passed, reasons = FCC._evaluate_gate(tmp_path, _sim_gate())
    assert passed is False, reasons
    assert any("missing files" in r for r in reasons), reasons


def test_failing_professional_result_does_not_leak_pass(tmp_path):
    """A professional results.xml with failures>0 is NOT a pass → gate FAILs."""
    (_pro_dir(tmp_path) / "results.xml").write_text(_JUNIT_FAIL)
    passed, reasons = FCC._evaluate_gate(tmp_path, _sim_gate())
    assert passed is False, reasons


def test_vacuous_professional_result_does_not_leak_pass(tmp_path):
    """A zero-test professional result is vacuous → gate FAILs (no leak)."""
    (_pro_dir(tmp_path) / "results.xml").write_text(_JUNIT_VACUOUS)
    passed, reasons = FCC._evaluate_gate(tmp_path, _sim_gate())
    assert passed is False, reasons


def test_connectivity_bridge_is_not_a_functional_pass(tmp_path):
    """The <results><verdict> connectivity bridge is not JUnit → never counts as
    a professional functional pass for this supersede."""
    (_pro_dir(tmp_path) / "results.xml").write_text(_CONNECTIVITY_BRIDGE)
    passed, reasons = FCC._evaluate_gate(tmp_path, _sim_gate())
    assert passed is False, reasons


def test_canonical_sim_present_passes_clean_unchanged(tmp_path):
    """When the canonical sim/results.xml IS present, the gate passes WITHOUT the
    supersede reason (byte-identical to the pre-fix pass path)."""
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text(_CONNECTIVITY_BRIDGE)
    passed, reasons = FCC._evaluate_gate(tmp_path, _sim_gate())
    assert passed is True, reasons
    assert not any("professional_tb functional PASS" in r for r in reasons), reasons


def test_non_sim_files_exist_gate_never_superseded(tmp_path):
    """SCOPING §4.05: a real professional PASS is present, but a NON-sim
    files_exist gate (e.g. a formal/PnR artifact) must STILL FAIL — the supersede
    is keyed on the sim canonical-results signature only."""
    (_pro_dir(tmp_path) / "results.xml").write_text(_JUNIT_PASS)
    gate = {"files_exist": ["phase2/stage1/formal/results.json"]}
    passed, reasons = FCC._evaluate_gate(tmp_path, gate)
    assert passed is False, reasons
    assert not any("professional_tb functional PASS" in r for r in reasons), reasons


# ── (6) end-to-end check_step on the canonical Step-4 all_of shape ────────────
def _step4():
    """The canonical Step-4 shape, mirroring the flow yaml.

    `required_outputs` used to be listed here (and in the yaml) as three
    independent entries — `sim/*.log`, `sim/results.xml OR sim/pass.flag`, and
    the coverage json. That was only ever satisfiable because check_step pooled
    evidence across the list; under the ALL-of-N contract the module documents,
    no real run could satisfy it, because the supported TB paths are mutually
    exclusive in what they emit: cocotb writes results.xml/pass.flag and no
    *.log, a transcript run writes *.log, and the professional TB this file is
    about writes under sim_professional/<top>/. They are one requirement — "a
    simulation ran and left a transcript" — in three shapes, so they are now one
    OR entry. `test_fixture_matches_the_flow_yaml` below pins this to the real
    declaration so the two cannot drift apart again."""
    return {
        "id": 4, "name": "Simulation",
        "required_outputs": [
            "phase2/stage1/sim/*.log OR phase2/stage1/sim/results.xml"
            " OR phase2/stage1/sim/pass.flag"
            " OR phase2/stage1/sim_professional/**/results.xml",
            "reports/phase2/coverage/coverage_actual.json",
            # ONE PRODUCER PER PATH (v1.11.92, `e314f1923d`). The line/toggle/
            # branch MEASUREMENT moved off `coverage_actual.json` — which the
            # functional-verdict producer owns — onto its own path, and the yaml
            # declares both. The mirror had only the first, so the pin below was
            # RED on main: it is the drift detector working, not a stale rule.
            "reports/phase2/coverage/coverage_verilator.json",
        ],
        "gate": {"all_of": [dict(_sim_gate())]},
    }


def test_fixture_matches_the_flow_yaml():
    """This file's Step-4 fixture must BE the flow's Step 4, not a lookalike —
    otherwise it can keep asserting a shape the real flow no longer has."""
    import yaml
    flow = (Path(__file__).resolve().parents[2] / "flow"
            / "phase1_phase2_phase3.yaml")
    doc = yaml.safe_load(flow.read_text())
    real = next(s for s in doc["steps"] if s.get("id") == 4)
    assert real["required_outputs"] == _step4()["required_outputs"]


def test_check_step_step4_passes_on_professional_tb(tmp_path):
    """check_step over a Step-4-shaped all_of: canonical sim/results.xml + pass.flag
    absent, coverage_actual.json present (evidence → reaches the gate), a real
    professional_tb PASS present → PASS (not FAIL, not SKIPPED-CONDITION)."""
    (_pro_dir(tmp_path) / "results.xml").write_text(_JUNIT_PASS)
    cov = tmp_path / "reports" / "phase2" / "coverage"
    cov.mkdir(parents=True)
    # BOTH declared coverage outputs — the functional verdict and, since
    # v1.11.92 split the paths, the measurement. Existence is all Step 4's
    # `required_outputs` ask of them here; this file's subject is whether a real
    # professional-TB PASS supersedes the ABSENT canonical sim files, and the
    # coverage artefacts are present only so the step reaches its gate instead
    # of short-circuiting on MISSING. Writing one and not the other made the
    # step MISSING and put this file's subject out of reach.
    (cov / "coverage_actual.json").write_text("{}")
    (cov / "coverage_verilator.json").write_text("{}")
    res = FCC.check_step(tmp_path, _step4(), waivers={})
    assert res.status == "PASS", (res.status, res.reasons)


def test_check_step_step4_fails_without_professional_tb(tmp_path):
    """§4.05 no-leak end-to-end: same shape but NO professional pass → Step-4
    FAILs exactly as before (coverage present so it reaches the gate)."""
    cov = tmp_path / "reports" / "phase2" / "coverage"
    cov.mkdir(parents=True)
    # BOTH declared coverage outputs — the functional verdict and, since
    # v1.11.92 split the paths, the measurement. Existence is all Step 4's
    # `required_outputs` ask of them here; this file's subject is whether a real
    # professional-TB PASS supersedes the ABSENT canonical sim files, and the
    # coverage artefacts are present only so the step reaches its gate instead
    # of short-circuiting on MISSING. Writing one and not the other made the
    # step MISSING and put this file's subject out of reach.
    (cov / "coverage_actual.json").write_text("{}")
    (cov / "coverage_verilator.json").write_text("{}")
    res = FCC.check_step(tmp_path, _step4(), waivers={})
    assert res.status == "FAIL", (res.status, res.reasons)
