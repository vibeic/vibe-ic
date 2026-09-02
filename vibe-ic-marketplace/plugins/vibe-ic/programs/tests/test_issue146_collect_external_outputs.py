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
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))
import collect_external_outputs as CE  # noqa: E402
import project_outputs_in_tree_check as gate  # noqa: E402


@pytest.fixture
def volatile_dir():
    """A scratch directory under one of the gate's OWN volatile prefixes.

    The artefact these tests stage has to be one the gate classifies as
    volatile, and that is decided by `_VOLATILE_PREFIXES` (`/tmp/`, `/var/tmp/`,
    `/dev/shm/`, `/run/`) — not by wherever pytest happens to put `tmp_path`.
    Under a relocated `TMPDIR` (the #2014 census lane, `run_suite_in_eda_image.sh
    --scratch`, any scratch under `$HOME`) `tmp_path` is NOT under a volatile
    prefix, the collector correctly copies nothing, and four of these six tests
    went red with the collector unchanged — MEASURED at 14de9b8a36 in the pinned
    image: `assert 0 == 1` on the collected count, the gate returning 0 where
    the test expected 1. The precondition is built here and ASSERTED, so a lane
    with no writable volatile root fails on the premise, not on the collector.
    """
    for prefix in gate._VOLATILE_PREFIXES:
        root = Path(prefix)
        if root.is_dir() and os.access(root, os.W_OK):
            made = Path(tempfile.mkdtemp(prefix="issue146-", dir=str(root)))
            break
    else:
        pytest.fail(f"no writable volatile root among {gate._VOLATILE_PREFIXES}; "
                    "the collector cannot be exercised here")
    assert any(str(made).startswith(pre) for pre in gate._VOLATILE_PREFIXES), made
    try:
        yield made
    finally:
        shutil.rmtree(made, ignore_errors=True)


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


def test_live_external_output_collected_and_gate_passes(tmp_path, volatile_dir):
    art = _live_artifact(volatile_dir)
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


def test_dangling_reference_not_masked(tmp_path, volatile_dir):
    art = _live_artifact(volatile_dir)
    p = tmp_path / "projB"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "out.json").write_text(json.dumps({
        "live": str(art), "gone": "/tmp/nonexistent_xyz/lost.gds"}))
    n, _ = CE.collect(p)
    assert n == 1                                # only the LIVE one collected
    txt = (p / "reports" / "out.json").read_text()
    assert "/tmp/nonexistent_xyz/lost.gds" in txt  # dangling left untouched
    assert _run_gate(p) == 1                      # still FAILs on the dangling ref


def test_idempotent(tmp_path, volatile_dir):
    art = _live_artifact(volatile_dir)
    p = tmp_path / "projC"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "r.json").write_text(json.dumps({"a": str(art)}))
    assert CE.collect(p)[0] == 1
    assert CE.collect(p)[0] == 0                  # re-run is a no-op


def test_provenance_recorded(tmp_path, volatile_dir):
    art = _live_artifact(volatile_dir)
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


def test_log_file_reference_not_collected(tmp_path, volatile_dir):
    # a /tmp reference inside a *.log is ephemeral tool scratch — not collected
    art = _live_artifact(volatile_dir)
    p = tmp_path / "projF"
    (p / "reports").mkdir(parents=True)
    (p / "reports" / "tool.log").write_text(f"scratch at {art}\n")
    assert CE.collect(p) == (0, [])
