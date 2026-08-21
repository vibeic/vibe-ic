"""Bidirectional test — canonical GDS provenance re-stamp ordering fix.

The defect
----------
In `step_canonicalize_artefacts`, the in-place provenance refresh loop (and
the `_v1_6_620_append_pv_signoff_provenance` call) ran BEFORE the Step 37
GDS canonical-alias copy.  When `phase3/stage4/gds/<top>.gds` did not yet
exist on disk, neither the refresh loop nor the append helper could stamp the
correct hash — the loop skips files that don't exist, the append helper also
skips non-existent files.  Step 37 then created the file, but with no
provenance entry carrying its actual hash.  If a STALE entry already existed
(from a prior run), it held the wrong hash; if no entry existed at all, the
gate found the output undeclared.  Either way,
`provenance_output_hash_completeness_check` FAILed with
PROVENANCE_HASH_MISMATCH or PROVENANCE_OUTPUT_FILE_MISSING.

The fix
-------
`_step37_restamp_canon_gds_provenance(project, top, canon_gds)` is called
immediately after the Step 37 binary copy.  It patches any existing provenance
entry that declared `phase3/stage4/gds/<top>.gds` in-place to the
freshly-computed hash; if no entry exists it appends a new one.

Constraint (from reading the gate): appending a SECOND entry with a different
hash would trade HASH_MISMATCH for HASH_INCONSISTENT; hence the fix updates
IN PLACE.

Test structure
--------------
(a) DEFECT direction — simulate the pre-fix ordering: perform the Step 37 copy
    WITHOUT calling the re-stamp helper, then run the gate.  Assert FAIL with
    PROVENANCE_HASH_MISMATCH.  This direction FAILS when the fix is absent.
(b) FIXED direction — same project, call the real helper
    `_step37_restamp_canon_gds_provenance` from phase3_one_shot_runner, then
    run the gate.  Assert PASS and no HASH_INCONSISTENT.

Mutations target the real module helper so that source mutations kill the tests.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
for _p in (str(_PROGRAMS), str(_PROGRAMS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase3_one_shot_runner as _runner           # noqa: E402
from provenance_output_hash_completeness_check import audit  # noqa: E402

# Grab the helper we are testing from the actual source module.
_restamp = _runner._step37_restamp_canon_gds_provenance


# ── helpers ──────────────────────────────────────────────────────────────────

def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _make_stale_project(tmp_path: Path, top: str = "chip_top") -> Path:
    """Build a temp project with:
      * phase3/stage3/pnr/<top>.gds   — primary GDS (NEW content)
      * phase3/stage4/gds/            — exists but <top>.gds absent
      * provenance.jsonl              — stale entry for stage4 GDS with WRONG hash

    Faithfully recreates the pre-copy state: the canonical GDS does not exist
    on disk but provenance carries a wrong hash (e.g. from a prior run that
    created then deleted the file).
    """
    project = tmp_path / "proj"

    pnr_dir = project / "phase3" / "stage3" / "pnr"
    pnr_dir.mkdir(parents=True)
    primary_content = b"\x00\x06\x00\x02GDS_NEW_CONTENT" + b"\xab" * 256
    (pnr_dir / f"{top}.gds").write_bytes(primary_content)

    gds_out = project / "phase3" / "stage4" / "gds"
    gds_out.mkdir(parents=True)

    # stale provenance entry: declares a WRONG (old) hash for the canonical GDS
    old_hash = "sha256:" + "d" * 64   # clearly wrong
    prov = {
        "tool": "klayout",
        "command": "klayout streamout (canonical GDS) (phase3_one_shot_runner step37)",
        "exit_code": 0,
        "duration_ms": 0,
        "timestamp": "2026-01-01T00:00:17Z",
        "outputs": {f"phase3/stage4/gds/{top}.gds": old_hash},
    }
    (project / "provenance.jsonl").write_text(json.dumps(prov) + "\n")
    return project


def _canon_gds_rel(top: str) -> str:
    return f"phase3/stage4/gds/{top}.gds"


def _step37_copy_only(project: Path, top: str) -> None:
    """Simulate the PRE-FIX Step 37: binary copy WITHOUT re-stamping provenance."""
    primary_gds = project / "phase3" / "stage3" / "pnr" / f"{top}.gds"
    canon_gds = project / "phase3" / "stage4" / "gds" / f"{top}.gds"
    if primary_gds.is_file() and not canon_gds.is_file():
        with primary_gds.open("rb") as src, canon_gds.open("wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
    # deliberately does NOT call _restamp (the defect)


def _step37_fixed(project: Path, top: str) -> None:
    """The FIXED Step 37: binary copy + call to the real module re-stamp helper."""
    primary_gds = project / "phase3" / "stage3" / "pnr" / f"{top}.gds"
    canon_gds = project / "phase3" / "stage4" / "gds" / f"{top}.gds"
    if primary_gds.is_file() and not canon_gds.is_file():
        with primary_gds.open("rb") as src, canon_gds.open("wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
        # call the REAL helper from phase3_one_shot_runner — mutations here kill
        _restamp(project, top, canon_gds)


# ── (a) DEFECT DIRECTION ──────────────────────────────────────────────────────

def test_defect_direction_hash_mismatch_without_restamp(tmp_path: Path) -> None:
    """PRE-FIX: copy without re-stamp → stale hash → gate FAIL HASH_MISMATCH.

    This test FAILS (correctly) when the re-stamp logic is absent.
    """
    project = _make_stale_project(tmp_path)
    top = "chip_top"

    _step37_copy_only(project, top)

    canon_gds = project / _canon_gds_rel(top)
    assert canon_gds.is_file(), "Step 37 copy must create the file"

    actual_sha = _sha(canon_gds.read_bytes())
    prov_text = (project / "provenance.jsonl").read_text()
    # confirm provenance still carries the stale hash (not the real one)
    assert actual_sha not in prov_text, (
        "Defect scenario: provenance must NOT contain the correct hash yet — "
        "this assertion verifies the fixture represents the real defect")

    verdict, findings = audit(project)
    mismatch = [f for f in findings if f.rule == "PROVENANCE_HASH_MISMATCH"]
    assert verdict == "FAIL", (
        f"gate must FAIL without re-stamp (got {verdict!r}); "
        f"findings: {[(f.rule, f.detail) for f in findings]}")
    assert mismatch, (
        "gate must produce PROVENANCE_HASH_MISMATCH without re-stamp; "
        f"findings: {[(f.rule, f.detail) for f in findings]}")


def test_appending_the_correct_hash_is_now_the_valid_fix(tmp_path: Path) -> None:
    """Appending a record that declares the digest the file ACTUALLY carries
    is the correct way to record a re-emit, and the gate accepts it.

    This test previously asserted the opposite — that appending merely traded
    HASH_MISMATCH for HASH_INCONSISTENT, "proving append-only is not a valid
    fix". That was true of the old checker, and it is why every producer in
    this runner patched provenance IN PLACE instead. Patching in place is what
    made a hand-edited artefact indistinguishable from a re-run one: any
    disagreement between ledger and disk was resolved by amending the ledger.
    The checker now resolves a path to its NEWEST record, so an append is both
    honest and sufficient.

    The second half below is the load-bearing part: appending a record whose
    digest does NOT match disk must still FAIL, so this is not "append makes
    everything pass"."""
    project = _make_stale_project(tmp_path, top="widget")
    top = "widget"

    _step37_copy_only(project, top)
    canon_gds = project / _canon_gds_rel(top)
    correct_sha = _sha(canon_gds.read_bytes())

    def _append(sha_value: str) -> None:
        with (project / "provenance.jsonl").open("a") as f:
            f.write(json.dumps({
                "tool": "klayout",
                "command": "re-emit",
                "exit_code": 0,
                "duration_ms": 0,
                "timestamp": "2026-01-01T00:01:17Z",
                "outputs": {_canon_gds_rel(top): sha_value},
            }) + "\n")

    # Append the digest the shipped file ACTUALLY carries.
    _append(correct_sha)
    verdict, findings = audit(project)
    assert verdict == "PASS", (
        "appending the real digest of the shipped bytes must be accepted; "
        f"findings: {[(f.rule, f.detail) for f in findings]}")
    assert [f for f in findings
            if f.rule == "PROVENANCE_OUTPUT_SUPERSEDED"], (
        "the earlier record must be reported as superseded, not dropped in "
        f"silence; findings: {[(f.rule, f.detail) for f in findings]}")

    # ...and the reverse: appending a digest the file does NOT carry must
    # still FAIL. Supersession must not become a way to declare anything.
    _append("sha256:" + "f" * 64)
    verdict, findings = audit(project)
    assert verdict == "FAIL", "a newest record that disagrees with disk must FAIL"
    assert [f for f in findings if f.rule == "PROVENANCE_HASH_MISMATCH"], (
        f"findings: {[(f.rule, f.detail) for f in findings]}")


# ── (b) FIXED DIRECTION ───────────────────────────────────────────────────────

def test_fixed_direction_gate_passes_after_restamp(tmp_path: Path) -> None:
    """FIXED: copy + in-place re-stamp → gate PASS, no HASH_MISMATCH, no
    HASH_INCONSISTENT."""
    project = _make_stale_project(tmp_path)
    top = "chip_top"

    _step37_fixed(project, top)

    canon_gds = project / _canon_gds_rel(top)
    assert canon_gds.is_file(), "Step 37 must create the canonical GDS"

    verdict, findings = audit(project)

    mismatch = [f for f in findings if f.rule == "PROVENANCE_HASH_MISMATCH"]
    assert not mismatch, (
        f"HASH_MISMATCH must be absent after fix; "
        f"findings: {[(f.rule, f.detail) for f in findings]}")

    inconsistent = [f for f in findings if f.rule == "PROVENANCE_HASH_INCONSISTENT"]
    assert not inconsistent, (
        f"HASH_INCONSISTENT must be absent (in-place patch, not append); "
        f"findings: {[(f.rule, f.detail) for f in findings]}")

    assert verdict == "PASS", (
        f"gate must PASS after fix (got {verdict!r}); "
        f"findings: {[(f.rule, f.detail) for f in findings]}")


def test_fixed_direction_no_prior_entry_appends_correctly(tmp_path: Path) -> None:
    """FIXED: when no prior entry exists for the canonical GDS, the fix appends
    a fresh correct entry and the gate passes."""
    project = tmp_path / "proj"
    top = "chip_top"

    pnr_dir = project / "phase3" / "stage3" / "pnr"
    pnr_dir.mkdir(parents=True)
    primary_content = b"\x00\x06\x00\x02GDS_FRESH" + b"\xcd" * 128
    (pnr_dir / f"{top}.gds").write_bytes(primary_content)
    (project / "phase3" / "stage4" / "gds").mkdir(parents=True)

    # provenance has only a routed.def entry (no stage4/gds entry)
    routed_bytes = b"DEF content"
    (pnr_dir / "routed.def").write_bytes(routed_bytes)
    prov_entry = {
        "tool": "openroad",
        "exit_code": 0,
        "timestamp": "2026-01-01T00:00:17Z",
        "outputs": {
            "phase3/stage3/pnr/routed.def": _sha(routed_bytes),
        },
    }
    (project / "provenance.jsonl").write_text(json.dumps(prov_entry) + "\n")

    _step37_fixed(project, top)

    # The fix MUST have appended an entry for the canonical GDS path.
    # Without this assertion Mutation 2 (disabled append) would survive.
    canon_rel = _canon_gds_rel(top)
    prov_text = (project / "provenance.jsonl").read_text()
    assert canon_rel in prov_text, (
        f"fix must append an entry for {canon_rel!r} when none exists; "
        f"provenance content: {prov_text!r}")

    # The declared hash must match the actual file.
    canon_gds = project / canon_rel
    expected_sha = _sha(canon_gds.read_bytes())
    assert expected_sha in prov_text, (
        f"appended entry must contain the correct hash {expected_sha!r}; "
        f"provenance content: {prov_text!r}")

    verdict, findings = audit(project)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert verdict == "PASS", (
        f"gate must PASS when fix appends fresh entry; "
        f"errors: {[(f.rule, f.detail) for f in errors]}")


def test_fixed_direction_idempotent_second_call(tmp_path: Path) -> None:
    """FIXED: running the fixed Step 37 a second time is a no-op (canon_gds
    already exists → copy branch skipped → restamp not called again).

    The project starts with a STALE declaration, so the first call supersedes
    it with one appended record: two occurrences, one of them history. The
    second call must add nothing — a producer that appends on every pass would
    grow the ledger without bound and is as wrong as one that amends it."""
    project = _make_stale_project(tmp_path)
    top = "chip_top"

    _step37_fixed(project, top)   # first call: copy + restamp
    after_first = (project / "provenance.jsonl").read_text()
    _step37_fixed(project, top)   # second call: canon_gds exists → skip
    after_second = (project / "provenance.jsonl").read_text()

    assert after_second == after_first, (
        "the second call must not touch provenance at all")
    count = after_second.count(_canon_gds_rel(top))
    assert count == 2, (
        f"expected the superseded declaration plus the current one; "
        f"got {count} occurrences")

    verdict, findings = audit(project)
    assert not [f for f in findings if f.severity == "ERROR"], findings
    assert verdict == "PASS"


# ── RE-RUN / STALE-REFRESH — the shape that actually fires on main ───────────
#
# The helpers above simulate Step 37's "copy only when ABSENT" form. Today's
# runner ALSO refreshes the alias when the stream-out is newer
# (`_canonical_gds_is_stale`), which is exactly the re-run case that puts a
# PREVIOUS design's hash in provenance against THIS design's bytes. These two
# tests drive the runner's OWN helpers end-to-end — the declaration comes from
# `_v1_6_620_append_pv_signoff_provenance`, the staleness decision from
# `_canonical_gds_is_stale` — so nothing about the defect is assumed.


def _rerun_project(tmp_path: Path, top: str = "chip_top") -> tuple:
    """Run N-1 leaves a declared, hash-consistent stage4 alias; run N streams a
    DIFFERENT layout to phase3/stage3/pnr/<top>.gds."""
    import os
    import time as _t
    project = tmp_path / "proj"
    pnr = project / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    gds_out = project / "phase3" / "stage4" / "gds"
    gds_out.mkdir(parents=True)
    prev = b"\x00\x06\x00\x02PREVIOUS-DESIGN" + b"\x11" * 200
    (pnr / f"{top}.gds").write_bytes(prev)
    (gds_out / f"{top}.gds").write_bytes(prev)
    (project / "provenance.jsonl").write_text("")
    declared = _runner._v1_6_620_append_pv_signoff_provenance(project, top)
    assert f"phase3/stage4/gds/{top}.gds" in declared, declared
    assert audit(project)[0] == "PASS", "run N-1 must start hash-consistent"

    _t.sleep(0.02)
    (pnr / f"{top}.gds").write_bytes(b"\x00\x06\x00\x02THIS-DESIGN"
                                     + b"\x22" * 400)
    os.utime(pnr / f"{top}.gds", None)
    # The in-place refresh loop of step_canonicalize_artefacts runs HERE, before
    # Step 37. It re-hashes whatever is on disk AT THAT MOMENT: the stream-out
    # (correctly, to this design) and the stage4 alias (still the PREVIOUS
    # bytes). That is the whole point — it cannot describe a file Step 37 has
    # not written yet.
    _inplace_refresh_loop(project)
    _runner._v1_6_620_append_pv_signoff_provenance(project, top)  # idempotent
    return project, pnr / f"{top}.gds", gds_out / f"{top}.gds"


def _inplace_refresh_loop(project: Path) -> None:
    """step_canonicalize_artefacts' provenance refresh, verbatim in effect:
    every DECLARED output that still exists on disk gets its hash re-stamped."""
    prov = project / "provenance.jsonl"
    lines = prov.read_text().splitlines()
    out = []
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            continue
        rec = json.loads(ln)
        outs = rec.get("outputs", {})
        if isinstance(outs, dict):
            for rel in list(outs):
                fp = project / rel
                if fp.is_file():
                    outs[rel] = _sha(fp.read_bytes())
        out.append(json.dumps(rec))
    prov.write_text("\n".join(out) + "\n")


def _real_step37_copy(primary_gds: Path, canon_gds: Path) -> bool:
    """Step 37 verbatim, minus the re-stamp: refresh when ABSENT or STALE."""
    stale = _runner._canonical_gds_is_stale(primary_gds, canon_gds)
    if not canon_gds.is_file() or stale:
        with primary_gds.open("rb") as src, canon_gds.open("wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
    return stale


def test_defect_direction_rerun_stale_refresh_leaves_a_wrong_hash(
        tmp_path: Path) -> None:
    """PRE-FIX, the shape that fires on a real re-run: Step 37 refreshes the
    stale alias, and provenance still declares the PREVIOUS design's hash."""
    project, primary, canon = _rerun_project(tmp_path)
    assert _real_step37_copy(primary, canon) is True, (
        "premise: the alias must be judged STALE, else this is not a re-run")

    verdict, findings = audit(project)
    mismatch = [f for f in findings if f.rule == "PROVENANCE_HASH_MISMATCH"]
    assert verdict == "FAIL" and mismatch, (
        "a re-run that refreshed the shipped GDS must be caught declaring the "
        f"previous design's hash; findings: "
        f"{[(f.rule, f.detail) for f in findings]}")


def test_fixed_direction_rerun_stale_refresh_is_restamped(
        tmp_path: Path) -> None:
    """FIXED: the same re-run, with the re-stamp called right after the copy —
    the NEWEST declared hash follows the bytes that were actually shipped, and
    the previous round's declaration survives as history rather than being
    overwritten by it."""
    project, primary, canon = _rerun_project(tmp_path)
    before = (project / "provenance.jsonl").read_text().splitlines()
    _real_step37_copy(primary, canon)
    _restamp(project, "chip_top", canon)

    prov_lines = [l for l in (project / "provenance.jsonl")
                  .read_text().splitlines() if l.strip()]
    assert prov_lines[:len(before)] == before, (
        "the re-stamp must not amend the records already in the ledger")
    declared = [json.loads(l)["outputs"][_canon_gds_rel("chip_top")]
                for l in prov_lines
                if _canon_gds_rel("chip_top") in json.loads(l).get("outputs", {})]
    assert declared[-1] == _sha(canon.read_bytes()), (
        "the NEWEST declaration must carry the digest of the shipped bytes")

    verdict, findings = audit(project)
    assert verdict == "PASS", (
        f"gate must PASS after the re-stamp; "
        f"findings: {[(f.rule, f.detail) for f in findings]}")


def test_the_restamp_is_actually_wired_into_step_canonicalize_artefacts():
    """Every behavioural test above drives the helper DIRECTLY, so all of them
    pass even if the runner never calls it — the wiring is what ships. Walk the
    runner's AST and require the call inside `step_canonicalize_artefacts`."""
    import ast
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef)
               and n.name == "step_canonicalize_artefacts"), None)
    assert fn is not None, (
        "premise: the canonicalisation step was renamed — this test scans "
        "nothing")
    called = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_step37_restamp_canon_gds_provenance"
        for n in ast.walk(fn))
    assert called, (
        "Step 37 writes phase3/stage4/gds/<top>.gds AFTER both provenance "
        "writers have run; without the re-stamp call the shipped deliverable "
        "carries the previous design's declared hash")
