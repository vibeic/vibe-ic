"""vibe-ic#901 — a step is vacuous only when EVERY clause that ran was.

THE DEFECT
==========
`check_step` promoted a step to VACUOUS_PASS with

    elif passed and vacuous_hints and not non_hint_reasons and not skip_hints:

while the branch's own docstring stated the intent: "every executed sub-gate
was vacuously satisfied". `not non_hint_reasons` only APPROXIMATES that,
because **a clause that passes substantively appends no reason at all**. So
"nobody said anything" and "every clause was vacuous" were the same
observation, and ONE inapplicable clause re-tiered a step whose siblings had
measured real design content.

That is not a style complaint. v1.10.14 wired `_json_report_signals_vacuous`
into that branch; more clauses then disclosed vacuity, step 23 (post-route
STA, six clauses) flipped to VACUOUS_PASS on the strength of
`drv_promotion_corroboration_check` alone ("no route promotion this run —
gate inapplicable"), eight downstream steps recorded
PASS_VOIDED_BY_DEPENDENCY, and a genuinely converged cell reported an overall
FAIL with `failed_gate_count: 0`. The hook was withdrawn in v1.10.18 and the
hole it was closing — a gate writing `{"verdict": "NOT_APPLICABLE"}` into a
`--json` report the consumer never opened — was left open as the lesser evil.

WHAT THIS FILE PINS
===================
The COUNT, and then the re-wiring that the count makes safe:

  1. one inapplicable clause among substantive siblings  -> PASS (+ disclosure)
  2. every executed clause inapplicable                  -> VACUOUS_PASS
  3. a clause that never RAN is in neither side of the count
  4. an ADVISORY clause does not vote (#306: it cannot fail a step, so it
     must not be able to re-tier one either)
  5. a clause with NO vacuity channel (`files_exist`) is in neither side
     either — it could never be in the numerator, so it must not inflate the
     denominator
  6. a `--json` report declaring NOT_APPLICABLE IS read (#901's hole)
  7. and it still cannot outvote a substantive sibling (the v1.10.14 shape)

2, 3, 4 and 5 are the polarity controls. A "fix" that simply deleted the
VACUOUS_PASS tier would satisfy 1, 6 and 7 and destroy the tier the campaign
depends on; a naive count that put never-invoked optional clauses in the
denominator would satisfy 1 and break 3 — which is exactly how a real
converged cell's step 14 (two optional clauses, both vacuous, one advisory
sibling) would have been silently re-tiered; and one that counted presence
probes would break 5, turning the SHIPPED step 30
(`files_exist(*.sp) AND spice_correlation_check`) from a disclosed vacuous
pass into a bare PASS on every project that ships a deck and no SPEF.

Chip-AGNOSTIC: synthetic gate programs and synthetic projects throughout. No
PDK, no design, no run tree.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F  # noqa: E402


# ── synthetic gate programs ────────────────────────────────────────────────
# `_resolve_program_cmd` resolves a bare gate name against PROGRAMS_DIR, so a
# fixture gate has to live there for the REAL consumer path to run it. Every
# planted file is removed again by the fixture, pass or fail.
_PREFIX = "_i901_"

_SILENT_SUBSTANTIVE = '''\
"""Fixture: a clause that MEASURED something and, being satisfied, says
nothing. This silence is the whole defect — pre-#901 it was indistinguishable
from a clause that examined nothing."""
import sys
sys.exit(0)
'''

_RC2_VACUOUS = '''\
"""Fixture: a clause that discloses vacuity by the rc=2 convention."""
import sys
print("VACUOUS_PASS: nothing of this kind in the project")
sys.exit(2)
'''

_JSON_ONLY_VACUOUS = '''\
"""Fixture: #901's hole. Exits 0, prints nothing a consumer would notice, and
declares NOT_APPLICABLE only inside its own --json report."""
import json, sys
from pathlib import Path
args = sys.argv[1:]
out = None
for i, a in enumerate(args):
    if a == "--json" and i + 1 < len(args):
        out = args[i + 1]
    elif a.startswith("--json="):
        out = a.split("=", 1)[1]
if out:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"verdict": "NOT_APPLICABLE",
                             "reason": "step did not run"}))
print("done")
sys.exit(0)
'''

_JSON_SUBSTANTIVE = '''\
"""Fixture: the polarity partner — same --json shape, real verdict."""
import json, sys
from pathlib import Path
args = sys.argv[1:]
out = None
for i, a in enumerate(args):
    if a == "--json" and i + 1 < len(args):
        out = args[i + 1]
if out:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"verdict": "PASS", "cells_examined": 65}))
print("done")
sys.exit(0)
'''

_FIXTURES = {
    "substantive": _SILENT_SUBSTANTIVE,
    "substantive2": _SILENT_SUBSTANTIVE,
    "substantive3": _SILENT_SUBSTANTIVE,
    "rc2_vacuous": _RC2_VACUOUS,
    "json_vacuous": _JSON_ONLY_VACUOUS,
    "json_substantive": _JSON_SUBSTANTIVE,
    "advisory_ok": _SILENT_SUBSTANTIVE,
}


@pytest.fixture()
def gates():
    """Plant the fixture gates in PROGRAMS_DIR; remove them afterwards."""
    written = []
    for name, body in _FIXTURES.items():
        p = PROGRAMS / f"{_PREFIX}{name}.py"
        p.write_text(body, encoding="utf-8")
        written.append(p)
    try:
        yield {name: f"{_PREFIX}{name}" for name in _FIXTURES}
    finally:
        for p in written:
            try:
                p.unlink()
            except OSError:
                pass


def _step(gate, sid=901):
    return {"id": sid, "name": "synthetic #901 step", "stage": "stage2",
            "required_outputs": [], "gate": gate}


def _reasons(result) -> str:
    return " | ".join(result.reasons)


# ══════════════════════════════════════════════════════════════════════
# 1. THE COUNT — the forward case
# ══════════════════════════════════════════════════════════════════════
def test_one_inapplicable_clause_among_substantive_siblings_is_not_vacuous(
        tmp_path, gates):
    """The load-bearing assertion, and the exact shape of the v1.10.14 bug.

    Three clauses run. One discloses that it examined nothing; two measure
    something and, being satisfied, say nothing at all. Pre-#901 the one
    disclosure decided the tier and the whole step was labelled "ran without
    measuring design-bound content" — false, and expensive, because a
    VACUOUS_PASS voids the steps that declare a dependency on it.
    """
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero": gates["rc2_vacuous"]},
        {"program_exit_zero": gates["substantive"]},
        {"program_exit_zero": gates["substantive2"]},
    ]}), {})
    assert r.status == "PASS", (
        f"a step with 2 substantive clauses and 1 inapplicable one was tiered "
        f"{r.status}; vacuity was inferred from the silence of the clauses "
        f"that did the work. reasons={_reasons(r)}")


def test_the_demotion_does_not_bury_the_disclosure(tmp_path, gates):
    """A PASS that hides the inapplicable clause would trade one silent
    substitution for another. The step line must still NAME the clause that
    examined nothing, and must carry the DENOMINATOR that justifies the PASS.
    """
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero": gates["rc2_vacuous"]},
        {"program_exit_zero": gates["substantive"]},
        {"program_exit_zero": gates["substantive2"]},
    ]}), {})
    blob = _reasons(r)
    assert "partially vacuous" in blob, (
        f"the vacuity disclosure was dropped on the demotion: {blob}")
    assert "1 of 3" in blob, (
        f"the disclosure must carry the count that justifies the tier, so a "
        f"reviewer can check it: {blob}")
    assert gates["rc2_vacuous"] in blob, (
        f"the disclosure must name WHICH clause examined nothing: {blob}")


def test_the_v1_10_14_regression_shape_stays_a_pass(tmp_path, gates):
    """Step 23's shape, reduced: six clauses, one legitimately inapplicable.

    This is the case that turned a converged cell red — an overall FAIL with
    `failed_gate_count: 0` and nothing enumerated as failed.
    """
    (tmp_path / "sta").mkdir()
    (tmp_path / "sta" / "post_route.rpt").write_text("wns 0.12\n")
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero": gates["substantive"]},
        {"program_exit_zero": gates["substantive2"]},
        {"program_exit_zero": gates["substantive3"]},
        {"program_exit_zero":
            f"{gates['json_vacuous']} . --json reports/drv_promo.json"},
        {"program_exit_zero":
            f"{gates['json_substantive']} . --json reports/sta.json"},
        {"files_exist": ["sta/post_route.rpt"]},
    ]}, sid=23), {})
    assert r.status == "PASS", (
        f"one inapplicable clause among five that measured design content "
        f"re-tiered the step to {r.status}: reasons={_reasons(r)}")
    assert "1 of 5" in _reasons(r), (
        f"the census must name the five clauses that could have disclosed "
        f"vacuity — the `files_exist` probe is not one of them: {_reasons(r)}")


# ══════════════════════════════════════════════════════════════════════
# 2. THE POLARITY CONTROLS — the tier must survive the fix
# ══════════════════════════════════════════════════════════════════════
def test_every_executed_clause_vacuous_is_still_a_vacuous_step(
        tmp_path, gates):
    """Without this, "count the clauses" degenerates into "delete the tier"."""
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero": gates["rc2_vacuous"]},
        {"program_exit_zero": gates["rc2_vacuous"]},
    ]}), {})
    assert r.status == "VACUOUS_PASS", (
        f"every clause disclosed that it examined nothing and the step was "
        f"still tiered {r.status}: {_reasons(r)}")


def test_a_single_vacuous_clause_alone_is_still_a_vacuous_step(
        tmp_path, gates):
    r = F.check_step(
        tmp_path, _step({"program_exit_zero": gates["rc2_vacuous"]}), {})
    assert r.status == "VACUOUS_PASS", _reasons(r)


def test_a_clause_that_never_ran_is_in_neither_side_of_the_count(
        tmp_path, gates):
    """An `optional_program_exit_zero` whose `condition_files_exist` matches
    nothing was NOT evaluated. Counting it as substantive would demote a
    genuinely all-vacuous step to PASS — which is how a real converged cell's
    step 14 (two optional clauses, both inapplicable) would have been
    silently re-tiered by a naive denominator.
    """
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero": gates["rc2_vacuous"]},
        {"optional_program_exit_zero": {
            "command": gates["substantive"],
            "condition_files_exist": ["nothing/here/*.json"]}},
    ]}), {})
    assert r.status == "VACUOUS_PASS", (
        f"a clause that was never invoked was counted as measuring design "
        f"content: {r.status} / {_reasons(r)}")


def test_a_presence_probe_is_not_a_measurement(tmp_path, gates):
    """Step 30's shape: `files_exist(*.sp) AND spice_correlation_check`.

    A SPICE deck on disk is the PRECONDITION for the correlation, not the
    correlation. The program says it had nothing to correlate; the step is
    vacuous. Counting the probe as a substantive clause would demote step 30
    to PASS on every project that ships a deck and no SPEF — and a probe can
    never be counted VACUOUS (it has no channel to say so), so putting it in
    the denominator makes "every clause was vacuous" unreachable rather than
    false.
    """
    (tmp_path / "spice").mkdir()
    (tmp_path / "spice" / "crit.sp").write_text("* deck\n.end\n")
    r = F.check_step(tmp_path, _step({"all_of": [
        {"files_exist": ["spice/*.sp"]},
        {"program_exit_zero": gates["rc2_vacuous"]},
    ]}), {})
    assert r.status == "VACUOUS_PASS", (
        f"a presence probe was counted as measuring design content: "
        f"{r.status} / {_reasons(r)}")


def test_an_advisory_clause_does_not_vote_in_the_census(tmp_path, gates):
    """#306 — an advisory gate cannot FAIL a step. A census that let it decide
    the tier would hand it, through the back door, the authority its own slot
    exists to withhold.
    """
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero": gates["rc2_vacuous"]},
        {"advisory_program_exit_zero": gates["advisory_ok"]},
    ]}), {})
    assert r.status == "VACUOUS_PASS", (
        f"an advisory clause re-tiered the step: {r.status} / {_reasons(r)}")


# ══════════════════════════════════════════════════════════════════════
# 3. THE HOLE #901 WAS FILED ABOUT — now that counting makes it safe
# ══════════════════════════════════════════════════════════════════════
def test_a_json_only_not_applicable_declaration_is_read(tmp_path, gates):
    """The original #901 finding, at the STEP tier rather than in the helper.

    The gate exits 0, prints nothing a consumer notices, and declares
    NOT_APPLICABLE only in the `--json` report it was told to write. Six gates
    do this on an empty project — `vacuous_testbench_check`, the gate against
    vacuous passes, among them.
    """
    r = F.check_step(tmp_path, _step({
        "program_exit_zero":
            f"{gates['json_vacuous']} . --json reports/g.json"}), {})
    assert (tmp_path / "reports" / "g.json").is_file(), (
        "fixture did not write the report the consumer is supposed to read")
    assert json.loads(
        (tmp_path / "reports" / "g.json").read_text())["verdict"] == \
        "NOT_APPLICABLE"
    assert r.status == "VACUOUS_PASS", (
        f"a gate that declared it examined nothing was scored a substantive "
        f"{r.status}: {_reasons(r)}")


def test_a_json_substantive_verdict_is_not_read_as_vacuous(tmp_path, gates):
    """Polarity. A helper that answered vacuous to every `--json` gate would
    satisfy the test above and convert every real pass into a vacuous one — a
    worse defect than the one being closed.
    """
    r = F.check_step(tmp_path, _step({
        "program_exit_zero":
            f"{gates['json_substantive']} . --json reports/g.json"}), {})
    assert r.status == "PASS", (
        f"a gate reporting a real verdict was read as vacuous: {_reasons(r)}")


def test_a_json_declared_vacuity_cannot_outvote_a_substantive_sibling(
        tmp_path, gates):
    """The two halves together — the reason the re-wiring is safe now and was
    not in v1.10.14.
    """
    r = F.check_step(tmp_path, _step({"all_of": [
        {"program_exit_zero":
            f"{gates['json_vacuous']} . --json reports/a.json"},
        {"program_exit_zero": gates["substantive"]},
    ]}), {})
    assert r.status == "PASS", (
        f"the JSON channel re-tiered a step whose sibling measured design "
        f"content — the v1.10.14 regression, reopened: {_reasons(r)}")
    assert "partially vacuous" in _reasons(r), (
        f"the JSON disclosure was read and then silently dropped, which is "
        f"the #901 defect wearing a different hat: {_reasons(r)}")


def test_the_optional_slot_reads_the_json_channel_too(tmp_path, gates):
    """A disclosure that counts through one slot and not the other is how the
    same program came to be read two different ways (#654's shape).
    """
    (tmp_path / "cond").mkdir()
    (tmp_path / "cond" / "x.json").write_text("{}\n")
    r = F.check_step(tmp_path, _step({"optional_program_exit_zero": {
        "command": f"{gates['json_vacuous']} . --json reports/o.json",
        "condition_files_exist": ["cond/*.json"]}}), {})
    assert r.status == "VACUOUS_PASS", (
        f"the optional slot ignored the report the required slot reads: "
        f"{r.status} / {_reasons(r)}")


# ══════════════════════════════════════════════════════════════════════
# 4. THE CENSUS ITSELF
# ══════════════════════════════════════════════════════════════════════
def test_census_excludes_advisory_and_never_ran():
    log = []
    F._clause(log, "program_exit_zero", vacuous=True)
    F._clause(log, "program_exit_zero", vacuous=False)
    F._clause(log, "advisory_program_exit_zero", advisory=True, vacuous=True)
    F._clause(log, "optional_program_exit_zero", ran=False, vacuous=True)
    assert F._clause_vacuity_census(log) == (1, 2)


def test_an_empty_census_falls_back_to_the_pre_901_rule():
    """A gate shape that registers no clause at all must not be re-tiered by a
    census that saw nothing. (0, 0) is the signal for that fallback."""
    assert F._clause_vacuity_census([]) == (0, 0)
    assert F._clause_vacuity_census(None) == (0, 0)
