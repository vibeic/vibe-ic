#!/usr/bin/env python3
"""A scoped compliance pass must not re-enter its own scope.

`flow_compliance_check` SPAWNS ITSELF: a step's gate may carry
`stageN_compliance`, which is `flow_compliance_check --stage N`, and that nested
pass evaluates steps whose gates may spawn it again. Every such chain in the
shipped flow used to descend (stage3 -> stage2 -> stage1 -> stage_phase1) and so
terminated by luck rather than by construction. The flow said so itself, at step
40, as the reason stage4's on-pass review was parked there:

    NO RECURSION: `flow_compliance_check --stage 4` evaluates stage4 steps only,
    and step 40 is stage5_manufacturing — outside the filter. Wired onto any
    stage4 step (37.5ic, 38, 39 are the tempting ones) it would re-enter itself
    without bound, which is why it is not.

That avoidance is what put the review behind step 40's `condition:` —
`phase3/stage5_manufacturing/silicon_received.json`, a path no run tree and no
commit in this repository's history has ever carried — so the rule that reads
the die had never executed. The recursion is now refused BY NAME, which is what
lets the review sit on a step the engine reaches.

DISCLOSED, NEVER SILENT: rc=2 with the scope stack printed. rc=2 is this
program's existing "the question could not be put" tier and the advisory slot
already records it as such, so a declining inner pass cannot read as a clean one.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent.parent
FCC = PLUGIN / "programs" / "flow_compliance_check.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
SCOPE_ENV = "VIBEIC_FCC_ACTIVE_SCOPES"


def _run(project: Path, *args, env_extra=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, str(FCC), str(project), *args],
                       capture_output=True, text=True, env=env, timeout=900)
    return r.returncode, r.stdout + r.stderr


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """A tree thin enough to audit fast and real enough to have steps."""
    p = tmp_path_factory.mktemp("run")
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "chip_top"}), encoding="utf-8")
    return p


def test_stage_id_names_a_stage_the_int_flag_never_could(project):
    """`--stage` is `type=int, choices=[1,2,3,4]`; the flow declares eight."""
    out = project / "sp1.json"
    rc, log = _run(project, "--stage-id", "stage_phase1", "--strict",
                   "--json", str(out))
    assert out.is_file(), log
    rows = json.loads(out.read_text())["steps"]
    assert rows, log
    assert {r["stage"] for r in rows} == {"stage_phase1"}, rows


def test_an_unknown_scope_is_a_typo_not_an_empty_run(project):
    rc, log = _run(project, "--stage-id", "stage_nope")
    assert rc == 2, log
    assert "no stage 'stage_nope'" in log, log
    # the message must LIST what is askable, or the caller has to grep the yaml
    assert "stage_phase1" in log and "stage_analog" in log, log


def test_stage_and_stage_id_together_are_refused(project):
    rc, log = _run(project, "--stage", "1", "--stage-id", "stage1")
    assert rc == 2, log
    assert "not both" in log, log


def test_a_pass_whose_scope_is_already_open_declines_and_says_so(project):
    """The guard itself, driven the way a nested gate drives it."""
    rc, log = _run(project, "--stage-id", "stage4", "--strict",
                   env_extra={SCOPE_ENV: "ALL:stage4"})
    assert rc == 2, log
    assert "already being evaluated by an outer pass" in log, log
    assert "ALL -> stage4" in log, log


def test_a_different_scope_under_the_same_stack_still_runs(project):
    """The guard must refuse RE-ENTRY, not nesting. The chain
    stage3 -> stage2 -> stage1 -> stage_phase1 is the shipped shape."""
    rc, log = _run(project, "--stage-id", "stage_phase1", "--strict",
                   env_extra={SCOPE_ENV: "ALL:stage3:stage2:stage1"})
    assert "already being evaluated" not in log, log


def test_stage4s_review_is_hosted_on_a_stage4_step_which_needs_the_guard():
    """The wiring this guard exists to permit, asserted so it cannot silently
    revert to the unreachable step it came from."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    host = None
    for step in doc["steps"]:
        for sub in (step.get("gate") or {}).get("all_of") or []:
            for val in sub.values():
                cmd = val.get("command") if isinstance(val, dict) else val
                if isinstance(cmd, str) and "--stage stage4 " in cmd + " " \
                        and cmd.startswith("stage_on_pass_review"):
                    host = step
    assert host is not None, "stage4's review is dispatched by nothing"
    assert host.get("stage") == "stage4", (
        f"hosted on {host['id']!r} in stage {host.get('stage')!r}")
    assert not host.get("condition"), (
        f"step {host['id']!r} carries a condition: {host.get('condition')}")
    cmds = [v.get("command") if isinstance(v, dict) else v
            for sub in host["gate"]["all_of"] for v in sub.values()]
    assert any(isinstance(c, str) and c.startswith("stage4_compliance")
               for c in cmds), cmds
