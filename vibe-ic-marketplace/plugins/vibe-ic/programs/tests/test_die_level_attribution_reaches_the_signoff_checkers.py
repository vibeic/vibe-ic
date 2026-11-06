"""Three checkers, ONE quantity: the two sign-off checkers that had never been
told what the delivery IS.

MEASURED 2026-09-15 (lane icsub2) on `subservient` x gf180mcuD, a HARDMACRO
delivery that had already passed 9 of 9 declared phase-3 sign-off gates::

    reports/phase3/die_level_rule_attribution.json   (written BY THE RUN)
      verdict     DIE_LEVEL_DENSITY_ATTRIBUTED_TO_INTEGRATOR
      deliverable HARDMACRO   total 2   {M2.4: 1, M3.4: 1}   unattributed 0
      drc_tier    PASS_WITH_ATTRIBUTION

    phase 3's own `drc` STEP        -> PASS_WITH_ATTRIBUTION, remainder 0
    step 31 drc_report_check --signoff -> FAIL "2 real DRC violation(s)"
    step 36 tapeout_signoff_check      -> FAIL "2 at design level - met2+/via+"

Those two FAILs are two of the completion audit's 17 failed gates and two of
its 36 non-green steps, on a design whose unattributed remainder is zero.
M2.4/M3.4 are metal-density MINIMUMS whose measurement window, in the deck's
own block, is the WHOLE DIE -- which a 413 um macro placed inside somebody
else's die cannot move.

THE POINT OF THIS FILE IS THAT THE CREDIT IS HARD TO GET. A checker that
consults the attribution asks MORE of a HARDMACRO than one that does not, and
exactly as much of a DIE. Every clause below is a refusal that did not exist
before, and each has its own case here:

  * a DIE deliverable is never attributed, whatever the record says;
  * a rule whose deck evidence does not read the deck's whole-die area
    identifier is not die-level BY THE PRODUCER'S OWN PREDICATE, re-run here;
  * the attributed rules must be exactly the rules THE CALLER'S OWN REPORT
    carries violations under -- a forged record cannot make a DRC report emit
    a violation the design did not commit;
  * the count must match the count THE CALLER MEASURED;
  * the handoff record beside the abstract must name every attributed rule;
  * one unattributed violation and the FAIL stands.

And the credited verdict is never a bare PASS: `drc_report_check` reports
terminal_verdict PASS_WITH_ATTRIBUTION with the base audit's own
DRC_REAL_VIOLATIONS_FOUND still in the document at ERROR, and
`tapeout_signoff_check` exits 3 (PASS_WITH_WAIVERS), not 0.

chip-AGNOSTIC: the fixture PDK is `fixture_pdk`, the fixture rules are
`XX.9`/`YY.9`, the fixture die-area identifier is `whole_die_area`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import _owner_declared as _OD                              # noqa: E402
import die_level_deck_rule_attribution as D  # noqa: E402

# DEFERRED, and that is the point. `_die_level_attribution_consult` does not
# exist on the pre-fix tree, and a module-level import of it would make THIS
# WHOLE FILE a collection error there -- 0 cases run, 0 questions answered,
# and the end-to-end cases below (which drive the SHIPPED programs by
# subprocess and need no new symbol) would never get to report what the
# pre-fix tree actually does. Each case that needs the new module asks for it
# itself.
def _C():
    import _die_level_attribution_consult as C  # noqa: PLC0415
    return C


class _TIER:
    """`_TIER.value` without importing C at module scope; equal to the tier the
    producer already declares, which exists on both trees."""
    value = D.TIER_PASS_WITH_ATTRIBUTION

import pytest  # noqa: E402
from _finished_gds_fixture import publish_finished_gds


RULES = {"XX.9": 1, "YY.9": 1}
DECK = "/nonexistent/fixture_pdk/rule_decks/density.rb"


def _rdb(rules=("XX.9", "YY.9")) -> str:
    items = "".join(
        f"<item><category>'{r}'</category>"
        f"<values><value>polygon: (0,0;10,0;10,10;0,10)</value></values>"
        f"</item>" for r in rules)
    return f"<report-database><items>{items}</items></report-database>"


def _record(**over) -> dict:
    rec = {
        "program": "die_level_deck_rule_attribution",
        "deliverable": "HARDMACRO",
        "verdict": D.DENSITY_ATTRIBUTED,
        "total": 2,
        "attributed_density_rules": dict(RULES),
        "attributed_density_violations": 2,
        "unattributed_total": 0,
        "drc_tier": D.TIER_PASS_WITH_ATTRIBUTION,
        "die_area_identifiers": ["whole_die_area"],
        "die_level_density_rules_in_deck": {"XX.9": DECK, "YY.9": DECK},
        "die_level_density_rule_evidence": {
            r: {"deck_source": DECK,
                "code": "  density = metal.area / whole_die_area\n"
                        "  density.output(...)\n",
                "die_area_identifiers_matched": ["whole_die_area"]}
            for r in RULES},
    }
    rec.update(over)
    return rec


def make_project(tmp_path: Path, record=None, deliverable="HARDMACRO",
                 handoff_rules=("XX.9", "YY.9")) -> Path:
    (tmp_path / "input/submission_template").mkdir(parents=True, exist_ok=True)
    (tmp_path / "input/submission_template/tapeout_declaration.json").write_text(
        json.dumps(_OD.attest({"schema": "vibe-ic/tapeout_declaration/1",
                               "answers": {"deliverable": deliverable}})))
    (tmp_path / "reports/phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/phase3/die_level_rule_attribution.json").write_text(
        json.dumps(record if record is not None else _record()))
    if handoff_rules is not None:
        (tmp_path / "phase3/stage4/hardmacro").mkdir(parents=True,
                                                     exist_ok=True)
        (tmp_path / "phase3/stage4/hardmacro" / D.HANDOFF_NAME).write_text(
            json.dumps({"record": "integrator_requirements",
                        "requirements": [{"rule": r} for r in handoff_rules]}))
    return tmp_path


# ── the producer now carries the evidence a host with no PDK can re-check ──

def test_the_producer_records_the_deck_code_each_rule_was_read_from():
    """WHY IT MUST: the deck is inside the flow's container image and the
    completion audit re-invokes both callers ON THE HOST, where that path does
    not resolve. Without the recorded code a host consumer could only take the
    record's word."""
    deck = (f"{D.FILE_SEP}{DECK}\n"
            "# Rule XX.9: metal density minimum\n"
            "  d = metal1.area / whole_die_area\n"
            "  d.output('XX.9', 'metal density')\n"
            "# Rule ZZ.1: spacing\n"
            "  metal1.space(0.2).output('ZZ.1', 'spacing')\n")
    got = D.density_rule_evidence(deck, ["XX.9", "ZZ.1"], ["whole_die_area"])
    assert got["XX.9"]["die_area_identifiers_matched"] == ["whole_die_area"]
    assert "whole_die_area" in got["XX.9"]["code"]
    assert got["ZZ.1"]["die_area_identifiers_matched"] == [], (
        "a spacing rule reads no whole-die area and must record none")


def test_the_recorded_code_is_comment_stripped():
    """`deck_code_only`'s contract, carried through: a COMMENT that spells the
    die-area identifier must not make a rule die-level, here or downstream."""
    deck = (f"{D.FILE_SEP}{DECK}\n"
            "# Rule QQ.1: this comment mentions whole_die_area on purpose\n"
            "  metal1.space(0.2).output('QQ.1', 'spacing')\n")
    got = D.density_rule_evidence(deck, ["QQ.1"], ["whole_die_area"])
    assert got["QQ.1"]["die_area_identifiers_matched"] == []
    assert "whole_die_area" not in got["QQ.1"]["code"]


def test_rdb_rule_counts_reads_the_reports_own_rule_names():
    assert D.rdb_rule_counts(_rdb()) == {"XX.9": 1, "YY.9": 1}


# ── the consultation: credited, and every way it is not ───────────────────

def test_a_complete_hardmacro_attribution_is_credited(tmp_path):
    got = _C().consult(make_project(tmp_path), 2, ["XX.9", "YY.9"])
    assert got["credit"] is True
    assert got["tier"] == D.TIER_PASS_WITH_ATTRIBUTION
    assert set(got["provenance"].values()) == {"producer_recorded_deck_code"}


def test_a_DIE_delivery_is_never_attributed(tmp_path):
    """A die owns its own die-level rules and there is nobody above it."""
    got = _C().consult(make_project(tmp_path, deliverable="DIE"), 2,
                    ["XX.9", "YY.9"])
    assert got["applicable"] is False and got["credit"] is False
    assert "HARDMACRO" in got["reason"]


def test_an_undeclared_delivery_is_never_attributed(tmp_path):
    p = make_project(tmp_path)
    (p / "input/submission_template/tapeout_declaration.json").unlink()
    got = _C().consult(p, 2, ["XX.9", "YY.9"])
    assert got["credit"] is False and "undeclared" in got["reason"]


def test_a_rule_whose_deck_code_reads_no_die_area_is_refused(tmp_path):
    """THE PRODUCER'S OWN PREDICATE, RE-RUN. A rule is die-level because its
    block's CODE reads the deck's whole-die area -- not because a record says
    so."""
    rec = _record()
    rec["die_level_density_rule_evidence"]["XX.9"] = {
        "deck_source": DECK, "code": "  metal1.space(0.2).output('XX.9')\n",
        "die_area_identifiers_matched": []}
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["credit"] is False
    assert "NO whole-die area identifier" in got["reason"]


def test_evidence_claiming_an_identifier_its_code_lacks_is_refused(tmp_path):
    rec = _record()
    rec["die_level_density_rule_evidence"]["XX.9"] = {
        "deck_source": DECK, "code": "  metal1.space(0.2).output('XX.9')\n",
        "die_area_identifiers_matched": ["whole_die_area"]}
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["credit"] is False
    assert "does not actually contain" in got["reason"]


def test_evidence_claiming_an_identifier_the_deck_never_declared_is_refused(
        tmp_path):
    rec = _record()
    rec["die_area_identifiers"] = ["whole_die_area"]
    rec["die_level_density_rule_evidence"]["XX.9"] = {
        "deck_source": DECK, "code": "  d = m1.area / invented_area\n",
        "die_area_identifiers_matched": ["invented_area"]}
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["credit"] is False and "invented_area" in got["reason"]


def test_a_rule_with_no_recorded_evidence_at_all_is_refused(tmp_path):
    rec = _record()
    rec.pop("die_level_density_rule_evidence")
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["credit"] is False and "no recorded deck code" in got["reason"]


def test_the_attributed_rules_must_be_the_callers_own(tmp_path):
    """THE BINDING TO REALITY. A forged record can claim any deck block; it
    cannot make the caller's DRC report emit a violation under a rule the
    design did not violate."""
    got = _C().consult(make_project(tmp_path), 2, ["XX.9", "ZZ.1"])
    assert got["credit"] is False
    assert "not the rule(s) the caller's own report carries" in got["reason"]


def test_the_count_must_be_the_callers_own(tmp_path):
    got = _C().consult(make_project(tmp_path), 5, ["XX.9", "YY.9"])
    assert got["credit"] is False and "not about the report" in got["reason"]


def test_a_caller_that_states_no_count_is_not_credited(tmp_path):
    got = _C().consult(make_project(tmp_path))
    assert got["credit"] is False and "did not state" in got["reason"]


def test_a_missing_handoff_record_is_refused(tmp_path):
    got = _C().consult(make_project(tmp_path, handoff_rules=None), 2,
                    ["XX.9", "YY.9"])
    assert got["credit"] is False and got["handoff_ok"] is False
    assert "waiver wearing another word" in got["reason"]


def test_a_partial_handoff_record_is_refused(tmp_path):
    got = _C().consult(make_project(tmp_path, handoff_rules=("XX.9",)), 2,
                    ["XX.9", "YY.9"])
    assert got["credit"] is False
    assert "part of the problem to nobody" in got["reason"]


def test_one_unattributed_violation_keeps_the_fail(tmp_path):
    rec = _record(total=3, unattributed_total=1)
    got = _C().consult(make_project(tmp_path, rec), 3, ["XX.9", "YY.9"])
    assert got["credit"] is False
    assert "NOT attributed to the integrator" in got["reason"]


def test_arithmetic_that_does_not_close_is_refused(tmp_path):
    rec = _record(total=9)
    got = _C().consult(make_project(tmp_path, rec), 9, ["XX.9", "YY.9"])
    assert got["credit"] is False and "does not add up" in got["reason"]


def test_a_record_that_attributed_nothing_is_not_applicable(tmp_path):
    rec = _record(verdict="NOTHING_TO_ATTRIBUTE")
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["applicable"] is False and got["credit"] is False


def test_no_attribution_record_at_all_is_not_applicable(tmp_path):
    p = make_project(tmp_path)
    (p / "reports/phase3/die_level_rule_attribution.json").unlink()
    got = _C().consult(p, 2, ["XX.9", "YY.9"])
    assert got["applicable"] is False and "could not be read" in got["reason"]


def test_a_deck_ON_THIS_HOST_outranks_the_recorded_code(tmp_path):
    """When the deck IS readable the file decides, and the provenance says so
    -- the recorded arm exists for hosts without a PDK, not to displace one."""
    deck = tmp_path / "density.rb"
    deck.write_text("# Rule XX.9\n d = m.area / whole_die_area\n"
                    "# Rule YY.9\n d = m.area / whole_die_area\n")
    rec = _record()
    rec["die_level_density_rules_in_deck"] = {"XX.9": str(deck),
                                              "YY.9": str(deck)}
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["credit"] is True
    assert set(got["provenance"].values()) == {"deck_on_disk"}


def test_a_deck_on_this_host_that_does_not_name_the_rule_is_refused(tmp_path):
    deck = tmp_path / "density.rb"
    deck.write_text("# Rule ZZ.1\n m.space(0.2)\n")
    rec = _record()
    rec["die_level_density_rules_in_deck"] = {"XX.9": str(deck),
                                              "YY.9": str(deck)}
    got = _C().consult(make_project(tmp_path, rec), 2, ["XX.9", "YY.9"])
    assert got["credit"] is False
    assert "does NOT contain the rule name" in got["reason"]


# ── the two callers, end to end ───────────────────────────────────────────

def _current_signoff_subject(project: Path, report: Path) -> None:
    """Source-fixture current protocol; no native EDA or checker substitution."""
    import hashlib
    import _gdsii
    import _physical_current as current

    pnr = project / "phase3/stage3/pnr"
    gds = _gdsii.write_gdsii(pnr / "fixture_core.gds", cell="fixture_core")
    final = project / "phase3/stage4/gds/fixture_core.gds"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(gds.read_bytes())
    pdk = project / "input/pdk/source_fixture"
    materials = {
        "def": (pnr / "fixture_core.def", "VERSION 5.8 ;\nDESIGN fixture_core ;\nEND DESIGN\n"),
        "netlist": (pnr / "fixture_core_pnr.v", "module fixture_core(); endmodule\n"),
        "pdk_tech_lef": (pdk / "tech.lef", "VERSION 5.8 ;\nLAYER met1\n TYPE ROUTING ;\nEND met1\nEND LIBRARY\n"),
        "pdk_cell_lef": (pdk / "cells.lef", "VERSION 5.8 ;\nEND LIBRARY\n"),
        "pdk_deck": (pdk / "fixture.drc", "# SOURCE_FIXTURE parser input; no native EDA\n"),
        "technology": (project / "reports/phase3/technology_units.json",
                       json.dumps({"pdk": "source_fixture"})),
    }
    for path, body in materials.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    (project / "state_out.json").write_text(json.dumps({
        "gds": str(gds), "def": str(materials["def"][0])}))
    publish_finished_gds(project)
    native = project / "phase3/reports/drc.rpt"
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_bytes(report.read_bytes())
    log = native.with_suffix(".log")
    log.write_text("SOURCE_FIXTURE KLayout current/report protocol; no native EDA\n")
    report.with_suffix(".log").write_bytes(log.read_bytes())
    rel = lambda path: path.relative_to(project).as_posix()
    sha = lambda path: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    deck = materials["pdk_deck"][0]
    argv = ["klayout", "-b", "-r", str(deck), "-rd", f"input={gds}",
            "-rd", f"report={native}"]
    invocation = {
        "record": "invocation", "measured": True, "tool": "klayout",
        "exit_code": 0, "command": " ".join(argv),
        "scope": "SOURCE_FIXTURE parser/receipt control; no native EDA",
        "inputs": {rel(gds): sha(gds), rel(deck): sha(deck)},
        "outputs": {rel(path): sha(path) for path in
                    (report, report.with_suffix(".log"), native, log)},
    }
    with (project / "provenance.jsonl").open("a") as stream:
        stream.write(json.dumps(invocation) + "\n")
    subject = current.build(project, "31", "stage4", "fixture_core",
        "source_fixture", "klayout",
        {"gds": current.entry(project, gds),
         **{role: current.entry(project, path)
            for role, (path, _body) in materials.items()}},
        {"report": current.entry(project, report),
         "native_report": current.entry(project, native),
         "log": current.entry(project, log)},
        {"rc": 0, "argv": argv, "native_invocation": invocation,
         "scope": "SOURCE_FIXTURE parser/receipt control; no native EDA"})
    (project / "reports/phase3/direct_current_drc.json").write_text(json.dumps(subject))


def _signoff_project(tmp_path: Path, rules=("XX.9", "YY.9"),
                     deliverable="HARDMACRO", handoff=("XX.9", "YY.9")) -> Path:
    p = make_project(tmp_path, deliverable=deliverable, handoff_rules=handoff)
    rpt = p / "reports/phase3/drc_signoff.rpt"
    rpt.write_text(
        "# Tool: KLayout\n"
        "<report-database>\n"
        f" <generator>drc: script='{p / 'input/pdk/source_fixture/fixture.drc'}'"
        "</generator>\n"
        " <description>DRC</description>\n"
        f" <cells><cell><name>fixture_core</name></cell></cells>\n"
        " <items>\n" + "".join(
            f"  <item><cell>fixture_core</cell>"
            f"<category>'{r}'</category><visited>true</visited>"
            f"<values><value>polygon: (0,0;10,0;10,10;0,10)</value></values>"
            f"</item>\n" for r in rules) +
        " </items>\n</report-database>\n")
    _current_signoff_subject(p, rpt)
    return p


def _run(prog: str, project: Path, *argv):
    out = project / "out.json"
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / prog), ".", *argv,
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(project))
    rec = json.loads(out.read_text()) if out.is_file() else None
    return cp, rec


def test_drc_report_check_signoff_reaches_PASS_WITH_ATTRIBUTION(tmp_path):
    """THE CONTROL THE PRE-FIX TREE CAN EXECUTE: it drives the shipped
    checker over a project and asks for its exit code. Pre-fix: rc 1,
    "N real DRC violation(s)". Post-fix: rc 0, terminal_verdict
    PASS_WITH_ATTRIBUTION -- with the base audit's own ERROR still present."""
    p = _signoff_project(tmp_path)
    cp, rec = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                   "--under", "reports/phase3/drc_signoff.rpt")
    assert cp.returncode == 0, cp.stderr[-2000:]
    assert rec["summary"]["terminal_verdict"] == _TIER.value
    rules = {f["rule"] for f in rec["findings"]}
    assert "DRC_SIGNOFF_DIE_LEVEL_ATTRIBUTED" in rules
    assert "DRC_REAL_VIOLATIONS_FOUND" in rules, (
        "the base audit's finding must survive verbatim -- this clause adds a "
        "verdict, it does not relabel anyone's finding")
    assert rec["summary"]["die_level_attribution_measured_rules"] == \
        {"XX.9": 1, "YY.9": 1}


def test_drc_report_check_still_fails_a_DIE_delivery(tmp_path):
    """The same two violations on a DIE: nothing to attribute, FAIL stands."""
    p = _signoff_project(tmp_path, deliverable="DIE")
    cp, rec = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                   "--under", "reports/phase3/drc_signoff.rpt")
    assert cp.returncode == 1
    assert rec["summary"].get("terminal_verdict") != _TIER.value


def test_drc_report_check_still_fails_an_unhanded_over_attribution(tmp_path):
    p = _signoff_project(tmp_path, handoff=None)
    cp, rec = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                   "--under", "reports/phase3/drc_signoff.rpt")
    assert cp.returncode == 1
    assert "DRC_SIGNOFF_DIE_LEVEL_NOT_ATTRIBUTED" in {
        f["rule"] for f in rec["findings"]}


def test_drc_report_check_still_fails_a_violation_the_record_omits(tmp_path):
    """A third rule fires that the attribution never heard of: the names no
    longer match the caller's report, and the FAIL stands."""
    p = _signoff_project(tmp_path, rules=("XX.9", "YY.9", "ZZ.1"))
    cp, _ = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                 "--under", "reports/phase3/drc_signoff.rpt")
    assert cp.returncode == 1


def test_drc_report_check_adds_no_finding_when_there_is_nothing_to_attribute(
        tmp_path):
    """A clean report must not grow a die-level disclosure."""
    p = _signoff_project(tmp_path, rules=())
    _, rec = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                  "--under", "reports/phase3/drc_signoff.rpt")
    assert not [f for f in (rec or {}).get("findings", [])
                if "DIE_LEVEL" in f["rule"]]


# ── the tapeout checklist, end to end ─────────────────────────────────────
#
# The fixture is #515's own `_proj` — a tapeout-ready project whose DRC
# content each case supplies — so these cases sit beside the branch they were
# written next to and share its evidence denominator rather than a second
# definition of "tapeout-ready".















def test_the_attribution_cannot_suppress_an_unrelated_signoff_refusal(tmp_path):
    """THE CONTROL THIS FILE'S OWN R ARM FORCED INTO EXISTENCE.

    An early draft cleared `signoff_refused` when the attribution was
    credited. Run against the base tree, the fixture report happened to carry
    no `<generator>` deck; the base tree refused it for THAT reason and the
    fixed tree returned 0 — a real, unrelated refusal suppressed by a change
    that has nothing to do with it.

    The two questions are different. `--signoff`'s producer clauses ask
    WHETHER THIS IS A CERTIFICATE (is it a rule deck applied to a layout, does
    it name its rule set, was a layout streamed at all); the attribution asks
    WHOSE the violations are. A perfectly attributed macro whose report does
    not say which rules ran has certified nothing, and must still FAIL.
    """
    p = _signoff_project(tmp_path)
    rpt = p / "reports/phase3/drc_signoff.rpt"
    rpt.write_text(rpt.read_text().replace(
        f" <generator>drc: script='{p / 'input/pdk/source_fixture/fixture.drc'}'"
        "</generator>\n", ""))
    cp, rec = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                   "--under", "reports/phase3/drc_signoff.rpt")
    assert cp.returncode == 1, (
        "a credited attribution must not answer the producer question")
    rules = {f["rule"] for f in rec["findings"]}
    assert "DRC_SIGNOFF_PRODUCER_DECK_UNNAMED" in rules
    assert "DRC_SIGNOFF_DIE_LEVEL_ATTRIBUTED" in rules, (
        "and the attribution is still DISCLOSED — it was measured, it just "
        "does not decide this")


def test_the_attribution_cannot_suppress_a_missing_layout(tmp_path):
    """Same contract, the other producer clause: no streamed layout means no
    certificate, however cleanly the violations are attributed."""
    p = _signoff_project(tmp_path)
    # Remove both the declared stream and its required current-subject mirror.
    for g in (p / "phase3").rglob("*.gds"):
        g.unlink()
    cp, _ = _run("drc_report_check.py", p, "--mode", "drc", "--signoff",
                 "--under", "reports/phase3/drc_signoff.rpt")
    assert cp.returncode == 1
