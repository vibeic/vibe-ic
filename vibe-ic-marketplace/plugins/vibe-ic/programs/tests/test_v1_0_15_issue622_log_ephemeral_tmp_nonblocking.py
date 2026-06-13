"""ORGANIC #622 [MEDIUM] — project_outputs_in_tree_check reported a 'dangling
external-path reference' whenever a referenced /tmp path no longer exists. A
LEC/yosys LOG (reports/lec_yosys.log) legitimately references a tool-internal
ephemeral path (e.g. /tmp/yosys-abc-XXXX/stdcells.genlib) the OS /tmp-sweep
removes after the run. Treating a LOG's reference to a transient tool path as a
blocking dangling PROJECT OUTPUT is wrong — logs reference ephemeral tool paths
by nature. Under final_audit --strict-structural the WARN escalated to a FAIL
that halted phase2 -> phase3 SKIPPED for an otherwise-clean run.

Fix: a /tmp reference found INSIDE A LOG FILE (*.log) is auto-classified
EPHEMERAL — disclosed ([INFO]) but NON-BLOCKING, no per-path waiver. Only
references in the canonical artefact files (RESULT.md / waivers.json /
reports/**/*.json|md / generated_docs/*.json), where a real deliverable's
location is declared, can FAIL the gate.

POSITIVE (#622): a yosys/LEC log citing a swept /tmp tool path → exit 0.

NEGATIVE no-leak:
  - a DANGLING /tmp path in RESULT.md (a non-log canonical artefact) → FAIL.
  - a LIVE /tmp artefact referenced in a report JSON → FAIL.
  - a clean project (no /tmp anywhere) → PASS.

chip-AGNOSTIC: keyed on the .log file-suffix + volatile-path grammar, no chip
literal.
"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROG = str(PLUGIN / "programs" / "project_outputs_in_tree_check.py")


def _run(tmp_path):
    r = subprocess.run([sys.executable, PROG, str(tmp_path)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def test_log_ephemeral_tmp_path_is_nonblocking(tmp_path):
    (tmp_path / "reports").mkdir()
    # the real #622 evidence shape, verbatim
    (tmp_path / "reports" / "lec_yosys.log").write_text(
        "Reading liberty /tmp/yosys-abc-1234/stdcells.genlib ...\n"
        "ABC: optimizing...\nLEC: equivalence PROVEN.\n")
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "[INFO]" in out and "ephemeral" in out  # disclosed, not silent
    assert "[PASS]" in out


def test_dangling_tmp_in_result_md_still_fails(tmp_path):
    # NO-LEAK: a non-log canonical artefact citing a /tmp project output FAILs.
    (tmp_path / "RESULT.md").write_text(
        "Final GDS written to /tmp/run-9/chip.gds (saved).\n")
    rc, _out = _run(tmp_path)
    assert rc == 1


def test_live_tmp_in_report_json_still_fails(tmp_path):
    # NO-LEAK: a LIVE /tmp artefact referenced in a report JSON FAILs.
    live = tmp_path / "scratch.def"  # any existing path under a /tmp-like ref
    # craft an absolute /tmp path that actually exists
    real = Path("/tmp") / f"zz_issue622_{tmp_path.name}.def"
    real.write_text("x")
    try:
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "sink.json").write_text(
            '{"gds": "%s"}' % str(real))
        rc, out = _run(tmp_path)
        assert rc == 1, out
        assert "live" in out.lower()
    finally:
        real.unlink(missing_ok=True)


def test_clean_project_passes(tmp_path):
    (tmp_path / "RESULT.md").write_text("All artefacts in the project tree.\n")
    rc, _out = _run(tmp_path)
    assert rc == 0


def test_log_and_canonical_mixed_fails_on_canonical_only(tmp_path):
    # A log ephemeral ref (non-blocking) PLUS a canonical-artefact dangling ref
    # (blocking) → FAIL, driven solely by the canonical one.
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec_yosys.log").write_text(
        "scratch at /tmp/yosys-zzz-9/abc.genlib\n")
    (tmp_path / "RESULT.md").write_text("GDS at /tmp/gone-7/chip.gds\n")
    rc, out = _run(tmp_path)
    assert rc == 1
    assert "[INFO]" in out  # the log ref is still disclosed as ephemeral
