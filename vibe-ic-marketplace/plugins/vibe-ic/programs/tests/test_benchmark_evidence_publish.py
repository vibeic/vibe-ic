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
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "benchmark_evidence_publish.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pdk_revision_fixture as _pdk_fixture  # noqa: E402
from _invocation_fixture import bind_invocation_top, preserve_invocation_runtime

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


# Public, self-authored transport bytes; these are not native design evidence.
_CANONICAL_PNR_INPUTS = {
    "phase3/stage3/pnr/constraint.sdc": (
        "# neutral publication transport fixture\n"
        "create_clock -name neutral_clk -period 10 [get_ports clk]\n"),
    "phase3/stage3/pnr/post_spare.def": (
        "VERSION 5.8 ;\nDESIGN neutral_publish ;\nEND DESIGN\n"),
}
_CANONICAL_PNR_STEPS = ("15", "18")


def _publish_canonical_pnr_fixture(tmp_path, entry, variant="present"):
    import step_output_collector as collector
    run = _make_run(tmp_path)
    bind_invocation_top(run, 'top')
    # Existing provenance pruning serializes JSON lines. Start this new
    # byte-preservation control in that existing canonical representation.
    (run / "provenance.jsonl").write_text(json.dumps({"tool": "yosys"}) + "\n")
    for rel, text in _CANONICAL_PNR_INPUTS.items():
        target = run / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    target = run / entry
    if variant == "missing":
        target.unlink()
    elif variant == "wrong-sibling":
        target.rename(target.with_name("wrong_" + target.name))
    elif variant == "zero-byte":
        target.write_bytes(b"")
    observation = collector.materialize(run, only_steps=list(_CANONICAL_PNR_STEPS))
    assert observation["bounded_to"] == list(_CANONICAL_PNR_STEPS)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    (tmp_path / "publish.stdout").write_text(r.stdout)
    (tmp_path / "publish.stderr").write_text(r.stderr)
    (tmp_path / "publish.invocation.json").write_text(json.dumps({
        "argv": r.args, "rc": r.returncode, "scope": "SOURCE_TRANSPORT_ONLY"}, indent=2))
    assert r.returncode == 0, r.stdout + r.stderr
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    # Commit only this neutral published cell. The unchanged resolver asks HEAD.
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=Neutral fixture", "-c",
                  "user.email=fixture@localhost", "commit", "-qm",
                  "Record self-authored source transport fixture"]):
        proc = subprocess.run(["git", *args], cwd=cell,
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
    records = [json.loads(p.read_text())
               for p in cell.glob("steps/**/STEP_RECORD.json")]
    assert {row["id"] for row in records} == set(_CANONICAL_PNR_STEPS)
    return run, cell, records


@pytest.mark.parametrize("entry", tuple(_CANONICAL_PNR_INPUTS))
def test_canonical_pnr_outputs_reach_the_record_and_resolver(tmp_path, entry):
    import test_matrix_d3_outputs_produced as d3
    run, cell, records = _publish_canonical_pnr_fixture(tmp_path, entry)
    row = next(o for rec in records for o in rec["declared_outputs"]
               if o["rel"] == entry)
    expected = _CANONICAL_PNR_INPUTS[entry].encode()
    assert row["bytes"] == len(expected)
    assert row["sha256"] == hashlib.sha256(expected).hexdigest()
    # This observed value is the RED -> GREEN -> RED production control.
    assert row["decision"] == "IN_CELL", row
    assert row["in_cell"] is True and row["symlink"] is False
    assert (cell / entry).read_bytes() == expected == (run / entry).read_bytes()
    assert (cell / "provenance.jsonl").read_bytes() == (run / "provenance.jsonl").read_bytes()
    hit, rejected = d3.resolve(cell, entry)
    assert hit and hit.path == entry and hit.size_bytes == len(expected), rejected
    # Public scope stays exact: a sibling scratch artefact was not admitted.
    assert not d3.publishable("phase3/stage3/pnr/floorplan.def")


@pytest.mark.parametrize("entry", tuple(_CANONICAL_PNR_INPUTS))
@pytest.mark.parametrize("variant", ("missing", "wrong-sibling", "zero-byte"))
def test_canonical_pnr_missing_wrong_and_empty_are_not_positive(tmp_path, entry, variant):
    import test_matrix_d3_outputs_produced as d3
    _run_dir, cell, records = _publish_canonical_pnr_fixture(tmp_path, entry, variant)
    rows = [o for rec in records for o in rec["declared_outputs"] if o["rel"] == entry]
    assert not any(o["decision"] == "IN_CELL" and o["bytes"] > 0 for o in rows), rows
    hit, rejected = d3.resolve(cell, entry)
    assert hit is None, (hit, rejected)
    if variant == "zero-byte" and (cell / entry).exists():
        assert rejected.empty == (entry,), rejected


@pytest.mark.parametrize("entry", tuple(_CANONICAL_PNR_INPUTS))
def test_canonical_pnr_record_discloses_postpublication_byte_drift(tmp_path, entry):
    import test_matrix_d3_outputs_produced as d3
    _run_dir, cell, records = _publish_canonical_pnr_fixture(tmp_path, entry)
    row = next(o for rec in records for o in rec["declared_outputs"] if o["rel"] == entry)
    target = cell / entry
    # A file added AFTER publication cannot supply the missing IN_CELL binding.
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_CANONICAL_PNR_INPUTS[entry])
    target.write_bytes(target.read_bytes() + b"# changed after publication\n")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    assert actual != row["sha256"] and target.stat().st_size != row["bytes"]
    # The normal resolver enforces tracked/nonempty identity, not content hashes.
    # Retain that limit: a hit alone must never be described as a bound record.
    hit, rejected = d3.resolve(cell, entry)
    (tmp_path / "drift-observation.json").write_text(json.dumps({
        "record": row, "actual_sha256": actual,
        "record_binding_matches": False,
        "resolver_hit": hit.path if hit else None,
        "scope": "SOURCE_TRANSPORT_ONLY; resolver is not a hash validator"}, indent=2))
    assert not (row["in_cell"] and row["sha256"] == actual)


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


# --------------------------------------------------------------------------
# #2007 — citation closure: a staged document's cited proof ships with it.
#
# MEASURED on the published spm x gf180mcuD v1.14.88 cell: RESULT.md said
# "retained in `full_acceptance.log`" and reports/phase3/antenna.json carried
# `"source": "phase3/stage3/pnr/openroad.log"` under `"verdict": "PASS"`.
# Neither path is in a copy subtree, both existed in the run tree under the
# ceiling, and the cell shipped both documents and neither proof — with its
# own CITATION_ROUTING.txt recording the two rows DANGLING. The fixtures below
# reproduce exactly that shape with generic content.
# --------------------------------------------------------------------------
_ACCEPT_LOG = "full_acceptance.log"                 # cell root; not a copy file
_OPENROAD_LOG = "phase3/stage3/pnr/openroad.log"    # phase3/stage3: no subtree
_ANTENNA = "reports/phase3/antenna.json"            # reports/: a copy subtree


def _plant_citations(run: Path, *, cited_log: str = _ACCEPT_LOG,
                     cited_source: str = _OPENROAD_LOG,
                     log_exists: bool = True,
                     source_exists: bool = True) -> None:
    (run / "RESULT.md").write_text(
        _RESULT_PASS + f"\nThe full phase summaries are retained in "
                       f"`{cited_log}`.\n")
    (run / _ANTENNA).parent.mkdir(parents=True, exist_ok=True)
    (run / _ANTENNA).write_text(json.dumps(
        {"tool": "openroad", "net_violations": 0, "clean": True,
         "source": cited_source, "verdict": "PASS"}, indent=2))
    if log_exists:
        (run / _ACCEPT_LOG).write_text("phase1 PASS\nphase2 PASS\nphase3 PASS\n")
    if source_exists:
        p = run / _OPENROAD_LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[INFO ANT-0002] Found 0 net violations.\n")


def _routing_rows(cell: Path) -> dict:
    rows = {}
    for line in (cell / "CITATION_ROUTING.txt").read_text().splitlines():
        if line.startswith("#") or " :: " not in line:
            continue
        left, decision = line.rsplit(" ", 1)
        doc, cited = left.split(" :: ", 1)
        rows[(doc, cited)] = decision
    return rows


def test_a_cited_proof_that_exists_in_the_run_is_staged_beside_its_document(tmp_path):
    """THE MEASURED CASE. A Markdown citation of a root-level log and a JSON
    gate report's `source` field pointing into a subtree the publisher does
    not copy: both artefacts exist in the run, so both must land in the cell
    at the path the document names, and the routing record must say
    RESOLVES for both rather than DANGLING."""
    run = _make_run(tmp_path)
    _plant_citations(run)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    cp = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert cp.returncode == 0, cp.stderr + cp.stdout
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    for rel in (_ACCEPT_LOG, _OPENROAD_LOG):
        assert (cell / rel).is_file(), f"{rel} was cited and not staged"
        assert (cell / rel).read_bytes() == (run / rel).read_bytes()
    rows = _routing_rows(cell)
    assert rows[("RESULT.md", _ACCEPT_LOG)] == "RESOLVES", rows
    assert rows[(_ANTENNA, _OPENROAD_LOG)] == "RESOLVES", rows
    cc = json.loads(out.read_text())["citation_closure"]
    assert sorted(r["path"] for r in cc["staged"]) == sorted(
        [_ACCEPT_LOG, _OPENROAD_LOG]), cc
    # The base fixture's pdk record cites a container image record it never
    # writes; that absence is the fixture's, not this test's subject.
    assert not {r["cited"] for r in cc["absent"]} & {_ACCEPT_LOG, _OPENROAD_LOG}
    assert cc["amended"] == [] and cc["unamended"] == [], cc
    # The deliverable's own listing names each closed artefact AND the
    # document that needed it — the stdout is not the record, but a reader
    # of the publish must be able to see why a stage3 file is in the cell.
    assert f"+ {_ACCEPT_LOG} (citation closure: cited by RESULT.md)" in cp.stdout
    assert (f"+ {_OPENROAD_LOG} (citation closure: cited by {_ANTENNA})"
            in cp.stdout)


def test_closure_is_listed_on_a_dry_run_and_stages_nothing(tmp_path):
    """A dry run must answer the same question the real publish does — what
    WOULD be pulled in — and write nothing. The population is decided by the
    same copy walk in both modes, so the two listings cannot drift."""
    run = _make_run(tmp_path)
    _plant_citations(run)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    cp = _run(_base_args(run, dest_root) + ["--dry-run", "--json", str(out)])
    assert cp.returncode == 0, cp.stderr + cp.stdout
    assert not (dest_root / "ic").exists()
    cc = json.loads(out.read_text())["citation_closure"]
    assert sorted(r["path"] for r in cc["staged"]) == sorted(
        [_ACCEPT_LOG, _OPENROAD_LOG]), cc
    assert f"+ {_ACCEPT_LOG} (citation closure: cited by RESULT.md)" in cp.stdout
    assert (f"+ {_OPENROAD_LOG} (citation closure: cited by {_ANTENNA})"
            in cp.stdout)


def test_an_absent_citation_is_never_invented_and_is_disclosed(tmp_path):
    """THE PAIRED HALF. A citation whose target exists nowhere in the run must
    not produce a file — and must not be passed over in silence either. The
    JSON gate report is amended IN THE CELL by the honest-absence mechanism
    the corpus gate honours (evidence_present: false, verdict UNSUBSTANTIATED,
    the run's own word retained); the run's copy is untouched; the Markdown
    citation, which this program will not edit, is reported UNAMENDED."""
    run = _make_run(tmp_path)
    _plant_citations(run, cited_log="missing_proof.log",
                     cited_source="phase3/stage3/pnr/nowhere.log",
                     log_exists=False, source_exists=False)
    run_antenna_before = (run / _ANTENNA).read_text()
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    cp = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert cp.returncode == 0, cp.stderr + cp.stdout
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert not (cell / "missing_proof.log").exists()
    assert not (cell / "phase3" / "stage3" / "pnr" / "nowhere.log").exists()
    assert not (cell / "phase3" / "stage3").exists(), (
        "nothing under phase3/stage3 was cited AND present; the closure "
        "must not create the directory either")
    rows = _routing_rows(cell)
    assert rows[("RESULT.md", "missing_proof.log")] == "DANGLING", rows
    # Outside a git checkout the routing's carried-directory test falls back
    # to the phase/stage prefix rule, which words a cell carrying nothing
    # under phase3/stage3 as OUT_OF_PUBLISHED_SCOPE; in a corpus clone it is
    # DANGLING. Either way the row must not claim the reader can follow it.
    assert rows[(_ANTENNA, "phase3/stage3/pnr/nowhere.log")] in (
        "DANGLING", "OUT_OF_PUBLISHED_SCOPE"), rows
    cc = json.loads(out.read_text())["citation_closure"]
    assert cc["staged"] == [], cc
    assert {r["cited"] for r in cc["absent"]} >= {
        "missing_proof.log", "phase3/stage3/pnr/nowhere.log"}, cc
    # the JSON report: amended in the cell, verbatim in the run
    staged = json.loads((cell / _ANTENNA).read_text())
    assert staged["evidence_present"] is False
    assert staged["verdict"] == "UNSUBSTANTIATED"
    assert staged["verdict_as_run"] == "PASS"
    assert staged["source"] is None
    assert staged["evidence_absent"] == {"source": "phase3/stage3/pnr/nowhere.log"}
    assert "nowhere.log" in staged["null_because"]
    assert staged["net_violations"] == 0, "the run's other fields are retained"
    assert (run / _ANTENNA).read_text() == run_antenna_before
    assert cc["amended"] == [{"doc": _ANTENNA,
                              "fields": {"source": "phase3/stage3/pnr/nowhere.log"},
                              "verdict_as_run": "PASS",
                              "verdict": "UNSUBSTANTIATED"}], cc
    # the gate itself must now read the amended report as a disclosure, not
    # a claim — the same predicate `evidence_citation_resolves_check` applies
    sys.path.insert(0, str(PROG.parent))
    import evidence_citation_resolves_check as gate  # noqa: E402
    assert gate._json_artifact_refs(cell / _ANTENNA) == []
    assert gate._json_artifact_refs(run / _ANTENNA) == [
        ("source", "phase3/stage3/pnr/nowhere.log")]
    # the Markdown citation: not edited, and said so
    assert (cell / "RESULT.md").read_text() == (run / "RESULT.md").read_text()
    assert cc["unamended"] == [{"doc": "RESULT.md",
                                "cited": ["missing_proof.log"]}], cc
    assert "WARNING RESULT.md cites missing_proof.log" in cp.stdout


def test_a_cited_layout_artefact_stays_under_the_layout_policy(tmp_path):
    """Closure defers to the two records that already exist. A cited `.def`
    under phase3/stage3 is a layout artefact: it is NOT pulled in by the
    citation, and LAYOUT_ROUTING.txt keeps its NOT_PUBLISHED line."""
    run = _make_run(tmp_path)
    _plant_citations(run, cited_log="phase3/stage3/pnr/placed.def")
    p = run / "phase3" / "stage3" / "pnr" / "placed.def"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("DESIGN top ;\nEND DESIGN\n")
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    cp = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert cp.returncode == 0, cp.stderr + cp.stdout
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert not (cell / "phase3" / "stage3" / "pnr" / "placed.def").exists()
    cc = json.loads(out.read_text())["citation_closure"]
    assert [r["path"] for r in cc["layout_policy"]] == [
        "phase3/stage3/pnr/placed.def"], cc
    assert any(
        "phase3/stage3/pnr/placed.def" in line and "NOT_PUBLISHED" in line
        for line in (cell / "LAYOUT_ROUTING.txt").read_text().splitlines()), (
        (cell / "LAYOUT_ROUTING.txt").read_text())


def test_a_cited_proof_over_the_ceiling_is_recorded_not_staged(tmp_path, monkeypatch):
    """The ONE reason a cited, existing artefact is not staged: the commit
    ceiling. It is then listed OVER_CEILING with its size, and the other
    citation still closes — one refusal must not silence the rest."""
    sys.path.insert(0, str(PROG.parent))
    import benchmark_evidence_publish as B  # noqa: E402
    run = _make_run(tmp_path)
    _plant_citations(run)
    monkeypatch.setattr(B, "over_ceiling",
                        lambda p, ceiling=None: p.name == "openroad.log")
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    assert B.main(_base_args(run, dest_root) + ["--json", str(out)]) == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert (cell / _ACCEPT_LOG).is_file()
    assert not (cell / _OPENROAD_LOG).exists()
    cc = json.loads(out.read_text())["citation_closure"]
    assert [r["path"] for r in cc["staged"]] == [_ACCEPT_LOG], cc
    assert [(r["path"], r["bytes"]) for r in cc["over_ceiling"]] == [
        (_OPENROAD_LOG, (run / _OPENROAD_LOG).stat().st_size)], cc
    rows = _routing_rows(cell)
    assert rows[(_ANTENNA, _OPENROAD_LOG)] != "RESOLVES", rows


def test_a_closure_staged_document_is_itself_closed_and_recorded_on_a_restage(tmp_path):
    """Two defects the first spm re-stage exposed together. (a) A document
    the closure stages is a staged document: what IT cites must be closed
    too (the write ledger cited a summary JSON that cited an STA report).
    (b) Re-staging into a corpus CLONE, the routing record's published-tree
    filter kept only paths git already published at HEAD, so the document
    the closure had just added was left out of the record — and the
    structure gate, counting the cell's citations from the index after
    `git add`, found the routing answering for 23 of 24."""
    import subprocess as sp
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    dest_root.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(dest_root)]
    sp.run(git + ["init", "-q"], check=True)
    # first publish, committed: the cell now HAS a published tree at HEAD
    assert _run(_base_args(run, dest_root)).returncode == 0
    sp.run(git + ["add", "-A"], check=True)
    sp.run(git + ["commit", "-q", "-m", "first"], check=True)
    # the run grows a two-link chain, neither link in a copy subtree
    summary = "phase3/stage3/repair/no_repair_summary.json"
    report = "phase3/stage3/sta/sta_spef_based.rpt"
    (run / "RESULT.md").write_text(
        _RESULT_PASS + f"\nNo repair was needed; see `{summary}`.\n")
    for rel, body in ((summary, json.dumps({"verdict": "PASS", "report": report})),
                      (report, "slack 0.12 ns MET\n")):
        (run / rel).parent.mkdir(parents=True, exist_ok=True)
        (run / rel).write_text(body)
    out = tmp_path / "s.json"
    cp = _run(_base_args(run, dest_root) + ["--force", "--json", str(out)])
    assert cp.returncode == 0, cp.stderr + cp.stdout
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert (cell / summary).is_file() and (cell / report).is_file()
    cc = json.loads(out.read_text())["citation_closure"]
    assert {r["path"] for r in cc["staged"]} >= {summary, report}, cc
    assert (summary, report) in {(r["doc"], r["cited"]) for r in cc["staged"]}
    rows = _routing_rows(cell)
    assert rows[("RESULT.md", summary)] == "RESOLVES", rows
    assert rows[(summary, report)] == "RESOLVES", rows
    # the gate's own census, from the index, must be fully answered
    sp.run(git + ["add", "-A"], check=True)
    checker = PROG.parent / "benchmark_evidence_structure_check.py"
    chk = sp.run([sys.executable, str(checker), str(cell)],
                 capture_output=True, text=True)
    assert "answers for" not in chk.stdout + chk.stderr, chk.stdout + chk.stderr
    assert chk.returncode == 0, chk.stdout + chk.stderr


# #3315: public transport fixtures, never a claim that these logs prove an IC.
def _cited_text_cell(tmp_path, payloads, reports, *, dry=False):
    import benchmark_evidence_publish as publisher
    run = _make_run(tmp_path)
    for rel, body in {**payloads, **reports}.items():
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body if isinstance(body, bytes) else body.encode())
    dest = tmp_path / "published"
    dest.mkdir()
    # Start at the owner's citation boundary, with exactly the documents the
    # subtree copier handed it. The end-to-end test below covers publish().
    docs = []
    rels = set()
    for rel in reports:
        target = dest / rel
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((run / rel).read_bytes())
        docs.append((run / rel, rel))
        rels.add(rel)
    summary = publisher.close_citations(run, dest, docs, rels, dry)
    return run, dest, summary


@pytest.mark.parametrize('section', ['libs.ref', 'libs.tech'])
@pytest.mark.parametrize('prefix', ['/retired-store/kit/procx/', ''])
@pytest.mark.parametrize('dry', [False, True])
def test_external_kit_citations_keep_revision_and_location_without_copying(tmp_path, section, prefix, dry):
    import benchmark_evidence_publish as publisher
    cite = f'{prefix}{section}/cellsZ/model.lef:40'
    report = 'reports/transport.json'
    body = json.dumps({'verdict': 'PASS', 'source': cite})
    run, cell, result = _cited_text_cell(tmp_path, {}, {report: body}, dry=dry)
    record = result['records'][0]
    assert record['decision'] == 'EXTERNAL_PDK'
    assert record['kit_relative_path'] == f'{section}/cellsZ/model.lef'
    assert record['pdk_revision'] == publisher._pdk_revision(run)['revision']
    assert record['destination'] == 'external-kit'
    assert result['amended'] == [] and result['text_bytes'] == 0
    assert not (cell / section).exists()
    if not dry:
        assert (cell / report).read_text() == body
        publisher.write_citation_routing(cell, [], closure=result)
        text = (cell / 'CITATION_ROUTING.txt').read_text()
        assert record['kit_relative_path'] in text and record['pdk_revision'] in text


def test_citation_matching_does_not_invent_suffix_paths(tmp_path):
    import benchmark_evidence_publish as publisher
    full = 'input/current/retained-reports/ambiguous.json'
    run, cell, result = _cited_text_cell(tmp_path, {full: '{"data": 1}\n'}, {
        'reports/child.json': json.dumps({'verdict': 'PASS', 'source': full}),
        'reports/parent.json': json.dumps({'verdict': 'PASS', 'source': 'reports/child.json'})})
    assert 'reports/ambiguous.json' not in {r['cited'] for r in result['records']}
    assert (cell / full).read_bytes() == (run / full).read_bytes()
    assert json.loads((cell / 'reports/parent.json').read_text())['verdict'] == 'PASS'
    assert publisher._CITED_RE.findall('see reports/real.json, retained-reports/ghost.json') == [
        'reports/real.json']


def test_scan_census_is_not_a_citation_or_a_pass_claim(tmp_path):
    import benchmark_evidence_publish as publisher
    data = {'verdict': 'PASS', 'documents_scanned': [
        {'verdict': 'PASS', 'evidence': 'reports/census.json', 'source': '/old/census.json'}],
        'derived_answers': {'signal': {'evidence': 'reports/needed.rpt'}}}
    doc = tmp_path / 'report.json'
    doc.write_text(json.dumps(data))
    assert publisher._document_citations(doc) == {'reports/needed.rpt'}
    assert publisher._absolute_citation_values(doc.read_text()) == set()
    assert publisher._citations_under_a_pass(doc.read_text()) == {'reports/needed.rpt'}


@pytest.mark.parametrize('state', ['missing', 'unresolved'])
def test_external_kit_citation_stays_unavailable_without_resolved_revision(tmp_path, state):
    import benchmark_evidence_publish as publisher
    run = _make_run(tmp_path)
    revision = run / 'reports/pdk_revision.json'
    if state == 'missing':
        revision.unlink()
    else:
        record = json.loads(revision.read_text())
        record['resolved'] = False
        revision.write_text(json.dumps(record))
    report = run / 'reports/transport.json'
    report.write_text(json.dumps({'verdict': 'PASS',
        'source': '/retired-store/kit/procx/libs.ref/cellsZ/model.lef'}))
    cell = tmp_path / 'cell'
    (cell / 'reports').mkdir(parents=True)
    (cell / 'reports/transport.json').write_bytes(report.read_bytes())
    result = publisher.close_citations(run, cell, [(report, 'reports/transport.json')],
                                      {'reports/transport.json'}, False)
    assert result['records'][0]['decision'] == 'UNALLOWED_TEXT'
    assert result['external_pdk'] == []
    assert json.loads((cell / 'reports/transport.json').read_text())['verdict'] == 'UNSUBSTANTIATED'


@pytest.mark.parametrize("case", ["binary", "large", "unallowed", "private", "missing"])
def test_cited_text_refusal_preserves_honest_verdict(tmp_path, case):
    rel = {"binary": "raw/tool.rpt", "large": "raw/tool.log",
           "unallowed": "raw/model.bin", "private": "private/answers.txt",
           "missing": "raw/missing.log"}[case]
    body = {"binary": b"tool\x00binary\n", "large": b"x" * 1_000_001,
            "unallowed": b"not an allowed evidence type\n",
            "private": b"synthetic private answer fixture\n"}.get(case)
    report = "reports/phase3/transport.json"
    original = json.dumps({"verdict": "PASS", "evidence": rel, "value": 17})
    run, cell, summary = _cited_text_cell(
        tmp_path, {} if body is None else {rel: body}, {report: original})
    data = json.loads((cell / report).read_text())
    assert data["verdict"] == "UNSUBSTANTIATED", (case, data, summary)
    assert data["evidence"] is None and data["verdict_as_run"] == "PASS"
    assert data["value"] == 17
    assert (cell / rel).is_file() is False
    assert (run / report).read_text() == original
    refusals = [r for r in summary["records"] if r["doc"] == report]
    assert len(refusals) == 1
    assert refusals[0]["decision"] == {
        "binary": "NOT_TEXT", "large": "TEXT_FILE_LIMIT",
        "unallowed": "UNALLOWED_TEXT", "private": "UNALLOWED_TEXT",
        "missing": "ABSENT_IN_RUN"}[case]


def test_cited_text_cell_budget_is_shared_and_deduplicated(tmp_path, monkeypatch):
    import benchmark_evidence_publish as publisher
    monkeypatch.setattr(publisher, "_CITED_TEXT_CELL_BUDGET", 12, raising=False)
    reports = {f"reports/{key}.json": json.dumps({"verdict": "PASS", "source": rel})
               for key, rel in (("a", "raw/one.log"), ("b", "raw/one.log"),
                                ("c", "raw/two.log"))}
    _, cell, summary = _cited_text_cell(
        tmp_path, {"raw/one.log": "12345678", "raw/two.log": "abcdefgh"}, reports)
    verdicts = {key: json.loads((cell / f"reports/{key}.json").read_text())["verdict"]
                for key in "abc"}
    assert verdicts == {"a": "PASS", "b": "PASS", "c": "UNSUBSTANTIATED"}, summary
    assert summary["text_bytes"] == 8
    assert [r["decision"] for r in summary["records"]] == [
        "STAGED", "ALREADY_IN_CELL", "TEXT_CELL_BUDGET"]


@pytest.mark.parametrize("prior", [None, "PASS"])
def test_cited_text_missing_proof_does_not_replace_fail(tmp_path, prior):
    rel = "reports/phase3/transport.json"
    data = {"verdict": "FAIL", "evidence": "raw/missing.log"}
    if prior is not None:
        data["verdict_as_run"] = prior
    _, cell, summary = _cited_text_cell(tmp_path, {}, {
        rel: json.dumps(data)})
    data = json.loads((cell / rel).read_text())
    assert data["verdict"] == "FAIL", (data, summary)
    assert data["evidence_present"] is False


def test_cited_text_public_sby_inputs_reach_native_consumer(tmp_path):
    import formal_proof_evidence_check as consumer
    from _hostpaths import require_repo
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs")
    sby = (root / "calibration/sby_prove_arms.sby").read_bytes()
    fixture = root / "tests/fixtures/sby_prove_arms/pass"
    report = "reports/phase2/transport.json"
    run, cell, summary = _cited_text_cell(tmp_path, {
        "proofs/check.sby": sby,
        "proofs/ctr.v": (fixture / "ctr.v").read_bytes(),
        "proofs/formal_ctr.sv": (fixture / "formal_ctr.sv").read_bytes(),
    }, {report: json.dumps({"verdict": "PASS", "evidence": "proofs/check.sby"})})
    published_sby = cell / "proofs/check.sby"
    refs = consumer._sby_file_refs(published_sby.read_text())
    resolved = [consumer._resolve(published_sby.parent, published_sby.parent, cell, ref)
                for ref in refs]
    # Exercise the real consumer's path resolution, not publisher fields.
    assert sum(path is not None for path in resolved) == len(refs) == 2, summary
    for path in [published_sby, *resolved]:
        rel = path.relative_to(cell).as_posix()
        assert path.read_bytes() == (run / rel).read_bytes()
        entry = next(r for r in summary["records"] if r["path"] == rel)
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("source_present", [True, False],
                         ids=["source-present", "real-source-missing"])
def test_cited_text_sby_copy_rename_preserves_declared_source(tmp_path, source_present):
    from _hostpaths import require_repo
    fixture = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                           "tests", "fixtures", "sby_prove_arms", "pass")
    # The retained root-review counterexample: SBY creates formal_ctr.sv in
    # its task directory from the actual project input renamed_formal.sv.
    sby = ("[options]\nmode prove\ndepth 20\n\n[engines]\nabc pdr\n\n"
           "[script]\nread_verilog -formal -sv formal_ctr.sv ctr.v\nprep -top formal_ctr\n\n"
           "[files]\nctr.v\nformal_ctr.sv renamed_formal.sv\n")
    payloads = {"proofs/check.sby": sby,
                "proofs/ctr.v": (fixture / "ctr.v").read_bytes()}
    if source_present:
        payloads["proofs/renamed_formal.sv"] = (fixture / "formal_ctr.sv").read_bytes()
    report = "reports/transport.json"
    run, cell, summary = _cited_text_cell(tmp_path, payloads, {
        report: json.dumps({"verdict": "PASS", "evidence": "proofs/check.sby"})})
    data = json.loads((cell / report).read_text())
    assert data["verdict"] == ("PASS" if source_present else "UNSUBSTANTIATED"), (data, summary)
    assert not (run / "proofs/formal_ctr.sv").exists()
    assert not (cell / "proofs/formal_ctr.sv").exists(), "task-local copy must not be fabricated"
    if source_present:
        assert (cell / "proofs/check.sby").read_bytes() == sby.encode()
        staged = cell / "proofs/renamed_formal.sv"
        assert staged.read_bytes() == (fixture / "formal_ctr.sv").read_bytes()
        row = next(r for r in summary["records"] if r["path"] == "proofs/renamed_formal.sv")
        assert row["sha256"] == hashlib.sha256(staged.read_bytes()).hexdigest()
        assert not summary["absent"]
    else:
        assert data["evidence"] is None
        assert any(r["cited"] == "renamed_formal.sv" and r["decision"] == "ABSENT_IN_RUN"
                   for r in summary["records"])


def test_cited_text_missing_sby_input_is_not_a_substantiated_pass(tmp_path):
    report = "reports/phase2/transport.json"
    _, cell, summary = _cited_text_cell(tmp_path, {
        "proofs/check.sby": "[files]\nmissing.sv\n",
    }, {report: json.dumps({"verdict": "PASS", "evidence": "proofs/check.sby"})})
    data = json.loads((cell / report).read_text())
    assert data["verdict"] == "UNSUBSTANTIATED", (data, summary)
    assert data["evidence"] is None
    assert any(r["doc"] == "proofs/check.sby" and
               r["decision"] == "ABSENT_IN_RUN" for r in summary["records"])


def test_cited_text_publish_binds_bytes_and_relative_consumer_paths(tmp_path):
    import evidence_citation_resolves_check as consumer
    import citation_routing_is_true_check as routing_consumer
    run = _make_run(tmp_path)
    # A real record may cite a document-relative filename or a state path
    # absolute on the producing host. The staged pointers must be portable.
    report = "reports/phase3/transport.json"
    log = "reports/phase3/transport.log"
    state = "phase3/backend/irdrop/state_out.json"
    (run / log).write_text("PUBLIC TRANSPORT FIXTURE ONLY\n")
    (run / state).parent.mkdir(parents=True)
    (run / state).write_text('{"metrics": {}}\n')
    (run / report).write_text(json.dumps({
        "verdict": "PASS", "evidence": "transport.log", "tool_state": str(run / state)}))
    dest_root = tmp_path / "benchmark-data"
    cp = _run(_base_args(run, dest_root))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    cell = dest_root / "ic/widgetmul/v9.9.9_openpdkx"
    data = json.loads((cell / report).read_text())
    assert data["tool_state"] == state, data
    for cite in (data["evidence"], data["tool_state"]):
        resolved = consumer.resolve_citation(cell / report, cite, cell)
        assert resolved is not None
        assert resolved.read_bytes() == (run / resolved.relative_to(cell)).read_bytes()
    rows = _routing_rows(cell)
    assert rows[(report, "transport.log")] == "RESOLVES", rows
    assert rows[(report, state)] == "RESOLVES", rows
    assert routing_consumer.audit_cell(cell)["false_claims"] == []
    text = (cell / "CITATION_ROUTING.txt").read_text()
    for rel in (log, state):
        assert hashlib.sha256((run / rel).read_bytes()).hexdigest() in text
    # A fresh clone, with tracked-file resolution, is the reader's deliverable.
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=Transport fixture", "-c", "user.email=fixture@localhost",
                  "commit", "-qm", "Public transport fixture"]):
        subprocess.run(["git", "-C", str(dest_root), *args], check=True, capture_output=True)
    cloned = tmp_path / "reader"
    subprocess.run(["git", "clone", "-q", str(dest_root), str(cloned)], check=True)
    reader_cell = cloned / cell.relative_to(dest_root)
    tracked = consumer.tracked_files(reader_cell)
    assert tracked is not None
    for cite in (data["evidence"], data["tool_state"]):
        assert consumer.resolve_citation(reader_cell / report, cite, reader_cell, tracked) is not None
    assert routing_consumer.audit_cell(reader_cell)["false_claims"] == []


def test_cited_text_dry_run_uses_same_bytes_and_budget(tmp_path, monkeypatch):
    import benchmark_evidence_publish as publisher
    monkeypatch.setattr(publisher, "_CITED_TEXT_CELL_BUDGET", 7, raising=False)
    payloads = {"raw/one.log": "12345678"}
    reports = {"reports/transport.json": json.dumps({
        "verdict": "PASS", "evidence": "raw/one.log"})}
    _, cell, dry = _cited_text_cell(tmp_path / "dry", payloads, reports, dry=True)
    _, _, real = _cited_text_cell(tmp_path / "real", payloads, reports)
    assert dry["staged"] == real["staged"] == [], (dry, real)
    assert dry["records"] == real["records"]
    assert list(cell.rglob("*")) == []


def test_cited_text_hash_binds_the_published_document_after_path_rewrite(tmp_path):
    # A cited JSON can itself cite a host-absolute project log. Bind the
    # portable published bytes, while retaining the source digest separately.
    root = tmp_path / "run"
    summary_path = "raw/summary.json"
    source = json.dumps({"verdict": "PASS", "source": str(root / "raw/tool.log")})
    _, cell, summary = _cited_text_cell(tmp_path, {
        summary_path: source, "raw/tool.log": "PUBLIC TRANSPORT ONLY\n",
    }, {"reports/transport.json": json.dumps({
        "verdict": "PASS", "source": summary_path})})
    row = next(r for r in summary["records"] if r["path"] == summary_path)
    assert row["sha256"] == hashlib.sha256((cell / summary_path).read_bytes()).hexdigest()
    assert row["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.parametrize("case", ["copied-binary", "outside-project", "absolute-sby"])
def test_cited_text_respects_planned_files_and_restricts_extra_paths(tmp_path, case):
    import benchmark_evidence_publish as publisher
    run = _make_run(tmp_path)
    cell = tmp_path / "published"
    cell.mkdir()
    report = "reports/transport.json"
    rel = "raw/proof.log"
    payload = run / rel
    payload.parent.mkdir()
    payload.write_text("PUBLIC TRANSPORT ONLY\n")
    rels = {report}
    if case == "outside-project":
        outside = tmp_path / "outside.log"
        outside.write_text("PUBLIC SYNTHETIC OUTSIDE PROJECT\n")
        payload.unlink()
        payload.symlink_to(outside)
    elif case == "copied-binary":
        payload.write_bytes(b"binary\x00payload")
        (cell / rel).parent.mkdir()
        (cell / rel).write_bytes(payload.read_bytes())
        rels.add(rel)
    else:
        sby = run / "raw/check.sby"
        sby.write_text(f"[files]\n{payload}\n")
        rel = "raw/check.sby"
    doc = run / report
    doc.write_text(json.dumps({"verdict": "PASS", "evidence": rel}))
    (cell / report).parent.mkdir()
    (cell / report).write_bytes(doc.read_bytes())
    summary = publisher.close_citations(run, cell, [(doc, report)], rels, False)
    data = json.loads((cell / report).read_text())
    if case == 'copied-binary':
        # Citation closure cannot revoke a file selected by the copy plan.
        assert data['verdict'] == 'PASS'
        assert (cell / rel).read_bytes() == payload.read_bytes()
        assert summary['records'][0]['decision'] == 'ALREADY_IN_CELL'
        return
    assert data["verdict"] == "UNSUBSTANTIATED", (case, data, summary)
    if case != "absolute-sby":
        assert not (cell / rel).exists()


@pytest.mark.parametrize('dry', [False, True])
def test_planned_release_documents_survive_citations_without_spending_extra_budget(
        tmp_path, monkeypatch, dry):
    import benchmark_evidence_publish as publisher
    monkeypatch.setattr(publisher, '_CITED_TEXT_FILE_LIMIT', 7)
    monkeypatch.setattr(publisher, '_CITED_TEXT_CELL_BUDGET', 7)
    paths = ['reports/docs/RELEASE.html', 'phase3/documentation/manifest.yaml',
             'phase3/documentation/RELEASE_NOTES.md']
    planned = {rel: 'Required release document with signal EM NOT_MEASURED.\n'
               for rel in paths}
    planned['reports/release.json'] = json.dumps({
        'verdict': 'PASS', 'html_path': paths[0], 'yaml_path': paths[1],
        'document_path': paths[2], 'extra_log': 'raw/tool.log'})
    run, cell, summary = _cited_text_cell(
        tmp_path, {'raw/tool.log': '12345678'}, planned, dry=dry)
    decisions = {(r['doc'], r['cited']): r['decision'] for r in summary['records']}
    for rel in paths:
        assert decisions[('reports/release.json', rel)] == 'ALREADY_IN_CELL'
        if not dry:
            assert (cell / rel).read_bytes() == (run / rel).read_bytes()
    assert publisher._close_one(run, cell, dry, 'reports/absolute.md',
        str(run / paths[0]), set(planned), [], {'bytes': 0, 'files': {}}) == (
            'ALREADY_IN_CELL', paths[0])
    assert decisions[('reports/release.json', 'raw/tool.log')] == 'TEXT_FILE_LIMIT'
    assert summary['text_bytes'] == 0
    assert not (cell / 'raw/tool.log').exists()
    if dry:
        assert list(cell.iterdir()) == []


@pytest.mark.parametrize('dry', [False, True])
def test_captured_row_documents_keep_their_step_view_policy(tmp_path, dry):
    import benchmark_evidence_publish as publisher
    run = _make_run(tmp_path)
    captured = 'steps/001_transport/20260101/result.json'
    source = run / captured
    source.parent.mkdir(parents=True)
    original = '{"verdict":"FAIL","evidence":"missing-original.log"}\n'
    source.write_text(original)
    report = run / 'reports/transport.json'
    report.write_text(json.dumps({'captured_path': captured}))
    cell = tmp_path / 'cell'
    if not dry:
        (cell / captured).parent.mkdir(parents=True)
        (cell / captured).write_text(original)
    result = publisher.close_citations(run, cell, [(report, 'reports/transport.json')],
        {captured, 'reports/transport.json'}, dry)
    assert [r['decision'] for r in result['records']] == ['STEP_VIEW']
    assert result['n_documents'] == 1
    assert result['amended'] == []
    if not dry:
        assert (cell / captured).read_text() == original


@pytest.mark.parametrize("state_present", [True, False])
def test_cited_text_composite_description_uses_packaged_report_and_state(tmp_path, state_present):
    # Public IR report shape: the evidence string is a description, while
    # source/tool_state name the actual files. Never invent the missing state.
    import evidence_citation_resolves_check as consumer
    report = "reports/phase3/transport.json"
    state = "phase3/backend/state_out.json"
    raw = "reports/phase3/power.rpt"
    description = "native state metrics + power.rpt"
    payloads = {raw: "PUBLIC TRANSPORT REPORT ONLY\n"}
    if state_present:
        payloads[state] = '{"metrics": {}}\n'
    _, cell, summary = _cited_text_cell(tmp_path, payloads, {report: json.dumps({
        "verdict": "PASS", "source": raw, "tool_state": state,
        "evidence": description})})
    data = json.loads((cell / report).read_text())
    assert data["verdict"] == ("PASS" if state_present else "UNSUBSTANTIATED"), (data, summary)
    if state_present:
        assert data["evidence"] == [raw, state]
        assert data["evidence_as_run"] == {"description": description}
        assert consumer._json_artifact_refs(cell / report) == [("source", raw)]
        for cite in data["evidence"]:
            assert consumer.resolve_citation(cell / report, cite, cell) is not None
    else:
        assert data["evidence"] is None and data["tool_state"] is None


# --------------------------------------------------------------------------
# #2017 — the release documentation is REQUIRED, per DESIGN KIND
#
# The defect: the spm x gf180mcuD run produced the full 37.5ip document set
# and the published cell carried NONE of it, every file recorded
# OUT_OF_PUBLISHED_SCOPE. The owner's ruling makes the set an INVARIANT keyed
# on the design KIND read from the delivery route — an IC owes 37.5ic's nine
# declared outputs; an IP owes the 37.5ip document set. Neither needs the
# other route's documents (owner ruling, 2026-10-19).
# --------------------------------------------------------------------------

sys.path.insert(0, str(PROG.parent))
import _release_docs_contract as _RDC  # noqa: E402
import _tapeout_declaration as _TD  # noqa: E402
import _owner_declared as _OD                              # noqa: E402

#: The set the spm run measured, and the shape any IP release takes: the five
#: contract-required documents, the manifest that binds them to the artefacts,
#: and the optional Application Note a run that WROTE it must not lose.
_IP_DOC_SET = ("IP_DATASHEET.md", "IP_INTEGRATION_GUIDE.md", "RELEASE_NOTES.md",
               "ERRATA.md", "DELIVERABLES_MANIFEST.md",
               "documentation_manifest.yaml",
               "AN001_REFERENCE_INTEGRATION.md")

_IC_DOC_SET = ("PRELIMINARY_DATASHEET.md", "RELEASE_NOTES.md", "ERRATA.md",
               "documentation_manifest.yaml")


def _plant_docs(run: Path, arm: str, release: str, names) -> list:
    """One arm's document set for one release. Returns the run-relative paths."""
    d = run / _RDC.doc_dir(arm) / release
    d.mkdir(parents=True, exist_ok=True)
    rels = []
    for n in names:
        (d / n).write_text(f"# {n}\n\nrelease {release}, arm {arm}\n")
        rels.append(f"{_RDC.doc_dir(arm)}/{release}/{n}")
    return rels


def _declare_route(run: Path, deliverable: str) -> None:
    """The run's delivery route, written the way step 0.5ic writes it."""
    doc = _TD.blank_declaration()
    doc, _ignored = _TD.merge_answers(doc, {"deliverable": deliverable})
    _OD.attest(doc)   # the fixture means "the owner declared this route"
    p = run / _TD.DECLARATION_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))


def _plant_ic_signoff(run: Path) -> None:
    """Step 37.5ic's five NON-document declared outputs, where it writes them."""
    rp = run / "reports" / "phase3"
    rp.mkdir(parents=True, exist_ok=True)
    for n in ("tapeout_precheck.json", "general_precheck.json",
              "shuttle_precheck.json"):
        (rp / n).write_text("{}")
    (rp / "docs").mkdir(parents=True, exist_ok=True)
    (rp / "docs" / "SIGNOFF_widgetmul_openpdkx.html").write_text("<html></html>")
    (rp / "docs" / "BRIEF_widgetmul_openpdkx.html").write_text("<html></html>")


def _ip_run(tmp_path, names=_IP_DOC_SET, release: str = "widgetblock"):
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_HARDMACRO)
    rels = _plant_docs(run, "ip", release, names)
    return run, rels


def test_an_ip_run_stages_its_whole_37_5ip_document_set(tmp_path):
    """THE #2017 PIN. Seven files in the run, seven files in the cell."""
    run, rels = _ip_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 0, r.stdout + r.stderr
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert len(rels) == 7
    for rel in rels:
        assert (cell / rel).is_file(), f"{rel} was not staged: {r.stdout}"


def test_a_dry_run_lists_the_document_set_it_would_stage(tmp_path):
    """The acceptance shape: --dry-run must NAME the documents, and write none."""
    run, rels = _ip_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    r = _run(_base_args(run, dest_root) + ["--dry-run", "--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert not dest_root.exists()
    summary = json.loads(out.read_text())
    state = summary["release_documentation"]
    assert state["design_kind"] == "IP"
    assert state["arms"]["ip"]["n_files_in_run"] == 7
    assert state["arms"]["ip"]["n_files_in_cell"] == 7


def test_an_ip_cell_missing_one_document_is_REFUSED(tmp_path):
    """The invariant, not the scope: drop the copy subtree and the publish
    must FAIL rather than quietly produce the v1.14.88 cell again."""
    run, rels = _ip_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    prog = (PROG.parent / "benchmark_evidence_publish.py").read_text()
    hobbled = tmp_path / "hobbled_publish.py"
    # The ONE edit that reproduces #2017: the documentation subtree is not
    # copied. Everything else about the program is unchanged, so a PASS here
    # would mean the invariant is not the thing holding the line.
    assert "    Path(_release_docs_contract.DOC_ROOT),\n" in prog
    hobbled.write_text(prog.replace(
        "    Path(_release_docs_contract.DOC_ROOT),\n", "", 1))
    env = dict(os.environ, PYTHONPATH=str(PROG.parent))
    r = subprocess.run([sys.executable, str(hobbled)] + _base_args(run, dest_root),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "#2017" in (r.stdout + r.stderr)
    for rel in rels:
        assert rel in (r.stdout + r.stderr), f"{rel} not named in the refusal"


def test_an_ip_run_whose_own_document_set_is_short_is_REFUSED(tmp_path):
    """A run missing a CONTRACT-required document is refused by name, and the
    refusal says the run is short rather than blaming the publish."""
    short = tuple(n for n in _IP_DOC_SET if n != "IP_INTEGRATION_GUIDE.md")
    run, _rels = _ip_run(tmp_path, names=short)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IP_INTEGRATION_GUIDE.md" in (r.stdout + r.stderr)
    assert "IN THE RUN ITSELF" in (r.stdout + r.stderr)


def test_an_ip_run_with_no_document_set_at_all_is_REFUSED(tmp_path):
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_HARDMACRO)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NO release directory" in (r.stdout + r.stderr)


def test_an_ic_run_stages_its_required_and_existing_optional_document_sets(tmp_path):
    """An IC owes its nine outputs; optional IP documents already produced
    by the run are still staged rather than silently dropped."""
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_DIE)
    _plant_ic_signoff(run)
    ic_rels = _plant_docs(run, "ic", "widgetdie", _IC_DOC_SET)
    ip_rels = _plant_docs(run, "ip", "widgetdie", _IP_DOC_SET)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    r = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    for rel in ic_rels + ip_rels:
        assert (cell / rel).is_file(), rel
    state = json.loads(out.read_text())["release_documentation"]
    assert state["design_kind"] == "IC"
    assert state["arms_required"] == ["ic"]
    assert state["arms"]["ip"]["required_by_this_kind"] is False
    # The count the owner ruled on, DERIVED from the flow rather than typed.
    assert len(state["arms"]["ic"]["declared_outputs_enforced"]) == 9


def test_an_ic_run_without_ip_documents_is_published(tmp_path):
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_DIE)
    _plant_ic_signoff(run)
    _plant_docs(run, "ic", "widgetdie", _IC_DOC_SET)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 0, r.stdout + r.stderr
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert (cell / _RDC.doc_dir("ic")).is_dir()
    assert not (cell / _RDC.doc_dir("ip")).exists()


def test_an_ic_run_missing_a_declared_signoff_output_is_REFUSED(tmp_path):
    """The nine are enforced as OUTPUTS, not just as documents."""
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_DIE)
    _plant_ic_signoff(run)
    (run / "reports" / "phase3" / "shuttle_precheck.json").unlink()
    _plant_docs(run, "ic", "widgetdie", _IC_DOC_SET)
    _plant_docs(run, "ip", "widgetdie", _IP_DOC_SET)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "shuttle_precheck.json" in (r.stdout + r.stderr)


def _flow109_release_docs(tmp_path, *, shuttle=False):
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_DIE)
    answers = _OD.attest({'answers': {'deliverable': _TD.DELIVERABLE_DIE},
        'operator_template': {'path': None, 'slot': 'owned-slot' if shuttle else None,
            'absent_reason': 'Owner selects an independent self-tapeout.'}})
    (run / 'input/step_0_5ic_answers.json').write_text(json.dumps(answers))
    _plant_ic_signoff(run)
    _plant_docs(run, 'ic', 'widgetdie', _IC_DOC_SET)
    plan = run / 'reports/flow109/plan.json'
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({'rows': []}))
    (run / 'reports/phase3/tapeout_precheck.json').write_text(json.dumps({'verdict': 'PASS'}))
    return run


def _release_docs_check(run):
    import benchmark_evidence_publish as publisher
    return publisher.release_docs_invariant(run,
        {p.relative_to(run).as_posix() for p in run.rglob('*') if p.is_file()})


def test_dry_run_counts_selected_row_folders_and_the_real_publication_files(tmp_path):
    # Synthetic transport only: compare the plan with an actual fixture copy,
    # including repeated attempts, an unselected row and legacy history.
    from step_output_collector import flow109_step_folder
    run = _flow109_release_docs(tmp_path)
    rows = [{'position': 1, 'name': 'First tool'},
            {'position': 2, 'name': 'Second tool'}]
    (run / 'reports/flow109/plan.json').write_text(json.dumps({'rows': rows}))
    for row, stamps in [(rows[0], ['20260101', '20260102']),
                        (rows[1], ['20260101']),
                        ({'position': 3, 'name': 'Unselected'}, ['20260101'])]:
        for stamp in stamps:
            folder = run / 'steps' / flow109_step_folder(row) / stamp
            (folder / 'outputs').mkdir(parents=True)
            (folder / 'result.json').write_text('{"status":"PASS"}\n')
            (folder / 'outputs/tool.log').write_text('TRANSPORT FIXTURE\n')
    legacy = run / 'steps/legacy/1_transport'
    legacy.mkdir(parents=True)
    (legacy / 'outputs.json').write_text('{"outputs": []}')
    (legacy / 'note.txt').write_text('Historical transport record\n')
    limitations = 'signal EM, ESD simulation, dynamic IR, thermal and aging: NOT_MEASURED'
    documents = list((run / _RDC.doc_dir('ic')).rglob('*.*'))
    documents += list((run / 'reports/phase3/docs').glob('*.html'))
    for doc in documents:
        doc.write_text(doc.read_text() + '\n' + limitations + '\n')
    references = {f'document_{i}_path': doc.relative_to(run).as_posix()
                  for i, doc in enumerate(documents)}
    (run / 'reports/release_documents.json').write_text(json.dumps(references))
    dest_root = tmp_path / 'benchmark-data'
    dry_summary, real_summary = tmp_path / 'dry.json', tmp_path / 'real.json'
    args = _base_args(run, dest_root)
    dry = _run(args + ['--dry-run', '--json', str(dry_summary)])
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert not dest_root.exists()
    real = _run(args + ['--json', str(real_summary)])
    assert real.returncode == 0, real.stdout + real.stderr
    planned, copied = [json.loads(path.read_text()) for path in (dry_summary, real_summary)]
    cell = Path(copied['dest'])
    for summary in (planned, copied):
        assert summary['step_evidence']['n_steps'] == 2
        assert summary['step_evidence']['n_selected_rows'] == 2
        assert summary['step_evidence']['n_legacy_steps'] == 1
        assert summary['step_evidence']['n_canonical_attempts'] == 4
        assert summary['step_evidence']['n_records_copied'] == 9
        assert summary['file_count'] == sum(p.is_file() for p in cell.rglob('*'))
        shared = dest_root / 'ic/widgetmul/input'
        assert summary['shared_input_file_count'] == sum(p.is_file() for p in shared.rglob('*'))
        assert summary['total_file_count'] == summary['file_count'] + summary['shared_input_file_count']
    for doc in documents:
        delivered = cell / doc.relative_to(run)
        assert delivered.read_bytes() == doc.read_bytes()
        assert limitations in delivered.read_text()
    assert planned['step_evidence'] == copied['step_evidence']


def test_flow109_self_tapeout_uses_native_precheck_without_legacy_reports(tmp_path):
    run = _flow109_release_docs(tmp_path)
    for name in ('general_precheck.json', 'shuttle_precheck.json'):
        (run / 'reports/phase3' / name).unlink()
    state, violations = _release_docs_check(run)
    assert violations == [], violations
    declared = state['arms']['ic']['declared_outputs_enforced']
    assert 'reports/phase3/tapeout_precheck.json' in declared
    assert 'reports/phase3/general_precheck.json' not in declared
    assert 'reports/phase3/shuttle_precheck.json' not in declared
    assert len(declared) == len(set(declared))


def test_external_kit_provenance_preserves_the_release_precheck_and_routing(tmp_path):
    import citation_routing_is_true_check as routing
    import evidence_citation_resolves_check as citations
    run = _flow109_release_docs(tmp_path)
    cite = '/retired-store/kit/procx/libs.ref/cellsZ/model.gds:UNITS'
    (run / 'reports/phase3/tapeout_precheck.json').write_text(json.dumps({
        'verdict': 'PASS', 'final_declaration': 'reports/phase3/transport_declaration.json'}))
    (run / 'reports/phase3/transport_declaration.json').write_text(json.dumps({
        'verdict': 'PASS', 'source': cite}))
    dest_root = tmp_path / 'benchmark-data'
    result = _run(_base_args(run, dest_root))
    assert result.returncode == 0, result.stdout + result.stderr
    cell = dest_root / 'ic/widgetmul/v9.9.9_openpdkx'
    assert json.loads((cell / 'reports/phase3/tapeout_precheck.json').read_text())['verdict'] == 'PASS'
    assert json.loads((cell / 'reports/phase3/transport_declaration.json').read_text())['source'] == cite
    assert _routing_rows(cell)[('reports/phase3/transport_declaration.json', cite)] == 'EXTERNAL_PDK'
    assert routing.audit_cell(cell)['false_claims'] == []
    disclosed = citations._disclosed_map(cell, None)
    key = ('reports/phase3/transport_declaration.json', cite)
    assert disclosed[key] == 'EXTERNAL_PDK'
    text = (cell / 'CITATION_ROUTING.txt').read_text()
    revision = json.loads((cell / 'reports/pdk_revision.json').read_text())['revision']
    assert 'libs.ref/cellsZ/model.gds:UNITS' in text and revision in text
    assert not (cell / 'libs.ref').exists()
    (cell / 'reports/pdk_revision.json').unlink()
    assert key not in citations._disclosed_map(cell, None)


@pytest.mark.parametrize('dry', [False, True])
@pytest.mark.parametrize('case', ['same', 'source-changed', 'unselected', 'snapshot-missing', 'unrecorded'])
def test_preplanned_native_inputs_are_referenced_from_their_recorded_snapshots(tmp_path, dry, case):
    import step_output_collector as collector
    run = _flow109_release_docs(tmp_path)
    row = {'id': 'D01', 'position': 1, 'name': 'Requirements and delivery route'}
    context = {'context_sha256': hashlib.sha256(b'public transport fixture').hexdigest()}
    attempt = collector.begin_flow109_row(run, row, context)
    paths = ['phase3/native/tool.spice', 'phase3/native/tool.nl.v']
    for rel in paths:
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('* PUBLIC TRANSPORT FIXTURE ONLY\n' * 36000)
    proof = {'verdict': 'PASS', 'spice_file': paths[0], 'netlist_file': paths[1],
             'documents_scanned': paths.copy()}
    (run / 'reports/phase3/transport_inputs.json').write_text(json.dumps(proof))
    collector.finish_flow109_row(run, row, context,
        {'default_row_status': 'PASS', **proof}, attempt)
    (run / 'reports/flow109/plan.json').write_text(json.dumps({
        'rows': [] if case == 'unselected' else [row]}))
    (run / 'reports/phase3/tapeout_precheck.json').write_text(json.dumps({
        'verdict': 'PASS', 'final_declaration': 'reports/phase3/transport_inputs.json'}))
    if case == 'source-changed':
        with (run / paths[1]).open('a') as stream:
            stream.write('changed source\n')
    elif case == 'snapshot-missing':
        (attempt['folder'] / 'outputs' / paths[1]).unlink()
    elif case == 'unrecorded':
        other = 'phase3/native/unrecorded.spice'
        (run / other).write_bytes((run / paths[0]).read_bytes())
        proof['spice_file'] = other
        (run / 'reports/phase3/transport_inputs.json').write_text(json.dumps(proof))
    dest_root = tmp_path / 'benchmark-data'
    result = _run(_base_args(run, dest_root) + (['--dry-run'] if dry else []))
    if case not in ('same', 'unselected'):
        assert result.returncode == 1, result.stdout + result.stderr
        assert 'published verdict is UNSUBSTANTIATED' in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        if not dry:
            cell = dest_root / 'ic/widgetmul/v9.9.9_openpdkx'
            data = json.loads((cell / 'reports/phase3/transport_inputs.json').read_text())
            for key, original in [('spice_file', paths[0]), ('netlist_file', paths[1])]:
                assert data[key].startswith('steps/001_')
                assert (cell / data[key]).read_bytes() == (run / original).read_bytes()
                assert not (cell / original).exists()
            assert data['verdict'] == 'PASS'
            assert data['documents_scanned'] == paths
            assert json.loads((cell / 'reports/phase3/tapeout_precheck.json').read_text())['verdict'] == 'PASS'
    if dry:
        assert not dest_root.exists()


@pytest.mark.parametrize('actual_evidence', [False, True])
@pytest.mark.parametrize('dry', [False, True])
def test_scan_census_stays_visible_while_real_answer_evidence_stays_required(
        tmp_path, actual_evidence, dry):
    run = _flow109_release_docs(tmp_path)
    old = 'reports/phase2/old_fpga.json'
    (run / old).parent.mkdir(parents=True, exist_ok=True)
    (run / old).write_text(json.dumps({'verdict': 'PASS',
        'source': 'phase2/stage1/fpga/missing.sdc'}))
    io = {'verdict': 'PASS', 'documents_scanned': [old]}
    if actual_evidence:
        io['derived_answers'] = {'signal': {'evidence': old}}
    (run / 'reports/phase3/transport_io.json').write_text(json.dumps(io))
    (run / 'reports/phase3/tapeout_precheck.json').write_text(json.dumps({
        'verdict': 'PASS', 'final_declaration': 'reports/phase3/transport_io.json'}))
    dest_root = tmp_path / 'benchmark-data'
    result = _run(_base_args(run, dest_root) + (['--dry-run'] if dry else []))
    assert result.returncode == (1 if actual_evidence else 0), result.stdout + result.stderr
    if actual_evidence:
        assert 'published verdict is UNSUBSTANTIATED' in result.stderr
    elif not dry:
        delivered = dest_root / 'ic/widgetmul/v9.9.9_openpdkx/reports/phase3/transport_io.json'
        assert json.loads(delivered.read_text()) == io
    if dry:
        assert not dest_root.exists()


@pytest.mark.parametrize('verdict', ['FAIL', 'NOT_MEASURED', 'UNSUBSTANTIATED'])
def test_release_requires_pass_in_the_published_precheck_too(tmp_path, verdict):
    import benchmark_evidence_publish as publisher
    run = _flow109_release_docs(tmp_path)
    rels = {p.relative_to(run).as_posix() for p in run.rglob('*') if p.is_file()}
    _, violations = publisher.release_docs_invariant(run, rels,
        published_verdicts={'reports/phase3/tapeout_precheck.json': verdict})
    assert any(f'published verdict is {verdict}' in v for v in violations), violations


@pytest.mark.parametrize('dry', [False, True])
def test_source_pass_cannot_hide_a_published_unsubstantiated_release_precheck(tmp_path, dry):
    run = _flow109_release_docs(tmp_path)
    native = run / 'reports/phase3/tapeout_precheck.json'
    native.write_text(json.dumps({'verdict': 'PASS',
        'final_declaration': 'reports/phase3/transport_declaration.json'}))
    (run / 'reports/phase3/transport_declaration.json').write_text(json.dumps({
        'verdict': 'PASS', 'source': str(tmp_path / 'historical-absent-source.json')}))
    before = native.read_bytes()
    dest_root = tmp_path / 'benchmark-data'
    args = _base_args(run, dest_root) + (['--dry-run'] if dry else [])
    result = _run(args)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'native verdict is PASS, published verdict is UNSUBSTANTIATED' in result.stderr
    assert 'step folders;' in result.stderr and 'cell file(s)' in result.stderr
    assert '#2017' in result.stderr
    assert native.read_bytes() == before
    if dry:
        assert not dest_root.exists()
    else:
        delivered = dest_root / 'ic/widgetmul/v9.9.9_openpdkx' / native.relative_to(run)
        assert json.loads(delivered.read_text())['verdict'] == 'UNSUBSTANTIATED'


@pytest.mark.parametrize('verdict', ['FAIL', 'NOT_MEASURED', None, 'invalid-json'])
def test_flow109_native_precheck_cannot_fall_back_to_legacy_pass(tmp_path, verdict):
    run = _flow109_release_docs(tmp_path)
    (run / 'reports/phase3/general_precheck.json').write_text(json.dumps({'verdict': 'PASS'}))
    native = run / 'reports/phase3/tapeout_precheck.json'
    if verdict is None:
        native.unlink()
    else:
        native.write_text('not JSON' if verdict == 'invalid-json' else json.dumps({'verdict': verdict}))
    _, violations = _release_docs_check(run)
    assert any('native verdict' in item and 'tapeout_precheck.json' in item for item in violations)


def test_flow109_shuttle_still_requires_the_operator_precheck(tmp_path):
    run = _flow109_release_docs(tmp_path, shuttle=True)
    (run / 'reports/phase3/general_precheck.json').unlink()
    shuttle = run / 'reports/phase3/shuttle_precheck.json'
    shuttle.unlink()
    _, violations = _release_docs_check(run)
    assert any('shuttle_precheck.json' in item for item in violations)
    shuttle.write_text('{}')
    assert _release_docs_check(run)[1] == []


def test_non_flow109_still_requires_the_legacy_general_precheck(tmp_path):
    run = _flow109_release_docs(tmp_path)
    (run / 'reports/flow109/plan.json').unlink()
    (run / 'reports/phase3/general_precheck.json').unlink()
    _, violations = _release_docs_check(run)
    assert any('general_precheck.json' in item for item in violations)


@pytest.mark.parametrize('missing', ['PRELIMINARY_DATASHEET.md', 'SIGNOFF_widgetmul_openpdkx.html'])
def test_flow109_native_precheck_does_not_replace_required_release_documents(tmp_path, missing):
    run = _flow109_release_docs(tmp_path)
    next(p for p in run.rglob(missing) if p.is_file()).unlink()
    _, violations = _release_docs_check(run)
    assert any(missing in item or (missing.startswith('SIGNOFF_') and 'SIGNOFF_' in item)
               for item in violations)


def test_an_ip_run_is_NOT_asked_for_the_ic_set(tmp_path):
    """The honest half: an IP has no die, and a run with no ic/ tree stages
    nothing for that arm and is not refused for it."""
    run, _rels = _ip_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    r = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    state = json.loads(out.read_text())["release_documentation"]
    assert state["arms"]["ic"]["required_by_this_kind"] is False
    assert state["arms"]["ic"]["n_files_in_run"] == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert not (cell / _RDC.doc_dir("ic")).exists()


def test_the_kind_comes_from_the_route_not_from_the_design_name(tmp_path):
    """Same design name, two declarations, two kinds — and no chip literal
    anywhere in the decision."""
    import importlib
    sys.path.insert(0, str(PROG.parent))
    bep = importlib.import_module("benchmark_evidence_publish")
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_HARDMACRO)
    assert bep.design_kind(run)[0] == "IP"
    _declare_route(run, _TD.DELIVERABLE_DIE)
    assert bep.design_kind(run)[0] == "IC"
    # R-0915-65 — THE OPERATOR'S BINDING OUTRANKS THE DECLARATION; THE
    # OPERATOR'S CATALOGUE DOES NOT. This step used to assert that ingesting
    # `slots/*.yaml` alone flipped a HARDMACRO to IC. MEASURED on spm x
    # gf180mcuD: since step 0.5ic's fetch was wired, every design whose PDK has
    # a live shuttle gets the operator's whole catalogue ingested, bought or
    # not — so a HARDMACRO that binds nothing classified IC, and the publisher
    # then refused the cell for step 37.5ic's nine die-path outputs while the
    # run's own 37.5ic sat at design-declared NOT_APPLICABLE. A catalogue is
    # information, not a purchase.
    slots = run / "input" / "submission_template" / "slots"
    slots.mkdir(parents=True, exist_ok=True)
    (slots / "s.yaml").write_text("SLOT: a\n")
    _declare_route(run, _TD.DELIVERABLE_HARDMACRO)
    assert bep.design_kind(run)[0] == "IP", (
        "an ingested catalogue is not a binding")

    # …and a BINDING still does outrank it, which is the half that must not be
    # lost: the design names the slot it bought.
    (run / "input" / "step_0_5ic_answers.json").write_text(json.dumps(
        {"operator_template": {"path": None, "slot": "s"}}))
    assert bep.design_kind(run)[0] == "IC"


def test_an_undeclared_route_is_disclosed_and_not_silently_passed(tmp_path):
    """A run that never said what it is cannot be told what it owes. The cell
    publishes, and says so."""
    run = _make_run(tmp_path)          # `_make_run` writes no declaration
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "s.json"
    r = _run(_base_args(run, dest_root) + ["--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "declares no delivery route" in r.stderr
    state = json.loads(out.read_text())["release_documentation"]
    assert state["design_kind"] == "UNDECLARED"
    assert state["enforced"] is False


@pytest.mark.parametrize("kind,missing,expected_rc", [
    ("IC", None, 0),
    ("IC", "PRELIMINARY_DATASHEET.md", 1),
    ("IP", "IP_INTEGRATION_GUIDE.md", 1),
])
def test_publication_requires_the_selected_delivery_document_arm(
        tmp_path, kind, missing, expected_rc):
    """Exercise the real publisher CLI, route reader and repository flow
    output contract. Other-arm documents cannot replace a required document.
    All artefacts are neutral transport fixtures, not native signoff evidence.
    """
    run = _make_run(tmp_path)
    deliverable = (_TD.DELIVERABLE_DIE if kind == "IC"
                   else _TD.DELIVERABLE_HARDMACRO)
    _declare_route(run, deliverable)
    arm = kind.lower()
    if kind == "IC":
        _plant_ic_signoff(run)
    own = _plant_docs(run, arm, "neutral-release",
                      _IC_DOC_SET if kind == "IC" else _IP_DOC_SET)
    if missing:
        (run / _RDC.doc_dir(arm) / "neutral-release" / missing).unlink()
        # Having the other arm's complete documents cannot excuse the loss.
        other = "ip" if kind == "IC" else "ic"
        _plant_docs(run, other, "neutral-release",
                    _IP_DOC_SET if other == "ip" else _IC_DOC_SET)
        if kind == "IP":
            _plant_ic_signoff(run)
    dest = tmp_path / "benchmark-data"
    report = tmp_path / "publication.json"
    proc = _run(_base_args(run, dest) + ["--json", str(report)])
    cell = dest / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    observed = {"rc": proc.returncode, "success_summary_exists": report.exists()}
    expected = {"rc": expected_rc, "success_summary_exists": expected_rc == 0}
    (tmp_path / "delivery-document-observation.json").write_text(json.dumps({
        "kind": kind, "missing": missing, "observed": observed,
        "expected": expected, "partial_cell_exists": cell.exists(),
        "argv": proc.args,
        "stdout": proc.stdout, "stderr": proc.stderr,
        "scope": "Real publication CLI; neutral source transport only."},
        indent=2))
    assert observed == expected, {"observed": observed, "expected": expected,
                                  "stderr": proc.stderr}
    if expected_rc:
        assert missing in proc.stdout + proc.stderr
        assert "release documentation INVARIANT" in proc.stdout + proc.stderr
        assert "IN THE RUN ITSELF" in proc.stdout + proc.stderr
    else:
        state = json.loads(report.read_text())["release_documentation"]
        assert state["arms_required"] == [arm]
        assert len(state["arms"]["ic"]["declared_outputs_enforced"]) == 9
        assert not (cell / _RDC.doc_dir("ip")).exists()
        assert all((cell / rel).is_file() for rel in own)
