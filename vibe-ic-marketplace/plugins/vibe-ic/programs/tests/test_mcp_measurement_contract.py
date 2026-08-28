#!/usr/bin/env python3
"""The flow half of the measurement contract: who READS the evidence, and where.

THE CONTRACT, in one sentence: a flow step may not record a step-level PASS on
a tool verdict that does not carry positive evidence the tool performed its
work.  The tool half -- what a tool must EMIT -- is
``mcp-eda/test/test_mcp_measurement_contract.py``.  A field nothing consults
relocates a defect instead of fixing it, so this file exists to pin the two
DECISION POINTS that consume it:

  1. ``eda_report_audit._check_sta`` -- the ``any_verdict_determined`` /
     ``real_violation_found`` computation behind ``sta_report_check``, which is
     step 10's and step 23's blocking gate.  MEASURED 2026-08-27: given a
     report from a run with no ``clk`` port, it set
     ``any_verdict_determined=True, real_violation_found=False`` -- it accepted
     a fabricated ``wns max 0.00`` as a met timing verdict.  It now reads the
     producing tool's own statement first.

  2. ``provenance_check --require-measured`` -- the artefact-to-run binding
     behind steps 9, 21, 22, 31 and 37.  It bound an artefact to an exit-0 run
     naming the right tool and never asked whether that run did any work; the
     linkless STA run satisfies every one of its conditions.

BOTH POLES, FOR EVERY GUARD.  Each test below has a companion asserting the
opposite direction, because a check that cannot go red is not a check and one
that fires on everything is equally useless.  In particular
``test_a_genuine_clean_run_still_passes`` and
``test_a_real_timing_violation_is_still_caught`` are what stop this from being
a refusal machine.

FIXTURES.  The four report bodies are VERBATIM ``openroad`` stdout captured on
``ghcr.io/vibeic/vibeic-eda@sha256:4ece6c01…`` on 2026-08-27.  See the tool-half
test file for what each one is and why (B) and (C) are indistinguishable to any
reader of the bytes alone.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _mcp_measurement as M  # noqa: E402

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

# ── verbatim report bodies ───────────────────────────────────────────────
BODY_VACUOUS = """OpenROAD 26Q3-1797-g1c09d62b96 
[INFO ORD-0030] Using 4 thread(s).
[ERROR ORD-2010] no technology has been read.
[ERROR STA-1570] No network has been linked.
[ERROR STA-1571] No network has been linked.
STA_CLOCK_COUNT=0
STA_COMPLETE
"""
BODY_GOOD = """OpenROAD 26Q3-1797-g1c09d62b96
Startpoint: _12_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _12_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
           1.34   slack (MET)
tns max 0.00
wns max 0.00
worst slack max 196.75
worst slack min 1.34
STA_COMPLETE
"""
# The FULL 1480-byte capture, unedited: a short excerpt would be under the
# 1024 B `STA_REPORT_TOO_SMALL` floor and the test would then be measuring
# the fixture's length rather than the contract.
BODY_COMBINATIONAL = """OpenROAD 26Q3-1797-g1c09d62b96 
Features included (+) or not (-): -GPU +GUI -Python
This program is licensed under the BSD-3 license. See the LICENSE file for details.
Components of this program may be licensed under more restrictive licenses which must be honored.
[INFO ORD-0030] Using 4 thread(s).
[INFO ODB-0388] unsupported LEF58_EOLENCLOSURE property for layer Via1 :"
  	EOLENCLOSURE 0.34 0.06 ;"
[INFO ODB-0388] unsupported LEF58_EOLENCLOSURE property for layer Via2 :" EOLENCLOSURE 0.34 0.06 ; "
[INFO ODB-0388] unsupported LEF58_EOLENCLOSURE property for layer Via3 :" EOLENCLOSURE 0.34 0.06 ; "
[INFO ODB-0388] unsupported LEF58_EOLENCLOSURE property for layer Via4 :" EOLENCLOSURE 0.34 0.06 ; "
[INFO ODB-0227] LEF file: /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef, created 15 layers, 56 vias
[WARNING ODB-0220] WARNING (LEFPARS-2008): NOWIREEXTENSIONATPIN statement is obsolete in version 5.6 or later.
The NOWIREEXTENSIONATPIN statement will be ignored. See file /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef at line 2.

[INFO ODB-0227] LEF file: /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/gf180mcu_fd_sc_mcu7t5v0.lef, created 229 library cells
STA_REGISTER_COUNT=0
STA_CLOCK_PORT_FOUND=0
[WARNING STA-0366] port 'clk' not found.
STA_CLOCK_COUNT=1
No paths found.
No paths found.
tns max 0.00
wns max 0.00
worst slack max INF
worst slack min INF
STA_COMPLETE
"""
BODY_VIOLATION = """OpenROAD 26Q3-1797-g1c09d62b96
Startpoint: _12_ (rising edge-triggered flip-flop clocked by clk)
Path Type: max
          -3.20   slack (VIOLATED)
tns max -10.65
wns max -3.20
worst slack max -3.20
worst slack min 1.34
STA_COMPLETE
"""

_SCHEMA = "mcp-eda/measurement/1"


def _stamp(measured, cls=None, reason="", tool="opensta via openroad"):
    rec = {"schema": _SCHEMA, "operation": "sta", "measured": measured,
           "not_measured_class": cls, "not_measured_reason": reason,
           "read": ["netlist.v"], "wrote": ["pre_pnr_timing.rpt"],
           "tool": tool}
    return M.STAMP_PREFIX + json.dumps(rec) + "\n"


def _sta_project(tmp_path: Path, body: str, stamp: str = "") -> Path:
    proj = tmp_path / "proj"
    (proj / "phase3/stage3/sta").mkdir(parents=True, exist_ok=True)
    (proj / "phase3/stage3/sta/pre_pnr_timing.rpt").write_text(stamp + body)
    return proj


def _sta_gate(proj: Path):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sta_report_check.py"), ".",
         "--mode", "sta",
         "--under", "phase3/stage3/sta/pre_pnr_timing.rpt",
         "--json", "reports/phase3/sta/pre_pnr_summary.json"],
        cwd=proj, capture_output=True, text=True, env=ENV, timeout=300)
    try:
        doc = json.loads(r.stdout)
    except json.JSONDecodeError:                       # pragma: no cover
        pytest.fail(f"gate did not emit JSON: {r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r.returncode, doc, {f["rule"] for f in doc["findings"]}


# =========================================================================
# DECISION POINT 1 — sta_report_check / eda_report_audit._check_sta
# =========================================================================
def test_the_vacuous_run_is_refused_by_name(tmp_path):
    """The whole point. rc must be 1 and the refusal must NAME what was missing."""
    proj = _sta_project(tmp_path, BODY_VACUOUS,
                        _stamp(False, "TOOL_DID_NOT_RUN",
                               "OpenROAD reported 10 error(s) and no timing "
                               "was analysed: [ERROR ORD-2010] no technology "
                               "has been read."))
    rc, doc, rules = _sta_gate(proj)
    assert rc == 1
    assert "STA_TOOL_REPORTS_NOT_MEASURED" in rules
    msg = next(f["message"] for f in doc["findings"]
               if f["rule"] == "STA_TOOL_REPORTS_NOT_MEASURED")
    assert "TOOL_DID_NOT_RUN" in msg and "ORD-2010" in msg
    assert doc["summary"]["sta_not_measured_hard"]


def test_a_genuine_clean_run_still_passes_and_lets_the_flow_continue(tmp_path):
    """THE OTHER POLE. If this ever fails, the change is a refusal machine."""
    proj = _sta_project(tmp_path, BODY_GOOD, _stamp(True))
    rc, doc, rules = _sta_gate(proj)
    assert rc == 0
    assert "STA_TOOL_REPORTS_NOT_MEASURED" not in rules
    assert doc["summary"]["sta_not_measured_hard"] == []


def test_a_real_timing_violation_is_still_caught(tmp_path):
    """The pole that proves the gate did not go blind while getting honest."""
    proj = _sta_project(tmp_path, BODY_VIOLATION, _stamp(True))
    rc, doc, rules = _sta_gate(proj)
    assert rc == 1
    assert "STA_REAL_VIOLATION_FOUND" in rules


def test_nothing_to_constrain_reaches_its_own_state_not_a_fabricated_pass(tmp_path):
    """A combinational block with no clock: honest, and NOT a refusal.

    It does not FAIL (there was nothing to measure), it does not claim a timing
    sign-off it never performed (`verdict: VACUOUS_PASS`, which
    `flow_compliance_check._json_report_signals_vacuous` already reads off a
    gate's own --json report), and it discloses the tool's reason.
    """
    proj = _sta_project(tmp_path, BODY_COMBINATIONAL,
                        _stamp(False, "NOTHING_TO_MEASURE",
                               "'dut_noclk' contains no sequential elements "
                               "and no SDC was supplied"))
    rc, doc, rules = _sta_gate(proj)
    assert rc == 0
    assert doc["verdict"] == "VACUOUS_PASS"
    assert "STA_NOTHING_TO_MEASURE" in rules
    assert "STA_VALUE_UNDETERMINED" not in rules
    assert "STA_TOOL_REPORTS_NOT_MEASURED" not in rules
    assert doc["summary"]["sta_nothing_to_measure"]


def test_the_same_bytes_without_a_stamp_are_judged_exactly_as_before(tmp_path):
    """UNDECLARED is its own state: it must not be read as measured:false.

    Every report the runner writes today, and every published one, is
    unstamped. Treating "nobody stated this" as "the tool failed" would turn
    the entire corpus into a fabrication claim -- the same lie in the opposite
    direction.
    """
    stamped = _sta_project(tmp_path / "a", BODY_GOOD, _stamp(True))
    bare = _sta_project(tmp_path / "b", BODY_GOOD)
    assert _sta_gate(stamped)[0] == _sta_gate(bare)[0] == 0
    _, doc, rules = _sta_gate(bare)
    assert "STA_TOOL_REPORTS_NOT_MEASURED" not in rules
    assert "STA_NOTHING_TO_MEASURE" not in rules


def test_the_stamp_does_not_pay_for_the_report_it_stamps(tmp_path):
    """A stamp is metadata ABOUT the output, never a substitute for it.

    MEASURED while building this: stamping an 873 B link-failure report pushed
    it past the 1024 B `STA_REPORT_TOO_SMALL` floor and matched the tool
    signature list, so two authenticity screens that had correctly refused that
    report started passing it. Both are measured on what the TOOL wrote.
    """
    tiny = "openroad failed\n"
    bare = _sta_project(tmp_path / "a", tiny)
    stamped = _sta_project(tmp_path / "b", tiny,
                           _stamp(False, "TOOL_DID_NOT_RUN", "x" * 2000))
    _, _, bare_rules = _sta_gate(bare)
    _, _, stamped_rules = _sta_gate(stamped)
    for rule in ("STA_REPORT_TOO_SMALL", "STA_NO_TOOL_SIGNATURE"):
        assert rule in bare_rules
        assert rule in stamped_rules, (
            f"{rule} disappeared once the report was stamped: the stamp is "
            f"paying for the report")


def test_a_stamp_cannot_delete_a_violation_written_in_its_own_report(tmp_path):
    """The producer's word must never outvote the producer's own output.

    Letting a `measured:false` stamp skip a report entirely would mean a
    `NOTHING_TO_MEASURE` claim sitting on top of `slack (VIOLATED)` lines
    erased every one of them -- the same defect this contract closes, rebuilt
    one layer up. A stamp may decline to ADD a verdict; it can never subtract
    one that is written down.
    """
    proj = _sta_project(tmp_path, BODY_VIOLATION,
                        _stamp(False, "NOTHING_TO_MEASURE", "no seq elements"))
    rc, doc, rules = _sta_gate(proj)
    assert rc == 1
    assert "STA_STAMP_CONTRADICTED_BY_ITS_OWN_REPORT" in rules
    assert "STA_REAL_VIOLATION_FOUND" in rules
    # And the step is NOT dispositioned vacuous on the strength of the stamp.
    assert doc.get("verdict") != "VACUOUS_PASS"


def test_the_same_stamp_over_a_report_with_no_violation_stays_vacuous(tmp_path):
    """THE OTHER POLE of the contradiction check: it must not fire on the
    honest case, or the combinational lane is refused after all."""
    proj = _sta_project(tmp_path, BODY_COMBINATIONAL,
                        _stamp(False, "NOTHING_TO_MEASURE", "no seq elements"))
    rc, doc, rules = _sta_gate(proj)
    assert rc == 0
    assert "STA_STAMP_CONTRADICTED_BY_ITS_OWN_REPORT" not in rules
    assert doc["verdict"] == "VACUOUS_PASS"


# =========================================================================
# DECISION POINT 2 — provenance_check --require-measured
# =========================================================================
def _prov_project(tmp_path: Path, measurement) -> Path:
    import hashlib
    proj = tmp_path / "p"
    (proj / "phase2/stage2/synth").mkdir(parents=True, exist_ok=True)
    art = "phase2/stage2/synth/netlist.v"
    body = "module top(input a, output y);\n  BUF _0_ (.A(a), .Z(y));\nendmodule\n"
    (proj / art).write_text(body)
    rec = {"timestamp": "2026-08-27T00:00:00Z", "tool": "yosys",
           "version": "yosys | version=0.68 | image=sha256:4ece6c01",
           "cwd": str(proj), "argv": ["yosys"], "inputs": {},
           "outputs": {art: "sha256:" + hashlib.sha256(body.encode()).hexdigest()},
           "exit_code": 0, "duration_s": 1.0, "stdout_sha": "sha256:x",
           "stderr_sha": "sha256:x", "stdout_tail": "", "stderr_tail": "",
           "source": "mcp-eda"}
    if measurement is not None:
        rec["measurement"] = measurement
    (proj / "provenance.jsonl").write_text(json.dumps(rec) + "\n")
    return proj


def _prov_gate(proj: Path, require: bool):
    cmd = [sys.executable, str(PROGRAMS / "provenance_check.py"), ".",
           "--output", "phase2/stage2/synth/netlist.v",
           "--tool", "yosys,yosys-abc"]
    if require:
        cmd.append("--require-measured")
    r = subprocess.run(cmd, cwd=proj, capture_output=True, text=True,
                       env=ENV, timeout=120)
    return r.returncode, r.stdout


def _m(measured, cls=None, reason=""):
    return {"schema": _SCHEMA, "operation": "synthesis", "measured": measured,
            "not_measured_class": cls, "not_measured_reason": reason,
            "read": [], "wrote": [], "tool": "yosys"}


def test_a_run_that_states_it_measured_nothing_fails_the_binding(tmp_path):
    proj = _prov_project(tmp_path, _m(False, "UNPARSEABLE",
                                      "yosys completed but its stat block "
                                      "yielded no cell count"))
    rc, out = _prov_gate(proj, require=True)
    assert rc == 1
    assert "UNPARSEABLE" in out and "measured\n" not in out.split("Overall")[1]
    # THE OTHER POLE: the artefact, the tool name, the exit code and the hash
    # are all exactly as before, so without the flag this binding still passes.
    # That is the measurement of what the flag adds, and of what was missing.
    assert _prov_gate(proj, require=False)[0] == 0


def test_a_run_that_states_it_measured_passes(tmp_path):
    proj = _prov_project(tmp_path, _m(True))
    assert _prov_gate(proj, require=True)[0] == 0
    assert _prov_gate(proj, require=False)[0] == 0


def test_nothing_to_measure_is_not_a_refusal(tmp_path):
    """A legitimately zero-cell design measured perfectly well."""
    proj = _prov_project(tmp_path, _m(False, "NOTHING_TO_MEASURE",
                                      "the design synthesises to zero cells"))
    rc, out = _prov_gate(proj, require=True)
    assert rc == 0


def test_an_undeclared_run_is_INCOMPLETE_not_PASS_and_not_FAIL(tmp_path):
    """The third state, rendered as itself.

    rc 0 -- because treating "nobody stated this" as a failure converts an
    unmeasured thing into a bad result. NOT a pass either: the `INCOMPLETE:`
    line is the token `flow_compliance_check._stdout_signals_token` reads to
    disposition the whole step into the INCOMPLETE tier, which is counted and
    rendered separately and never enters `pass_count`.
    """
    proj = _prov_project(tmp_path, None)
    rc, out = _prov_gate(proj, require=True)
    assert rc == 0
    assert "[UNMEASURED" in out
    assert any(line.startswith("INCOMPLETE:") for line in out.splitlines())
    # The sentinel must survive the consumer's tail cut: `output_snippet` keeps
    # only the LAST 300 characters of stdout and then requires the token to
    # start a line. A disclosure a path length can delete is not a disclosure.
    assert any(line.lstrip().startswith("INCOMPLETE:")
               for line in out[-300:].splitlines())
    # Without the flag, this same project is an ordinary PASS -- which is
    # exactly the gap: the artefact is bound to an exit-0 run by the right
    # tool, and nothing anywhere says whether that run did any work.
    assert _prov_gate(proj, require=False)[0] == 0


# =========================================================================
# The reader itself, and the wiring
# =========================================================================
def test_undeclared_is_never_read_as_a_failure():
    for text in ("", "no stamp here\n", M.STAMP_PREFIX + "{not json\n",
                 M.STAMP_PREFIX + '{"schema":"other/1","measured":false}\n',
                 M.STAMP_PREFIX + '{"schema":"mcp-eda/measurement/1","measured":null}\n'):
        m = M.from_text(text)
        assert m.undeclared is True
        assert m.hard_miss is False and m.nothing_to_measure is False


def test_worst_takes_the_loudest_claim_not_the_first():
    hard = M.from_text(M.STAMP_PREFIX + json.dumps(
        {"schema": _SCHEMA, "measured": False,
         "not_measured_class": "UNCONSTRAINED"}) + "\n")
    ok = M.from_text(M.STAMP_PREFIX + json.dumps(
        {"schema": _SCHEMA, "measured": True}) + "\n")
    assert M.worst([ok, hard]).hard_miss is True
    assert M.worst([hard, ok]).hard_miss is True
    assert M.worst([ok, ok]).positive is True
    assert M.worst([]).undeclared is True


def test_every_provenance_bound_step_asks_the_measurement_question():
    """The flow declaration is the wiring, so it is asserted as such.

    Both poles: this fails if a `--require-measured` is dropped from a wired
    gate, and it fails if a new `provenance_check` gate is added without one.
    """
    import yaml
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    wired, bare = [], []
    for step in flow["steps"]:
        for clause in (step.get("gate") or {}).get("all_of", []) or []:
            cmd = clause.get("program_exit_zero") if isinstance(clause, dict) else None
            if not cmd or not cmd.startswith("provenance_check "):
                continue
            if "--require-entries" in cmd:
                continue            # the coarse mode binds no artefact
            (wired if "--require-measured" in cmd else bare).append(
                (step["id"], cmd))
    assert bare == [], f"provenance_check gates that never ask: {bare}"
    assert len(wired) >= 6, wired


# ── the boundary itself: JS writes the stamp, Python reads it ────────────
#
# EVERYTHING ABOVE MOCKS THE OTHER SIDE. This module hand-writes the stamps it
# feeds the flow half, and `mcp-eda/test/test_mcp_measurement_contract.py`
# hand-checks the record the tool half emits. Both can be green while the two
# halves disagree about the bytes between them — which is the one failure that
# would make the whole contract inert without reddening a single test.
#
# So this runs the REAL emitter out of `src/index.js` under node and feeds its
# output to the REAL reader in `programs/_mcp_measurement.py`, for all three
# states. A schema rename, a prefix change, or a JSON-shape drift on either
# side fails here and nowhere else.
_NODE = shutil.which("node")
_INDEX_JS = (Path(__file__).resolve().parents[2] / "mcp-eda" / "src" / "index.js")


def _emit_stamps_with_node(cases):
    """Return one stamp line per case, produced by src/index.js itself."""
    src = _INDEX_JS.read_text()
    a = src.index("const MEASUREMENT_SCHEMA = ")
    b = src.index("function measurementStamp(rec) {")
    b = src.index("}", src.index("return MEASUREMENT_STAMP_PREFIX", b)) + 1
    js = src[a:b] + "\nconst out=[];\n"
    for kw in cases:
        js += f"out.push(measurementStamp(measurementRecord({json.dumps(kw)})));\n"
    js += "process.stdout.write(out.join(''));\n"
    r = subprocess.run([_NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return [ln for ln in r.stdout.split("\n") if ln.strip()]


@pytest.mark.skipif(not _NODE, reason="node not available")
@pytest.mark.parametrize("cls,exp_measured,exp_hard,exp_benign", [
    ("TOOL_DID_NOT_RUN",   False, True,  False),
    ("UNCONSTRAINED",      False, True,  False),
    ("NOTHING_TO_MEASURE", False, False, True),
    (None,                 True,  False, False),
])
def test_the_reader_agrees_with_the_emitter_on_every_state(
        cls, exp_measured, exp_hard, exp_benign):
    """All THREE states must survive the language boundary, not just the two
    poles: if `NOTHING_TO_MEASURE` were to arrive as a hard miss, the gate
    would refuse every combinational design; if a hard miss were to arrive as
    benign, the fabricated 0.00 is back."""
    kw = {"operation": "sta", "measured": exp_measured,
          "reasonClass": cls, "reason": "measured on the boundary",
          "toolLabel": "opensta via openroad"}
    (stamp,) = _emit_stamps_with_node([kw])
    got = M.from_text(stamp + "\nwns max 0.00\n", "boundary")
    assert got.declared is True, (
        "the reader did not recognise the emitter's own stamp as a declaration "
        f"at all — the two halves disagree about the bytes: {stamp[:120]!r}")
    assert got.measured is exp_measured
    assert got.hard_miss is exp_hard
    assert got.nothing_to_measure is exp_benign


@pytest.mark.skipif(not _NODE, reason="node not available")
def test_the_reader_strips_exactly_the_bytes_the_emitter_added():
    """The stamp must not pay for the report it stamps. MEASURED: without the
    strip, a stamped 873 B link-failure report cleared the 1024 B size floor
    and matched the tool-signature list, and two checks that had correctly
    refused it began passing it. An off-by-one here re-opens that by degrees.
    """
    (stamp,) = _emit_stamps_with_node([{
        "operation": "sta", "measured": False,
        "reasonClass": "TOOL_DID_NOT_RUN", "reason": "linked nothing",
        "toolLabel": "opensta via openroad"}])
    # `stamp` comes back without the trailing newline the emitter writes, so
    # the stamped file is reconstructed here exactly as the tool writes it:
    # the stamp line, its newline, then the report.
    report = "some timing report text\nwns max 0.00\n"
    stripped, n = M.strip_stamp(stamp + "\n" + report)
    assert "MCP_MEASUREMENT" not in stripped, "the stamp survived the strip"
    assert stripped == report, (
        "the strip took report bytes with it, or left stamp bytes behind — "
        "either way the screens below it are now reading the wrong text")
    assert n == len(stamp) + 1, (
        f"the byte count the size screen subtracts is {n}, but the emitter "
        f"added {len(stamp) + 1}; a size floor is now measured against the "
        "wrong number in one direction or the other")
