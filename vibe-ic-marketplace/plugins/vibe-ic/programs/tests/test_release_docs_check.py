"""tests/test_release_docs_check.py — the gate must REFUSE, and NAME what.

WHY THIS FILE IS SHAPED THE WAY IT IS
=====================================
Measured on this tree at v1.13.42: SIX on-pass gates could only ever answer
rc 2. Every declared command carried neither `--compliance` nor
`--stage-verdict`, so `stage_passed()` returned UNESTABLISHED and the program
exited before consulting a single rule — on every input, forever. The flow
declared the review, the audit measured a wiring, the tests passed, and no
review had ever run.

So the acceptance for a documentation gate is NOT "the documents are
generated". It is:

    THE GATE REFUSES A REAL DEFECT, AND THE REFUSAL NAMES IT.

Every case below therefore:

  * asserts an EXACT exit code. rc 2 is "the question could not be put",
    rc 143 is KILLED and rc 199 is a stall kill; none of them is a result, and
    a test that accepts `!= 0` would accept all three;
  * breaks exactly ONE thing, so a future weakening of any single predicate
    turns exactly one test;
  * runs over a project holding a SECOND, UNTOUCHED release, and asserts that
    control release stays green in the SAME invocation. A refusal that also
    reddens the untouched release is environmental, not content-earned;
  * REPAIRS the same defect and asserts the gate returns to rc 0. A gate that
    only ever goes red is a gate that will be switched off.
"""
from __future__ import annotations

import importlib.util
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
from _release_docs_contract import MANIFEST_NAME  # noqa: E402

GATE = Path(__file__).resolve().parents[1] / "release_docs_check.py"
GEN = Path(__file__).resolve().parents[1] / "ip_release_docs_gen.py"
FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2
#: rc values `flow_compliance_check` scores in a PASS tier.
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
        [sys.executable, str(GATE), str(project), "--arm", "ip", *extra],
        capture_output=True, text=True)


def report(project: Path):
    out = project / "release_docs.json"
    result = check(project, "--json", str(out))
    return result, json.loads(out.read_text(encoding="utf-8"))


def rules_for(data, release: str) -> set:
    """The rules that REFUSED this release — severity ERROR only.

    Collecting every severity would make these assertions survive a mutation
    that downgrades a rule to INFO, which is exactly how a gate gets quietly
    disarmed: the finding is still emitted, still appears in the report, and no
    longer fails anything. MEASURED while writing this file — with
    `REQUIRED_SECTION_ABSENT` downgraded to INFO the whole suite stayed green.
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


# ═══════════════════════════ the control arm ═══════════════════════════════

def test_a_clean_release_passes_and_the_gate_says_how_much_it_looked_at(tmp_path):
    project = released(tmp_path)
    result = check(project)
    assert result.returncode == RC_PASS, result.stdout + result.stderr
    assert "[PASS] release_docs_check" in result.stdout
    # A scan of two releases and a scan of none must not print the same
    # sentence — the class `gate_discloses_denominator_check` exists for.
    assert "examined 2 release(s)" in result.stdout
    assert "derived row(s)" in result.stdout


def test_both_documented_releases_are_judged_not_just_the_first(tmp_path):
    project = released(tmp_path)
    _result, data = report(project)
    assert {d["release"] for d in data["summary"]["releases"]} == {SUBJECT,
                                                                  CONTROL}
    assert data["summary"]["rows_examined"] > 0


# ═══════════════════ F1 — a missing required section ═══════════════════════

def _drop_section(path: Path, heading: str) -> None:
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


def test_a_missing_required_section_is_refused_and_the_section_is_named(tmp_path):
    project = released(tmp_path)
    _drop_section(docs_dir(project, SUBJECT) / "IP_INTEGRATION_GUIDE.md",
                  "7. Test And Debug Access")

    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout
    assert "REQUIRED_SECTION_ABSENT" in rules_for(data, SUBJECT)
    named = [f["message"] for f in data["findings"]
             if f["rule"] == "REQUIRED_SECTION_ABSENT"]
    assert any("7. Test And Debug Access" in m for m in named), named
    assert any("IP_INTEGRATION_GUIDE.md" in m for m in named), named
    assert verdict_of(data, CONTROL) is True, (
        "the control release went red for a defect in the other release")


def test_the_repaired_release_passes_again(tmp_path):
    project = released(tmp_path)
    _drop_section(docs_dir(project, SUBJECT) / "IP_INTEGRATION_GUIDE.md",
                  "7. Test And Debug Access")
    assert check(project).returncode == RC_FAIL
    generate(project)                      # the repair: regenerate the set
    assert check(project).returncode == RC_PASS


def test_a_missing_required_document_is_refused(tmp_path):
    project = released(tmp_path)
    (docs_dir(project, SUBJECT) / "ERRATA.md").unlink()
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "REQUIRED_DOCUMENT_ABSENT" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_section_that_drifted_out_of_order_is_refused(tmp_path):
    """A section that moved is a section a reader stops finding."""
    project = released(tmp_path)
    path = docs_dir(project, SUBJECT) / "ERRATA.md"
    text = path.read_text(encoding="utf-8")
    head, _, tail = text.partition("## 2. Open Errata")
    body, _, rest = tail.partition("## 3. Closed Errata")
    path.write_text(head + "## 3. Closed Errata" + rest.split("## 4.")[0]
                    + "## 2. Open Errata" + body
                    + "## 4." + rest.split("## 4.", 1)[1], encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "REQUIRED_SECTION_OUT_OF_ORDER" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


# ═════════════ F2 — a pin count that disagrees with the netlist ════════════

def _restate_signal_pins(path: Path, count: int, total: int) -> None:
    """Restate BOTH interface rows, so exactly ONE predicate is broken.

    Editing the signal count alone also breaks the total's arithmetic, and the
    two findings would then pin each other's tests: downgrade either rule and
    the other still reddens the same case. Moving the total with it leaves the
    document internally consistent and disagreeing with the netlist and nothing
    else — which is what a stale hand-maintained interface table actually looks
    like, because whoever edited it kept the sums right.
    """
    edit(path, "| Signal pins | 3 |", f"| Signal pins | {count} |")
    edit(path, "| Pin count (total) | 5 |", f"| Pin count (total) | {total} |")


def test_a_pin_count_that_disagrees_with_the_netlist_is_refused(tmp_path):
    """BOTH SIDES NAMED. "The pin count is wrong" is not actionable."""
    project = released(tmp_path)
    _restate_signal_pins(docs_dir(project, SUBJECT) / "IP_DATASHEET.md", 4, 6)

    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout
    assert rules_for(data, SUBJECT) == {"PIN_COUNT_DISAGREES_WITH_NETLIST"}, (
        "exactly one predicate was broken and more than one refused")
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "PIN_COUNT_DISAGREES_WITH_NETLIST")
    assert "= 4" in message, message
    assert "3 logical port(s)" in message, message
    assert f"{SUBJECT}.lef" in message and f"{SUBJECT}.v" in message, message
    assert verdict_of(data, CONTROL) is True


def test_a_total_that_does_not_equal_its_parts_is_refused(tmp_path):
    """A Verilog view omits the supplies, so the total is settled by arithmetic."""
    project = released(tmp_path)
    edit(docs_dir(project, SUBJECT) / "IP_DATASHEET.md",
         "| Pin count (total) | 5 |", "| Pin count (total) | 7 |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert rules_for(data, SUBJECT) == {"PIN_COUNT_INTERNALLY_INCONSISTENT"}
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "PIN_COUNT_INTERNALLY_INCONSISTENT")
    assert "= 7" in message and "sum to 5" in message, message
    assert verdict_of(data, CONTROL) is True


def test_a_correct_datasheet_does_not_mask_an_edited_guide(tmp_path):
    """Two documents state the interface; the first must not settle for both."""
    project = released(tmp_path)
    _restate_signal_pins(
        docs_dir(project, SUBJECT) / "IP_INTEGRATION_GUIDE.md", 5, 7)
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert rules_for(data, SUBJECT) == {"PIN_COUNT_DISAGREES_WITH_NETLIST"}
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "PIN_COUNT_DISAGREES_WITH_NETLIST"
                   and f["severity"] == "ERROR")
    assert "IP_INTEGRATION_GUIDE.md" in message, message
    assert verdict_of(data, CONTROL) is True


def test_the_repaired_pin_count_passes_again(tmp_path):
    project = released(tmp_path)
    datasheet = docs_dir(project, SUBJECT) / "IP_DATASHEET.md"
    _restate_signal_pins(datasheet, 4, 6)
    assert check(project).returncode == RC_FAIL
    edit(datasheet, "| Signal pins | 4 |", "| Signal pins | 3 |")
    edit(datasheet, "| Pin count (total) | 6 |", "| Pin count (total) | 5 |")
    assert check(project).returncode == RC_PASS


# ══════════ F3 — a mandatory constraint that lives only in an AN ═══════════

def test_a_mandatory_constraint_only_in_an_app_note_is_refused(tmp_path):
    """An AN is optional and is the first document dropped from a delivery."""
    project = released(tmp_path)
    note = docs_dir(project, SUBJECT) / "AN001_REFERENCE_INTEGRATION.md"
    note.write_text(
        note.read_text(encoding="utf-8").rstrip()
        + "\n- **MANDATORY** `CLOCK-JITTER-BUDGET` — the integrating clock "
          "tree must hold jitter under the budget this note assumes\n",
        encoding="utf-8")

    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout
    assert "MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE" in rules_for(data, SUBJECT)
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE")
    assert "CLOCK-JITTER-BUDGET" in message, message
    assert "AN001_REFERENCE_INTEGRATION.md" in message, message
    assert verdict_of(data, CONTROL) is True


def test_a_constraint_dropped_from_the_guide_but_left_in_the_note_is_refused(tmp_path):
    """The other direction of the same defect, and the likelier one."""
    project = released(tmp_path)
    guide = docs_dir(project, SUBJECT) / "IP_INTEGRATION_GUIDE.md"
    kept = [line for line in guide.read_text(encoding="utf-8").splitlines()
            if "`PLACEMENT-OUTLINE`" not in line]
    guide.write_text("\n".join(kept) + "\n", encoding="utf-8")

    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_constraint_restated_in_both_places_passes(tmp_path):
    """Restating is the AN's job. The rule must not refuse the correct case."""
    project = released(tmp_path)
    assert check(project).returncode == RC_PASS


def test_issue_1990_same_source_test_mode_disagreement_is_refused(tmp_path):
    """Two sections may not state different counts from the same artefact."""
    project = released(tmp_path)
    guide = docs_dir(project, SUBJECT) / "IP_INTEGRATION_GUIDE.md"
    source = "phase1/generated_docs/L7_TEST_DEBUG.json"
    line = (
        "- **MANDATORY** `TEST-MODE-CONSISTENCY-PROBE` — this IP declares "
        f"6 test mode(s) (derived from `{source}`)"
    )
    guide.write_text(
        guide.read_text(encoding="utf-8").rstrip() + "\n" + line + "\n",
        encoding="utf-8")

    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout + result.stderr
    assert rules_for(data, SUBJECT) == {"SOURCE_COUNT_INCONSISTENT"}
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "SOURCE_COUNT_INCONSISTENT")
    assert "IP_INTEGRATION_GUIDE.md" in message
    assert "6 test mode(s)" in message and "1" in message
    assert source in message
    assert verdict_of(data, CONTROL) is True

    edit(guide, "6 test mode(s)", "1 test mode(s)")
    assert check(project).returncode == RC_PASS


# ═════════════ F4 — a shipped-view digest that has gone stale ══════════════

def test_a_stale_shipped_view_digest_is_refused(tmp_path):
    """The documents describe a build that is not the one shipped."""
    project = released(tmp_path)
    view = project / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.v"
    view.write_text(view.read_text(encoding="utf-8") + "\n// a later build\n",
                    encoding="utf-8")

    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout
    assert "MANIFEST_DIGEST_STALE" in rules_for(data, SUBJECT)
    message = next(f["message"] for f in data["findings"]
                   if f["rule"] == "MANIFEST_DIGEST_STALE")
    assert f"{SUBJECT}.v" in message, message
    assert verdict_of(data, CONTROL) is True


def test_a_manifest_naming_a_file_that_is_not_there_is_refused(tmp_path):
    project = released(tmp_path)
    (project / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.gds").unlink()
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_FILE_ABSENT" in rules_for(data, SUBJECT)


def test_the_regenerated_manifest_passes_again(tmp_path):
    project = released(tmp_path)
    view = project / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.v"
    view.write_text(view.read_text(encoding="utf-8") + "\n// a later build\n",
                    encoding="utf-8")
    assert check(project).returncode == RC_FAIL
    generate(project)
    assert check(project).returncode == RC_PASS


# ══════════════ F5 — a value with no artefact behind it ════════════════════

def test_a_hand_typed_value_with_no_artefact_is_refused(tmp_path):
    project = released(tmp_path)
    datasheet = docs_dir(project, SUBJECT) / "IP_DATASHEET.md"
    edit(datasheet, f"| Macro area (um^2) | 9600 | `phase3/stage4/hardmacro/{SUBJECT}.lef` |",
         "| Macro area (um^2) | 9600 | measured by hand |")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "FIELD_NOT_DERIVED" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_citation_that_resolves_to_nothing_is_refused(tmp_path):
    """A citation that resolves to nothing binds nothing."""
    project = released(tmp_path)
    edit(docs_dir(project, SUBJECT) / "IP_DATASHEET.md",
         f"`phase3/stage4/hardmacro/{SUBJECT}.lib`",
         "`phase3/stage4/hardmacro/some_other_build.lib`")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "DERIVATION_SOURCE_ABSENT" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_not_measured_without_a_reason_is_refused(tmp_path):
    """'We did not look' is only honest when it says why."""
    project = released(tmp_path)
    datasheet = docs_dir(project, SUBJECT) / "IP_DATASHEET.md"
    text = datasheet.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines()
                if l.startswith("| Tree SHA | NOT_MEASURED |"))
    datasheet.write_text(
        text.replace(line, "| Tree SHA | NOT_MEASURED |  |"), encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "NOT_MEASURED_WITHOUT_A_REASON" in rules_for(data, SUBJECT)


def test_an_unresolved_placeholder_is_refused(tmp_path):
    project = released(tmp_path)
    errata = docs_dir(project, SUBJECT) / "ERRATA.md"
    errata.write_text(errata.read_text(encoding="utf-8")
                      + "\n- TODO: fill this in before shipping\n",
                      encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "UNRESOLVED_PLACEHOLDER" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


# ══════════════════ F6 — a manifest count nobody re-derived ════════════════

def test_a_manifest_count_that_drifted_is_refused(tmp_path):
    project = released(tmp_path)
    manifest = docs_dir(project, SUBJECT) / MANIFEST_NAME
    lines = manifest.read_text(encoding="utf-8").splitlines()
    stated = next(l for l in lines if l.startswith("derived_fields:"))
    manifest.write_text(
        "\n".join("derived_fields: 999" if l == stated else l for l in lines)
        + "\n", encoding="utf-8")
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_COUNT_DISAGREES" in rules_for(data, SUBJECT)
    assert verdict_of(data, CONTROL) is True


def test_a_release_with_no_manifest_is_refused(tmp_path):
    project = released(tmp_path)
    (docs_dir(project, SUBJECT) / MANIFEST_NAME).unlink()
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_ABSENT" in rules_for(data, SUBJECT)


def test_a_tree_sha_that_is_neither_a_commit_nor_not_measured_is_refused(tmp_path):
    project = released(tmp_path)
    manifest = docs_dir(project, SUBJECT) / MANIFEST_NAME
    edit(manifest, 'tree_sha: "NOT_MEASURED"', 'tree_sha: "the latest build"')
    result, data = report(project)
    assert result.returncode == RC_FAIL
    assert "MANIFEST_TREE_SHA_INVALID" in rules_for(data, SUBJECT)


# ═══════════════ absence: the shape this gate was written for ══════════════

def test_a_kit_that_ships_with_no_documentation_is_a_refusal_not_a_skip(tmp_path):
    """THE DEFECT THIS GATE EXISTS FOR, and rc 2 would reinstate it.

    Before this landed, step 37.5ip's required_outputs were the four views and
    nothing else. A gate that answered the vacuous tier here would credit
    exactly that state as a pass.
    """
    project = build_project(tmp_path / "p")          # kit, no generate()
    result, data = report(project)
    assert result.returncode == RC_FAIL, result.stdout + result.stderr
    assert result.returncode not in (RC_VACUOUS,), (
        "a delivered kit with no documents was credited to the vacuous tier")
    assert rules_for(data, SUBJECT) == {"RELEASE_DOCUMENTATION_ABSENT"}
    assert rules_for(data, CONTROL) == {"RELEASE_DOCUMENTATION_ABSENT"}
    message = next(f["message"] for f in data["findings"])
    assert "hardmacro" in message, message


def test_no_kit_and_no_documents_is_the_vacuous_tier_and_discloses_it(tmp_path):
    """The ONE vacuous state, and it says where it looked."""
    project = build_project(tmp_path / "p", packages=())
    result = check(project)
    assert result.returncode == RC_VACUOUS, result.stdout + result.stderr
    assert "VACUOUS_PASS:" in result.stderr
    assert "no_release_to_examine" in result.stderr
    assert "examined 0 release(s)" in result.stdout


def test_an_absent_project_directory_does_not_answer_a_verdict(tmp_path):
    result = check(tmp_path / "nope")
    assert result.returncode == RC_VACUOUS
    assert "VACUOUS_PASS:" in result.stderr


# ══════════════════ the gate is wired, and the wiring works ════════════════

def _declared_clause() -> str:
    """The clause step 37.5ip declares for THIS arm.

    Matched on `--arm ip` rather than on position: both arms now declare a
    `release_docs_check` clause, and "the first one in the file" is a selector
    whose answer moves when the flow is reordered.
    """
    for line in FLOW_YAML.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if ("release_docs_check" in line and "--arm ip" in line
                and line.startswith("- program_exit_zero:")):
            return line.split(":", 1)[1].strip().strip('"')
    raise AssertionError("no release_docs_check ip gate clause in the flow yaml")


def test_the_invocation_the_flow_declares_is_one_this_gate_accepts(tmp_path):
    """A clause the program's own parser rejects measures nothing.

    argparse's rc 2 IS the flow's VACUOUS_PASS tier, so a mis-declared clause
    does not go red — it passes vacuously, on every project, forever. That is
    what `tapeout_docs_gen` shipped with on origin/main 69ce9260d.
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


def test_the_flows_own_evaluator_fails_a_defective_release_and_passes_a_clean_one(tmp_path):
    """The composition, not the exit code in isolation — this is what the gate does."""
    spec = importlib.util.spec_from_file_location(
        "_fcc_release_docs_probe", GATE.parent / "flow_compliance_check.py")
    fcc = importlib.util.module_from_spec(spec)
    sys.modules["_fcc_release_docs_probe"] = fcc
    spec.loader.exec_module(fcc)
    clause = _declared_clause()

    clean = released(tmp_path, "clean")
    ok_clean, out_clean = fcc._check_program_exit_zero(clean, clause)
    assert ok_clean, (
        f"a clean release must still PASS, or this gate is red for everyone: "
        f"{out_clean[:200]!r}")

    harmed = released(tmp_path, "harmed")
    edit(docs_dir(harmed, SUBJECT) / "IP_DATASHEET.md",
         "| Signal pins | 3 |", "| Signal pins | 6 |")
    ok_bad, out_bad = fcc._check_program_exit_zero(harmed, clause)
    assert not ok_bad, (
        f"the flow scored a release whose datasheet disagrees with its own "
        f"netlist as a gate pass: {out_bad[:200]!r}")
    assert "__VACUOUS_HINT__" not in out_bad, (
        "the refusal reached the flow's VACUOUS_PASS tier, which is a PASS")


@pytest.mark.parametrize("defect", [
    "section", "pin_count", "app_note", "digest", "hand_typed",
])
def test_no_refusal_ever_lands_in_a_pass_tier_exit_code(tmp_path, defect):
    """rc 2 / rc 3 are PASS tiers here; a content-earned refusal is rc 1."""
    project = released(tmp_path, defect)
    subject = docs_dir(project, SUBJECT)
    if defect == "section":
        _drop_section(subject / "IP_DATASHEET.md", "5. Timing")
    elif defect == "pin_count":
        _restate_signal_pins(subject / "IP_DATASHEET.md", 8, 10)
    elif defect == "app_note":
        note = subject / "AN001_REFERENCE_INTEGRATION.md"
        note.write_text(note.read_text(encoding="utf-8")
                        + "\n- **MANDATORY** `AN-ONLY-RULE` — stated nowhere "
                          "else in this release\n", encoding="utf-8")
    elif defect == "digest":
        view = project / "phase3" / "stage4" / "hardmacro" / f"{SUBJECT}.lib"
        view.write_text(view.read_text(encoding="utf-8") + "\n/* rebuilt */\n",
                        encoding="utf-8")
    elif defect == "hand_typed":
        edit(subject / "RELEASE_NOTES.md", "`input/project.json` |",
             "an earlier release |")

    rc = check(project).returncode
    assert rc == RC_FAIL, f"defect {defect!r} answered rc={rc}"
    assert rc not in PASS_TIER_RCS
    assert rc not in (143, 199), "a kill is not a verdict"
