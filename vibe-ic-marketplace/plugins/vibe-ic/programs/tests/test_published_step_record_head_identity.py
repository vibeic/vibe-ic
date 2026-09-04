"""A tracked publisher STEP_RECORD is evidence only for its exact HEAD blob."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import test_matrix_d3_outputs_produced as D3


STEP = "30"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _source_record():
    for label, rr in D3.run_roots().items():
        for path in sorted((rr.path / "steps").rglob(D3._bep._STEP_RECORD_FILENAME)):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rel = path.relative_to(rr.path).as_posix()
            if str(doc.get("id")) == STEP and D3.is_tracked(rr.path, rel):
                return label, path, rel, doc
    pytest.skip("the offered published corpus carries no tracked Step-30 record")


@pytest.fixture
def record_repo(tmp_path, monkeypatch):
    source_label, source, rel, doc = _source_record()
    root = tmp_path / "published-cell"
    target = root / rel
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)
    _git(root, "init", "-q")
    _git(root, "add", rel)
    _git(root, "-c", "user.name=matrix-control", "-c",
         "user.email=matrix-control.invalid", "commit", "-qm", "real record")
    D3.tracked_under.cache_clear()
    D3._head_record_blob.cache_clear()
    monkeypatch.setattr(
        D3, "run_roots",
        lambda: {source_label: D3.RunRoot(source_label, "published", root)})
    monkeypatch.setattr(D3, "_is_published_cell", lambda _path: True)
    # This fixture grades one thing: whether mutable worktree bytes can answer
    # for the committed STEP_RECORD blob.  Step 30 also has two unrelated
    # manifest citations whose registered run root is deliberately
    # unreachable and therefore makes the real cell NOT_MEASURED.  Holding
    # that independent axis fixed keeps the positive control positive while
    # every byte-binding negative control below still exercises the shipped
    # record reader.
    monkeypatch.setattr(D3, "unanswerable_citations", lambda _step: ())
    yield root, target, rel, doc
    D3.tracked_under.cache_clear()
    D3._head_record_blob.cache_clear()


def _invented_pass(doc: dict) -> bytes:
    made = dict(doc)
    made["status"] = "pass"
    made["declared_outputs"] = [
        {"rel": "phase3/stage3/spice/fabricated.sp", "symlink": False,
         "bytes": 99, "sha256": "1" * 64, "in_cell": False,
         "decision": D3._RECORDED_UNPUBLISHED},
        {"rel": "reports/phase3/spice_correlation.json", "symlink": False,
         "bytes": 88, "sha256": "2" * 64, "in_cell": False,
         "decision": D3._RECORDED_UNPUBLISHED},
    ]
    return (json.dumps(made, indent=2) + "\n").encode()


def _assert_not_enforced() -> None:
    observed_hits = [
        D3.recorded_unpublished_output(STEP, entry).hit is not None
        for entry in D3.F.required_outputs(STEP)
    ]
    assert observed_hits == [False, False], (
        "mutable record bytes changed the two concrete required-output "
        f"answers: observed_hits={observed_hits}")
    missing, details = D3.audit_step(STEP)
    assert missing, (
        "mutable or absent record bytes still produced a green D3 predicate: "
        + repr(details))
    # `ENFORCED` is the matrix execution state, not a PASS verdict.  This
    # fixture intentionally holds the unrelated unanswerable-citation axis
    # empty; the assertion above proves the active predicate rejects the bad
    # record instead of relabelling that rejection NOT_MEASURED.
    assert D3.matrix_not_measured_reason(STEP) is None
    assert D3.matrix_cell_state(STEP) == "ENFORCED"


def test_exact_committed_record_bytes_are_the_positive_control(record_repo):
    root, target, rel, doc = record_repo
    target.write_bytes(_invented_pass(doc))
    _git(root, "add", rel)
    _git(root, "-c", "user.name=matrix-control", "-c",
         "user.email=matrix-control.invalid", "commit", "-qm", "bound pass")
    D3._head_record_blob.cache_clear()
    for entry in D3.F.required_outputs(STEP):
        assert D3.recorded_unpublished_output(STEP, entry).hit is not None
    assert D3.matrix_not_measured_reason(STEP) is None
    assert D3.matrix_cell_state(STEP) == "ENFORCED"


def test_modified_record_bytes_are_rejected(record_repo):
    _root, target, _rel, _doc = record_repo
    target.write_bytes(target.read_bytes() + b"\n")
    _assert_not_enforced()
    found = D3.recorded_unpublished_output(STEP, next(iter(D3.F.required_outputs(STEP))))
    assert any("differ from the exact HEAD blob" in r for r in found.rejected)


def test_deleted_record_bytes_are_rejected(record_repo):
    _root, target, _rel, _doc = record_repo
    target.unlink()
    _assert_not_enforced()


def test_symlinked_record_bytes_are_rejected(record_repo):
    root, target, _rel, doc = record_repo
    replacement = root / "replacement.json"
    replacement.write_bytes(_invented_pass(doc))
    target.unlink()
    target.symlink_to(os.path.relpath(replacement, target.parent))
    _assert_not_enforced()
    found = D3.recorded_unpublished_output(STEP, next(iter(D3.F.required_outputs(STEP))))
    assert any("symlink" in r for r in found.rejected)


def test_malformed_record_bytes_are_rejected(record_repo):
    _root, target, _rel, _doc = record_repo
    target.write_bytes(b"{")
    _assert_not_enforced()


def test_invented_pass_worktree_bytes_are_rejected(record_repo):
    _root, target, _rel, doc = record_repo
    target.write_bytes(_invented_pass(doc))
    _assert_not_enforced()


def test_in_memory_record_substitution_is_rejected(record_repo):
    _root, target, _rel, doc = record_repo
    original = Path.read_bytes

    def substituted(self):
        if self == target:
            return _invented_pass(doc)
        return original(self)

    with mock.patch.object(Path, "read_bytes", substituted):
        _assert_not_enforced()
