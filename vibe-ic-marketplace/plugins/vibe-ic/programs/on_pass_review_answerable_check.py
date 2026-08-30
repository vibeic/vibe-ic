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
P2  THE NAMED REPORT IS PRODUCED BY THE FLOW.  A command that names
                 `--compliance <path>` is unanswerable one indirection out if
                 nothing in the flow writes `<path>`. The flow's `final_gate`
                 declares the run's compliance report, so `<path>` must be the
                 path `final_gate` writes with `--json`.
P3  A DISABLED CLAUSE DECLARES NO GATE.  `enabled: false` and a dispatchable
                 `gate:` contradict each other: the clause would be invoked
                 while declaring that it is not wired. `stage5_manufacturing`
                 is correct today and P3 keeps it so.

NOT CHECKED HERE, ON PURPOSE
============================
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


def declared_reviews(flow: dict) -> list:
    """Every stage carrying an `on_pass_review:`, enabled or not."""
    out = []
    for stage in flow.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        review = stage.get("on_pass_review")
        if not isinstance(review, dict):
            continue
        gate = review.get("gate")
        command = None
        if isinstance(gate, dict):
            command = gate.get("program_exit_zero")
        out.append({
            "stage": str(stage.get("id") or stage.get("name") or "?"),
            # ABSENT `enabled:` MEANS ENABLED. Five of the six declare no
            # `enabled` key at all and are live; only stage5 opts out
            # explicitly. Defaulting the other way would exempt every clause
            # that never thought about it, which is all of them.
            "enabled": review.get("enabled", True) is not False,
            "command": command,
            "argv": _argv(command) if command else [],
        })
    return out


def final_gate_report(flow: dict):
    """The compliance report path the flow's `final_gate` writes, if any."""
    fg = flow.get("final_gate")
    if not isinstance(fg, dict):
        return None
    return _flag_value(_argv(str(fg.get("args") or "")), "--json")


def analyse(flow_path: Path):
    text = flow_path.read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    if not isinstance(flow, dict):
        raise ValueError(f"{flow_path} is not a mapping")

    reviews = declared_reviews(flow)
    produced = final_gate_report(flow)
    findings = []

    for r in reviews:
        if not r["enabled"]:
            # P3 - a clause that declares itself not wired must not carry a
            # dispatchable gate.
            if r["command"]:
                findings.append(
                    f"P3 DISABLED CLAUSE CARRIES A GATE [{r['stage']}]: the "
                    f"clause declares `enabled: false` and also declares "
                    f"`gate.program_exit_zero`. A dispatcher reaching that "
                    f"gate would run a review the clause says is not wired. "
                    f"Drop the gate, or drop `enabled: false`.")
            continue
        if not r["command"]:
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

        # P2 - and is the report it names actually written by this flow?
        named = _flag_value(r["argv"], "--compliance")
        if named is None:
            continue
        if produced is None:
            findings.append(
                f"P2 NAMES A REPORT THE FLOW NEVER WRITES [{r['stage']}]: the "
                f"gate reads `--compliance {named}`, and the flow's "
                f"`final_gate` runs `flow_compliance_check` with no `--json`, "
                f"so no compliance report is produced anywhere in the flow. "
                f"The gate is unanswerable one indirection out: rc=2 for a "
                f"missing file instead of rc=2 for a missing flag.")
        elif named != produced:
            findings.append(
                f"P2 READS A DIFFERENT REPORT THAN THE FLOW WRITES "
                f"[{r['stage']}]: the gate reads `--compliance {named}` while "
                f"`final_gate` writes `--json {produced}`. One of the two is a "
                f"typo, and the gate is the half that goes quiet.")

    enabled = [r for r in reviews if r["enabled"] and r["command"]]
    return findings, {
        "flow": str(flow_path),
        "declared_reviews": len(reviews),
        "enabled_with_gate": len(enabled),
        "final_gate_report": produced,
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
              f"establish a verdict and read the report `final_gate` writes "
              f"({report['final_gate_report']}).")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
