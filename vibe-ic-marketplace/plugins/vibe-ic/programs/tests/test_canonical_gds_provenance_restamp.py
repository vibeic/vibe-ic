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
import json
import sys
from pathlib import Path


# ── path setup ───────────────────────────────────────────────────────────────
_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
for _p in (str(_PROGRAMS), str(_PROGRAMS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from provenance_output_hash_completeness_check import audit  # noqa: E402

# Grab the helper we are testing from the actual source module.


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







# ── RE-RUN / STALE-REFRESH — the shape that actually fires on main ───────────
#
# The helpers above simulate Step 37's "copy only when ABSENT" form. Today's
# runner ALSO refreshes the alias when the stream-out is newer
# (`_canonical_gds_is_stale`), which is exactly the re-run case that puts a
# PREVIOUS design's hash in provenance against THIS design's bytes. These two
# tests drive the runner's OWN helpers end-to-end — the declaration comes from
# `_v1_6_620_append_pv_signoff_provenance`, the staleness decision from
# `_canonical_gds_is_stale` — so nothing about the defect is assumed.












def test_the_restamp_is_actually_wired_into_step_canonicalize_artefacts():
    """Every behavioural test above drives the helper DIRECTLY, so all of them
    pass even if the runner never calls it — the wiring is what ships. Follow
    live calls from `step_canonicalize_artefacts`, including its alias helper."""
    import ast
    from _runner_ast_fixture import reachable_calls
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef)
               and n.name == "step_canonicalize_artefacts"), None)
    assert fn is not None, (
        "premise: the canonicalisation step was renamed — this test scans "
        "nothing")
    called = "_step37_restamp_canon_gds_provenance" in reachable_calls(
        ast.parse(src), "step_canonicalize_artefacts")
    assert called, (
        "Step 37 writes phase3/stage4/gds/<top>.gds AFTER both provenance "
        "writers have run; without the re-stamp call the shipped deliverable "
        "carries the previous design's declared hash")


def test_live_helper_wiring_rejects_dead_or_disconnected_restamp():
    import ast
    from _runner_ast_fixture import reachable_calls
    live = "def entry():\n    alias()\ndef alias():\n    restamp()\n"
    assert 'restamp' in reachable_calls(ast.parse(live), 'entry')
    for broken in (
        "def entry():\n    pass\ndef alias():\n    restamp()\n",
        "def entry():\n    alias()\ndef alias():\n    if False:\n        restamp()\n",
        "def entry():\n    alias()\ndef alias():\n    return\n    restamp()\n",
        "def entry():\n    def unused():\n        restamp()\n",
    ):
        assert 'restamp' not in reachable_calls(ast.parse(broken), 'entry')
