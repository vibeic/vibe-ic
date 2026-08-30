"""tests/test_ic_release_docs_gen.py — step 37.5ic's PRODUCT-document producer.

WHAT IS BEING DEFENDED HERE, AND WHY IT IS NOT "THE DOCUMENTS ARE GENERATED"
===========================================================================
Step 37.5ic already had a document generator before this one. ``tapeout_docs_gen``
writes the sign-off HTML and refuses to write anything for a run that is not
clean — and every one of the 17 properties it decides is read from ONE artefact,
``phase3/final/metrics.json``, which is a set of NUMBERS ABOUT a layout and not
the layout.

That is the gap this producer closes, and the fixture below makes the gap
provable rather than asserted: ``METRICS_CLEAN`` carries all 17 properties CLEAN
in EVERY case in this file. So when a case plants a hollow GDS and the producer
refuses, the refusal cannot be the metrics half firing — the metrics half is
green by construction, and the only thing that changed is the bytes of an
artefact nothing had ever opened.

    A generator that writes a beautiful datasheet for a design with no geometry
    in its GDS is worse than no generator, because it launders an empty result
    into a document somebody signs.

Every case therefore:

  * asserts an EXACT exit code. rc 2 is "the question could not be put", rc 143
    is KILLED and rc 199 is a stall kill; none of them is a result, and a test
    that accepted ``!= 0`` would accept all three;
  * breaks exactly ONE artefact, so a future weakening of any single predicate
    turns exactly one test;
  * asserts NO DOCUMENT WAS WRITTEN, because the refusal that matters is the
    absence of the file — a document that says NOT RELEASABLE is a status line
    wearing a document's clothes, and it still gets copied and quoted;
  * REPAIRS the same defect and asserts rc 0. A producer that only ever refuses
    is a producer that will be switched off.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ic_release_kit import (  # noqa: E402
    CONTROL,
    MACRO,
    SUBJECT,
    build_gds,
    build_gds_without_geometry,
    build_project,
    docs_dir,
)
from _release_docs_contract import (  # noqa: E402
    DERIVED_COLUMN,
    IC_DOCS,
    MANIFEST_NAME,
    NOT_MEASURED,
    REASON_PREFIX,
)

PROG = Path(__file__).resolve().parents[1] / "ic_release_docs_gen.py"
FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2
#: rc values `flow_compliance_check` scores in a PASS tier: 0 PASS,
#: 2 VACUOUS_PASS, 3 PASS_WITH_WAIVERS.
PASS_TIER_RCS = (0, 2, 3)

DEF_REL = "phase3/stage3/pnr/routed.def"
LEF_REL = f"phase3/analog/hardmacro/{MACRO}/{MACRO}.lef"
STA_REL = "reports/phase3/sta/post_route_summary.json"
POWER_REL = "reports/phase3/power.json"
DRC_REL = "reports/phase3/drc_signoff.json"
LVS_REL = "reports/phase3/lvs_verdict.json"


def run(project: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project), *extra],
                          capture_output=True, text=True)


def documentation(project: Path) -> Path:
    return project / "phase3" / "stage4" / "documentation"


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path.name} does not contain {old!r} to edit"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def derived_rows(text: str):
    """Every `Derived from` row of one document, as (label, value, third)."""
    rows, in_table = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 3:
            in_table = False
            continue
        if cells[2] == DERIVED_COLUMN:
            in_table = True
            continue
        if in_table and not (set(cells[0]) <= {"-", ":"} and cells[0]):
            rows.append(tuple(cells))
    return rows


# ═════════════════════ the clean run, and what it produces ═════════════════
def test_a_signed_off_die_gets_its_product_document_set(tmp_path):
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    result = run(project)
    assert result.returncode == RC_PASS, result.stdout + result.stderr
    for spec in IC_DOCS:
        path = docs_dir(project) / spec.filename
        if spec.requirement == "required":
            assert path.is_file(), f"{spec.filename} is required and absent"
    assert (docs_dir(project) / MANIFEST_NAME).is_file()


def test_one_directory_per_release_including_the_single_release_case(tmp_path):
    """A tree with two sign-off streams has two document sets, and the SHAPE of
    the one-release case must be the shape the two-release case takes."""
    one = build_project(tmp_path / "one", releases=(SUBJECT,))
    assert run(one).returncode == RC_PASS
    assert (documentation(one) / "ic" / SUBJECT).is_dir()

    two = build_project(tmp_path / "two")
    assert run(two).returncode == RC_PASS
    assert {p.name for p in (documentation(two) / "ic").iterdir()} == {
        SUBJECT, CONTROL}


def test_every_quantitative_field_is_derived_or_says_it_was_not(tmp_path):
    """The rule the whole feature rests on, checked over every row written."""
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    assert run(project).returncode == RC_PASS
    seen = 0
    for path in sorted(docs_dir(project).glob("*.md")):
        for label, value, third in derived_rows(path.read_text(encoding="utf-8")):
            seen += 1
            if value == NOT_MEASURED:
                assert third.startswith(REASON_PREFIX), (
                    f"{path.name}: '{label}' is {NOT_MEASURED} with no reason")
                assert third[len(REASON_PREFIX):].strip(), (
                    f"{path.name}: '{label}' gives an EMPTY reason")
            else:
                m = re.search(r"`([^`]+)`", third)
                assert m, (f"{path.name}: '{label}' = {value!r} with no "
                           f"artefact path behind it — a hand-typed number")
                assert (project / m.group(1)).exists(), (
                    f"{path.name}: '{label}' cites `{m.group(1)}`, which does "
                    f"not resolve")
    assert seen > 20, f"only {seen} derived rows written; the check is vacuous"


def test_the_manifest_counts_agree_with_a_recount_of_the_documents(tmp_path):
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    assert run(project).returncode == RC_PASS
    manifest = (docs_dir(project) / MANIFEST_NAME).read_text(encoding="utf-8")
    import yaml
    doc = yaml.safe_load(manifest)
    derived = holes = 0
    for path in sorted(docs_dir(project).glob("*.md")):
        for _label, value, _third in derived_rows(path.read_text(encoding="utf-8")):
            if value == NOT_MEASURED:
                holes += 1
            else:
                derived += 1
    assert doc["derived_fields"] == derived
    assert doc["not_measured_fields"] == holes
    assert doc["arm"] == "ic"


def test_the_conditional_document_is_decided_by_an_artefact_not_by_eye(tmp_path):
    """"Conditional" is where a document set quietly loses a required document."""
    rich = build_project(tmp_path / "rich", releases=(SUBJECT,),
                         register_rich=True)
    assert run(rich).returncode == RC_PASS
    assert (docs_dir(rich) / "USER_REFERENCE_MANUAL.md").is_file()

    plain = build_project(tmp_path / "plain", releases=(SUBJECT,),
                          register_rich=False)
    assert run(plain).returncode == RC_PASS
    assert not (docs_dir(plain) / "USER_REFERENCE_MANUAL.md").exists()
    import yaml
    doc = yaml.safe_load((docs_dir(plain) / MANIFEST_NAME).read_text())
    assert doc["register_rich"] is False
    assert doc["register_rich_source"].endswith("L4_REGMAP.json"), (
        "the decision was recorded without the artefact that made it")


def test_a_layer_the_run_does_not_carry_becomes_a_hole_not_a_default(tmp_path):
    project = build_project(tmp_path / "p", releases=(SUBJECT,),
                            with_layers=False)
    assert run(project).returncode == RC_PASS
    text = (docs_dir(project) / "PRELIMINARY_DATASHEET.md").read_text()
    assert NOT_MEASURED in text
    assert "## 7. What Is Not Measured" in text
    for _label, value, third in derived_rows(text):
        if value == NOT_MEASURED:
            assert third.startswith(REASON_PREFIX)


def test_a_chip_that_places_no_macro_is_a_hole_not_a_refusal(tmp_path):
    """ABSENT IS NOT EMPTY. A chip built entirely from standard cells places no
    macro abstract, and refusing it would make the LEF rule fire on a correct
    run and be switched off within a week."""
    project = build_project(tmp_path / "p", releases=(SUBJECT,),
                            with_macro=False)
    result = run(project)
    assert result.returncode == RC_PASS, result.stdout + result.stderr
    text = (docs_dir(project) / "PRELIMINARY_DATASHEET.md").read_text()
    assert "Placed macro abstracts" in text
    assert "places no macro abstract" in text


def test_the_application_note_never_originates_a_mandatory_constraint(tmp_path):
    """Every ID the AN states must also stand in a constraint-bearing document."""
    from _release_docs_contract import CONSTRAINT_BEARING, MANDATORY_RE
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    assert run(project).returncode == RC_PASS

    def ids(name):
        path = docs_dir(project) / name
        if not path.is_file():
            return set()
        return {m.group("id") for m in
                (MANDATORY_RE.match(line)
                 for line in path.read_text(encoding="utf-8").splitlines())
                if m}

    bearing = set()
    for name in CONSTRAINT_BEARING["ic"]:
        bearing |= ids(name)
    note = ids("AN001_TYPICAL_APPLICATION.md")
    assert note, "the note restates no constraint; the check is vacuous"
    assert note <= bearing, f"only in the note: {sorted(note - bearing)}"


# ═══════ the refusals — one artefact class each, metrics CLEAN throughout ═══
#: (case id, the rule the refusal must name, how to plant it)
HOLLOW = [
    ("gds_no_geometry", "GDS_NO_GEOMETRY",
     lambda p: (p / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
         build_gds_without_geometry(SUBJECT))),
    ("def_no_diearea", "DEF_NO_DIEAREA",
     lambda p: edit(p / DEF_REL, "DIEAREA ( 0 0 ) ( 240000 160000 ) ;\n", "")),
    ("def_no_components", "DEF_NO_COMPONENTS",
     lambda p: (p / DEF_REL).write_text(re.sub(
         r"COMPONENTS 4 ;.*?END COMPONENTS", "COMPONENTS 0 ;\nEND COMPONENTS",
         (p / DEF_REL).read_text(encoding="utf-8"), flags=re.S),
         encoding="utf-8")),
    ("def_no_pins", "DEF_NO_PINS",
     lambda p: (p / DEF_REL).write_text(re.sub(
         r"PINS 5 ;.*?END PINS", "PINS 0 ;\nEND PINS",
         (p / DEF_REL).read_text(encoding="utf-8"), flags=re.S),
         encoding="utf-8")),
    ("lef_no_size", "LEF_NO_SIZE",
     lambda p: edit(p / LEF_REL, "  SIZE 60.000 BY 40.000 ;\n", "")),
    ("lef_no_pin", "LEF_NO_PIN",
     lambda p: (p / LEF_REL).write_text(re.sub(
         r"  PIN .*?END \w+\n", "",
         (p / LEF_REL).read_text(encoding="utf-8"), flags=re.S),
         encoding="utf-8")),
    ("sta_no_slack", "STA_NO_SLACK",
     lambda p: (p / STA_REL).write_text(json.dumps(
         {"program": "sta_report_check", "passed": True,
          "summary": {"corners": []}}), encoding="utf-8")),
    ("power_no_total", "POWER_NO_TOTAL",
     lambda p: (p / POWER_REL).write_text(json.dumps(
         {"program": "eda_report_audit:power", "passed": True,
          "summary": {}}), encoding="utf-8")),
    ("drc_not_run", "DRC_SIGNOFF_NOT_RUN",
     lambda p: (p / DRC_REL).write_text(json.dumps(
         {"program": "drc_report_check", "passed": False, "findings": [],
          "summary": {"files_found": 0, "checked": False,
                      "terminal_verdict": "NOT_CHECKED"}}), encoding="utf-8")),
    ("lvs_no_verdict", "LVS_NO_VERDICT",
     lambda p: (p / LVS_REL).write_text(json.dumps(
         {"program": "lvs_report_check", "summary": {}}), encoding="utf-8")),
]


@pytest.mark.parametrize("case,rule,plant", HOLLOW,
                         ids=[c for c, _r, _p in HOLLOW])
def test_a_hollow_artefact_is_refused_and_the_refusal_names_the_rule(
        tmp_path, case, rule, plant):
    """The acceptance for this whole landing, one artefact class at a time.

    `metrics.json` is CLEAN in this fixture — all 17 sign-off properties — so a
    refusal here cannot be the metrics half firing. The only thing that changed
    is the substance of an artefact the metrics half never opens.
    """
    project = build_project(tmp_path / case, releases=(SUBJECT,))
    plant(project)
    result = run(project)
    assert result.returncode == RC_FAIL, result.stdout + result.stderr
    assert rule in result.stderr, result.stderr
    assert not documentation(project).exists(), (
        "a run whose artefacts carry no substance published a document set; "
        "the absence of the file IS the signal")


@pytest.mark.parametrize("case,rule,plant", HOLLOW,
                         ids=[c for c, _r, _p in HOLLOW])
def test_the_repaired_run_writes_its_documents_again(tmp_path, case, rule, plant):
    """A producer that only ever refuses is a producer that gets switched off."""
    project = build_project(tmp_path / case, releases=(SUBJECT,))
    plant(project)
    assert run(project).returncode == RC_FAIL
    # RESTORE: rebuild the same tree, unbroken.
    repaired = build_project(tmp_path / (case + "_ok"), releases=(SUBJECT,))
    result = run(repaired)
    assert result.returncode == RC_PASS, result.stdout + result.stderr
    assert (docs_dir(repaired) / "PRELIMINARY_DATASHEET.md").is_file()


@pytest.mark.parametrize("case,rule,plant", HOLLOW,
                         ids=[c for c, _r, _p in HOLLOW])
def test_no_refusal_ever_lands_in_a_pass_tier_exit_code(tmp_path, case, rule,
                                                        plant):
    """rc 2 and rc 3 are PASS tiers here; a content-earned refusal is rc 1.

    `tapeout_docs_gen` shipped exiting 2 on precisely the runs it had just
    refused to document, and `flow_compliance_check` scored every one of them
    VACUOUS_PASS. Measured on origin/main 69ce9260d.
    """
    project = build_project(tmp_path / case, releases=(SUBJECT,))
    plant(project)
    assert run(project).returncode not in PASS_TIER_RCS


def test_a_refusal_reports_every_hollow_class_not_just_the_first(tmp_path):
    """One report, not two passes: a run repaired one class at a time is a run
    refused once per class for reasons it could have been told at once."""
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    (project / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
        build_gds_without_geometry(SUBJECT))
    (project / LVS_REL).write_text(json.dumps({"summary": {}}),
                                   encoding="utf-8")
    result = run(project)
    assert result.returncode == RC_FAIL
    assert "GDS_NO_GEOMETRY" in result.stderr
    assert "LVS_NO_VERDICT" in result.stderr


def test_a_metrics_property_that_is_not_clean_is_refused_by_the_existing_verdict(
        tmp_path):
    """The METRICS half, unchanged and NOT re-decided — `release_blockers` owns it."""
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    metrics = project / "phase3" / "final" / "metrics.json"
    doc = json.loads(metrics.read_text(encoding="utf-8"))
    doc["timing__setup__ws"] = -1.53
    metrics.write_text(json.dumps(doc), encoding="utf-8")
    result = run(project)
    assert result.returncode == RC_FAIL, result.stdout + result.stderr
    assert "timing__setup__ws" in result.stderr
    assert "release_blockers" in result.stderr, (
        "the refusal must name the verdict it deferred to, not restate one")
    assert not documentation(project).exists()


# ═══════════════════════════ the vacuous tier ══════════════════════════════
def test_an_empty_project_is_the_vacuous_tier_and_says_it_is_not_a_pass(tmp_path):
    """The sentence the owner asked for, and it is not written here.

    `_vacuous_exit.announce_vacuous` already emits "this is NOT a pass over the
    design" on the rc-independent channel, so this producer IMPORTS the
    disclosure rather than spelling a second one. A second spelling of a tier is
    a second policy, and two policies is how one of them stops being enforced.
    """
    project = tmp_path / "empty"
    (project / "input").mkdir(parents=True)
    (project / "input" / "project.json").write_text(
        json.dumps({"design": "widget", "pdk": "gf180mcuD"}), encoding="utf-8")
    result = run(project)
    assert result.returncode == RC_VACUOUS, result.stdout + result.stderr
    assert "VACUOUS_PASS:" in result.stderr
    assert "this is NOT a pass over the design" in result.stderr
    assert not documentation(project).exists()


def test_the_vacuous_report_names_where_it_looked_for_each_class(tmp_path):
    """An absence verdict that does not name its denominator cannot be re-checked."""
    project = tmp_path / "empty"
    project.mkdir(parents=True)
    result = run(project)
    assert result.returncode == RC_VACUOUS
    for class_id in ("gds", "def", "lef", "sta", "power", "drc", "lvs"):
        assert f"{class_id}:" in result.stdout, result.stdout


def test_an_absent_project_directory_is_refused_not_documented(tmp_path):
    result = run(tmp_path / "nope")
    assert result.returncode == RC_VACUOUS
    assert "VACUOUS_PASS:" in result.stderr


def test_a_routed_run_with_no_signoff_layout_names_no_release(tmp_path):
    """Substance everywhere and no GDS: there is nothing to write a datasheet
    ABOUT, and naming the release after anything else would invent an identifier."""
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    (project / "phase3/stage4/gds" / f"{SUBJECT}.gds").unlink()
    result = run(project)
    assert result.returncode == RC_VACUOUS, result.stdout + result.stderr
    assert "no_signoff_layout" in result.stderr
    assert not documentation(project).exists()


# ═════════════════ the flow declares what this producer writes ═════════════
def test_the_step_declares_every_document_this_producer_writes(tmp_path):
    """Both directions, from the FLOW's own text against a REAL run.

    A declared output no producer writes can never be produced, and a produced
    artefact no step declares is invisible to the audit. d4/criteria_match
    caught 37.5ic's pair disagreeing once already.
    """
    import fnmatch
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    assert run(project).returncode == RC_PASS
    written = {p.relative_to(project).as_posix()
               for p in documentation(project).rglob("*") if p.is_file()}
    declared = [line.strip().lstrip("- ").strip('"')
                for line in FLOW_YAML.read_text(encoding="utf-8").splitlines()
                if "phase3/stage4/documentation/ic/" in line
                and line.strip().startswith('- "')]
    assert declared, "step 37.5ic declares no documentation output any more"
    for spec in declared:
        assert any(fnmatch.fnmatch(w, spec) for w in written), (
            f"the flow declares {spec!r} and this producer wrote "
            f"{sorted(written)}")


def test_the_producer_is_dispatched_by_the_runner_and_a_refusal_publishes_nothing(
        tmp_path):
    """The runner must EXECUTE the producer; a `programs:` row is not that."""
    runner_path = Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py"
    text = runner_path.read_text(encoding="utf-8")
    assert text.count('PROGRAMS_DIR / "ic_release_docs_gen.py"') == 1
    assert text.count("plan.append(step_ic_release_docs_gen(project))") == 1, (
        "a producer helper that main never calls is still an orphan")

    import phase3_one_shot_runner as runner

    clean = build_project(tmp_path / "clean", releases=(SUBJECT,))
    result = runner.step_ic_release_docs_gen(clean)
    assert result.status == "PASS", result
    assert result.extras.get("flow_step") == "37.5ic"
    assert any(p.endswith("PRELIMINARY_DATASHEET.md")
               for p in result.output_files)

    harmed = build_project(tmp_path / "harmed", releases=(SUBJECT,))
    (harmed / "phase3/stage4/gds" / f"{SUBJECT}.gds").write_bytes(
        build_gds_without_geometry(SUBJECT))
    harmed_result = runner.step_ic_release_docs_gen(harmed)
    assert harmed_result.status == "SKIP", harmed_result
    assert harmed_result.extras.get("producer_rc") == RC_FAIL, harmed_result
    assert not documentation(harmed).exists(), (
        "a run whose GDS carries no geometry published release documents")


def test_the_step_declares_this_producer_in_its_programs_list():
    text = FLOW_YAML.read_text(encoding="utf-8")
    start = text.index("  - id: 37.5ic")
    block = text[start:text.index("required_outputs:", start)]
    assert "- ic_release_docs_gen" in block, (
        "the producer runs but the step does not declare it; a program the "
        "flow does not name is a program the audit cannot account for")


def test_the_existing_signoff_generator_is_not_replaced():
    """EXTEND, DO NOT REPLACE. `tapeout_docs_gen` stays exactly where it is."""
    text = FLOW_YAML.read_text(encoding="utf-8")
    start = text.index("  - id: 37.5ic")
    block = text[start:text.index("  - id: 38", start)]
    assert "- tapeout_docs_gen" in block
    assert 'program_exit_zero: "tapeout_docs_gen --project . ' in block
    assert '"reports/phase3/docs/SIGNOFF_*.html"' in block
    assert '"reports/phase3/docs/BRIEF_*.html"' in block


# ═══════════════════════════════ NDA ═══════════════════════════════════════
#: Substrings that must appear in NOTHING this producer emits. Narrow on
#: purpose: this is a leak census, not a prose critic. The open PDKs this flow
#: targets are NOT on it and must never be added.
FORBIDDEN = ("tsmc", "samsung foundry", "globalfoundries", "umc ", "smic",
             "intel foundry", "28nm", "16nm", "7nm", "5nm", "3nm",
             "automotive grade", "aec-q100", "jedec qualification")


def test_nothing_this_producer_writes_names_a_commercial_process_or_programme(
        tmp_path):
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    assert run(project).returncode == RC_PASS
    for path in sorted(documentation(project).rglob("*")):
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN:
            assert token not in body, f"{path.name} names {token!r}"


def test_the_qualification_section_is_titled_by_question_and_names_no_programme(
        tmp_path):
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    assert run(project).returncode == RC_PASS
    text = (docs_dir(project) / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "## 5. Third-Party Qualification Status" in text
    assert "names no programme" in text
