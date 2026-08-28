"""v0.3.9 — #507 (CRITICAL): lvs_report_check FALSE-PASS. The LVS audit
(`eda_report_audit:lvs`) decided `passed` SOLELY from (mismatch-category
keyword present + tool signature) and NEVER parsed netgen's terminal
verdict token — so a report whose verdict is 'Netlists do not match.'
(41× in the real spm_e2e) reported passed=true, letting a non-LVS-clean
design pass Step-31 sign-off. Directly threatens tapeout integrity.

Fix mirrors the runner's #477 step_lvs logic so gate and runner agree:
  * MATCH  ('Circuits/Netlists match uniquely')  → eligible PASS
  * MISMATCH ('do not match' / 'failed pin matching' / 'NET MISMATCH'
    / '失配')                                     → hard FAIL (named)
  * neither (compare killed mid-run)             → INCOMPLETE FAIL
A mismatch token is AUTHORITATIVE — FAILs even when sub-cells also
printed 'match uniquely' and even when categories + signature pass.

These fixtures embed real netgen terminal-verdict lines; the dominant
mismatch case reproduces the exact spm_e2e defect shape. Chip-AGNOSTIC.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as ERA  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# A realistic netgen footer carrying mismatch categories + signature
# (and padded past the lvs byte-size authenticity floor, ~1536 B) so the
# PRE-#507 (category+signature only) path would have PASSed — isolating
# the terminal-verdict axis under test.
_NETGEN_SIG = (
    "Netgen 1.5.272 compare\n"
    "Equivalence test for cells chip_top and chip_top\n"
    "Contents of circuit 1:  Circuit: 'chip_top'\n"
    "Contents of circuit 2:  Circuit: 'chip_top'\n"
    "Device classes for circuit 1:  instance net device parameter\n"
    "Device classes for circuit 2:  instance net device parameter\n"
    + ("Subcircuit summary: sky130_fd_sc_hd__inv_2 instances net device "
       "parameter count balanced across both netlists.\n") * 24
)


def _write_lvs(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "lvs.rpt").write_text(_NETGEN_SIG + body)
    return tmp_path


def _audit(tmp_path: Path):
    return ERA._check_lvs(tmp_path)


def test_do_not_match_report_fails(tmp_path):
    # the exact #507 shape: mismatch token present (×many), categories +
    # signature present → must FAIL, not PASS.
    proj = _write_lvs(tmp_path, "Netlists do not match.\n" * 41)
    r = _audit(proj)
    assert r.passed is False
    assert r.summary["terminal_verdict"] == "MISMATCH"
    assert any(f.rule == "LVS_NETLISTS_DO_NOT_MATCH" for f in r.findings)


def test_failed_pin_matching_fails(tmp_path):
    proj = _write_lvs(tmp_path, "Top level cell failed pin matching.\n")
    r = _audit(proj)
    assert r.passed is False
    assert r.summary["terminal_verdict"] == "MISMATCH"


def test_match_uniquely_report_passes(tmp_path):
    # clean report → PASS.
    proj = _write_lvs(tmp_path, "Final result: Circuits match uniquely.\n")
    r = _audit(proj)
    assert r.passed is True
    assert r.summary["terminal_verdict"] == "MATCH"


def test_subcells_match_but_top_mismatch_fails(tmp_path):
    # mismatch is AUTHORITATIVE even when sub-cells matched.
    proj = _write_lvs(
        tmp_path,
        "Circuits match uniquely.\n" * 5 + "Netlists do not match.\n")
    r = _audit(proj)
    assert r.passed is False
    assert r.summary["terminal_verdict"] == "MISMATCH"


def test_no_terminal_verdict_is_incomplete_fail(tmp_path):
    # netgen killed mid-run → no terminal token → INCOMPLETE FAIL (#477).
    proj = _write_lvs(tmp_path, "Flattening unmatched subcell ...\n")
    r = _audit(proj)
    assert r.passed is False
    assert r.summary["terminal_verdict"] == "INCOMPLETE"
    assert any(f.rule == "LVS_NO_TERMINAL_VERDICT" for f in r.findings)


def test_e2e_real_spm_artifact_fails_with_json(tmp_path):
    # #507 acceptance, verbatim CLI shape, against the REAL do-not-match
    # artifact when present on this host (skips cleanly off-host).
    real = require_corpus("spm_e2e_v034")
    rpt = real / "reports" / "phase3" / "lvs.rpt"
    if not rpt.is_file():
        import pytest
        pytest.skip("real spm_e2e_v034 artifact not on this host")
    # The real artifact is MUTABLE: the GDSII-LVS feature (#508/#509) was
    # completed and the field runner-auto LVS upgrade (#515/#516) regenerated
    # this report to a UNIQUE MATCH. When the on-disk report is no longer a
    # do-not-match, this case's PRECONDITION ("REAL do-not-match artifact") is
    # gone — assert nothing here; the do-not-match → FAIL path stays fully
    # covered by the synthetic fixtures above (test_do_not_match_report_fails,
    # test_failed_pin_matching_fails, test_subcells_match_but_top_mismatch_fails,
    # test_no_terminal_verdict_is_incomplete_fail). chip-AGNOSTIC: pure verdict
    # tokens, no chip literal in the gate.
    _txt = rpt.read_text(errors="replace").lower()
    _is_mismatch = ("do not match" in _txt or "failed pin matching" in _txt
                    or "net mismatch" in _txt)
    if not _is_mismatch:
        import pytest
        pytest.skip("real spm_e2e_v034 artifact upgraded to a unique LVS "
                    "match — do-not-match e2e covered by synthetic fixtures")
    out = tmp_path / "x.json"
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "lvs_report_check.py"),
         str(real), "--mode", "lvs", "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode != 0, r.stdout[-500:]
    assert json.loads(out.read_text())["passed"] is False


def test_wrapper_forwards_json_flag(tmp_path):
    # the wrapper must forward --json so the acceptance's /tmp/x.json is
    # written (it hard-coded argv pre-#507).
    proj = _write_lvs(tmp_path, "Final result: Circuits match uniquely.\n")
    out = tmp_path / "v.json"
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "lvs_report_check.py"),
         str(proj), "--mode", "lvs", "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-300:]
    assert json.loads(out.read_text())["passed"] is True
