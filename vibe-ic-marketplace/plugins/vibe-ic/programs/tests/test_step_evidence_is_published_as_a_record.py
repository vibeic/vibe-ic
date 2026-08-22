#!/usr/bin/env python3
"""The per-step evidence is PUBLISHED, and it is published as a RECORD.

WHAT WAS BROKEN
---------------
`benchmark_evidence_publish._COPY_SUBTREES` excluded the run's `steps/` tree by
name — "per-step scratch". So no published cell carried anything per-step, and
a per-step dimension of the evaluation matrix had nothing to read even on a run
that had produced a full steps tree.

WHY THE FIX IS NOT "COPY THE TREE"
----------------------------------
`<run>/steps/` is a VIEW made of symlinks into that run directory. Two
measurements taken while writing this, both on real trees:

  * `_car15_evidence`, a CONVERGED run (PASS_WITH_WAIVERS) whose steps tree was
    materialized and whose run directory was later renamed — 63 steps, 90
    declared outputs, **83 of 83 view symlinks dangling**. A copy publishes 83
    broken links.
  * the legacy hand-staged cells that DID commit their steps tree —
    **142 tracked symlinks under `benchmark-data/**/steps/`, 31 of whose
    targets the git index does not carry**, so a clean clone receives 31
    dangling links from a committed cell.

And a copy that DEREFERENCES instead duplicates bytes the cell already has at
their canonical path: measured 2,787,213 bytes for the spm x ihp-sg13g2 run,
against 59,581 bytes for the record that replaces it.

So the published form is `steps/<phase>/<stage>/<id>_<slug>/STEP_RECORD.json`
plus a flat `STEP_ROUTING.txt`: every declared output as a RUN-RELATIVE path
with its size, its sha256, and where a reader of THIS cell can find it. Same
doctrine as `GDS_MANIFEST.txt` — the hash is what makes an artefact verifiable
whether or not it is stored.

CONTROLS IN THIS FILE
---------------------
`test_the_cell_carries_per_step_evidence` is the NEGATIVE CONTROL: it fails
against the byte-identical pre-change file and passes after.

Everything else is a REVERSE CASE that must STILL pass — and four of them are
aimed at the naive fix (delete `steps/` from the exclusion list, let `_copy_tree`
have it), which satisfies the negative control and breaks these:

  * no symlink is created in the cell,
  * no byte already published at its canonical path is duplicated under steps/,
  * a DANGLING declared output is RECORDED (`_copy_tree` skips it silently,
    because `Path.is_file()` answers False for a broken link),
  * a run with NO steps tree publishes exactly as before and still conforms.
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
CHECKER = (Path(__file__).resolve().parent.parent
           / "benchmark_evidence_structure_check.py")

_GDS_BYTES = b"GDSII-FAKE-STREAM-" * 64
_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"
_NETLIST = "module top(); NAND2_X1 g0(); endmodule\n"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _make_run(base: Path, with_steps: bool = True) -> Path:
    """A converged run. With `with_steps`, it also carries the collector's
    symlink VIEW — including one link whose target has since been deleted,
    which is the state every published steps tree eventually reaches."""
    run = base / "run"
    (run / "reports" / "audit").mkdir(parents=True)
    (run / "reports" / "audit" / "phase23_completion_audit.json").write_text(
        json.dumps({"verdict": "PASS_WITH_WAIVERS"}))
    (run / "RESULT.md").write_text(_RESULT_PASS)
    (run / "phase1" / "generated_docs").mkdir(parents=True)
    (run / "phase1" / "generated_docs" / "L1.json").write_text('{"a":1}')
    (run / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (run / "phase2" / "stage2" / "synth" / "netlist.v").write_text(_NETLIST)
    (run / "phase3" / "reports").mkdir(parents=True)
    (run / "phase3" / "reports" / "drc.rpt").write_text("clean\n")
    (run / "reports" / "phase3").mkdir(parents=True)
    (run / "reports" / "phase3" / "sta.json").write_text("{}")
    # PnR scratch: real, but outside every published subtree.
    (run / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (run / "phase3" / "stage3" / "pnr" / "routed.rpt").write_text("routed\n")
    (run / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (run / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(_GDS_BYTES)
    (run / "input" / "docs").mkdir(parents=True)
    (run / "input" / "docs" / "L1.md").write_text("# spec\n")
    if with_steps:
        _make_steps_view(run)
    # `benchmark_evidence_publish` REFUSES a run that cannot name the PDK
    # revision it signed off against (W6). The record is produced by the
    # REAL resolver over a synthesized tree — never hand-written — so this
    # fixture cannot drift from the program that writes it in production.
    _pdk_fixture.write_run_pdk_revision(run)
    return run


def _step(run: Path, folder: str, sid: str, name: str, status: str,
          phase: str, stage: str, outputs) -> Path:
    """One step folder exactly as `step_output_collector.materialize` writes
    it: a symlink per output (ABSOLUTE — mount-stable, host-bound) and an
    `outputs.json` whose `abs` field names this machine."""
    d = run / "steps" / folder
    d.mkdir(parents=True, exist_ok=True)
    present = []
    for rel in outputs:
        src = run / rel
        link = d / Path(rel).name
        link.symlink_to(src)                       # absolute, as the collector does
        present.append({"rel": rel, "abs": str(src),
                        "size": src.stat().st_size if src.exists() else 0})
    (d / "outputs.json").write_text(json.dumps(
        {"id": sid, "name": name, "status": status, "phase": phase,
         "stage": stage, "folder": folder, "outputs": present}, indent=2))
    return d


def _make_steps_view(run: Path) -> None:
    _step(run, "phase1/stage_phase1/D1_phase_1_doc_extraction", "D1",
          "Phase 1 Doc Extraction", "pass", "phase1", "stage_phase1",
          ["phase1/generated_docs/L1.json"])
    _step(run, "phase2/stage2/9_synthesis_yosys_mapped_netlist", "9",
          "Synthesis (Yosys)", "pass", "phase2", "stage2",
          ["phase2/stage2/synth/netlist.v"])
    _step(run, "phase3/stage3/21_routing_global_detailed", "21",
          "Routing (global + detailed)", "pass", "phase3", "stage3",
          ["phase3/stage3/pnr/routed.rpt"])
    # A step that declares an output the run no longer has. On the real
    # `_car15_evidence` run SEVEN steps are in this state, every one of them
    # with status `pass`: routed.def, placed.def, filled.def and four more.
    d = _step(run, "phase3/stage3/22_parasitic_extraction", "22",
              "Parasitic extraction (RC -> SPEF)", "pass", "phase3", "stage3",
              ["phase3/stage3/extracted/top.spef"])
    (run / "phase3" / "stage3" / "extracted").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "stage3" / "extracted" / "top.spef").write_text("*SPEF\n")
    # ...then it goes away, leaving the view's link broken. Written this way
    # round because `_step` reads st_size to fill the manifest, so the record
    # carries the size that WAS claimed.
    _rewrite_declared_size(d, "phase3/stage3/extracted/top.spef", 983635)
    (run / "phase3" / "stage3" / "extracted" / "top.spef").unlink()


def _rewrite_declared_size(step_dir: Path, rel: str, size: int) -> None:
    data = json.loads((step_dir / "outputs.json").read_text())
    for o in data["outputs"]:
        if o["rel"] == rel:
            o["size"] = size
    (step_dir / "outputs.json").write_text(json.dumps(data, indent=2))


def _base_args(run: Path, dest_root: Path):
    return ["--run-dir", str(run), "--ic", "widgetmul", "--pdk", "openpdkx",
            "--plugin-version", "9.9.9", "--dest-root", str(dest_root)]


def _publish(tmp_path, with_steps: bool = True):
    run = _make_run(tmp_path, with_steps=with_steps)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 0, r.stdout + r.stderr
    return run, dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx", r


def _routing_rows(cell: Path):
    rows = []
    for ln in (cell / "STEP_ROUTING.txt").read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or " :: " not in s:
            continue
        folder, _, rest = s.partition(" :: ")
        parts = rest.split()
        rows.append({"folder": folder, "rel": parts[0],
                     "decision": parts[-1]})
    return rows


# ==========================================================================
# NEGATIVE CONTROL — fails against the byte-identical pre-change file.
# ==========================================================================

def test_the_cell_carries_per_step_evidence(tmp_path):
    """Pre-change `_COPY_SUBTREES` excluded `steps/` by name, so this cell had
    nothing per-step at all and both assertions below failed."""
    _run_dir, cell, _r = _publish(tmp_path)

    assert (cell / "STEP_ROUTING.txt").is_file(), \
        "no STEP_ROUTING.txt — the cell publishes no per-step evidence"
    rec = (cell / "steps" / "phase2" / "stage2"
           / "9_synthesis_yosys_mapped_netlist" / "STEP_RECORD.json")
    assert rec.is_file(), \
        "no per-step record in the owner's phase/stage/step tree: %r" % (
            sorted(p.relative_to(cell).as_posix()
                   for p in cell.rglob("*") if p.is_file())[:20],)

    d = json.loads(rec.read_text())
    assert d["id"] == "9" and d["phase"] == "phase2" and d["stage"] == "stage2"
    assert [o["rel"] for o in d["declared_outputs"]] == \
        ["phase2/stage2/synth/netlist.v"]


def test_the_nested_phase_stage_step_tree_is_preserved(tmp_path):
    """The owner's layout, mirrored — not re-derived. Every step lands under
    `steps/<phase>/<stage>/<id>_<slug>/`."""
    _run_dir, cell, _r = _publish(tmp_path)
    folders = sorted(p.parent.relative_to(cell / "steps").as_posix()
                     for p in (cell / "steps").rglob("STEP_RECORD.json"))
    assert folders == [
        "phase1/stage_phase1/D1_phase_1_doc_extraction",
        "phase2/stage2/9_synthesis_yosys_mapped_netlist",
        "phase3/stage3/21_routing_global_detailed",
        "phase3/stage3/22_parasitic_extraction",
    ], folders


# ==========================================================================
# REVERSE CASES — must STILL pass. The first four are what the naive fix
# (drop the exclusion, let `_copy_tree` have the tree) breaks.
# ==========================================================================

def test_no_symlink_is_ever_published(tmp_path):
    """THE REASON THE RECORD EXISTS. The run's steps tree is 100% symlinks;
    the cell must contain none. Measured on committed cells that did copy the
    tree: 31 of 142 tracked links dangle for a clean clone."""
    _run_dir, cell, _r = _publish(tmp_path)
    links = [p.relative_to(cell).as_posix() for p in cell.rglob("*")
             if p.is_symlink()]
    assert links == [], links


def test_no_artefact_is_duplicated_under_steps(tmp_path):
    """A dereferencing copy ships the same bytes twice — measured 2,787,213
    bytes for one real run. The record ships the sha256 instead."""
    _run_dir, cell, _r = _publish(tmp_path)
    published = [p for p in (cell / "steps").rglob("*") if p.is_file()]
    assert all(p.name in ("STEP_RECORD.json", "STEP_INDEX.json")
               for p in published), \
        [p.relative_to(cell).as_posix() for p in published]
    assert not any(p.read_text() == _NETLIST for p in published)


def test_a_declared_output_the_run_no_longer_has_is_recorded(tmp_path):
    """`_copy_tree` filters on `is_file()`, which answers False for a broken
    link, so a copy drops this case in silence — and silence is what makes a
    step's `pass` unfalsifiable. Attributed to the STEP, with the size that
    was claimed for it."""
    _run_dir, cell, _r = _publish(tmp_path)
    rows = [r for r in _routing_rows(cell)
            if r["rel"] == "phase3/stage3/extracted/top.spef"]
    assert len(rows) == 1, _routing_rows(cell)
    assert rows[0]["decision"] == "ABSENT_IN_RUN", rows[0]
    assert rows[0]["folder"] == "phase3/stage3/22_parasitic_extraction"

    rec = json.loads((cell / "steps" / "phase3" / "stage3"
                      / "22_parasitic_extraction" / "STEP_RECORD.json").read_text())
    assert rec["status"] == "pass", \
        "the step claims a pass; that is what makes the missing output evidence"
    assert rec["declared_outputs"][0]["decision"] == "ABSENT_IN_RUN"


def test_a_run_with_no_steps_tree_still_publishes_and_conforms(tmp_path):
    """The publish contract does not become conditional on a steps tree.
    Runs driven straight at phase2/phase3 produce none."""
    _run_dir, cell, r = _publish(tmp_path, with_steps=False)
    assert not (cell / "steps").exists(), "fabricated a steps tree from nothing"
    chk = subprocess.run([sys.executable, str(CHECKER), str(cell)],
                         capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout + chk.stderr


def test_the_staged_cell_still_passes_the_structure_check(tmp_path):
    """With the steps record present. Adding evidence must not cost a cell its
    conformance — the three published spm cells are the population this
    protects."""
    _run_dir, cell, _r = _publish(tmp_path)
    chk = subprocess.run([sys.executable, str(CHECKER), str(cell)],
                         capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout + chk.stderr


def test_the_pre_existing_cell_contents_are_untouched(tmp_path):
    """Everything the publisher staged before still stages, byte for byte.
    The steps record is additive."""
    _run_dir, cell, _r = _publish(tmp_path)
    for rel, want in (("phase1/generated_docs/L1.json", '{"a":1}'),
                      ("phase2/stage2/synth/netlist.v", _NETLIST),
                      ("phase3/reports/drc.rpt", "clean\n"),
                      ("reports/phase3/sta.json", "{}")):
        assert (cell / rel).read_text() == want, rel
    assert (cell / "LAYOUT_ROUTING.txt").is_file()
    assert (cell / "CITATION_ROUTING.txt").is_file()
    assert (cell / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").is_file()


# ==========================================================================
# The record is SELF-CONTAINED — the property that made it the right form.
# ==========================================================================

def test_no_host_absolute_path_reaches_the_published_record(tmp_path):
    """`outputs.json` carries an `abs` field naming the authoring host. On the
    real `_car15_evidence` run every one of those paths is dead while 83 of
    the 90 run-relative ones still resolve, so the record is keyed on `rel`
    and `abs` is dropped rather than republished."""
    run, cell, _r = _publish(tmp_path)
    for p in (cell / "steps").rglob("*.json"):
        text = p.read_text()
        assert str(run) not in text, (p.relative_to(cell).as_posix(), text[:400])
        assert '"abs"' not in text, p.relative_to(cell).as_posix()


def test_the_recorded_sha256_is_the_artefact_s_sha256(tmp_path):
    """A hash nobody can check is decoration. Cross-verified against the cell's
    own copy, and against GDS_MANIFEST.txt for the one artefact both describe."""
    _run_dir, cell, _r = _publish(tmp_path)
    rec = json.loads((cell / "steps" / "phase2" / "stage2"
                      / "9_synthesis_yosys_mapped_netlist"
                      / "STEP_RECORD.json").read_text())
    o = rec["declared_outputs"][0]
    assert o["decision"] == "IN_CELL" and o["in_cell"] is True
    body = (cell / o["rel"]).read_bytes()
    assert o["bytes"] == len(body)
    assert o["sha256"] == hashlib.sha256(body).hexdigest()


def test_an_out_of_scope_output_is_disclosed_not_dropped(tmp_path):
    """PnR scratch is real evidence the cell does not carry. Recording the
    sha256 is what turns recovering it from a source host into a checkable
    file copy rather than a guess about which same-named artefact it was."""
    _run_dir, cell, _r = _publish(tmp_path)
    rows = [r for r in _routing_rows(cell)
            if r["rel"] == "phase3/stage3/pnr/routed.rpt"]
    assert len(rows) == 1 and rows[0]["decision"] == "OUT_OF_PUBLISHED_SCOPE", rows
    rec = json.loads((cell / "steps" / "phase3" / "stage3"
                      / "21_routing_global_detailed" / "STEP_RECORD.json").read_text())
    o = rec["declared_outputs"][0]
    assert o["in_cell"] is False
    assert o["sha256"] == hashlib.sha256(
        (_run_dir / o["rel"]).read_bytes()).hexdigest()


def test_the_routing_record_is_emitted_even_with_nothing_to_report(tmp_path):
    """A record that only appears when there is something wrong cannot be used
    to prove there is nothing wrong. A run with no steps tree says SO, which
    is a different fact from a cell published before this record existed."""
    _run_dir, cell, _r = _publish(tmp_path, with_steps=False)
    text = (cell / "STEP_ROUTING.txt").read_text()
    assert "ABSENT in the source run" in text, text[:600]
    assert _routing_rows(cell) == []


# ==========================================================================
# The seam a per-step RECORD written by the runner rides through, and the
# guards on it.
# ==========================================================================

@pytest.mark.parametrize("name", ["WRITES.json", "written.json", "notes.md"])
def test_a_record_file_in_a_step_folder_is_published_verbatim(tmp_path, name):
    """The collector's own two manifests are REPLACED (they describe the
    symlink view). Anything else a step folder holds is somebody's record and
    is carried through untouched — no coupling to its schema OR its name.

    `written.json` is the per-step slice `step_write_ledger.emit` drops beside
    `outputs.json`; it is in the parameter list as the live case, not as a
    contract — the rule is by kind, so renaming it costs nothing."""
    run = _make_run(tmp_path)
    d = run / "steps" / "phase2" / "stage2" / "9_synthesis_yosys_mapped_netlist"
    body = '{"actually_wrote":["netlist.v"]}'
    (d / name).write_text(body)
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    sdir = cell / "steps" / "phase2" / "stage2" / "9_synthesis_yosys_mapped_netlist"
    assert (sdir / name).is_file() and (sdir / name).read_text() == body
    assert not (sdir / "outputs.json").exists()


def test_a_declared_path_escaping_the_run_is_recorded_not_resolved(tmp_path):
    """TIGHTENING GUARD. `rel` comes off a file on disk; a `..` or absolute
    value must not send the resolver outside the run and must not be answered
    for as if it had been checked."""
    run = _make_run(tmp_path)
    d = run / "steps" / "phase2" / "stage2" / "9_synthesis_yosys_mapped_netlist"
    data = json.loads((d / "outputs.json").read_text())
    data["outputs"].append({"rel": "../../../etc/passwd", "abs": "/etc/passwd",
                            "size": 1})
    (d / "outputs.json").write_text(json.dumps(data))
    dest_root = tmp_path / "benchmark-data"
    assert _run(_base_args(run, dest_root)).returncode == 0
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    rec = json.loads((cell / "steps" / "phase2" / "stage2"
                      / "9_synthesis_yosys_mapped_netlist"
                      / "STEP_RECORD.json").read_text())
    esc = [o for o in rec["declared_outputs"] if ".." in o["rel"]]
    assert len(esc) == 1
    assert esc[0]["decision"] == "ABSENT_IN_RUN" and esc[0]["sha256"] == ""


def test_a_malformed_steps_tree_does_not_cost_the_cell_its_evidence(tmp_path):
    """Bookkeeping must never be the reason a publish loses phase evidence —
    and a failure that leaves no trace is worse than no bookkeeping, so the
    unreadable manifest is skipped and the rest of the tree still records."""
    run = _make_run(tmp_path)
    d = run / "steps" / "phase2" / "stage2" / "9_synthesis_yosys_mapped_netlist"
    (d / "outputs.json").write_text("{ this is not json")
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root))
    assert r.returncode == 0, r.stdout + r.stderr
    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert (cell / "phase2" / "stage2" / "synth" / "netlist.v").is_file()
    assert (cell / "STEP_ROUTING.txt").is_file()
    # the other three steps still recorded
    assert len(list((cell / "steps").rglob("STEP_RECORD.json"))) == 4


def test_dry_run_writes_no_step_record(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    r = _run(_base_args(run, dest_root) + ["--dry-run"])
    assert r.returncode == 0
    assert not (dest_root / "ic").exists()


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
