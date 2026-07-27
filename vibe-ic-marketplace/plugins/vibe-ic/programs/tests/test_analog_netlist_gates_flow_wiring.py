"""Pins the landing of the A3 netlist gates + the A8 Liberty non-degeneracy gate.

Five programs that already existed and already worked were reachable only from
prose in `skills/analog-netlist-gen/SKILL.md` and
`skills/analog-hardmacro-gen/SKILL.md` ("Deterministic gates — run these, do
not eyeball"). Nothing in `flow/phase1_phase2_phase3.yaml`, in
`flow_compliance_check.py`, or in any runner ever invoked them, so what they
check had never been enforced.

Three things are pinned here, and they fail for different reasons:

  * WIRING — the flow YAML step must actually name the program. A capability
    the flow cannot reach is indistinguishable from one that was never built.
  * TEETH — the gate must still turn its step RED through the new channel on a
    bad input. A clause that cannot fail is decoration.
  * SCOPE — the gate must look where the step's artefacts actually are, and
    must not accuse where it cannot parse. Both were measured defects:
      - the netlist gates returned the FIRST existing analog root, so a
        project that had reached A5 (and therefore owned `phase3/analog/`)
        hid its `phase2/analog/*/*.sp` decks from them → vacuous PASS;
      - `analog_netlist_connectivity_check` counted only `X` sub-circuit
        instances, so on the completed benchmark run
        benchmark-data/ic/u_hawaii_adc/clean_run_v1422_20260715 the CORRECT
        switched-capacitor `delta_sigma` integrator was reported as
        `UNUSED_PORT: vin` + `FLOATING_NODE: vsum` — both false, because the
        signal reaches those nodes through `cs`/`ci` capacitors.

All fixtures are SYNTHETIC. The SC fixture reproduces the SHAPE of the real
deck (an OTA plus a sampling/integrating cap pair); no PDK or foundry data is
involved.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
COMPLIANCE = PROGRAMS / "flow_compliance_check.py"

A3_GATES = (
    "analog_netlist_connectivity_check",
    "analog_netlist_include_order_check",
    "analog_netlist_path_lint",
    "analog_tb_supply_pdk_check",
)
A8_GATE = "analog_liberty_nonzero_delay_check"


# ---------------------------------------------------------------------------
# WIRING — reachable from the flow
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def flow():
    return yaml.safe_load(FLOW_YAML.read_text())


def _step(flow, step_id):
    for s in flow["steps"]:
        if s.get("id") == step_id:
            return s
    raise AssertionError(f"step {step_id} missing from the flow")


def _gate_commands(gate):
    """Every program command reachable under a gate spec, at any nesting."""
    out = []
    if isinstance(gate, dict):
        for key, val in gate.items():
            if key in ("program_exit_zero", "optional_program_exit_zero"):
                out.append(val["command"] if isinstance(val, dict) else val)
            else:
                out.extend(_gate_commands(val))
    elif isinstance(gate, list):
        for item in gate:
            out.extend(_gate_commands(item))
    return out


def test_programs_exist():
    for name in A3_GATES + (A8_GATE,):
        assert (PROGRAMS / f"{name}.py").is_file(), f"{name}.py missing"


@pytest.mark.parametrize("prog", A3_GATES)
def test_netlist_gate_is_wired_into_a3(flow, prog):
    cmds = _gate_commands(_step(flow, "A3")["gate"])
    assert any(c.startswith(prog) for c in cmds), \
        f"Step A3 does not invoke {prog}"


def test_a3_incumbent_gate_is_preserved(flow):
    """The four gates ADD an opinion; they must not have replaced one."""
    cmds = _gate_commands(_step(flow, "A3")["gate"])
    assert any(c.startswith("analog_netlist_pdk_check") for c in cmds), \
        "the PDK-compliance gate was dropped from Step A3"


def test_liberty_gate_is_wired_into_a8(flow):
    cmds = _gate_commands(_step(flow, "A8")["gate"])
    assert any(c.startswith(A8_GATE) for c in cmds), \
        f"Step A8 does not invoke {A8_GATE}"


def test_a8_incumbent_gate_is_preserved(flow):
    cmds = _gate_commands(_step(flow, "A8")["gate"])
    assert any(c.startswith("analog_hardmacro_check") for c in cmds), \
        "the hardmacro-completeness gate was dropped from Step A8"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
GOOD_SP = """\
* ldo core -- GF180, clean deck
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.subckt ldo vin vout vdd vss
XMP1 vout gate vdd vdd pfet_03v3 W=20u L=4u
XMP2 gate gate vdd vdd pfet_03v3 W=20u L=4u
XMN1 gate vin vss vss nfet_03v3 W=10u L=2u
XMN2 vout vin vss vss nfet_03v3 W=10u L=2u
.ends
Vdd vdd 0 DC 3.3
.end
"""
FLOATING_SP = GOOD_SP.replace("XMN2 vout vin vss vss nfet_03v3 W=10u L=2u",
                              "XMN2 orphan vin vss vss nfet_03v3 W=10u L=2u")
BADORDER_SP = "\n".join([
    GOOD_SP.splitlines()[0],
    GOOD_SP.splitlines()[2],   # .lib first
    GOOD_SP.splitlines()[1],   # .include second
] + GOOD_SP.splitlines()[3:]) + "\n"
BADPATH_SP = GOOD_SP.replace(
    "/foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice",
    "/opt/scratch_models/design.ngspice")
BADSUPPLY_SP = GOOD_SP.replace("Vdd vdd 0 DC 3.3", "Vdd vdd 0 DC 1.8")

GOOD_LIB = """\
library (ldo) {
  cell (ldo) {
    area : 10000 ;
    pin (vout) {
      direction : output ;
      timing () {
        related_pin : "vin" ;
        cell_rise (scalar) { values ("0.42"); }
        cell_fall (scalar) { values ("0.37"); }
      }
    }
  }
}
"""
# The exact A8 stub shape analog_one_shot_runner emits: area only, no timing.
ZERO_LIB = "library(ldo_stub) {\n  cell(ldo) {\n    area : 10000 ;\n  }\n}\n"

GOOD_LEF = ("VERSION 5.8 ;\nMACRO ldo\n  CLASS BLOCK ;\n  SIZE 100 BY 100 ;\n"
            "  PIN vout\n    DIRECTION OUTPUT ;\n  END vout\n"
            "  PIN vin\n    DIRECTION INPUT ;\n  END vin\nEND ldo\n")


def _project(root: Path, sp_text: str, lib_text: str | None = None) -> Path:
    (root / "phase1" / "analog" / "ldo").mkdir(parents=True, exist_ok=True)
    (root / "phase1" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo", "type": "ldo"}]}))
    (root / "phase1" / "analog" / "ldo" / "spec.json").write_text(
        json.dumps({"block": "ldo"}))
    d = root / "phase2" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.sp").write_text(sp_text)
    if lib_text is not None:
        h = root / "phase3" / "analog" / "hardmacro" / "ldo"
        h.mkdir(parents=True, exist_ok=True)
        (h / "ldo.lib").write_text(lib_text)
        (h / "ldo.lef").write_text(GOOD_LEF)
        (h / "ldo.gds").write_text("stub-gds-bytes")
        (h / "ldo.v").write_text("module ldo(); endmodule\n")
        b = root / "phase3" / "analog" / "ldo"
        b.mkdir(parents=True, exist_ok=True)
        (b / "spec.json").write_text(json.dumps({"block": "ldo"}))
        (b / "corner_results.json").write_text(
            json.dumps({"_provenance": "real_ngspice"}))
    return root


def _step_status(project: Path, step_id: str) -> str:
    r = subprocess.run(
        [sys.executable, str(COMPLIANCE), "."],
        cwd=project, capture_output=True, text=True, timeout=900)
    for line in r.stdout.splitlines():
        if f"Step {step_id}:" in line:
            return line.split("[", 1)[1].split("]", 1)[0].strip()
    raise AssertionError(
        f"Step {step_id} not present in flow_compliance_check output:\n"
        f"{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


# ---------------------------------------------------------------------------
# TEETH — the wiring turns the step red through the real channel
# ---------------------------------------------------------------------------
def test_a3_passes_a_clean_netlist(tmp_path):
    assert _step_status(_project(tmp_path, GOOD_SP), "A3") == "PASS"


@pytest.mark.parametrize("sp_text,label", [
    pytest.param(FLOATING_SP, "floating internal node", id="floating_node"),
    pytest.param(BADORDER_SP, ".lib bound before .include design.ngspice",
                 id="lib_before_design_include"),
    pytest.param(BADPATH_SP, "non-portable absolute include",
                 id="non_whitelisted_absolute_path"),
    pytest.param(BADSUPPLY_SP, "supply that does not match the PDK flavour",
                 id="supply_pdk_mismatch"),
])
def test_a3_fails_through_the_new_gates(tmp_path, sp_text, label):
    assert _step_status(_project(tmp_path, sp_text), "A3") == "FAIL", \
        f"A3 stayed green on: {label}"


def test_a8_passes_a_liberty_with_real_delays(tmp_path):
    assert _step_status(_project(tmp_path, GOOD_SP, GOOD_LIB), "A8") == "PASS"


def test_a8_fails_on_the_area_only_stub_liberty(tmp_path):
    """`analog_hardmacro_check` accepts this hardmacro; STA on it is vacuous."""
    assert _step_status(_project(tmp_path, GOOD_SP, ZERO_LIB), "A8") == "FAIL"


# ---------------------------------------------------------------------------
# SCOPE — the measured blind spots must not come back
# ---------------------------------------------------------------------------
def test_phase2_netlists_are_not_hidden_by_a_phase3_analog_dir(tmp_path):
    """Pre-fix, the mere EXISTENCE of phase3/analog/ hid the phase2 decks."""
    root = _project(tmp_path, FLOATING_SP)
    (root / "phase3" / "analog" / "ldo").mkdir(parents=True, exist_ok=True)
    assert _step_status(root, "A3") == "FAIL"


def test_liberty_gate_discovers_blocks_from_the_flow_yaml_layout(tmp_path):
    """The flow anchors the analog track on phase1/analog/; the gate used to
    read phase3/analog/ only, so it found zero blocks and vacuously PASSed."""
    sys.path.insert(0, str(PROGRAMS))
    import analog_liberty_nonzero_delay_check as mod
    root = tmp_path / "p"
    (root / "phase1" / "analog").mkdir(parents=True)
    (root / "phase1" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}]}))
    assert mod._discover_blocks(root) == ["ldo"]


def test_connectivity_counts_passive_elements(tmp_path):
    """Real SC shape: the signal reaches vin/vsum through capacitors."""
    sys.path.insert(0, str(PROGRAMS))
    import analog_netlist_connectivity_check as mod
    sc = """\
.subckt integ vdd vss vcm vin vout
r_ib vdd nbias 200k
xm1 nd1 vsum ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm2 nd2 vcm  ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm5 ntail nbias vss vss sky130_fd_pr__nfet_01v8 w=8 l=1
xmb nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=1
xm3 nd1 nd1 vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.5
xm4 nd2 nd1 vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.5
xm6 vout nd2 vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.5
xm7 vout nbias vss vss sky130_fd_pr__nfet_01v8 w=8 l=1
cc  nd2 vout 0.5p
cs  vin  vsum 0.25p
ci  vsum vout 1p
.ends
"""
    d = tmp_path / "analog" / "integ"
    d.mkdir(parents=True)
    (d / "integ.sp").write_text(sc)
    res = mod.run_audit(tmp_path)
    assert res.passed is True, [f.message for f in res.findings
                                if f.severity == "ERROR"]

    # ... and it still accuses when the sampling cap really is gone.
    (d / "integ.sp").write_text(sc.replace("cs  vin  vsum 0.25p\n", ""))
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "UNUSED_PORT" in {f.rule for f in res.findings}


def test_connectivity_withholds_its_verdict_on_an_unparsed_element(tmp_path):
    """A partial parse must never manufacture a floating node."""
    sys.path.insert(0, str(PROGRAMS))
    import analog_netlist_connectivity_check as mod
    d = tmp_path / "analog" / "blk"
    d.mkdir(parents=True)
    (d / "blk.sp").write_text(
        ".subckt blk vin vout vdd vss\n"
        "q1 vout vin vss npn_model\n"
        ".ends\n")
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert "UNPARSED_ELEMENT" in {f.rule for f in res.findings}


def test_path_lint_accepts_a_staged_in_project_pdk(tmp_path):
    """Rung 1 of the analog PDK ladder stages a native PDK under
    <project>/input/pdk/; `analog_netlist_pdk_check` accepts a deck that loads
    it (#151), so the path lint must not hard-FAIL the same deck."""
    sys.path.insert(0, str(PROGRAMS))
    import analog_netlist_path_lint as mod
    root = tmp_path / "proj"
    staged = root / "input" / "pdk" / "spice" / "models.lib"
    staged.parent.mkdir(parents=True)
    staged.write_text("* staged native models\n")
    d = root / "phase2" / "analog" / "blk"
    d.mkdir(parents=True)
    (d / "blk.sp").write_text(f".include {staged}\n.subckt blk a b\n.ends\n")
    assert mod.run_audit(root).passed is True

    # ... and an environment path OUTSIDE the project is still a FAIL.
    (d / "blk.sp").write_text(
        ".include /opt/scratch_models/models.lib\n.subckt blk a b\n.ends\n")
    res = mod.run_audit(root)
    assert res.passed is False
    assert "NON_WHITELISTED_ABSOLUTE_PATH" in {f.rule for f in res.findings}


def test_netlist_gates_do_not_scan_a_digital_project(tmp_path):
    """A pure-digital project has no analog root; its PEX netlist under
    phase3/stage3/extracted/ is NOT an analog deck. The old whole-project
    fallback reported that netlist's ECO spare cells as FLOATING_NODE on
    campaign_pr427/spm/converge_ihp-sg13g2."""
    sys.path.insert(0, str(PROGRAMS))
    import analog_netlist_connectivity_check as conn
    import analog_netlist_include_order_check as order
    import analog_netlist_path_lint as plint
    import analog_tb_supply_pdk_check as supply
    d = tmp_path / "phase3" / "stage3" / "extracted"
    d.mkdir(parents=True)
    (d / "top_extracted.sp").write_text(
        ".subckt top a y vdd vss\n"
        "Xspare_0 dangling_in vss vdd vdd sky130_fd_sc_hd__inv_1\n"
        ".ends\n")
    for mod in (conn, order, plint, supply):
        res = mod.run_audit(tmp_path)
        assert res.passed is True, mod.GATE
        assert res.summary.get("skipped") is True, mod.GATE
