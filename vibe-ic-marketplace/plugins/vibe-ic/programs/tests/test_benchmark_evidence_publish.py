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


# --------------------------------------------------------------------------
# #2017 — the release documentation is REQUIRED, per DESIGN KIND
#
# The defect: the spm x gf180mcuD run produced the full 37.5ip document set
# and the published cell carried NONE of it, every file recorded
# OUT_OF_PUBLISHED_SCOPE. The owner's ruling makes the set an INVARIANT keyed
# on the design KIND read from the delivery route — an IC owes 37.5ic's nine
# declared outputs AND the 37.5ip document set; an IP owes the 37.5ip set.
# --------------------------------------------------------------------------

sys.path.insert(0, str(PROG.parent))
import _release_docs_contract as _RDC  # noqa: E402
import _tapeout_declaration as _TD  # noqa: E402

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


def test_an_ic_run_owes_BOTH_sets_and_a_complete_one_is_staged(tmp_path):
    """The IC kind: 37.5ic's nine declared outputs AND the 37.5ip document
    set, both in the cell."""
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
    assert sorted(state["arms_required"]) == ["ic", "ip"]
    # The count the owner ruled on, DERIVED from the flow rather than typed.
    assert len(state["arms"]["ic"]["declared_outputs_enforced"]) == 9


def test_an_ic_run_missing_the_ip_document_set_is_REFUSED(tmp_path):
    run = _make_run(tmp_path)
    _declare_route(run, _TD.DELIVERABLE_DIE)
    _plant_ic_signoff(run)
    _plant_docs(run, "ic", "widgetdie", _IC_DOC_SET)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "37.5ip" in (r.stdout + r.stderr)


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
    # The operator's answer outranks the declaration.
    slots = run / "input" / "submission_template" / "slots"
    slots.mkdir(parents=True, exist_ok=True)
    (slots / "s.yaml").write_text("SLOT: a\n")
    _declare_route(run, _TD.DELIVERABLE_HARDMACRO)
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
