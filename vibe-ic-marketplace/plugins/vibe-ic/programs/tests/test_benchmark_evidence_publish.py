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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pdk_revision_fixture as _pdk_fixture  # noqa: E402

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
    # `benchmark_evidence_publish` REFUSES a run that cannot name the PDK
    # revision it signed off against (W6). The record is produced by the
    # REAL resolver over a synthesized tree — never hand-written — so this
    # fixture cannot drift from the program that writes it in production.
    _pdk_fixture.write_run_pdk_revision(run)
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


def test_small_layout_artefacts_are_staged(tmp_path):
    """#419 — this asserted the OPPOSITE until v1.6.61, and that assertion is
    why a cell published by this program carried LESS evidence than the
    hand-staged cells it replaced. `.gitignore` accepts layout artefacts
    under `benchmark-data/ic/**`; dropping them by extension threw away the
    0.8 MB artefact a reviewer wants in order to avoid a 105 MB one."""
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    shipped = sorted(p.name for p in cell.rglob("*")
                     if p.suffix.lower() in (".gds", ".def", ".spef", ".oas"))
    assert "dump.def" in shipped and "parasitics.spef" in shipped, shipped


def test_an_oversized_layout_artefact_is_still_excluded(tmp_path):
    """The paired half — the reason the rule exists at all. Above the ceiling
    the file cannot be committed, so staging it would only produce a cell
    whose push is rejected."""
    run = _make_run(tmp_path)
    big = run / "reports" / "phase3" / "huge.def"
    big.parent.mkdir(parents=True, exist_ok=True)
    with big.open("wb") as fh:
        fh.truncate(51 * 1000 * 1000)        # sparse: st_size without the disk
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert not (cell / "reports" / "phase3" / "huge.def").exists()
    # and the small ones beside it are unaffected — the rule is about size
    assert (cell / "reports" / "phase3" / "dump.def").exists()


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
    # #419: nothing in this fixture is over the ceiling, so nothing is
    # excluded. The field must still be REPORTED — a publish that silently
    # dropped an artefact and said nothing is what made the shortfall in the
    # published cells invisible for four versions.
    assert data["excluded_raw_files"] == 0, data


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


# --------------------------------------------------------------------------
# #2006 — compiler build residue never lands in the cell
# --------------------------------------------------------------------------

_RESIDUE_EXTS = (".gch", ".pch", ".o", ".obj", ".a", ".so", ".d", ".mk", ".cpp")


def _plant_verilator_build(run: Path) -> tuple:
    """A Verilator model directory the way the coverage step leaves it — under
    the flow's OWN directory name (`cov_build`, not the tool's default
    `obj_dir`), beside the outputs a reader actually wants. Every residue
    file is SMALL, so the size rule cannot be what excludes it.

    Returns (residue relpaths, evidence relpaths), both relative to the run.
    """
    sim = run / "phase2" / "stage1" / "sim"
    cov = sim / "cov_build"
    cov.mkdir(parents=True)
    residue = [
        # the marker Verilator writes into every -Mdir it populates
        "cov_build/Vtb_widget__verFiles.dat",
        # the two precompiled headers the issue was filed about
        "cov_build/Vtb_widget__pch.h.fast.gch",
        "cov_build/Vtb_widget__pch.h.slow.gch",
        "cov_build/Vtb_widget__pch.h",
        # the generated model, its build files, and the compiled simulator
        "cov_build/Vtb_widget.cpp",
        "cov_build/Vtb_widget.h",
        "cov_build/Vtb_widget.mk",
        "cov_build/Vtb_widget_classes.mk",
        "cov_build/Vtb_widget___024root__0.cpp",
        "cov_build/Vtb_widget.o",
        "cov_build/Vtb_widget.d",
        "cov_build/Vtb_widget__ALL.a",
        "cov_build/Vtb_widget",
        # the runtime Verilator copies in beside them
        "cov_build/verilated.o",
        "cov_build/verilated.d",
        "cov_build/verilated_cov.o",
        # the tool's default directory name, anywhere
        "obj_dir/Vother.cpp",
        # a bare object file outside any build directory
        "stray.o",
    ]
    evidence = [
        "cov_build/coverage.dat",
        "results.xml",
        "pass.flag",
        "tb/case_1.v",
        "sim.log",
        # a header and a main in a directory Verilator never populated is
        # somebody's SOURCE — the rule keys on the tool's marker, not on a
        # `V*` name shape
        "src/Vtb_widget.h",
        "src/main.cpp",
    ]
    for rel in residue + evidence:
        p = sim / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fixture:" + rel.encode() + b"\n")
    return (["phase2/stage1/sim/" + r for r in residue],
            ["phase2/stage1/sim/" + e for e in evidence])


def test_build_residue_never_lands_in_the_cell(tmp_path):
    """#2006. A published cell carried a whole Verilator build directory —
    55 files, 174 MB, two precompiled headers of 84 MB each — beside the one
    71 KB `coverage.dat` that is the evidence. The size rule never saw them:
    it routes layout artefacts and nothing else. The residue here is tiny on
    purpose, so this test fails on the OLD code for the right reason."""
    run = _make_run(tmp_path)
    residue, evidence = _plant_verilator_build(run)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    r = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"

    # the evidence beside the residue is untouched
    for rel in evidence:
        assert (cell / rel).is_file(), f"evidence {rel} was dropped"

    # the pin: a run tree containing a .gch never lands it in the cell
    landed = sorted(p.relative_to(cell).as_posix()
                    for p in cell.rglob("*") if p.is_file())
    gch = [p for p in landed if p.endswith(".gch")]
    assert not gch, gch
    for rel in residue:
        assert not (cell / rel).exists(), f"build residue {rel} was staged"
    # and nothing of that shape anywhere in the cell, by any route
    shaped = [p for p in landed
              if "/obj_dir/" in p
              or Path(p).suffix in (".gch", ".pch", ".o", ".obj", ".a", ".so", ".d")
              or (p.startswith("phase2/stage1/sim/cov_build/")
                  and not p.endswith("coverage.dat"))]
    assert not shaped, shaped

    # the omission is legible: counted, sized and named in the summary and
    # on stdout — never silent
    data = json.loads(out.read_text())
    br = data["build_residue_skipped"]
    assert br["files"] == len(residue), br
    assert sorted(br["paths"]) == sorted(residue), br
    assert br["bytes"] == sum((run / rel).stat().st_size for rel in residue)
    assert "build residue:" in r.stdout, r.stdout
    assert any(s.startswith("phase2/") and "build-residue" in s
               for s in data["staged"]), data["staged"]


def test_build_residue_is_reported_even_when_there_is_none(tmp_path):
    """The field is part of the summary's shape, not a conditional extra —
    the same rule `excluded_raw_files` follows."""
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    assert _run(_base_args(run, dest_root) + ["--json", str(out)]).returncode == 0
    data = json.loads(out.read_text())
    assert data["build_residue_skipped"] == {"files": 0, "bytes": 0, "paths": []}


def test_build_residue_predicate_is_bound_to_the_tool_marker(tmp_path):
    """The decision itself, probed directly (the publish test above cannot
    tell WHICH half of the rule excluded a file). Verilator marks every
    directory it populates with `<prefix>__verFiles.dat`; that marker, not a
    directory name and not a `V*` name shape, is what turns the model files
    into residue."""
    sys.path.insert(0, str(PROG.parent))
    import benchmark_evidence_publish as bep

    src = tmp_path / "src"
    src.mkdir()
    for name in ("Vtop.h", "Vtop.cpp", "verilated.cpp", "main.cpp"):
        (src / name).write_text("// source\n")
    # no marker: nothing here is residue, whatever it is called
    for name in ("Vtop.h", "Vtop.cpp", "verilated.cpp", "main.cpp"):
        assert not bep.is_build_residue(src / name), name

    (src / "Vtop__verFiles.dat").write_text("")
    # marker present: the model prefix and the runtime are residue ...
    for name in ("Vtop.h", "Vtop.cpp", "Vtop", "Vtop_classes.mk",
                 "Vtop___024root__0.cpp", "verilated.cpp", "Vtop__verFiles.dat"):
        assert bep.is_build_residue(src / name), name
    # ... and the simulation's own outputs are not
    for name in ("main.cpp", "coverage.dat", "results.xml", "sim.log"):
        assert not bep.is_build_residue(src / name), name

    # extension and obj_dir rules need no marker at all
    for rel in ("x.gch", "x.pch", "x.o", "x.obj", "x.a", "x.so", "x.d",
                "deep/obj_dir/Vany.cpp", "obj_dir/x.txt"):
        assert bep.is_build_residue(tmp_path / rel), rel
    for rel in ("x.v", "x.sv", "x.json", "x.dat", "x.xml", "x.log", "x.gds",
                "objects_dir/x.cpp"):
        assert not bep.is_build_residue(tmp_path / rel), rel
