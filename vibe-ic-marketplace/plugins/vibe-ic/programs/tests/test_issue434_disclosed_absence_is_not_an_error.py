#!/usr/bin/env python3
"""#434 — two provenance gates disagreed about the same 102 rows.

`provenance_output_hash_completeness_check` ERRORed
PROVENANCE_OUTPUT_FILE_MISSING on exactly the rows #414 had deliberately
annotated as published-without-this-file. Measured across the 21 tracked
ledgers (156 declared outputs) at bb2f154d3:

    present at the declared path, hashes as declared        54
    absent, disclosed as relocated, hashes at the target    12
    absent, disclosed as not shipped, digest recorded       90
    absent, no disclosure of any kind                        0

102 ERRORs, 12 of 21 cells FAIL, and not one of them was wrong about the
facts — only about the verdict. The middle set is not a corner case: it is
65% of every declared output in the corpus.

THE TRAP THIS FILE GUARDS. The cheapest way to clear those 102 was to
delete the disclosure, which restores the dangling pointer #414 removed.
The second cheapest was to skip any row carrying the marker, which makes
the marker a waiver. So every accepted state below is PAIRED with the
near-miss that must still fail, and the last section runs those pairs as
MUTATIONS OF A REAL PUBLISHED CELL — including the "just delete the
disclosure" move itself, which must make the gate LOUDER, not quieter.

The synthetic pairs carry the logic; the corpus mutations are the witness
that the logic is pointed at real published data. Only the latter can skip,
and only when benchmark-data is genuinely not checked out.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import provenance_output_hash_completeness_check as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]
_REASON = "not shipped in this deliverable; digest is the run's own"


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _cell(tmp_path: Path, files: dict, rows: list) -> Path:
    cell = tmp_path / "cell"
    cell.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = cell / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (cell / "provenance.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    return cell


def _rules(findings, severity=None):
    return [f.rule for f in findings
            if severity is None or f.severity == severity]


# ── the two states that already existed, unchanged ──────────────────────────

def test_a_present_output_that_hashes_is_still_verified(tmp_path):
    body = b"real synth log\n"
    cell = _cell(tmp_path, {"synth.log": body},
                 [{"tool": "t", "outputs": {"synth.log": _sha(body)}}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "PASS", _rules(findings)
    assert counts == {"declared": 1, "superseded": 0, "unproduced": 0,
                      "verified_present": 1,
                      "verified_relocated": 0, "not_verifiable_here": 0}


def test_an_absent_output_with_no_disclosure_is_still_an_ERROR(tmp_path):
    """THE REGRESSION GUARD. #434 must not have removed the check, only
    split its outcome. A row that declares a path, does not ship it, and
    says nothing about that is the original defect and stays fatal."""
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"gone.v": _sha(b"x")}}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_OUTPUT_FILE_MISSING"]
    assert counts["not_verifiable_here"] == 0


# ── PAIR A — a relocation makes the gate do MORE work, not less ─────────────

def test_a_relocation_to_the_same_bytes_is_verified(tmp_path):
    body = b"DEF CONTENT\n"
    cell = _cell(tmp_path, {"stage4/routed.def": body},
                 [{"tool": "t", "outputs": {"pnr/spm.def": _sha(body)},
                   "outputs_relocated_at_publish": {
                       "pnr/spm.def": "stage4/routed.def"}}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "PASS", _rules(findings)
    assert findings == []
    assert counts["verified_relocated"] == 1
    assert counts["verified_present"] == 0


def test_a_relocation_to_DIFFERENT_bytes_is_an_ERROR(tmp_path):
    """The pair. If a marker could repoint a declaration at any shipped
    file, it would launder a changed artefact into a passing one."""
    cell = _cell(tmp_path, {"stage4/routed.def": b"SOMETHING ELSE\n"},
                 [{"tool": "t", "outputs": {"pnr/spm.def": _sha(b"DEF\n")},
                   "outputs_relocated_at_publish": {
                       "pnr/spm.def": "stage4/routed.def"}}])
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_RELOCATION_UNVERIFIED"]


def test_a_relocation_to_a_target_that_is_not_there_is_an_ERROR(tmp_path):
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"pnr/spm.def": _sha(b"DEF\n")},
                   "outputs_relocated_at_publish": {
                       "pnr/spm.def": "stage4/routed.def"}}])
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_RELOCATION_UNVERIFIED"]


def test_a_relocation_pointing_outside_the_project_is_an_ERROR(tmp_path):
    """The traversal guard applies to the disclosed path too — otherwise
    the marker is a way around the v1.6.32 check it was added after."""
    outside = tmp_path / "outside.def"
    body = b"DEF\n"
    outside.write_bytes(body)
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"pnr/spm.def": _sha(body)},
                   "outputs_relocated_at_publish": {
                       "pnr/spm.def": "../outside.def"}}])
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_PATH_OUTSIDE_PROJECT"]


@pytest.mark.parametrize("shipped", [
    {"elsewhere.def": b"OTHER BYTES\n"},   # target ships, wrong digest
    {},                                    # target does not ship at all
])
def test_a_broken_relocation_may_not_fall_back_on_a_pruned_marker(
        tmp_path, shipped):
    """A row that says "it ships elsewhere" does not get to say "it does
    not ship" when the first claim fails to check out. Both ways a
    relocation can break are covered: a wrong-digest target and an absent
    one reach different branches, and a fallback added to either would let
    the weaker disclosure rescue the stronger one."""
    cell = _cell(tmp_path, shipped,
                 [{"tool": "t", "outputs": {"pnr/spm.def": _sha(b"DEF\n")},
                   "outputs_relocated_at_publish": {
                       "pnr/spm.def": "elsewhere.def"},
                   "outputs_pruned_at_publish": ["pnr/spm.def"],
                   "outputs_pruned_reason": _REASON}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_RELOCATION_UNVERIFIED"]
    assert counts["not_verifiable_here"] == 0
    assert counts["verified_relocated"] == 0


# ── PAIR B — a not-shipped disclosure must be explained, true, digested ─────

def test_a_pruned_output_with_a_reason_is_DISCLOSED_not_an_ERROR(tmp_path):
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"pnr/openroad.log": _sha(b"log")},
                   "outputs_pruned_at_publish": ["pnr/openroad.log"],
                   "outputs_pruned_reason": _REASON}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "PASS", _rules(findings)
    assert _rules(findings) == ["PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE"]
    assert [f.severity for f in findings] == ["DISCLOSED"]
    assert counts["not_verifiable_here"] == 1
    # The row is not silent: the digest the run recorded is quoted back, so
    # a reader can still match it against a copy they obtain elsewhere.
    assert _sha(b"log").split(":")[1] in findings[0].detail


def test_a_pruned_output_with_NO_reason_is_an_ERROR(tmp_path):
    """The pair, and the line between the two kinds of marker. A bare list
    of paths says only "stop asking"; that is a waiver and is refused."""
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"pnr/openroad.log": _sha(b"log")},
                   "outputs_pruned_at_publish": ["pnr/openroad.log"]}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_PRUNE_UNEXPLAINED"]
    assert counts["not_verifiable_here"] == 0


def test_a_whitespace_only_reason_is_an_ERROR(tmp_path):
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"a.log": _sha(b"log")},
                   "outputs_pruned_at_publish": ["a.log"],
                   "outputs_pruned_reason": "   \n  "}])
    assert _rules(G.audit_counted(cell)[1]) == ["PROVENANCE_PRUNE_UNEXPLAINED"]


def test_a_pruned_marker_NEVER_silences_a_hash_mismatch(tmp_path):
    """THE ANTI-GAMING PROPERTY. Presence and hash are decided before any
    disclosure is read, so "mark it pruned" cannot be used to quiet a
    changed artefact that is sitting right there."""
    cell = _cell(tmp_path, {"a.gds": b"TAMPERED\n"},
                 [{"tool": "t", "outputs": {"a.gds": _sha(b"ORIGINAL\n")},
                   "outputs_pruned_at_publish": ["a.gds"],
                   "outputs_pruned_reason": _REASON}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_MISMATCH" in _rules(findings)
    assert counts["not_verifiable_here"] == 0


def test_a_pruned_marker_on_a_file_that_IS_here_is_CONTRADICTED(tmp_path):
    """"Not shipped" is a factual claim, and this one is refutable: the
    artefact with exactly that digest is at exactly that path."""
    body = b"SHIPPED AFTER ALL\n"
    cell = _cell(tmp_path, {"a.gds": body},
                 [{"tool": "t", "outputs": {"a.gds": _sha(body)},
                   "outputs_pruned_at_publish": ["a.gds"],
                   "outputs_pruned_reason": _REASON}])
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert _rules(findings) == ["PROVENANCE_PRUNE_CONTRADICTED"]
    assert counts["verified_present"] == 1


def test_a_disclosure_does_not_leak_across_rows(tmp_path):
    """Scoped per row. If one row's marker could account for another
    row's declaration, a single marker anywhere in the ledger would
    account for that path everywhere in it."""
    cell = _cell(tmp_path, {}, [
        {"tool": "a", "outputs": {"x.log": _sha(b"x")},
         "outputs_pruned_at_publish": ["x.log"],
         "outputs_pruned_reason": _REASON},
        {"tool": "b", "outputs": {"y.log": _sha(b"y")},
         "outputs_pruned_at_publish": ["x.log"],
         "outputs_pruned_reason": _REASON},
    ])
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert "PROVENANCE_OUTPUT_FILE_MISSING" in _rules(findings)


@pytest.mark.parametrize("row_extra", [
    {"outputs_pruned_at_publish": "a.log", "outputs_pruned_reason": _REASON},
    {"outputs_pruned_at_publish": [123], "outputs_pruned_reason": _REASON},
    {"outputs_pruned_at_publish": ["a.log"], "outputs_pruned_reason": 7},
    {"outputs_relocated_at_publish": ["a.log"]},
    {"outputs_relocated_at_publish": {"a.log": ""}},
])
def test_a_malformed_disclosure_accounts_for_nothing(tmp_path, row_extra):
    """Degrade toward the ERROR, never toward the pass. A disclosure the
    gate cannot read must leave the row exactly as unaccounted-for as it
    was before anyone wrote the key."""
    row = {"tool": "t", "outputs": {"a.log": _sha(b"log")}}
    row.update(row_extra)
    verdict, findings, counts = G.audit_counted(_cell(tmp_path, {}, [row]))
    assert verdict == "FAIL"
    assert counts["not_verifiable_here"] == 0
    assert set(_rules(findings)) <= {"PROVENANCE_OUTPUT_FILE_MISSING",
                                     "PROVENANCE_PRUNE_UNEXPLAINED"}


# ── the population question, answered by a flag and never by a guess ────────

def test_require_outputs_present_promotes_DISCLOSED_back_to_ERROR(tmp_path):
    """On a RUN directory nothing has been published yet, so a not-shipped
    disclosure is itself the fault. Which population is being audited is
    stated by the caller, not inferred from the presence of a marker."""
    row = {"tool": "t", "outputs": {"a.log": _sha(b"log")},
           "outputs_pruned_at_publish": ["a.log"],
           "outputs_pruned_reason": _REASON}
    cell = _cell(tmp_path, {}, [row])
    assert G.audit_counted(cell)[0] == "PASS"
    verdict, findings, _ = G.audit_counted(cell, require_outputs_present=True)
    assert verdict == "FAIL"
    assert [f.severity for f in findings] == ["ERROR"]
    assert _rules(findings) == ["PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE"]


def test_DISCLOSED_is_its_own_severity_not_a_warning(tmp_path):
    """A WARNING says something looks wrong. Nothing is wrong here, and
    filing 90 of them corpus-wide would train readers to ignore the
    channel that carries ATTEST_TIMING_SUSPICIOUS."""
    cell = _cell(tmp_path, {},
                 [{"tool": "t", "outputs": {"a.log": _sha(b"log")},
                   "outputs_pruned_at_publish": ["a.log"],
                   "outputs_pruned_reason": _REASON}])
    _, findings, _ = G.audit_counted(cell)
    assert _rules(findings, "WARNING") == []
    assert _rules(findings, "ERROR") == []
    assert len(_rules(findings, "DISCLOSED")) == 1


def test_the_verdict_line_states_what_PASS_did_not_cover(tmp_path, capsys):
    """"PASS: provenance.jsonl is on-disk verifiable" over a ledger where
    7 of 17 outputs were never opened is the sentence #434 exists to
    stop. The census goes on the verdict line itself."""
    body = b"here\n"
    cell = _cell(tmp_path, {"a.log": body}, [
        {"tool": "t", "outputs": {"a.log": _sha(body),
                                  "b.log": _sha(b"gone\n")},
         "outputs_pruned_at_publish": ["b.log"],
         "outputs_pruned_reason": _REASON}])
    assert G.main([str(cell)]) == 0
    out = capsys.readouterr().out
    assert "2 declared output(s)" in out
    assert "1 verified on disk" in out
    assert "1 NOT VERIFIABLE HERE" in out


def test_the_json_report_carries_the_census_and_the_disclosed_count(tmp_path):
    body = b"here\n"
    cell = _cell(tmp_path, {"a.log": body}, [
        {"tool": "t", "outputs": {"a.log": _sha(body),
                                  "b.log": _sha(b"gone\n")},
         "outputs_pruned_at_publish": ["b.log"],
         "outputs_pruned_reason": _REASON}])
    out = tmp_path / "r.json"
    assert G.main([str(cell), "--json", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["disclosed_count"] == 1
    assert rep["outcome_census"] == {"declared": 2, "superseded": 0,
                                     "unproduced": 0,
                                     "verified_present": 1,
                                     "verified_relocated": 0,
                                     "not_verifiable_here": 1}


def test_audit_keeps_its_two_tuple_shape_for_existing_callers():
    verdict, findings = G.audit(Path("/nonexistent-project-dir-434"))
    assert (verdict, findings) == ("VACUOUS_PASS", [])


# ── the same pairs, as mutations of a REAL published cell ───────────────────

_SPM = _REPO / "benchmark-data/ic/spm/v1.5.65_sky130A"


def _real_cell(tmp_path: Path) -> Path:
    if not (_SPM / "provenance.jsonl").is_file():
        pytest.skip(f"benchmark-data not checked out at {_SPM}")
    dst = tmp_path / "published"
    shutil.copytree(_SPM, dst, symlinks=True)
    return dst


def _rows(cell: Path) -> list:
    return [json.loads(l)
            for l in (cell / "provenance.jsonl").read_text().splitlines()
            if l.strip()]


def _write_rows(cell: Path, rows: list) -> None:
    (cell / "provenance.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def test_the_real_published_cell_passes_with_the_measured_census(tmp_path):
    """The count #434 asked for, on the cell it was measured on. Identical
    in all three spm deliverables: 17 declared, 7 shipped and hashing, 3
    shipped under a disclosed other name, 7 disclosed as not shipped."""
    verdict, findings, counts = G.audit_counted(_real_cell(tmp_path))
    assert verdict == "PASS", _rules(findings, "ERROR")
    assert counts == {"declared": 17, "superseded": 0, "unproduced": 0,
                      "verified_present": 7,
                      "verified_relocated": 3, "not_verifiable_here": 7}


def test_MUTATION_deleting_the_disclosure_makes_the_gate_LOUDER(tmp_path):
    """THE TRAP, RUN AS AN EXPERIMENT. #434's warning was that the cheapest
    way to clear the 102 errors is to delete the marker. Do exactly that to
    a real cell: the gate must go from PASS to FAIL, because the row is now
    a dangling pointer again — which is #414's defect, not its fix."""
    cell = _real_cell(tmp_path)
    rows = _rows(cell)
    stripped = 0
    for r in rows:
        if r.pop("outputs_pruned_at_publish", None) is not None:
            stripped += 1
        r.pop("outputs_pruned_reason", None)
    _write_rows(cell, rows)
    verdict, findings, counts = G.audit_counted(cell)
    assert verdict == "FAIL"
    # `== 7` was the published cell's row count. THE COUNT IS DERIVED FROM THE
    # MUTATION: every row whose marker this test just deleted must come back as
    # a dangling pointer — one error per row stripped, no more and no fewer.
    # That is the experiment's own arithmetic, so republishing the cell with a
    # different number of pruned rows changes both sides together.
    assert stripped > 0, (
        "the real cell carries no `outputs_pruned_at_publish` marker, so this "
        "experiment deleted nothing and proves nothing")
    assert _rules(findings, "ERROR").count(
        "PROVENANCE_OUTPUT_FILE_MISSING") == stripped, (
        f"deleting {stripped} marker(s) must produce {stripped} dangling-"
        f"pointer error(s)")
    assert counts["not_verifiable_here"] == 0


def test_MUTATION_a_tampered_shipped_file_is_still_caught(tmp_path):
    """PASS on a published cell is not vacuous. 7 of its outputs are real
    files that are really hashed; change one byte of one and the gate says
    so. This is the 66 verifications that would be lost by deciding the
    gate does not belong on curated deliverables."""
    cell = _real_cell(tmp_path)
    victim = next(p for r in _rows(cell) for p in (r.get("outputs") or {})
                  if (cell / p).is_file())
    tgt = cell / victim
    tgt.write_bytes(tgt.read_bytes() + b"\n// tampered\n")
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_MISMATCH" in _rules(findings, "ERROR")


def test_MUTATION_dropping_the_reason_from_a_real_row_is_an_ERROR(tmp_path):
    """The disclosure is load-bearing on real data too: keep the path list,
    drop the sentence that explains it, and what is left is a silencer."""
    cell = _real_cell(tmp_path)
    rows = _rows(cell)
    assert any(r.pop("outputs_pruned_reason", None) for r in rows), \
        "the published cell no longer carries a pruned reason to drop"
    _write_rows(cell, rows)
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert "PROVENANCE_PRUNE_UNEXPLAINED" in _rules(findings, "ERROR")


def test_MUTATION_claiming_a_shipped_file_was_pruned_is_CONTRADICTED(tmp_path):
    """A false disclosure on real data. Take an output the cell really does
    ship and add it to the not-shipped list; the gate refutes it by finding
    exactly that digest at exactly that path."""
    cell = _real_cell(tmp_path)
    rows = _rows(cell)
    for r in rows:
        shipped = [p for p in (r.get("outputs") or {}) if (cell / p).is_file()]
        if shipped:
            r["outputs_pruned_at_publish"] = sorted(
                set(r.get("outputs_pruned_at_publish") or []) | {shipped[0]})
            r.setdefault("outputs_pruned_reason", _REASON)
            break
    else:
        pytest.fail("the published cell ships none of its declared outputs")
    _write_rows(cell, rows)
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert "PROVENANCE_PRUNE_CONTRADICTED" in _rules(findings, "ERROR")


def test_MUTATION_repointing_a_real_relocation_elsewhere_is_UNVERIFIED(tmp_path):
    """The three relocated rows are the ones #414 called actively
    misleading. Point one at a different shipped file — a plausible-looking
    repair — and the gate rejects it, because only an equal digest counts."""
    cell = _real_cell(tmp_path)
    rows = _rows(cell)
    others = [p for r in rows for p in (r.get("outputs") or {})
              if (cell / p).is_file()]
    assert others, "the published cell ships none of its declared outputs"
    for r in rows:
        reloc = r.get("outputs_relocated_at_publish") or {}
        if reloc:
            r["outputs_relocated_at_publish"] = {
                k: others[0] for k in reloc}
            break
    else:
        pytest.fail("the published cell carries no relocation to repoint")
    _write_rows(cell, rows)
    verdict, findings, _ = G.audit_counted(cell)
    assert verdict == "FAIL"
    assert "PROVENANCE_RELOCATION_UNVERIFIED" in _rules(findings, "ERROR")


def test_MUTATION_removing_a_relocated_target_is_UNVERIFIED(tmp_path):
    """And the disclosure is checked against the tree, not taken on trust:
    delete the file a relocation points at and the row stops verifying."""
    cell = _real_cell(tmp_path)
    for r in _rows(cell):
        for tgt in (r.get("outputs_relocated_at_publish") or {}).values():
            if (cell / tgt).is_file():
                (cell / tgt).unlink()
                verdict, findings, _ = G.audit_counted(cell)
                assert verdict == "FAIL"
                assert "PROVENANCE_RELOCATION_UNVERIFIED" in \
                    _rules(findings, "ERROR")
                return
    pytest.fail("the published cell carries no verifiable relocation")


# ── the corpus, as the issue asked it be measured ───────────────────────────

def test_the_whole_tracked_corpus_now_agrees_with_the_414_ledger():
    """#434's real complaint: two gates, one corpus, opposite verdicts. The
    census here must reproduce `provenance_declared_output_check`'s split
    of the same 156 declarations — 54 / 12 / 90 / 0 — and no cell may FAIL,
    since every absence in the corpus is disclosed."""
    leds = [_REPO / x for x in subprocess.run(
        ["git", "-C", str(_REPO), "ls-files", "benchmark-data"],
        capture_output=True, text=True).stdout.splitlines()
        if x.endswith("provenance.jsonl")]
    if not leds:
        pytest.skip("benchmark-data not checked out")
    tot = {"declared": 0, "verified_present": 0,
           "verified_relocated": 0, "not_verifiable_here": 0,
           # A record the ledger itself supersedes is ACCOUNTED FOR, in a
           # bucket that is named on the verdict line — it is not an
           # unexplained gap. It belongs in this sum for the same reason
           # `not_verifiable_here` does: the invariant being defended is
           # "no declaration is silently unaccounted for", not "every
           # declaration was hashed against disk".
           "superseded": 0,
           # Same reasoning: a declaration made by an invocation that
           # exited non-zero is ACCOUNTED FOR — named on the verdict line
           # as UNPRODUCED — rather than silently unhashed. Zero across
           # the tracked corpus today; in the sum so that the day one
           # appears, the invariant still reads correctly instead of
           # reporting it as an unexplained gap.
           "unproduced": 0}
    failed = []
    for led in leds:
        verdict, findings, counts = G.audit_counted(led.parent)
        if verdict == "FAIL":
            failed.append((str(led.parent.relative_to(_REPO)),
                           _rules(findings, "ERROR")[:4]))
        for k in tot:
            tot[k] += counts[k]
    assert failed == []
    assert tot["declared"] >= 156, tot
    undisclosed = (tot["declared"] - tot["verified_present"]
                   - tot["verified_relocated"] - tot["not_verifiable_here"]
                   - tot["superseded"] - tot["unproduced"])
    assert undisclosed == 0, tot
