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


# ---------------------------------------------------------------------------
# APPEND-ONLY, ASSERTED AS A BEHAVIOUR.
#
# The guard that used to live here read the runner's SOURCE for the strings
# `prov_path.write_text(` / `prov_path_s.write_text(`. It was a string used as
# a proxy for a behaviour and it did exactly what that always does: a
# concurrent change spelling the identical read-edit-write-back shape as
# `prov.write_text(` sailed straight through it. Measured on that branch —
# grep guard green, ledger amended, an earlier row's `outputs` emptied.
#
# So assert the property instead: after a re-emit, the bytes that WERE in the
# ledger are still a PREFIX of the bytes in the ledger. That is what
# append-only means, it holds no matter what the variable is called, and it
# fails on every amendment shape — an edited digest, a popped key, even a
# re-serialisation that only reorders whitespace.
# ---------------------------------------------------------------------------

def _heterogeneous_ledger(project: Path) -> bytes:
    """A ledger a whole-file rewrite cannot survive intact: two records for
    other paths, a blank line, a line that is not JSON at all, and
    hand-spaced JSON no `json.dumps` round-trip reproduces."""
    raw = (
        json.dumps(_record("reports/other_a.rpt", "sha256:" + "a" * 64)) + "\n"
        + '{"tool": "handwritten",  "outputs" : {"reports/other_b.rpt": '
          '"sha256:' + "b" * 64 + '"}}\n'
        + "\n"
        + "# not json at all — a reader must keep it verbatim\n"
    ).encode()
    (project / "provenance.jsonl").write_bytes(raw)
    return raw


def _drive_reemit_twice(mod, project: Path, rel: str, art: Path):
    """Two re-emits of the same path, the second after the bytes change
    again — i.e. drive the runner twice."""
    art.write_text("second pass\n")
    mod._restamp_provenance_output(project, rel, art, "demotool", "demotool -o")
    art.write_text("third pass\n")
    mod._restamp_provenance_output(project, rel, art, "demotool", "demotool -o")


def test_runner_reemit_twice_grows_the_ledger_and_never_rewrites_it(tmp_path):
    """FORWARD. Drive the re-emit path twice; the ledger must GROW and the
    bytes that were there must come back untouched, byte for byte."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    _heterogeneous_ledger(tmp_path)
    prov = tmp_path / "provenance.jsonl"
    with prov.open("ab") as f:
        f.write((json.dumps(_record(rel, _sha(art))) + "\n").encode())
    before = prov.read_bytes()
    n_before = len([l for l in before.decode().splitlines() if l.strip()])

    _drive_reemit_twice(mod, tmp_path, rel, art)

    after = prov.read_bytes()
    assert after.startswith(before), (
        "the ledger was REWRITTEN, not appended to: the bytes that were "
        "there are no longer a prefix of the bytes that are there")
    n_after = len([l for l in after.decode().splitlines() if l.strip()])
    assert n_after == n_before + 2, (
        f"two re-emits must add two records; {n_before} -> {n_after}")
    assert json.loads(after.decode().splitlines()[-1])["outputs"][rel] \
        == _sha(art)


def test_runner_reemit_leaves_records_of_other_paths_byte_identical(tmp_path):
    """FORWARD, narrower. The #826 amendment shape edits an unrelated row's
    `outputs` in passing; a prefix assertion catches it, and so does this."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    _heterogeneous_ledger(tmp_path)
    prov = tmp_path / "provenance.jsonl"
    with prov.open("ab") as f:
        f.write((json.dumps(_record(rel, _sha(art))) + "\n").encode())
    before_lines = prov.read_text().splitlines()

    _drive_reemit_twice(mod, tmp_path, rel, art)

    after_lines = prov.read_text().splitlines()
    assert after_lines[:len(before_lines)] == before_lines, (
        "a pre-existing line changed; every historical line must survive "
        "verbatim, including the unparseable one and the blank one")


def test_reverse_the_prefix_guard_goes_red_on_a_whole_ledger_rewrite(tmp_path):
    """REVERSE — the control that makes the two tests above mean something.

    Perform the deliberate amendment the guard exists to forbid: read the
    whole ledger, edit the historical record's declared digest to agree with
    disk, write it back. If the prefix assertion cannot see THAT, it cannot
    see anything."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    _heterogeneous_ledger(tmp_path)
    prov = tmp_path / "provenance.jsonl"
    with prov.open("ab") as f:
        f.write((json.dumps(_record(rel, _sha(art))) + "\n").encode())
    before = prov.read_bytes()
    art.write_text("second pass\n")

    # the forbidden shape, spelled with a THIRD variable name so that no
    # source-level grep for `prov_path.write_text(` would notice it
    ledger = prov
    rewritten = []
    for line in ledger.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            rewritten.append(line)
            continue
        outs = rec.get("outputs")
        if isinstance(outs, dict) and rel in outs:
            outs[rel] = _sha(art)
        rewritten.append(json.dumps(rec))
    ledger.write_text("\n".join(rewritten) + "\n")

    after = prov.read_bytes()
    assert not after.startswith(before), (
        "the prefix guard did not notice a whole-ledger rewrite — it is "
        "not measuring append-only at all")
    # the amendment really did land — otherwise the assertion above could
    # have gone red for some unrelated reason
    assert json.loads(after.decode().splitlines()[-1])["outputs"][rel] \
        == _sha(art)


def test_reverse_an_untouched_ledger_is_its_own_prefix(tmp_path):
    """REVERSE. The prefix assertion must not be trivially true only
    because something always appends: with nothing to re-emit, the ledger
    is unchanged and still passes."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "stable\n")
    _heterogeneous_ledger(tmp_path)
    prov = tmp_path / "provenance.jsonl"
    with prov.open("ab") as f:
        f.write((json.dumps(_record(rel, _sha(art))) + "\n").encode())
    before = prov.read_bytes()

    mod._restamp_provenance_output(
        tmp_path, rel, art, "demotool", "demotool -o")

    after = prov.read_bytes()
    assert after == before, "an unchanged output must not grow the ledger"
    assert after.startswith(before)


# The SECOND re-emit site. It used to be inline in
# `step_canonicalize_artefacts` — undrivable, which is the whole reason its
# guard was a grep. It is a named helper now, so the same property is
# asserted on it directly instead of inferred from a string.

def test_canonicalize_reemit_helper_appends_and_keeps_history_verbatim(
        tmp_path):
    """FORWARD."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    _heterogeneous_ledger(tmp_path)
    prov = tmp_path / "provenance.jsonl"
    with prov.open("ab") as f:
        f.write((json.dumps(_record(rel, _sha(art))) + "\n").encode())
    before = prov.read_bytes()
    art.write_text("second pass\n")

    assert mod._record_reemitted_outputs(tmp_path) is None

    after = prov.read_bytes()
    assert after.startswith(before), "history was amended, not appended to"
    rec = json.loads(after.decode().splitlines()[-1])
    assert rec["outputs"][rel] == _sha(art)
    assert rec["reconstructed"] is True


def test_canonicalize_reemit_produces_a_ledger_the_checker_accepts(tmp_path):
    """FORWARD. The append is not merely well-shaped; it is the record that
    makes the drifted path verify again."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first pass\n")
    _ledger(tmp_path, _record(rel, _sha(art)))
    art.write_text("second pass\n")
    assert _run(tmp_path).returncode == 1        # drifted: FAIL before

    assert mod._record_reemitted_outputs(tmp_path) is None

    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 SUPERSEDED" in (r.stdout + r.stderr)


def test_reverse_canonicalize_reemit_does_not_launder_a_failed_rows_digest(
        tmp_path):
    """REVERSE. A failed invocation's observation must not count as 'the
    newest record', or this helper would append a re-emit for drift that
    never happened — and would disagree with the checker."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "produced\n")
    _ledger(tmp_path,
            _invocation(rel, _sha(art), 0),
            _invocation(rel, "sha256:" + "c" * 64, 1))
    before = (tmp_path / "provenance.jsonl").read_bytes()

    assert mod._record_reemitted_outputs(tmp_path) is None

    assert (tmp_path / "provenance.jsonl").read_bytes() == before, (
        "a failed row's digest was treated as the newest production record")


def test_the_reemit_helper_is_actually_wired_into_the_canonicalize_step():
    """Extracting the block created the failure mode this test class exists
    for: every behavioural test above drives the helper DIRECTLY, so all of
    them stay green even if `step_canonicalize_artefacts` no longer calls it
    and no re-emit is ever recorded on a real run. Walk the runner's AST and
    require the call to be inside that function."""
    import ast
    fn = next((n for n in ast.walk(ast.parse(RUNNER.read_text()))
               if isinstance(n, ast.FunctionDef)
               and n.name == "step_canonicalize_artefacts"), None)
    assert fn is not None, (
        "premise: the canonicalisation step was renamed — this test scans "
        "nothing")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_record_reemitted_outputs"
               for n in ast.walk(fn)), (
        "the re-emit helper is defined but never called by the step that "
        "owns it; a re-run would leave every drifted output undeclared")


def test_reverse_the_wiring_scan_can_fail(tmp_path):
    """REVERSE for the test above. An AST walk that finds the call in the
    real source proves nothing unless it can also NOT find one: run the
    identical predicate over a function that demonstrably does not make the
    call, and require it to answer False."""
    import ast
    src = ("def step_canonicalize_artefacts(project):\n"
           "    _restamp_provenance_output(project)\n"
           "    return None\n")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_record_reemitted_outputs"
                   for n in ast.walk(fn)), (
        "the wiring predicate reports the call present in a function that "
        "does not contain it — it is not measuring wiring")


def test_reverse_canonicalize_reemit_helper_is_a_noop_without_drift(tmp_path):
    """REVERSE. No drift, no record — otherwise every pass would grow the
    ledger and the forward test would pass for the wrong reason."""
    mod = _load_runner()
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "stable\n")
    _heterogeneous_ledger(tmp_path)
    prov = tmp_path / "provenance.jsonl"
    with prov.open("ab") as f:
        f.write((json.dumps(_record(rel, _sha(art))) + "\n").encode())
    before = prov.read_bytes()

    assert mod._record_reemitted_outputs(tmp_path) is None

    assert prov.read_bytes() == before


# ---------------------------------------------------------------------------
# A FAILED INVOCATION PRODUCED NOTHING, SO IT SUPERSEDES NOTHING.
#
# Measured on the newest-record-wins scheme before this guard: an honest
# ledger whose artefact was hand-edited FAILed; appending ONE rc=1
# invocation that merely NAMED that path made the identical ledger PASS
# (1 -> 0). `_hash_declared_outputs` hashes whatever sits at a declared
# path, so a run that exited 1 having written nothing carries the digest of
# the corruption and, unguarded, becomes the newest record of it.
# ---------------------------------------------------------------------------

def _invocation(rel: str, sha: str, rc: int, tool: str = "demotool") -> dict:
    return {
        "record": "invocation", "tool": tool,
        "command": f"{tool} --out {rel}", "exit_code": rc,
        "version_capture": "probed",
        "timestamp": "2026-01-01T00:00:00Z",
        "outputs": {rel: sha},
    }


def test_a_failed_invocation_cannot_vouch_for_a_tampered_artefact(tmp_path):
    """FORWARD. Honest production, then a hand edit, then a FAILED run that
    names the path. The hand edit must still be the answer."""
    rel = "reports/signoff.rpt"
    art = _artefact(tmp_path, rel, "tally: {'PASS': 100, 'FAIL': 4}\n")
    honest = _sha(art)
    art.write_text("tally: {'PASS': 104, 'FAIL': 0}\n")
    _ledger(tmp_path,
            _invocation(rel, honest, 0),
            _invocation(rel, _sha(art), 1))     # rc=1: observed, not produced

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PROVENANCE_HASH_MISMATCH" in (r.stdout + r.stderr)


def test_a_failed_invocations_declaration_is_disclosed_and_counted(tmp_path):
    """FORWARD. Not verified is not the same as not mentioned."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "produced once\n")
    _ledger(tmp_path,
            _invocation(rel, _sha(art), 0),
            _invocation(rel, _sha(art), 1))

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(out.read_text())
    unproduced = [f for f in report["findings"]
                  if f["rule"] == "PROVENANCE_OUTPUT_UNPRODUCED"]
    assert len(unproduced) == 1, report["findings"]
    assert unproduced[0]["severity"] == "DISCLOSED"
    assert report["outcome_census"]["unproduced"] == 1
    # the honest row is still the verified one, NOT superseded by the failure
    assert report["outcome_census"]["superseded"] == 0
    assert report["outcome_census"]["verified_present"] == 1
    assert "UNPRODUCED" in (r.stdout + r.stderr)


def test_reverse_a_successful_rerun_after_a_failure_still_supersedes(tmp_path):
    """REVERSE. The guard must exclude FAILURES, not 'anything later'. An
    honest row, a failed observation, then a real re-run: the re-run is the
    newest record and the FIRST row is superseded by it."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "pass 1\n")
    first = _sha(art)
    art.write_text("pass 2\n")
    _ledger(tmp_path,
            _invocation(rel, first, 0),      # honest first production
            _invocation(rel, first, 1),      # a failure that observed it
            _invocation(rel, _sha(art), 0))  # the real re-run

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    census = json.loads(out.read_text())["outcome_census"]
    assert census["superseded"] == 1, census
    assert census["unproduced"] == 1, census
    assert census["verified_present"] == 1, census


def test_reverse_a_row_with_no_exit_code_is_still_a_production_record(
        tmp_path):
    """REVERSE. `provenance_logger.py` omits `exit_code` entirely. Absence
    must not be read as failure, or every legacy row stops superseding and
    every legacy ledger's census changes."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first\n")
    first = _sha(art)
    art.write_text("second\n")
    _ledger(tmp_path, _record(rel, first), _record(rel, _sha(art)))

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    census = json.loads(out.read_text())["outcome_census"]
    assert census["unproduced"] == 0, census
    assert census["superseded"] == 1, census


def test_reverse_rc_zero_rows_are_unaffected_by_the_guard(tmp_path):
    """REVERSE. An explicit `exit_code: 0` must behave exactly as before."""
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "first\n")
    first = _sha(art)
    art.write_text("second\n")
    _ledger(tmp_path, _invocation(rel, first, 0), _invocation(rel, _sha(art), 0))

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    census = json.loads(out.read_text())["outcome_census"]
    assert census["unproduced"] == 0, census
    assert census["superseded"] == 1, census


def test_reverse_the_failed_row_does_not_hide_a_missing_artefact(tmp_path):
    """REVERSE. Excluding failed rows from supersession must not let the
    honest row's own absence check go quiet.

    NOTE what this does and does not measure: the ledger also carries an
    rc=0 row for the same path, so the FAIL it observes comes from THAT
    row's absence check. It says nothing about the failed row's own. The
    two tests below drive a ledger whose ONLY declaration of the path is
    the failed one, so the verdict is about the failed row itself.
    """
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "produced\n")
    good = _sha(art)
    _ledger(tmp_path, _invocation(rel, good, 0), _invocation(rel, good, 1))
    art.unlink()

    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# THE FAILED-ROW EXEMPTION IS ABOUT SUPERSESSION AND VERIFICATION-AGAINST-
# DISK. IT IS NOT AN AMNESTY FOR THE ROW.
#
# The guard shipped as a blanket `continue` placed AHEAD of the on-disk
# block, so a failed row's declared outputs skipped the path-boundary check
# and the existence check as well as supersession — every question the gate
# asks of a row, when only one of them had a justification. A run that
# exited non-zero having written OUTSIDE the project boundary, or having
# declared a path that is not there at all, was the one row the audit could
# not name.
#
# What the exemption legitimately buys the row stays exactly as it was:
# it supersedes nothing (`_latest_declaration_index`), and its digest is
# not compared against disk, because a later honest run may have replaced
# those bytes without declaring them and faulting on that would punish an
# honest ledger. Both are pinned by the FORWARD tests above and by
# `test_reverse_a_failed_rows_digest_is_still_not_checked_against_disk`.
# ---------------------------------------------------------------------------

def test_a_failed_rows_absent_output_is_still_a_missing_artefact(tmp_path):
    """FORWARD. The only row that declares this path exited 1, and the path
    is not on disk. PROVENANCE_OUTPUT_FILE_MISSING is not a claim about who
    produced the bytes — it is a dangling pointer, and the ledger dangles it
    whatever the exit code was."""
    rel = "reports/never_written.rpt"
    _ledger(tmp_path, _invocation(rel, "sha256:" + "0" * 64, 1))

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    report = json.loads(out.read_text())
    rules = [f["rule"] for f in report["findings"]]
    assert "PROVENANCE_OUTPUT_FILE_MISSING" in rules, report["findings"]
    assert report["errors_count"] >= 1, report
    # the row is faulted, so it is NOT also filed away as a disclosed
    # observation — one row, one verdict.
    assert report["outcome_census"]["unproduced"] == 0, report["outcome_census"]


def test_a_failed_row_declaring_a_path_outside_the_project_still_faults(
        tmp_path):
    """FORWARD. Boundary before bookkeeping. A run that exited non-zero
    having declared an artefact outside the project root is precisely the
    row an audit exists to name, and the blanket exemption made it the one
    row it could not."""
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "outside.rpt"
    outside.write_text("not owned by this project\n")
    _ledger(project, _invocation("../outside.rpt", _sha(outside), 1))

    out = tmp_path / "report.json"
    r = _run(project, "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    report = json.loads(out.read_text())
    rules = [f["rule"] for f in report["findings"]]
    assert "PROVENANCE_PATH_OUTSIDE_PROJECT" in rules, report["findings"]
    assert report["errors_count"] >= 1, report
    assert report["outcome_census"]["unproduced"] == 0, report["outcome_census"]


def test_reverse_a_failed_rows_digest_is_still_not_checked_against_disk(
        tmp_path):
    """REVERSE — a CEILING, not a floor. This one passes on BOTH sides of
    the narrowing and is here to stop the fix swinging too far.

    Narrowing the exemption must not turn into deleting it. A failed row
    whose declared digest disagrees with the bytes now on disk is NOT a
    PROVENANCE_HASH_MISMATCH: the row recorded what it FOUND at some earlier
    moment, and a later honest run that rewrote the file without declaring
    it would otherwise be reported as tampering. The row stays DISCLOSED
    UNPRODUCED and stays out of `verified_present`.
    """
    rel = "reports/out.rpt"
    art = _artefact(tmp_path, rel, "what the failed run saw\n")
    seen = _sha(art)
    art.write_text("what a later run left behind\n")
    _ledger(tmp_path, _invocation(rel, seen, 1))

    out = tmp_path / "report.json"
    r = _run(tmp_path, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(out.read_text())
    rules = [f["rule"] for f in report["findings"]]
    assert "PROVENANCE_HASH_MISMATCH" not in rules, report["findings"]
    assert rules == ["PROVENANCE_OUTPUT_UNPRODUCED"], report["findings"]
    census = report["outcome_census"]
    assert census["unproduced"] == 1, census
    assert census["verified_present"] == 0, census
