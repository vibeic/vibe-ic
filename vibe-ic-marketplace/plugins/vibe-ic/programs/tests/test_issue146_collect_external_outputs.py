"""#146 blocker-3 — collect volatile external-storage outputs into the project
tree before the audit (generic producer-side fix).

For every LIVE artifact a canonical report cites at a volatile /tmp path, the
collect pass copies it in-tree (top-level collected_external/) and rewrites the
reference to the project-relative path, so project_outputs_in_tree_check PASSes.
§4.05 no-leak: a DANGLING reference (file gone) is never copied/rewritten and the
gate still FAILs it; only files that EXIST are collected; the pass is idempotent.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
import collect_external_outputs as CE  # noqa: E402
import project_outputs_in_tree_check as gate  # noqa: E402


def _run_gate(project: Path) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        old = sys.argv
        sys.argv = ["x", str(project)]
        try:
            return gate.main()
        finally:
            sys.argv = old


def _live_artifact(tmp: Path) -> Path:
    art = tmp / "eda_scratch" / "design.gds"
    art.parent.mkdir(parents=True)
    art.write_text("GDS-DATA")
    return art


def test_live_external_output_collected_and_gate_passes(tmp_path):
    art = _live_artifact(tmp_path)
    p = tmp_path / "projA"
    (p / "reports" / "phase3").mkdir(parents=True)
    (p / "reports" / "phase3" / "gds.json").write_text(
        json.dumps({"gds_path": str(art), "status": "done"}))
    assert _run_gate(p) == 1                      # BEFORE: live external → FAIL
    n, collected = CE.collect(p)
    assert n == 1
    txt = (p / "reports" / "phase3" / "gds.json").read_text()
    assert "/tmp" not in txt and "collected_external/design.gds" in txt
    assert (p / "collected_external" / "design.gds").exists()
    assert _run_gate(p) == 0                      # AFTER: in-tree → PASS


def test_dangling_reference_not_masked(tmp_path):
    art = _live_artifact(tmp_path)
    p = tmp_path / "projB"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "out.json").write_text(json.dumps({
        "live": str(art), "gone": "/tmp/nonexistent_xyz/lost.gds"}))
    n, _ = CE.collect(p)
    assert n == 1                                # only the LIVE one collected
    txt = (p / "reports" / "out.json").read_text()
    assert "/tmp/nonexistent_xyz/lost.gds" in txt  # dangling left untouched
    assert _run_gate(p) == 1                      # still FAILs on the dangling ref


def test_idempotent(tmp_path):
    art = _live_artifact(tmp_path)
    p = tmp_path / "projC"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "r.json").write_text(json.dumps({"a": str(art)}))
    assert CE.collect(p)[0] == 1
    assert CE.collect(p)[0] == 0                  # re-run is a no-op


def test_provenance_recorded(tmp_path):
    art = _live_artifact(tmp_path)
    p = tmp_path / "projD"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "r.json").write_text(json.dumps({"a": str(art)}))
    CE.collect(p)
    prov = json.loads((p / "collected_external" / "_provenance.json").read_text())
    assert str(art) in prov["in_tree_to_original"].values()


def test_no_external_paths_is_noop(tmp_path):
    p = tmp_path / "projE"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "r.json").write_text(json.dumps({"a": "reports/x.gds"}))
    assert CE.collect(p) == (0, [])
    assert not (p / "collected_external").exists()


def test_log_file_reference_not_collected(tmp_path):
    # a /tmp reference inside a *.log is ephemeral tool scratch — not collected
    art = _live_artifact(tmp_path)
    p = tmp_path / "projF"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "tool.log").write_text(f"scratch at {art}\n")
    assert CE.collect(p) == (0, [])
