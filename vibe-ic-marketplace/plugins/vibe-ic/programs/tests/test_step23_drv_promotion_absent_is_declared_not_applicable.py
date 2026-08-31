"""A rarely-applicable corroboration clause must not void a sign-off step.

THE DEFECT, measured on spm@1.14.30
-----------------------------------
That run posted step-level ``FAIL=0, PASS=24, PASS_VOIDED_BY_DEPENDENCY=6``.
Three of the six voided steps chain to INCOMPLETE steps 31/37. The other three
-- 32, 34, 35 -- chain to step 23, whose own observed line read::

    PARTIALLY-VACUOUS (1 of 5 gate clause(s) examined nothing):
    drv_promotion_corroboration_check . --json reports/phase3/sta/drv_promotion_corroboration.json

`drv_promotion_corroboration_check` (#293) corroborates a route promoted by
`signoff_spef_repair`. Its OWN verdict table makes the inapplicable case its
NORMAL outcome -- "no promotion happened this run" -- and the marker it keys on
is written at exactly one site (`phase3_one_shot_runner`) only when a promotion
actually occurred; `test_issue306_register_paydown` measures **0 of 15**
published run-roots carrying it.

Wired as a MANDATORY clause on step 23, that normal outcome cost the whole step.
Step 23 is a sign-off step (`_SIGNOFF_RE` matches "post-route STA"), so one
vacuous clause beside four substantive ones made it PARTIALLY-VACUOUS -- a
qualified-done tier -- and `_blocks_when_vacuous` then voided every downstream
done-claim. No design can make that go away: the flow could not reach PASS on
any run where no route promotion happened, which is the usual case.

WHAT MUST NOT REGRESS
---------------------
Scoping the clause must NOT delete #293. When a promotion DID happen and the
sign-off contradicts it -- or no sign-off report exists at all -- the clause must
still FAIL the step and still stop the flow. `test_the_refusal_still_blocks_*`
is that guard, and it is the one to read first if this file is ever relaxed.

chip-AGNOSTIC: synthetic artefact text and the shipped flow's own step records;
no design, PDK, foundry, vendor or process literal appears anywhere.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _hostpaths as _hp  # noqa: E402
import flow_step_execution_coverage_check as _cov  # noqa: E402

FCC = PROGRAMS / "flow_compliance_check.py"
DRV = PROGRAMS / "drv_promotion_corroboration_check.py"
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

_SUB = '''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:]; out=None
for i,x in enumerate(a):
    if x=="--json" and i+1<len(a): out=a[i+1]
if out:
    p=Path(out)
    if not p.is_absolute(): p=Path.cwd()/p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"gate":"substantive","verdict":"PASS","examined":11}))
print("[PASS] substantive"); sys.exit(0)
'''
_REASON = ("no route promotion happened this run, so no promoted route exists "
           "whose claimed improvement the sign-off report could corroborate")


def _steps(doc):
    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    return list(walk(doc))


def _clause_7(flow_doc):
    """The drv-promotion clause as the flow actually wires it."""
    for s in _steps(flow_doc):
        if str(s["id"]) != "23":
            continue
        for c in s["gate"]["all_of"]:
            for kind, spec in c.items():
                cmd = spec.get("command") if isinstance(spec, dict) else spec
                if isinstance(cmd, str) and "drv_promotion_corroboration_check" in cmd:
                    return kind, spec
    raise AssertionError("step 23 carries no drv_promotion_corroboration clause")


# ── the control: read off the SHIPPED flow, a checked-in artefact (#400) ──
def test_the_shipped_flow_declares_the_absent_promotion_as_not_applicable():
    """OBSERVES A VALUE — the clause KIND and the declared reason — not an absence.

    Pre-fix this reads `program_exit_zero` with no `absent_condition_reason`, so
    it fails on what the flow SAYS, not on a missing file or an ImportError.
    """
    flow = yaml.safe_load(_hp.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml").read_text())
    kind, spec = _clause_7(flow)
    assert kind == "optional_program_exit_zero", (
        f"step 23's drv-promotion clause is wired `{kind}`. Its normal outcome is "
        f"'no promotion happened this run' (0 of 15 published run-roots carry the "
        f"marker), and step 23 is a sign-off step, so a mandatory wiring makes the "
        f"step PARTIALLY-VACUOUS and voids every downstream done-claim.")
    cond = spec.get("condition_files_exist") or []
    assert any("routed_base_prerepair.def" in c for c in cond), cond
    why = (spec.get("absent_condition_reason") or "").strip()
    assert len(why) >= 40, (
        f"the not-applicable must be BOUGHT at the wiring site; got {len(why)} char(s)")


def test_the_condition_names_every_directory_the_gate_itself_searches():
    """The condition and the program must not disagree about where the marker is.

    If the gate grows a third `_PNR_DIRS` entry and the clause does not, the
    condition goes false on a tree where a promotion DID happen, and the gate
    that exists to catch an uncorroborated promotion silently stops running.
    """
    src = DRV.read_text()
    marker = "routed_base_prerepair.def"
    dirs = []
    for line in src.splitlines():
        if line.strip().startswith("_PNR_DIRS"):
            dirs = [p.strip().strip('"\'') for p in
                    line.split("(", 1)[1].split(")")[0].split(",") if p.strip()]
            break
    assert dirs, "could not read _PNR_DIRS from the gate"
    flow = yaml.safe_load(FLOW_YAML.read_text())
    kind, spec = _clause_7(flow)
    # COMPARE TWO CONCRETE SETS, never `isinstance` or a bare truthiness. A
    # mandatory clause carries a bare command string and no condition at all, so
    # its observed set is empty -- and an empty set measured against the required
    # one is a VALUE the control graded, where `assert isinstance(...)` would be
    # scored `undecided` and credit nothing. See control_substance_check's own
    # note on bare truthiness.
    cond = set(spec.get("condition_files_exist") or []) if isinstance(spec, dict) else set()
    required = {f"{d}/{marker}" for d in dirs}
    assert cond >= required, (
        f"the clause (wired `{kind}`) names condition paths {sorted(cond)}, but "
        f"the gate itself searches {sorted(required)}; a promotion landing in "
        f"{sorted(required - cond)} would never be corroborated")


# ─────────────────────── behavioural, through the real runner ──────────────
def _synth(tmp_path):
    p = tmp_path / "g" / "substantive.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_SUB)
    p.chmod(0o755)
    return p


def _one_step_flow(tmp_path, optional, tag):
    """A CERTIFYING sign-off step: four substantive clauses plus the real gate."""
    sub = _synth(tmp_path)
    cmd = f"{DRV} . --json reports/phase3/sta/drv_promotion_corroboration.json"
    clauses = "".join(
        f'        - program_exit_zero: "{sub} . --json reports/s{i}.json"\n'
        for i in range(4))
    clauses += (
        f'        - program_exit_zero: "{cmd}"\n' if not optional else
        "        - optional_program_exit_zero:\n"
        f'            command: "{cmd}"\n'
        '            condition_files_exist: ["pnr/routed_base_prerepair.def"]\n'
        f'            absent_condition_reason: "{_REASON}"\n')
    y = tmp_path / f"{tag}.yaml"
    y.write_text(
        "version: 2\nflow_name: t_step23\ntotal_steps: 2\nanalog_steps: 0\n"
        "stages:\n  - id: stage3\n    name: \"back end\"\n    steps: [23, 32]\n"
        "steps:\n"
        "  - id: 23\n"
        "    name: \"Post-route STA (multi-corner multi-mode sign-off)\"\n"
        "    stage: stage3\n    gate:\n      all_of:\n" + clauses +
        "  - id: 32\n    name: \"Post-route timing repair pass\"\n"
        "    stage: stage3\n    blocks_on: [23]\n    gate:\n      all_of:\n"
        f'        - program_exit_zero: "{sub} . --json reports/t.json"\n')
    return y


def _audit(tmp_path, flow, tag, promoted=False, signoff_rows=None):
    proj = tmp_path / f"p_{tag}"
    (proj / "reports" / "phase3" / "sta").mkdir(parents=True, exist_ok=True)
    if promoted:
        pnr = proj / "pnr"
        pnr.mkdir(parents=True, exist_ok=True)
        (pnr / "routed_base_prerepair.def").write_text("DESIGN x ;\n")
        (pnr / "signoff_spef_repair.log").write_text(
            "Found 2 slew violations.\nFound 0 capacitance violations.\n")
    if signoff_rows is not None:
        sta = proj / "phase3" / "stage3" / "sta"
        sta.mkdir(parents=True, exist_ok=True)
        sta.joinpath("sta_mcorner_ocv.rpt").write_text(
            "Max slew\n\nPin  Limit Slew Slack\n" + "".join(
                f"_0{7890 + i}_/B0   3.00  6.12  -3.12 (VIOLATED)\n"
                for i in range(signoff_rows)))
    rep = proj / "r.json"
    r = subprocess.run(
        [sys.executable, str(FCC), ".", "--flow-def", str(flow), "--json", str(rep)],
        cwd=proj, capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert rep.is_file(), (r.stdout or "") + (r.stderr or "")
    doc = json.loads(rep.read_text())
    return r.returncode, {str(s.get("id")): s.get("status") for s in doc["steps"]}


def test_a_declared_unmet_clause_leaves_the_signoff_step_and_its_successor_passing(
        tmp_path):
    """The defect and its repair, through the real runner. No promotion happened."""
    rc_a, a = _audit(tmp_path, _one_step_flow(tmp_path, False, "a"), "a")
    assert a["23"] == "PARTIALLY-VACUOUS" and a["32"] == "PASS_VOIDED_BY_DEPENDENCY", a
    assert rc_a != 0

    rc_b, b = _audit(tmp_path, _one_step_flow(tmp_path, True, "b"), "b")
    assert b["23"] == "PASS", b
    assert b["32"] == "PASS", (
        f"the successor is {b['32']}: a clause with nothing to corroborate still "
        f"voided a step it sits above")
    assert rc_b == 0


@pytest.mark.parametrize(
    "signoff_rows, why",
    [(9, "the sign-off shows MORE violations than the promotion claimed"),
     (None, "a promotion was made with NO sign-off report to corroborate it")])
def test_the_refusal_still_blocks_when_a_promotion_is_uncorroborated(
        tmp_path, signoff_rows, why):
    """CRITERION 3, prove-by-run. THE GUARD ON THIS WHOLE CHANGE.

    Scoping the clause to "only when a promotion happened" must not silence the
    case #293 exists for. Under BOTH wirings the step must FAIL and the run must
    stop. If this ever goes green by turning amber, the change deleted #293.
    """
    for optional, arm in ((False, "mand"), (True, "opt")):
        flow = _one_step_flow(tmp_path, optional, f"{arm}{signoff_rows}")
        rc, st = _audit(tmp_path, flow, f"{arm}{signoff_rows}",
                        promoted=True, signoff_rows=signoff_rows)
        assert st["23"] == "FAIL", (
            f"[{arm}] {why}: step 23 is {st['23']}, not FAIL — the refusal is gone")
        assert rc != 0, f"[{arm}] {why}: the gate failed but the run did not stop"


def test_step_23_is_a_certifying_step_so_a_qualified_tier_on_it_really_does_void():
    """The premise the whole finding rests on, asserted rather than assumed."""
    flow = yaml.safe_load(FLOW_YAML.read_text())
    s23 = next(s for s in _steps(flow) if str(s["id"]) == "23")
    assert _cov._blocks_when_vacuous(s23), (
        "step 23 no longer classifies as certifying; if that is deliberate, this "
        "whole file's premise moved and the finding needs re-deriving")
