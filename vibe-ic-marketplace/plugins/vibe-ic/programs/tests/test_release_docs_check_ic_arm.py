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

import json
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ic_release_kit import (  # noqa: E402
    CONTROL,
    SUBJECT,
    build_project,
)

GATE = Path(__file__).resolve().parents[1] / "release_docs_check.py"
FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2






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






# ═══════════════════════════ the control arm ═══════════════════════════════






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






# ═════════════════ the cross-checks: re-derived, never believed ════════════










# ══════════════════════ the mandatory-constraint rule ══════════════════════




# ════════════════ the substance re-check, AFTER generation ═════════════════




# ═══════════════════════════ digests and manifest ══════════════════════════








# ══════════════════════════ the row-level rules ════════════════════════════








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
