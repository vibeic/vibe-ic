"""ORGANIC #773 — l10_tb_conformance_check class/kind-aware A/M-track waiver.

Before this fix l10_tb_conformance_check demanded a digital-TB id-substring
trace for EVERY L10 case regardless of `kind` and emitted only rc 0/1/2. A
`kind=verification_intent` case (satisfiable only by the --skip-analog'd A/M
track — LDO line/load regulation + SNDR, multi-corner TT/SS/FF, tool
disclosure, golden-GDS cross-check) therefore hard-FAILed Step 4 even though
the runner's own verdict was PASS_WITH_WAIVERS. The sibling
`cpu_functional_oracle_waiver_check` (#651) is class-aware (rc=3 +
`PASS_WITH_WAIVERS:` sentinel → WAIVED-DEFERRED); this gate now mirrors it.

§4.05 NO-LEAK (load-bearing): the relaxation is kind-scoped AND anchor-gated.
A genuine digital case (`cmd_response` / `error_path` / …) with no tb evidence
must STILL FAIL even under --skip-analog, and an UNANCHORED verification_intent
case (no reviewable capability-gap bridge) must ALSO still FAIL — so the
relaxation can never mask a missing digital testbench.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "l10_tb_conformance_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l10_tb_conformance_check as gate  # noqa: E402


# ---------------------------------------------------------------------------
# helpers — build a faithful project tree matching the #773 現象
# ---------------------------------------------------------------------------
def _make_project(tmp_path, l10_cases, *, tb_text="module tb_dummy;\nendmodule\n",
                  summary_text="", with_anchor=True):
    """Build phase1/phase2 tree. `with_anchor` writes the reviewable
    sim/results.xml capability-gap bridge (#651-style)."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    l10 = gd / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": l10_cases}))

    sim = tmp_path / "phase2" / "stage1" / "sim"
    tb = sim / "tb"
    tb.mkdir(parents=True)
    (tb / "tb_dummy.v").write_text(tb_text)
    work = sim / "work"
    work.mkdir(parents=True)
    (work / "summary.txt").write_text(summary_text)

    if with_anchor:
        (sim / "results.xml").write_text(
            "<results><verdict>CONNECTIVITY_PASS</verdict>"
            "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
            "<functional_verified>false</functional_verified></results>")
    return l10, tb, work / "summary.txt"


# The exact four cases from the #773 observation (u_hawaii_adc delta-sigma ADC).
_VERIFICATION_INTENT_CASES = [
    {"id": "LDO_LINE_LOAD_SNDR", "kind": "verification_intent",
     "description": "LDO line/load regulation + SNDR (analog A/M track)"},
    {"id": "MULTI_CORNER_TT_SS_FF", "kind": "verification_intent",
     "description": "multi-corner TT/SS/FF"},
    {"id": "TOOL_DISCLOSURE", "kind": "verification_intent",
     "description": "tool disclosure"},
    {"id": "GOLDEN_GDS_XCHECK", "kind": "verification_intent",
     "description": "golden-GDS cross-check"},
]


# ---------------------------------------------------------------------------
# REPRODUCE — shipped behaviour preserved when --skip-analog is NOT passed
# ---------------------------------------------------------------------------
def test_repro_verification_intent_hard_fails_without_skip_analog(tmp_path):
    """The #773 現象 on shipped code: 4 verification_intent cases, no digital
    trace, no --skip-analog → rc=1 hard-FAIL (Step-4 cascade)."""
    l10, tb, summary = _make_project(tmp_path, _VERIFICATION_INTENT_CASES)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(l10), "--tb-dir", str(tb),
        "--summary", str(summary), "--out", str(out),
    ])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["not_executed"] == 4
    assert data["fail"] == 0 and data["ok"] == 0 and data["waived"] == 0


# ---------------------------------------------------------------------------
# FIX — class/kind-aware A/M-track waiver under anchored --skip-analog
# ---------------------------------------------------------------------------
def test_verification_intent_waived_under_skip_analog_with_anchor(tmp_path):
    """With --skip-analog + a reviewable capability-gap anchor, the four
    verification_intent cases are WAIVED-DEFERRED → rc=3 (#651 mirror)."""
    l10, tb, summary = _make_project(tmp_path, _VERIFICATION_INTENT_CASES)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(l10), "--tb-dir", str(tb),
        "--summary", str(summary), "--out", str(out),
        "--skip-analog", "--project", str(tmp_path),
    ])
    assert rc == 3
    data = json.loads(out.read_text())
    assert data["waived"] == 4 and data["fail"] == 0
    assert data["capability_gap"] == gate.CAP_ANALOG_VERIFICATION_INTENT
    for r in data["results"]:
        assert r["status"] == "waived"
        assert r["review_required"] is True
        assert r["capability_gap"] == gate.CAP_ANALOG_VERIFICATION_INTENT


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — the genuine defect the relaxation must NOT mask
# ---------------------------------------------------------------------------
def test_noleak_digital_cmd_response_still_fails_under_skip_analog(tmp_path):
    """§4.05 — a genuine digital cmd_response case with NO tb evidence must
    STILL hard-FAIL (rc=1) even under --skip-analog, even when a sibling
    verification_intent case is legitimately waived. The relaxation is
    kind-scoped; it cannot mask a missing digital testbench."""
    cases = [
        {"id": "LDO_LINE_LOAD_SNDR", "kind": "verification_intent"},
        {"id": "GET_ID_DIGITAL", "kind": "cmd_response", "opcode": "70"},
    ]
    l10, tb, summary = _make_project(tmp_path, cases)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(l10), "--tb-dir", str(tb),
        "--summary", str(summary), "--out", str(out),
        "--skip-analog", "--project", str(tmp_path),
    ])
    assert rc == 1, "digital cmd_response with no evidence must STILL FAIL"
    data = json.loads(out.read_text())
    # the verification_intent case is waived; the digital one remains an
    # explicit Step-4 blocker without pretending an unrun test actually failed.
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["GET_ID_DIGITAL"]["status"] == "NOT_EXECUTED"
    assert by_id["LDO_LINE_LOAD_SNDR"]["status"] == "waived"
    assert data["not_executed"] == 1
    assert data["fail"] == 0 and data["waived"] == 1


def test_noleak_unanchored_verification_intent_still_fails(tmp_path):
    """§4.05 — an UNANCHORED verification_intent case (no reviewable
    capability-gap bridge) under --skip-analog must STILL FAIL (rc=1). An
    unanchored, unreviewable blanket waiver is NOT honoured."""
    l10, tb, summary = _make_project(
        tmp_path, _VERIFICATION_INTENT_CASES, with_anchor=False)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(l10), "--tb-dir", str(tb),
        "--summary", str(summary), "--out", str(out),
        "--skip-analog", "--project", str(tmp_path),
    ])
    assert rc == 1, "unanchored verification_intent waiver must NOT be honoured"
    data = json.loads(out.read_text())
    assert data["not_executed"] == 4
    assert data["fail"] == 0 and data["waived"] == 0


def test_noleak_digital_case_never_waived_even_with_anchor(tmp_path):
    """§4.05 — even a fully-anchored --skip-analog run does NOT waive a
    non-verification_intent (digital) case. is_verification_intent gates the
    relaxation by KIND, not by --skip-analog alone."""
    cases = [{"id": "ERR_CRC", "kind": "error_path"}]
    l10, tb, summary = _make_project(tmp_path, cases)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(l10), "--tb-dir", str(tb),
        "--summary", str(summary), "--out", str(out),
        "--skip-analog", "--project", str(tmp_path),
    ])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["waived"] == 0 and data["fail"] == 0
    assert data["not_executed"] == 1


# ---------------------------------------------------------------------------
# classification helpers — chip-AGNOSTIC kind vocabulary, not chip literals
# ---------------------------------------------------------------------------
def test_is_verification_intent_kind_synonyms():
    assert gate.is_verification_intent({"kind": "verification_intent"})
    assert gate.is_verification_intent({"category": "analog_verification"})
    assert gate.is_verification_intent({"type": "mixed_signal_verification"})
    # genuine digital kinds are NOT verification_intent
    assert not gate.is_verification_intent({"kind": "cmd_response"})
    assert not gate.is_verification_intent({"category": "error_path"})
    assert not gate.is_verification_intent({"id": "X"})  # no kind


def test_anchor_requires_capability_gap_or_connectivity(tmp_path):
    # a plain functional PASS results.xml is NOT a reviewable analog anchor
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text(
        "<results><verdict>PASS</verdict></results>")
    assert gate.analog_skip_anchor(str(tmp_path), None) is None
    # a connectivity / capability-gap bridge IS a reviewable anchor
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap></results>")
    assert gate.analog_skip_anchor(str(tmp_path), None) is not None


# ---------------------------------------------------------------------------
# #478 END-STATE — direct-write a tmp_path artifact, invoke the REAL program
# via subprocess, assert the returncode AND the line-start sentinel
# ---------------------------------------------------------------------------
def test_issue478_endstate_subprocess_rc3_and_sentinel(tmp_path):
    """#478 END-STATE: DIRECT-write the L10 artifact + project tree, invoke the
    real l10_tb_conformance_check.py via subprocess, and assert (a) rc==3 and
    (b) a line-start `PASS_WITH_WAIVERS` sentinel that flow_compliance_check's
    _stdout_signals_waiver recognises to promote Step 4 to WAIVED-DEFERRED."""
    l10, tb, summary = _make_project(tmp_path, _VERIFICATION_INTENT_CASES)
    out = tmp_path / "reports" / "gates" / "l10_tb_conformance.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--l10", str(l10), "--tb-dir", str(tb),
         "--summary", str(summary), "--out", str(out),
         "--skip-analog", "--project", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 3, (
        f"expected rc=3 PASS_WITH_WAIVERS, got {proc.returncode}\n"
        f"STDOUT:{proc.stdout}\nSTDERR:{proc.stderr}")
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # mirror flow_compliance_check._stdout_signals_waiver: token at line-start
    assert any(line.lstrip().startswith("PASS_WITH_WAIVERS")
               for line in combined.splitlines()), \
        f"no line-start PASS_WITH_WAIVERS sentinel in:\n{combined}"
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["waived"] == 4 and data["fail"] == 0
    assert data["capability_gap"] == gate.CAP_ANALOG_VERIFICATION_INTENT


def test_issue478_endstate_subprocess_noleak_digital_rc1(tmp_path):
    """#478 END-STATE (no-leak twin): a digital cmd_response with no evidence,
    invoked via subprocess under --skip-analog, must exit rc=1 — NOT rc=3 —
    and must NOT print the waiver sentinel for that genuine FAIL."""
    cases = [{"id": "GET_ID_DIGITAL", "kind": "cmd_response", "opcode": "70"}]
    l10, tb, summary = _make_project(tmp_path, cases)
    out = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--l10", str(l10), "--tb-dir", str(tb),
         "--summary", str(summary), "--out", str(out),
         "--skip-analog", "--project", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, (
        f"digital no-evidence case must FAIL rc=1, got {proc.returncode}")
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert not any(line.lstrip().startswith("PASS_WITH_WAIVERS")
                   for line in combined.splitlines()), \
        "a genuine digital FAIL must NOT emit the waiver sentinel"
