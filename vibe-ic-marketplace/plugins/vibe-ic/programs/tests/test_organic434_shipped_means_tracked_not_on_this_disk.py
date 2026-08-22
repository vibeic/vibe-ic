#!/usr/bin/env python3
"""Found by the gatekeeper while landing #434, on the very corpus the change
was measured against.

#434 taught the gate a third outcome: an absent output whose ledger discloses
why is DISCLOSED, not an ERROR. It answered "is this output present?" by
asking the LOCAL DISK. But the question the disclosure answers is "does this
deliverable SHIP it?", and shipped-ness is a property of the published tree —
which is what git tracks.

MEASURED over the 21 tracked ledgers: 37 declared outputs exist on disk while
being UNTRACKED. They are leftover run artefacts on the author's machine; a
reader who clones this repository never receives them. Their presence turned
three cells' honest `not shipped` disclosures into PROVENANCE_PRUNE_CONTRADICTED
("the disclosure is false") — about files that genuinely are not shipped.

So the SAME commit gave two verdicts: PASS in a fresh git worktree, which
materialises tracked files only, and FAIL in a working checkout that still had
the run's leftovers. That is how it reached the merge queue reported as
"21/21 PASS": the author measured in a worktree. A gate whose verdict depends
on untracked leftovers is not measuring the artefact, it is measuring the
machine.

THE DISCRIMINATOR IS THE LEDGER ITSELF. A deliverable is published exactly when
its own `provenance.jsonl` is in the published tree; then shipped means tracked.
A raw run directory — outside a repository, or inside one and not committed —
has published nothing, so the question does not apply and presence on disk
remains the answer. That keeps `--require-outputs-present` and every run-dir
use of this gate working unchanged.

The direction matters: this must never make the gate quieter about bytes a
reader DOES receive. Tampering a TRACKED file is still PROVENANCE_HASH_MISMATCH,
verified here and re-verified by the gatekeeper on the real spm cell before
landing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import provenance_output_hash_completeness_check as G  # noqa: E402

_SHA_EMPTYISH = None  # computed per test


def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _cell(tmp_path: Path, *, in_repo: bool, track_ledger: bool,
          track_output: bool) -> Path:
    """Build a one-output deliverable whose ledger says the output was pruned
    at publish, while the file is present on disk."""
    root = tmp_path / "cell"
    (root / "phase2").mkdir(parents=True)
    out = root / "phase2" / "netlist.v"
    out.write_text("module m; endmodule\n")
    (root / "provenance.jsonl").write_text(json.dumps({
        "tool": "yosys",
        "outputs": {"phase2/netlist.v": f"sha256:{_sha(out)}"},
        "outputs_pruned_at_publish": ["phase2/netlist.v"],
        "outputs_pruned_reason": "NOT SHIPPED — size policy",
    }) + "\n")
    if not in_repo:
        return root
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    add = []
    if track_ledger:
        add.append("provenance.jsonl")
    if track_output:
        add.append("phase2/netlist.v")
    if add:
        subprocess.run(["git", "-C", str(root), "add", *add], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "publish"],
                       check=True)
    return root


#: Severity order for the failure MESSAGE. The verdict already knows which
#: finding drove it; the message did not. `audit_counted` returns findings in
#: entry order, and DISCLOSED rows outnumber ERRORs heavily on a real cell —
#: `ic/spm/v1.10.18_sky130A` reports 33 DISCLOSED to 1 ERROR — so a caller that
#: truncates the list prints four rules NONE of which is the cause. The single
#: ERROR there (`PROVENANCE_PRUNE_CONTRADICTED`) never appeared at all.
_SEVERITY_FIRST = {"ERROR": 0, "WARN": 1, "DISCLOSED": 2}


def _rules(findings) -> list[str]:
    """Rule names, ERRORs first — a truncated message must not hide the cause."""
    return [f.rule for f in sorted(
        findings, key=lambda f: _SEVERITY_FIRST.get(f.severity, 3))]


def test_an_untracked_leftover_does_not_falsify_a_not_shipped_disclosure(
        tmp_path):
    """THE LOAD-BEARING CASE — the three real cells, reduced."""
    root = _cell(tmp_path, in_repo=True, track_ledger=True, track_output=False)
    verdict, findings, counts = G.audit_counted(root)
    assert verdict == "PASS", _rules(findings)
    assert "PROVENANCE_PRUNE_CONTRADICTED" not in _rules(findings)
    assert counts["not_verifiable_here"] == 1
    assert counts["verified_present"] == 0


def test_the_skipped_file_is_disclosed_not_silently_ignored(tmp_path):
    """A file sitting right there that the gate deliberately does not verify is
    a decision, and a decision that leaves no trace is the failure this whole
    issue is about."""
    root = _cell(tmp_path, in_repo=True, track_ledger=True, track_output=False)
    _, findings, _ = G.audit_counted(root)
    assert "PROVENANCE_OUTPUT_PRESENT_BUT_UNTRACKED" in _rules(findings)
    f = next(x for x in findings
             if x.rule == "PROVENANCE_OUTPUT_PRESENT_BUT_UNTRACKED")
    assert f.severity == "DISCLOSED", f.severity


def test_a_TRACKED_file_still_contradicts_a_not_shipped_disclosure(tmp_path):
    """The paired half, and the one that keeps #434's anti-gaming property:
    when the file really IS shipped, saying it is not is still provably false."""
    root = _cell(tmp_path, in_repo=True, track_ledger=True, track_output=True)
    verdict, findings, _ = G.audit_counted(root)
    assert verdict == "FAIL"
    assert "PROVENANCE_PRUNE_CONTRADICTED" in _rules(findings)


def test_a_tracked_output_that_was_tampered_is_still_a_MISMATCH(tmp_path):
    """The direction that must never get quieter: a reader's bytes."""
    root = _cell(tmp_path, in_repo=True, track_ledger=True, track_output=True)
    (root / "phase2" / "netlist.v").write_text("module m; wire x; endmodule\n")
    verdict, findings, _ = G.audit_counted(root)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_MISMATCH" in _rules(findings)


def test_a_raw_run_directory_outside_git_still_uses_the_disk(tmp_path):
    """Nothing has been published, so tracked-ness is not the question and the
    disk is still the honest answer — the disclosure is contradicted."""
    root = _cell(tmp_path, in_repo=False, track_ledger=False,
                 track_output=False)
    assert G._published_paths(root) is None
    verdict, findings, _ = G.audit_counted(root)
    assert verdict == "FAIL"
    assert "PROVENANCE_PRUNE_CONTRADICTED" in _rules(findings)


def test_a_repo_whose_ledger_is_NOT_committed_is_not_a_published_deliverable(
        tmp_path):
    """The discriminator, tested directly. A run directory that happens to sit
    inside a repository has published nothing; treating its empty tracked set
    as 'ships nothing' would flip every present file to absent."""
    root = _cell(tmp_path, in_repo=True, track_ledger=False,
                 track_output=False)
    assert G._published_paths(root) is None
    verdict, findings, _ = G.audit_counted(root)
    assert verdict == "FAIL"
    assert "PROVENANCE_PRUNE_CONTRADICTED" in _rules(findings)


def test_the_real_tracked_corpus_is_clean_and_not_vacuously_so():
    """Repo-level, and both halves matter: 21/21 PASS, AND the census still
    reports real on-disk verifications — a corpus that verified nothing would
    also be 'clean'."""
    import pytest
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True,
                          cwd=str(_PROGRAMS)).stdout.strip()
    if not repo:
        pytest.skip("not in a git repo")
    root = Path(repo)
    leds = [x for x in subprocess.run(
        ["git", "-C", repo, "ls-files", "benchmark-data"],
        capture_output=True, text=True).stdout.splitlines()
        if x.endswith("provenance.jsonl")]
    if not leds:
        pytest.skip("benchmark-data not checked out")
    failed, verified = [], 0
    for led in leds:
        v, f, c = G.audit_counted(root / Path(led).parent)
        if v == "FAIL":
            failed.append((led, _rules(f)[:4]))
        verified += c["verified_present"] + c["verified_relocated"]
    assert failed == [], failed
    assert verified > 0, "clean but vacuous: nothing was actually verified"


def test_a_present_but_untracked_output_is_never_called_absent(tmp_path):
    """Found by the #438 triage, in the fix for #434 itself.

    An untracked-but-present declared output with no disclosure produced BOTH
    `PROVENANCE_OUTPUT_PRESENT_BUT_UNTRACKED` ("is on this disk") and
    `PROVENANCE_OUTPUT_FILE_MISSING` ("does not exist on disk") — two
    contradictory verdicts on one row, which is the exact complaint #434 was
    filed about, reproduced by its own repair.

    The VERDICT was never wrong: this is a real fault, and it stays fatal. Only
    the REASON was false, and a false reason sends the reader to look for a
    file that is sitting in front of them.
    """
    root = _cell(tmp_path, in_repo=True, track_ledger=True, track_output=False)
    # strip the disclosure so nothing accounts for the absence
    led = root / "provenance.jsonl"
    rec = json.loads(led.read_text().strip())
    rec.pop("outputs_pruned_at_publish", None)
    rec.pop("outputs_pruned_reason", None)
    led.write_text(json.dumps(rec) + "\n")

    verdict, findings, _ = G.audit_counted(root)
    assert verdict == "FAIL"
    rules = _rules(findings)
    assert "PROVENANCE_OUTPUT_NOT_SHIPPED_UNDISCLOSED" in rules, rules
    assert "PROVENANCE_OUTPUT_FILE_MISSING" not in rules, rules
    detail = next(f.detail for f in findings
                  if f.rule == "PROVENANCE_OUTPUT_NOT_SHIPPED_UNDISCLOSED")
    assert "does not exist on disk" not in detail


def test_a_genuinely_absent_output_still_says_FILE_MISSING(tmp_path):
    """The paired half. Renaming every absence would lose the distinction
    between 'never written' and 'written and not shipped', which are different
    repairs."""
    root = _cell(tmp_path, in_repo=True, track_ledger=True, track_output=False)
    (root / "phase2" / "netlist.v").unlink()
    led = root / "provenance.jsonl"
    rec = json.loads(led.read_text().strip())
    rec.pop("outputs_pruned_at_publish", None)
    rec.pop("outputs_pruned_reason", None)
    led.write_text(json.dumps(rec) + "\n")

    verdict, findings, _ = G.audit_counted(root)
    assert verdict == "FAIL"
    assert "PROVENANCE_OUTPUT_FILE_MISSING" in _rules(findings)
