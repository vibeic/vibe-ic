"""vibe-ic#2081 — a Phase-3 sign-off STA violation that no physical remedy can
close must REFUSE, name its residual, and route to the step that can act.

Every fixture below is a REDUCTION of the real reports of the run in #2081
(sha256 x sky130A, lane rbsha2) or of its own pre-layout per-corner control.
The numbers are that run's; the geometry of each path is preserved.
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


PLUGIN = Path(__file__).resolve().parents[2]

# ── fixtures ────────────────────────────────────────────────────────────────

# The architectural path: 39 arcs, ONE buffer (0.55 ns), 1.03 ns of adverse
# clock skew, slack -2.46. PRUB 1.58 < 2.46 -> residual +0.88 ns.
_ARCH = """=== SETUP corner: process=SS liberty=lib_ss ===
STA_BASIS: POST_ROUTE_SPEF
Startpoint: _17630_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _17661_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

    Cap    Slew   Delay    Time   Description
                   6.33    6.33   clock network delay (propagated)
   0.05    0.38    1.06    7.39 ^ _17630_/Q (cell__dfxtp_2)
{ARCS}
   0.01    0.15    0.55   99.00 v rebuffer1/X (cell__buf_1)
                  25.90   25.90   clock clk (rise edge)
                   5.30   31.20   clock network delay (propagated)
                          -2.46   slack (VIOLATED)
"""
_ARCH = _ARCH.replace(
    "{ARCS}",
    "\n".join(f"   0.04    0.20    0.68   {10 + i:5.2f} v _1{i:04d}_/X "
              f"(cell__maj3_4)" for i in range(37)))

# The DRIVE-LIMITED control, from the run's own pre-layout per-corner report:
# 4 arcs, no buffers, slack -125.54, and ONE arc carries 94.70 of 151.17 ns.
# The bare bound calls this architectural; it is not — placement and buffering
# DID fix it (-125.54 -> -2.53 on the routed netlist).
_DRIVE = """=== SETUP corner: process=SS liberty=lib_ss ===
STA_BASIS: POST_ROUTE_SPEF
Startpoint: _18239_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _18269_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
   0.00    0.00   clock network delay (propagated)
   2.36    2.36 v _18239_/Q (cell__dfxtp_1)
  47.39   49.75 ^ _08229_/Y (cell__o21ai_0)
  94.70  144.45 v _08263_/Y (cell__nor2_1)
   6.72  151.17 ^ _08266_/Y (cell__o21ai_0)
   0.00    0.00   clock network delay (propagated)
        -125.54   slack (VIOLATED)
"""

# A HOLD path. Different physics, different remedy; this bound says nothing
# about it and must not judge it.
_HOLD = _ARCH.replace("Path Type: max", "Path Type: min")

# A path whose violation IS inside the physical bound: same shape, but 3.00 ns
# of buffers against a 2.46 ns violation.
_PHYS = _ARCH.replace("   0.01    0.15    0.55   99.00 v rebuffer1/X "
                      "(cell__buf_1)",
                      "   0.01    0.15    3.00   99.00 v rebuffer1/X "
                      "(cell__buf_1)")

_MET = _ARCH.replace("-2.46   slack (VIOLATED)", "1.20   slack (MET)")


def _project(tmp_path: Path, body: str, name="sta_mcorner_ocv.rpt") -> Path:
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    return tmp_path




# ── the subject ─────────────────────────────────────────────────────────────







# ── the guards, each with the measurement that forced it ────────────────────

















# ── the wiring: a gate nobody runs is the defect this issue is about ────────

def test_the_gate_is_wired_into_the_signoff_step():
    flow = yaml.safe_load(
        (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s["id"]) == "23")
    blob = json.dumps(step["gate"])
    assert "sta_architectural_residual_check" in blob, (
        "step 23 (post-route STA sign-off) does not run the gate")


def test_the_step_declares_the_report_it_produces():
    flow = yaml.safe_load(
        (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s["id"]) == "23")
    assert any("architectural_residual" in o
               for o in step["required_outputs"])


def test_capture_routing_sends_the_finding_to_authoring():
    """#2081's structural half: `phase3.sta` routed to the STA runner and the
    sta-review skill — both physical. The architectural case must route to the
    step that can remove a combinational depth."""
    routing = json.loads(
        (PLUGIN / "benchmark" / "CAPTURE_ROUTING.json").read_text())
    entry = routing["steps"].get("phase3.sta.architectural_residual")
    assert entry, "no routing entry for the architectural-residual finding"
    assert entry["bucket_A_program"] == \
        "programs/sta_architectural_residual_check.py"




# ── the corner label is prose, and its polarity is asked (vibe-ic#712) ───────
#
# `prose_polarity_consulted_check` REFUSED this program's landing on
# `analyse_report`, and the refusal was right. MEASURED before the fix, on the
# fixture below: `corner` came back as the string
# "Corner SS: this corner is NOT a sign-off corner" — a denying sentence
# published as a declared field and quoted back in the refusal as the corner
# this gate had judged. That is #706's shape one field over: `_PROCESS_RE`
# matches only when the emitter writes a `process=` token, and the fallback
# publishes the banner's own WORDS.
#
# The pair below is bidirectional. `test_a_denying_corner_banner...` FAILS
# against the pre-fix function (it asserted the sentence into `corner`), and
# `test_an_ordinary_corner_banner...` passes against BOTH — so the fix is not
# free to answer by blanking every label it reads.

_DENIED_BANNER = _ARCH.replace(
    "=== SETUP corner: process=SS liberty=lib_ss ===",
    "=== SETUP corner SS: this corner is NOT a sign-off corner, retained "
    "for reference only ===")










@pytest.mark.parametrize("body, expected", [(_ARCH, "FAIL"), (_MET, "PASS"), (None, "NOT_MEASURED")],
                         ids=["violated", "met", "missing"])
def test_inline_signoff_executes_the_architectural_gate(tmp_path, monkeypatch, body, expected):
    import phase3_one_shot_runner as runner
    project = _project(tmp_path, body) if body is not None else tmp_path
    actual = runner._run_declared_signoff_gate

    def dispatch(project, name, program, out_rel, extra_argv=()):
        # Isolate this gate's contribution to the real dispatch and verdict
        # fold. Unrelated gates (including operator tools) are outside this
        # report-reader test; the subject runs as its actual subprocess.
        if program == "sta_architectural_residual_check.py":
            return actual(project, name, program, out_rel, extra_argv)
        return runner.StepResult(name, "PASS", 0.0, "unrelated gate control", [])

    monkeypatch.setattr(runner, "_run_declared_signoff_gate", dispatch)
    rows = runner.step_declared_signoff_gates(project)
    own = [r for r in rows if r.name == "sta_architectural_residual"]
    assert len(own) == 1, "the inline sign-off executor never called the declared gate"
    assert own[0].status == expected
    report = json.loads((project / "reports/phase3/sta/architectural_residual.json").read_text())
    assert report["route_skill"] == "spec-to-rtl"
    if expected == "FAIL":
        assert "SS" in own[0].detail and "0.88" in own[0].detail
        assert runner._aggregate_verdict(rows) == "FAIL"
    elif expected == "NOT_MEASURED":
        assert runner._aggregate_verdict(rows) not in ("PASS", "PASS_WITH_WAIVERS")
    else:
        assert runner._aggregate_verdict(rows) == "PASS"


@pytest.mark.parametrize("body, expected_rc, expected_verdict",
                         [(_ARCH, 1, "FAIL"), (_MET, 0, "PASS"),
                          (None, 2, "INCOMPLETE")],
                         ids=["violated", "met", "missing"])
@pytest.mark.parametrize("existing_report", [False, True],
                         ids=["absent-report", "existing-report"])
def test_compliance_audit_preserves_producer_output(
        tmp_path, body, expected_rc, expected_verdict, existing_report):
    """The actual YAML/FCC consumer may check, but may not self-certify.

    Tiny report reductions exercise the real checker subprocess. A prior
    producer report is deliberately different from the current timing inputs:
    its existence must neither suppress re-checking nor authorize replacement.
    """

    project = _project(tmp_path, body) if body is not None else tmp_path
    report = project / "reports/phase3/sta/architectural_residual.json"
    if existing_report:
        report.parent.mkdir(parents=True)
        report.write_bytes(b'{"verdict":"PASS","producer_receipt":"original"}\n')

    def files():
        return {str(p.relative_to(project)): p.read_bytes()
                for p in project.rglob("*") if p.is_file()}

    before = files()
    flow = yaml.safe_load(
        (PLUGIN / "flow/phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s["id"]) == "23")
    commands = []

    def find_commands(value):
        if isinstance(value, dict):
            cmd = value.get("program_exit_zero", "")
            if isinstance(cmd, str) and cmd.split()[0:1] == ["sta_architectural_residual_check"]:
                commands.append(cmd)
            for child in value.values():
                find_commands(child)
        elif isinstance(value, list):
            for child in value:
                find_commands(child)

    find_commands(step["gate"])
    assert len(commands) == 1
    after = files()
    if existing_report:
        assert report.read_bytes() == before[str(report.relative_to(project))]
    else:
        assert len(after) == len(before), "audit created a producer-owned output"
    assert after == before, "audit changed project evidence"


@pytest.mark.parametrize("broken", ["missing-reader", "missing-output"])
def test_d4_inline_report_wiring_requires_actual_consumption(monkeypatch, broken):
    """Neither a registered path nor a successful writer is a report read."""
    import matrix_d4_probe as probe
    import phase3_one_shot_runner as runner

    if broken == "missing-reader":
        monkeypatch.setattr(runner, "_gate_detail", lambda path, out, err: out or err)
    else:
        actual = runner._pr.run

        def missing_output(cmd, **kwargs):
            result = actual(cmd, **kwargs)
            # Only this real subprocess's scratch output is removed, after
            # it produced a report but before the normal wrapper can read it.
            Path(cmd[cmd.index("--json") + 1]).unlink()
            return result

        monkeypatch.setattr(runner._pr, "run", missing_output)

    assert probe.ground(23, "reports/phase3/sta/architectural_residual.json") is None


# #3359: neutral synthetic controls using OpenSTA's native column layout.
# The actual three-line PRE_LAYOUT snapshot is retained in the repair packet;
# these controls do not relabel that snapshot as post-route evidence.
def _column_path(columns=5, *, kind="max", violated=True, dominant=False,
                 basis="POST_ROUTE_SPEF"):
    labels = {2: ("Delay", "Time"), 3: ("Slew", "Delay", "Time"),
              4: ("Cap", "Slew", "Delay", "Time"),
              5: ("Fanout", "Cap", "Slew", "Delay", "Time")}[columns]
    header = "".join(f"{name:>12}" for name in labels) + "   Description"
    rows = []
    # Include an input-pin row with blank Fanout/Cap and zero Delay, then
    # enough logic arcs to exercise the depth guard without a dominant arc.
    for i, delay in enumerate([0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]):
        if dominant and i == 6:
            delay = 20.0
        values = {"Fanout": "2", "Cap": "0.009140", "Slew": "25.000000",
                  "Delay": f"{delay:.6f}", "Time": f"{100 + i:.6f}"}
        if i == 0:
            values.update(Fanout="", Cap="")
        row = "".join(f"{values[name]:>12}" for name in labels)
        cell = "cell__buf_1" if i == 1 else "cell__logic_1"
        rows.append(row + f" v stage{i}/X ({cell})")
    slack = "-3.529765   slack (VIOLATED)" if violated else "1.200000   slack (MET)"
    return (f"STA_BASIS: {basis}\nStartpoint: launch\nEndpoint: capture\n"
            f"Path Type: {kind}\n{header}\n" + "\n".join(rows) + f"\n{slack}\n")
