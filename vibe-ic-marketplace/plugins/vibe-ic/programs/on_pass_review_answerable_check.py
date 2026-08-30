#!/usr/bin/env python3
"""on_pass_review_answerable_check — an on-pass gate that can only ever say rc=2.

WHY THIS EXISTS
===============
MEASURED on main at v1.13.40. The on-pass review axis ships SIX enabled stages
(`stage_phase1`, `stage1`, `stage2`, `stage_analog`, `stage3`, `stage4`) and
NINE rules, every one of them declared with a `gate.program_exit_zero` that
invokes `stage_on_pass_review`. NOT ONE OF THE SIX CAN REJECT ANYTHING, and the
reason is in the declared command rather than in the engine.

`stage_on_pass_review` establishes the stage's verdict through `stage_passed()`,
which reads `--stage-verdict` if given, else the `--compliance` report, else
returns `passed=None` -- UNESTABLISHED. On `passed is None` the program prints
"no --compliance report and no --stage-verdict: the stage's verdict is
unestablished" and returns 2. All six declared commands carry NEITHER flag:

    stage_on_pass_review . --stage stage3 --json reports/phase3/gates/stage3_on_pass_review.json

so the branch that returns 2 is taken before any rule is consulted, on every
input, forever. MEASURED against the repo's own known-BAD fixture
`programs/tests/fixtures/stage3_on_pass_review/reject_sgmii`, which is a real
contradiction (the intent asks 1.6 ns, the sign-off deck constrains 20.0 ns, a
factor of 12.5):

    the DECLARED command, verbatim          rc=2   NOT CHECKED
    the same fixture + --stage-verdict PASS rc=1   REJECT, R3 proven

Same fixture, same engine, same rule. The only difference is whether the
invocation can put the question at all.

rc=2 IS NOT A PASS, AND THAT IS EXACTLY WHY THIS HID
====================================================
`rc=2` means THE QUESTION COULD NOT BE PUT. It is the honest answer for a run
that has no compliance report yet, and it is also what a permanently
unanswerable command returns -- and those two are not the same fact. One is a
run that will answer tomorrow; the other is a clause that will never answer.
Conflating them is what let six gates sit silent since the engine landed at
v1.13.16 without anyone reading a false PASS: nothing ever claimed to have
reviewed anything. A gate that only ever declines to answer looks exactly like
a gate that has not been reached yet.

THE SECOND INSTANCE OF A SHAPE THIS REPO HAS ALREADY PAID FOR
=============================================================
v1.13.32 found five clauses DECLARED WHERE THE ENGINE NEVER LOOKED. This is the
same shape one indirection out: declared where the engine DOES look, in a form
the engine can never answer. `flow_gate_enforcement_audit` already discloses the
neighbouring half of it --

    DISCLOSURE - 1 gate(s) are declared in the flow document but sit OUTSIDE
    `steps:`, which is the only section `flow_compliance_check` reads
    (`steps = flow.get("steps", [])`). Nothing dispatches them.
        stage_on_pass_review  6 clause(s) under stages:

-- and correctly does not FAIL on it, because WHERE a stage-level clause should
be dispatched from is a flow owner's call and a step's `gate:` cannot express
`fires_on: stage_pass`. This program does not answer that question either. It
answers the one that has an answer regardless of who dispatches it: WHOEVER
runs this command, can it produce a verdict? Today, for all six, it cannot.

WHAT THIS CHECKS
================
P1  ANSWERABLE.  Every ENABLED `on_pass_review:` whose gate invokes
                 `stage_on_pass_review` passes a VERDICT SOURCE -- `--compliance`
                 or `--stage-verdict`. A command with neither returns 2 on every
                 input and is a comment wearing a gate's name.
P2  THE NAMED REPORT HAS AN EXECUTED PRODUCER, AND IT RUNS FIRST.
                 A command naming `--compliance <path>` is unanswerable one
                 indirection out if nothing WRITES `<path>` before it reads it.
                 The producer must be an EARLIER clause in the SAME `all_of`,
                 naming that path with `--json`.

                 THIS CHECK USED TO ASK A DIFFERENT QUESTION AND THE DIFFERENCE
                 COST THE WHOLE AXIS. It compared the gate's `--compliance`
                 string to the string in the flow's `final_gate:` block: a
                 declaration validated against a declaration, in the same file
                 -- the v1.13.32 shape this program exists to refuse, sitting
                 inside the program written to refuse it. MEASURED at v1.13.70:
                 NOTHING EXECUTES `final_gate`. It is read by this program and
                 by `tools/d9_corpus_baseline.py` (which censuses its program
                 name) and by nothing else. `flow_compliance_check`'s `--json`
                 has no default and both drivers omit it --
                 `design_one_shot_runner._build_final_audit_cmd` builds
                 `[project, --phase N, --strict-structural, --allow-thin-input]`
                 and `phase3_one_shot_runner` builds `[project, --strict]`. So
                 `reports/flow_compliance.json` was written on no run, all six
                 gates returned rc=2 NOT CHECKED ("[Errno 2] No such file or
                 directory") forever, and this check said PASS about it.
                 SECOND AND INDEPENDENT: even when a caller DOES pass `--json`,
                 that report is written AFTER `flow_compliance_check`'s step
                 loop, and these clauses are evaluated INSIDE it. Ordering is
                 therefore part of the question, and "an earlier clause in the
                 same `all_of`" is the only shape that answers it.
P3  A DISABLED CLAUSE DECLARES NO GATE.  `enabled: false` and a dispatchable
                 `gate:` contradict each other: the clause would be invoked
                 while declaring that it is not wired. `stage5_manufacturing`
                 is correct today and P3 keeps it so.

NOT CHECKED HERE, ON PURPOSE
============================
Whether the host step is REACHABLE. That is
`on_pass_review_declared_command_runs_check`'s P8/P9: it already resolves the
host step in order to execute the argv, so it is the one that can see a
`condition:` the engine will never satisfy. Answerability and reachability are
orthogonal -- a clause nobody reaches is still broken if it could not answer
when reached, and a clause that can answer is still silent if nothing reaches
it. Two programs, two questions, no shared premise for them to disagree about.

Whether anything DISPATCHES these clauses. That is
`flow_gate_enforcement_audit`'s disclosure and a flow owner's decision; this
program would report the same finding twice and the two could then disagree.
Answerability is orthogonal: a clause nobody dispatches is still broken if it
could not answer when dispatched, and fixing it is a precondition for wiring it
rather than a substitute.

NOT A DEFECT, AND SAYING SO HERE SO NOBODY REPAIRS IT
=====================================================
`stage_on_pass_review._STA_EDGE_RE` parses OpenSTA's real report shape, which
puts THE NUMBERS FIRST and the clock name and edge after them:

    20.00   20.00   clock clk (rise edge)

The `reject_sgmii` fixture's `phase3/stage3/sta/post_route_timing.rpt` is picked
up correctly by that regex and lands in the rejection's `signed_off_under`
blast radius. A hand-written .rpt that puts the numbers AFTER the clock name is
not matched -- that is the synthetic file being in the wrong column order, not
the regex being narrow. A reader who meets only the failing parse will conclude
the gate is broken and go repair something that works.
"""
import argparse
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_json  # noqa: E402  vibe-ic#1082 (helper from PR #1094)

try:
    import yaml
except ImportError:  # pragma: no cover - the tree ships pyyaml
    yaml = None

PLUGIN = Path(__file__).resolve().parent.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

#: The program whose invocation this check reads. A stage-level gate naming any
#: other program is not this check's subject: its verdict contract is its own.
SUBJECT = "stage_on_pass_review"

#: Either flag establishes the stage verdict in `stage_on_pass_review.
#: stage_passed()`. Neither present means `passed=None` -> rc 2, always.
VERDICT_FLAGS = ("--compliance", "--stage-verdict")


def _argv(command: str) -> list:
    """The declared command as tokens, tolerant of an unsplittable string."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _flag_value(argv: list, flag: str):
    """The value of `flag` in `argv`, supporting `--f v` and `--f=v`."""
    for i, tok in enumerate(argv):
        if tok == flag:
            return argv[i + 1] if i + 1 < len(argv) else None
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


#: The one top-level section `flow_compliance_check.main` dispatches from
#: (`steps = flow.get("steps", [])`). A clause anywhere else is declared and
#: dispatched by nothing -- v1.13.32's finding, and the reason this checker
#: resolves the command from HERE rather than from the stage block.
DISPATCHED_SECTION = "steps"

#: Every gate slot the engine evaluates. The command is looked for in all
#: three: a review wired through the wrong slot is a different defect, and
#: this checker must be able to SEE it rather than report the clause missing.
GATE_SLOTS = ("program_exit_zero", "optional_program_exit_zero",
              "advisory_program_exit_zero")


def _commands_in(node) -> list:
    """Every gate command string anywhere under `node`, in document order.

    Used to build the "what already ran" list for P2. It reads ALL the slots,
    not just the ones that can fail: an `advisory_` producer still writes its
    `--json`, and a producer whose findings must not block the step is exactly
    the shape a verdict source wants.
    """
    found = []
    if isinstance(node, dict):
        for key, val in node.items():
            if key in GATE_SLOTS:
                cmd = val.get("command") if isinstance(val, dict) else val
                if isinstance(cmd, str):
                    found.append(cmd)
            found.extend(_commands_in(val))
    elif isinstance(node, list):
        for item in node:
            found.extend(_commands_in(item))
    return found


def step_clauses(flow: dict) -> list:
    """Every clause under `steps:` that invokes the subject, tagged by stage.

    Structural walk of the shapes `flow_compliance_check._evaluate_gate`
    executes -- not a text scan, so a program name inside a comment or a path
    argument is not read as a clause.
    """
    out = []

    def walk(node, step, earlier=()):
        if isinstance(node, dict):
            for key, val in node.items():
                if key in GATE_SLOTS:
                    cmd = val.get("command") if isinstance(val, dict) else val
                    if isinstance(cmd, str):
                        argv = _argv(cmd)
                        if argv and SUBJECT in argv[0]:
                            out.append({"slot": key, "command": cmd,
                                        "argv": argv,
                                        "step": str((step or {}).get("id")),
                                        "stage": _flag_value(argv, "--stage"),
                                        # The commands the engine runs BEFORE
                                        # this one, in order, so P2 can ask WHO
                                        # WROTE the report this clause reads.
                                        "earlier": list(earlier)})
                walk(val, step, earlier)
        elif isinstance(node, list):
            # `all_of` IS AN ORDERED SHAPE. `flow_compliance_check.
            # _evaluate_gate` walks it in sequence, so a clause can legitimately
            # read a file an EARLIER sibling wrote — and cannot read one a later
            # sibling writes. P2 is that distinction, so the order has to be
            # carried here rather than reconstructed from a set later.
            seen = []
            for item in node:
                walk(item, step, tuple(earlier) + tuple(seen))
                seen.extend(_commands_in(item))

    for step in flow.get(DISPATCHED_SECTION) or []:
        if isinstance(step, dict):
            walk(step.get("gate"), step)
    return out


def declared_reviews(flow: dict) -> list:
    """Every stage carrying an `on_pass_review:`, enabled or not.

    THE COMMAND IS READ FROM `steps:`, NOT FROM THE STAGE BLOCK, and that is
    the whole of this function's history. Until the six clauses were wired,
    the command lived in `stages[].on_pass_review.gate` -- a section the flow
    engine never reads -- and this checker read it from there, so it was
    grading an argv nothing would ever run. It now asks its question about the
    argv the engine will actually dispatch, which is the only one whose
    answerability is a fact about this flow.
    """
    clauses = step_clauses(flow)
    out = []
    for stage in flow.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        review = stage.get("on_pass_review")
        if not isinstance(review, dict):
            continue
        sid = str(stage.get("id") or stage.get("name") or "?")
        mine = [c for c in clauses if c["stage"] == sid]
        command = mine[0]["command"] if mine else None
        out.append({
            "stage": sid,
            # ABSENT `enabled:` MEANS ENABLED. Five of the six declare no
            # `enabled` key at all and are live; only stage5 opts out
            # explicitly. Defaulting the other way would exempt every clause
            # that never thought about it, which is all of them.
            "enabled": review.get("enabled", True) is not False,
            "command": command,
            "slot": mine[0]["slot"] if mine else None,
            "step": mine[0]["step"] if mine else None,
            "earlier": mine[0]["earlier"] if mine else [],
            "argv": _argv(command) if command else [],
        })
    return out


def producer_of(path: str, earlier: list):
    """The earlier clause that writes `path` with `--json`, or None.

    THE PRODUCER MUST BE A COMMAND THE ENGINE EXECUTES, AND IT MUST RUN FIRST.
    `earlier` is the ordered list of commands `_evaluate_gate` runs before the
    review inside the same `all_of`, so "found here" means both halves at once:
    something writes the file, and it has already written it by the time the
    review opens it. A producer declared anywhere else -- a later sibling, a
    different step, or the flow's `final_gate:` block, which nothing executes --
    cannot satisfy either half.
    """
    for cmd in earlier or []:
        if _flag_value(_argv(str(cmd)), "--json") == path:
            return str(cmd)
    return None


def analyse(flow_path: Path):
    text = flow_path.read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    if not isinstance(flow, dict):
        raise ValueError(f"{flow_path} is not a mapping")

    reviews = declared_reviews(flow)
    findings = []

    for r in reviews:
        if not r["enabled"]:
            # P3 - a clause that declares itself not wired must not carry a
            # dispatchable gate.
            if r["command"]:
                findings.append(
                    f"P3 DISABLED CLAUSE IS DISPATCHED [{r['stage']}]: the "
                    f"clause declares `enabled: false` and step {r['step']!r} "
                    f"nevertheless dispatches `{r['slot']}: {r['command']}`. "
                    f"The engine reaching that clause would run a review the "
                    f"block says is not wired. Drop the step clause, or drop "
                    f"`enabled: false`.")
            continue
        if not r["command"]:
            # A DECLARED REVIEW THIS CHECKER CANNOT FIND IS NOT A SILENT SKIP.
            # It used to be: `continue`, from when the command lived in the
            # stage block and "no command" meant "this stage declared none".
            # The command now lives in `steps:`, so not finding one means the
            # review is DISPATCHED BY NOTHING -- the v1.13.32 defect -- and
            # this checker has no argv to grade. MEASURED while landing the
            # wiring: retargeting ONE clause's `--stage` left this program
            # printing `[PASS] ... 5 enabled on-pass gate(s)` and exiting 0.
            # A population that quietly shrank by one read exactly like a
            # clean result. This is not `flow_gate_enforcement_audit`'s
            # disclosure restated: that one reports where a clause SITS, this
            # one reports that its own subject is missing.
            findings.append(
                f"P0 DECLARED BUT NOT DISPATCHED [{r['stage']}]: the stage "
                f"declares an enabled `on_pass_review:` and no clause under "
                f"`{DISPATCHED_SECTION}:` invokes {SUBJECT} with `--stage "
                f"{r['stage']}`. `flow_compliance_check` reads `steps = "
                f"flow.get(\"{DISPATCHED_SECTION}\", [])` and nothing else, so "
                f"this review is dispatched by nothing and this check has no "
                f"command to grade.")
            continue
        if not r["argv"] or SUBJECT not in r["argv"][0]:
            continue

        # P1 - can this invocation put the question at all?
        if not any(_flag_value(r["argv"], f) is not None for f in VERDICT_FLAGS):
            findings.append(
                f"P1 CANNOT REJECT [{r['stage']}]: the declared gate invokes "
                f"{SUBJECT} with neither `--compliance` nor `--stage-verdict`, "
                f"so `stage_passed()` returns UNESTABLISHED and the program "
                f"returns rc=2 NOT CHECKED before any rule is consulted -- on "
                f"every input, forever. It can neither accept nor reject. "
                f"Command: {r['command']}")
            continue

        # P2 - and does anything the ENGINE RUNS write that report FIRST?
        named = _flag_value(r["argv"], "--compliance")
        if named is None:
            continue
        wrote = producer_of(named, r.get("earlier"))
        if wrote is None:
            findings.append(
                f"P2 NAMES A REPORT WITH NO EXECUTED PRODUCER [{r['stage']}]: "
                f"the gate reads `--compliance {named}` and NO clause the "
                f"engine runs before it -- none of the "
                f"{len(r.get('earlier') or [])} earlier command(s) in step "
                f"{r['step']!r}'s `all_of` -- writes that path with `--json`. "
                f"`stage_passed()` then gets an unreadable file, returns "
                f"UNESTABLISHED, and the program exits 2 NOT CHECKED before "
                f"consulting a rule: rc=2 for a missing file instead of rc=2 "
                f"for a missing flag, which is the same silence one "
                f"indirection out. A path named in the flow's `final_gate:` "
                f"block does NOT count: nothing executes `final_gate`, and a "
                f"report written after the step loop is written after this "
                f"clause has already read it.")

    enabled = [r for r in reviews if r["enabled"] and r["command"]]
    # NOTHING TO CHECK IS A FAIL, AND THIS BRANCH IS HERE BECAUSE IT ALREADY
    # HAPPENED. Moving the six clauses out of `stages[].on_pass_review.gate`
    # and into `steps:` -- the change that made them dispatchable at all --
    # left this checker reading a key that no longer exists, and it printed
    # `[PASS] ... 0 enabled on-pass gate(s) can establish a verdict` and
    # exited 0. A checker whose subject vanished must not report a clean
    # result about it; that substitution is the exact defect this whole axis
    # exists to refuse, and it is one line to prevent.
    if reviews and not enabled and any(r["enabled"] for r in reviews):
        findings.append(
            f"P0 NO DECLARED REVIEW IS DISPATCHED: {sum(1 for r in reviews if r['enabled'])} "
            f"stage(s) declare an enabled `on_pass_review:` and NOT ONE of "
            f"them is invoked by a clause under `{DISPATCHED_SECTION}:`, the "
            f"only section `flow_compliance_check` reads. This check examined "
            f"0 commands, which refutes nothing and certifies nothing.")
    return findings, {
        "flow": str(flow_path),
        "declared_reviews": len(reviews),
        "enabled_with_gate": len(enabled),
        "verdict_sources": {r["stage"]: producer_of(
            _flag_value(r["argv"], "--compliance") or "", r.get("earlier"))
            for r in enabled},
        "stages": [r["stage"] for r in enabled],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow", default=str(FLOW),
                    help="flow definition to check (default: this tree's own)")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    if yaml is None:
        print("[SKIP] on_pass_review_answerable_check: pyyaml unavailable")
        return 2
    try:
        findings, report = analyse(Path(a.flow).resolve())
    except Exception as exc:  # unreadable input is rc 2, never a silent PASS
        print(f"[SKIP] on_pass_review_answerable_check: cannot read input: "
              f"{exc}")
        return 2
    report["findings"] = findings
    report["verdict"] = "FAIL" if findings else "PASS"
    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        # vibe-ic#1082 -- ATOMIC, because this record IS the verdict. It carries
        # `verdict` and the findings a caller acts on, so a `write_text` that
        # dies mid-write leaves a half-parsed judgement at the DECLARED
        # destination, and the next reader takes that truncation for this
        # gate's evidence rather than for a write that never finished.
        #
        # `ensure_ascii=True` and `sort_keys=False` are `json.dumps`'s own
        # defaults, which is what the call this replaces used, so the BYTES do
        # not move; the trailing newline comes from `write_json` itself.
        write_json(out, report, indent=2, ensure_ascii=True, sort_keys=False)
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings:
        print(f"[PASS] on_pass_review_answerable_check: "
              f"{report['enabled_with_gate']} enabled on-pass gate(s) can "
              f"establish a verdict, and each reads a report an EARLIER clause "
              f"in its own step's `all_of` writes with `--json`.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
