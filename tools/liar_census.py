#!/usr/bin/env python3
"""liar_census.py — ask EVERY gate clause, mechanically, whether it is a check that lies.

WHY THIS EXISTS
===============
The 63x9 campaign has been finding "checks that lie" one at a time, by collision.
On 2026-08-12 alone, six turned up without anyone systematically looking:

  * two BLOCKING clauses printed "NOT screened" / "NOT compared against anything"
    and returned 0, so an empty directory passed them          (vibe-ic#1017)
  * a gate reported PASS over a zero denominator                (vibe-ic#1002)
  * a `--corpus` sweep reached NOTHING unless the caller typed
    the right path depth, and refused honestly about it         (vibe-ic#1025)
  * a "real data" selector fell back to the SUITE'S OWN FIXTURE  (vibe-ic#1037)
  * a test passed only because an earlier test repaired the tree (vibe-ic#1029)
  * a cadence gate certified "tests ran" by counting that a
    COMMAND STRING was supplied, executing nothing              (vibe-ic#1019)

Every one of those has a mechanical signature. The repo already owns detectors for
several of them. What it has never owned is ONE INSTRUMENT THAT ASKS ALL OF THEM OF
ALL OF THEM -- so a gate can be clean on the one axis somebody happened to check and
lying on the other eleven.

    The defect is not that we lack detectors. It is that no gate has ever had a
    SCORECARD.

This file is that scorecard.

WHAT IT IS NOT
==============
It does not decide whether a gate's RULE is correct -- that needs an expert and it is
what the 63x9 review is for. It decides whether the gate is CAPABLE OF LYING in ways
that can be established without one: passing on nothing, being unable to fail, saying
one thing and exiting another. A gate that survives this census can still be wrong.
A gate that fails it cannot be trusted even when it is right.

THE PROBES, AND WHAT EACH COSTS
===============================
    empty       P1  does it PASS over a tree containing nothing?          static-ish
    prose       P2  does it SAY it did not check, and exit 0 anyway?      one run
    zero        P3  does it report a ZERO population and still pass?      one run
    writes      P4  does RUNNING it modify the tree it is judging?        one run
    selector    P5  can its input selection reach the suite's fixtures?   AST only
    forcedpass  P6  neuter its verdict -- does any test die?              MUTATION
    forcedfail  P7  force it to refuse -- does any test die?              MUTATION

P6 and P7 are the only ones that cannot be answered by looking, and they are the
only ones that cost minutes rather than seconds: three pytest sessions per
distinct gate program, over a disposable copy of the plugin. `--probes` names a
cheaper subset; `--mutation-budget` bounds them and PRINTS what it dropped.

EXIT CODES
    0  every clause CLEAN on every probe that ran
    1  at least one LIAR
    2  refused -- the population could not be established (never a pass)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
PROGRAMS = PLUGIN / "programs"
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

CLEAN, SUSPECT, LIAR, NA = "CLEAN", "SUSPECT", "LIAR", "N/A"
#: A finding the census DECLINES to score, having established structurally that
#: the question it asked cannot be load-bearing here. Printed, never hidden: a
#: discount nobody can audit is the next check that lies.
GUARDED = "GUARDED"

#: Words a gate uses when it is telling you it did NOT do the thing. If any of these
#: leads a line of stdout and the gate still exits 0, the exit code contradicts the
#: prose -- the #1017 shape, and the one that let an empty directory pass two BLOCKING
#: clauses. Anchored at line start on purpose: gates narrate these words in docstrings
#: and explanatory paragraphs all the time, and only a line that LEADS with one is the
#: gate's own verdict line.
#:
#: THE `_SUFFIX` CLAUSE IS LOAD-BEARING, and it was missing (found while adjudicating
#: `l_doc_todo_stub_count_check` for #1051's follow-up). `\b` does not match between
#: `VACUOUS` and `_`, because `_` is a word character -- so the pattern was blind to
#: `VACUOUS_PASS`, which is THIS REPO'S OWN canonical disclosed-skip verdict token and
#: appears 139 times in `programs/`. It was equally blind to `SKIP_NO_ANALOG_DIR`,
#: `SKIPPED_CONDITION`, `SKIP_MISSING_ORACLE` and every other SCREAMING_SNAKE variant
#: the gates actually print. A refusal detector that cannot see the repo's standard
#: refusal token is the census's own version of the defect it hunts.
_REFUSAL_LEAD = re.compile(
    r"^\s*(?:INCOMPLETE|NOT[ _-]?CHECKED|NOT[ _-]?SCREENED|SKIPPED|SKIP|CANNOT|"
    r"COULD NOT|UNABLE|NO DATA|NOTHING TO|INSUFFICIENT|UNDECIDED|UNMEASURED|"
    r"VACUOUS)(?:_[A-Z0-9_]+)?\b",
    re.I | re.M,
)

#: A population word next to a zero. `gate_zero_denominator_refuses_check` owns the
#: full rule; this is the cheap textual smell so the census can flag it per-clause.
#:
#: THE TRAILING `\b` IS ALSO LOAD-BEARING, and was `\w*`, which could not tell a
#: DENOMINATOR from a NUMERATOR. `0 docs_with_todo` matched -- `doc` plus `\w*`
#: swallowing `s_with_todo` -- and on a real clean project `docs_with_todo=0` is the
#: CORRECT answer, so the census was reporting a violation count as if it were an
#: empty population. With `s?\b` the compound findings word no longer matches (`docs`
#: is followed by `_`, not a boundary) while #1002's real evidence still does:
#: `0 librar(ies) across 0 log(s)`, and #1017's `0 segment`.
#:
#: `violation` was dropped from the word list for the same reason: it counts what the
#: gate FOUND, never what it looked at, so `504 cells screened, 0 violations` is a
#: clean result and reading it as an empty population is backwards.
_ZERO_POP = re.compile(
    r"\b0\s+(?:run|cell|file|report|net|pin|gate|check|document|doc|entry|entries|"
    r"segment|sample|corner|step|instance|point|library|librar)s?\b", re.I
)


def _consumer_reads_the_refusal(out: str) -> bool:
    """Does `flow_compliance_check` READ this refusal, or does it reach nobody?

    Imported from the consumer, never reimplemented. A census that carried its own
    copy of this predicate would keep scoring by a rule the flow had moved on from —
    and it would do so silently, which is the whole family of defect being hunted.

    Degrades LOUDLY: if the consumer cannot be imported the census says so on stderr
    and treats nothing as disclosed, so the failure shows up as noisy LIARs rather
    than as a quiet amnesty.
    """
    if not out:
        return False
    try:
        # the REAL plugin, never `PROGRAMS` — that one is redirected at a planted
        # tree under test, and importing a planted `flow_compliance_check` would
        # let a fixture decide what counts as disclosure.
        sys.path.insert(0, str(PLUGIN / "programs"))
        from flow_compliance_check import (  # noqa: PLC0415
            _stdout_signals_vacuous, _VACUOUS_HINT_PREFIX,
        )
    except Exception as exc:                                   # pragma: no cover
        print(f"liar_census: CANNOT IMPORT the vacuity consumer ({exc}) — scoring "
              f"every refusal as unread; this run OVERSTATES the LIAR count",
              file=sys.stderr)
        return False
    return bool(_stdout_signals_vacuous(out) or out.startswith(_VACUOUS_HINT_PREFIX))


@dataclass
class Clause:
    step: str
    kind: str          # program_exit_zero | advisory_program_exit_zero
    cmd: str
    program: str
    #: Existence guards the flow declares ABOVE this clause, which an empty tree
    #: cannot satisfy. See `discover_clauses` — this is the census's own
    #: false-positive control, derived from YAML structure, never a name list.
    guards: List[str] = field(default_factory=list)
    #: the enclosing step's `required_outputs`: what the flow SAYS this step writes
    step_outputs: List[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return self.kind == "program_exit_zero"

    @property
    def guarded_on_empty(self) -> bool:
        return bool(self.guards)


def _declared_outputs(cl: "Clause") -> List[str]:
    """Paths the FLOW says this clause's step is supposed to write.

    A gate writing an artefact its own step declares is doing its job, not
    contaminating its subject. Read from the step node, never from a name list.
    """
    return list(cl.step_outputs)


@dataclass
class ProbeResult:
    probe: str
    verdict: str
    detail: str = ""
    repro: str = ""


@dataclass
class ClauseReport:
    step: str
    kind: str
    cmd: str
    program: str
    probes: List[ProbeResult] = field(default_factory=list)

    @property
    def worst(self) -> str:
        for want in (LIAR, SUSPECT, GUARDED, CLEAN):
            if any(p.verdict == want for p in self.probes):
                return want
        return NA


# --------------------------------------------------------------- discovery
def _files_exist_of(node: Any) -> List[str]:
    """The `files_exist` patterns a node declares, or []. No text matching."""
    if isinstance(node, dict) and isinstance(node.get("files_exist"), list):
        return [str(p) for p in node["files_exist"]]
    return []


def discover_clauses(flow_yaml: Path) -> List[Clause]:
    """Every gate clause the flow declares, with the step that declares it.

    Parsed from the YAML STRUCTURE, never from the text. vibe-ic#1012 is the whole
    reason: a substring test over the raw text counted a program named in a COMMENT
    as wired, so documenting a hold made the held checker unmeasurable.

    EXISTENCE GUARDS — the census's control on its own empty-tree probe
    ------------------------------------------------------------------
    `probe_empty_tree` asks "does rc 0 here certify a project that does not
    exist?". For some clauses that question is not the flow's question, and
    answering it anyway produces a false LIAR. Three structures make it so, and
    ALL THREE are read out of the YAML — never out of a list of gate names,
    which would rot silently and be a check that lies in its own right:

      * the STEP declares `condition: {files_exist: [...]}`. On an empty tree
        the step does not run at all, so its gate's exit code is never read.
      * a SIBLING conjunct in the same `all_of` declares `files_exist: [...]`.
        The conjunction fails at the sibling on an empty tree, so this clause's
        rc 0 cannot wave anything through. Presence is asserted by the sibling;
        this clause was only ever asked about SUBSTANCE.
        (Checked: every gate list in this flow is `all_of`. `any_of` appears
        only as a key INSIDE a `files_exist` dict — "any one of these files" —
        never as a list-level operator, so a sibling can never be an
        alternative to the clause rather than a precondition of it.)
      * the STEP declares `required_outputs: [...]`. `flow_compliance_check`
        resolves those FIRST and ALL-of-N, and a step with no evidence for any
        of them is MISSING before its gate verdict is read at all
        (`flow_compliance_check.py`, "First check required_outputs presence").
        61 of the 62 gated steps declare some, so this rule alone subsumes most
        of what the empty-tree probe finds — which is itself the finding: the
        empty tree is a cheap REPRODUCTION of a lie, rarely the lie. Disclosed
        with its own caveat: under `--lenient` (opt-in, not the default)
        MISSING degrades to WARN, and this guard is correspondingly weaker.

    An empty tree satisfies NO `files_exist`, whatever it names, so the guard is
    decidable without evaluating the pattern.

    What GUARDED does NOT mean: that the gate is honest. It means this probe
    cannot establish otherwise. A guarded gate can still pass over a populated
    tree with no substance in it — the empty-tree probe simply cannot see that,
    and says so instead of scoring it.
    """
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(flow_yaml.read_text(errors="replace"))
    out: List[Clause] = []

    def walk(node: Any, step: Optional[str], guards: Tuple[str, ...],
             outputs: List[str]) -> None:
        if isinstance(node, dict):
            here = str(node["id"]) if "id" in node else step
            here_guards = guards
            cond = node.get("condition")
            for pat in _files_exist_of(cond):
                here_guards += (f"[condition] step {here} runs only if files_exist: {pat}",)
            here_outputs = outputs
            if isinstance(node.get("required_outputs"), list):
                here_outputs = outputs + [str(p) for p in node["required_outputs"]]
            if isinstance(node.get("required_outputs"), list) and "gate" in node:
                pats = [str(p) for p in node["required_outputs"]]
                here_guards += (f"[required_outputs] step {here} is MISSING before its "
                                f"gate is read unless one of {len(pats)} declared output(s) "
                                f"resolves, e.g. {pats[0]}",)
            for key, val in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero") and isinstance(val, str):
                    prog = val.split()[0] if val.split() else ""
                    out.append(Clause(step=here or "?", kind=key, cmd=val,
                                      program=prog, guards=list(here_guards),
                                      step_outputs=list(here_outputs)))
                elif key != "condition":
                    walk(val, here, here_guards, here_outputs)
        elif isinstance(node, list):
            # every element of a gate list is a conjunct: a `files_exist`
            # element is a precondition of every OTHER element beside it
            sibling: Tuple[str, ...] = ()
            for val in node:
                for pat in _files_exist_of(val):
                    sibling += (f"[sibling] a conjunct beside this one in the same "
                                f"all_of requires files_exist: {pat}",)
            for val in node:
                own = _files_exist_of(val)
                # a conjunct is not a precondition of itself
                keep = tuple(g for g in sibling
                             if not any(g.endswith(f": {p}") for p in own))
                walk(val, step, guards + keep, outputs)

    walk(doc, None, (), [])
    return out


# --------------------------------------------------------------- invocation
def _argv_for(cmd: str, project: Path) -> List[str]:
    """Turn a clause command string into an argv, exactly as the flow would run it.

    The clause is written relative to a project root (`prog . --json reports/x.json`),
    so `.` means the tree under test. We keep the clause VERBATIM -- rewriting it here
    would be measuring an invocation nobody actually runs, which is the error that made
    `--root` return a confident `[PASS] 504 cells` for a question nobody asked.
    """
    parts = cmd.split()
    prog = PROGRAMS / f"{parts[0]}.py"
    return [sys.executable, str(prog)] + parts[1:]


def _run(cmd: str, project: Path, timeout: int = 60) -> Tuple[int, str]:
    argv = _argv_for(cmd, project)
    try:
        proc = subprocess.run(
            argv, cwd=str(project), capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return 124, "<TIMEOUT>"
    except OSError as exc:
        return 127, f"<NOT RUNNABLE: {exc}>"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------- probes
def probe_empty_tree(cl: Clause, empty: Path) -> ProbeResult:
    """P1 -- does it PASS on a tree containing nothing?

    A blocking clause that exits 0 over an empty directory certifies a project that
    does not exist. rc 2 is the disclosed-skip tier and is the CORRECT answer here;
    rc 1 is also fine (it looked and objected).
    """
    rc, out = _run(cl.cmd, empty)
    repro = f"cd <empty dir> && python3 programs/{cl.program}.py {' '.join(cl.cmd.split()[1:])}"
    if rc == 127:
        return ProbeResult("empty_tree", NA, out.strip()[:160], repro)
    if rc == 124:
        return ProbeResult("empty_tree", SUSPECT, "timed out on an EMPTY tree", repro)
    if rc == 0:
        if cl.guarded_on_empty:
            return ProbeResult(
                "empty_tree", GUARDED,
                "exits 0 over an empty tree, but the flow never reads that: "
                + cl.guards[0] + " — this probe cannot establish a lie here "
                "(it says nothing about a POPULATED tree with no substance)",
                repro)
        sev = LIAR if cl.blocking else SUSPECT
        return ProbeResult("empty_tree", sev,
                           "exits 0 over an empty tree — it certifies a project that does not exist",
                           repro)
    return ProbeResult("empty_tree", CLEAN, f"rc={rc} (refused or objected)", repro)


def probe_prose_vs_exit(cl: Clause, empty: Path) -> ProbeResult:
    """P2 -- does it SAY it did not check, and exit 0 anyway?  (vibe-ic#1017)

    The exact shape that let two BLOCKING clauses pass an empty directory while their
    own last line read "electromigration was NOT screened" and "total power was NOT
    compared against anything". `program_exit_zero` reads the EXIT CODE, not the prose.

    NOT discounted by an existence guard, unlike `probe_empty_tree`. The empty tree is
    only the CHEAPEST way to reach this code path; the path itself is "the authority is
    missing, so return 0", and a populated tree reaches it too. #1017 measured exactly
    that: 92 published run directories, every one rc 0, none of them empty.

    WHAT MAKES A REFUSAL A LIE IS THE CONSUMER, NOT THE EXIT CODE
    ------------------------------------------------------------
    rc 0 beside a refusal is only laundering if NOTHING READS THE REFUSAL. This repo
    has a documented, rc-INDEPENDENT second channel: a gate may print a line beginning
    `VACUOUS_PASS:` and still exit 0, and `flow_compliance_check` promotes the step to
    the VACUOUS_PASS tier on the PASSING path when it sees it
    (`_check_program_exit_zero`: "A gate program may disclose the vacuous tier by
    PRINTING `VACUOUS_PASS:` while still exiting 0 — which is exactly what the shared
    analog helper `_analog_a_check_common.vacuous_pass()` does for every A-track gate").

    Scoring those LIAR was this probe's own version of the defect it hunts: reading a
    verdict off prose without asking what consumes it. Measured — 11 of 17 flagged
    clauses were using the channel correctly, including 8 BLOCKING ones.

    The predicate is IMPORTED from the consumer rather than reimplemented, so the
    census cannot drift from the thing that actually decides. #1017's gates are
    untouched by it: `INCOMPLETE:` is not the sentinel and reaches no consumer.
    """
    rc, out = _run(cl.cmd, empty)
    repro = f"cd <empty dir> && python3 programs/{cl.program}.py … ; echo rc=$?"
    if rc in (124, 127):
        return ProbeResult("prose_vs_exit", NA, "", repro)
    hit = _REFUSAL_LEAD.search(out or "")
    if rc == 0 and hit:
        line = next((l.strip() for l in out.splitlines() if _REFUSAL_LEAD.match(l)), "")
        if _consumer_reads_the_refusal(out):
            return ProbeResult(
                "prose_vs_exit", GUARDED,
                f"refuses and exits 0, but on the documented rc-independent channel "
                f"flow_compliance_check reads on the passing path, so the flow records "
                f"VACUOUS_PASS rather than PASS — {line[:100]!r}",
                repro)
        return ProbeResult("prose_vs_exit", LIAR,
                           f"stdout leads a line with a refusal word but rc=0, and the "
                           f"refusal is in free prose no consumer reads — {line[:110]!r}",
                           repro)
    return ProbeResult("prose_vs_exit", CLEAN, f"rc={rc}", repro)


def probe_zero_denominator(cl: Clause, empty: Path) -> ProbeResult:
    """P3 -- does it report a ZERO population and still pass?  (vibe-ic#1002)

    "0 librar(ies) across 0 log(s) — nothing to compare" printed one line under its own
    FAIL. A zero beside a population word is not a result at all.

    NOT discounted by an existence guard, for the same reason as `prose_vs_exit`: the
    finding is that the gate PRINTS its own empty denominator and passes anyway, which
    is a property of its verdict logic, not of the tree it was pointed at.
    """
    rc, out = _run(cl.cmd, empty)
    repro = f"cd <empty dir> && python3 programs/{cl.program}.py …"
    if rc in (124, 127):
        return ProbeResult("zero_denominator", NA, "", repro)
    hit = _ZERO_POP.search(out or "")
    if rc == 0 and hit:
        return ProbeResult("zero_denominator", LIAR,
                           f"passes while reporting a zero population — {hit.group(0)!r}", repro)
    return ProbeResult("zero_denominator", CLEAN, f"rc={rc}", repro)


def probe_writes_its_subject(cl: Clause, sandbox: Path,
                             same_step: Optional[set] = None) -> ProbeResult:
    """P4 -- does RUNNING it modify the tree it is judging?  (vibe-ic#1029)

    The instrument perturbing its subject. Measured on a sandbox seeded with a minimal
    tree: anything the gate creates or modifies that it was not explicitly told to write
    (via its own --json argument) is contamination.
    """
    declared = set(_declared_outputs(cl))
    parts = cl.cmd.split()
    for i, tok in enumerate(parts):
        if tok == "--json" and i + 1 < len(parts):
            declared.add(parts[i + 1])
    before = {p: p.stat().st_mtime_ns for p in sandbox.rglob("*") if p.is_file()}
    _run(cl.cmd, sandbox)
    after = {p: p.stat().st_mtime_ns for p in sandbox.rglob("*") if p.is_file()}
    touched = [p for p in after if p not in before or after[p] != before.get(p)]
    undeclared = [p for p in touched
                  if str(p.relative_to(sandbox)) not in declared]
    repro = f"seed a tree, run programs/{cl.program}.py in it, then `git status --porcelain`"
    if not undeclared:
        return ProbeResult("writes_its_subject", CLEAN, "wrote nothing it was not asked to", repro)

    rels = sorted(str(p.relative_to(sandbox)) for p in undeclared)
    # SEVERITY BY STRUCTURE, not by name. A gate emitting its OWN report is the
    # normal shape and says nothing. What #1029 is actually about is an auditor
    # PRODUCING THE ARTEFACT A LATER AUDITOR ACCEPTS AS EVIDENCE — so the
    # question is whether anything ELSE names the path it wrote.
    consumers: List[Tuple[str, str]] = []
    for rel in rels:
        for other in sorted(PROGRAMS.glob("*.py")):
            if other.stem == cl.program:
                continue           # naming your own output is not a chain
            try:
                if rel in other.read_text(errors="replace"):
                    consumers.append((rel, other.stem))
                    break
            except OSError:
                continue
    names = ", ".join(rels[:4])
    if consumers:
        rel, reader = consumers[0]
        # DECLARED PRODUCER, by structure. If the consumer is another clause in
        # the SAME step's gate, the two run in one conjunction on one invocation
        # and the flow declared them as a pair -- there is no later auditor and
        # no step boundary for the artefact to cross as evidence. The flow says
        # so itself at M1: "PRODUCER, advisory on purpose: producing is not a
        # verdict ... the BLOCKING verdict stays with mixed_signal_merge_check,
        # which reads what this writes."
        #
        # Deliberately CONSERVATIVE: it only ever forgives. A cross-step consumer
        # is NOT automatically a lie -- `step_internal_fail_bubble_up_check`
        # (step 36) reads earlier gates' reports by design, and reads their FAIL
        # CONTENT, so a writer fabricating a PASS would simply not trigger it.
        # Separating content-reading from existence-reading consumers is the rule
        # this does not yet have, and it is stated in the summary rather than
        # guessed at here.
        if same_step and reader in same_step:
            return ProbeResult(
                "writes_its_subject", GUARDED,
                f"writes {rel}, read by {reader} — but {reader} is another clause in "
                f"step {cl.step}'s OWN gate, so the flow declares them as one "
                f"producer/checker pair in a single conjunction, not an artefact "
                f"handed across a step boundary as evidence",
                repro)
        return ProbeResult(
            "writes_its_subject", LIAR,
            f"wrote {len(undeclared)} undeclared path(s) into the tree it judges "
            f"({names}) and {rel} is READ BY {reader} — the auditor produces the "
            f"artefact a later auditor accepts as evidence",
            repro)
    return ProbeResult(
        "writes_its_subject", SUSPECT,
        f"wrote {len(undeclared)} undeclared path(s) into the tree it judges ({names}); "
        f"no other program names them, so it is an undisclosed self-report rather "
        f"than a self-certified evidence chain",
        repro)


def _repo_anchored_names(tree: "ast.Module") -> set:
    """Module-level names whose value derives from `__file__`.

    These are the only roots that point AT THE CHECKOUT rather than at the
    project under test, so they are the only ones from which a walk can reach
    the suite's own fixtures.
    """
    out: set = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(
                isinstance(x, ast.Name) and x.id == "__file__"
                for x in ast.walk(n.value)):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    for _ in range(4):                     # X = SOME_ANCHORED_CONST / "sub"
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and {
                    x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)} & out:
                out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return out


def _walk_root(call: "ast.Call") -> Optional[str]:
    """The left-most Name of the expression a walk is rooted at."""
    cur: Any = call.func
    while True:
        if isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.func
        elif isinstance(cur, ast.BinOp):
            cur = cur.left
        elif isinstance(cur, ast.Subscript):
            cur = cur.value
        else:
            break
    return cur.id if isinstance(cur, ast.Name) else None


def probe_selector_reaches_fixtures(cl: Clause) -> ProbeResult:
    """P5 -- can its input selection walk reach a fixture tree?  (vibe-ic#1037)

    STATIC. `_real_spef()` fell back to an unbounded `rglob` and returned the suite's
    own fixture, and two tests then described it as production extraction output. It
    was caught by luck: the fixture happened to contradict the assertion. A fixture
    that agreed would have shipped green.

    THE QUESTION IS WHERE THE WALK IS ROOTED, not whether the file mentions fixtures.
    This probe used to ask the second, and got it wrong in both directions: "the file
    names `tests/` somewhere" forgave walks that were never dangerous, and its absence
    accused 30 gates that walk only what the CALLER handed them. A walk rooted at the
    project argument cannot reach `programs/tests/fixtures/` unless the project IS the
    checkout; a walk rooted at a `__file__`-derived module constant can, always, on
    every invocation. That is decidable from the AST and it is the actual rule.

    MEASURED, and the measurement is the finding: on all 136 clauses, ZERO gate
    programs walk from a `__file__`-anchored root. #1037's defect was never in this
    population -- `_real_spef` lives in `programs/tests/_real_data.py`, a TEST helper
    no gate clause names. Pointing this probe at the test tree is a different
    instrument over a different population, and it is filed rather than bolted on
    here: a probe that silently scans the wrong population is how a census reports a
    confident zero.
    """
    src = PROGRAMS / f"{cl.program}.py"
    repro = (f"python3 -c \"import ast;…\" over programs/{cl.program}.py — find every "
             f"rglob/glob('**')/os.walk and ask whether its ROOT derives from __file__")
    if not src.is_file():
        return ProbeResult("selector_reaches_fixtures", NA, "program not found", repro)
    try:
        tree = ast.parse(src.read_text(errors="replace"))
    except SyntaxError as exc:
        return ProbeResult("selector_reaches_fixtures", SUSPECT,
                           f"cannot parse, so cannot answer: {exc}", repro)

    anchored = _repo_anchored_names(tree)
    hits: List[str] = []
    walks = 0
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr not in ("rglob", "glob", "walk"):
            continue
        if n.func.attr == "glob" and not (
                n.args and isinstance(n.args[0], ast.Constant)
                and "**" in str(n.args[0].value)):
            continue
        walks += 1
        root = _walk_root(n)
        if root and root in anchored:
            hits.append(f"{root} (line {n.lineno})")

    if hits:
        return ProbeResult("selector_reaches_fixtures", LIAR,
                           f"{len(hits)} unbounded walk(s) rooted at a __file__-derived "
                           f"constant, so the walk reaches the CHECKOUT and can select "
                           f"the suite's own fixtures as evidence: {', '.join(hits[:3])}",
                           repro)
    if walks:
        return ProbeResult("selector_reaches_fixtures", CLEAN,
                           f"{walks} unbounded walk(s), all rooted at caller-supplied "
                           f"paths — they cannot reach the checkout's fixtures", repro)
    return ProbeResult("selector_reaches_fixtures", CLEAN, "no unbounded walk", repro)


# ------------------------------------------- shapes 4 & 5: the mutation probes
#
# The five probes above are static, or run the gate once and ask whether what
# came back contradicts itself. Neither of the two below can be answered that
# way. "Has this gate ever had a CONTROL" is not a property of the gate's text
# and not a property of one run -- it is a property of the gate's TEST SUITE,
# and the only way to establish it is to break the gate and see whether the
# suite notices.
#
#   SHAPE 4  force the verdict to PASS. If nothing dies, nothing in this repo
#            can tell this gate from a gate that always says yes. It has no
#            NEGATIVE control, and neutering it is invisible.
#   SHAPE 5  force the verdict to FAIL. If nothing dies either, nothing pins
#            that it can ever say yes. It has no POSITIVE control -- which
#            makes it a BAN rather than a check.
#
# THE REPO ALREADY OWNS HALF OF THIS, AND IT IS IMPORTED, NOT REIMPLEMENTED
# ------------------------------------------------------------------------
# `programs/gate_cli_mutation_probe.py` asks SHAPE 4's question already, for the
# gates a commit touches. Two things it learned the expensive way are reused
# here verbatim rather than re-derived:
#
#   * WHICH TESTS COUNT -- `naming_tests`, including its measured refusal to cap
#     the selection ("capping at three excluded the very test written to protect
#     one of these gates, and the probe called it unprotected").
#   * WHERE THE MUTATION LIVES -- never in the checkout. Two shipped gates were
#     once found carrying an injected `return 0` beside a `.probe-orig` sidecar,
#     left by runs that were SIGKILLed between the write and the restore; a
#     neutered gate exits 0, which the flow reads as PASS. `finally` does not
#     run on SIGKILL, so the mutation moved out of the tree entirely. This
#     census mutates a disposable copy under the same `_crash_safe_scratch`
#     reservation and NEVER writes inside the repository.
#
# TWO THINGS ARE DELIBERATELY DIFFERENT, AND BOTH ARE THE CENSUS'S CONTRIBUTION
# ----------------------------------------------------------------------------
# 1. A BASELINE ARM. `gate_cli_mutation_probe` scores `CAUGHT if returncode != 0`
#    against a single run. That cannot tell "this test reddened BECAUSE of the
#    mutation" from "this test was already red", and reads the second as
#    protection. It is not a hypothetical: main carried 49 failures across a
#    184-file selection on the day this was written, and the scratch copy holds
#    `programs/` alone, so every test that resolves a path through the PLUGIN
#    root fails in the copy for reasons that have nothing to do with any gate.
#    Here every program is run THREE times -- unmutated, forced-pass,
#    forced-fail -- and the finding is the set difference of FAILED NODE IDS,
#    never a count and never an exit code.
#
# 2. THE MUTATION CHANGES THE VERDICT AND NOTHING ELSE. The shipped probe
#    injects `return 0` as the first statement of the entry point, so the gate
#    returns before it writes its report or prints a line. Every test asserting
#    on the gate's OUTPUT then dies -- including tests that never once
#    constrained the exit code the flow actually reads. That over-reports
#    protection, which is the direction that costs the most. The rewrite below
#    keeps every side effect and replaces only the value that reaches the exit,
#    by evaluating the original expression and discarding it: `return X` becomes
#    `return (X, 0)[1]`. What survives it is a test that observed the VERDICT.

#: Rewritten sources are unparsed from the AST, which normalises formatting.
#: That normalisation is subtracted, not tolerated: the baseline arm is unparsed
#: TOO, so all three arms differ in exactly one thing. A pristine-file baseline
#: would attribute every test that reads a gate's own source text -- and this
#: repo has many -- to the mutation.
def _unparse(tree: ast.Module) -> str:
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _entry_functions(tree: ast.Module) -> List[str]:
    """Module-level functions the `__main__` dispatch actually calls.

    From the AST, so a function named in a COMMENT is not one -- vibe-ic#1012 is
    the whole reason this file never decides anything by text matching. Every
    dispatch shape in this tree is covered because they are all the same shape
    structurally: a `Call` to a module-level `def`, whether it is spelled
    `sys.exit(main())`, `raise SystemExit(_cli())`, `main()` or
    `sys.exit(run(sys.argv[1:]))`.
    """
    top = {n.name for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out: List[str] = []
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(c, ast.Compare) and isinstance(c.left, ast.Name)
                   and c.left.id == "__name__" for c in ast.walk(node.test)):
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id in top):
                out.append(call.func.id)
    return out


def _discard_and_yield(expr: ast.expr, const: int) -> ast.expr:
    """`(expr, const)[1]` — evaluate the original verdict, then throw it away.

    The tuple is what keeps this a VERDICT mutation rather than a lobotomy. The
    gate still walks the tree, still writes its report, still prints its own
    prose; only the number the flow reads is replaced.
    """
    return ast.Subscript(
        value=ast.Tuple(elts=[expr, ast.Constant(const)], ctx=ast.Load()),
        slice=ast.Constant(1), ctx=ast.Load())


class _ForceVerdict(ast.NodeTransformer):
    """Every path by which a value reaches this process's exit status."""

    def __init__(self, const: int, entries: List[str]) -> None:
        self.const = const
        self.entries = set(entries)
        self.changes = 0
        self._depth = 0

    # -- the entry function's own `return`s ---------------------------------
    def visit_FunctionDef(self, node):                      # noqa: N802
        top = self._depth == 0 and node.name in self.entries
        self._depth += 1
        if top:
            self._rewrite_returns(node)
        self.generic_visit(node)
        self._depth -= 1
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def _rewrite_returns(self, fn) -> None:
        const, outer = self.const, self

        class _R(ast.NodeTransformer):
            # A nested helper's `return` is not the gate's verdict, and
            # rewriting it would change what the gate COMPUTES rather than what
            # it reports -- a different experiment with the same name.
            def visit_FunctionDef(self, n):                 # noqa: N802
                return n
            visit_AsyncFunctionDef = visit_FunctionDef
            visit_Lambda = visit_FunctionDef

            def visit_Return(self, n):                      # noqa: N802
                if n.value is None:
                    outer.changes += 1
                    return ast.Return(value=ast.Constant(const))
                if isinstance(n.value, ast.Constant) and n.value.value == const:
                    return n
                outer.changes += 1
                return ast.Return(value=_discard_and_yield(n.value, const))

        fn.body = [_R().visit(s) for s in fn.body]
        # Falling off the end returns None, which `sys.exit` reads as 0. For
        # SHAPE 5 that is a path by which the forced FAIL would silently not
        # happen, so it is closed. Unreachable when the body already returns.
        if not fn.body or not isinstance(fn.body[-1], (ast.Return, ast.Raise)):
            self.changes += 1
            fn.body.append(ast.Return(value=ast.Constant(self.const)))

    # -- and every direct exit ----------------------------------------------
    def visit_Call(self, node):                             # noqa: N802
        self.generic_visit(node)
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else "")
        if name in ("exit", "_exit"):
            self._force_first_arg(node)
        return node

    def visit_Raise(self, node):                            # noqa: N802
        self.generic_visit(node)
        exc = node.exc
        if (isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)
                and exc.func.id == "SystemExit"):
            self._force_first_arg(exc)
        elif isinstance(exc, ast.Name) and exc.id == "SystemExit":
            self.changes += 1
            node.exc = ast.Call(func=ast.Name(id="SystemExit", ctx=ast.Load()),
                                args=[ast.Constant(self.const)], keywords=[])
        return node

    def _force_first_arg(self, call: ast.Call) -> None:
        if not call.args:
            self.changes += 1
            call.args = [ast.Constant(self.const)]
            return
        first = call.args[0]
        if isinstance(first, ast.Constant) and first.value == self.const:
            return
        self.changes += 1
        call.args[0] = _discard_and_yield(first, self.const)


def force_verdict(source: str, const: int) -> Tuple[Optional[str], int]:
    """`(rewritten source, number of verdict sites changed)`.

    `(None, 0)` when there was nothing to force, which is NOT a clean result:
    a gate program with no expression reaching its exit status is one that
    cannot report anything, and the caller says so rather than scoring it.
    """
    tree = ast.parse(source)
    mut = _ForceVerdict(const, _entry_functions(tree))
    mut.visit(tree)
    if not mut.changes:
        return None, 0
    return _unparse(tree), mut.changes


# --------------------------------------------------------- running the arms
#: `FAILED <nodeid>` / `ERROR <nodeid>` from pytest's own `-rfE` short summary.
#: Node IDs, because a COUNT cannot tell one test going green and another going
#: red from nothing happening -- and the flow-change-acceptance doctrine says so
#: in as many words: "compare failure name sets, not counts".
_PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)
_PYTEST_PASSED = re.compile(r"(\d+) passed")


@dataclass
class ArmResult:
    failed: set
    passed: int
    rc: int


def _run_selection(cwd: Path, selection: List[Path],
                   timeout: int) -> Optional[ArmResult]:
    """One pytest arm. `None` means it could not be measured (timeout)."""
    # `--continue-on-collection-errors` IS LOAD-BEARING, and it was missing.
    # pytest aborts the WHOLE session on one uncollectable module -- "Interrupted:
    # 1 error during collection" -- so a single test file that cannot import
    # takes every other file in the selection with it, and the arm reports zero
    # tests run. Measured while calibrating: `step_internal_fail_bubble_up_check`
    # came back BASELINE_DEAD over a selection of 8 files for that reason alone,
    # and it would have done so on both arms of a gate the flow blocks on. With
    # the flag the broken module is reported as an ERROR node ID, which appears
    # in every arm and cancels in the difference, and the other seven files are
    # actually measured.
    argv = [sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=no",
            "-rfE", "-p", "no:cacheprovider", "-p", "pytest_timeout",
            "--continue-on-collection-errors",
            "--timeout=120", "--timeout-method=thread"]
    argv += [str(p) for p in selection]
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    # The LAST match, which is pytest's own summary line. A test that prints
    # something like "3 passed" of its own would otherwise be read as the
    # session's result, and the number this feeds decides BASELINE_DEAD -- the
    # verdict that says "this gate could not be measured".
    counts = _PYTEST_PASSED.findall(out)
    return ArmResult(failed=set(_PYTEST_FAILED.findall(out)),
                     passed=int(counts[-1]) if counts else 0,
                     rc=proc.returncode)


@dataclass
class MutationRun:
    """What forcing a gate's verdict did to that gate's own test suite."""
    program: str
    #: MEASURED, or one of the ways this probe can fail to measure. Every one of
    #: them is a DISTINCT name on purpose: "the measurement did not finish" is
    #: not one fact, and folding a spent budget, a dead baseline and a tree that
    #: could not be reserved into a single word is how a coverage hole stops
    #: being auditable.
    state: str                    # MEASURED | NO_SOURCE | NO_VERDICT | NO_TEST
    #                             # | BASELINE_DEAD | TIMEOUT | BUDGET_SPENT
    #                             # | NO_SCRATCH | MUTANT_INVALID
    tests: List[str] = field(default_factory=list)
    sites: int = 0
    baseline_passed: int = 0
    baseline_failed: List[str] = field(default_factory=list)
    #: const -> node IDs that were green at baseline and red under the forced
    #: verdict. Empty list means NOTHING DIED.
    killed: Dict[str, List[str]] = field(default_factory=dict)
    seconds: float = 0.0
    note: str = ""


#: One `MutationRun` per program, not per clause: 136 clauses name 127 distinct
#: programs, and a program probed twice would pay for the same answer twice.
#:
#: Keyed by the PROGRAMS TREE as well as the program. `PROGRAMS` is redirectable
#: -- that is how this file's own suite plants a gate -- and a cache that ignored
#: which tree it measured would answer the second planted tree with the first
#: one's result. A stale answer that looks like a measurement is the defect this
#: file exists to find, and it would be reporting one about itself.
_MUTATION_CACHE: Dict[Tuple[str, str], MutationRun] = {}
_SCRATCH_ROOTS: Dict[str, Path] = {}


def _scratch_programs_root() -> Path:
    """A disposable copy of the PLUGIN, made once per process.

    Reserved through `_crash_safe_scratch`, the module the shipped probe uses,
    so a SIGKILL leaves a stale directory under /tmp that the NEXT run reaps --
    and leaves the repository byte-for-byte what it was. Nothing in this file
    writes inside the checkout, and there is no flag that makes it. (Verified
    the ugly way while this was being written: a sweep killed mid-mutation left
    `/tmp/liar_census_mut_xhfscg6y` and a `git status` with nothing in it.)

    THE WHOLE PLUGIN, NOT `programs/` ALONE, AND THAT IS THE LOAD-BEARING PART
    -------------------------------------------------------------------------
    `gate_cli_mutation_probe.disposable_programs_root` copies `programs/` and
    runs pytest from its parent. That parent holds no `pytest.ini` and no
    plugin-root `conftest.py`, and every test that resolves a path through the
    plugin root -- the flow yaml, the skills tree, the shipped INDEX -- fails to
    IMPORT there. Measured on the first ten clauses of the first sweep: 6 came
    back with a selection in which NOTHING passed, 9 test files collecting 0
    tests. In this census that reads as BASELINE_DEAD, which is honest and
    useless; in a probe with no baseline arm it reads as CAUGHT, because pytest
    exits non-zero on a collection error. That is the false comfort the baseline
    arm exists to catch, and its cause is a copy that was too small.

    `programs/` is 68 MB of the plugin's 76 MB, so copying the other 8 MB costs
    almost nothing and buys a tree the suite can actually run in.

    Rooted at `PROGRAMS.parent` rather than `PLUGIN` so a planted tree under
    test is copied whole, the same way `PROGRAMS` itself is redirectable.

    Degrades LOUDLY. If the reservation cannot be made the census says so on
    stderr and the mutation probes decline rather than quietly scoring CLEAN.
    """
    # PER THREAD, not per process. Two workers mutating one tree would each be
    # measuring the other's mutation, and the result would be a number with no
    # experiment behind it. Each worker gets its own plugin copy; at 76 MB that
    # is the cheapest part of this probe.
    key = f"{PROGRAMS}#{threading.get_ident()}"
    if key not in _SCRATCH_ROOTS:
        # SERIALIZED, and the lock is not for the dict. `_crash_safe_scratch.
        # reserve` REAPS first and only then `mkdtemp`s and writes its lock
        # file, so between those two steps its new directory exists carrying no
        # lock -- and a concurrent `reserve` reaps precisely that shape, as "a
        # directory written by a build that predates this module". Measured the
        # first time this ran with 8 workers: `[Errno 2] ... liar_census_mut_
        # m3rtom2i` from the copytree, because a sibling had just deleted the
        # tree under it. Every shipped caller reserves once per process, so the
        # window has never been reachable before; this caller closes it by never
        # reserving twice at once rather than by changing a primitive four other
        # programs depend on.
        with _SCRATCH_LOCK:
            if key not in _SCRATCH_ROOTS:
                sys.path.insert(0, str(PLUGIN / "programs"))
                import _crash_safe_scratch as scratch          # noqa: PLC0415
                import atexit                                  # noqa: PLC0415
                res, _report = scratch.reserve("liar_census_mut_")
                plugin = res.path / "plugin"
                shutil.copytree(PROGRAMS.parent, plugin,
                                ignore=shutil.ignore_patterns(
                                    "__pycache__", ".pytest_cache", ".git"))
                atexit.register(res.release)
                _SCRATCH_ROOTS[key] = plugin / PROGRAMS.name
    return _SCRATCH_ROOTS[key]


_SCRATCH_LOCK = threading.Lock()


def _selection_for(program: str, root: Path) -> List[Path]:
    """The test files a regression in `program` would have to get past.

    IMPORTED from `gate_cli_mutation_probe`, never reimplemented, for the reason
    `probe_prose_vs_exit` imports its predicate from `flow_compliance_check`: a
    census carrying its own copy would drift from the guard that actually runs,
    silently, which is the family of defect being hunted.

    The imported selector matches the program name in the test's raw TEXT, so it
    can count a file that only mentions the program in prose. That direction is
    conservative here -- an extra file can only make something MORE likely to
    die, so it can only turn a finding into a clean result, never the reverse.

    THE COVERAGE LIMIT, STATED RATHER THAN DISCOVERED LATER
    ------------------------------------------------------
    The other direction is not covered and cannot be, by this selector: a test
    that constrains this gate's verdict WITHOUT ever naming it -- an orchestrator
    test that drives the whole flow, a generic sweep over `programs/*.py` -- is
    not in the selection, so a gate it protects can still be reported as having
    no control. 28 modules in this tree glob the programs directory. That is a
    known over-accusation channel, it is why every finding here is worth
    reproducing by hand before it is acted on, and naming it is the difference
    between a limit and a defect.
    """
    sys.path.insert(0, str(PLUGIN / "programs"))
    from gate_cli_mutation_probe import naming_tests    # noqa: PLC0415
    tests_dir = root / "tests" if (root / "tests").is_dir() else root
    return naming_tests(program, tests_dir)


def mutation_run(program: str, timeout: int, budget: "Budget") -> MutationRun:
    """Force `program`'s verdict to 0 and to 1, and see what its suite says.

    Three arms over ONE selection and ONE tree: unmutated, forced-pass,
    forced-fail. Every arm is unparsed from the AST so formatting is identical
    across all three and the only difference is the verdict.
    """
    key = (str(PROGRAMS), program)
    if key in _MUTATION_CACHE:
        return _MUTATION_CACHE[key]
    started = time.monotonic()

    def _done(run: MutationRun) -> MutationRun:
        elapsed = time.monotonic() - started
        run.seconds = round(elapsed, 1)
        # Charged on EVERY path, including the ones that give up. A budget that
        # only counts the runs that finished cannot bound a sweep whose cost is
        # in the runs that time out.
        budget.spend(elapsed)
        _MUTATION_CACHE[key] = run
        return run

    try:
        root = _scratch_programs_root()
    except Exception as exc:                                # pragma: no cover
        print(f"liar_census: CANNOT RESERVE a disposable programs tree ({exc}) "
              f"— the mutation probes are DECLINING, not passing", file=sys.stderr)
        return _done(MutationRun(program, "NO_SCRATCH", note=str(exc)[:160]))

    src = root / f"{program}.py"
    if not src.is_file():
        return _done(MutationRun(program, "NO_SOURCE"))
    original = src.read_text(errors="replace")
    fingerprint = hashlib.md5(original.encode("utf-8", "replace")).hexdigest()
    try:
        arms = {str(c): force_verdict(original, c) for c in (0, 1)}
        baseline_src = _unparse(ast.parse(original))
    except SyntaxError as exc:
        return _done(MutationRun(program, "NO_SOURCE", note=f"unparseable: {exc}"))
    if any(text is None for text, _n in arms.values()):
        return _done(MutationRun(program, "NO_VERDICT"))
    # A mutant that does not compile would fail every test in the arm, which
    # reads as "the suite noticed" -- a CLEAN bill of health handed out for a
    # broken experiment. Checked before it can be measured, never after.
    for label, (text, _n) in list(arms.items()) + [("baseline", (baseline_src, 0))]:
        try:
            compile(text, f"<{program}:{label}>", "exec")
        except SyntaxError as exc:
            return _done(MutationRun(program, "MUTANT_INVALID",
                                     note=f"the forced-{label} rewrite does not "
                                          f"compile: {exc}"))

    selection = _selection_for(program, root)
    if not selection:
        return _done(MutationRun(program, "NO_TEST"))
    if not budget.affords():
        return _done(MutationRun(program, "BUDGET_SPENT",
                                 tests=[p.name for p in selection]))

    run = MutationRun(program, "MEASURED", tests=[p.name for p in selection],
                      sites=arms["0"][1])
    try:
        src.write_text(baseline_src)
        base = _run_selection(root.parent, selection, timeout)
        if base is None:
            return _done(MutationRun(program, "TIMEOUT", tests=run.tests,
                                     note=f"baseline arm exceeded {timeout}s"))
        if base.passed == 0:
            # Nothing in the selection is green, so nothing COULD die. Scoring
            # "no test noticed" here would be an accusation the measurement
            # cannot support.
            return _done(MutationRun(
                program, "BASELINE_DEAD", tests=run.tests,
                baseline_failed=sorted(base.failed),
                note="no test in the selection passes even unmutated, so the "
                     "mutation had nothing to kill"))
        run.baseline_passed = base.passed
        run.baseline_failed = sorted(base.failed)
        for const, (text, _sites) in arms.items():
            src.write_text(text)
            arm = _run_selection(root.parent, selection, timeout)
            if arm is None:
                run.state = "TIMEOUT"
                run.note = f"forced-{const} arm exceeded {timeout}s"
                return _done(run)
            run.killed[const] = sorted(arm.failed - base.failed)
    finally:
        # Restoring is not best-effort even on a disposable tree: the NEXT
        # program measured by this process reads these bytes as its baseline.
        src.write_text(original)
        after = hashlib.md5(src.read_text(errors="replace")
                            .encode("utf-8", "replace")).hexdigest()
        if after != fingerprint:                            # pragma: no cover
            raise SystemExit(
                f"FATAL: the scratch copy of {program}.py was not restored "
                f"({fingerprint} -> {after}); every later result in this run "
                f"would be measured against a gate nobody chose to change")
    return _done(run)


class Budget:
    """A wall-clock ceiling for the mutation probes, and a record of the drop.

    Mutation is the expensive probe -- three pytest sessions per gate program.
    A sweep that runs out of time must say WHICH gates it did not reach: a
    truncation nobody can see reads as "covered everything" when it did not.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.spent = 0.0
        self._lock = threading.Lock()

    def affords(self) -> bool:
        with self._lock:
            return self.seconds <= 0 or self.spent < self.seconds

    def spend(self, dt: float) -> None:
        with self._lock:
            self.spent += dt


#: What the mutation probes CANNOT establish, by state. Each is printed with
#: the finding list, never folded into CLEAN.
_UNMEASURED = {
    "NO_SOURCE": "the clause names a program this tree does not contain",
    "NO_VERDICT": "no expression in the module reaches its exit status, so "
                  "there is no verdict to force — the gate cannot report "
                  "anything, which is a finding of a different shape",
    "NO_TEST": "no test file names this program, so there is no suite to "
               "notice — an unprotected gate and an untested one are different "
               "facts and this probe can only establish the second",
    "BASELINE_DEAD": "nothing in the selection passes even unmutated",
    "TIMEOUT": "an arm exceeded its pytest ceiling",
    "BUDGET_SPENT": "--mutation-budget ran out before this program was reached, "
                    "so it was DROPPED rather than cleared",
    "NO_SCRATCH": "no disposable tree could be reserved, so nothing was mutated",
    "MUTANT_INVALID": "the rewrite did not compile, so the arm would have "
                      "reddened for a reason that is this probe's, not the gate's",
}


def _mutation_probe(cl: Clause, const: int, probe: str, timeout: int,
                    budget: "Budget") -> ProbeResult:
    run = mutation_run(cl.program, timeout, budget)
    repro = (f"python3 -c \"import liar_census as l; "
             f"print(l.mutation_run('{cl.program}', 600, l.Budget(0)))\"")
    if run.state != "MEASURED":
        return ProbeResult(probe, NA,
                           f"NOT MEASURED ({run.state}): {_UNMEASURED[run.state]}"
                           + (f" — {run.note}" if run.note else ""), repro)
    killed = run.killed.get(str(const), [])
    if killed:
        return ProbeResult(
            probe, CLEAN,
            f"forcing the verdict to {const} killed {len(killed)} test(s) that "
            f"pass unmutated, e.g. {killed[0]} ({len(run.tests)} file(s), "
            f"{run.baseline_passed} passing at baseline)", repro)

    files = ", ".join(run.tests[:4]) + (" …" if len(run.tests) > 4 else "")
    if const == 0:
        detail = (f"NO NEGATIVE CONTROL — the verdict was forced to PASS at "
                  f"{run.sites} site(s) and every one of {run.baseline_passed} "
                  f"passing test(s) in {len(run.tests)} file(s) stayed green: "
                  f"{files}. Nothing in this repo can tell this gate from a "
                  f"gate that always says yes.")
        sev = LIAR if cl.blocking else SUSPECT
    else:
        detail = (f"NO POSITIVE CONTROL — the verdict was forced to FAIL and "
                  f"every one of {run.baseline_passed} passing test(s) in "
                  f"{len(run.tests)} file(s) stayed green: {files}. Nothing "
                  f"pins that this gate can ever say yes, which makes it a BAN "
                  f"rather than a check.")
        # A gate that can only ever say no does not launder a PASS, so it is
        # not the LIAR shape on its own -- but it is why the pair is reported
        # together: when BOTH fire, the verdict is unconstrained in every
        # direction any test could have looked.
        sev = SUSPECT
    return ProbeResult(probe, sev, detail, repro)


def _selection_size(program: str) -> int:
    """How many test files name `program`, for ORDERING only.

    Deliberately cheaper and blunter than `_selection_for`: it decides the order
    a bounded sweep works in and nothing else, so being approximate here cannot
    make a verdict wrong -- only make a budget reach a different set of gates,
    which the report names either way.
    """
    global _TEST_TEXT
    tests = PROGRAMS / "tests"
    if _TEST_TEXT is None:
        _TEST_TEXT = {p: p.read_text(errors="replace")
                      for p in sorted(tests.glob("test_*.py"))} if tests.is_dir() else {}
    rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(program) + r"(?![A-Za-z0-9_])")
    return sum(1 for text in _TEST_TEXT.values() if rx.search(text))


_TEST_TEXT: Optional[Dict[Path, str]] = None


def prewarm_mutation_cache(programs: List[str], jobs: int, timeout: int,
                           budget: "Budget") -> None:
    """Measure every distinct gate program once, `jobs` at a time.

    Ordered SMALLEST-SELECTION-FIRST when a budget is set, so a sweep that runs
    out of time has answered as many gates as it could rather than spending it
    all on one 51-file suite. Ordering changes WHICH gates a bounded sweep
    reaches; it never changes whether the report admits to the bound.

    WHICH WAY CONCURRENCY CAN BE WRONG. Workers share a machine, and a flaky
    failure under load lands in one arm and not another. In the FORCED arm it
    reads as a test the mutation killed, and in the BASELINE arm it removes a
    test that could have died -- both push the verdict toward CLEAN. So `--jobs`
    can hide a finding and cannot manufacture one, which is the direction to be
    wrong in for an instrument whose accusations cost a person's afternoon.
    """
    if budget.seconds > 0:
        programs = sorted(programs, key=_selection_size)
    if jobs <= 1:
        for name in programs:
            mutation_run(name, timeout, budget)
        return
    from concurrent.futures import ThreadPoolExecutor      # noqa: PLC0415
    done = [0]
    lock = threading.Lock()

    def work(name: str) -> None:
        run = mutation_run(name, timeout, budget)
        with lock:
            done[0] += 1
            print(f"  mutation [{done[0]}/{len(programs)}] {name[:56]:<56} "
                  f"{run.state} {run.seconds:.0f}s", file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(work, programs))


def probe_verdict_forced_pass(cl: Clause, timeout: int, budget: "Budget") -> ProbeResult:
    """P6 (SHAPE 4) -- neuter its decision, and see whether anything dies.

    WHY `guarded_on_empty` IS NOT CONSULTED HERE, WHICH IS NOT AN OVERSIGHT
    ----------------------------------------------------------------------
    `probe_empty_tree` discounts a clause when the flow declares `[condition]`,
    a `[sibling]` `files_exist`, or `[required_outputs]` above it. Those three
    are answers to ITS question -- "does rc 0 here certify a project that does
    not exist" -- and they answer it by establishing that on an empty tree this
    clause's exit code is never read.

    They say nothing about THIS question. A `files_exist` precondition decides
    WHEN the gate runs; it cannot make the verdict unimportant on the runs where
    it does. A step that is skipped on an empty tree still has its gate read on
    every populated one, and a gate nothing can tell from a gate that always
    says yes is exactly as blind there. Carrying the discount across would have
    forgiven 61 of the 62 gated steps on a rule that does not apply to them --
    the shape #1051's own empty_tree probe was corrected FOR, one probe over.

    The structure that IS consulted is the clause KIND, read from the same YAML:
    a `program_exit_zero` verdict is acted on and a finding against it is a
    LIAR; an `advisory_program_exit_zero` verdict is recorded, and the same
    measurement is a weaker claim.
    """
    return _mutation_probe(cl, 0, "verdict_forced_pass", timeout, budget)


def probe_verdict_forced_fail(cl: Clause, timeout: int, budget: "Budget") -> ProbeResult:
    """P7 (SHAPE 5) -- make it always say NO, and see whether anything dies.

    The negative control's mirror, and the reason both ship together: a suite
    that only pins the FAILURE is satisfied by a gate that always fails, and a
    suite that only pins the PASS is satisfied by one that always passes.
    v1.8.29 said so in as many words while repairing seven gates -- "every new
    test covers a return path in BOTH directions" -- and this is that sentence
    made measurable over the whole flow rather than over the seven somebody
    happened to look at.
    """
    return _mutation_probe(cl, 1, "verdict_forced_fail", timeout, budget)


# --------------------------------------------------------------- harness
def seed_minimal_tree(root: Path) -> Path:
    """A tree that LOOKS like a project but contains no evidence.

    Deliberately not empty: a gate that bails at "no reports/ dir" is a different
    (and honest) case from one that walks a populated skeleton and still says PASS.
    """
    for rel in ("reports", "phase1/generated_docs", "phase2/stage2/synth",
                "phase3/stage3/pnr", "input/docs"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def run_census(clauses: List[Clause], probes: List[str], timeout: int,
               mutation_timeout: int = 900,
               mutation_budget: float = 0,
               mutation_jobs: int = 1) -> List[ClauseReport]:
    reports: List[ClauseReport] = []
    budget = Budget(mutation_budget)
    # 136 clauses name 127 distinct programs, and the mutation probes answer per
    # PROGRAM. Doing that work up front means the per-clause loop below reads a
    # cache, and it is what makes `--mutation-jobs` possible at all.
    if {"forcedpass", "forcedfail"} & set(probes):
        prewarm_mutation_cache(sorted({c.program for c in clauses}),
                               mutation_jobs, mutation_timeout, budget)
    #: which programs each step declares as gate clauses -- the structure the
    #: producer/checker discount in `probe_writes_its_subject` reads.
    by_step: Dict[str, set] = {}
    for c in clauses:
        by_step.setdefault(c.step, set()).add(c.program)
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty"
        empty.mkdir()
        skeleton = seed_minimal_tree(Path(tmp) / "skeleton")
        for i, cl in enumerate(clauses, 1):
            rep = ClauseReport(step=cl.step, kind=cl.kind, cmd=cl.cmd, program=cl.program)
            if "empty" in probes:
                rep.probes.append(probe_empty_tree(cl, empty))
            if "prose" in probes:
                rep.probes.append(probe_prose_vs_exit(cl, empty))
            if "zero" in probes:
                rep.probes.append(probe_zero_denominator(cl, empty))
            if "writes" in probes:
                sb = Path(tmp) / f"sb{i}"
                shutil.copytree(skeleton, sb)
                rep.probes.append(probe_writes_its_subject(
                    cl, sb, same_step=by_step.get(cl.step, set()) - {cl.program}))
                shutil.rmtree(sb, ignore_errors=True)
            if "selector" in probes:
                rep.probes.append(probe_selector_reaches_fixtures(cl))
            if "forcedpass" in probes:
                rep.probes.append(probe_verdict_forced_pass(cl, mutation_timeout, budget))
            if "forcedfail" in probes:
                rep.probes.append(probe_verdict_forced_fail(cl, mutation_timeout, budget))
            reports.append(rep)
            print(f"  [{i}/{len(clauses)}] step {cl.step:>4}  {cl.program[:52]:<52} {rep.worst}",
                  file=sys.stderr, flush=True)
    return reports


#: `forcedpass`/`forcedfail` are MUTATION probes: three pytest sessions per
#: distinct gate program, measured at minutes each. They are in the default set
#: on purpose -- this file's whole thesis is that a gate can be clean on the one
#: axis somebody happened to check -- and `--probes` names the cheap subset for
#: anyone who wants the static sweep alone.
ALL_PROBES = ["empty", "prose", "zero", "writes", "selector",
              "forcedpass", "forcedfail"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flow", type=Path, default=FLOW_YAML)
    ap.add_argument("--probes", default=",".join(ALL_PROBES),
                    help=f"comma-separated subset of {ALL_PROBES}")
    ap.add_argument("--only", action="append", default=[],
                    help="restrict to clauses whose program name contains this (repeatable)")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--mutation-timeout", type=int, default=900,
                    help="per-ARM pytest ceiling for the mutation probes")
    ap.add_argument("--mutation-budget", type=float, default=0,
                    help="wall-clock seconds for ALL mutation probes together; "
                         "0 means no ceiling. What it drops is printed.")
    ap.add_argument("--mutation-jobs", type=int, default=1,
                    help="gate programs to mutate concurrently, each in its own "
                         "disposable copy of the plugin (76 MB apiece)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    clauses = discover_clauses(args.flow)
    if args.only:
        clauses = [c for c in clauses if any(o in c.program for o in args.only)]

    if not clauses:
        print("REFUSE — no gate clauses discovered. A census over nothing is not a census.")
        return 2

    probes = [p.strip() for p in args.probes.split(",") if p.strip()]
    print(f"liar_census: {len(clauses)} clause(s) x {len(probes)} probe(s)", file=sys.stderr)
    reports = run_census(clauses, probes, args.timeout,
                         mutation_timeout=args.mutation_timeout,
                         mutation_budget=args.mutation_budget,
                         mutation_jobs=args.mutation_jobs)

    liars = [r for r in reports if r.worst == LIAR]
    suspects = [r for r in reports if r.worst == SUSPECT]
    guarded = [r for r in reports if r.worst == GUARDED]
    blocking_liars = [r for r in liars if r.kind == "program_exit_zero"]
    # every discounted probe result, however its clause was finally scored
    discounted = sum(1 for r in reports for p in r.probes if p.verdict == GUARDED)

    print()
    print("=" * 78)
    print(f"LIAR CENSUS — {len(reports)} clause(s), probes: {','.join(probes)}")
    print("=" * 78)
    # A clause on which NO probe returned a score is UNMEASURED, and it used to
    # land in this line's arithmetic as CLEAN: `CLEAN` was
    # `total - liar - suspect - guarded`, so a clause whose every probe came
    # back N/A was reported as having survived them. That is the census's own
    # version of the defect it hunts -- a bill of health issued over an
    # experiment that never ran -- and it only became visible once a probe
    # existed that DECLINES often enough to notice. Counted by verdict now.
    clean = [r for r in reports if r.worst == CLEAN]
    unscored = [r for r in reports if r.worst == NA]
    print(f"  LIAR     {len(liars):>4}   ({len(blocking_liars)} of them BLOCKING)")
    print(f"  SUSPECT  {len(suspects):>4}")
    print(f"  GUARDED  {len(guarded):>4}   ({discounted} probe result(s) declined, listed below)")
    print(f"  CLEAN    {len(clean):>4}")
    print(f"  UNSCORED {len(unscored):>4}   (no probe could answer — NOT a pass)")
    print()
    for r in liars + suspects:
        tag = "BLOCKING" if r.kind == "program_exit_zero" else "advisory"
        print(f"[{r.worst}] step {r.step} ({tag})  {r.cmd}")
        for p in r.probes:
            if p.verdict in (LIAR, SUSPECT):
                print(f"     {p.probe}: {p.detail}")
                print(f"        repro: {p.repro}")
        print()

    # The discount is PRINTED. A census that silently forgives is the shape it
    # was built to find; the reader has to be able to audit every forgiveness.
    if discounted:
        print("-" * 78)
        print(f"DECLINED — {discounted} probe result(s) the census refuses to score,")
        print("each with the flow structure that makes the question not load-bearing:")
        for r in reports:
            for p in r.probes:
                if p.verdict == GUARDED:
                    print(f"  step {r.step:>4} {r.program} [{p.probe}]")
                    print(f"      {p.detail}")
        print()

    # WHAT WAS NOT MEASURED, per probe. A bounded sweep that does not name its
    # own coverage hole reads as "covered everything" -- and the mutation probes
    # are the ones with a hole, because they are the ones with a budget.
    unmeasured = [(r, p) for r in reports for p in r.probes
                  if p.verdict == NA and p.detail.startswith("NOT MEASURED")]
    if unmeasured:
        print("-" * 78)
        print(f"NOT MEASURED — {len(unmeasured)} probe result(s) over "
              f"{len({r.program for r, _ in unmeasured})} program(s). A gate this "
              f"probe could not reach has NOT been cleared by it:")
        for rep, p in unmeasured:
            print(f"  step {rep.step:>4} {rep.program} [{p.probe}]")
            print(f"      {p.detail}")
        print()
    if _MUTATION_CACHE:
        spent = sum(m.seconds for m in _MUTATION_CACHE.values())
        by_state: Dict[str, int] = {}
        for m in _MUTATION_CACHE.values():
            by_state[m.state] = by_state.get(m.state, 0) + 1
        print(f"mutation probes: {len(_MUTATION_CACHE)} distinct program(s), "
              f"{spent / 60:.1f} min, " +
              ", ".join(f"{k}={v}" for k, v in sorted(by_state.items())))
        print()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"clauses": len(reports), "probes": probes,
             "liar": len(liars), "suspect": len(suspects),
             "guarded": len(guarded), "declined_probe_results": discounted,
             "clean": len(clean), "unscored": len(unscored),
             "blocking_liar": len(blocking_liars),
             "not_measured": len(unmeasured),
             "mutation": {v.program: asdict(v)
                          for _k, v in sorted(_MUTATION_CACHE.items())},
             "reports": [asdict(r) for r in reports]}, indent=1), encoding="utf-8")

    return 1 if liars else 0


if __name__ == "__main__":
    sys.exit(main())
