"""tests/test_provenance_superseded_declaration.py

A PRODUCING provenance entry that re-writes an artefact a previous entry
already declared carries `supersedes` as a DICT {"timestamp", "tool"} naming
the record it replaces (written by `phase3_one_shot_runner`, whose own comment
states the contract: "A superseding record says so, so a reader is never left
to guess which of two entries for one path is current").

`provenance_output_hash_completeness_check` did not implement that reader. Its
only supersede handling is `_removal_list`, which requires a removal marker in
`op`/`type`/`event` and reads `supersedes` only when it is a LIST — neither of
which a producing entry carries. So every legitimate re-run of a step that
re-writes a declared artefact — the normal close-loop case — faulted twice, on
ledger HISTORY rather than on any live claim:

    PROVENANCE_HASH_MISMATCH      the stale entry's digest != the file
    PROVENANCE_HASH_INCONSISTENT  the two entries disagree

BIDIRECTIONAL NEGATIVE CONTROL. `test_superseded_declaration_is_history`
FAILs against the byte-identical pre-fix file and PASSes after. Every other
test here is a REVERSE case that must STILL FAIL after the fix — they are the
guard against the failure mode of a fix in this file, which is not "too
strict" but silencing the real defect underneath by widening the exemption
until the fault count reaches zero.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from programs.provenance_output_hash_completeness_check import audit

REL = "reports/phase3/signoff.rpt"
OLD_TS = "2026-05-08T12:21:20Z"
NEW_TS = "2026-05-08T18:09:55Z"
TOOL = "somedrc"


def _write(project: Path, rel: str, body: bytes) -> str:
    dst = project / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(body)
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _sha_of(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _make(project: Path, entries: list) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "provenance.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n")


def _rules(findings) -> set:
    return {f.rule for f in findings}


def _entry(ts, outputs, supersedes=None, tool=TOOL):
    e = {"timestamp": ts, "tool": tool, "exit_code": 0, "outputs": outputs}
    if supersedes is not None:
        e["supersedes"] = supersedes
    return e


# ---------------------------------------------------------------- forward

def test_superseded_declaration_is_history(tmp_path: Path) -> None:
    """THE FIX. A re-run re-wrote the artefact and disclosed what it replaced.
    The file on disk matches the LIVE (superseding) digest. Pre-fix this is
    two ERRORs; post-fix it is PASS with the stale row disclosed, not silent.
    """
    p = tmp_path / "proj"
    new_sha = _write(p, REL, b"second run of the deck\n" + b"B" * 300)
    stale_sha = _sha_of(b"first run of the deck\n" + b"A" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: stale_sha}),
        _entry(NEW_TS, {REL: new_sha},
               supersedes={"timestamp": OLD_TS, "tool": TOOL}),
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS", [(f.rule, f.detail) for f in findings]
    assert "PROVENANCE_HASH_MISMATCH" not in _rules(findings)
    assert "PROVENANCE_HASH_INCONSISTENT" not in _rules(findings)
    # Disclosed, never silent — and it points at the STALE row (index 0).
    sup = [f for f in findings
           if f.rule == "PROVENANCE_DECLARATION_SUPERSEDED"]
    assert len(sup) == 1, [(f.rule, f.detail) for f in findings]
    assert sup[0].severity == "DISCLOSED"
    assert sup[0].entry_index == 0


# ---------------------------------------------------------------- reverse

def test_live_digest_still_verified_against_disk(tmp_path: Path) -> None:
    """REVERSE. The superseding entry is the LIVE claim. If IT disagrees with
    the file on disk that is a genuine fault and must still FAIL — this is the
    check's whole purpose and the exemption must never reach it."""
    p = tmp_path / "proj"
    _write(p, REL, b"what is actually on disk\n" + b"C" * 300)
    stale_sha = _sha_of(b"first run\n" + b"A" * 300)
    wrong_live_sha = _sha_of(b"NOT what is on disk\n" + b"D" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: stale_sha}),
        _entry(NEW_TS, {REL: wrong_live_sha},
               supersedes={"timestamp": OLD_TS, "tool": TOOL}),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_MISMATCH" in _rules(findings)


def test_undisclosed_rewrite_still_inconsistent(tmp_path: Path) -> None:
    """REVERSE. Two entries disagree on one path and NOTHING discloses that
    one replaced the other. That is the defect PROVENANCE_HASH_INCONSISTENT
    exists to catch — an undisclosed rewrite — and it must still FAIL."""
    p = tmp_path / "proj"
    new_sha = _write(p, REL, b"second run\n" + b"B" * 300)
    stale_sha = _sha_of(b"first run\n" + b"A" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: stale_sha}),
        _entry(NEW_TS, {REL: new_sha}),          # no `supersedes`
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_INCONSISTENT" in _rules(findings)


def test_supersedes_resolving_to_nothing_grants_no_exemption(
        tmp_path: Path) -> None:
    """REVERSE. A `supersedes` that names no earlier entry is not a
    disclosure about anything. It must not become a blanket silencer."""
    p = tmp_path / "proj"
    new_sha = _write(p, REL, b"second run\n" + b"B" * 300)
    stale_sha = _sha_of(b"first run\n" + b"A" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: stale_sha}),
        _entry(NEW_TS, {REL: new_sha},
               supersedes={"timestamp": "2020-01-01T00:00:00Z",
                           "tool": "never-ran"}),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_INCONSISTENT" in _rules(findings)
    assert "PROVENANCE_DECLARATION_SUPERSEDED" not in _rules(findings)


def test_forward_reference_grants_no_exemption(tmp_path: Path) -> None:
    """REVERSE. The ledger is append-only. An EARLIER entry claiming to
    supersede a LATER one cannot retroactively silence it."""
    p = tmp_path / "proj"
    _write(p, REL, b"on disk\n" + b"C" * 300)
    sha_a = _sha_of(b"run a\n" + b"A" * 300)
    sha_b = _sha_of(b"run b\n" + b"B" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: sha_a},
               supersedes={"timestamp": NEW_TS, "tool": TOOL}),  # forward
        _entry(NEW_TS, {REL: sha_b}),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_DECLARATION_SUPERSEDED" not in _rules(findings)


def test_exemption_is_per_path_not_per_entry(tmp_path: Path) -> None:
    """REVERSE. The superseding entry re-declares ONE of the two paths the
    old entry declared. The path it did NOT re-declare is still a live claim
    and its absence from disk must still FAIL — the exemption must not
    swallow the whole row."""
    p = tmp_path / "proj"
    other = "reports/phase3/other.rpt"
    new_sha = _write(p, REL, b"second run\n" + b"B" * 300)
    stale_sha = _sha_of(b"first run\n" + b"A" * 300)
    other_sha = _sha_of(b"never written to disk\n" + b"E" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: stale_sha, other: other_sha}),
        _entry(NEW_TS, {REL: new_sha},
               supersedes={"timestamp": OLD_TS, "tool": TOOL}),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_OUTPUT_FILE_MISSING" in _rules(findings)
    # ...while the re-declared path IS correctly treated as history.
    sup = [f for f in findings
           if f.rule == "PROVENANCE_DECLARATION_SUPERSEDED"]
    assert len(sup) == 1 and REL in sup[0].detail


def test_non_dict_supersedes_grants_no_exemption(tmp_path: Path) -> None:
    """REVERSE. Only the writer's DICT shape counts. A bare truthy marker is
    not the disclosure and must not be read as one."""
    p = tmp_path / "proj"
    new_sha = _write(p, REL, b"second run\n" + b"B" * 300)
    stale_sha = _sha_of(b"first run\n" + b"A" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: stale_sha}),
        _entry(NEW_TS, {REL: new_sha}, supersedes=True),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_DECLARATION_SUPERSEDED" not in _rules(findings)


def test_superseded_row_with_malformed_digest_still_faults(
        tmp_path: Path) -> None:
    """REVERSE. Being history exempts a row from the ON-DISK comparison only.
    A record that is not a well-formed sha256 claim is malformed regardless of
    whether it was later replaced."""
    p = tmp_path / "proj"
    new_sha = _write(p, REL, b"second run\n" + b"B" * 300)
    _make(p, [
        _entry(OLD_TS, {REL: "not-a-digest"}),
        _entry(NEW_TS, {REL: new_sha},
               supersedes={"timestamp": OLD_TS, "tool": TOOL}),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert "PROVENANCE_HASH_SHAPE_INVALID" in _rules(findings)
