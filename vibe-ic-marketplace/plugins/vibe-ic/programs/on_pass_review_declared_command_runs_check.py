#!/usr/bin/env python3
"""on_pass_review_declared_command_runs_check — the declared command must RUN.

ENFORCEMENT: blocking. This gate's rc IS a landing decision: rc=1 means a
declared on-pass command cannot reach a verdict, and shipping it would restore
exactly the state v1.13.32 and v1.13.42 were each written to end. It is wired
in `flow/phase1_phase2_phase3.yaml` as a `program_exit_zero` clause, which is
the slot whose rc stops the step.

STATED FIRST, NOT WHERE THE ARGUMENT FOR IT ENDS. `flow_gate_enforcement_audit`
reads a program's declaration out of its first `DECL_WINDOW_BYTES` (4000) bytes.
This line sat at byte 10336 — correctly spelt, opening its own line, and unread,
so the audit would have reported this gate UNDECLARED and a wiring decision
could have been taken without ever seeing what the gate says about itself. The
measured account below is the evidence for the declaration; it is not a
prerequisite for reading it.

WHAT WAS MISSING, AND IT IS ONE LEVEL DEEPER THAN #1858
=======================================================
v1.13.32 found five on-pass clauses DECLARED WHERE THE ENGINE NEVER LOOKED.
v1.13.42 found six whose declared argv carried neither `--compliance` nor
`--stage-verdict`, so `stage_on_pass_review.stage_passed()` returned
UNESTABLISHED and the program returned rc=2 before consulting a rule — on every
input, forever. `on_pass_review_answerable_check` was written for that, and it
asks a question about the argv's TEXT: is a verdict flag spelt in it.

MEASURED ON v1.13.54 (118a12fa9fb2245fca10e84b16cb287692687fd9), mutating
stage3's clause and running BOTH nets against the repo's own known-BAD fixture
`stage3_on_pass_review/reject_sgmii` — which the pristine clause rejects at
rc=1 with R3 proven and its regression emitted:

    mutation of the DECLARED clause      answerable_check   14-file suite   gate
    --stage stage3      -> stage2              rc=0 PASS      304 passed     rc=2
    --stage stage3      -> stage99             rc=0 PASS      304 passed     rc=2
    --stage stage3      -> stage5_manufacturing rc=0 PASS     304 passed     rc=2
    --emit-test /proc/nope/x  (added)          rc=0 PASS      304 passed     rc=2
    project positional "." -> "./no_such_dir"  rc=0 PASS      304 passed     rc=2
    "--flow-def /dev/null"    (added)          rc=0 PASS      304 passed     rc=2

SIX mutants, both nets green, and the gate can never answer again. Every one of
them keeps `--compliance <the report final_gate writes>` — everything P1 and P2
of the answerable check ask for — and breaks REACHABILITY one level down inside
`stage_on_pass_review.main()`'s rc=2 ladder: WHICH stage is asked, WHICH
project is read, WHERE the proof is written, WHICH flow is parsed.

THE CAUSE IS ONE SENTENCE. Nothing anywhere executes the flow's declared
`gate.program_exit_zero`. The strongest assertion on a declared command in the
whole tree is a substring test — `tests/test_stage_analog_on_pass_review.py`:

    assert STAGE in blk["gate"]["program_exit_zero"]
    assert "stage_on_pass_review" in blk["gate"]["program_exit_zero"]

and the CI fixture that proves the answerable check says so about itself in its
own first line: "THE MUTATION IS ONE FLAG". Every stage test invokes the
program with its OWN hand-built argv (`run(tree(tmp_path, ...),
"--stage-verdict", "PASS")`). The suite proves the PROGRAM works. Nothing
proved the DECLARED COMMAND works.

WHAT THIS CHECKS, AND WHY IT IS EXECUTION AND NOT A LONGER TEXT TEST
====================================================================
A longer text test is what the last two fixes were, and each one was evaded by
the next spelling. The only question that cannot be evaded by a spelling is
whether the command, run as written, reaches a verdict. So this gate RUNS it.

For every ENABLED `on_pass_review:` the flow declares:

P1  DISPATCHED.  The command must appear in `steps:`, the only section
    `flow_compliance_check` reads (`steps = flow.get("steps", [])`). A clause
    anywhere else is dispatched by nothing.
P2  THE SLOT MATCHES THE DECLARED VERDICT.  `verdict: advisory` must be wired
    through `advisory_program_exit_zero` — the slot that RUNS the gate and
    records the verdict without changing the step's tier. Wiring an advisory
    review through `program_exit_zero` would make a rejection stop the step
    (turning "unverified" into "blocking", which #1253 refuses) and would read
    the program's rc=2 NOT CHECKED as VACUOUS_PASS.
P3  THE BACK-POINTER IS TRUE.  `dispatched_by:` must name the step that
    actually carries the clause. A pointer nobody checks is a comment.
P4  `fires_on: stage_pass`.  MEASURED on v1.13.54: setting it to "never" left
    the gate rejecting unchanged — the field is read by nothing, and a field
    the engine does not read is worse than an absent one because the flow
    author believes it. Reading it here makes it load-bearing.
P5  `emit_test_dir:` IS RELATIVE.  MEASURED on v1.13.54: pointed at an absolute
    path outside the run, the review still returns rc=1 REJECT and writes its
    regression OUTSIDE the run tree, with an absolute path in the record's
    `test:` field. A rejection whose evidence lands where nobody will look is
    an unproven rejection wearing a proof.
P6  IT RUNS, AND IT REFUSES.  The declared argv is executed VERBATIM against
    that stage's own published known-BAD tree; rc must be 1, the record must
    carry at least one rejection, and each rejection's emitted `test:` must
    resolve INSIDE the run tree and exist on disk.
P8  THE HOST STEP IS REACHABLE.  A clause the engine can SEE is not a clause
    the engine RUNS. A step whose `condition:` is unmet is SKIPPED-CONDITION and
    ITS GATE IS NOT RUN, so a review hosted there is silent on every project
    whose tree does not happen to satisfy that condition.
    MEASURED at v1.13.70, and this is the defect that wrote this check: stage4's
    review — R4_DIE_IS_NOT_THE_DESIGN, the one rule that reads the artefact that
    actually LEAVES — was hosted on step 40, whose `condition:` is
    `files_exist: [phase3/stage5_manufacturing/silicon_received.json]`.
    `find` over the v1.13.70 tree returns 0 such files and
    `git log --all --diff-filter=A -- '*silicon_received.json'` is EMPTY: no
    commit in this repository's history has ever added that path. Running
    `flow_compliance_check` on a tree with and without the file flips step 40
    between SKIPPED-CONDITION (clause never dispatched) and FAIL (clause
    dispatched), so the condition is the whole of it.
    A condition naming only paths the flow ITSELF undertakes to write (some
    step's `required_outputs`) is not a hazard and is allowed; anything else
    gates the review on work outside the flow.

    THIS IS NOT `flow_condition_reachability_check` RESTATED, AND THE TWO MUST
    NOT BE MERGED. That program asks the #210/#219 question -- "if the thing
    this step checks for went wrong, would this condition still be true?" -- and
    it reaches the OPPOSITE verdict on this very path ON PURPOSE: its `T1
    DECLARATION` list carries `phase3/stage5_manufacturing/silicon_received.json`
    by name, because a manufacturing INTAKE MARKER is a declaration that silicon
    arrived, not a result the step produces, so conditioning a fab-intake step on
    it is correct scoping. It is right, and it stays right (it is rc=0 on the
    flow this change ships); it says nothing about the question here, which is
    not "is this condition self-disabling" but "may a review that fires on
    `stage_pass` be hosted behind it at all". A review is conditioned on the
    stage passing and on nothing else, so for THIS clause the only acceptable
    trigger is that program's `T3 BACKSTOP` shape -- a path the flow's own
    `required_outputs` undertake to write. Same document, two questions, and
    each program answers only its own.
P9  THE CLAUSE ITSELF IS NOT CONDITIONED.  The same silence is available one
    level down, through the slot's own `condition_files_exist:` +
    `absent_condition_reason:` escape: `_evaluate_gate` then returns True with
    "n/a (declared; condition ... matched 0 path(s), so it did not run)" and the
    program is never started. Same rule as P8: flow-produced paths only.

WHY P8 AND P9 EXIST AT ALL, WHEN P6 ALREADY EXECUTES THE COMMAND
================================================================
Because P6 executes it ITSELF. It resolves the argv, materialises a fixture, and
runs the child with `cwd=<that tree>`; it proves the COMMAND works and cannot
prove that the ENGINE ever reaches it. Both nets were measured green against two
deliberate mutations of v1.13.70's flow, each of which leaves the command
perfectly answerable and perfectly executable and stops the engine from starting
it:
    M1  `condition: {files_exist: ["never/exists/at/all.json"]}` on step 7
        (the host of stage1's review, which today declares none)
    M2  the same condition moved onto the clause, as
        `condition_files_exist:` + `absent_condition_reason:`
    on_pass_review_answerable_check            rc=0 on both
    on_pass_review_declared_command_runs_check rc=0 on both  (before P8/P9)
A guard that cannot go red for the reason it exists is worse than no guard, so
reachability is checked here, where the host step is already resolved.

P7  AND IT DOES NOT ALWAYS REFUSE.  The same declared argv is executed VERBATIM
    against that stage's own published known-GOOD tree; rc must be 0. This is
    the control, and it is inside the gate on purpose: a "fix" that simply made
    everything block would pass P6 and fail here.

WHAT "VERBATIM" MEANS, EXACTLY, BECAUSE IT IS THE LOAD-BEARING WORD
===================================================================
The child process is

    <python> <stage_on_pass_review.py> --flow-def <the flow being checked>
             *declared_argv[1:]

`declared_argv[0]` is the program name and is resolved to this tree's own copy
— the same resolution `flow_compliance_check._resolve_program_cmd` performs, so
this is not a substitution of behaviour.

`--flow-def` is PREPENDED, never appended, and that is deliberate: argparse
takes the LAST occurrence, so a `--flow-def` smuggled into the declared clause
still wins and is still caught (it is one of the six mutants above). Prepending
supplies the flow under test to a clause that names none; it cannot mask one
that does.

EVERYTHING ELSE IS UNTOUCHED. The project positional stays as written and is
resolved against `cwd=<the materialised run root>`, so a clause that says `.`
reads the run and a clause that says `./no_such_dir` reads nothing. `--stage`,
`--json`, `--emit-test`, `--stage-verdict` are passed through byte-for-byte.

THE ONE THING THIS GATE PLANTS, and why it is not cheating: when the declared
argv names `--compliance <path>`, a report is written at that path inside the
run root saying the stage PASSED. The review fires on `stage_pass`; without a
verdict source it correctly declines. Planting the verdict is what puts the
question — it is not an answer to it, and a clause carrying `--stage-verdict
FAIL` is left alone and duly fails P6, which is correct.

NOTHING TO CHECK IS A FAIL, NEVER A PASS. If the flow declares no enabled
on-pass review, or the published fixture trees this gate measures against are
absent, it returns 1 and says so. An execution check with nothing to execute is
the vacuous pass this whole axis exists to refuse.

chip-AGNOSTIC: every stage id, path and tree name below is read from the flow
and from the fixtures' own PROVENANCE.json. This file names no IC, vendor, SKU
or process.
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - the tree ships pyyaml
    yaml = None

PLUGIN = Path(__file__).resolve().parent.parent
PROGRAMS = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS))
# vibe-ic#1082 — this program's `--json` is a VERDICT, and a `write_text` that
# dies mid-write leaves a half-parsed one at the declared destination for the
# next reader to take as this gate's evidence.
from _atomic_artefact import write_json as atomic_write_json  # noqa: E402
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIXTURES = PROGRAMS / "tests" / "fixtures"
SUBJECT = "stage_on_pass_review"
SUBJECT_PROGRAM = PROGRAMS / "stage_on_pass_review.py"

#: The slot each declared `verdict:` must be wired through. Keyed by the
#: verdict the flow states, so the two can never drift apart silently.
SLOT_FOR_VERDICT = {"advisory": "advisory_program_exit_zero",
                    "blocking": "program_exit_zero"}

#: Every gate slot the engine evaluates — `flow_compliance_check`'s own
#: `_PROGRAM_GATE_KEYS`, restated here because this gate must find a clause in
#: ANY of them to report that it was wired through the wrong one.
GATE_SLOTS = ("program_exit_zero", "optional_program_exit_zero",
              "advisory_program_exit_zero")

#: The one section `flow_compliance_check.main` dispatches from.
DISPATCHED_SECTION = "steps"

#: The known-BAD and known-GOOD tree this gate runs each stage's declared
#: command against, BY NAME. Not "the first tree called reject_*": MEASURED on
#: v1.13.54, `stage_phase1_on_pass_review/reject_pcie_gen5` returns rc=2 (a
#: sibling rule disarms on that cell) and `accept_lpddr5` / `accept_a2b` return
#: rc=2 as well. A control has to be a cell whose answer is known, so the pair
#: is named and the measurement is what put it here. Both trees are published
#: cells this gate's author did not write.
ARMS = {
    "stage_phase1": ("reject_ddr5", "accept_interlaken"),
    "stage1": ("reject_caravel", "accept_spm"),
    "stage2": ("reject_opentitan_aes", "accept_spm"),
    "stage_analog": ("reject_adc_stub", "accept_adc_conv"),
    "stage3": ("reject_sgmii", "accept_subservient"),
    "stage4": ("reject_hawaii_ldo", "accept_spm_ihp"),
}


# ─────────────────────────────────────────────────────────────────────────────
# reading the declaration
# ─────────────────────────────────────────────────────────────────────────────
def _flag_value(argv: List[str], flag: str) -> Optional[str]:
    """The value of `flag` in `argv`, supporting `--f v` and `--f=v`.

    LAST occurrence wins, because that is what argparse does. A checker that
    read the first would disagree with the program it is checking about what
    the command says.
    """
    found = None
    for i, tok in enumerate(argv):
        if tok == flag:
            found = argv[i + 1] if i + 1 < len(argv) else None
        elif tok.startswith(flag + "="):
            found = tok.split("=", 1)[1]
    return found


def _argv(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def step_clauses(flow: dict) -> List[Dict[str, Any]]:
    """Every gate clause under `steps:` that invokes the subject program.

    Structural walk of the shapes `flow_compliance_check._evaluate_gate`
    executes (all_of / any_of lists; a slot holding a bare command string or a
    mapping with `command:`) — not a text scan, so a program name mentioned in
    a comment or in a path argument cannot be read as a clause.
    """
    out: List[Dict[str, Any]] = []

    def walk(node: Any, step: Optional[dict]) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in GATE_SLOTS:
                    cmd = val.get("command") if isinstance(val, dict) else val
                    if isinstance(cmd, str):
                        argv = _argv(cmd)
                        if argv and argv[0] == SUBJECT:
                            out.append({"slot": key, "command": cmd,
                                        "argv": argv,
                                        "step": str((step or {}).get("id")),
                                        "stage": _flag_value(argv, "--stage"),
                                        # P8/P9 read these two. The host step's
                                        # `condition:` and the clause's own
                                        # `condition_files_exist:` are the two
                                        # places the engine decides NOT to run
                                        # a clause it can otherwise see.
                                        "host_condition":
                                            (step or {}).get("condition"),
                                        "clause_condition":
                                            (val.get("condition_files_exist")
                                             if isinstance(val, dict)
                                             else None)})
                walk(val, step)
        elif isinstance(node, list):
            for item in node:
                walk(item, step)

    for step in flow.get(DISPATCHED_SECTION) or []:
        if isinstance(step, dict):
            walk(step.get("gate"), step)
    return out


#: Paths the flow itself undertakes to produce. A `condition:` naming one of
#: these is not a reachability hazard: the run that reaches the step has already
#: been required to write it. A condition naming anything else gates the clause
#: on something outside the flow's own work, and P8/P9 refuse that for a review.
def flow_produced_paths(flow: dict) -> set:
    """Every `required_outputs` pattern any step declares, `OR` alternates split."""
    out = set()
    for step in flow.get(DISPATCHED_SECTION) or []:
        if not isinstance(step, dict):
            continue
        for o in step.get("required_outputs") or []:
            for part in str(o).split(" OR "):
                part = part.strip()
                if part:
                    out.add(part)
    return out


def unproduced(paths, produced: set) -> List[str]:
    """The condition paths this flow never undertakes to write.

    Compared BOTH WAYS with fnmatch, because either side may be the glob: a
    condition may say `phase3/stage4/gds/*.gds` against a literal output, and an
    output may say `reports/*/x.json` against a literal condition.
    """
    missing = []
    for pat in (paths or []):
        pat = str(pat)
        if any(pat == q or fnmatch.fnmatch(pat, q) or fnmatch.fnmatch(q, pat)
               for q in produced):
            continue
        missing.append(pat)
    return missing


def declared_reviews(flow: dict) -> List[Dict[str, Any]]:
    """Every stage carrying an `on_pass_review:`, enabled or not."""
    out = []
    for stage in flow.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        review = stage.get("on_pass_review")
        if not isinstance(review, dict):
            continue
        out.append({
            "stage": str(stage.get("id") or stage.get("name") or "?"),
            # ABSENT `enabled:` MEANS ENABLED — five of the six declare no
            # `enabled` key at all and are live; only stage5 opts out.
            "enabled": review.get("enabled", True) is not False,
            "verdict": review.get("verdict"),
            "fires_on": review.get("fires_on"),
            "emit_test_dir": review.get("emit_test_dir"),
            "dispatched_by": review.get("dispatched_by"),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# materialising a published tree
# ─────────────────────────────────────────────────────────────────────────────
def materialise(stage: str, tree: str, dest: Path) -> None:
    """Write the published tree `tree` into `dest`, from its PROVENANCE.json.

    The layouts are shipped gzipped (a sign-off die is ~0.8-1.6 MB); every
    other file is the published byte stream as-is. This is the same
    materialisation the stage's own test file performs, and it exists here so
    the gate never writes into the shipped fixture.
    """
    fx = FIXTURES / f"{stage}_on_pass_review"
    prov = json.loads((fx / "PROVENANCE.json").read_text(encoding="utf-8"))
    spec = prov["trees"][tree]
    for rel, entry in spec["files"].items():
        # NOT named `out`: `atomic_artifact_write_check` resolves a report
        # destination one assignment hop and is not scope-aware, so a local
        # `out` here is indistinguishable from `out = Path(a.json)` in main().
        # It flagged these two lines, and it was right to — the ambiguity was
        # real. The name is the fix; the writes below go to a temporary tree
        # this gate deletes, never to a declared destination.
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(entry, dict) and "source" in entry:
            dst.write_bytes(gzip.decompress((fx / entry["source"]).read_bytes()))
        else:
            dst.write_bytes((fx / tree / rel).read_bytes())


def run_declared(argv: List[str], flow_path: Path, root: Path,
                 stage: str) -> Tuple[int, str, Optional[dict]]:
    """Execute the DECLARED argv verbatim with `cwd=root`. See the module
    docstring for exactly what "verbatim" covers and what it does not."""
    if "--compliance" in " ".join(argv):
        named = _flag_value(argv, "--compliance")
        if named:
            rep = root / named
            rep.parent.mkdir(parents=True, exist_ok=True)
            rep.write_text(json.dumps(
                {"steps": [{"stage": stage, "status": "PASS"}]}),
                encoding="utf-8")
    child = [sys.executable, str(SUBJECT_PROGRAM),
             "--flow-def", str(flow_path)] + argv[1:]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(child, cwd=str(root), capture_output=True,
                          text=True, env=env)
    record = None
    named_json = _flag_value(argv, "--json")
    if named_json:
        try:
            record = json.loads((root / named_json).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = None
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), record


# ─────────────────────────────────────────────────────────────────────────────
# the checks
# ─────────────────────────────────────────────────────────────────────────────
def analyse(flow_path: Path) -> Tuple[List[str], Dict[str, Any]]:
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    if not isinstance(flow, dict):
        raise ValueError(f"{flow_path} is not a mapping")

    reviews = declared_reviews(flow)
    clauses = step_clauses(flow)
    findings: List[str] = []
    rows: List[Dict[str, Any]] = []

    enabled = [r for r in reviews if r["enabled"]]
    if not enabled:
        findings.append(
            "NOTHING TO CHECK: the flow declares no enabled `on_pass_review:`. "
            "An execution check with nothing to execute concluded nothing, and "
            "that is a FAIL, not a pass.")
        return findings, {"flow": str(flow_path), "stages": []}

    for r in enabled:
        stage = r["stage"]
        row: Dict[str, Any] = {"stage": stage, "checks": {}}
        mine = [c for c in clauses if c["stage"] == stage]

        # P1 — dispatched at all
        if not mine:
            findings.append(
                f"P1 NOT DISPATCHED [{stage}]: no clause under "
                f"`{DISPATCHED_SECTION}:` invokes {SUBJECT} with `--stage "
                f"{stage}`. `flow_compliance_check.main` reads `steps = "
                f"flow.get(\"{DISPATCHED_SECTION}\", [])` and nothing else, so "
                f"a review declared anywhere else is dispatched by nothing.")
            row["checks"]["P1"] = "FAIL"
            rows.append(row)
            continue
        row["checks"]["P1"] = "ok"
        clause = mine[0]
        row["command"] = clause["command"]
        row["slot"] = clause["slot"]
        row["step"] = clause["step"]

        # P2 — the slot matches the declared verdict
        want = SLOT_FOR_VERDICT.get(str(r["verdict"]))
        if want is None:
            findings.append(
                f"P2 UNDECLARED VERDICT [{stage}]: the block declares "
                f"`verdict: {r['verdict']!r}`, which is not one of "
                f"{sorted(SLOT_FOR_VERDICT)}. Whether a rejection blocks is "
                f"the flow's decision and it has not been made.")
            row["checks"]["P2"] = "FAIL"
        elif clause["slot"] != want:
            findings.append(
                f"P2 WRONG SLOT [{stage}]: the block declares `verdict: "
                f"{r['verdict']}` and the clause is wired through "
                f"`{clause['slot']}`, not `{want}`. The slot is what decides "
                f"whether the verdict stops the step; declaring one and wiring "
                f"the other means the flow says two different things.")
            row["checks"]["P2"] = "FAIL"
        else:
            row["checks"]["P2"] = "ok"

        # P3 — the back-pointer is true
        if str(r["dispatched_by"]) != str(clause["step"]):
            findings.append(
                f"P3 BACK-POINTER IS WRONG [{stage}]: the block says "
                f"`dispatched_by: {r['dispatched_by']!r}` and the clause is "
                f"actually on step {clause['step']!r}. A pointer nobody checks "
                f"is a comment.")
            row["checks"]["P3"] = "FAIL"
        else:
            row["checks"]["P3"] = "ok"

        # P4 — fires_on is read HERE, which is what makes it load-bearing
        if str(r["fires_on"]) != "stage_pass":
            findings.append(
                f"P4 fires_on IS NOT stage_pass [{stage}]: the block declares "
                f"`fires_on: {r['fires_on']!r}`. This review reviews a PASS. "
                f"MEASURED on v1.13.54, nothing read this field: set to "
                f"\"never\" the gate went on rejecting unchanged. It is read "
                f"here so the declaration means something.")
            row["checks"]["P4"] = "FAIL"
        else:
            row["checks"]["P4"] = "ok"

        # P5 — the proof must land inside the run
        emit = str(r["emit_test_dir"] or "")
        if not emit or Path(emit).is_absolute():
            findings.append(
                f"P5 emit_test_dir ESCAPES THE RUN [{stage}]: "
                f"`emit_test_dir: {r['emit_test_dir']!r}` is absolute or "
                f"absent. MEASURED on v1.13.54: pointed outside the run tree "
                f"the review still returns rc=1 REJECT and writes its "
                f"regression where nobody will look, with an absolute path in "
                f"the record's `test:` field. A rejection whose evidence "
                f"leaves the run is an unproven rejection wearing a proof.")
            row["checks"]["P5"] = "FAIL"
        else:
            row["checks"]["P5"] = "ok"

        # P8 — is the step that carries the clause one the engine ever reaches?
        produced = flow_produced_paths(flow)
        host_cond = clause.get("host_condition")
        cond_paths = []
        if isinstance(host_cond, dict):
            for key in ("files_exist", "files_absent"):
                cond_paths.extend(host_cond.get(key) or [])
        bad_paths = unproduced(cond_paths, produced)
        if bad_paths:
            findings.append(
                f"P8 THE HOST STEP IS NOT REACHABLE [{stage}]: the clause is on "
                f"step {clause['step']!r}, which declares `condition: "
                f"{host_cond}`. A step whose condition is unmet is "
                f"SKIPPED-CONDITION and ITS GATE IS NOT RUN, and no step in "
                f"this flow declares "
                f"{', '.join(repr(b) for b in bad_paths)} among its "
                f"`required_outputs` — so nothing the flow does can satisfy it "
                f"and this review is silent on every run. Being declared where "
                f"the engine LOOKS is not the same as being declared where the "
                f"engine ARRIVES. Host it on a step with no condition, or on "
                f"one conditioned only on artefacts the flow itself writes.")
            row["checks"]["P8"] = "FAIL"
        else:
            row["checks"]["P8"] = "ok"

        # P9 — and is the clause itself conditioned out of existence?
        clause_cond = clause.get("clause_condition")
        bad_clause = unproduced(clause_cond or [], produced)
        if bad_clause:
            findings.append(
                f"P9 THE CLAUSE IS CONDITIONED OUT [{stage}]: the clause "
                f"carries `condition_files_exist: {clause_cond}`, and no step "
                f"in this flow declares "
                f"{', '.join(repr(b) for b in bad_clause)} among its "
                f"`required_outputs`. `_evaluate_gate` then returns True with "
                f"\"n/a (declared; condition ... matched 0 path(s), so it did "
                f"not run)\" and never starts the program — the same silence as "
                f"P8, one level down and wearing a disclosure. A review that "
                f"fires on `stage_pass` is conditioned on the stage passing and "
                f"on nothing else.")
            row["checks"]["P9"] = "FAIL"
        else:
            row["checks"]["P9"] = "ok"

        # P6 / P7 — it runs, it refuses, and it does not always refuse
        pair = ARMS.get(stage)
        if pair is None:
            findings.append(
                f"P6 NO MEASURED ARM PAIR [{stage}]: this gate has no named "
                f"known-BAD/known-GOOD tree for this stage, so it cannot "
                f"execute the declared command against anything. A stage wired "
                f"without a control is not covered by this gate; name the pair "
                f"in `ARMS` and measure it.")
            row["checks"]["P6"] = "FAIL"
            rows.append(row)
            continue
        bad, good = pair
        fx = FIXTURES / f"{stage}_on_pass_review"
        if not (fx / "PROVENANCE.json").is_file():
            findings.append(
                f"P6 FIXTURES ABSENT [{stage}]: {fx}/PROVENANCE.json is not "
                f"readable, so the declared command was executed against "
                f"nothing. Nothing to check is a FAIL, not a pass.")
            row["checks"]["P6"] = "FAIL"
            rows.append(row)
            continue

        for label, tree, want_rc in (("P6", bad, 1), ("P7", good, 0)):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td) / "run"
                root.mkdir(parents=True)
                try:
                    materialise(stage, tree, root)
                except (OSError, KeyError, ValueError) as exc:
                    findings.append(
                        f"{label} TREE UNREADABLE [{stage}]: could not "
                        f"materialise {tree!r}: {exc}")
                    row["checks"][label] = "FAIL"
                    continue
                rc, out, record = run_declared(clause["argv"], flow_path,
                                               root, stage)
                row.setdefault("arms", {})[label] = {
                    "tree": tree, "rc": rc, "expected_rc": want_rc}
                if rc != want_rc:
                    what = ("REFUSE the published known-BAD tree"
                            if want_rc == 1 else
                            "ACCEPT the published known-GOOD tree")
                    findings.append(
                        f"{label} THE DECLARED COMMAND CANNOT {what} "
                        f"[{stage}]: run verbatim against {tree!r} it exited "
                        f"{rc}, expected {want_rc}. rc=2 means THE QUESTION "
                        f"COULD NOT BE PUT — a gate that answers 2 on every "
                        f"input is a comment wearing a gate's name. "
                        f"Command: {clause['command']}  ::  "
                        f"{out.strip().splitlines()[0][:220] if out.strip() else '(no output)'}")
                    row["checks"][label] = "FAIL"
                    continue
                if want_rc == 1:
                    rejections = (record or {}).get("rejections") or []
                    if not rejections:
                        findings.append(
                            f"{label} REFUSED WITHOUT A PROVEN REJECTION "
                            f"[{stage}]: rc=1 against {tree!r} but the record "
                            f"the clause's own `--json` names carries no "
                            f"`rejections`. A refusal with no proof is not a "
                            f"refusal this flow can act on.")
                        row["checks"][label] = "FAIL"
                        continue
                    escaped = []
                    for f in rejections:
                        rel = str(f.get("test") or "")
                        p = Path(rel)
                        if not rel or p.is_absolute() or not (root / rel).is_file():
                            escaped.append(rel or "(absent)")
                    if escaped:
                        findings.append(
                            f"{label} THE PROOF DID NOT LAND IN THE RUN "
                            f"[{stage}]: {len(escaped)} emitted regression(s) "
                            f"are absolute or absent inside the run tree: "
                            f"{', '.join(escaped)}. The rejection cites a test "
                            f"nobody reading this run can open.")
                        row["checks"][label] = "FAIL"
                        continue
                    row["arms"][label]["rejections"] = [
                        {"rule": f.get("rule"), "test": f.get("test")}
                        for f in rejections]
                row["checks"][label] = "ok"
        rows.append(row)

    return findings, {"flow": str(flow_path), "stages": rows,
                      "enabled": len(enabled)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", nargs="?", default=".",
                    help="accepted and unused: this gate reads the FLOW and "
                         "the published trees, never the project. Declared so "
                         "the flow's clause shape matches every other gate.")
    ap.add_argument("--flow", default=str(FLOW),
                    help="flow definition to check (default: this tree's own)")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    if yaml is None:
        print("[FAIL] on_pass_review_declared_command_runs_check: pyyaml "
              "unavailable, so no declared command was executed. Nothing to "
              "check is a FAIL, not a pass.")
        return 1
    try:
        findings, report = analyse(Path(a.flow).resolve())
    except Exception as exc:
        print(f"[FAIL] on_pass_review_declared_command_runs_check: cannot read "
              f"input: {exc}")
        return 1
    report["findings"] = findings
    report["verdict"] = "FAIL" if findings else "PASS"
    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out, report, indent=2)
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings:
        for row in report["stages"]:
            arms = row.get("arms") or {}
            print(f"    {row['stage']:14} step {str(row.get('step')):4} "
                  f"{row.get('slot')}  "
                  f"BAD {arms.get('P6', {}).get('tree')} rc=1  "
                  f"GOOD {arms.get('P7', {}).get('tree')} rc=0")
        # THE PROJECT POSITIONAL IS NEVER OPENED, and until this line said so
        # this gate answered rc 0 for a project path that does not exist,
        # without disclosing it (#511/#564) — a caller could not tell a
        # typo'd path from a clean chip, and the clean answer is the one that
        # gets acted on. This is not a blindness to fix: the population is the
        # flow document and the published known-BAD/known-GOOD trees, and it
        # is stated above. What was missing was saying which question the
        # positional does NOT answer.
        print(f"       project positional {str(a.project_dir)!r}: not "
              f"applicable — no project directory is opened by this gate; its "
              f"population is {a.flow} and the published trees named above.")
        print(f"[PASS] on_pass_review_declared_command_runs_check: "
              f"{report['enabled']} declared on-pass command(s) sit on a step "
              f"the engine REACHES (no unsatisfiable `condition:` on the host "
              f"or on the clause) and were EXECUTED verbatim; each refused its "
              f"published known-BAD tree at rc=1 with its regression inside the "
              f"run, and accepted its published known-GOOD tree at rc=0.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
