#!/usr/bin/env python3
"""A RESULT.md that cites an audit must publish its provenance-bound input.

THE ORIGINAL DEFECT (vibe-ic#1293). ``benchmark_triage_absorption_audit`` is
deterministic and its verdict depends entirely on the triage JSON passed as its
positional input.  A published machine verdict without that input cannot be
re-run from the repository.

THE SECOND DEFECT.  The first guard froze four paths and one spelling,
``triage_records.json``, from benchmark-data at ``a38902d16``.  Evaluation cells
were subsequently normalized into version/model directories, and a later,
genuine input was published as ``triage-records.json``.  The moving corpus then
contained three citing RESULTs while the frozen inventory named four paths that
no longer cited the audit or existed.  All five load-bearing assertions went
red, including the paired positive control, even though one current record did
ship a genuine input.

THE CONTRACT NOW COMES FROM PUBLISHED EVIDENCE, NOT A MOVABLE PATH SNAPSHOT.
A reproducible citation has one adjacent audit report whose ``path`` identifies
the input basename, and RUN_MANIFEST.json binds both files to their shipped
SHA-256 digests.  Historical records whose original input was never captured
remain explicit ``UNREPRODUCED`` / ``input unpublished`` disclosures; the
residual inventory is derived from exact RESULT blobs whose Git lineage reaches
the published corpus's root snapshot, rather than copied into this test.  A
newly cited RESULT with neither provenance-bound input nor that independently
provable history still fails, even if it copies an old blob and forges an old
``completed_on`` value plus the historical disclosure words.

No plausible triage JSON is authored after the fact.  A loose file beside a
historical RESULT is not proof: without the matching audit report and manifest
digest it remains unproven and is rejected.

chip-AGNOSTIC: this reasons only about publication, provenance and file bytes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import pytest

from _published_corpus import corpus_tree  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]

#: The deliverables are in the external published corpus.  ``corpus_tree`` is
#: intentional: evaluation/ is not a published-cell population, so it remains
#: readable even when the corpus measures zero cells.
_CORPUS = corpus_tree()
EVAL = ((_CORPUS / "evaluation") if _CORPUS is not None
        else REPO / "benchmark-data" / "evaluation")

AUDIT = "benchmark_triage_absorption_audit"
MANIFEST_NAME = "RUN_MANIFEST.json"
REPORT_GLOB = "*triage*absorption*audit*.json"
INPUT_GLOB = "triage*records*.json"


def _all_results() -> list[Path]:
    if not EVAL.is_dir():
        return []
    return sorted(EVAL.rglob("RESULT.md"))


def _text(md: Path) -> str:
    try:
        return md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _citing_records() -> list[Path]:
    return [md for md in _all_results() if AUDIT in _text(md)]


def _rel(md: Path) -> str:
    return str(md.relative_to(EVAL))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name} is not readable JSON: {exc}"
    if not isinstance(raw, dict):
        return None, f"{path.name} is not a JSON object"
    return raw, ""


def _git(root: Path, *args: str) -> Optional[str]:
    """Return Git stdout, or fail closed when history cannot be proved."""
    try:
        completed = subprocess.run(
            ["git", "--no-replace-objects", "-c", f"safe.directory={root}",
             "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _historically_published(md: Path) -> bool:
    """Prove exact content and path lineage from the corpus root snapshot.

    Blob membership alone is insufficient because a later path can copy an old
    RESULT byte-for-byte.  ``git log --follow`` is also insufficient because its
    heuristic may follow such a copy.  Instead, walk backward only through R100
    entries in full-tree diffs until the exact blob and path reach the root tree.
    This binds the exception to repository history without a path or claimed-date
    allowlist.
    """
    root = EVAL.parent.resolve()
    try:
        rel = md.resolve().relative_to(root)
    except (OSError, ValueError):
        return False

    top = _git(root, "rev-parse", "--show-toplevel")
    roots = _git(root, "rev-list", "--max-parents=0", "HEAD")
    if top is None or Path(top).resolve() != root or roots is None:
        return False
    root_commits = roots.splitlines()
    if len(root_commits) != 1:
        return False
    root_commit = root_commits[0]

    rel_name = rel.as_posix()
    blob = _git(root, "hash-object", "--no-filters", "--", rel_name)
    tree = _git(root, "ls-tree", "-r", "--full-tree", root_commit)
    if not blob or tree is None:
        return False
    root_entries: Dict[str, str] = {}
    for line in tree.splitlines():
        header, separator, name = line.partition("\t")
        fields = header.split()
        if separator and len(fields) == 3 and fields[1] == "blob":
            root_entries[name] = fields[2]

    current = rel_name
    tip = "HEAD"
    for _ in range(32):
        additions = _git(
            root, "log", "--no-renames", "--diff-filter=A", "--format=%H",
            tip, "--", current)
        if not additions:
            return False
        introduction = additions.splitlines()[0]
        if introduction == root_commit:
            return root_entries.get(current) == blob
        parents = _git(root, "rev-list", "--parents", "-n", "1", introduction)
        if parents is None:
            return False
        parent_fields = parents.split()
        if len(parent_fields) != 2:
            return False
        changes = _git(
            root,
            "diff-tree",
            "-r",
            "--no-commit-id",
            "--name-status",
            "-M100%",
            parent_fields[1],
            introduction,
        )
        if changes is None:
            return False
        sources = []
        for line in changes.splitlines():
            fields = line.split("\t")
            if len(fields) == 3 and fields[0] == "R100" and fields[2] == current:
                sources.append(fields[1])
        if len(sources) != 1:
            return False
        current = sources[0]
        tip = parent_fields[1]
    return False


def _manifest_digest(manifest: Dict[str, Any], name: str) -> Tuple[Optional[str], str]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return None, "RUN_MANIFEST.json has no artifacts list"
    matches = [entry for entry in artifacts
               if isinstance(entry, dict) and entry.get("path") == name]
    if len(matches) != 1:
        return None, (f"RUN_MANIFEST.json names {len(matches)} artifacts called "
                      f"{name!r}, expected exactly one")
    digest = matches[0].get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return None, f"RUN_MANIFEST.json has no SHA-256 for {name}"
    return digest.lower(), ""


def _input_candidates(md: Path) -> list[Path]:
    return sorted(path for path in md.parent.glob(INPUT_GLOB) if path.is_file())


def _input_evidence(md: Path) -> Tuple[Optional[Dict[str, str]], str]:
    """Return the exact shipped input/report digests, or why they are unproven.

    The stored audit report owns the input filename.  This deliberately does
    not assume underscore or hyphen spelling, and deliberately does not credit
    an unmanifested file dropped beside an old result after publication.
    """
    reports = []
    malformed = []
    for report_path in sorted(md.parent.glob(REPORT_GLOB)):
        report, reason = _load_object(report_path)
        if report is None:
            malformed.append(reason)
        elif report.get("program") == AUDIT:
            reports.append((report_path, report))
    if malformed:
        return None, "; ".join(malformed)
    if len(reports) != 1:
        return None, (f"found {len(reports)} adjacent {AUDIT} report(s), "
                      "expected exactly one")

    report_path, report = reports[0]
    recorded_input = report.get("path")
    if not isinstance(recorded_input, str) or not recorded_input.strip():
        return None, f"{report_path.name} does not identify its input path"
    input_name = Path(recorded_input).name
    if input_name in ("", ".", ".."):
        return None, f"{report_path.name} has an invalid input basename"
    input_path = md.parent / input_name
    if not input_path.is_file():
        return None, (f"{report_path.name} names {input_name}, but it is not "
                      "published beside RESULT.md")

    manifest_path = md.parent / MANIFEST_NAME
    manifest, reason = _load_object(manifest_path)
    if manifest is None:
        return None, reason
    input_recorded_sha, reason = _manifest_digest(manifest, input_name)
    if input_recorded_sha is None:
        return None, reason
    report_recorded_sha, reason = _manifest_digest(manifest, report_path.name)
    if report_recorded_sha is None:
        return None, reason

    input_sha = _sha256(input_path)
    report_sha = _sha256(report_path)
    if input_sha != input_recorded_sha:
        return None, (f"{input_name} SHA-256 is {input_sha}, but the manifest "
                      f"records {input_recorded_sha}")
    if report_sha != report_recorded_sha:
        return None, (f"{report_path.name} SHA-256 is {report_sha}, but the "
                      f"manifest records {report_recorded_sha}")
    return {
        "input": input_name,
        "input_sha256": input_sha,
        "report": report_path.name,
        "report_sha256": report_sha,
    }, ""


def _explicitly_unreproduced(md: Path) -> bool:
    """Exact repository history, not a path list or claimed date, owns debt."""
    text = _text(md)
    lower = text.lower()
    if not ("vibe-ic#1293" in text and "UNREPRODUCED" in text
            and "input unpublished" in lower):
        return False
    manifest, _ = _load_object(md.parent / MANIFEST_NAME)
    if manifest is None:
        return False
    limitations = manifest.get("limitations")
    augmented = (isinstance(limitations, list)
                 and any(isinstance(item, str)
                         and "augmented with an evidence re-verifiability note"
                         in item for item in limitations))
    return augmented and _historically_published(md)


def _unverifiable_inventory() -> frozenset[str]:
    return frozenset(_rel(md) for md in _all_results()
                     if _explicitly_unreproduced(md))


def _evidence_map(citing: Iterable[Path]) -> Tuple[Dict[str, Dict[str, str]],
                                                    Dict[str, str]]:
    proven: Dict[str, Dict[str, str]] = {}
    unproven: Dict[str, str] = {}
    for md in citing:
        evidence, reason = _input_evidence(md)
        if evidence is None:
            unproven[_rel(md)] = reason
        else:
            proven[_rel(md)] = evidence
    return proven, unproven


def _assert_no_new(citing: Iterable[Path], inventory: frozenset[str]) -> None:
    _, unproven = _evidence_map(citing)
    unexpected = sorted(set(unproven) - set(inventory))
    assert not unexpected, (
        f"{len(unexpected)} published record(s) cite {AUDIT} as evidence "
        "without a provenance-bound shipped input: "
        f"{[(path, unproven[path]) for path in unexpected]}. Publish the "
        "original input and bind it through the audit report plus "
        f"{MANIFEST_NAME}; do NOT author one after the fact.")


def _assert_inventory_live(citing: Iterable[Path],
                           inventory: frozenset[str]) -> None:
    live = {_rel(md) for md in citing}
    phantom = sorted(set(inventory) - live)
    assert not phantom, (
        "the explicit UNREPRODUCED inventory names records that do not cite "
        f"{AUDIT} (or do not exist): {phantom}")


@pytest.fixture(scope="module")
def citing() -> list[Path]:
    records = _citing_records()
    if not records:
        pytest.skip(f"no RESULT.md under {EVAL} cites {AUDIT}")
    return records


@pytest.fixture(scope="module")
def inventory() -> frozenset[str]:
    return _unverifiable_inventory()


def test_the_population_is_not_empty(citing):
    """NON-VACUITY. Every assertion below is over this set."""
    assert len(citing) >= 2, [_rel(md) for md in citing]


def test_no_NEW_citation_ships_without_its_input(citing, inventory):
    """A new citation needs a report+manifest-bound input, not an exception."""
    _assert_no_new(citing, inventory)


def test_the_inventory_cannot_keep_claiming_a_defect_that_is_FIXED(
        citing, inventory):
    """A recovered input removes the disclosure; a loose input proves nothing."""
    by_rel = {_rel(md): md for md in citing}
    fixed = []
    post_hoc = []
    for rel in sorted(inventory):
        md = by_rel.get(rel)
        if md is None:
            continue
        evidence, _ = _input_evidence(md)
        if evidence is not None:
            fixed.append(rel)
        elif _input_candidates(md):
            post_hoc.append(rel)
    assert not fixed, (
        "these records now ship provenance-bound inputs and must remove their "
        f"UNREPRODUCED disclosure: {fixed}")
    assert not post_hoc, (
        "these historical records gained triage-looking files without the "
        "original audit-report plus manifest provenance; they remain "
        f"unverifiable and the loose files must not be credited: {post_hoc}")


def test_the_inventory_names_records_that_actually_exist(citing, inventory):
    """Every explicit residual must still be a live citation."""
    _assert_inventory_live(citing, inventory)


def test_PAIRED_at_least_one_citation_DOES_ship_its_input(citing):
    """The requirement is demonstrated by genuine, digest-bound evidence."""
    proven, _ = _evidence_map(citing)
    print(f"\n[{AUDIT}] provenance-bound inputs: {proven}")
    assert proven, (
        "no citation ships a report+manifest-bound input, so the requirement "
        "has never been met and this test cannot show it is meetable")


def test_the_residual_is_PUBLISHED_not_merely_tolerated(citing, inventory):
    """Print every genuine input digest and every explicit residual."""
    proven, unproven = _evidence_map(citing)
    missing = frozenset(unproven)
    print(f"\n[{AUDIT}] {len(proven) + len(unproven)} citing record(s); "
          f"{len(proven)} provenance-bound input(s): {proven}; "
          f"{len(missing)} explicitly UNREPRODUCED: {sorted(missing)}")
    assert inventory == missing, (inventory, missing, unproven)


def test_NEGATIVE_control_a_new_citation_without_input_is_rejected(
        tmp_path, monkeypatch):
    """A fresh citation with no input and no historical proof is rejected."""
    evaluation = tmp_path / "evaluation"
    md = evaluation / "new_run" / "RESULT.md"
    md.parent.mkdir(parents=True)
    md.write_text(
        f"# New result\n\n{AUDIT} PASS\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "EVAL", evaluation)
    records = _citing_records()
    with pytest.raises(AssertionError, match="new_run/RESULT.md"):
        _assert_no_new(records, _unverifiable_inventory())


def test_NEGATIVE_control_a_forged_old_date_cannot_grandfather_a_fresh_path(
        tmp_path, monkeypatch):
    """A fresh path cannot forge an old date, even by copying an old blob."""
    corpus = tmp_path / "corpus"
    evaluation = corpus / "evaluation"
    legacy = evaluation / "legacy_run" / "RESULT.md"
    legacy.parent.mkdir(parents=True)
    result_text = (
        f"# New result\n\n{AUDIT} PASS\n\n"
        "vibe-ic#1293: UNREPRODUCED, input unpublished.\n")
    forged_manifest = json.dumps({
        "completed_on": "2000-01-01",
        "limitations": [
            "RESULT.md was augmented with an evidence re-verifiability note."],
        "artifacts": [],
    })
    legacy.write_text(result_text, encoding="utf-8")
    (legacy.parent / MANIFEST_NAME).write_text(
        forged_manifest, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(corpus)], check=True)
    subprocess.run(["git", "-C", str(corpus), "add", "."], check=True)
    subprocess.run([
        "git", "-c", "user.name=Vibe IC Test",
        "-c", "user.email=test@vibeic.invalid", "-C", str(corpus),
        "commit", "-q", "-m", "root published snapshot",
    ], check=True)

    md = evaluation / "new_run" / "RESULT.md"
    md.parent.mkdir(parents=True)
    md.write_text(result_text, encoding="utf-8")
    (md.parent / MANIFEST_NAME).write_text(
        forged_manifest, encoding="utf-8")
    subprocess.run(["git", "-C", str(corpus), "add", "."], check=True)
    subprocess.run([
        "git", "-c", "user.name=Vibe IC Test",
        "-c", "user.email=test@vibeic.invalid", "-C", str(corpus),
        "commit", "-q", "-m", "fresh path with forged completed_on",
    ], check=True)

    monkeypatch.setattr(sys.modules[__name__], "EVAL", evaluation)
    assert _explicitly_unreproduced(legacy)
    assert not _explicitly_unreproduced(md)
    records = _citing_records()
    with pytest.raises(AssertionError, match="new_run/RESULT.md"):
        _assert_no_new(records, _unverifiable_inventory())


def test_NEGATIVE_control_a_readded_root_path_is_not_historical(
        tmp_path, monkeypatch):
    """Moving a legacy result cannot grandfather a later duplicate."""
    corpus = tmp_path / "corpus"
    evaluation = corpus / "evaluation"
    legacy = evaluation / "legacy_run"
    legacy.mkdir(parents=True)
    result_text = (
        f"# Legacy result\n\n{AUDIT} PASS\n\n"
        "vibe-ic#1293: UNREPRODUCED, input unpublished.\n")
    forged_manifest = json.dumps({
        "completed_on": "2000-01-01",
        "limitations": [
            "RESULT.md was augmented with an evidence re-verifiability note."],
        "artifacts": [],
    })
    (legacy / "RESULT.md").write_text(result_text, encoding="utf-8")
    (legacy / MANIFEST_NAME).write_text(forged_manifest, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(corpus)], check=True)
    subprocess.run(["git", "-C", str(corpus), "add", "."], check=True)
    subprocess.run([
        "git", "-c", "user.name=Vibe IC Test",
        "-c", "user.email=test@vibeic.invalid", "-C", str(corpus),
        "commit", "-q", "-m", "root published snapshot",
    ], check=True)

    subprocess.run([
        "git", "-C", str(corpus), "mv", "evaluation/legacy_run",
        "evaluation/moved_run",
    ], check=True)
    subprocess.run([
        "git", "-c", "user.name=Vibe IC Test",
        "-c", "user.email=test@vibeic.invalid", "-C", str(corpus),
        "commit", "-q", "-m", "move legacy result",
    ], check=True)
    legacy.mkdir(parents=True)
    readded = legacy / "RESULT.md"
    readded.write_text(result_text, encoding="utf-8")
    (legacy / MANIFEST_NAME).write_text(forged_manifest, encoding="utf-8")
    subprocess.run(["git", "-C", str(corpus), "add", "."], check=True)
    subprocess.run([
        "git", "-c", "user.name=Vibe IC Test",
        "-c", "user.email=test@vibeic.invalid", "-C", str(corpus),
        "commit", "-q", "-m", "re-add old path as a fresh duplicate",
    ], check=True)

    moved = evaluation / "moved_run" / "RESULT.md"
    monkeypatch.setattr(sys.modules[__name__], "EVAL", evaluation)
    assert _explicitly_unreproduced(moved)
    assert not _explicitly_unreproduced(readded)
    records = _citing_records()
    with pytest.raises(AssertionError, match="legacy_run/RESULT.md"):
        _assert_no_new(records, _unverifiable_inventory())


def test_NEGATIVE_control_a_phantom_inventory_path_is_rejected(
        citing, inventory):
    """The old stale-path failure remains observable after removing literals."""
    poisoned = inventory | {"phantom/removed/RESULT.md"}
    with pytest.raises(AssertionError, match="phantom/removed/RESULT.md"):
        _assert_inventory_live(citing, poisoned)
