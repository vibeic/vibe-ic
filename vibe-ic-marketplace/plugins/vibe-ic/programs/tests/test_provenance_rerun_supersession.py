#!/usr/bin/env python3
"""An append-only provenance ledger must survive a re-run — and must still
catch an artefact whose bytes are not the bytes its producer recorded.

Two halves of one contract:

  * provenance_output_hash_completeness_check resolves each output path to
    its NEWEST record and verifies only that one against disk. An earlier
    record describes a state that no longer exists; it is DISCLOSED, not
    faulted.
  * phase3_one_shot_runner APPENDS a record when it re-emits an output. It
    never rewrites a historical record's declared hash.

Before, neither half held: the checker faulted every historical record
against the one current on-disk state, which made it unsatisfiable after
the first re-run, and the runner reconciled that by editing the ledger to
agree with the disk — which made tampering and a legitimate re-run
indistinguishable, both PASS.

The reverse cases below are the load-bearing ones. A change that made the
re-run case pass by weakening the on-disk verification would sail through
the forward tests and fail these: tampering, a newest record that
disagrees with disk, and tampering AFTER a legitimate re-run all still
FAIL.

chip-AGNOSTIC: plain text files under tmp_path. No design, no PDK, no
geometry, no tool invocation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
CHECK = PROGRAMS / "provenance_output_hash_completeness_check.py"
RUNNER = PROGRAMS / "phase3_one_shot_runner.py"


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _run(project: Path, *extra):
    return subprocess.run(
        [sys.executable, str(CHECK), str(project), *extra],
        capture_output=True, text=True)


def _record(rel: str, sha: str, tool: str = "demotool", ts: str = "") -> dict:
    return {
        "timestamp": ts or "2026-01-01T00:00:00Z",
        "tool": tool,
        "argv": [tool, "--out", rel],
        "outputs": {rel: sha},
    }


def _ledger(project: Path, *records: dict) -> None:
    (project / "provenance.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records))


def _artefact(project: Path, rel: str, text: str) -> Path:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ---------------------------------------------------------------------------
# FORWARD — these FAIL against the pre-fix checker and PASS after it.
# ---------------------------------------------------------------------------

def test_a_rerun_that_rewrites_an_output_in_place_is_not_a_fault(tmp_path):
    """The whole defect, minimally. A step ran, then ran again and rewrote
    its output. The bytes on disk are exactly what the newest record
    declares. Pre-fix this produced two faults on an honest ledger."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    first = _sha(art)
    art.write_text("second pass\n")
    _ledger(tmp_path, _record(rel, first), _record(rel, _sha(art)))

    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_many_reruns_of_the_same_path_stay_clean(tmp_path):
    """N re-runs produced 2N-1 guaranteed faults pre-fix (one MISMATCH per
    superseded record plus one INCONSISTENT per re-declaration)."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "pass 0\n")
    records = [_record(rel, _sha(art))]
    for n in range(1, 6):
        art.write_text(f"pass {n}\n")
        records.append(_record(rel, _sha(art)))
    _ledger(tmp_path, *records)

    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_rerun_by_a_different_tool_is_also_a_supersession(tmp_path):
    """Distinct producers legitimately rewrite the same report path across
    a flow. Ledger order decides, not tool identity."""
    rel = "reports/drc.rpt"
    art = _artefact(tmp_path, rel, "router view\n")
    first = _sha(art)
    art.write_text("signoff view\n")
    _ledger(tmp_path,
            _record(rel, first, tool="router"),
            _record(rel, _sha(art), tool="signoff"))

    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_supersession_is_disclosed_and_counted_never_silent(tmp_path):
    """Degrade loudly. A reader must be able to see that an earlier record
    was not verified, and why — otherwise PASS reads as "all of it"."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    first = _sha(art)
    art.write_text("second pass\n")
    _ledger(tmp_path, _record(rel, first), _record(rel, _sha(art)))

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr

    report = json.loads(out.read_text())
    rules = [f["rule"] for f in report["findings"]]
    assert "PROVENANCE_OUTPUT_SUPERSEDED" in rules
    superseded = [f for f in report["findings"]
                  if f["rule"] == "PROVENANCE_OUTPUT_SUPERSEDED"]
    assert all(f["severity"] == "DISCLOSED" for f in superseded)
    assert report["outcome_census"]["superseded"] == 1
    # and it reaches the human on the verdict line, not only the JSON
    assert "SUPERSEDED" in (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# REVERSE — these pass BOTH pre-fix and post-fix. They are what stops the
# forward fix from being "make the check stop looking".
# ---------------------------------------------------------------------------

def test_reverse_tampering_still_fails(tmp_path):
    """Nobody re-ran anything; the bytes were edited. The ledger's only
    record still declares the pre-tamper digest."""
    rel = "reports/signoff.rpt"
    art = _artefact(tmp_path, rel, "tally: {'PASS': 100, 'FAIL': 0}\n")
    _ledger(tmp_path, _record(rel, _sha(art)))
    art.write_text("tally: {'PASS': 104, 'FAIL': 0}\n")

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PROVENANCE_HASH_MISMATCH" in (r.stdout + r.stderr)


def test_reverse_tampering_AFTER_a_legitimate_rerun_still_fails(tmp_path):
    """The case supersession could have opened a hole for, and the reason
    this file exists. Two honest records, then the artefact is hand-edited.
    The NEWEST record is now the one that disagrees with disk."""
    rel = "reports/signoff.rpt"
    art = _artefact(tmp_path, rel, "tally: {'PASS': 100, 'FAIL': 4}\n")
    first = _sha(art)
    art.write_text("tally: {'PASS': 101, 'FAIL': 3}\n")
    _ledger(tmp_path, _record(rel, first), _record(rel, _sha(art)))
    # ... and now somebody edits the artefact without producing a record.
    art.write_text("tally: {'PASS': 104, 'FAIL': 0}\n")

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PROVENANCE_HASH_MISMATCH" in (r.stdout + r.stderr)


def test_reverse_newest_record_disagreeing_with_disk_still_fails(tmp_path):
    """A superseded record must not be able to vouch for the path. Here the
    OLDEST record happens to match the bytes on disk and the newest does
    not; that is still a broken chain."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "the bytes on disk\n")
    on_disk = _sha(art)
    stale = "sha256:" + "0" * 64
    _ledger(tmp_path, _record(rel, on_disk), _record(rel, stale))

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PROVENANCE_HASH_MISMATCH" in (r.stdout + r.stderr)


def test_reverse_declared_output_that_does_not_exist_still_fails(tmp_path):
    rel = "reports/never_written.rpt"
    (tmp_path / "reports").mkdir(parents=True)
    _ledger(tmp_path, _record(rel, "sha256:" + "a" * 64))

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def test_reverse_an_honest_single_record_ledger_passes(tmp_path):
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "only ever produced once\n")
    _ledger(tmp_path, _record(rel, _sha(art)))

    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_reverse_a_malformed_digest_still_fails(tmp_path):
    rel = "reports/out.rpt"
    _artefact(tmp_path, rel, "x\n")
    _ledger(tmp_path, _record(rel, "not-a-digest"))

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PROVENANCE_HASH_SHAPE_INVALID" in (r.stdout + r.stderr)


def test_reverse_supersession_does_not_excuse_a_vanished_output(tmp_path):
    """Two records, newest declares a path that is no longer on disk. The
    supersession rule must not swallow the absence."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first\n")
    first = _sha(art)
    art.write_text("second\n")
    _ledger(tmp_path, _record(rel, first), _record(rel, _sha(art)))
    art.unlink()

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# The runner half — a re-emit APPENDS; it never amends history.
# ---------------------------------------------------------------------------

_PLUGIN = PROGRAMS.parent
for _p in (str(PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase3_one_shot_runner as _runner                     # noqa: E402


def _load_runner():
    return _runner


def test_runner_reemit_appends_and_leaves_history_byte_intact(tmp_path):
    """`_restamp_provenance_output` used to rewrite every record declaring
    the path. The historical line must now come back byte-identical."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    original_line = json.dumps(_record(rel, _sha(art)))
    (tmp_path / "provenance.jsonl").write_text(original_line + "\n")

    art.write_text("second pass\n")
    mod._restamp_provenance_output(
        tmp_path, rel, art, "demotool", "demotool --out")

    lines = [l for l in (tmp_path / "provenance.jsonl")
             .read_text().splitlines() if l.strip()]
    assert lines[0] == original_line, "history was amended"
    assert len(lines) == 2, "no superseding record was appended"
    assert json.loads(lines[1])["outputs"][rel] == _sha(art)
    # and the ledger it produced is one the checker accepts
    assert _run(tmp_path).returncode == 0


def test_runner_reemit_is_a_noop_when_the_bytes_did_not_change(tmp_path):
    """Reverse case: an unchanged output must not grow the ledger on every
    pass. A guard that always appends is as wrong as one that always
    rewrites."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "stable\n")
    before = json.dumps(_record(rel, _sha(art))) + "\n"
    (tmp_path / "provenance.jsonl").write_text(before)

    mod._restamp_provenance_output(
        tmp_path, rel, art, "demotool", "demotool --out")

    assert (tmp_path / "provenance.jsonl").read_text() == before


def test_runner_still_declares_a_path_the_ledger_never_had(tmp_path):
    """Reverse case: the pre-existing 'no prior entry declares it' branch
    is unchanged."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "brand new\n")
    other = json.dumps(_record("reports/other.rpt", "sha256:" + "b" * 64))
    (tmp_path / "provenance.jsonl").write_text(other + "\n")

    mod._restamp_provenance_output(
        tmp_path, rel, art, "demotool", "demotool --out")

    lines = [l for l in (tmp_path / "provenance.jsonl")
             .read_text().splitlines() if l.strip()]
    assert lines[0] == other, "history was amended"
    assert len(lines) == 2
    rec = json.loads(lines[1])
    assert rec["outputs"][rel] == _sha(art)
    assert rec["reconstructed"] is True


def test_runner_source_carries_no_whole_ledger_rewrite(tmp_path):
    """The amendment operation is 'read the whole ledger, edit records,
    write it back'. Assert the shape is gone from the source, so a future
    edit cannot quietly reintroduce it at a third site."""
    src = RUNNER.read_text()
    for shape in ("prov_path.write_text(", "prov_path_s.write_text("):
        assert shape not in src, (
            f"{shape} rewrites provenance.jsonl wholesale; a re-emit must "
            f"append a superseding record instead of amending history")
