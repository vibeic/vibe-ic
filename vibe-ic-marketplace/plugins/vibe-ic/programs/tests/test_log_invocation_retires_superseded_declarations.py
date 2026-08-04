#!/usr/bin/env python3
"""An append-only ledger must survive a producer that legitimately runs TWICE.

`provenance.jsonl` is append-only and
`provenance_output_hash_completeness_check` re-hashes EVERY declared output of
EVERY entry. So the moment any producer re-emits a path an earlier entry
declared, that earlier entry's digest can never match disk again:

    PROVENANCE_HASH_MISMATCH     on the old row   (declared != on-disk)
    PROVENANCE_HASH_INCONSISTENT on the new row   (two rows, two digests)

and NO subsequent run can clear either — the chain is punished for truthfully
recording a second production. Today that is rare only because the sign-off
producers skip when their own output already exists; a freshness-aware producer
re-emits after every re-route, and then this fires on ordinary clean runs.

The repo already had the sanctioned remedy for ONE artefact
(`_restamp_provenance_output`, whose docstring states that appending a second
entry "would only trade PROVENANCE_HASH_MISMATCH for
PROVENANCE_HASH_INCONSISTENT"). It was never wired into `_log_invocation` — the
writer every tool invocation goes through. This is that remedy generalised, with
one deliberate difference: the superseded digest is RETIRED to
`outputs_superseded`, not overwritten, so no row is ever edited into claiming
bytes it did not produce.

FORWARD (must FAIL against the byte-identical pre-fix runner, PASS after):
  * F1 a second `_log_invocation` for the same path leaves the gate clean
  * F2 the retired digest is preserved, not deleted
  * F3 a row that declared SEVERAL paths retires only the re-produced one

REVERSE (must STILL hold after the fix — these are what stop this from being
"mutate the ledger until the gate goes quiet"):
  * R1 a stale declaration that NO invocation re-produced is untouched and
       still FAILs — the gate's real catch is not weakened
  * R2 the row that this call just appended never retires itself
  * R3 a row whose outputs would be EMPTIED, and which is not a command-audit
       invocation row, is left alone — retiring must not trade
       HASH_MISMATCH for PROVENANCE_OUTPUTS_MISSING
  * R4 no re-run -> the ledger file is byte-identical afterwards
  * R6 a FAILED invocation retires nothing

GUARD case on the new mechanism (cannot run pre-fix — the helper does not
exist there — so it is counted with the forward cases, not as a both-ways pass):
  * R5 retiring never leaves an artefact undeclared

Measured negative control (this file, unchanged, against the byte-identical
pre-fix `phase3_one_shot_runner.py` restored from HEAD):

    PRE-FIX   4 failed, 5 passed      <- the 3 forward cases + the R5 guard
    POST-FIX  9 passed

(Reverting ONLY the runner — an earlier attempt at this control used `git stash`,
which reverted the test file too and reported a meaningless 8-passed.)

The 5 that pass BOTH ways are the reverse cases. R1, R3 and R6 are the
load-bearing ones: R1 proves the gate's real catch is untouched, R3 proves the
fix refuses the case where it would have traded one fatal fault for another, and
R6 is the one this fix was measured to get WRONG before the rc gate was added.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
for _p in (str(_PROGRAMS), str(_PROGRAMS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase3_one_shot_runner as _runner            # noqa: E402

GATE = _PROGRAMS / "provenance_output_hash_completeness_check.py"


def _sha_text(t: str) -> str:
    return "sha256:" + hashlib.sha256(t.encode()).hexdigest()


def _invocation(outputs, tool="openroad"):
    """A well-formed command-audit row, exactly as `_log_invocation` writes."""
    return {"record": "invocation", "tool": tool, "version": "v",
            "version_capture": "probed", "command": f"{tool} -no_init -exit",
            "exit_code": 0, "duration_ms": 12, "duration_s": 0.012,
            "measured": True, "timestamp": "2026-01-01T00:00:00Z",
            "marker": "step.tcl", "outputs": outputs}


def _write_ledger(proj: Path, rows):
    (proj / "provenance.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))


def _read_ledger(proj: Path):
    return [json.loads(l) for l in
            (proj / "provenance.jsonl").read_text().splitlines() if l.strip()]


def _gate(proj: Path):
    out = proj / "gate.json"
    r = subprocess.run([sys.executable, str(GATE), str(proj),
                        "--json", str(out)], capture_output=True, text=True)
    return r.returncode, json.loads(out.read_text())


def _fatal(rep):
    return sorted(f["rule"] for f in rep["findings"] if f["severity"] == "ERROR")


def _relog(proj: Path, outputs, rc: int = 0):
    """Drive the REAL writer with the sink pointed at `proj`."""
    _runner._PROV_SINK = str(proj)
    try:
        _runner._log_invocation("openroad -no_init -exit re-run", rc, 12,
                                marker="step.tcl", outputs=outputs)
    finally:
        _runner._PROV_SINK = None


# ------------------------------------------------------------------ FORWARD

def test_f1_second_production_of_same_path_leaves_the_gate_clean(tmp_path):
    """PRE-FIX: HASH_MISMATCH + HASH_INCONSISTENT. POST-FIX: clean."""
    rel = "reports/phase3/ir_em.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("v1 — first layout\n")
    _write_ledger(tmp_path, [_invocation({rel: _sha_text("v1 — first layout\n")})])

    rc, rep = _gate(tmp_path)
    assert rc == 0, "precondition: the tree starts clean"

    # The layout was re-routed and the producer legitimately re-emits.
    (tmp_path / rel).write_text("v2 — re-routed layout\n")
    _relog(tmp_path, [tmp_path / rel])

    rc, rep = _gate(tmp_path)
    assert rc == 0, f"gate must be clean after a legitimate re-run: {rep}"
    assert _fatal(rep) == []


def test_f2_the_retired_digest_is_preserved_not_deleted(tmp_path):
    """Nothing is invented and nothing is lost: the old row stops CLAIMING the
    old digest and still RECORDS it."""
    rel = "reports/phase3/ir_em.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("v1\n")
    old_sha = _sha_text("v1\n")
    _write_ledger(tmp_path, [_invocation({rel: old_sha})])

    (tmp_path / rel).write_text("v2\n")
    _relog(tmp_path, [tmp_path / rel])

    rows = _read_ledger(tmp_path)
    assert rows[0].get("outputs_superseded", {}).get(rel) == old_sha
    assert rel not in rows[0].get("outputs", {})
    # and the NEW row declares the real current bytes
    assert rows[-1]["outputs"][rel] == _sha_text("v2\n")


# ------------------------------------------------------------------ REVERSE
# (F3 lives below with the reverse block only for narrative order; it is a
#  FORWARD case — it asserts the new mechanism and cannot pass pre-fix.)

def test_r1_a_stale_declaration_nobody_reproduced_is_untouched_and_fails(tmp_path):
    """The defect this gate exists to catch must still be caught. Only paths
    the invocation ACTUALLY produced are eligible."""
    rel = "reports/phase3/ir_em.log"
    other = "reports/phase3/antenna.rpt"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("v1\n")
    (tmp_path / other).write_text("tampered\n")
    _write_ledger(tmp_path, [_invocation({rel: _sha_text("v1\n"),
                                          other: _sha_text("original\n")})])

    (tmp_path / rel).write_text("v2\n")
    _relog(tmp_path, [tmp_path / rel])          # produced `rel` ONLY

    rows = _read_ledger(tmp_path)
    assert rows[0]["outputs"][other] == _sha_text("original\n"), \
        "an untouched path must keep its declaration"
    rc, rep = _gate(tmp_path)
    assert rc == 1
    assert "PROVENANCE_HASH_MISMATCH" in _fatal(rep)


def test_r2_the_row_just_appended_never_retires_itself(tmp_path):
    rel = "reports/phase3/ir_em.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("v1\n")
    _write_ledger(tmp_path, [_invocation({rel: _sha_text("v1\n")})])
    (tmp_path / rel).write_text("v2\n")
    _relog(tmp_path, [tmp_path / rel])

    last = _read_ledger(tmp_path)[-1]
    assert last["outputs"][rel] == _sha_text("v2\n")
    assert "outputs_superseded" not in last


def test_r3_a_non_invocation_row_is_never_emptied(tmp_path):
    """An artefact-declaration row (no `record`) with empty outputs is
    PROVENANCE_OUTPUTS_MISSING — a DIFFERENT fatal fault. Retiring its only
    declaration would reshape the fault, not fix it, so it is refused and the
    honest HASH_MISMATCH is what the reader gets."""
    rel = "reports/phase3/ir_em.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("v1\n")
    _write_ledger(tmp_path, [
        {"tool": "openroad", "command": "reconstructed", "exit_code": 0,
         "duration_ms": None, "reconstructed": True,
         "timestamp": "2026-01-01T00:00:00Z",
         "outputs": {rel: _sha_text("v1\n")}}])

    (tmp_path / rel).write_text("v2\n")
    _relog(tmp_path, [tmp_path / rel])

    rows = _read_ledger(tmp_path)
    assert rows[0]["outputs"] == {rel: _sha_text("v1\n")}, \
        "the sole declaration of a non-invocation row must be left alone"
    rc, rep = _gate(tmp_path)
    assert rc == 1
    fatal = _fatal(rep)
    assert "PROVENANCE_HASH_MISMATCH" in fatal
    assert "PROVENANCE_OUTPUTS_MISSING" not in fatal


def test_f3_a_multi_output_row_retires_only_the_reproduced_path(tmp_path):
    a, b = "reports/phase3/ir_em.log", "reports/phase3/em.rpt"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / a).write_text("a1\n")
    (tmp_path / b).write_text("b1\n")
    _write_ledger(tmp_path, [_invocation({a: _sha_text("a1\n"),
                                          b: _sha_text("b1\n")})])
    (tmp_path / a).write_text("a2\n")
    _relog(tmp_path, [tmp_path / a])

    rows = _read_ledger(tmp_path)
    assert rows[0]["outputs"] == {b: _sha_text("b1\n")}
    assert rows[0]["outputs_superseded"] == {a: _sha_text("a1\n")}
    rc, rep = _gate(tmp_path)
    assert rc == 0, f"{rep}"


def test_r4_no_rerun_leaves_the_ledger_byte_identical(tmp_path):
    """A producer emitting a path nobody declared before must not rewrite the
    file. A fix that rewrote every ledger on every invocation would be a
    corpus-wide mutation disguised as a bug fix."""
    rel = "reports/phase3/new.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("fresh\n")
    _write_ledger(tmp_path, [_invocation({"reports/phase3/other.log":
                                          _sha_text("o\n")})])
    (tmp_path / "reports/phase3/other.log").write_text("o\n")
    before = (tmp_path / "provenance.jsonl").read_bytes()

    _relog(tmp_path, [tmp_path / rel])

    after = (tmp_path / "provenance.jsonl").read_bytes()
    assert after.startswith(before), \
        "existing rows must be byte-identical; only an append is allowed"


def test_r5_retiring_never_leaves_an_artefact_undeclared(tmp_path):
    """Retiring the ONLY declaration of a path would make the gate PASS by
    leaving nothing to check — a hole strictly worse than the mismatch it
    replaces. A path is eligible only when some row already declares this run's
    digest, so the helper called with an unbacked digest is inert."""
    rel = "reports/phase3/ir_em.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("v1\n")
    _write_ledger(tmp_path, [_invocation({rel: _sha_text("v1\n")})])

    (tmp_path / rel).write_text("v2\n")
    before = (tmp_path / "provenance.jsonl").read_bytes()
    # No new row was appended: nothing backs the v2 digest.
    _runner._retire_superseded_declarations(str(tmp_path),
                                            {rel: _sha_text("v2\n")})
    assert (tmp_path / "provenance.jsonl").read_bytes() == before, \
        "an unbacked digest must not retire anything"
    rc, rep = _gate(tmp_path)
    assert rc == 1, "the artefact must still be accounted for by the gate"
    assert "PROVENANCE_HASH_MISMATCH" in _fatal(rep)


def test_r6_a_failed_invocation_retires_nothing(tmp_path):
    """WRITTEN FROM A MEASURED MISS, not from caution.

    `_hash_declared_outputs` hashes whatever sits at the declared path — it
    cannot know whether THIS invocation produced it. So a run that FAILED over
    a pre-existing artefact declares that artefact's current digest. Without an
    rc gate, the older row that really did produce it gets its declaration
    retired, and the gate goes quiet because the measurement moved rather than
    because the ledger got better.

    Observed on a real tree: an openroad sign-off producer exited 1 having
    written nothing, adopted the previous run's report, and the true
    declaration was retired. This is that case, refused.
    """
    rel = "reports/phase3/ir_em.log"
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / rel).write_text("produced by the run that SUCCEEDED\n")
    stale = _sha_text("an older production\n")
    _write_ledger(tmp_path, [_invocation({rel: stale})])
    before = (tmp_path / "provenance.jsonl").read_bytes()

    _relog(tmp_path, [tmp_path / rel], rc=1)      # the run FAILED

    rows = _read_ledger(tmp_path)
    assert rows[0]["outputs"][rel] == stale, \
        "a failed invocation must not retire anyone else's declaration"
    assert "outputs_superseded" not in rows[0]
    assert (tmp_path / "provenance.jsonl").read_bytes().startswith(before)
    rc, rep = _gate(tmp_path)
    assert rc == 1, "the real fault must still be visible"
    assert "PROVENANCE_HASH_MISMATCH" in _fatal(rep)
