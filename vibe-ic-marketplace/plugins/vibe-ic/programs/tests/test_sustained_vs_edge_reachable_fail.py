#!/usr/bin/env python3
"""`sustained_vs_edge_check` could not emit the FAIL its docstring promises.

THE DEFECT. The gate's own header says `1 = FAIL (edge detector with no sustain
counter while spec says sustain)`. Two conditions had to hold for that rc to be
produced:

    a finding of severity ERROR   <- requires `spec_match`, which was only ever
                                     set from an explicitly supplied `--spec-text`
    or `--strict` with any WARN   <- requires the `--strict` flag

The one caller that runs this gate is the P0 umbrella, whose argv comes from
`flow_compliance_check._structural_gate_argv`. Its adapter row is
`("--rtl-dir",)` and it registers no bare flags for this gate, so it supplies
NEITHER. As invoked, both routes to rc 1 were closed: the gate printed the exact
finding it exists to report — `[WARN] ... signal=<sig>  sustain_counter=False` —
and exited 0, and the umbrella recorded PASS. `flow_compliance_check` names that
hazard in prose for a sibling gate ("clearing the bar precisely BECAUSE it is
incapable of failing") and the bar was never applied to this row; the table entry
`sustained_vs_edge_check: (0, 108)` reads as "0 FAILs across the corpus" when the
gate could not have produced one anywhere.

WHAT THESE TESTS PIN, both directions, because one direction is half the
property:

  * `test_umbrella_argv_can_now_reach_the_fail_verdict` — RED against the
    unfixed program. Umbrella argv, umbrella cwd, a project whose spec says a
    named signal is HELD for a duration and whose RTL edge-detects that same
    signal with no sustain counter. rc must be 1.

  * `test_umbrella_argv_still_reaches_pass_when_the_rtl_is_correct` — the gate
    must not have become always-fail. Same spec, same signal, but the RTL
    implements the sustain counter. rc must be 0.

  * `test_a_project_with_no_spec_sources_still_passes_and_says_so` — the third
    reachable state, and the one that keeps the PASS honest: nothing to compare
    against is rc 0 AND is disclosed as such rather than printed as a clean
    comparison.

  * `test_a_signal_name_inside_an_english_word_is_not_a_spec_match` — the
    false-positive the ERROR arm would otherwise acquire the moment it became
    reachable.

Every assertion is on an exit code or on emitted stdout. Nothing here greps the
source of the program under test. All fixtures are synthetic: no design, PDK or
part number appears in this file.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load_flow():
    """Import the umbrella so the tests drive the argv it REALLY builds.

    Re-typing `["--rtl-dir", str(rtl)]` here would agree with the umbrella by
    coincidence; the whole point of this defect is that the argv is the thing
    that closed the verdict off.
    """
    spec = importlib.util.spec_from_file_location(
        "fcc_sustained_reach", PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_sustained_reach"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()

#: Spec prose carrying a sustain-class word AND a duration, naming one signal.
#: Synthetic wording; the signal is a generic request line.
_SUSTAIN_SPEC = (
    "# Wake sequencing\n"
    "\n"
    "The wake_req line must be held low for 80 us before the wake event is\n"
    "generated. A shorter excursion is noise and must be ignored.\n"
)

#: The bug the gate exists to catch: a one-cycle edge detector standing in for
#: a held-for-a-duration condition. No counter anywhere in the module.
_EDGE_ONLY_RTL = """\
module top (
  input  wire clk,
  input  wire rst_n,
  input  wire wake_req,
  output reg  wake_evt
);
  reg wake_req_q;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wake_req_q <= 1'b0;
      wake_evt   <= 1'b0;
    end else begin
      wake_req_q <= wake_req;
      wake_evt   <= wake_req && !wake_req_q;
    end
  end
endmodule
"""

#: The same protocol implemented CORRECTLY: the level is counted while held and
#: the event only fires once the threshold is reached.
_SUSTAINED_RTL = """\
module top #(parameter WAKE_HOLD_CYC = 16'd4000) (
  input  wire clk,
  input  wire rst_n,
  input  wire wake_req,
  output reg  wake_evt
);
  reg [15:0] wake_req_hold;
  reg        wake_req_q;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wake_req_q    <= 1'b0;
      wake_req_hold <= 16'd0;
      wake_evt      <= 1'b0;
    end else begin
      wake_req_q <= wake_req;
      if (!wake_req)
        wake_req_hold <= wake_req_hold + 1;
      else
        wake_req_hold <= 16'd0;
      wake_evt <= (wake_req_hold >= WAKE_HOLD_CYC) && !wake_req && wake_req_q;
    end
  end
endmodule
"""


def _project(tmp_path, rtl_text, spec_text=None):
    """A synthetic project in the layout `_path_layout` describes."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(rtl_text)
    if spec_text is not None:
        docs = tmp_path / "phase1" / "input_doc"
        docs.mkdir(parents=True)
        (docs / "protocol.md").write_text(spec_text)
    return rtl


def _run_as_umbrella(project, rtl):
    """Exactly what the P0 umbrella does: its argv, its cwd, its timeout."""
    argv = F._structural_gate_argv("sustained_vs_edge_check", project,
                                   rtl_dir=rtl)
    return argv, subprocess.run(argv, cwd=project, capture_output=True,
                                text=True, timeout=60)


# ---------------------------------------------------------------------------
# 1. THE MISSING VERDICT — red against the unfixed program
# ---------------------------------------------------------------------------
def test_umbrella_argv_can_now_reach_the_fail_verdict(tmp_path):
    """The verdict the docstring promises, from the argv the umbrella builds.

    Unfixed, this is rc 0: `spec_match` needs `--spec-text`, the umbrella does
    not pass it, so every finding is a WARN and every WARN is benign without
    `--strict`, which the umbrella does not pass either.
    """
    rtl = _project(tmp_path, _EDGE_ONLY_RTL, _SUSTAIN_SPEC)
    argv, r = _run_as_umbrella(tmp_path, rtl)

    assert "--spec-text" not in argv and "--strict" not in argv, (
        "this test is only meaningful while the umbrella supplies neither "
        f"flag; if that changed, re-derive the defect: {argv}")
    assert r.returncode == 1, (
        "spec says a named signal is HELD for a duration and the RTL "
        "edge-detects that same signal with no sustain counter — the gate's "
        f"whole reason to exist — yet it exited {r.returncode}.\n"
        f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    assert "FAIL" in r.stdout.splitlines()[0], r.stdout
    assert "[ERROR]" in r.stdout, (
        f"rc 1 without an ERROR finding to justify it: {r.stdout}")
    assert "wake_req" in r.stdout, (
        f"the verdict must name the signal it is about: {r.stdout}")


def test_the_fail_is_evidence_backed_in_the_json_report(tmp_path):
    """Same run, structured. The ERROR must carry the clause it was derived
    from and the provenance of the document that clause came from — otherwise
    rc 1 is an assertion rather than a finding."""
    rtl = _project(tmp_path, _EDGE_ONLY_RTL, _SUSTAIN_SPEC)
    out = tmp_path / "reports"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sustained_vs_edge_check.py"),
         "--rtl-dir", str(rtl), "--out-dir", str(out)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"

    doc = json.loads((out / "sustained_vs_edge_check.json").read_text())
    assert doc["status"] == "FAIL", doc
    assert doc["spec_provenance"] == "discovered", doc
    assert doc["spec_clauses"] >= 1, doc
    assert doc["spec_sources"], doc
    errs = [f for f in doc["findings"] if f["severity"] == "ERROR"]
    assert len(errs) == 1, doc["findings"]
    assert errs[0]["signal"] == "wake_req", errs[0]
    assert errs[0]["has_sustain_counter"] is False, errs[0]
    assert "held low for 80 us" in errs[0]["spec_match"], errs[0]


# ---------------------------------------------------------------------------
# 2. THE OTHER DIRECTION — the gate must not have become always-fail
# ---------------------------------------------------------------------------
def test_umbrella_argv_still_reaches_pass_when_the_rtl_is_correct(tmp_path):
    """Same spec clause, same signal, same umbrella argv — but the RTL COUNTS
    the held level instead of edge-detecting it. That is the design the spec
    asked for, and it must be rc 0.

    Without this, "the gate can now FAIL" is satisfied by a gate that can only
    ever FAIL, which is the same defect pointing the other way.
    """
    rtl = _project(tmp_path, _SUSTAINED_RTL, _SUSTAIN_SPEC)
    _argv, r = _run_as_umbrella(tmp_path, rtl)
    assert r.returncode == 0, (
        "RTL that implements the sustain counter the spec asked for was "
        f"failed:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    assert "PASS" in r.stdout.splitlines()[0], r.stdout
    # and it must be a COMPARED pass, not an accidental one
    assert "spec: discovered" in r.stdout, (
        f"the PASS must state that it did read a spec: {r.stdout}")


def test_a_spec_clause_about_another_signal_does_not_fail_this_one(tmp_path):
    """The ERROR arm is keyed on the SIGNAL, not on the mere presence of a
    sustain sentence in the project. A sustain requirement about an unrelated
    line must leave an ordinary edge detector alone."""
    rtl = _project(tmp_path, _EDGE_ONLY_RTL,
                   "The cal_ref input must be maintained for 5 ms while the "
                   "reference settles.\n")
    _argv, r = _run_as_umbrella(tmp_path, rtl)
    assert r.returncode == 0, (
        "a sustain clause naming a DIFFERENT signal failed an unrelated edge "
        f"detector:\n{r.stdout}\n{r.stderr}")


def test_a_project_with_no_spec_sources_still_passes_and_says_so(tmp_path):
    """rc 0 stays rc 0 for a project that ships no spec prose — and the run
    discloses that it compared nothing, so the PASS cannot be misread as a
    clean comparison. This is the state EVERY umbrella run was silently in."""
    rtl = _project(tmp_path, _EDGE_ONLY_RTL, spec_text=None)
    _argv, r = _run_as_umbrella(tmp_path, rtl)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "spec: none" in r.stdout, (
        "a PASS reached without reading any spec must say so, or it reads "
        f"identically to a PASS that compared and found nothing: {r.stdout}")
    assert "NOT compared" in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# 3. THE FALSE POSITIVE THE REACHABLE ARM WOULD OTHERWISE ACQUIRE
# ---------------------------------------------------------------------------
def test_a_signal_name_inside_an_english_word_is_not_a_spec_match(tmp_path):
    """`en` is a substring of "when", "enable" and "length".

    While no sustain clause could ever be built, substring containment was a
    harmless way to relate a clause to a signal. The moment the ERROR arm
    became reachable it became a false-alarm generator: any timing sentence
    about an "enable" would condemn a two-letter signal. Boundary-matched, this
    is a WARN and rc 0.
    """
    rtl = _project(tmp_path, """\
module top (input wire clk, input wire en, output reg pulse);
  reg en_q;
  always @(posedge clk) begin
    en_q  <= en;
    pulse <= en && !en_q;
  end
endmodule
""", "The enable line must be held stable for 10 ms during calibration.\n")
    _argv, r = _run_as_umbrella(tmp_path, rtl)
    assert r.returncode == 0, (
        "'en' matched a clause that only contains it inside the word "
        f"'enable':\n{r.stdout}\n{r.stderr}")
    assert "[ERROR]" not in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# 4. THE EXPLICIT ROUTE IS UNCHANGED, AND ITS OWN SILENT-DOWNGRADE IS CLOSED
# ---------------------------------------------------------------------------
def test_explicit_spec_text_still_drives_the_error_arm(tmp_path):
    """Discovery is the DEFAULT, not a replacement: a caller that names a
    document still gets that document."""
    rtl = _project(tmp_path, _EDGE_ONLY_RTL, spec_text=None)
    spec = tmp_path / "elsewhere.txt"
    spec.write_text(_SUSTAIN_SPEC)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sustained_vs_edge_check.py"),
         "--rtl-dir", str(rtl), "--spec-text", str(spec)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    assert "spec: explicit" in r.stdout, r.stdout


def test_a_spec_text_that_does_not_exist_is_not_silently_a_clean_run(tmp_path):
    """The same defect one layer up: a caller that ASKED to compare against a
    document that is not there used to fall into the no-spec mode and print a
    PASS. Input-missing is rc 2 everywhere else in this gate."""
    rtl = _project(tmp_path, _EDGE_ONLY_RTL, _SUSTAIN_SPEC)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "sustained_vs_edge_check.py"),
         "--rtl-dir", str(rtl), "--spec-text", str(tmp_path / "absent.txt")],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, (
        f"a missing --spec-text produced rc {r.returncode}: "
        f"{r.stdout}\n{r.stderr}")


# ---------------------------------------------------------------------------
# 5. THE UMBRELLA'S OWN RECORD
# ---------------------------------------------------------------------------
def test_the_umbrella_records_the_reachable_fail_as_a_fail(tmp_path):
    """END-TO-END. rc 1 from the gate is worth nothing if the umbrella files it
    somewhere benign, which is exactly how 39 gates stayed silent (#492)."""
    rtl = _project(tmp_path, _EDGE_ONLY_RTL, _SUSTAIN_SPEC)
    assert rtl.is_dir()
    _passed, fails, skips, _waivers = F._run_structural_rtl_gates(tmp_path)
    joined_fails = " ".join(fails)
    skip_names = {s.split(" ", 1)[0] for s in skips}
    assert "sustained_vs_edge_check" in joined_fails, (
        "the gate returned rc 1 and the umbrella did not report it as a "
        f"failure.\nfails={fails[:10]}\nskips={sorted(skip_names)[:10]}")


def test_the_umbrella_does_not_fail_the_correct_design(tmp_path):
    """The paired direction end-to-end: the same umbrella, the same project
    shape, RTL that honours the spec — no failure attributed to this gate."""
    rtl = _project(tmp_path, _SUSTAINED_RTL, _SUSTAIN_SPEC)
    assert rtl.is_dir()
    _passed, fails, _skips, _waivers = F._run_structural_rtl_gates(tmp_path)
    assert "sustained_vs_edge_check" not in " ".join(fails), (
        f"correct RTL was failed by the umbrella: "
        f"{[f for f in fails if 'sustained' in f]}")


# ---------------------------------------------------------------------------
# 6. THE CONVERSION LICENCE STILL HOLDS
# ---------------------------------------------------------------------------
def test_the_gate_is_still_licensed_by_the_measurement_table():
    """`flow_compliance_check` licenses an adapter row only for a gate measured
    at 0 new FAILs with a non-empty denominator over the whole corpus. Making
    the FAIL arm reachable is a change to that measurement's SUBJECT, so the
    row has to still be true: re-measured over the 108 tracked rtl directories
    with this change in place, the gate is rc 0 on 108/108 and discloses a
    non-zero `files scanned` on 108/108 — unchanged. This asserts the recorded
    licence, not the sweep; the sweep is quoted in the commit."""
    assert F.P0_RTL_DIR_GROUP_MEASUREMENT["sustained_vs_edge_check"] == (
        0, F.P0_CORPUS_DENOMINATOR)
    assert "sustained_vs_edge_check" in F._STRUCTURAL_GATE_ARGV_ADAPTERS
    assert "sustained_vs_edge_check" not in F._STRUCTURAL_GATE_BARE_FLAGS, (
        "wiring --strict would escalate every edge detector with no counter "
        "nearby — an ordinary and usually-correct RTL idiom — into a failure. "
        "The reachable verdict is the evidence-backed ERROR arm, not this.")
