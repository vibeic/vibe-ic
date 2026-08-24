from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _truth


_REPO = HERE.parents[2]
sys.path.insert(0, str(
    _REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "tests"
))
from _hostpaths import require_repo

ROOT = require_repo(".")
RESULT = require_repo(
    "docs", "capture", "2026-08-21-jcap-ppa", "RESULT.md"
).read_text()
EXCLUDED = "324435d94a65f7ef1c8d2b8e4b66407cf778220d"
RESULT_PATH = pathlib.PurePosixPath("docs/capture/2026-08-21-jcap-ppa/RESULT.md")


def _validate(md: str) -> list[str]:
    _, _, checkpoints, errors = _truth.validate_current_claim_counts(md)
    errors.extend(_truth.validate_history_checkpoints(ROOT, RESULT_PATH, checkpoints))
    return errors


def _replace_line(md: str, prefix: str, transform) -> str:
    lines = md.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    assert len(hits) == 1
    lines[hits[0]] = transform(lines[hits[0]])
    return "".join(lines)


def _drop_first_table_row(md: str) -> str:
    return _replace_line(md, "| (smaller) `jsonschema`", lambda _: "")


MUTATIONS = [
    ("title claim number-word", lambda md: md.replace("the twenty-one already-program", "the twenty-two already-program", 1), "title"),
    ("title holding number-word", lambda md: md.replace("of which twenty hold", "of which nineteen hold", 1), "title"),
    ("cross-line introduction claim", lambda md: md.replace("**twenty-one claims\nexamined", "**twenty-two claims\nexamined", 1), "introduction"),
    ("introduction holding number-word", lambda md: md.replace("examined — twenty hold", "examined — nineteen hold", 1), "introduction"),
    ("summary claims", lambda md: md.replace(". 21 ALREADY-PROGRAM claims examined", ". 22 ALREADY-PROGRAM claims examined", 1), "summary"),
    ("summary holding", lambda md: md.replace("claims examined, 20 holding", "claims examined, 19 holding", 1), "summary"),
    ("ladder claims", lambda md: md.replace("| ALREADY-PROGRAM | 21 claims", "| ALREADY-PROGRAM | 22 claims", 1), "ladder"),
    ("ladder holding", lambda md: md.replace("21 claims, **20 hold**", "21 claims, **19 hold**", 1), "ladder"),
    ("finding-table row", _drop_first_table_row, "finding-table introduction"),
    ("disproven row", lambda md: md.replace("DISPROVEN by execution", "DISPROVEN at a checkpoint", 1), "disproven claim rows"),
]


def test_current_pair_is_derived_and_every_surface_agrees():
    pair, surfaces, checkpoints, errors = _truth.validate_current_claim_counts(RESULT)
    errors.extend(_truth.validate_history_checkpoints(ROOT, RESULT_PATH, checkpoints))
    assert not errors
    assert pair is not None
    assert surfaces and all(surface == pair for surface in surfaces.values())


@pytest.mark.parametrize(("name", "mutate", "expected"), MUTATIONS, ids=[x[0] for x in MUTATIONS])
def test_each_count_surface_mutation_is_rejected(name, mutate, expected):
    mutated = mutate(RESULT)
    assert mutated != RESULT, f"mutation did not alter the document: {name}"
    errors = _validate(mutated)
    assert any(expected in error for error in errors), errors


def test_excluded_source_is_the_reverse_control():
    old = subprocess.run(
        ["git", "show", f"{EXCLUDED}:{RESULT_PATH.as_posix()}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    errors = _validate(old)
    for surface in ("introduction", "summary", "ladder"):
        assert any(surface in error for error in errors), errors


def test_old_pair_needs_an_exact_checkpoint_label():
    checkpoint = _truth.strip_labeled_history(RESULT)[1][0]
    inverse = {value: word for word, value in _truth.NUMBER_WORDS.items()}
    historical_surface = (
        "Historical copy, current source of truth: **"
        f"{inverse[checkpoint.pair.claims]} claims\nexamined — "
        f"{inverse[checkpoint.pair.holding]} hold at that checkpoint.**\n"
    )
    unlabelled = RESULT.replace("## Summary", historical_surface + "\n## Summary", 1)
    assert any("introduction" in error for error in _validate(unlabelled))

    marker = (
        "<!-- already-program-history-start "
        f"checkpoint={checkpoint.sha} claims={checkpoint.pair.claims} "
        f"holding={checkpoint.pair.holding} -->\n"
        + historical_surface
        + _truth.HISTORY_END
        + "\n\n"
    )
    labelled = RESULT.replace("## Summary", marker + "## Summary", 1)
    assert not _validate(labelled)


def _run(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: pathlib.Path, message: str) -> str:
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def test_lane_tip_receipt_ignores_other_lane_program_but_catches_ours(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.name", "truth-control")
    _run(repo, "config", "user.email", "truth-control@example.invalid")
    (repo / "README").write_text("base\n")
    base = _commit(repo, "base")

    docs = repo / "docs" / "capture" / "lane"
    docs.mkdir(parents=True)
    (docs / "RESULT.md").write_text("source\n")
    source = _commit(repo, "excluded source")
    (docs / "RESULT.md").write_text("candidate\n")
    candidate = _commit(repo, "truth repair")

    _run(repo, "checkout", "-q", "-b", "other", base)
    other_program = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "other.py"
    other_program.parent.mkdir(parents=True)
    other_program.write_text("OTHER = True\n")
    _commit(repo, "other lane program")
    _run(repo, "merge", "--no-ff", "--no-edit", candidate)
    union = _run(repo, "rev-parse", "HEAD")
    errors, _ = _truth.lane_constraint_errors(
        repo, head=union, lane_tip=candidate, lane_base=base, excluded_source=source,
    )
    assert not errors

    # A squash has the received blobs but not the received commit as ancestor.
    # That is the repository's normal landing shape and must remain provable.
    _run(repo, "checkout", "-q", "-b", "squash", base)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "RESULT.md").write_text("candidate\n")
    squash = _commit(repo, "squash-equivalent landing")
    errors, detail = _truth.lane_constraint_errors(
        repo, head=squash, lane_tip=candidate, lane_base=base,
        excluded_source=source,
    )
    assert not errors, errors
    assert any("squash-equivalent" in item for item in detail), detail

    (docs / "RESULT.md").write_text("mutated after receipt\n")
    harmed_squash = _commit(repo, "harm received content")
    errors, _ = _truth.lane_constraint_errors(
        repo, head=harmed_squash, lane_tip=candidate, lane_base=base,
        excluded_source=source,
    )
    assert any("neither an ancestor nor squash-equivalent" in error
               for error in errors), errors

    _run(repo, "checkout", "-q", "-b", "lane-bad", candidate)
    lane_program = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "lane.py"
    lane_program.parent.mkdir(parents=True)
    lane_program.write_text("LANE = True\n")
    bad_tip = _commit(repo, "lane adds a program")
    errors, _ = _truth.lane_constraint_errors(
        repo, head=bad_tip, lane_tip=bad_tip, lane_base=base, excluded_source=source,
    )
    assert any("program file(s) added by lane" in error for error in errors), errors
