"""tests/test_release_docs_check_ic_arm.py — the ic arm must REFUSE, and NAME what.

WHY THIS FILE EXISTS SEPARATELY FROM `test_release_docs_check`
=============================================================
Its sibling falsifies the `ip` arm over a delivered hardmacro kit. This file
falsifies the `ic` arm over a signed-off die, and the two fixtures are different
trees — a chip has a routed DEF, a gate-level netlist, sign-off records and a
metrics file, and a hard IP has four views. Sharing one fixture would mean one
of the arms was being judged over a tree it never sees in a real run.

THE DEFECT THIS FILE WAS WRITTEN AGAINST, MEASURED ON THIS TREE
===============================================================
Before this landed, `release_docs_check --arm ic` could only ever answer
"nothing to examine". `expected_releases` returned `[]` for the ic arm
unconditionally, so a run that signed off a die and wrote NOT ONE document
reached the `not expected and not present` branch, was scored NOT_DETERMINED,
and NOT_DETERMINED is a PASS tier. The arm was declared and wired to nothing —
the exact v1.13.42 shape the gate's own docstring was written about, reproduced
inside the gate written to end it. `test_a_die_that_ships_with_no_documentation_
is_a_refusal_not_a_skip` is the falsification of that specific defect.

And `_check_pin_count` carried an `if arm == "ip"` guard, so the ic arm's three
interface rows were re-derived by NOTHING and a hand-edited chip pin count was
believed.

Every case below:

  * asserts an EXACT exit code — rc 2 is "the question could not be put", rc 143
    is KILLED and rc 199 is a stall kill, and `!= 0` would accept all three;
  * breaks exactly ONE thing;
  * runs over a project holding a SECOND, UNTOUCHED release and asserts that
    control stays green in the SAME invocation, except where the thing broken is
    genuinely SHARED by both releases — in which case both reddening is the
    correct reading and is asserted as such;
  * REPAIRS the same defect and asserts rc 0.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ic_release_kit import (  # noqa: E402
    CONTROL,
    SUBJECT,
    build_gds,
    build_gds_without_geometry,
    build_project,
    docs_dir,
)
from _release_docs_contract import MANIFEST_NAME  # noqa: E402

GATE = Path(__file__).resolve().parents[1] / "release_docs_check.py"
GEN = Path(__file__).resolve().parents[1] / "ic_release_docs_gen.py"
FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2
PASS_TIER_RCS = (0, 2, 3)


def generate(project: Path) -> None:
    result = subprocess.run([sys.executable, str(GEN), str(project)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def released(tmp_path: Path, name: str = "p") -> Path:
    """A project with TWO documented releases: the subject and the control."""
    project = build_project(tmp_path / name)
    generate(project)
    return project


def check(project: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), str(project), "--arm", "ic", *extra],
        capture_output=True, text=True)


def report(project: Path):
    out = project / "release_docs_ic.json"
    result = check(project, "--json", str(out))
    return result, json.loads(out.read_text(encoding="utf-8"))


def rules_for(data, release: str) -> set:
    """The rules that REFUSED this release — severity ERROR only.

    Collecting every severity would make these assertions survive a mutation
    that downgrades a rule to INFO, which is how a gate gets quietly disarmed:
    the finding is still emitted, still appears in the report, and no longer
    fails anything.
    """
    return {f["rule"] for f in data["findings"]
            if f["release"] == release and f["severity"] == "ERROR"}


def verdict_of(data, release: str) -> bool:
    for detail in data["summary"]["releases"]:
        if detail["release"] == release:
            return detail["pass"]
    raise AssertionError(f"{release} has no per-release verdict in the report")


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path.name} does not contain {old!r} to edit"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def drop_section(path: Path, heading: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    out, dropping = [], False
    for line in lines:
        if line.startswith(f"## {heading}"):
            dropping = True
            continue
        if dropping and line.startswith("## "):
            dropping = False
        if not dropping:
            out.append(line)
    assert len(out) < len(lines), f"section {heading!r} was not found"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ═══════════════════════════ the control arm ═══════════════════════════════
def test_a_clean_release_passes_and_the_gate_says_how_much_it_looked_at(tmp_path):
    project = released(tmp_path)
    result = check(project)
    assert result.returncode == RC_PASS, result.stdout + result.stderr
    assert "[PASS] release_docs_check" in result.stdout
    assert "examined 2 release(s)" in result.stdout
    assert "derived row(s)" in result.stdout


def test_both_documented_releases_are_judged_not_just_the_first(tmp_path):
    _result, data = report(tmp_path and released(tmp_path))
    assert {d["release"] for d in data["summary"]["releases"]} == {SUBJECT,
                                                                  CONTROL}
    assert data["summary"]["rows_examined"] > 0


def test_the_cross_checks_that_only_the_ic_arm_can_run_actually_ran(tmp_path):
    """A cross-check reported NOT_STATED on every run is a cross-check nobody
    is running; assert the clean run reaches AGREES on both."""
    _result, data = report(released(tmp_path))
    for detail in data["summary"]["releases"]:
        assert detail["pin_count_cross_check"] == "AGREES", detail
        assert detail["die_size_cross_check"] == "AGREES", detail
        assert detail["artefact_substance"] == "CLEAN", detail
        assert detail["source_digests_recomputed"] > 0, detail


# ══════════ THE DEFECT THIS ARM WAS BLIND TO: shipped and undocumented ══════
def test_a_die_that_ships_with_no_documentation_is_a_refusal_not_a_skip(tmp_path):
    """Measured: before this, the ic arm scored this NOT_DETERMINED — a PASS tier.

    The releases the gate EXPECTS are derived from `phase3/stage4/gds/*.gds`,
    not from the documentation directory. Reading the directory makes "the die
    was signed off and nobody documented it" an empty sweep that passes.
    """
    project = build_project(tmp_path / "p")
    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout + result.stderr
    assert data["summary"]["expected_releases"] == sorted([SUBJECT, CONTROL])
    for release in (SUBJECT, CONTROL):
        assert "RELEASE_DOCUMENTATION_ABSENT" in rules_for(data, release)
        assert verdict_of(data, release) is False
    assert "signs off layout" in result.stdout


def test_the_same_project_documented_passes(tmp_path):
    project = released(tmp_path)
    assert check(project).returncode == RC_PASS


def test_one_release_documented_and_one_not_is_refused_naming_only_that_one(
        tmp_path):
    project = released(tmp_path)
    shutil.rmtree(docs_dir(project, SUBJECT))
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "RELEASE_DOCUMENTATION_ABSENT" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True, (
        "the untouched release was reddened by its neighbour's absence")


def test_no_die_and_no_documents_is_the_vacuous_tier_and_discloses_it(tmp_path):
    project = tmp_path / "bare"
    project.mkdir()
    result, data = report(project)
    assert result.returncode == RC_VACUOUS
    assert data["summary"]["reason"] == "no_release_to_examine"
    assert any("phase3/stage4/gds/*.gds" in s
               for s in data["summary"]["searched_and_absent"]), data["summary"]
    assert "VACUOUS_PASS:" in result.stderr


# ═══════════════════════ the document-shape refusals ═══════════════════════
def test_a_missing_required_section_is_refused_and_the_section_is_named(tmp_path):
    project = released(tmp_path)
    drop_section(docs_dir(project) / "PRELIMINARY_DATASHEET.md", "5. Timing")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "REQUIRED_SECTION_ABSENT" in rules_for(data, SUBJECT)
    assert any("5. Timing" in f["message"] for f in data["findings"])
    assert verdict_of(data, CONTROL) is True


def test_a_missing_required_document_is_refused(tmp_path):
    project = released(tmp_path)
    (docs_dir(project) / "ERRATA.md").unlink()
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "REQUIRED_DOCUMENT_ABSENT" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_the_conditional_document_is_demanded_only_when_the_manifest_says_so(
        tmp_path):
    """A conditional document absent on a run that owes it is a FAIL; absent on
    a run that does not owe it is correct."""
    owed = build_project(tmp_path / "owed", releases=(SUBJECT,),
                         register_rich=True)
    generate(owed)
    (docs_dir(owed) / "USER_REFERENCE_MANUAL.md").unlink()
    result, data = report(owed)
    assert result.returncode == RC_FAIL
    assert "REQUIRED_DOCUMENT_ABSENT" in rules_for(data, SUBJECT)

    plain = build_project(tmp_path / "plain", releases=(SUBJECT,),
                          register_rich=False)
    generate(plain)
    assert check(plain).returncode == RC_PASS


# ═════════════════ the cross-checks: re-derived, never believed ════════════
def test_a_pin_count_edited_away_from_the_netlist_is_refused_naming_both_sides(
        tmp_path):
    """The document derived it from the DEF; this re-derives it from the
    gate-level netlist the route produced — a different view, a different
    program."""
    project = released(tmp_path)
    edit(docs_dir(project) / "PRELIMINARY_DATASHEET.md",
         "| Signal pins | 3 |", "| Signal pins | 7 |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "PIN_COUNT_DISAGREES_WITH_NETLIST" in rules_for(data, SUBJECT)
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "PIN_COUNT_DISAGREES_WITH_NETLIST")
    assert "7" in message and "3" in message, message
    assert "_pnr.v" in message, "the refusal does not name the view it re-derived from"
    assert verdict_of(data, CONTROL) is True


def test_a_total_that_does_not_equal_its_own_parts_is_refused(tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / "PRELIMINARY_DATASHEET.md",
         "| Pin count (total) | 5 |", "| Pin count (total) | 9 |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "PIN_COUNT_INTERNALLY_INCONSISTENT" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_die_size_edited_away_from_the_metrics_is_refused_naming_both_sides(
        tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / "PRELIMINARY_DATASHEET.md",
         "| Die width (um) | 240 |", "| Die width (um) | 180 |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "DIE_SIZE_DISAGREES_WITH_METRICS" in rules_for(data, SUBJECT)
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "DIE_SIZE_DISAGREES_WITH_METRICS")
    assert "180" in message and "240" in message, message
    assert "metrics.json" in message
    assert verdict_of(data, CONTROL) is True


def test_the_repaired_cross_checks_pass_again(tmp_path):
    project = released(tmp_path)
    path = docs_dir(project) / "PRELIMINARY_DATASHEET.md"
    edit(path, "| Signal pins | 3 |", "| Signal pins | 7 |")
    assert check(project).returncode == RC_FAIL
    edit(path, "| Signal pins | 7 |", "| Signal pins | 3 |")
    assert check(project).returncode == RC_PASS


def test_a_rounding_difference_between_the_two_die_derivations_is_not_a_refusal(
        tmp_path):
    """The tolerance is on ROUNDING, not on the design. A metrics writer that
    rounds to one decimal must not redden a correct run."""
    project = released(tmp_path)
    metrics = project / "phase3" / "final" / "metrics.json"
    doc = json.loads(metrics.read_text(encoding="utf-8"))
    doc["design__die__bbox"] = "0 0 240.1 159.9"
    metrics.write_text(json.dumps(doc), encoding="utf-8")
    # the manifest digest of a shared artefact legitimately goes stale, so
    # regenerate rather than assert over a defect this case is not about
    generate(project)
    assert check(project).returncode == RC_PASS


# ══════════════════════ the mandatory-constraint rule ══════════════════════
def test_a_mandatory_constraint_only_in_the_app_note_is_refused(tmp_path):
    project = released(tmp_path)
    note = docs_dir(project) / "AN001_TYPICAL_APPLICATION.md"
    note.write_text(
        note.read_text(encoding="utf-8")
        + "\n- **MANDATORY** `BOARD-DECOUPLING` — the board must decouple "
          "every supply rail (derived from `input/project.json`)\n",
        encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE" in rules_for(data, SUBJECT)
    assert any("BOARD-DECOUPLING" in f["message"] for f in data["findings"])
    assert verdict_of(data, CONTROL) is True


def test_a_constraint_dropped_from_the_datasheet_but_left_in_the_note_is_refused(
        tmp_path):
    """The direction that actually happens: the bearing document is edited and
    the note keeps restating a constraint the release no longer carries."""
    project = released(tmp_path)
    sheet = docs_dir(project) / "PRELIMINARY_DATASHEET.md"
    text = sheet.read_text(encoding="utf-8")
    kept = [line for line in text.splitlines()
            if "**MANDATORY** `DIE-OUTLINE`" not in line]
    assert len(kept) < len(text.splitlines()), "DIE-OUTLINE was never stated"
    sheet.write_text("\n".join(kept) + "\n", encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE" in rules_for(data, SUBJECT)


# ════════════════ the substance re-check, AFTER generation ═════════════════
def test_an_artefact_hollowed_out_after_generation_is_still_refused(tmp_path):
    """Documents are FILES. A producer-side refusal alone would have run only at
    the one moment the tree was known good."""
    project = released(tmp_path)
    assert check(project).returncode == RC_PASS
    (project / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
        build_gds_without_geometry(SUBJECT))
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "GDS_NO_GEOMETRY" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True, (
        "the untouched release was reddened by its neighbour's hollow layout")


def test_a_shared_artefact_hollowed_out_reddens_every_release_that_cites_it(
        tmp_path):
    """Correct, and asserted so it cannot be mistaken for the environmental
    failure the control exists to catch: one routed DEF is SHARED by both
    releases, and a document set describing it is wrong in both."""
    project = released(tmp_path)
    def_path = project / "phase3/stage3/pnr/routed.def"
    def_path.write_text(re.sub(
        r"COMPONENTS 4 ;.*?END COMPONENTS", "COMPONENTS 0 ;\nEND COMPONENTS",
        def_path.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    for release in (SUBJECT, CONTROL):
        assert "DEF_NO_COMPONENTS" in rules_for(data, release)


# ═══════════════════════════ digests and manifest ══════════════════════════
def test_a_source_artefact_that_changed_after_generation_is_refused(tmp_path):
    """The check that catches a document set correctly describing a DIFFERENT
    build: every heading in place and the artefacts it names are not the ones
    on disk."""
    project = released(tmp_path)
    (project / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
        build_gds(SUBJECT, 250.0, 170.0))
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_SOURCE_DIGEST_STALE" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_manifest_source_naming_a_file_that_is_not_there_is_refused(tmp_path):
    project = released(tmp_path)
    (project / "phase3/stage4/gds" / f"{SUBJECT}.gds").unlink()
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_SOURCE_ABSENT" in rules_for(data, SUBJECT)


def test_a_manifest_count_that_drifted_is_refused(tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / MANIFEST_NAME,
         "derived_fields:", "derived_fields: 999 #")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_COUNT_DISAGREES" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_release_with_no_manifest_is_refused(tmp_path):
    project = released(tmp_path)
    (docs_dir(project) / MANIFEST_NAME).unlink()
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_ABSENT" in rules_for(data, SUBJECT)


# ══════════════════════════ the row-level rules ════════════════════════════
def test_a_hand_typed_value_with_no_artefact_is_refused(tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / "PRELIMINARY_DATASHEET.md",
         "| Die height (um) | 160 | `phase3/stage3/pnr/routed.def` |",
         "| Die height (um) | 160 | measured on the bench |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "FIELD_NOT_DERIVED" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_citation_that_resolves_to_nothing_is_refused(tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / "PRELIMINARY_DATASHEET.md",
         "| Die height (um) | 160 | `phase3/stage3/pnr/routed.def` |",
         "| Die height (um) | 160 | `phase3/stage3/pnr/absent.def` |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "DERIVATION_SOURCE_ABSENT" in rules_for(data, SUBJECT)


def test_not_measured_without_a_reason_is_refused(tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / "PRELIMINARY_DATASHEET.md",
         "| NOT_MEASURED | reason:", "| NOT_MEASURED | ")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "NOT_MEASURED_WITHOUT_A_REASON" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_an_unresolved_placeholder_is_refused(tmp_path):
    project = released(tmp_path)
    edit(docs_dir(project) / "RELEASE_NOTES.md",
         "## 4. Known Limitations",
         "## 4. Known Limitations\n\n- TODO: fill this in")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "UNRESOLVED_PLACEHOLDER" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


# ═══════════════════ the flow's own evaluator, end to end ══════════════════
def _declared_clause() -> str:
    for line in FLOW_YAML.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- program_exit_zero:") \
                and "release_docs_check" in stripped and "--arm ic" in stripped:
            return stripped.split(":", 1)[1].strip().strip('"')
    raise AssertionError("step 37.5ic declares no release_docs_check ic clause")


def test_the_invocation_the_flow_declares_is_one_this_gate_accepts(tmp_path):
    """A clause the program's own parser rejects measures nothing.

    argparse's rc 2 IS the flow's VACUOUS_PASS tier, so a mis-declared clause
    does not go red — it passes vacuously, on every project, forever.
    """
    clause = _declared_clause()
    argv = clause.split()
    assert argv[0] == "release_docs_check"
    project = released(tmp_path)
    result = subprocess.run([sys.executable, str(GATE), *argv[1:]],
                            cwd=project, capture_output=True, text=True)
    assert "the following arguments are required" not in result.stderr, result.stderr
    assert not (result.returncode == 2 and "error:" in result.stderr), result.stderr
    assert result.returncode == RC_PASS, result.stdout + result.stderr


def test_the_flows_own_evaluator_fails_a_defective_release_and_passes_a_clean_one(
        tmp_path):
    spec = importlib.util.spec_from_file_location(
        "_fcc_release_docs_ic_probe", GATE.parent / "flow_compliance_check.py")
    fcc = importlib.util.module_from_spec(spec)
    sys.modules["_fcc_release_docs_ic_probe"] = fcc
    spec.loader.exec_module(fcc)
    clause = _declared_clause()

    clean = released(tmp_path, "clean")
    ok_clean, out_clean = fcc._check_program_exit_zero(clean, clause)
    assert ok_clean, (
        f"a clean release must still PASS, or this gate is red for everyone: "
        f"{out_clean[:200]!r}")

    harmed = released(tmp_path, "harmed")
    (harmed / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
        build_gds_without_geometry(SUBJECT))
    ok_bad, out_bad = fcc._check_program_exit_zero(harmed, clause)
    assert not ok_bad, (
        f"the flow scored a release whose GDS carries no geometry as a gate "
        f"pass: {out_bad[:200]!r}")
    assert "__VACUOUS_HINT__" not in out_bad, (
        "the refusal reached the flow's VACUOUS_PASS tier, which is a PASS")


@pytest.mark.parametrize("defect", [
    "section", "pin_count", "die_size", "app_note", "hollow_gds",
    "undocumented",
])
def test_no_refusal_ever_lands_in_a_pass_tier_exit_code(tmp_path, defect):
    """rc 2 / rc 3 are PASS tiers here; a content-earned refusal is rc 1."""
    project = released(tmp_path, defect)
    subject = docs_dir(project, SUBJECT)
    if defect == "section":
        drop_section(subject / "PRELIMINARY_DATASHEET.md", "5. Timing")
    elif defect == "pin_count":
        edit(subject / "PRELIMINARY_DATASHEET.md",
             "| Signal pins | 3 |", "| Signal pins | 7 |")
    elif defect == "die_size":
        edit(subject / "PRELIMINARY_DATASHEET.md",
             "| Die width (um) | 240 |", "| Die width (um) | 180 |")
    elif defect == "app_note":
        note = subject / "AN001_TYPICAL_APPLICATION.md"
        note.write_text(note.read_text(encoding="utf-8")
                        + "\n- **MANDATORY** `INVENTED` — nothing supports "
                          "this (derived from `input/project.json`)\n",
                        encoding="utf-8")
    elif defect == "hollow_gds":
        (project / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
            build_gds_without_geometry(SUBJECT))
    else:
        shutil.rmtree(project / "phase3/stage4/documentation" / "ic")
    assert check(project).returncode == RC_FAIL


def test_the_ip_arm_is_untouched_by_the_ic_arms_new_checks(tmp_path):
    """The ic arm's substance and die-size checks must not run on an IP kit —
    step 37.5ip already declares `digital_hardmacro_check` in the same
    `all_of`, and a second substance audit would give that step two verdicts
    over one population."""
    from _release_kit import build_project as build_ip_project
    ip_project = build_ip_project(tmp_path / "ip")
    subprocess.run([sys.executable,
                    str(GATE.parent / "ip_release_docs_gen.py"),
                    str(ip_project)], capture_output=True, text=True, check=True)
    out = ip_project / "r.json"
    result = subprocess.run(
        [sys.executable, str(GATE), str(ip_project), "--arm", "ip",
         "--json", str(out)], capture_output=True, text=True)
    assert result.returncode == RC_PASS, result.stdout + result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    for detail in data["summary"]["releases"]:
        assert detail["die_size_cross_check"] == "NOT_APPLICABLE"
        assert detail["artefact_substance"] == "NOT_APPLICABLE"
        assert detail["pin_count_cross_check"] == "AGREES", (
            "the ip arm's own cross-check stopped running")
