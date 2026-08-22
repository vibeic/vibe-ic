"""Step 11 — the stuck-at coverage measurement must reach the sign-off gate in
the CONTRACT-NAMED artefact, not only in `fault atpg`'s native coverage.yml.

MEASURED shape (opentitan_aes × sky130A, r5→r8): `fault atpg` completed and
left `phase2/stage2/dft/coverage.yml` carrying a real ratio (0.507), but the
machine-readable `reports/phase2/dft/coverage.json` and `atpg_coverage.rpt`
that `dft_signoff_check` actually reads were written only AFTER the second,
long-running transition (at-speed) fault pass — and coverage.json only in the
CLI wrapper `main()`. When that transition pass ran long and the run was
interrupted (or a library caller drove `run_fault()` directly), the completed
stuck-at measurement survived only in coverage.yml, which the gate does not
read, and the gate reported "no DFT/ATPG coverage evidence found" on a design
that HAD been measured — a measurement that exists reading identically to a
tool that never ran.

The producer's own module docstring DECLARES `reports/dft/coverage.json` as its
machine-readable output, so the consumer names a file the producer promised.
The fix is on the PRODUCER: emit that declared artefact at the moment the
stuck-at ratio first exists, before the transition pass and independent of the
CLI wrapper.

BIDIRECTIONAL NEGATIVE CONTROL (vibe-ic flow-change-acceptance): the durability
test below is RED against the pre-fix tree (neither contract-named artefact
exists after the transition pass raises) and GREEN after. It genuinely can
fail; run it against origin/main to confirm.

chip-AGNOSTIC / PDK-AGNOSTIC: the fixture uses a synthetic netlist, a synthetic
coverage.yml, and no design/PDK literal in the assertions.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import fault_atpg_run as far  # noqa: E402
import _path_layout as _pl    # noqa: E402


# A minimal `fault atpg` coverage.yml the producer's own parser reads as a real
# measurement (ratio + a faultPoints enumeration → faults_total > 0).
_COVERAGE_YML = "ratio: 5.0e-1\nfaultPoints:\n- _1_.A\n- _2_.B\n"


def _mk_project(tmp_path: Path) -> str:
    (tmp_path / "phase2" / "stage2" / "dft").mkdir(parents=True)
    (tmp_path / "reports" / "phase2" / "dft").mkdir(parents=True)
    netlist_rel = "phase2/stage2/dft/mapped.v"
    (tmp_path / netlist_rel).write_text(
        "module t(input clk); MYLIB_DFF u0(.CK(clk)); endmodule\n")
    return netlist_rel


def _fake_docker_measuring(project, cmd, timeout=600, pdk_dir=None):
    """Stand in for the container: `fault cut` succeeds and leaves its output;
    `fault atpg` succeeds and leaves a real coverage.yml (a measured ratio)."""
    joined = " ".join(cmd)
    if joined.startswith("fault cut"):
        (project / "phase2/stage2/dft/cut_netlist.v").write_text(
            "module cut; endmodule\n")
        return 0, "cut ok", ""
    if "fault atpg" in joined:
        (project / "phase2/stage2/dft/coverage.yml").write_text(_COVERAGE_YML)
        return 0, "atpg ok", ""
    return 1, "", "unexpected container command"


def test_stuckat_snapshot_survives_transition_interruption(tmp_path,
                                                           monkeypatch):
    """The load-bearing negative control.

    Stuck-at is measured (coverage.yml lands), then the transition pass is
    INTERRUPTED (its helper raises, standing in for a wall-budget kill / OOM
    during the long at-speed SAT run). The contract-named artefacts the gate
    reads must already be on disk with the real stuck-at number."""
    netlist_rel = _mk_project(tmp_path)
    monkeypatch.setattr(far, "_run_docker", _fake_docker_measuring)

    def _interrupted_transition(*a, **k):
        raise RuntimeError("simulated wall-budget kill during at-speed pass")
    monkeypatch.setattr(far, "run_transition_atpg", _interrupted_transition)

    with pytest.raises(RuntimeError):
        far.run_fault(
            tmp_path, netlist_rel, clock="clk", pdk="__none__",
            min_coverage=95.0, tv_count=8,
            cell_model_override="/work/cells.v", dff_cells_override="MYLIB_DFF",
            run_transition=True)

    cov_json = _pl.report_path(tmp_path, "dft/coverage.json")
    rpt = tmp_path / "phase2/stage2/dft/atpg_coverage.rpt"

    assert cov_json.is_file(), (
        "coverage.json is absent after the transition pass was interrupted — a "
        "completed stuck-at measurement is invisible to dft_signoff_check")
    assert rpt.is_file(), (
        "atpg_coverage.rpt is absent — the gate's fallback evidence is missing")

    doc = json.loads(cov_json.read_text())
    assert doc.get("coverage_measured") is True, doc
    assert 49.0 <= doc.get("coverage_pct", 0.0) <= 51.0, doc
    # The gate reads this as a real, below-floor FAIL — a number, not an absence.
    assert doc.get("stuck_at_ge_target") is False, doc


def test_run_fault_writes_coverage_json_in_process(tmp_path, monkeypatch):
    """The CLI-vs-library asymmetry: coverage.json used to be written only by
    the CLI main(). A library caller of run_fault() must get it too."""
    netlist_rel = _mk_project(tmp_path)
    monkeypatch.setattr(far, "_run_docker", _fake_docker_measuring)

    ec, report = far.run_fault(
        tmp_path, netlist_rel, clock="clk", pdk="__none__",
        min_coverage=95.0, tv_count=8,
        cell_model_override="/work/cells.v", dff_cells_override="MYLIB_DFF",
        run_transition=False)   # no transition; the snapshot IS the final write

    cov_json = _pl.report_path(tmp_path, "dft/coverage.json")
    assert cov_json.is_file(), (
        "run_fault() called in-process did not emit its declared coverage.json")
    doc = json.loads(cov_json.read_text())
    assert doc.get("coverage_measured") is True
    assert 49.0 <= doc.get("coverage_pct", 0.0) <= 51.0
    assert ec == 1   # 50% < 95% floor → honest FAIL


def test_json_out_honours_custom_destination(tmp_path, monkeypatch):
    """A caller passing json_out gets coverage.json at THAT path (mirrors the
    orchestrator, which points --json at reports/phase2/dft/coverage.json)."""
    netlist_rel = _mk_project(tmp_path)
    monkeypatch.setattr(far, "_run_docker", _fake_docker_measuring)
    custom = tmp_path / "reports" / "phase2" / "dft" / "coverage.json"

    far.run_fault(
        tmp_path, netlist_rel, clock="clk", pdk="__none__",
        min_coverage=95.0, tv_count=8,
        cell_model_override="/work/cells.v", dff_cells_override="MYLIB_DFF",
        run_transition=False, json_out=custom)

    assert custom.is_file(), "json_out custom destination not honoured"
    assert json.loads(custom.read_text()).get("coverage_measured") is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
