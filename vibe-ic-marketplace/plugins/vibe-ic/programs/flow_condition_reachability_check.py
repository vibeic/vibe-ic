#!/usr/bin/env python3
"""flow_condition_reachability_check.py — the self-disabling-condition guard.

The defect class (measured twice, independently, in one day)
------------------------------------------------------------
A flow step is conditioned on a file. That same file's ABSENCE is the defect
the step exists to catch. So when the defect occurs the condition is false, the
step does not run, and the run reports nothing wrong. **The check is disabled
by exactly the situation it was written for.**

Instance 1 — `post_route_signoff_corner_check` (#210) was wired as

    optional_program_exit_zero:
      command: "post_route_signoff_corner_check . --json ..."
      condition_files_exist: ["phase3/stage3/sta/sta_spef_multicorner.rpt"]

so a vanished multicorner report produced NOT_APPLICABLE, and a vanished hold
corner produced `PASS — all analyzed sign-off corners MET`. The word *analyzed*
silently excludes whatever disappeared.

Instance 2 — DT1 transition-delay ATPG (#219) gated the step on
`cut_netlist.v`, and an absent cut netlist is precisely the symptom. The gate
never ran, so `transition_coverage_check` — which ALREADY FAILs on an absent
artefact — was never reached.

Two authors, two subsystems, one day. This program makes the class EXTINCT
rather than fixed twice: it scans the canonical flow YAML and FAILs when any
condition is unreachable in the very scenario its step exists to detect, so a
future step cannot silently re-introduce the shape.

THE RULE (deterministic, no LLM)
--------------------------------
For every condition — step-level `condition:` and predicate-level
`optional_program_exit_zero.condition_files_exist` — ask the issue's question:

    If the thing this step checks for went wrong, would this condition
    still be true?

A condition is REACHABLE (and therefore fine) when at least one of its trigger
paths survives its own subject's absence. Three ways a trigger survives:

  T1 DECLARATION — the trigger is a design-shape declaration or a user/PDK
     input, not a result the step produces. "Skip the analog gate on a purely
     digital design" is correct SCOPING, not a defect. `analog_block_list.json`,
     `phase1/generated_docs/L*.json`, `input/**`, `signoff/**` and the
     `silicon_received.json` intake marker are declarations: a broken analog
     block does not delete the declaration that the block exists.

  T2 DISCLOSURE — the trigger is a `*_not_run.json` / `*_skipped.json` record.
     This is the #219 shape: the producer ALWAYS leaves either a result or a
     record saying why there is none, and either one reaches the gate, so an
     unrunnable step reports BLOCKED instead of disappearing.

  T3 BACKSTOP — the trigger is the SOLE `required_outputs` pattern of some
     step. Then its absence already forces that step to MISSING, which is loud.
     The `len(required_outputs) == 1` test is load-bearing and NOT pedantry:
     `check_step` marks a step MISSING only when NO required_output matched
     (`if outputs and not result.evidence`), so required_outputs is ANY-of.
     A path listed alongside others can vanish while the step still passes on a
     sibling — which is exactly how a spare-cell manifest disappears without
     anybody noticing.

  T4 HARD-GATE — the same step's gate already carries a NON-optional
     `files_exist` predicate naming that path. Then the path's absence FAILs
     the step through the hard predicate before the conditioned checker is ever
     needed, so the condition hides nothing. This is why Step 18's two
     spare-cell checks are correct scoping and not holes: `all_of` opens with a
     hard `files_exist: ["phase3/stage3/pnr/spare_cells.json"]`, so a design
     with no spare cells FAILs loudly at that predicate. Skipping T4 would make
     this gate cry wolf on a step that is already safe.

Otherwise the condition is SELF-DISABLING and this gate FAILs it.

Known-open holes live in `flow_condition_reachability_baseline.json` next to
the flow YAML: a checked-in, reviewable list of conditions that ARE holes and
are owned by a named issue/PR. A hole in the baseline is reported but does not
fail the build; a hole NOT in the baseline fails. A baseline entry that is no
longer a hole ALSO fails, so the file cannot rot into a permanent excuse. The
baseline is deliberately visible — an invisible skip was never a pass, and a
hole nobody has fixed yet should at least be one everybody can see.

A stricter sub-rule fires first, because it is the purest form of the bug:

  R1 SELF-GATE — a step gated on its OWN `required_outputs` when that step has
     more than one required_output pattern. The step is conditioned on the
     artefact it is responsible for producing, and the any-of required_outputs
     rule means a sibling output keeps the step green while the gated artefact
     is gone.

Legitimate exceptions live in `ALLOWLIST` below, each with a written
justification. A new step is FAIL-CLOSED by default: it must either carry a
surviving trigger or earn an allowlist entry under review. That default is what
makes the class extinct instead of merely fixed.

Usage:
    python3 flow_condition_reachability_check.py [<flow_yaml>] [--json <out>]
    # default flow_yaml = <plugin>/flow/phase1_phase2_phase3.yaml

THE SECOND RULE — AN UNDECLARED NOT-APPLICABLE (W4)
---------------------------------------------------
Everything above asks whether a condition can be false EXACTLY WHEN the defect
it guards occurs. It does not ask what the RUN learns on the ordinary days the
condition is false for a perfectly good reason — and until W4 the answer was
"nothing": `flow_compliance_check` returned a bare `True` with no marker and no
reason, so a clause that never ran was indistinguishable in the record from one
that ran and found nothing. A condition can be entirely reachable and still
leave that hole in every run where it does not fire.

So every `optional_program_exit_zero` clause must DECLARE, at its own wiring
site, why an absent input is a genuine not-applicable:

    optional_program_exit_zero:
      command: "..."
      condition_files_exist: ["..."]
      absent_condition_reason: "<why nothing to check is legitimate here>"

A clause with no such declaration — or one whose declaration is too short to
be checkable — FAILs this gate, and `flow_compliance_check` FAILs the clause at
run time for the same reason. The declaration lives at the clause and not in
`ALLOWLIST` below deliberately: a registry keyed by (step, program, path)
desynchronises silently — a renamed program loses its entry and a deleted
clause leaves a rotting one — while deleting the clause deletes its declaration
with it. `ALLOWLIST` keeps its own, narrower job: excusing a condition this
gate has judged SELF-DISABLING.

Exit: 0 = every condition reachable and every optional clause declared (PASS) /
1 = self-disabling condition(s) or undeclared not-applicable(s) found (FAIL) /
2 = flow YAML not found or unparseable (operational).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- T1
# Roots whose contents are DECLARATIONS (design shape / user input / PDK), not
# results produced by the step being gated. Gating on these is correct scoping.
DECLARATION_ROOTS = (
    "phase1/generated_docs/",  # Phase-1 spec layers; completeness gated by D1
    "phase1/analog/",          # analog design-shape declaration
    "phase3/analog/hardmacro",  # analog hardmacro handoff (present or design
                                # has no analog macro to integrate)
    "input/",                  # user inputs + PDK
    "signoff/",                # PDK-provided sign-off decks
)
DECLARATION_FILES = (
    # Manufacturing intake marker: no silicon received is a genuine N/A, and
    # nothing a design step does can delete it.
    "phase3/stage5_manufacturing/silicon_received.json",
)

# ---------------------------------------------------------------- T2
DISCLOSURE_SUFFIXES = ("_not_run.json", "_skipped.json", "_not_run.flag")

# ---------------------------------------------------------------- W4
#: Minimum usable length of an `absent_condition_reason`. Kept EQUAL to
#: `flow_compliance_check._MIN_ABSENT_CONDITION_REASON` so a clause this gate
#: passes cannot be one the runtime refuses — the two are asserted equal by
#: `test_w4_absent_condition_is_not_a_pass.py`, because two hand-kept numbers
#: are two numbers that drift. A one-word "N/A" is a label on the hole, not the
#: hole closed; the floor is on EFFORT, and length is not being claimed as truth.
MIN_ABSENT_CONDITION_REASON = 40

# ---------------------------------------------------------------- allowlist
# (step_id, program_or_None, frozenset(condition paths)) -> justification.
# `program` is None for a step-level condition.
ALLOWLIST: dict[tuple, str] = {
    ("36", "ppa_head_to_head_check",
     "**/*head_to_head*.json"):
        "The subject is a CLAIM, not a result — the same shape as "
        "`rtl_bug_report_schema_check` below, with one property that one does "
        "not have. A PPA head-to-head record is produced by a comparison "
        "campaign against another flow, never by a design run, so nearly every "
        "sign-off legitimately files none; the failure this gate exists for, a "
        "comparison that cannot support the claim printed on it, REQUIRES the "
        "claim to exist. "
        "WHY THE CONDITION CANNOT HIDE ONE: the trigger glob IS the checker's "
        "own `_RECORD_GLOB`, so 'the condition matched nothing' and 'the corpus "
        "held nothing' are the SAME SET by construction — there is no state in "
        "which a claim was filed and this clause declined to look. That is what "
        "separates it from the self-disabling shape this gate exists to refuse, "
        "where the trigger names an artefact the flow itself produces and its "
        "absence is the very defect being skipped. "
        "WHY NOT UNCONDITIONAL, MEASURED: `--corpus .` returns rc 2 on a run "
        "that files no record, and `check_step` reads ONE vacuous clause beside "
        "substantive ones as 'every clause was vacuous' (a substantive sub-gate "
        "appends nothing). Wiring it unconditionally therefore demoted step 36 "
        "— the tapeout sign-off itself — from PASS to VACUOUS_PASS on every "
        "ordinary run, which is the mis-fire that withdrew v1.10.14.",
    ("2", "rtl_bug_report_schema_check",
     "reports/phase2/rtl_bugs.json"):
        "The subject is a CLAIM file, not a result. This gate validates the "
        "schema of an RTL-bug report when one is filed; a run that files no "
        "bug claim has nothing to schema-check. Absence is the normal case, "
        "not the failure mode — the failure mode is a malformed claim, which "
        "requires the claim to exist.",
    ("32", "eco_loop_audit",
     "phase3/stage3/eco/eco_log.json"):
        "Step 32's required_outputs is the single any-of pattern "
        "`eco_log.json OR no_eco_needed.flag`, so an ECO that ran and wrote no "
        "log leaves NEITHER and the step goes MISSING (loud). The condition's "
        "false branch therefore coincides with an honestly declared no-ECO "
        "run, not with a silent loss.",
    ("23", "post_route_signoff_corner_check",
     "phase3/stage3/sta/sta_spef_multicorner.rpt"):
        "SEMANTIC BACKSTOP, not mechanically derivable. This condition IS the "
        "self-disabling shape — it is Instance 1 from the issue. #210 fixed it "
        "not by changing this predicate but by adding the UNCONDITIONAL "
        "companion `sta_corner_record_completeness_check` to the same step "
        "(flow YAML line ~1250), which starts from the corners the flow "
        "DECLARED and FAILs when the record fails to account for each of them. "
        "An absent multicorner report is therefore now caught by the "
        "companion. Keeping the condition here only avoids a duplicate "
        "failure; it no longer hides one.",
    ("6", "fpga_verification_audit",
     "reports/fpga_verification_report.md"):
        "Scoping to a HUMAN deliverable on a HARDWARE-bearing run. The audit "
        "judges the honesty of a hand-authored FPGA verification report; a "
        "headless doc-to-GDS run has no board and authors no such report. "
        "Absence is covered by dedicated machinery rather than this gate: "
        "`--skip-hardware` routes the FPGA-board steps to an explicit WAIVED "
        "with a review_required at board-bringup, and Step 6 still hard-"
        "requires the .sof glob plus quartus_map_audit.json.",
    ("A9", "analog_hw_spice_correlation_check",
     "phase3/analog/*/hw_measurements.json"):
        "Scoping to bench-hardware availability, the analog analogue of "
        "`--skip-hardware`. The gate correlates measured silicon against SPICE; "
        "with no lab measurement there are no two things to correlate. A9's "
        "required_outputs already accepts the cosim result as the alternative "
        "evidence path, so a run that simulated but never measured is judged on "
        "the cosim, not silently exempted. "
        "STATED-VS-IMPLEMENTED CORRECTION: for a long time the sentence above "
        "was true only of this sub-gate. The `--skip-hardware` analogy it "
        "invokes was NOT implemented — that routing is guarded by "
        "`isinstance(sid, int)` and A9's id is the string \"A9\", so the flag "
        "silently did nothing here — and the STEP as a whole reported a bare "
        "PASS on a run with no hardware evidence at all, indistinguishable from "
        "a bench-verified close. Both halves are now real: A9 is in "
        "`_ANALOG_BENCH_STEP_IDS` so `--skip-hardware` waives it the way it "
        "waives step 6, and A9's gate runs `analog_a9_hw_verify_check`, whose "
        "rc=2 surfaces a simulation-only close as VACUOUS_PASS rather than "
        "PASS. Simulation-only closure stays legal; it is no longer silent.",
    ("27", "si_mcf_sta_check",
     "reports/phase3/si_mcf_sta.json"):
        "Documented ADVISORY axis, as a GATE only. The MCF crosstalk-delay "
        "check is a conservative BOUND (not PrimeTime-SI's iterative "
        "coupled-waveform calc), and the flow YAML comment states it "
        "validates the emitted report rather than hard-failing a negative "
        "bounded slack, so a self-disabling condition here does not silently "
        "excuse a finding. "
        "2026-07-28 — the second half of this justification was RETIRED, not "
        "re-worded: it used to add that the noise/glitch any_of alone means "
        "'Step 27 cannot pass with no SI evidence at all'. Since step 27 "
        "declares reports/phase3/si_mcf_sta_check.json in required_outputs, "
        "the crosstalk axis alone no longer suffices — MEASURED on a fresh "
        "copy of benchmark-data/ic/spm/v1.5.58_ihp-sg13g2 with the MCF "
        "artefacts deleted, step 27 resolves MISSING, not PASS. The axis is "
        "advisory as a gate and MANDATORY as an output, which is what makes "
        "the self-disabling condition tolerable rather than the old claim.",
}


def _walk_steps(doc) -> list:
    """Return the steps[] list wherever it lives in the flow doc."""
    if isinstance(doc, dict):
        s = doc.get("steps")
        if isinstance(s, list):
            return s
        for v in doc.values():
            r = _walk_steps(v)
            if r:
                return r
    return []


def _or_branches(pattern: str) -> list[str]:
    """required_outputs patterns may be `A OR B`; return the branches."""
    return [p.strip() for p in str(pattern).split(" OR ") if p.strip()]


def _same_path(a: str, b: str) -> bool:
    """Conservative path identity for YAML-declared paths.

    Exact match, or one is the other with a trailing glob segment removed.
    Deliberately NOT substring matching: `phase2/stage2/synth` (a directory
    trigger) must not be conflated with `phase2/stage2/synth/netlist.v` (a file
    output), because the directory can exist while the netlist is gone.
    """
    a = a.strip().rstrip("/")
    b = b.strip().rstrip("/")
    return a == b


def _is_declaration(path: str) -> bool:
    p = path.strip()
    if p in DECLARATION_FILES:
        return True
    return any(p.startswith(root) for root in DECLARATION_ROOTS)


def _is_disclosure(path: str) -> bool:
    return any(path.strip().endswith(sfx) for sfx in DISCLOSURE_SUFFIXES)


def _build_backstop_index(steps: list) -> dict[str, str]:
    """Map path -> step id, for steps whose required_outputs is a SINGLE
    pattern. Only those make an absent path loud (see T3 in the docstring)."""
    idx: dict[str, str] = {}
    for st in steps:
        if not isinstance(st, dict):
            continue
        ro = st.get("required_outputs") or []
        if len(ro) != 1:
            continue
        for branch in _or_branches(ro[0]):
            idx.setdefault(branch, str(st.get("id")))
    return idx


def _build_dir_backstop_index(steps: list) -> dict[str, str]:
    """Map directory path -> step id, when some step's required_outputs lives
    UNDER that directory (T5).

    A condition naming a whole source directory (`phase2/stage1/rtl`,
    `phase2/stage2/synth`) is scoping, not self-disabling: the directory only
    vanishes when the step that fills it produced nothing, and THAT step goes
    MISSING on its own required_outputs. The lints gated on the directory are
    about the CONTENT's quality, not the directory's existence, so their
    subject is not what the condition tests.
    """
    idx: dict[str, str] = {}
    for st in steps:
        if not isinstance(st, dict):
            continue
        for pat in (st.get("required_outputs") or []):
            for branch in _or_branches(pat):
                parts = branch.strip("/").split("/")
                for i in range(1, len(parts)):
                    idx.setdefault("/".join(parts[:i]), str(st.get("id")))
    return idx


def _build_hard_gate_index(steps: list) -> dict[str, str]:
    """Map path -> step id for every NON-optional `files_exist` in ANY step's
    gate (T7).

    Cross-step, deliberately: Step 34's spare-cell PRESERVATION check is gated
    on `spare_cells.json`, but Step 18 already hard-requires that same file, so
    a design that never inserted spare cells FAILs at 18 and never reaches 34
    looking clean. The absence is loud somewhere, which is all this rule asks.
    """
    idx: dict[str, str] = {}
    for st in steps:
        if not isinstance(st, dict):
            continue
        for p in _hard_files_exist(st.get("gate")):
            idx.setdefault(p, str(st.get("id")))
    return idx


def _hard_files_exist(gate) -> set[str]:
    """Paths named by NON-optional `files_exist` predicates in a step's gate.

    These are hard requirements: their absence FAILs the step outright, so a
    condition gating on the same path cannot hide the absence (T4). Predicates
    nested inside `optional_program_exit_zero` are NOT hard and are skipped.
    """
    hard: set[str] = set()

    def rec(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "optional_program_exit_zero":
                    continue  # conditioned, not hard
                if k == "files_exist" and isinstance(v, list):
                    for p in v:
                        hard.add(str(p).strip())
                else:
                    rec(v)
        elif isinstance(node, list):
            for i in node:
                rec(i)

    rec(gate)
    return hard


def _collect_conditions(steps: list) -> list[dict]:
    """Every condition in the flow, both surfaces, in document order."""
    out: list[dict] = []
    for st in steps:
        if not isinstance(st, dict):
            continue
        sid = str(st.get("id"))
        name = st.get("name", "")
        ro = st.get("required_outputs") or []
        hard = _hard_files_exist(st.get("gate"))
        cond = st.get("condition")
        if isinstance(cond, dict) and cond.get("files_exist"):
            out.append({
                "surface": "step", "step": sid, "name": name,
                "program": None,
                "paths": [str(p) for p in cond["files_exist"]],
                "any_of": bool(cond.get("any_of", False)),
                "required_outputs": [str(r) for r in ro],
                "hard_files_exist": sorted(hard),
            })

        def rec(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    # W4 — the ADVISORY slot carries the same
                    # `condition_files_exist` shape and had the same silent
                    # skip (`return True  # no inputs -> not applicable ->
                    # silent`). It is collected under its own surface rather
                    # than folded in with the blocking one: the REACHABILITY
                    # verdicts below are calibrated on blocking clauses, and an
                    # advisory clause that self-disables is a different-sized
                    # fact. The declaration requirement applies to both.
                    if (k == "advisory_program_exit_zero"
                            and isinstance(v, dict)
                            and v.get("condition_files_exist")):
                        cmd = str(v.get("command", ""))
                        _why = v.get("absent_condition_reason")
                        out.append({
                            "surface": "advisory", "step": sid, "name": name,
                            "program": cmd.split(" ")[0] or None,
                            "paths": [str(p)
                                      for p in v["condition_files_exist"]],
                            "any_of": True,
                            "required_outputs": [str(r) for r in ro],
                            "hard_files_exist": sorted(hard),
                            "absent_condition_reason": (
                                _why if isinstance(_why, str) else None),
                        })
                    elif (k == "optional_program_exit_zero"
                            and isinstance(v, dict)
                            and v.get("condition_files_exist")):
                        cmd = str(v.get("command", ""))
                        _why = v.get("absent_condition_reason")
                        out.append({
                            "surface": "predicate", "step": sid, "name": name,
                            "program": cmd.split(" ")[0] or None,
                            "paths": [str(p)
                                      for p in v["condition_files_exist"]],
                            "any_of": True,  # predicate conditions are any-of
                            "required_outputs": [str(r) for r in ro],
                            "hard_files_exist": sorted(hard),
                            # W4 — read from the clause, never defaulted to a
                            # string: `None` and `""` must stay distinguishable
                            # from a real declaration in the record this writes.
                            "absent_condition_reason": (
                                _why if isinstance(_why, str) else None),
                        })
                    else:
                        rec(v)
            elif isinstance(node, list):
                for i in node:
                    rec(i)

        rec(st.get("gate"))
    return out


def classify(flow_yaml: Path) -> list[dict]:
    """Classify every condition. Returns one record per condition with a
    verdict of `legitimate-scoping` (reachable) or `self-disabling`."""
    import yaml
    doc = yaml.safe_load(flow_yaml.read_text())
    steps = _walk_steps(doc)
    backstop = _build_backstop_index(steps)
    dir_backstop = _build_dir_backstop_index(steps)
    hard_index = _build_hard_gate_index(steps)
    records = []

    for c in _collect_conditions(steps):
        key = (c["step"], c["program"], ",".join(sorted(c["paths"])))
        allow_key = None
        for k in ALLOWLIST:
            if (k[0] == c["step"] and k[1] == c["program"]
                    and k[2] in c["paths"]):
                allow_key = k
                break

        # --- R1 SELF-GATE: gated on its own output, any-of required_outputs.
        # A path also named by a hard `files_exist` is exempt (T4): its absence
        # already FAILs the step, so the condition conceals nothing.
        _hard = set(c.get("hard_files_exist") or [])
        self_gated = []
        _cand = [p for p in c["paths"]
                 if not any(_same_path(p, h) for h in _hard)]
        if len(c["required_outputs"]) > 1:
            for p in _cand:
                for pat in c["required_outputs"]:
                    if any(_same_path(p, b) for b in _or_branches(pat)):
                        self_gated.append(p)
        # A single required_output pattern with OR branches is also any-of at
        # the branch level: `A OR B` lets B satisfy the step while A is gone.
        elif len(c["required_outputs"]) == 1:
            branches = _or_branches(c["required_outputs"][0])
            if len(branches) > 1:
                for p in _cand:
                    if any(_same_path(p, b) for b in branches):
                        self_gated.append(p)

        # --- T1/T2/T3/T4 reachability
        reasons = {}
        hard = set(c.get("hard_files_exist") or [])
        for p in c["paths"]:
            if _is_declaration(p):
                reasons[p] = "T1 declaration/input"
            elif _is_disclosure(p):
                reasons[p] = "T2 not-run disclosure record"
            elif any(_same_path(p, h) for h in hard):
                reasons[p] = ("T4 hard files_exist in the same step's gate "
                              "(absence FAILs the step outright)")
            elif p in backstop and backstop[p] != c["step"]:
                reasons[p] = f"T3 sole required_output of step {backstop[p]}"
            elif (p in backstop and backstop[p] == c["step"]
                    and c["surface"] == "predicate"):
                # Its own sole required_output. This rescues a PREDICATE only.
                # `check_step` evaluates the step-level `condition` at
                # flow_compliance_check.py:5598 and RETURNS SKIPPED-CONDITION
                # at :5617 — before the required_outputs check at :5651. So a
                # STEP gated on its own required_output never reaches the
                # MISSING path that would have made the absence loud, and the
                # artefact's disappearance is what silences the very step that
                # was supposed to report it (Step 44 / HTOL). A predicate
                # condition lives inside the gate, which runs after :5651, so
                # there the required_outputs check really does fire first.
                reasons[p] = ("T3 own sole required_output, predicate "
                              "surface (required_outputs checked first)")
            elif p in hard_index:
                reasons[p] = (f"T7 hard files_exist in step {hard_index[p]} "
                              f"(absence FAILs there)")
            elif p in dir_backstop:
                reasons[p] = (f"T5 source directory holding step "
                              f"{dir_backstop[p]}'s required_outputs")

        # AND vs ANY-OF semantics. A step-level condition without `any_of` is
        # ALL-of (`_check_condition` returns False on the FIRST missing path),
        # so ONE self-disabling path disarms the whole step and every path must
        # survive. A predicate condition — and `any_of: true` — needs only one
        # surviving trigger, because any single present path runs the check.
        if c["any_of"]:
            reachable = bool(reasons)
            unreachable = [] if reachable else list(c["paths"])
        else:
            unreachable = [p for p in c["paths"] if p not in reasons]
            reachable = not unreachable

        verdict = "legitimate-scoping"
        detail = "; ".join(f"{p}: {r}" for p, r in reasons.items())

        if self_gated:
            verdict = "self-disabling"
            detail = (
                f"R1 self-gate: {sorted(set(self_gated))} is this step's own "
                f"required_output, and required_outputs is ANY-of "
                f"({c['required_outputs']}), so a sibling output keeps the "
                f"step green while the gated artefact is gone.")
        elif not reachable:
            verdict = "self-disabling"
            mode = ("ANY-of: no trigger survives" if c["any_of"] else
                    "ALL-of: every path must be present, and these do not "
                    "survive their own subject's absence")
            detail = (
                f"{mode}: {unreachable} — none is a declaration (T1), a "
                f"not-run disclosure (T2), a backstopped required_output "
                f"(T3/T5), or a hard files_exist (T4/T7).")

        if allow_key and verdict == "self-disabling":
            verdict = "allowlisted"
            detail = ALLOWLIST[allow_key]

        # W4 — the ADVISORY surface is collected for the DECLARATION rule only.
        # The T1-T4/R1 verdicts above were calibrated against blocking clauses
        # and the ALLOWLIST is keyed on them, so letting an advisory clause
        # reach `holes` would fail this gate on a claim it has not measured.
        # Named rather than silently dropped, so a reader of the record can see
        # the clause was collected and see what was and was not asked of it.
        if c["surface"] == "advisory" and verdict == "self-disabling":
            verdict = "advisory-not-judged"
            detail = ("ADVISORY slot: collected for the "
                      "`absent_condition_reason` rule only. The reachability "
                      "verdicts are calibrated on BLOCKING clauses and the "
                      "allowlist is keyed on them, so no reachability claim is "
                      "made here.")

        records.append({**c, "verdict": verdict, "detail": detail})
    return records


_FLOW_REL = Path("flow") / "phase1_phase2_phase3.yaml"


def _resolve_flow_yaml(arg: str | None) -> Path:
    """Accept a flow YAML path, a PLUGIN DIRECTORY, or nothing.

    The plugin-directory form matters: `plugin_full_audit.audit_d2` invokes its
    guards as `[python, <guard>.py, <plugin_dir>]`. A guard that only accepts a
    YAML path answers that call with exit 2 ("cannot find the flow"), and
    audit_d2 records a finding only on exit 1 — so the guard reports nothing
    and the audit looks clean. That is this issue's own pattern one level up:
    a check disabled by the very condition it should report. Resolving the
    directory form keeps the guard reachable however it is invoked.
    """
    if not arg:
        return Path(__file__).resolve().parent.parent / _FLOW_REL
    p = Path(arg)
    if p.is_dir():
        cand = p / _FLOW_REL
        if cand.is_file():
            return cand
        # plugin root passed as the marketplace path
        for sub in p.glob("plugins/*/" + str(_FLOW_REL)):
            return sub
        return cand
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("flow_yaml", nargs="?", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--table", action="store_true",
                    help="print the full classification table, not only holes")
    ap.add_argument("--baseline", default=None,
                    help="known-open holes JSON (default: next to the flow "
                         "YAML). Use --baseline '' to ignore it.")
    a = ap.parse_args(argv)

    flow = _resolve_flow_yaml(a.flow_yaml)

    if not flow.is_file():
        print(f"SKIP: flow YAML not found at {flow}", file=sys.stderr)
        return 2
    try:
        records = classify(flow)
    except Exception as e:
        print(f"SKIP: cannot parse {flow}: {e}", file=sys.stderr)
        return 2

    # ---- baseline of known-open holes -------------------------------------
    if a.baseline is None:
        bpath = flow.parent / "flow_condition_reachability_baseline.json"
    elif a.baseline == "":
        bpath = None
    else:
        bpath = Path(a.baseline)

    baseline: list[dict] = []
    if bpath is not None and bpath.is_file():
        try:
            baseline = json.loads(bpath.read_text()).get("holes", [])
        except Exception as e:
            print(f"SKIP: cannot parse baseline {bpath}: {e}", file=sys.stderr)
            return 2

    def _bkey(step, program, paths):
        return (str(step), program or None, tuple(sorted(str(p)
                                                        for p in paths)))

    base_keys = {_bkey(b.get("step"), b.get("program"), b.get("paths") or [])
                 for b in baseline}

    # ---- W4: every optional clause must DECLARE its not-applicable ------
    # Predicate surface only: a STEP-level `condition:` is a different shape
    # with a different consumer (`check_step` resolves it to
    # SKIPPED-CONDITION, which is already a visible non-PASS tier), so demanding
    # the key there would be demanding a declaration for a state that is
    # already named in the record.
    #
    # NOT FOLDED INTO `holes`, and not answerable by the baseline: the baseline
    # excuses a condition that IS self-disabling and has a named owner. An
    # undeclared not-applicable is not a hazard waiting on an owner — it is one
    # missing line at the clause, and there is no state in which leaving it out
    # is the right call.
    undeclared = []
    for r in records:
        if r["surface"] not in ("predicate", "advisory"):
            continue
        why = r.get("absent_condition_reason")
        why = why.strip() if isinstance(why, str) else ""
        if len(why) < MIN_ABSENT_CONDITION_REASON:
            undeclared.append({**r, "declared_chars": len(why)})

    all_holes = [r for r in records if r["verdict"] == "self-disabling"]
    hole_keys = {_bkey(h["step"], h["program"], h["paths"]) for h in all_holes}

    known = [h for h in all_holes
             if _bkey(h["step"], h["program"], h["paths"]) in base_keys]
    holes = [h for h in all_holes
             if _bkey(h["step"], h["program"], h["paths"]) not in base_keys]
    # A baseline entry that is no longer a hole must be deleted, or the file
    # becomes a permanent excuse that outlives the defect it described.
    stale = [b for b in baseline
             if _bkey(b.get("step"), b.get("program"), b.get("paths") or [])
             not in hole_keys]

    verdict = ("PASS" if (not holes and not stale and not undeclared)
               else "FAIL")
    report = {"gate": "flow_condition_reachability_check", "verdict": verdict,
              "flow_yaml": str(flow), "total_conditions": len(records),
              "holes": holes, "known_open_holes": known,
              "undeclared_not_applicable": undeclared,
              "stale_baseline_entries": stale, "conditions": records}
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n")

    if a.table:
        for r in records:
            tag = {"legitimate-scoping": "ok  ", "allowlisted": "allw",
                   "self-disabling": "HOLE"}[r["verdict"]]
            who = f"{r['step']}/{r['program']}" if r["program"] else r["step"]
            print(f"[{tag}] {who:<46} {r['paths']}")

    if known:
        print(f"KNOWN-OPEN: {len(known)} self-disabling condition(s) listed in "
              f"{bpath.name if bpath else 'baseline'} (reported, not blocking):")
        for h in known:
            who = (f"step {h['step']} predicate {h['program']}"
                   if h["program"] else f"step {h['step']}")
            owner = next((b.get("owner", "?") for b in baseline
                          if _bkey(b.get("step"), b.get("program"),
                                   b.get("paths") or [])
                          == _bkey(h["step"], h["program"], h["paths"])), "?")
            print(f"  - {who}: {h['paths']}  [owner: {owner}]")

    if stale:
        print(f"FAIL: {len(stale)} stale baseline entry(ies) — these are no "
              f"longer self-disabling, so delete them from "
              f"{bpath.name if bpath else 'the baseline'}:")
        for b in stale:
            print(f"  - step {b.get('step')} "
                  f"predicate {b.get('program')}: {b.get('paths')}")

    if holes:
        print(f"FAIL: {len(holes)} NEW self-disabling condition(s) in "
              f"{flow.name} — each is a check disabled by exactly the "
              f"situation it was written for:")
        for h in holes:
            who = (f"step {h['step']} predicate {h['program']}"
                   if h["program"] else f"step {h['step']}")
            print(f"  - {who}: condition {h['paths']}")
            print(f"      {h['detail']}")
        print("  Fix shape (#210/#219): run the step, name the missing input, "
              "report BLOCKED — never silently skip. Either add the step's "
              "`*_not_run.json` disclosure record to the trigger list with "
              "`any_of: true`, or make the checker unconditional so it fails "
              "on the absent artefact itself.")

    if undeclared:
        print(f"FAIL: {len(undeclared)} optional_program_exit_zero clause(s) in "
              f"{flow.name} do not declare `absent_condition_reason` — when "
              f"their condition matches nothing the program does not run, the "
              f"clause concludes NOTHING, and without a declaration the record "
              f"cannot tell that apart from a gate that ran and found nothing:")
        for u in undeclared:
            print(f"  - step {u['step']} {u['surface']} {u['program']}: "
                  f"condition {u['paths']} "
                  f"({u['declared_chars']} declared char(s), "
                  f"{MIN_ABSENT_CONDITION_REASON} required)")
        print("  Fix shape: add `absent_condition_reason: >-` to the clause, "
              "saying why an absent input is a genuine not-applicable HERE and "
              "what still catches the absence if it is not. Nothing to check "
              "is a FAIL, not a pass.")

    if holes or stale or undeclared:
        return 1
    print(f"PASS: all {len(records)} flow conditions are reachable when their "
          f"own subject is missing, or are listed as known-open "
          f"({len(known)}); all "
          f"{sum(1 for r in records if r['surface'] in ('predicate', 'advisory'))}"
          f" conditioned gate clause(s) declare why an absent input is "
          f"not-applicable ({flow.name}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
