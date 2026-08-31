"""A non-promotion that leaves no record is a gate that cannot be armed (#220).

THE DEFECT, on origin/main c9dacb8275 (v1.14.71)
------------------------------------------------
`flow_condition_reachability_check` exited 1 with::

    FAIL: 1 NEW self-disabling condition(s) in phase1_phase2_phase3.yaml
      - step 23 predicate drv_promotion_corroboration_check:
        condition ['phase3/stage3/pnr/routed_base_prerepair.def',
                   'pnr/routed_base_prerepair.def']
        ANY-of: no trigger survives ... none is a declaration (T1), a not-run
        disclosure (T2), a backstopped required_output (T3/T5), or a hard
        files_exist (T4/T7).

`routed_base_prerepair.def` is written at exactly one site — the PROMOTION
branch of `step_signoff_spef_repair` — and every one of that function's five
non-promotion returns wrote nothing at all. So "no promotion happened" and "the
promotion ran and died before `shutil.copy2`" left byte-identical evidence, and
`drv_promotion_corroboration_check` called both VACUOUS_PASS: it INFERRED from
an absent file rather than reading a claim. Measured over 45 real run roots on a
working host, the marker is present in 0 of them — the branch that left no
evidence was not the corner case, it was every run.

THE COLLISION THIS DISSOLVES
----------------------------
`964b1eaac1` (v1.14.49) measured that the ordinary T2 repair — arm the clause on
a `*_not_run.json` and let it run — put the clause back in the vacuity tier on
the normal day, demoting step 23 (a sign-off step) to PARTIALLY-VACUOUS and
voiding ten downstream steps. It concluded that reachability (#210/#219) and
vacuity (#901/#1115) leave no wiring in which a rarely-applicable clause on a
certifying step is neutral, and called that a policy question.

It is not a policy question; it was a gate that could only infer. Reading the
producer's own record is an EXAMINATION, so the honest verdict on the normal day
is PASS, not VACUOUS_PASS. `test_the_mandatory_wiring_is_now_neutral_on_the_
normal_day` is the measurement of that claim, and it is the one to read first if
this file is ever relaxed.

WHAT MUST NOT REGRESS
---------------------
#293 itself. A promotion that the sign-off report contradicts must still FAIL,
and a promotion with no sign-off report at all must still FAIL. Those are
`test_a_contradicted_promotion_still_fails` and
`test_an_uncorroborated_promotion_still_fails`.

chip-AGNOSTIC: synthetic artefact text and the shipped flow's own step record;
no design, PDK, foundry, vendor or process literal appears anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

DRV = PROGRAMS / "drv_promotion_corroboration_check.py"
FCC = PROGRAMS / "flow_compliance_check.py"
REACH = PROGRAMS / "flow_condition_reachability_check.py"
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

_RECORD_REL = "phase3/stage3/pnr/drv_promotion_not_run.json"
_MARKER_REL = "phase3/stage3/pnr/routed_base_prerepair.def"


# ------------------------------------------------------------------ fixtures
def _pnr(project: Path) -> Path:
    d = project / "phase3/stage3/pnr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _declined(project: Path, stage: str = "repair_declined") -> Path:
    p = project / _RECORD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "program": "step_signoff_spef_repair", "promoted": False,
        "not_run_stage": stage,
        "reason": "the repair ran and its result did not clear the promotion "
                  "gate, so the base route was kept"}))
    return p


def _promoted(project: Path, claimed: int = 0) -> None:
    d = _pnr(project)
    (d / "routed_base_prerepair.def").write_text("DESIGN x ;\n")
    (d / "signoff_spef_repair.log").write_text(
        f"Found {claimed} slew violations.\n"
        f"Found {claimed} capacitance violations.\n")


def _signoff(project: Path, violating_rows: int = 0) -> None:
    p = project / "phase3/stage3/sta/sta_mcorner_ocv.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"  pin{i}/A    3.00    6.12   -3.12 (VIOLATED)\n"
                   for i in range(violating_rows))
    p.write_text("max slew\n\n" + rows)


def _run(project: Path):
    r = subprocess.run([sys.executable, str(DRV), str(project)],
                       capture_output=True, text=True)
    verdict = None
    for line in r.stdout.splitlines():
        if line.startswith("verdict: "):
            verdict = line.split(" ", 1)[1].strip()
            break
    vacuous_sentinel = any(l.startswith("VACUOUS_PASS:")
                           for l in r.stdout.splitlines())
    return r.returncode, verdict, vacuous_sentinel, r.stdout


# ------------------------------------------------------- the gate's verdicts
def test_a_declared_non_promotion_is_a_real_pass_not_a_vacuous_one(tmp_path):
    """THE FIX. The producer says it did not promote; the gate reads that and
    answers PASS, with no `VACUOUS_PASS:` sentinel on stdout.

    The sentinel is what `flow_compliance_check._stdout_signals_vacuous`
    promotes to the vacuity tier, so its absence is the whole behavioural
    difference — asserted directly rather than through the flow, so a failure
    here points at this gate and not at the harness.

    RED WITHOUT THE FIX: on origin/main this gate has no
    `promotion_declined_record` at all; `promotion_happened()` returns None and
    `check()` returns VACUOUS_PASS unconditionally, so `verdict` is
    "VACUOUS_PASS" and the sentinel line is printed.
    """
    _declined(tmp_path)
    rc, verdict, sentinel, out = _run(tmp_path)
    assert rc == 0, out
    assert verdict == "PASS", out
    assert not sentinel, (
        "the gate read the producer's own non-promotion record and still "
        "reported itself as having examined nothing:\n" + out)


def test_the_recorded_reason_is_quoted_not_discarded(tmp_path):
    """A declaration nobody can read back is a label. The producer's reason and
    its stage must both survive into the gate's report."""
    _declined(tmp_path, stage="producer_execution_error")
    rc, verdict, _, out = _run(tmp_path)
    assert rc == 0 and verdict == "PASS", out
    assert "producer_execution_error" in out, out
    assert "did not clear the promotion gate" in out, out


def test_no_record_and_no_marker_is_still_vacuous(tmp_path):
    """THE CONTROL that stops the test above from being satisfied by a gate
    that simply stopped saying VACUOUS_PASS.

    Neither artefact means `step_signoff_spef_repair` never ran (a routing FAIL
    that returns early from `step_pnr` skips it). Nothing was examined, and the
    verdict must still say so.
    """
    _pnr(tmp_path)
    rc, verdict, sentinel, out = _run(tmp_path)
    assert rc == 0, out
    assert verdict == "VACUOUS_PASS", out
    assert sentinel, out


def test_an_unreadable_record_is_never_a_pass(tmp_path):
    """A producer that claims to have declared something, in a file that cannot
    be parsed, has established nothing. Failing closed here is what stops the
    record from becoming a way to buy a PASS with an empty file."""
    p = tmp_path / _RECORD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json")
    rc, verdict, _, out = _run(tmp_path)
    assert rc == 1, out
    assert verdict == "FAIL", out


def test_a_stale_record_cannot_mask_a_real_promotion(tmp_path):
    """The producer deletes the record when it promotes, so both existing is
    off-nominal. If it happens anyway the MARKER must win, because the
    corroboration is the stronger duty."""
    _promoted(tmp_path)
    _signoff(tmp_path, violating_rows=2)
    _declined(tmp_path)
    rc, verdict, _, out = _run(tmp_path)
    assert rc == 1, (
        "a stale non-promotion record let a contradicted promotion pass:\n"
        + out)
    assert verdict == "FAIL", out


# ------------------------------------------------------ #293 must not regress
def test_a_contradicted_promotion_still_fails(tmp_path):
    """WHAT MUST NOT REGRESS. The promotion claimed 0 DRV violations from its
    own session; the sign-off report shows 2. #293 exists for exactly this and
    it must still stop the run."""
    _promoted(tmp_path, claimed=0)
    _signoff(tmp_path, violating_rows=2)
    rc, verdict, _, out = _run(tmp_path)
    assert rc == 1 and verdict == "FAIL", out


def test_an_uncorroborated_promotion_still_fails(tmp_path):
    """A promotion with NO sign-off report to corroborate it is the other half
    of #293."""
    _promoted(tmp_path, claimed=0)
    rc, verdict, _, out = _run(tmp_path)
    assert rc == 1 and verdict == "FAIL", out


def test_a_corroborated_promotion_still_passes(tmp_path):
    """And the gate must not have become unable to say yes."""
    _promoted(tmp_path, claimed=0)
    _signoff(tmp_path, violating_rows=0)
    rc, verdict, sentinel, out = _run(tmp_path)
    assert rc == 0 and verdict == "PASS", out
    assert not sentinel, out


# ------------------------------------------------------------- the producer
def test_every_non_promotion_return_leaves_a_record(tmp_path):
    """The gate can only read a record the producer actually writes.

    `step_signoff_spef_repair` has five non-promotion returns. This asserts
    against the SOURCE that each one discloses and that the promotion branch
    clears, because driving the real function needs an OpenROAD container and
    the property being pinned is structural: no non-promotion path may return
    without leaving evidence.

    MUTATION THIS CATCHES: adding a sixth early return without a disclosure —
    the exact way this defect was introduced in the first place.
    """
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    start = src.index("def step_signoff_spef_repair(")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]

    n_returns = body.count("\n        return None") + body.count(
        "\n        return StepResult(") + body.count("\n    return StepResult(")
    n_disclose = body.count("_drv_promotion_disclose(")
    assert n_disclose == 5, (
        f"expected all five non-promotion returns to disclose, found "
        f"{n_disclose} disclosure call(s) among {n_returns} return(s)")
    assert "_drv_promotion_clear(" in body, (
        "the promotion branch does not delete a stale non-promotion record, so "
        "the marker and the record could both be readable at once")
    # the clear must happen BEFORE the marker is written, so a crash between
    # them can never leave both.
    assert body.index("_drv_promotion_clear(") < body.index(
        'routed_base_prerepair.def"'), body[-400:]


def test_the_record_the_producer_writes_is_the_one_the_gate_reads(tmp_path):
    """Two hand-kept filenames are two filenames that drift. Pin them equal."""
    import drv_promotion_corroboration_check as _gate  # noqa: E402
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    assert f'_DRV_PROMOTION_NOT_RUN = "{_gate._NOT_RUN_RECORD}"' in src, (
        f"the gate reads {_gate._NOT_RUN_RECORD!r}; the producer writes some "
        f"other name")


# ---------------------------------------------------------- the flow wiring
def test_the_flow_clause_is_armed_on_the_record_in_both_pnr_dirs(tmp_path):
    """The clause must name the record under BOTH directories the gate itself
    searches, or the condition and the program can disagree about where it
    lives."""
    import drv_promotion_corroboration_check as _gate  # noqa: E402
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    clause = None
    for st in doc["steps"]:
        for sub in ((st.get("gate") or {}).get("all_of") or []):
            c = sub.get("optional_program_exit_zero") if isinstance(sub, dict) else None
            if c and c.get("command", "").startswith(
                    "drv_promotion_corroboration_check"):
                clause = c
    assert clause is not None, "the drv corroboration clause left the flow"
    cond = clause["condition_files_exist"]
    for d in _gate._PNR_DIRS:
        assert f"{d}/{_gate._NOT_RUN_RECORD}" in cond, (d, cond)
        assert f"{d}/{_gate._PROMOTION_MARKER}" in cond, (d, cond)


def test_the_clause_is_reachable_by_the_guards_own_classifier(tmp_path):
    """The guard, not a paraphrase of it. Ask `classify()` directly so this
    cannot drift from what the build actually runs.

    RED WITHOUT THE FIX: verdict "self-disabling", which is the finding
    `plugin_full_audit` D2 reports on origin/main.
    """
    import flow_condition_reachability_check as _g  # noqa: E402
    recs = [r for r in _g.classify(FLOW_YAML)
            if r["program"] == "drv_promotion_corroboration_check"]
    assert len(recs) == 1, recs
    assert recs[0]["verdict"] == "legitimate-scoping", recs[0]
    assert "T2" in recs[0]["detail"], (
        "the clause is reachable for some reason OTHER than the producer's "
        "disclosure record, which is not the fix this file pins: "
        + recs[0]["detail"])


def test_the_mandatory_wiring_is_now_neutral_on_the_normal_day(tmp_path):
    """THE MEASUREMENT THAT DISSOLVES THE COLLISION, and the reason this file
    exists rather than an allowlist entry.

    The clause is wired MANDATORY — a plain `program_exit_zero` with no
    condition at all, the spelling v1.14.49 said could never be neutral on a
    certifying step. With the fixed gate the normal day (no promotion, producer
    declared it) is an ordinary PASS, not VACUOUS-PASS, so the step is not
    demoted and its descendants are not voided.

    RED WITHOUT THE FIX: on origin/main this same wiring gives VACUOUS-PASS,
    which is precisely what v1.14.49 measured and what made it conclude the two
    doctrines were irreconcilable.
    """
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    st = [s for s in doc["steps"] if str(s.get("id")) == "23"][0]
    for k in ("blocks_on", "required_inputs", "required_outputs", "closed_loop"):
        st.pop(k, None)
    keep = [c for c in st["gate"]["all_of"]
            if "drv_promotion_corroboration_check" in yaml.safe_dump(c)]
    assert len(keep) == 1
    cmd = keep[0]["optional_program_exit_zero"]["command"]
    st["gate"] = {"all_of": [{"program_exit_zero": cmd}]}
    doc["steps"] = [st]
    doc["total_steps"] = 1
    doc.pop("final_gate", None)
    sub = tmp_path / "mandatory.yaml"
    sub.write_text(yaml.safe_dump(doc, sort_keys=False, width=250))

    proj = tmp_path / "proj"
    proj.mkdir()
    _declined(proj)
    rep = tmp_path / "fcc.json"
    subprocess.run([sys.executable, str(FCC), str(proj), "--flow-def", str(sub),
                    "--strict", "--json", str(rep)],
                   capture_output=True, text=True)
    got = json.loads(rep.read_text())
    status = [s.get("status") for s in got["steps"] if str(s.get("id")) == "23"]
    assert status == ["PASS"], (
        f"the mandatory wiring gave step 23 {status} on the normal day; "
        f"VACUOUS-PASS here is the v1.14.49 demotion recurring")
