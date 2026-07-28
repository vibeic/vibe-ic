#!/usr/bin/env python3
"""vibe-ic#518 — a provenance path in an L document must be PROJECT-RELATIVE.

An L document is a DESIGN artefact: the flow reads it back, diffs it across
runs and compares it between designs. A provenance value that names the
machine and the directory the run happened in makes the same design emit a
different document from every checkout, so two runs are not comparable and
neither is reproducible.

Measured over the tracked corpus at the time of the fix: 2550 of 2554 L
documents already used a project-relative provenance path. The four
exceptions were not a historical record — BOTH producers were live:

  * ``l22_coverage_goal_emit`` wrote ``framed_hits``' absolute ``source``
    into ``L22.fields.coverage_goals[].source``;
  * ``_post_emit_sdc_constraints`` wrote ``sdc_constraints``' absolute
    ``source`` into ``L8.clock_domains[].evidence`` — while the sibling
    ``source`` and ``L19.fields.sdc_constraints_path`` beside it were
    already relative.

Both now route through
``l_doc_consumer_contract.project_relative_source``. ``line`` is untouched
throughout: a line number is a property of the file's contents, not of the
machine it sits on.

All fixtures are synthesised neutral data — no design, PDK or vendor
literal. chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from l_doc_consumer_contract import (  # noqa: E402
    OUTSIDE_PROJECT_PREFIX,
    project_relative_source,
)
from l22_coverage_goal_emit import run as emit_run  # noqa: E402

_DOC_WITH_TARGET = (
    "# Verification\n"
    "\n"
    "The block must reach at least 95% branch coverage on the random run.\n"
)


def _mk_project(project: Path, *, doc_dir: str = "phase1/input_doc",
                doc_name: str = "verification_plan.txt") -> Path:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L22_VERIFICATION_PLAN.json").write_text(json.dumps({
        "doc_id": "L22",
        "doc_name": "L22_VERIFICATION_PLAN",
        "applicability": "APPLICABLE",
        "extraction_status": "NOT_YET_EXTRACTED",
        "fields": {"coverage_goals": [], "formal_properties": [],
                   "verification_plan_present": "implicit"},
    }, ensure_ascii=False), encoding="utf-8")
    d = project / doc_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / doc_name
    p.write_text(_DOC_WITH_TARGET, encoding="utf-8")
    return p


def _emitted_goal(project: Path) -> dict:
    rep = emit_run(project)
    assert rep["status"] == "OK", rep
    assert rep["emitted_count"] == 1, rep
    return rep["emitted"][0]


# ──────────────────────────── the emitter's own provenance field ──
def test_emitted_source_is_project_relative(tmp_path):
    """The defect, stated as an assertion."""
    _mk_project(tmp_path)
    goal = _emitted_goal(tmp_path)

    assert not Path(goal["source"]).is_absolute(), (
        f"l22_coverage_goal_emit wrote an ABSOLUTE path into an L document: "
        f"{goal['source']!r}. An L document is a design artefact the flow "
        f"diffs across runs; an absolute path records the checkout instead "
        f"of the document.")
    assert goal["source"] == "phase1/input_doc/verification_plan.txt", goal


def test_source_is_relative_from_every_input_location(tmp_path):
    """`input_doc_texts` reads several staged locations; all must relativise."""
    for i, doc_dir in enumerate(("phase1/input_doc", "input/docs",
                                 "phase1/input_prompt")):
        project = tmp_path / f"p{i}"
        _mk_project(project, doc_dir=doc_dir)
        goal = _emitted_goal(project)
        assert goal["source"] == f"{doc_dir}/verification_plan.txt", goal
        assert not Path(goal["source"]).is_absolute(), goal


def test_line_is_preserved(tmp_path):
    """`line` is a property of the FILE, not of the machine — keep it."""
    _mk_project(tmp_path)
    goal = _emitted_goal(tmp_path)
    assert goal["line"] == 3, (
        f"the target sits on line 3 of the fixture; got {goal['line']!r}. "
        f"Relativising the path must not disturb the line number.")


def test_value_and_evidence_are_untouched(tmp_path):
    """#518 is about the provenance field ONLY — what is lifted must not move."""
    _mk_project(tmp_path)
    goal = _emitted_goal(tmp_path)
    assert goal["target_pct"] == 95.0, goal
    assert goal["name"] == "branch coverage", goal
    assert "95%" in goal["evidence"], goal
    assert goal["signoff_gate"] is True, goal


def test_same_design_from_two_directories_emits_identical_documents(tmp_path):
    """The reproducibility claim, measured end to end.

    This is the defect's actual consequence and the reason a relative path
    is not a cosmetic preference: two checkouts of one design must produce
    byte-identical L documents."""
    a = tmp_path / "checkout_a" / "design"
    b = tmp_path / "some" / "deeper" / "checkout_b" / "design"
    for project in (a, b):
        _mk_project(project)
        emit_run(project)
    doc_a = (a / "phase1/generated_docs/L22_VERIFICATION_PLAN.json").read_text()
    doc_b = (b / "phase1/generated_docs/L22_VERIFICATION_PLAN.json").read_text()
    assert doc_a == doc_b, (
        "the same design emitted from two directories produced two different "
        "L22 documents — the emitted provenance still carries the checkout")


def test_no_absolute_path_survives_anywhere_in_the_written_document(tmp_path):
    """Not just `source`: nothing the emitter writes may be absolute."""
    _mk_project(tmp_path)
    emit_run(tmp_path)
    text = (tmp_path
            / "phase1/generated_docs/L22_VERIFICATION_PLAN.json").read_text()
    assert str(tmp_path) not in text, (
        f"the emitted L22 still contains the project's absolute path:\n"
        f"{text}")


def test_rerun_is_idempotent_with_relative_source(tmp_path):
    """Relativising must not break the (name, target_pct) dedup key."""
    _mk_project(tmp_path)
    assert emit_run(tmp_path)["emitted_count"] == 1
    assert emit_run(tmp_path)["emitted_count"] == 0, "re-run duplicated a goal"


def test_the_emitted_source_round_trips_through_the_reader(tmp_path):
    """The write side must produce what the read side accepts.

    `l_doc_evidence_util.resolve_under_project` is the counterpart of this
    change: it resolves an evidence string back to a file and REFUSES a path
    that escapes the project, on the same reasoning — "a certificate whose
    proof lives outside the run is not reproducible evidence". A relative
    source is therefore not merely tidier, it is the form the reader can
    actually resolve."""
    from l_doc_evidence_util import resolve_under_project

    src = _mk_project(tmp_path)
    goal = _emitted_goal(tmp_path)
    resolved = resolve_under_project(tmp_path, goal["source"])
    assert resolved is not None, (
        f"the reader could not resolve the emitted source {goal['source']!r}")
    assert resolved == src.resolve(), (resolved, src)


# ─────────────────────── the policy for an input outside the project ──
#
# NOTE ON REACHABILITY, stated honestly: both current callers discover their
# inputs by globbing UNDER the project root, so every path they hand in is
# lexically inside it and this branch does not fire in the shipped flow. It
# is unit-tested rather than integration-tested for that reason. The policy
# lives in the shared helper because it is the shared helper's job to have
# one, and because a future emitter handed a path by an orchestrator will
# reach it.
def test_outside_project_input_is_marked_not_dropped_and_not_absolute():
    src = "/somewhere/else/entirely/external_spec.txt"
    value, outside = project_relative_source(src, Path("/a/project/root"))

    assert outside is True
    assert not Path(value).is_absolute(), (
        f"an out-of-project input was recorded as an absolute path: {value!r}")
    assert value == f"{OUTSIDE_PROJECT_PREFIX}/external_spec.txt", value
    assert "somewhere" not in value and "else" not in value, (
        f"the machine-specific directory chain survived into {value!r}")
    assert "external_spec.txt" in value, (
        "the basename is a property of the DOCUMENT and is identical on "
        "every machine — dropping it discards provenance for no portability "
        "gain")


def test_outside_project_marker_is_flagged_on_the_emitted_goal(tmp_path):
    """The marker must be machine-readable, not only human-readable."""
    _mk_project(tmp_path)
    goal = _emitted_goal(tmp_path)
    assert "source_outside_project" not in goal, (
        "the in-project case must not carry the degradation flag")

    value, outside = project_relative_source("/elsewhere/x/y/doc.txt", tmp_path)
    assert outside is True and value.startswith(OUTSIDE_PROJECT_PREFIX)


# ───────────────────────────────── the shared helper's own contract ──
@pytest.mark.parametrize("given,expected", [
    ("phase1/input_doc/a.txt", "phase1/input_doc/a.txt"),
    ("input/docs/a.txt", "input/docs/a.txt"),
    ("", ""),
])
def test_already_relative_paths_pass_through(given, expected):
    value, outside = project_relative_source(given, Path("/p"))
    assert value == expected and outside is False


def test_none_source_is_empty_not_the_string_none():
    assert project_relative_source(None, Path("/p")) == ("", False)


def test_separator_is_posix_regardless_of_the_path_flavour(tmp_path):
    """The emitted separator is `/`, so the value does not record the OS.

    Normalisation is `PurePath.as_posix()`, applied to a real path object.
    It deliberately does NOT launder backslashes out of a string: on POSIX
    a backslash is a legal filename character, so rewriting it would
    corrupt a real filename. `test_a_posix_filename_containing_a_backslash_
    is_preserved` pins that limit."""
    (tmp_path / "phase1" / "input_doc").mkdir(parents=True)
    src = tmp_path / "phase1" / "input_doc" / "a.txt"
    src.write_text("x", encoding="utf-8")
    value, outside = project_relative_source(str(src), tmp_path)
    assert value == "phase1/input_doc/a.txt" and outside is False


def test_a_posix_filename_containing_a_backslash_is_preserved():
    """A backslash inside a POSIX name is data, not a separator."""
    value, _ = project_relative_source("phase1/odd\\name.txt", Path("/p"))
    assert value == "phase1/odd\\name.txt", value


def test_relativises_against_an_unresolved_project_root(tmp_path):
    """`main()` resolves its project dir; in-process callers often do not."""
    link = tmp_path / "link"
    real = tmp_path / "real"
    (real / "phase1").mkdir(parents=True)
    (real / "phase1" / "a.txt").write_text("x", encoding="utf-8")
    link.symlink_to(real, target_is_directory=True)

    value, outside = project_relative_source(
        str(real / "phase1" / "a.txt"), link)
    assert outside is False, (
        "a symlinked project root defeated relativisation and the path was "
        "recorded as out-of-project")
    assert value == "phase1/a.txt", value


# ─────────────────── the second live producer: staged SDC into L8 ──
def _mk_sdc_project(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for name in ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM"):
        (gd / f"{name}.json").write_text(json.dumps({
            "schema_version": 2,
            "clock_domains": [{"name": "clk", "domain_kind": "primary",
                               "freq_mhz": None, "evidence": None}],
        }, ensure_ascii=False), encoding="utf-8")
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {}}, ensure_ascii=False), encoding="utf-8")
    c = project / "input" / "constraints"
    c.mkdir(parents=True, exist_ok=True)
    (c / "clock.sdc").write_text(
        "create_clock -name core_clk -period 10.0 [get_ports clk]\n",
        encoding="utf-8")


def test_staged_sdc_evidence_lands_relative_in_l8(tmp_path):
    """The producer of the four published absolute paths, pinned.

    This was LIVE, not a stale corpus artefact: run against the pre-fix
    tree on a fresh minimal project it wrote an absolute path into BOTH L8
    documents."""
    import phase1_doc_one_shot_runner as R

    _mk_sdc_project(tmp_path)
    R._post_emit_sdc_constraints(tmp_path.resolve())

    for name in ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM"):
        doc = json.loads(
            (tmp_path / "phase1/generated_docs" / f"{name}.json").read_text())
        ev = doc["clock_domains"][0]["evidence"]
        assert not Path(ev).is_absolute(), (
            f"{name}.clock_domains[0].evidence is an ABSOLUTE path: {ev!r}")
        assert ev == "input/constraints/clock.sdc", ev

    l19 = json.loads(
        (tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())
    assert l19["fields"]["sdc_constraints_path"] == "input/constraints/clock.sdc"


def test_staged_sdc_ingest_leaves_no_absolute_path_in_any_l_doc(tmp_path):
    """End-to-end through the real gate, not by inspecting one field."""
    import phase1_doc_one_shot_runner as R
    from l_doc_path_portability_check import scan_tree

    _mk_sdc_project(tmp_path)
    R._post_emit_sdc_constraints(tmp_path.resolve())

    rep = scan_tree(tmp_path)
    assert rep["documents_read"] == 3, rep
    assert rep["verdict"] == "PASS", rep["findings"]
