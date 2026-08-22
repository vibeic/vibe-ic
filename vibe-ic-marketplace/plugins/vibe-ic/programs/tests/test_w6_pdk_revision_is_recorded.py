#!/usr/bin/env python3
"""A sign-off that cannot be reproduced is not a sign-off — W6.

THE GAP THESE TESTS BIND
========================
The PDK revision a run signed off against was recorded NOWHERE. Every place a
run said anything about its PDK said the REQUEST: `--pdk <name>` on the
publisher's own command line, `env_PDK_ROOT` verbatim in a repro bundle, the
registry entry, and the published cell's own `v<version>_<PDK>` directory name.
A name is not a revision, so two cells a year apart against a re-pulled volume
are byte-identical in the record and were measured against different process
data.

`pdk_revision_resolve` reads the revision from the RESOLVED tree — the
directory the tools actually opened, after symlinks — and
`benchmark_evidence_publish` REFUSES to stage a run that does not carry it.

THE CONTROL PAIR, and which half is which
-----------------------------------------
`test_publish_refuses_*` are the FIRING half: they fail against the pre-change
program, which stages the same run happily. `test_publish_accepts_*` is the
CLEARS half and is meaningless on its own — before the guard existed it passed
vacuously, because there was nothing to clear. They are only a control
together, and they are written together here for that reason.

EVERY FIXTURE IS SYNTHESIZED. `procx` / `cellsA` / `widgetmul` are
placeholders; the revisions are arbitrary hex with no meaning. No process,
foundry, node, SKU, vendor or design identifier appears in this file. One test
is driven by a REAL in-repo artefact (`programs/pdk_registry.json`) — see
`test_no_string_in_the_real_registry_is_ever_accepted_as_a_revision`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
for _p in (str(_PROGRAMS), str(_HERE)):
    if _p not in sys.path:                          # pragma: no cover - path setup
        sys.path.insert(0, _p)

import _hostpaths                                   # noqa: E402
import _pdk_revision_fixture as _fix                # noqa: E402
import pdk_revision_resolve as prr                  # noqa: E402

PUBLISH = _PROGRAMS / "benchmark_evidence_publish.py"
RESOLVE = _PROGRAMS / "pdk_revision_resolve.py"

_REV_A = "aa11bb22cc33dd44ee55ff6677889900aabbccdd"
_REV_B = "0011223344556677889900aabbccddeeff001122"


@pytest.fixture
def log_safe_tmp(tmp_path):
    """A temp dir whose path can survive a round trip through a TEXT LOG.

    pytest roots `tmp_path` at `/tmp/pytest-of-$USER`, and the EDA image this
    repo pins reports `$USER` as `1000\ndesigner` — with a real newline in it
    (`getpass.getuser() -> '1000\ndesigner'`, measured in the container). A
    path containing a newline cannot be recovered from a tool log at all: the
    log line ends at the newline, so any reader gets a truncated path to a
    directory that does not exist. That is a property of the HOST, not of the
    code under test — the resolver refuses such a path rather than inventing a
    tree for it, which is the right answer — so the tests that route a path
    through a log use a clean root instead of asserting on the quirk.

    Tests that pass paths as ARGV are unaffected and keep using `tmp_path`.
    """
    if "\n" not in str(tmp_path):
        yield tmp_path
        return
    d = Path(tempfile.mkdtemp(prefix="w6pdk_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# The resolver reads the tree, never the request.
# ---------------------------------------------------------------------------

def _install(base: Path, revision: str, entry_name: str = "procx") -> Path:
    """A content-addressed install whose ENTRY NAME is chosen by the caller."""
    store = base / "pdkstore" / "versions" / revision / "procx"
    (store / "libs.ref" / "cellsA" / "lib").mkdir(parents=True, exist_ok=True)
    (store / "libs.ref" / "cellsA" / "lib" / "cellsA__tt.lib").write_text("//\n")
    entry = base / entry_name
    entry.symlink_to(Path("pdkstore") / "versions" / revision / "procx")
    return entry


def test_the_revision_is_read_from_the_resolved_tree_not_from_the_entry_name(
        tmp_path):
    """TRAP 1. The entry a caller names carries one token; the tree it resolves
    to carries another. A revision copied from the request would report the
    first — it is a record of what we asked for, not of what ran."""
    entry = _install(tmp_path, _REV_A, entry_name=f"procx_{_REV_B}")
    rec = prr.resolve_tree(prr.Fs(None), str(entry))

    assert rec["resolved"] is True, rec
    assert _REV_A in rec["revision"], rec
    assert _REV_B not in rec["revision"], (
        "the recorded revision came from the name the caller passed, not from "
        f"the tree that name resolves to: {rec}")
    assert rec["resolved_tree"] != str(entry), rec


def test_the_record_names_the_artefact_it_read_and_digests_it(tmp_path):
    """A revision nobody can trace back to a file is a claim, not a record."""
    tree = _fix.synth_pdk_tree(tmp_path)
    rec = prr.resolve_tree(prr.Fs(None), str(tree))

    by_source = {e["source"]: e for e in rec["sources"]}
    assert prr.SOURCES_FILE in by_source, rec
    entry = by_source[prr.SOURCES_FILE]
    assert Path(entry["read_from"]).is_file(), entry
    assert entry["sha256"].startswith("sha256:"), entry
    # and the anchor is over the tree that ran, with its own count
    anchor = rec["content_anchor"]
    assert anchor["sha256"].startswith("sha256:") and anchor["files"] >= 2, anchor
    assert anchor["truncated"] is False, anchor


# ---------------------------------------------------------------------------
# "Could not determine" FAILS. It is never written as a passing 'unknown'.
# ---------------------------------------------------------------------------

def test_a_tree_that_states_no_revision_is_not_determined_and_exits_1(tmp_path):
    """TRAP 2, at the resolver. Measured as a REAL state, not a hypothetical:
    a third of the PDK trees the pinned image ships declare no revision at all."""
    bare = tmp_path / "procx"
    (bare / "libs.ref").mkdir(parents=True)
    (bare / "libs.ref" / "x.lib").write_text("//\n")

    proc = subprocess.run(
        [sys.executable, str(RESOLVE), "--tree", str(bare),
         "--json", str(tmp_path / "rec.json")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "NOT DETERMINED" in (proc.stdout + proc.stderr)

    rec = json.loads((tmp_path / "rec.json").read_text())
    assert rec["resolved"] is False and rec["revision"] is None, rec
    assert rec.get("reason"), "a refusal that names no reason is not legible"
    # the one spelling that would re-create the gap while looking closed
    assert "unknown" not in json.dumps(rec.get("revision")), rec


@pytest.mark.parametrize("placeholder", ["unknown", "SRAM_BUILD_COMMIT", "",
                                         "none", "HEAD", "latest"])
def test_a_placeholder_is_not_a_revision_token(placeholder):
    """Not decorative: the shipped node-info of a real tree carries `unknown`
    for three components and the literal `SRAM_BUILD_COMMIT` for another, both
    sitting exactly where a revision goes."""
    assert prr.is_revision_token(placeholder) is False


def test_a_tree_whose_revision_file_holds_a_placeholder_is_not_determined(
        tmp_path):
    tree = tmp_path / "procx"
    tree.mkdir()
    (tree / "COMMIT").write_text("unknown\n")
    rec = prr.resolve_tree(prr.Fs(None), str(tree))
    assert rec["resolved"] is False, rec
    assert prr.COMMIT_FILE in {e["source"] for e in rec["sources"]}, (
        "the artefact is present and must be RECORDED as present-but-empty; "
        "'there is no such file' is a different fact about a tree")


def test_two_artefacts_disagreeing_is_ambiguous_and_fails(tmp_path):
    tree = tmp_path / "procx"
    (tree / ".config").mkdir(parents=True)
    (tree / "SOURCES").write_text(f"upstream_pdk {_REV_A}\n")
    (tree / ".config" / "nodeinfo.json").write_text(
        json.dumps({"commit": {"upstream_pdk": _REV_B}}))
    rec = prr.resolve_tree(prr.Fs(None), str(tree))
    assert rec["resolved"] is False, rec
    assert "AMBIGUOUS" in rec["reason"], rec


# ---------------------------------------------------------------------------
# The run-time capture: derived from the run's OWN tool logs.
# ---------------------------------------------------------------------------

def test_the_runner_derives_the_tree_from_the_libraries_the_run_loaded(
        log_safe_tmp):
    """`--from-run` reads the absolute library paths the tools themselves
    logged — what RAN, rather than what was configured."""
    tree = _fix.synth_pdk_tree(log_safe_tmp / "pdks")
    lib = (tree / "libs.ref" / "cellsA" / "lib" / "cellsA__tt.lib").resolve()

    run = log_safe_tmp / "run"
    (run / "phase3" / "reports").mkdir(parents=True)
    (run / "phase3" / "reports" / "pnr.log").write_text(
        f"[INFO] reading liberty {lib}\n[INFO] done\n")

    import vibe_ic_one_shot_runner as V
    rec = V._capture_pdk_revision(run, None)

    assert rec["resolved"] is True, rec
    assert _fix.FIXTURE_REVISION in rec["revision"], rec
    written = json.loads((run / prr.RECORD_REL).read_text())
    assert written["revision"] == rec["revision"]


def test_the_walk_up_lands_on_the_pdk_root_not_on_the_library_directory(
        log_safe_tmp):
    """REGRESSION. The first cut of the walk stopped at the first ancestor for
    which any source matched — and `TREE_PATH` matches on the PATH SHAPE, which
    every descendant of a content-addressed install shares. So it stopped at
    `<tree>/libs.ref/<lib>/lib`, recorded that as the PDK tree, and reported
    `resolved: true`. The revision was right by accident and the tree was
    wrong, which is worse than a refusal: a later reader would go looking for a
    PDK at a path that is a library folder."""
    tree = _fix.synth_pdk_tree(log_safe_tmp / "pdks")
    lib = (tree / "libs.ref" / "cellsA" / "lib" / "cellsA__tt.lib").resolve()
    run = log_safe_tmp / "run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "pnr.log").write_text(f"reading {lib}\n")

    trees, scanned = prr.candidate_trees_from_run(run, prr.Fs(None))
    assert scanned == 1 and len(trees) == 1, (scanned, trees)
    landed = Path(trees[0])
    assert (landed / "SOURCES").is_file(), (
        f"the walk landed on {landed}, which carries no declared-revision "
        f"artefact of its own — it is inside the tree, not the tree")
    assert landed.resolve() == tree.resolve(), (landed, tree)


def test_a_run_that_loaded_no_library_says_so_rather_than_going_silent(tmp_path):
    """§6 degrade loudly. A run with no physical implementation is in this
    state legitimately — and the record must SAY it, because at publish time
    the difference between 'no PDK' and 'nobody looked' is the whole point."""
    run = tmp_path / "run"
    (run / "reports").mkdir(parents=True)

    import vibe_ic_one_shot_runner as V
    rec = V._capture_pdk_revision(run, None)

    assert rec["resolved"] is False and rec["revision"] is None, rec
    assert "no PDK tree was derivable" in rec["reason"], rec
    assert (run / prr.RECORD_REL).is_file(), (
        "the record must exist even when it has nothing good to say; a missing "
        "file and a recorded absence are different states")


# ---------------------------------------------------------------------------
# THE GATE. BLOCKING, at publish. The control pair.
# ---------------------------------------------------------------------------

_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"


def _converged_run(base: Path) -> Path:
    run = base / "run"
    (run / "reports" / "audit").mkdir(parents=True)
    (run / "reports" / "audit" / "phase23_completion_audit.json").write_text(
        json.dumps({"verdict": "PASS_WITH_WAIVERS"}))
    (run / "RESULT.md").write_text(_RESULT_PASS)
    (run / "phase1" / "generated_docs").mkdir(parents=True)
    (run / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (run / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (run / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module top; endmodule\n")
    (run / "phase3" / "reports").mkdir(parents=True)
    (run / "phase3" / "reports" / "drc.rpt").write_text("clean\n")
    (run / "reports" / "phase3").mkdir(parents=True)
    (run / "reports" / "phase3" / "sta.json").write_text("{}")
    (run / "provenance.jsonl").write_text('{"tool":"yosys"}\n')
    (run / "input" / "docs").mkdir(parents=True)
    (run / "input" / "docs" / "L1.md").write_text("# spec\n")
    (run / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (run / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(b"GDS" * 64)
    return run


def _publish(run: Path, dest_root: Path):
    return subprocess.run(
        [sys.executable, str(PUBLISH), "--run-dir", str(run),
         "--ic", "widgetmul", "--pdk", "openpdkx",
         "--plugin-version", "9.9.9", "--dest-root", str(dest_root)],
        capture_output=True, text=True, timeout=180)


def test_publish_refuses_a_run_that_records_no_pdk_revision(tmp_path):
    """FIRES. Against the pre-change program this run publishes cleanly."""
    run = _converged_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    proc = _publish(run, dest_root)

    assert proc.returncode != 0, proc.stdout
    assert "REFUSED" in proc.stdout + proc.stderr
    assert "PDK revision" in proc.stdout + proc.stderr
    assert not dest_root.exists() or not any(dest_root.rglob("RESULT.md")), (
        "the guard refused and STAGED SOMETHING ANYWAY — a refusal that leaves "
        "a partial cell behind is worse than no guard")


def test_publish_refuses_a_record_that_says_unknown(tmp_path):
    """FIRES. TRAP 2 at the gate: there is no spelling of 'we could not tell'
    that satisfies it."""
    run = _converged_run(tmp_path)
    (run / prr.RECORD_REL).write_text(json.dumps(
        {"schema": 1, "resolved": True, "revision": "unknown",
         "trees": [{"tree": "/pdks/procx"}]}))
    proc = _publish(run, tmp_path / "benchmark-data")

    assert proc.returncode != 0, proc.stdout
    assert "is not a revision token" in proc.stdout + proc.stderr


def test_publish_refuses_a_record_whose_own_verdict_is_not_determined(tmp_path):
    """FIRES. The honest record is still not a licence to publish."""
    run = _converged_run(tmp_path)
    bare = tmp_path / "bare_pdk"
    bare.mkdir()
    rec = prr.build_record([prr.resolve_tree(prr.Fs(None), str(bare))],
                           "host", "test")
    (run / prr.RECORD_REL).write_text(json.dumps(rec))
    proc = _publish(run, tmp_path / "benchmark-data")

    assert proc.returncode != 0, proc.stdout
    assert "resolved is not true" in proc.stdout + proc.stderr


def test_publish_accepts_a_run_that_names_its_pdk_revision(tmp_path):
    """CLEARS — and is NOT a control on its own. Before the guard existed this
    passed vacuously; it is meaningful only paired with the three above."""
    run = _converged_run(tmp_path)
    _fix.write_run_pdk_revision(run)
    dest_root = tmp_path / "benchmark-data"
    proc = _publish(run, dest_root)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _fix.FIXTURE_REVISION in proc.stdout, (
        "the publish must PRINT what it signed off against; a record nobody "
        "sees is one nobody checks")


def test_the_published_cell_carries_the_revision_it_signed_off_against(tmp_path):
    """The point of the whole exercise: the CELL, on its own, is enough to
    re-derive the sign-off. A record that stays behind in the run directory
    closes nothing for a reader of `benchmark-data`."""
    run = _converged_run(tmp_path)
    _fix.write_run_pdk_revision(run)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0

    cell = dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    staged = cell / prr.RECORD_REL
    assert staged.is_file(), sorted(p.name for p in cell.rglob("*"))
    rec = json.loads(staged.read_text())
    assert prr.record_gaps(rec) == [], rec
    assert _fix.FIXTURE_REVISION in rec["revision"]


# ---------------------------------------------------------------------------
# Driven by a REAL in-repo artefact.
# ---------------------------------------------------------------------------

def test_no_string_in_the_real_registry_is_ever_accepted_as_a_revision():
    """TRAP 1, swept over the repository's OWN PDK registry.

    `pdk_registry.json` is the REQUEST side: names, container paths, cell
    names, deck paths. Not one of those strings may pass as a revision, or the
    resolver could record the thing that was asked for and look like it had
    recorded the thing that ran. Driven by the checked-in artefact rather than
    by a fixture, so it keeps biting as the registry grows.
    """
    reg_path = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "pdk_registry.json")
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    entries = reg.get("pdks") or []
    assert entries, f"{reg_path} declares no PDK entries — nothing was swept"

    accepted = []
    scanned = 0

    def sweep(node):
        nonlocal scanned
        if isinstance(node, str):
            scanned += 1
            if prr.is_revision_token(node):
                accepted.append(node)
            # a path's own segments are equally part of the request
            for seg in node.split("/"):
                if seg:
                    scanned += 1
                    if prr.is_revision_token(seg):
                        accepted.append(seg)
        elif isinstance(node, dict):
            for v in node.values():
                sweep(v)
        elif isinstance(node, list):
            for v in node:
                sweep(v)

    sweep(entries)
    assert scanned > 100, f"the sweep examined only {scanned} strings"
    assert accepted == [], (
        f"{len(accepted)} string(s) from the request side would be accepted as "
        f"a PDK revision: {accepted[:10]}")
