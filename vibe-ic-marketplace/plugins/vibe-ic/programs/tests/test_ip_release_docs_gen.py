"""tests/test_ip_release_docs_gen.py — step 37.5ip's release-document producer.

WHAT IS BEING DEFENDED HERE
===========================
Before this producer existed, step 37.5ip's `required_outputs` were the four
views and NOTHING ELSE: a hard IP shipped its LEF, Liberty, GDS and Verilog and
no statement of what it is, how to instantiate it, what the integrating design
MUST do, or what is known to be wrong with it.

So the cases below are about the two ways a generated document lies, which are
the two `test_tapeout_docs_gen` already names for the chip path:

  * it fills a gap with a plausible number, and the gap becomes invisible;
  * it exists for a run that its own gate refused, and the FILE outlives the run.

and one more this producer adds, because an IP has a deliverability gate of its
own: it must never state a SECOND opinion about whether the kit is deliverable.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _release_kit import (  # noqa: E402
    CONTROL,
    SUBJECT,
    build_project,
    docs_dir,
)
from _release_docs_contract import (  # noqa: E402
    DERIVED_COLUMN,
    IP_DOCS,
    MANIFEST_NAME,
    NOT_MEASURED,
    REASON_PREFIX,
)

PROG = Path(__file__).resolve().parents[1] / "ip_release_docs_gen.py"
FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"

#: rc values `flow_compliance_check` scores in a PASS tier: 0 PASS,
#: 2 VACUOUS_PASS, 3 PASS_WITH_WAIVERS.
PASS_TIER_RCS = (0, 2, 3)


def run(project: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *extra],
        capture_output=True, text=True)


def _derived_rows(text: str):
    """Every `Derived from` row of one document, as (label, value, third)."""
    rows, in_table = [], False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        cells = [c.strip() for c in cells]
        if len(cells) != 3:
            in_table = False
            continue
        if cells[2] == DERIVED_COLUMN:
            in_table = True
            continue
        if not in_table or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(tuple(cells))
    return rows


# ───────────────────────────── it produces ─────────────────────────────────

def test_a_delivered_kit_gets_its_document_set(tmp_path):
    project = build_project(tmp_path / "p")
    result = run(project)
    assert result.returncode == 0, result.stderr
    for release in (SUBJECT, CONTROL):
        out = docs_dir(project, release)
        for spec in IP_DOCS:
            if spec.requirement == "required":
                assert (out / spec.filename).is_file(), (
                    f"{spec.filename} is required for the ip arm and was not "
                    f"written into {out}")
        assert (out / MANIFEST_NAME).is_file()


def test_one_directory_per_package_including_the_single_package_case(tmp_path):
    """A shape exercised on every run must be the shape a two-macro kit takes."""
    single = build_project(tmp_path / "one", packages=(SUBJECT,))
    assert run(single).returncode == 0
    assert docs_dir(single, SUBJECT).is_dir()
    assert not (single / "phase3" / "stage4" / "documentation" / "ip"
                / "IP_DATASHEET.md").exists(), (
        "a single-package release collapsed into the parent directory, so the "
        "common case has a different shape from a two-package one")


def test_every_quantitative_field_is_derived_or_says_it_was_not(tmp_path):
    """THE RULE. Never a default, never hand-typed.

    A hand-maintained copy of an automatically-changing fact is stale by
    construction, and a datasheet with a hand-typed pin count is stale on
    arrival. So every row is one of exactly two things and there is no third.
    """
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    assert run(project).returncode == 0
    out = docs_dir(project)
    seen = 0
    for path in sorted(out.glob("*.md")):
        for label, value, third in _derived_rows(path.read_text(encoding="utf-8")):
            seen += 1
            if value == NOT_MEASURED:
                assert third.startswith(REASON_PREFIX), (
                    f"{path.name}: '{label}' is {NOT_MEASURED} with no reason")
                assert third[len(REASON_PREFIX):].strip(), (
                    f"{path.name}: '{label}' has an empty reason")
                continue
            assert third.startswith("`") and third.endswith("`"), (
                f"{path.name}: '{label}' = {value!r} carries no artefact path "
                f"(third column {third!r})")
            cited = third.strip("`")
            assert (project / cited).exists(), (
                f"{path.name}: '{label}' cites `{cited}`, which does not "
                f"resolve under the project")
    assert seen > 0, "no derived rows were emitted at all"


def test_the_manifest_counts_agree_with_the_documents(tmp_path):
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    assert run(project).returncode == 0
    out = docs_dir(project)
    derived = holes = 0
    for path in sorted(out.glob("*.md")):
        for _label, value, _third in _derived_rows(path.read_text(encoding="utf-8")):
            if value == NOT_MEASURED:
                holes += 1
            else:
                derived += 1
    manifest = (out / MANIFEST_NAME).read_text(encoding="utf-8")
    assert f"derived_fields: {derived}" in manifest, manifest
    assert f"not_measured_fields: {holes}" in manifest, manifest


def test_a_tree_that_is_not_a_work_tree_says_so_rather_than_inventing_a_sha(tmp_path):
    """A report that does not name the tree it measured describes the wrong one."""
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    assert run(project).returncode == 0
    manifest = (docs_dir(project) / MANIFEST_NAME).read_text(encoding="utf-8")
    assert f'tree_sha: "{NOT_MEASURED}"' in manifest
    assert "tree_sha_reason: \"\"" not in manifest, (
        f"tree_sha is {NOT_MEASURED} with no reason")


def test_the_conditional_document_is_decided_by_an_artefact_not_by_eye(tmp_path):
    """'Conditional' is where a set quietly loses a required document."""
    rich = build_project(tmp_path / "rich", packages=(SUBJECT,),
                         register_rich=True)
    assert run(rich).returncode == 0
    assert (docs_dir(rich) / "IP_PROGRAMMING_REFERENCE.md").is_file()
    manifest = (docs_dir(rich) / MANIFEST_NAME).read_text(encoding="utf-8")
    assert "register_rich: true" in manifest
    assert "register_rich_source: \"phase1/generated_docs/L4_REGMAP.json\"" \
        in manifest, manifest

    plain = build_project(tmp_path / "plain", packages=(SUBJECT,),
                          register_rich=False)
    assert run(plain).returncode == 0
    assert not (docs_dir(plain) / "IP_PROGRAMMING_REFERENCE.md").exists()
    assert "register_rich: false" in (
        docs_dir(plain) / MANIFEST_NAME).read_text(encoding="utf-8")


def test_a_layer_the_run_does_not_carry_becomes_a_hole_not_a_default(tmp_path):
    project = build_project(tmp_path / "p", packages=(SUBJECT,),
                            with_layers=False)
    assert run(project).returncode == 0
    text = (docs_dir(project) / "IP_DATASHEET.md").read_text(encoding="utf-8")
    holes = [r for r in _derived_rows(text) if r[1] == NOT_MEASURED]
    assert holes, "a run with no design layers produced no NOT_MEASURED field"
    for label, _value, third in holes:
        assert third.startswith(REASON_PREFIX), label
        assert "generated_docs" in third or "git work tree" in third \
            or "kit" in third, (label, third)


def test_the_application_note_never_originates_a_mandatory_constraint(tmp_path):
    """An AN is optional and is the first document dropped from a delivery."""
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    assert run(project).returncode == 0
    out = docs_dir(project)
    guide = (out / "IP_INTEGRATION_GUIDE.md").read_text(encoding="utf-8")
    note = (out / "AN001_REFERENCE_INTEGRATION.md").read_text(encoding="utf-8")

    def ids(text):
        import re
        return set(re.findall(r"\*\*MANDATORY\*\*\s+`([A-Z0-9][A-Z0-9_.-]*)`",
                              text))

    assert ids(guide), "the guide states no mandatory constraint at all"
    assert ids(note) <= ids(guide), (
        f"the note originates {sorted(ids(note) - ids(guide))}")


# ───────────────────────────── it refuses ──────────────────────────────────

def test_a_kit_its_own_gate_refuses_gets_no_documents(tmp_path):
    """Same policy `tapeout_docs_gen` holds, deferred to rather than re-decided.

    A release document for a kit its own gate refuses is worse than none: it is
    a FILE, it outlives the run, and nothing in the copy says the kit was
    refused.
    """
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    (project / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.v").unlink()
    result = run(project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "NOT DELIVERABLE" in result.stderr
    assert not docs_dir(project).exists(), (
        "documents were written for a kit digital_hardmacro_check refuses")


def test_a_refusal_exits_a_code_the_flow_does_not_score_as_a_pass(tmp_path):
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    (project / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.v").unlink()
    rc = run(project).returncode
    assert rc not in PASS_TIER_RCS, (
        f"rc={rc} is a PASS tier in this flow (0 PASS / 2 VACUOUS_PASS / "
        f"3 PASS_WITH_WAIVERS), so a run this producer just refused to "
        f"document would be credited as a pass")


def test_no_kit_is_the_vacuous_tier_and_says_where_it_looked(tmp_path):
    """Nothing to document is neither a pass nor a refusal, and it discloses."""
    project = build_project(tmp_path / "p", packages=())
    result = run(project)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "VACUOUS_PASS:" in result.stderr
    assert "hardmacro" in result.stdout, (
        "an absence verdict that does not name where it looked cannot be "
        "re-checked")
    assert not (project / "phase3" / "stage4" / "documentation").exists()


def test_an_absent_project_directory_is_refused_not_documented(tmp_path):
    result = run(tmp_path / "nope")
    assert result.returncode == 2
    assert "VACUOUS_PASS:" in result.stderr


# ─────────────────── the flow declares what this writes ────────────────────

def _declared_clauses(needle: str):
    text = FLOW_YAML.read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if needle in line and line.startswith("- program_exit_zero:"):
            out.append(line.split(":", 1)[1].strip().strip('"'))
    return out


def test_the_step_declares_every_document_this_producer_writes(tmp_path):
    """d4/criteria_match caught 37.5ic's pair disagreeing; keep this pair agreeing.

    A declared output no producer writes can never be produced, and a produced
    artefact no step declares is invisible to the audit. Both directions are
    checked from the FLOW's own text against a REAL run of the producer.
    """
    import fnmatch
    project = build_project(tmp_path / "p", packages=(SUBJECT,))
    assert run(project).returncode == 0
    written = {
        p.relative_to(project).as_posix()
        for p in (project / "phase3" / "stage4" / "documentation").rglob("*")
        if p.is_file()}

    declared = [line.strip().lstrip("- ").strip('"')
                for line in FLOW_YAML.read_text(encoding="utf-8").splitlines()
                if "phase3/stage4/documentation/ip/" in line
                and line.strip().startswith('- "')]
    assert declared, "step 37.5ip declares no documentation output any more"
    for spec in declared:
        assert any(fnmatch.fnmatch(w, spec) for w in written), (
            f"the flow declares {spec!r} and this producer wrote "
            f"{sorted(written)} — a declared output no producer writes can "
            f"never be produced")


def test_the_producer_is_dispatched_by_the_runner_and_a_refusal_publishes_nothing(tmp_path):
    """The runner must EXECUTE the producer; a gate declaration is not that."""
    runner_path = Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py"
    runner_text = runner_path.read_text(encoding="utf-8")
    assert runner_text.count('PROGRAMS_DIR / "ip_release_docs_gen.py"') == 1
    assert runner_text.count("plan.append(step_ip_release_docs_gen(project))") == 1, (
        "a producer helper that main never calls is still an orphan")

    import phase3_one_shot_runner as runner

    clean = build_project(tmp_path / "clean", packages=(SUBJECT,))
    result = runner.step_ip_release_docs_gen(clean)
    assert result.status == "PASS", result
    assert result.extras.get("flow_step") == "37.5ip"
    assert any(p.endswith("IP_DATASHEET.md") for p in result.output_files)

    harmed = build_project(tmp_path / "harmed", packages=(SUBJECT,))
    (harmed / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.lef").unlink()
    harmed_result = runner.step_ip_release_docs_gen(harmed)
    assert harmed_result.status == "SKIP", harmed_result
    assert harmed_result.extras.get("producer_rc") == 1, harmed_result
    assert not (harmed / "phase3" / "stage4" / "documentation").exists(), (
        "a kit its own gate refuses published release documents")


@pytest.mark.parametrize("clause", _declared_clauses("release_docs_check"))
def test_the_gate_clause_the_flow_declares_names_this_producers_arm(clause):
    """The gate the flow wires must judge the arm this producer writes."""
    assert "--arm ip" in clause, clause
