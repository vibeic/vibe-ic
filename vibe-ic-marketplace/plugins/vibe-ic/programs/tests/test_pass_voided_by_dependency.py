"""A PASS a dependency contradicts is not a PASS.

The violation was always detected and always failed the RUN. What it never did
was touch the step's own status, so the per-step table published `PASS` beside
its own line saying a step it depends on had FAILED. Both locally correct; the
table showed the weaker one.
"""
from __future__ import annotations

import sys
from pathlib import Path

CHECK = Path(__file__).resolve().parent.parent / "flow_compliance_check.py"
import flow_step_execution_coverage_check as cov  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _report(statuses):
    return {"steps": [{"id": i, "name": f"step {i}", "status": s, "stage": "s"}
                      for i, s in statuses]}


def test_a_terminal_step_over_a_failed_dependency_is_a_violation():
    """The detection this fix writes back — unchanged, asserted as the premise."""
    got = cov.analyze(_report([(1, "FAIL"), (2, "PASS")]), {"2": ["1"]})
    v = got.get("ordering_violations") or []
    assert len(v) == 1, got
    assert str(v[0]["terminal_id"]) == "2"
    assert str(v[0]["signoff_id"]) == "1"


def test_a_healthy_chain_produces_no_violation():
    """THE control. A run whose dependencies all passed must be untouched — if
    this fires, the rule punishes correct work and is worse than the silence it
    replaces."""
    got = cov.analyze(_report([(1, "PASS"), (2, "PASS")]), {"2": ["1"]})
    assert not (got.get("ordering_violations") or []), got


def test_the_transitive_case_is_a_violation_too():
    """3 -> 2 -> 1: a failure two hops up still voids the terminal's PASS."""
    got = cov.analyze(_report([(1, "FAIL"), (2, "PASS"), (3, "PASS")]),
                      {"2": ["1"], "3": ["2"]})
    ids = {str(v["terminal_id"]) for v in (got.get("ordering_violations") or [])}
    assert "3" in ids, got


# ---- the write-back itself, exercised through the shipped entry point --------

def _run(project: Path):
    p = _pr.run([sys.executable, str(CHECK), str(project)],
                       capture_output=True, text=True)
    return p.stdout + p.stderr


def test_the_summary_parts_still_sum_to_the_step_count(tmp_path):
    """A bucket the summary line does not print loses steps silently.

    The first cut demoted 18 of 63 steps into exactly such a bucket, so the line
    read 45 out of 63 and the rest vanished — the defect this change exists to
    remove, reintroduced by the change itself.
    """
    import re
    out = _run(tmp_path)
    m = re.search(r"^\s+PASS=\d+.*$", out, re.M)
    if not m:                       # an empty project may not reach the summary
        return
    total = sum(int(x) for x in re.findall(r"=(\d+)", m.group(0)))
    steps = re.search(r"Steps:\s*(\d+)\s+total", out)
    if steps:
        assert total == int(steps.group(1)), m.group(0)


# ---- the tier itself, measured on a run that really produces it -------------

#: The canonical flow, read only for its top-level keys and its real `P0`, so
#: the probe below cannot drift from the schema the checker parses.
FLOW_YAML = CHECK.parent.parent / "flow" / "phase1_phase2_phase3.yaml"

#: A real gate program that answers rc 2 (`verdict: SKIP`) on a project
#: containing nothing, which is how `flow_compliance_check` decides
#: VACUOUS_PASS tier membership. Same program, same reason, as
#: `test_v0_2_95_issue461_final_summary._VACUOUS_GATE_PROGRAM`: verified live
#: by the premise assertions below rather than assumed, so a program that
#: stops being vacuous is REPORTED instead of quietly making the guard inert.
_VACUOUS_GATE_PROGRAM = "mixed_signal_merge_check"

#: THE CLAUSE THE FLOW DECLARES FOR IT, verbatim (flow step M1):
#: `mixed_signal_merge_check . --json reports/analog/mixed_signal/merge.json`.
#: The `--json` is not decoration and dropping it is what made this probe stop
#: producing a VACUOUS-PASS. `_command_json_report` reads the gate's declared
#: `reason_class` out of the report the command NAMES and out of nothing else,
#: so a bare `<program> .` has no typed channel at all: the gate's own
#: `DESIGN_DECLARED_NA` — earned here because `_analog_applicable` finds no
#: analog content in the probe project and the gate says so with its evidence —
#: never reaches `_check_program_exit_zero`, `infer_nonverdict_reason` falls
#: closed to EXECUTION_ERROR, and the tally prints INCOMPLETE=1 where this
#: guard needs VACUOUS-PASS=1. A probe that spells its clause differently from
#: the flow is measuring a wiring no step uses.
_VACUOUS_GATE_JSON = "reports/analog/mixed_signal/merge.json"

_SEED = "zvoid_seed.txt"


def _four_tier_probe_flow(path: Path) -> None:
    """A flow that yields PASS, VACUOUS_PASS, MISSING and PASS_VOIDED at once.

    The canonical flow on an empty project produces neither a VACUOUS-PASS nor
    a PASS-VOIDED, and a numerator guard measured where both counts are zero
    agrees no matter which definition either side uses — a green that means
    nothing. `P0` is carried over VERBATIM because the checker emits a `P0`
    result whether or not the flow declares one.
    """
    import yaml
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    top = {k: v for k, v in doc.items() if k != "steps"}
    p0 = next(dict(s) for s in doc["steps"] if str(s["id"]) == "P0")
    top["steps"] = [
        p0,
        {"id": "ZP1", "name": "voided-tier probe: plain pass",
         "stage": "stage1", "gate": {"files_exist": [_SEED]}},
        {"id": "ZV2", "name": "voided-tier probe: vacuous", "stage": "stage1",
         "gate": {"program_exit_zero":
                  f"{_VACUOUS_GATE_PROGRAM} . --json {_VACUOUS_GATE_JSON}"}},
        {"id": "ZF3", "name": "voided-tier probe: missing", "stage": "stage1",
         "required_outputs": ["never/produced.json"]},
        # PASSES on its own gate, and depends on the step that did not.
        {"id": "ZD4", "name": "voided-tier probe: voided", "stage": "stage1",
         "blocks_on": ["ZF3"], "gate": {"files_exist": [_SEED]}},
    ]
    path.write_text(yaml.safe_dump(top, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _run_probe(tmp_path: Path) -> str:
    flow = tmp_path / "voided_probe_flow.yaml"
    _four_tier_probe_flow(flow)
    project = tmp_path / "proj"
    project.mkdir()
    (project / _SEED).write_text("stub\n", encoding="utf-8")
    # <=60s: the targeted-subset harness dies at 180s, so an inner bound above
    # the ceiling kills the SESSION instead of the test. This probe drives a
    # four-step synthetic flow over a one-file project; measured ~0.5s.
    p = _pr.run(
        [sys.executable, str(CHECK), str(project), "--flow-def", str(flow)],
        capture_output=True, text=True)
    return p.stdout + p.stderr


def _tally(out: str) -> dict:
    import re
    m = re.search(r"^\s+PASS=\d+.*$", out, re.M)
    assert m is not None, (
        f"the checker printed no per-verdict tally line, so every premise "
        f"below is unmeasurable:\n{out[:3000]}")
    return {k: int(v) for k, v in re.findall(r"([A-Z][A-Z-]*)=(\d+)",
                                             m.group(0))}


def test_the_disclosure_tiers_stay_out_of_the_executed_pass_numerator(
        tmp_path):
    """`X` in `X/Y executed PASS` counts steps that were MEASURED and passed.

    Both VACUOUS_PASS and PASS_VOIDED_BY_DEPENDENCY are DISCLOSURE tiers: they
    sit outside `X` and inside `Y` (neither is EXCUSED), because a vacuous gate
    found nothing to audit and a voided one rests on a chain that broke. So on
    a run of 1 PASS + 1 VACUOUS-PASS + 1 PASS-VOIDED + 1 MISSING, `X` is 1.

    This replaces a test that asserted the SOURCE still contained
    `pass_count = counts["PASS"] + counts["VACUOUS_PASS"]`. That line was
    dead when it shipped — the unconditional assignment below it overwrites it
    before the only read — so the string match certified a line that could not
    move a number, and passed unchanged while the demotion this module exists
    to protect was disabled entirely.

    Bidirectional on purpose: `X == 2` means a disclosure tier was folded back
    into the numerator, `X == 0` means the numerator stopped counting real
    passes, and a missing `PASS-VOIDED=1` means the write-back never ran.
    """
    import re
    out = _run_probe(tmp_path)
    tally = _tally(out)

    # ── PREMISES. Asserted, never skipped: a probe that stops producing all
    # three tiers must FAIL here rather than agree vacuously below. Ordered
    # most-diagnostic first, so disabling the write-back reports THAT rather
    # than its downstream arithmetic.
    assert tally.get("PASS-VOIDED") == 1, (
        f"the probe produced no PASS-VOIDED. `ZD4` passes its own gate and "
        f"depends on `ZF3`, which is MISSING, so the write-back must have "
        f"demoted it. This is what fires when the demotion loop is disabled: "
        f"{tally}\n{out[:3000]}")
    assert tally.get("VACUOUS-PASS") == 1, (
        f"the probe produced no VACUOUS-PASS, so this guard cannot see the "
        f"fold it exists to catch. Gate program {_VACUOUS_GATE_PROGRAM!r} may "
        f"have stopped answering rc 2 on an empty project: {tally}\n"
        f"{out[:3000]}")
    assert tally.get("PASS") == 1, (
        f"the probe did not produce exactly one plain PASS: {tally}\n"
        f"{out[:3000]}")
    assert "ordering violations (1)" in out, (
        f"no ordering violation was reported, so the `if _ordering_violations:`"
        f" recompute branch — the one that used to carry a dead `pass_count` "
        f"store — never executed:\n{out[:3000]}")

    # ── THE PROPERTY.
    head = re.search(r"Steps: (\d+) total \((\d+)/(-?\d+) executed PASS", out)
    assert head is not None, (
        f"the checker published no `X/Y executed PASS` headline:\n"
        f"{out[:3000]}")
    executed, required = int(head.group(2)), int(head.group(3))
    assert executed == tally["PASS"], (
        f"the headline says {executed} executed PASS while the tally line it "
        f"is printed beside says PASS={tally['PASS']} — a disclosure tier is "
        f"inside the numerator: {tally}\n{out[:3000]}")
    assert executed == 1, (
        f"expected 1 executed PASS over a run with 1 PASS, 1 VACUOUS-PASS, "
        f"1 PASS-VOIDED and 1 MISSING; got {executed}: {tally}\n{out[:3000]}")
    # Both disclosure tiers are still OWED an answer, so they stay in Y.
    assert required == 4, (
        f"expected the denominator to keep both disclosure tiers "
        f"(4 = 5 steps - 1 SKIPPED-CONDITION); got {required}: {tally}\n"
        f"{out[:3000]}")

    # ── AND THE READER SEES IT. The number above is only half the fix; the
    # per-step line is the half a human actually reads.
    zd4 = next((l for l in out.splitlines() if "Step ZD4:" in l), None)
    assert zd4 is not None, f"no per-step line for ZD4:\n{out[:3000]}"
    assert "[PASS-VOIDED" in zd4, (
        f"the step whose dependency is MISSING is not labelled PASS-VOIDED; "
        f"a reader takes this line to mean the step is good: {zd4!r}")
    assert "[VACUOUS-PASS" not in zd4, (
        f"a voided PASS was rendered as a vacuous one, erasing the "
        f"distinction: {zd4!r}")


def test_detection_runs_before_the_table_is_printed():
    """A redundant, cheap tripwire — NOT the guard.

    It measures source line order as a proxy for "the reader sees the
    demotion", and a proxy is exactly how the previous test in this module
    went blind: with the write-back loop disabled this still passes, because
    the lines are still in that order. The GUARD is the `[PASS-VOIDED` label
    assertion above, which reads the rendered table. Kept only because the
    first attempt at this fix demoted AFTER the print loop and changed nothing
    a reader ever saw, and this catches that specific regression for free.
    """
    src = CHECK.read_text(encoding="utf-8").splitlines()
    demote = next(i for i, l in enumerate(src)
                  if '_r.status = "PASS_VOIDED_BY_DEPENDENCY"' in l)
    printed = next(i for i, l in enumerate(src) if "_icon = {" in l)
    assert demote < printed, (demote, printed)
