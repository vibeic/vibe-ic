#!/usr/bin/env python3
"""Tests for benchmark_evidence_publish.py.

Chip-AGNOSTIC synthetic run dirs under tmp_path (generic IC/PDK tokens). The
publish must: stage the canonical structure, exclude raw geometry, generate a
correct GDS_MANIFEST (size+sha256), REFUSE a non-converged / mis-specified run,
and never write on --dry-run.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "benchmark_evidence_publish.py"

_GDS_BYTES = b"GDSII-FAKE-STREAM-" * 64
_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"
_RESULT_FAIL = "# RESULT\n\n## VERDICT\n\n**FAIL.** did not converge.\n"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _make_run(base: Path, verdict: str = "PASS_WITH_WAIVERS",
              result: str = _RESULT_PASS, with_gds: bool = True,
              with_audit: bool = True, with_result: bool = True) -> Path:
    run = base / "run"
    # machine verdict
    if with_audit:
        (run / "reports" / "audit").mkdir(parents=True)
        (run / "reports" / "audit" / "phase23_completion_audit.json").write_text(
            json.dumps({"verdict": verdict}))
    # independent-audit RESULT.md
    if with_result:
        run.mkdir(parents=True, exist_ok=True)
        (run / "RESULT.md").write_text(result)
    # evidence subtrees
    (run / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (run / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (run / "phase2" / "stage2" / "synth").mkdir(parents=True, exist_ok=True)
    (run / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top; endmodule\n")
    (run / "phase3" / "reports").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "reports" / "drc.rpt").write_text("clean\n")
    (run / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "phase3" / "sta.json").write_text("{}")
    (run / "provenance.jsonl").write_text('{"tool":"yosys"}\n')
    # shared input source
    (run / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (run / "input" / "docs" / "L1.md").write_text("# spec\n")
    # raw geometry that MUST be excluded from copied subtrees
    (run / "reports" / "phase3" / "dump.def").write_text("DESIGN top ;\n")
    (run / "phase2" / "stage2" / "synth" / "parasitics.spef").write_text("*SPEF\n")
    # streamed GDS (for the manifest; NOT copied)
    if with_gds:
        (run / "phase3" / "stage4" / "gds").mkdir(parents=True, exist_ok=True)
        (run / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(_GDS_BYTES)
    return run


def _base_args(run: Path, dest_root: Path, version: str = "9.9.9"):
    return ["--run-dir", str(run), "--ic", "widgetmul", "--pdk", "openpdkx",
            "--plugin-version", version, "--dest-root", str(dest_root)]


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------

def test_help():
    assert _run(["--help"]).returncode == 0


def test_publish_stages_canonical_structure(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 0, r.stdout + r.stderr

    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert (cell / "RESULT.md").is_file()
    assert (cell / "phase1" / "generated_docs" / "L1.json").is_file()
    assert (cell / "phase2" / "stage2" / "synth" / "netlist.v").is_file()
    assert (cell / "reports" / "phase3" / "sta.json").is_file()
    assert (cell / "phase3" / "reports" / "drc.rpt").is_file()
    assert (cell / "provenance.jsonl").is_file()
    # shared input staged once
    assert (dest_root / "ic" / "widgetmul" / "input" / "docs" / "L1.md").is_file()
    # self-check reported PASS
    assert "self-check  : PASS" in r.stdout
    # never commits
    assert "NOT COMMITTED" in r.stdout


def test_manifest_has_correct_size_and_sha(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    manifest = (dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
                / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").read_text().strip()
    exp_sha = hashlib.sha256(_GDS_BYTES).hexdigest()
    assert manifest == f"top.gds {len(_GDS_BYTES)}B sha256:{exp_sha}"


def test_raw_geometry_excluded(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    raws = [p for p in cell.rglob("*")
            if p.suffix.lower() in (".gds", ".def", ".spef", ".oas")]
    assert raws == [], f"raw geometry leaked into publish: {raws}"


def test_dry_run_writes_nothing(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root) + ["--dry-run"])
    assert r.returncode == 0
    assert "WOULD STAGE" in r.stdout
    assert not (dest_root / "ic").exists()


def test_json_summary(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    assert _run(_base_args(run, dest_root) + ["--json", str(out)]).returncode == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "PASS_WITH_WAIVERS"
    assert data["excluded_raw_files"] >= 2


# --------------------------------------------------------------------------
# the convergence + input guards (REFUSE = rc 1, stages nothing)
# --------------------------------------------------------------------------

def test_refuse_non_converged_run(tmp_path):
    run = _make_run(tmp_path, verdict="FAIL", result=_RESULT_FAIL)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1
    assert "REFUSED" in r.stderr and "FAIL" in r.stderr
    assert not (dest_root / "ic").exists()


def test_refuse_missing_audit_verdict(tmp_path):
    run = _make_run(tmp_path, with_audit=False)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1
    assert "REFUSED" in r.stderr
    assert not (dest_root / "ic").exists()


def test_refuse_missing_result_md(tmp_path):
    run = _make_run(tmp_path, with_result=False)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1
    assert "RESULT.md" in r.stderr
    assert not (dest_root / "ic").exists()


def test_refuse_result_md_says_fail_while_audit_pass(tmp_path):
    # inconsistent: audit PASS but the human audit RESULT.md says FAIL
    run = _make_run(tmp_path, verdict="PASS_WITH_WAIVERS", result=_RESULT_FAIL)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1
    assert not (dest_root / "ic").exists()


def test_refuse_no_gds(tmp_path):
    run = _make_run(tmp_path, with_gds=False)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1
    assert "GDS" in r.stderr
    assert not (dest_root / "ic").exists()


def test_refuse_bad_version(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root, version="clean_run"))
    assert r.returncode == 1


def test_refuse_existing_dest_without_force(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    # second publish onto the same cell without --force
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1
    assert "already exists" in r.stderr
    # --force succeeds
    assert _run(_base_args(run, dest_root) + ["--force"]).returncode == 0


# --------------------------------------------------------------------------
# the publish output passes the companion structure checker
# --------------------------------------------------------------------------

def test_staged_folder_passes_structure_check(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    checker = PROG.parent / "benchmark_evidence_structure_check.py"
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    chk = subprocess.run([sys.executable, str(checker), str(cell)],
                         capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout + chk.stderr
