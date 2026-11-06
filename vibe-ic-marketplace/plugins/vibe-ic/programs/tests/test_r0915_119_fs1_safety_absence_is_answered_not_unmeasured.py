#!/usr/bin/env python3
"""FS1 — a design with no safety mechanism has been ANSWERED, not unmeasured.

THE MEASURED DEFECT (lane icgate1, 2026-09-21), reproduced byte-for-byte from
`spm x gf180mcuD` run13's own `phase2/stage1/rtl/spm.v`:

    "id": "FS1", "status": "NOT_MEASURED", "reason_class": "no_population",
    "disclosures": ["vacuity"],
    "reasons": ["vacuous: gate program signalled VACUOUS_PASS (input not
                 applicable), and it is 2 of 2 gate clause(s) that ran here:
                 fmeda_fault_injection_coverage …",
                "vacuous: … fmeda_coverage_check …"]

FS1's condition is `files_exist: ["phase2/stage1/rtl"]`, so the step is
APPLICABLE for every design that has RTL — which is every design — and with no
safety mechanism both of its gate clauses disclosed VACUOUS_PASS. All clauses
vacuous ⇒ `NOT_MEASURED(no_population)`, and the completion audit counts that
row against the run, on EVERY digital die, regardless of layout.

"Examined nothing" was a false account of it. `detect_safety_mechanism` READ
the design's RTL, enumerated its modules and ANSWERED the question. That is
R-0915-119's shape exactly — "a design with no arbiter has been ANSWERED about
arbiters" — so the two gates now state `NOT_APPLICABLE_BY_STRUCTURE` and carry
the enumeration that establishes it.

WHY NOT `DESIGN_DECLARED_NA`: that class requires a TYPED DESIGN DECLARATION to
have been examined (`_flow_reason_taxonomy._declared_basis`), and no L-doc in
`l_doc_taxonomy` carries a functional-safety declaration. The absence here is
derived from the checker's OWN enumeration, which is precisely the distinction
the two classes exist to keep.

AND THE READER'S HALF OF GUARD (i), which had to be repaired for any of it to
arrive. `flow_compliance_check._check_program_exit_zero` read a report's typed
class and passed it to `infer_nonverdict_reason` WITHOUT the enumeration, so
`_guard_structural` never saw a valid record and fell back to the fail-closed
default. The class was UNREACHABLE through the report channel. MEASURED on the
shipped `break_handler_safety_check`, one RTL file, rc 2 both times, the same
valid enumeration in the report, the ONLY variable being `--json`:

    no --json    -> PASS,         NOT_APPLICABLE_BY_STRUCTURE
    with --json  -> NOT_MEASURED, partial_population, and the row read "the
                    gate reports its input was applicable and was NOT
                    examined" over a gate that had examined 1 file and said so.

BOTH DIRECTIONS ARE PINNED HERE. Every negative control below keeps the rc-0
disclosed-vacuous answer it has today: an input nobody read establishes
nothing, a mechanism that was FOUND is a zero denominator and not an absence,
and a report carrying the class token with no enumeration is not believed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import _flow_reason_taxonomy as T        # noqa: E402
import _structural_absence as SA         # noqa: E402
import fmeda_fault_injection_coverage as fi  # noqa: E402

CLS = SA.NOT_APPLICABLE_BY_STRUCTURE

#: run13's own RTL, reduced to the one property under test: a plain digital
#: design with no ECC / parity / lockstep anywhere.
PLAIN_RTL = """\
module spm (input clk, input rst, input y, output p);
  reg [31:0] acc;
  always @(posedge clk) acc <= rst ? 32'b0 : {acc[30:0], y};
  assign p = acc[31];
endmodule
"""
#: The other direction: a genuine SEC-DED-shaped ECC pair — a corrected-data
#: output NARROWER than the protected codeword input, PAIRED with a syndrome
#: port. `detect_safety_mechanism` must keep firing on this.
ECC_RTL = """\
module ham_enc(input [3:0] data_in, output [6:0] code_out);
  assign code_out = 7'b0;
endmodule
module ham_dec(input [6:0] code_in, output [3:0] data_out,
               output syndrome_err);
  assign data_out = code_in[3:0];
  assign syndrome_err = 1'b0;
endmodule
"""
#: A mechanism that IS present but has no encoder to build stimulus from.
#: Guard (ii): the subject was FOUND, so this is a zero denominator and must
#: NOT reach the decided class.
DECODER_ONLY_RTL = """\
// ISO-26262 ASIL-D parity-protected register file
module par_dec(input [8:0] code_in, output [7:0] data_out,
               output parity_err);
  assign data_out = code_in[7:0];
  assign parity_err = 1'b0;
endmodule
"""


def _project(tmp_path: Path, rtl: str = None, name: str = "dut.v",
             make_rtl_dir: bool = True) -> Path:
    p = tmp_path / "proj"
    rtl_dir = p / "phase2" / "stage1" / "rtl"
    if make_rtl_dir:
        rtl_dir.mkdir(parents=True)
        if rtl is not None:
            (rtl_dir / name).write_text(rtl)
    else:
        p.mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    return p


def _run_producer(project: Path, out_rel="reports/phase2/safety/f.json"):
    cp = subprocess.run(
        [sys.executable, str(PROG / "fmeda_fault_injection_coverage.py"),
         str(project), "--rtl-dir", "phase2/stage1/rtl", "--asil", "D",
         "--json", out_rel],
        capture_output=True, text=True, cwd=str(project))
    rpt = project / out_rel
    report = json.loads(rpt.read_text()) if rpt.is_file() else None
    return cp, report


# ── 1. the reader's half of guard (i): the report channel must carry it ───
def _break_step(cmd: str) -> dict:
    return {"id": "T1", "name": "reader probe", "stage": "stage1",
            "gate": {"program_exit_zero": cmd}}


def test_a_class_token_with_no_enumeration_is_still_refused():
    """Guard (i) at the reader, unchanged: passing the evidence along cannot
    admit a claim the checker never established."""
    assert T.infer_nonverdict_reason(
        message="no safety mechanism found",
        evidence={"reason_class": CLS,
                  SA.EVIDENCE_KEY: None}) == T.EXECUTION_ERROR
    assert T.infer_nonverdict_reason(
        message="no safety mechanism found",
        evidence={"reason_class": CLS,
                  SA.EVIDENCE_KEY: {"population": "modules",
                                    "scanned": 0, "found": 0}}) == \
        T.EXECUTION_ERROR


# ── 2. FS1: the absent subject class is decided, with its enumeration ─────
def test_the_producer_states_the_class_with_its_enumeration(tmp_path):
    proj = _project(tmp_path, PLAIN_RTL)
    cp, report = _run_producer(proj)
    assert cp.returncode == fi.RC_NON_VERDICT, (cp.returncode, cp.stdout)
    ev = SA.evidence_of(report)
    assert ev is not None, json.dumps(report, indent=1)
    assert ev["scanned"] >= SA.MIN_SCANNED and ev["found"] == 0
    assert "spm" in ev["scanned_names"]
    assert T.report_reason_class(report) == CLS


def test_the_producers_sentence_fits_the_consumers_stdout_window(tmp_path):
    """The stdout channel is `stdout[-300:]` at LINE START. A sentence longer
    than the window is a disclosure the window ate — the same defect the
    `VACUOUS_PASS:` token line was bounded for."""
    proj = _project(tmp_path, PLAIN_RTL)
    cp, _ = _run_producer(proj)
    assert T.infer_nonverdict_reason(message=cp.stdout[-300:]) == CLS, cp.stdout
    assert "VACUOUS_PASS" not in cp.stdout, (
        "the two channels make opposite claims and must never be printed "
        "together")


def test_the_second_gate_mirrors_the_class_and_does_not_re_derive_it(tmp_path):
    proj = _project(tmp_path, PLAIN_RTL)
    _run_producer(proj, "reports/phase2/safety/fmeda_coverage.json")
    cp = subprocess.run(
        [sys.executable, str(PROG / "fmeda_coverage_check.py"), str(proj),
         "--json", "reports/phase2/safety/gate.json"],
        capture_output=True, text=True, cwd=str(proj))
    gate = json.loads((proj / "reports/phase2/safety/gate.json").read_text())
    assert cp.returncode == fi.RC_NON_VERDICT, (cp.returncode, cp.stdout)
    assert T.report_reason_class(gate) == CLS
    assert SA.evidence_of(gate) == SA.evidence_of(
        json.loads((proj / "reports/phase2/safety/fmeda_coverage.json"
                    ).read_text())), "the two gates must not disagree"


# ── 3. the other direction: a safety design keeps FS1 MEASURED ────────────
def test_a_design_that_declares_safety_is_still_examined(tmp_path):
    proj = _project(tmp_path, ECC_RTL, "ecc.v")
    census: dict = {}
    spec = fi.detect_safety_mechanism(
        proj / "phase2" / "stage1" / "rtl", "", census=census)
    assert spec is not None, "a genuine ECC pair must still fire"
    assert spec.dec_out == "data_out" and spec.detect_port == "syndrome_err"
    # the census is filled either way — it records the SCAN, not the verdict —
    # and the absence is not claimable while the subject is present.
    assert census["modules"], census


def test_a_safety_design_reaches_the_injection_and_never_the_decided_state(
        tmp_path, monkeypatch):
    """THE POSITIVE CONTROL, end to end through `run()`.

    The injection itself is stubbed — and ONLY the injection. This arm runs
    inside the EDA image, which carries no `docker` CLI, so
    `resolve_injection_backend` raises `ImageNotResolvable` for any design that
    IS applicable; that is an arm artefact, reproduced identically on pristine
    main, and it is not what this test is about. Everything the ruling touches
    — the mechanism scan, the applicability decision, the branch that could
    claim an absence — runs for real. A design that declares safety must stay
    MEASURED: `applicable` true, judged on its DC, and carrying no
    `structural_absence` for anyone to read as a stand-down."""
    proj = _project(tmp_path, ECC_RTL, "ecc.v")
    monkeypatch.setattr(fi, "run_injection_iverilog",
                        lambda *a, **k: (1, "", "injection stubbed"))

    class _Args:
        rtl_dir = "phase2/stage1/rtl"
        doc = None
        enc_module = dec_module = None
        enc_in = enc_out = dec_in = dec_out = detect_port = None
        data_width = code_width = 0
        rtl_file = None
        asil = "D"
        min_dc = None
        max_vectors = 8
        timeout = 30
        json = None

    rc, rep = fi.run(proj, _Args())
    assert rep["applicable"] is True, json.dumps(rep, indent=1)
    assert SA.evidence_of(rep) is None, json.dumps(rep, indent=1)
    assert rc != fi.RC_NON_VERDICT, (rc, rep)
    assert T.report_reason_class(rep) != CLS


def test_a_mechanism_that_was_found_is_a_zero_denominator_not_an_absence(
        tmp_path):
    """Guard (ii): FOUND-but-examined-nothing is not this class. The decoder
    is a declared parity mechanism with no encoder to build stimulus from."""
    proj = _project(tmp_path, DECODER_ONLY_RTL, "par.v")
    cp, report = _run_producer(proj)
    assert report.get("applicable") is False
    assert SA.evidence_of(report) is None, json.dumps(report, indent=1)
    assert cp.returncode == 0, (cp.returncode, cp.stdout)
    assert "VACUOUS_PASS" in cp.stdout, cp.stdout


# ── 4. an input nobody read establishes nothing ───────────────────────────
def test_an_rtl_dir_with_no_hdl_keeps_its_disclosed_vacuous_answer(tmp_path):
    proj = _project(tmp_path, rtl=None)          # dir exists, no .v/.sv
    cp, report = _run_producer(proj)
    assert cp.returncode == 0, (cp.returncode, cp.stdout)
    assert report["verdict"] == "UNMEASURED_NO_RTL_READ"
    assert SA.evidence_of(report) is None, json.dumps(report, indent=1)
    assert "VACUOUS_PASS" in cp.stdout, cp.stdout


def test_an_absent_rtl_dir_is_still_a_fail_not_an_absence(tmp_path):
    proj = _project(tmp_path, make_rtl_dir=False)
    cp, report = _run_producer(proj)
    assert cp.returncode == 1, (cp.returncode, cp.stdout)
    assert SA.evidence_of(report) is None, json.dumps(report, indent=1)


def test_rtl_that_parses_to_no_module_establishes_nothing(tmp_path):
    """A file set that yielded no module has enumerated an EMPTY population,
    which `_structural_absence.absence` refuses in its own right."""
    proj = _project(tmp_path, "// only a comment, no module here\n", "c.v")
    cp, report = _run_producer(proj)
    assert cp.returncode == 0, (cp.returncode, cp.stdout)
    assert SA.evidence_of(report) is None, json.dumps(report, indent=1)
    assert fi.safety_mechanism_absence({}, "phase2/stage1/rtl") is None
    assert fi.safety_mechanism_absence(
        {"modules": [], "rtl_files": ["c.v"]}, "phase2/stage1/rtl") is None


def test_the_second_gate_mirrors_nothing_when_there_is_nothing_to_mirror(
        tmp_path):
    """The mirror is not a second scanner: with no enumeration upstream the
    gate keeps the disclosed vacuous pass it has today."""
    res = fi  # noqa: F841 — module kept in scope for the import assertion
    import fmeda_coverage_check as fc
    out = fc.check({"applicable": False, "verdict": "NOT_APPLICABLE",
                    "reason": "no safety mechanism"}, None, None)
    assert out["verdict"] == "VACUOUS_PASS"
    assert SA.evidence_of(out) is None, out
    # and a token with no enumeration cannot borrow the decided state either
    out = fc.check({"applicable": False, "reason_class": CLS,
                    SA.EVIDENCE_KEY: {"population": "m", "scanned": 0,
                                      "found": 0}}, None, None)
    assert out["verdict"] == "VACUOUS_PASS", out
