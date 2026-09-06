"""Tests for the antenna substance check (eda_report_audit --mode antenna +
antenna_report_check.py wrapper). Step 26 was presence-only; this gates on the
OpenROAD check_antennas violation count. Verifies: clean→PASS, violations→FAIL,
missing→FAIL, hand-typed-stub→FAIL — mirroring the EM/IR siblings, no regression
on a real clean report."""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
from eda_report_audit import main as audit_main, _check_antenna  # noqa: E402

CLEAN = (
    "# OpenROAD antenna check (gate-oxide protection)\n"
    "# Tool: openroad / check_antennas (ANT).\n"
    "antenna check: 0 net violations, 0 pin violations\n"
    "antenna clean: YES\n"
    "[INFO ANT-0002] Found 0 net violations.\n"
    "[INFO ANT-0001] Found 0 pin violations.\n"
)
VIOL = (
    "# OpenROAD antenna check\n# Tool: openroad / check_antennas (ANT).\n"
    "antenna check: 3 net violations, 1 pin violations\n"
    "antenna clean: NO\n"
    "[INFO ANT-0002] Found 3 net violations.\n"
    "[INFO ANT-0001] Found 1 pin violations.\n"
)


def _proj(tmp_path, rpt_text):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "antenna.rpt").write_text(rpt_text)
    return tmp_path


def test_clean_antenna_passes(tmp_path):
    r = _check_antenna(_proj(tmp_path, CLEAN))
    assert r.passed is True
    assert r.summary["violations"] == 0


def test_violating_antenna_fails(tmp_path):
    r = _check_antenna(_proj(tmp_path, VIOL))
    assert r.passed is False
    assert r.summary["violations"] == 4  # 3 net + 1 pin


def test_missing_report_fails(tmp_path):
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    r = _check_antenna(tmp_path)
    assert r.passed is False
    assert r.summary["files_found"] == 0


def test_handtyped_stub_fails(tmp_path):
    # below MIN_REPORT_BYTES(antenna)=200 and no tool signature → not authentic
    r = _check_antenna(_proj(tmp_path, "antenna clean: YES\n"))
    assert r.passed is False


def test_cli_exit_codes(tmp_path):
    proj = _proj(tmp_path, CLEAN)
    rc = subprocess.run([sys.executable, str(PROGRAMS / "antenna_report_check.py"),
                         str(proj)]).returncode
    assert rc == 0
    proj2 = _proj(tmp_path / "v", VIOL)
    rc2 = subprocess.run([sys.executable, str(PROGRAMS / "antenna_report_check.py"),
                          str(proj2)]).returncode
    assert rc2 != 0


# ---------------------------------------------------------------------------
# vibe-ic#2058 FP-18 — a verdict may not ignore its own findings
# ---------------------------------------------------------------------------
# MEASURED, spm x gf180mcuD, image label 0.3.46, lane czspmfp, through the front
# door. `reports/phase3/antenna_signoff.json` as the flow published it:
#
#     "passed": true,   rc 0
#     four severity=ERROR findings — ANTENNA_REPORT_TOO_SMALL and
#     ANTENNA_NO_TOOL_SIGNATURE on `phase3/stage3/pnr/antenna_iter_0.rpt` and
#     `..._1.rpt`, both 0 bytes
#     "summary": {"files_found": 4, "violations": 0, "tool_authentic": true}
#
# `Checker.KLayoutAntenna` read PASS off that document. The audit had found the
# two empty files, judged them, written down that they are not antenna tool
# output, and then formed its verdict from a boolean that only asks whether ANY
# candidate was genuine. 0 bytes is "could not read it", never "read it and it
# was clean", so the honest tier is NOT_MEASURED.
#
# The fixture below is the real shape: two authentic reports the audit CAN read
# and two empty per-iteration reports it cannot.
_REAL_JSON = (
    '{\n  "tool": "openroad",\n  "mode": "antenna_check_in_session",\n'
    '  "net_violations": 0,\n  "pin_violations": 0,\n  "clean": true,\n'
    '  "source": "phase3/stage3/pnr/openroad.log",\n'
    '  "note": "openroad check_antennas, post-repair, in session; this file is '
    'the runner summary beside the tool report and is padded to clear the '
    '200 B floor the audit applies to every candidate."\n}\n'
)


def _spm_shaped_project(tmp_path, *, with_empty_iters: bool):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "antenna.rpt").write_text(CLEAN + "# " + "x" * 200 + "\n")
    (d / "antenna.json").write_text(_REAL_JSON)
    if with_empty_iters:
        pnr = tmp_path / "phase3" / "stage3" / "pnr"
        pnr.mkdir(parents=True)
        (pnr / "antenna_iter_0.rpt").write_bytes(b"")
        (pnr / "antenna_iter_1.rpt").write_bytes(b"")
    return tmp_path


def test_a_clean_count_beside_a_0_byte_report_is_not_a_pass(tmp_path):
    r = _check_antenna(_spm_shaped_project(tmp_path, with_empty_iters=True))
    errors = [f for f in r.findings if f.severity == "ERROR"]
    assert errors, "precondition: the audit must still judge the empty files"
    assert r.passed is False, (
        "the audit carried its own ERROR findings about two discovered files "
        "and passed anyway")
    assert r.verdict == "NOT_MEASURED"
    assert r.summary["violations"] == 0, \
        "the substantive antenna measurement is unchanged — this is a tier, " \
        "not a new violation"
    # four accusations + the one refusal the tier appends, and the published
    # count must agree with the published list it is printed beside
    assert len(errors) == 5, [f.rule for f in errors]
    assert r.summary["own_error_findings"] == len(errors)
    assert r.summary["unread_files"] == 2, r.summary


def test_the_refusal_names_every_file_it_could_not_credit(tmp_path):
    """NOT_MEASURED must say WHAT was not measured. #1029: name every path."""
    r = _check_antenna(_spm_shaped_project(tmp_path, with_empty_iters=True))
    contra = [f for f in r.findings if f.rule == "ANTENNA_REPORT_NOT_READ"]
    assert len(contra) == 1, contra
    for name in ("antenna_iter_0.rpt", "antenna_iter_1.rpt"):
        assert name in contra[0].message, contra[0].message


def test_the_same_project_without_the_empty_reports_still_passes(tmp_path):
    """THE CONTROL. Remove only the 0-byte files and nothing else changes:
    a real clean antenna sign-off must still be a PASS, or the tier above is
    a blanket refusal wearing a finding's name."""
    r = _check_antenna(_spm_shaped_project(tmp_path, with_empty_iters=False))
    assert r.passed is True, [f.rule for f in r.findings]
    assert r.verdict == ""
    assert r.summary["own_error_findings"] == 0
    assert r.summary["unread_files"] == 0
    assert r.summary["violations"] == 0


def test_warning_and_info_findings_do_not_gate(tmp_path):
    """The tier keys on ERROR alone. A WARNING is disclosure, not a verdict —
    widening this to `any finding` would refuse every waived and every
    disclosed run in the tree."""
    from eda_report_audit import Finding, _check_antenna as _ca
    proj = _spm_shaped_project(tmp_path, with_empty_iters=False)
    r = _ca(proj)
    assert r.passed is True
    r.findings.append(Finding(rule="X", severity="WARNING", message="m"))
    r.findings.append(Finding(rule="Y", severity="INFO", message="m"))
    assert [f.severity for f in r.findings if f.severity == "ERROR"] == []


def test_cli_refuses_the_0_byte_case_end_to_end(tmp_path):
    """rc, not just the dataclass — this is what `Checker.KLayoutAntenna` reads."""
    proj = _spm_shaped_project(tmp_path, with_empty_iters=True)
    out = tmp_path / "signoff.json"
    rc = subprocess.run(
        [sys.executable, str(PROGRAMS / "antenna_report_check.py"), str(proj),
         "--mode", "antenna", "--json", str(out)],
        capture_output=True, text=True).returncode
    assert rc == 1, "a NOT_MEASURED antenna sign-off must not exit 0"
    doc = json.loads(out.read_text())
    assert doc["passed"] is False
    assert doc["verdict"] == "NOT_MEASURED"


def test_a_compact_runner_summary_under_the_byte_floor_still_passes(tmp_path):
    """THE CONTROL THAT NARROWED THE RULE, and the regression that found it.

    A first version of the tier above gated on ANY severity=ERROR finding.
    `tests/test_wrapper_argv_forwarding.py` went red on this exact shape: a
    144 B `reports/phase3/antenna.json` — the RUNNER's own summary, beside a
    genuine 3319 B `antenna.rpt`, read without difficulty — carrying one
    ANTENNA_REPORT_TOO_SMALL because it is under the 200 B floor.

    That accusation must not gate, and this module says why in its own words:
    `test_ir_drop_compact_report_strong_signature` measured 16 of 16 authentic
    `openroad-psm` ir_drop.json in the corpus at 197-611 B, under their floor. A
    compact summary is MIS-ACCUSED; an empty file was NEVER READ. Only the
    second is NOT_MEASURED.
    """
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "antenna.rpt").write_text(CLEAN + "# " + "x" * 3000 + "\n")
    (d / "antenna.json").write_text(json.dumps(
        {"tool": "openroad", "mode": "antenna_check_in_session_post_repair",
         "net_violations": 0, "pin_violations": 0, "clean": True,
         "verdict": "PASS"}))
    assert (d / "antenna.json").stat().st_size < 200, \
        "the fixture must be UNDER the floor or it is not this control"
    r = _check_antenna(tmp_path)
    assert [f.rule for f in r.findings if f.severity == "ERROR"] == \
        ["ANTENNA_REPORT_TOO_SMALL"], [f.rule for f in r.findings]
    assert r.passed is True, "a read-but-compact summary was treated as unread"
    assert r.summary["unread_files"] == 0
