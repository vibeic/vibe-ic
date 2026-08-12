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

EXIT CODES
    0  every clause CLEAN on every probe that ran
    1  at least one LIAR
    2  refused -- the population could not be established (never a pass)
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

    A SECOND DISCLOSURE CHANNEL THIS DOES NOT READ, disclosed rather than assumed
    away. `flow_compliance_check._json_report_signals_vacuous` reads a vacuity
    verdict out of the gate's OWN `--json` report — `{"verdict": "NOT_APPLICABLE"}`
    and six siblings — in BOTH the mandatory and the optional slot. This census
    reads only the stdout/rc channel. The difference is deliberate and it is not
    symmetric: that bucket is documented as "strictly ONE-DIRECTIONAL", promoting a
    step only when EVERY clause that dispatched a program disclosed vacuity, so a
    single clause's JSON disclosure does NOT stop the step being recorded PASS and
    could not license a per-clause GUARDED here. MEASURED after widening the
    population to all 167: no clause is accused on a basis this channel would
    overturn — the one new LIAR is `writes_its_subject`, which the channel does not
    touch. Stated because it is a real consumer channel and the next reader should
    not have to re-derive that it was considered.
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


#: EVERY clause kind that dispatches a gate PROGRAM. All three, because
#: `flow_compliance_check` runs all three and this census used to read two —
#: which made its own denominator the thing it had never printed. See
#: `population_report`.
CLAUSE_KINDS = ("program_exit_zero", "advisory_program_exit_zero",
                "optional_program_exit_zero")

#: Keys that STRUCTURE a gate rather than declare a clause. Kept explicit and
#: short so that anything else appearing inside a `gate:` subtree falls out as
#: an UNRECOGNISED SHAPE and gets printed, instead of silently leaving the
#: population the way `optional_program_exit_zero` did for the whole campaign.
_GATE_STRUCTURE_KEYS = frozenset({"all_of", "any_of", "files_exist"})

#: Clause spellings that carry a program but are NOT judged by an exit code, so
#: no probe here can address them. Named rather than skipped.
_NON_PROGRAM_CLAUSE_KEYS = frozenset({"json_field_true"})


def _clause_spec(key: str, val: Any) -> Optional[Tuple[str, List[str]]]:
    """`(command, condition_files_exist)` for either YAML spelling, or None.

    The flow writes a clause TWO ways and the consumer accepts both:

        - program_exit_zero: "gate_prog . --json reports/x.json"
        - optional_program_exit_zero:
            command: "gate_prog . --json reports/x.json"
            condition_files_exist: ["phase1/generated_docs/L10_TEST_CASES.json"]

    The old walker tested `isinstance(val, str)` and nothing else, so the
    mapping form fell through to `walk()`, which descended into the dict, saw
    `command:` under a key that is not a clause kind, and recorded nothing.
    Three clauses left the population that way — one of them BLOCKING
    (`clock_plan_check`) — on top of the 28 that left because their KIND was
    never in the key test at all.
    """
    if key not in CLAUSE_KINDS:
        return None
    if isinstance(val, str):
        return (val, [])
    if isinstance(val, dict) and isinstance(val.get("command"), str):
        cond = val.get("condition_files_exist")
        return (val["command"],
                [str(p) for p in cond] if isinstance(cond, list) else [])
    return None


@dataclass
class Clause:
    step: str
    kind: str          # any of CLAUSE_KINDS
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
        """Does a non-zero exit here FAIL the step?

        `optional_program_exit_zero` IS blocking, and reading it as advisory
        would have understated every finding among the 28 of them. Its
        optionality is entirely in WHETHER IT RUNS, not in what happens if it
        objects — `flow_compliance_check`, optional slot: an unmet
        `condition_files_exist` `return True` before dispatch, but once the
        condition is met, `if not passed: reasons.append("optional program
        failed: …")` and the gate fails exactly as the mandatory slot does.
        """
        return self.kind in ("program_exit_zero", "optional_program_exit_zero")

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
    def blocking(self) -> bool:
        """Same rule as `Clause.blocking`, and it must stay the same rule —
        two spellings of "does this fail the step" is two places to drift."""
        return self.kind in ("program_exit_zero", "optional_program_exit_zero")

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
                spec = _clause_spec(key, val)
                if spec is not None:
                    cmd, cond_files = spec
                    # `condition_files_exist` is the SAME structural fact as a
                    # step-level `condition`, one level down: the consumer
                    # `return True`s before dispatch when none of these
                    # resolve, so on an empty tree the program never runs and
                    # its exit code is never read. Read off the clause node,
                    # never off a list of gate names.
                    clause_guards = here_guards + tuple(
                        f"[condition_files_exist] the consumer skips this clause "
                        f"before dispatch unless files_exist: {pat}"
                        for pat in cond_files)
                    prog = cmd.split()[0] if cmd.split() else ""
                    out.append(Clause(step=here or "?", kind=key, cmd=cmd,
                                      program=prog, guards=list(clause_guards),
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


def population_report(flow_yaml: Path) -> Dict[str, Any]:
    """The census's own DENOMINATOR, derived from the same YAML structure.

    WHY THIS EXISTS
    ===============
    Every number this instrument has published — "136 clauses, LIAR n,
    SUSPECT n" — silently meant *of the ones I could see*. A reader takes it to
    mean *of all of them*. That is the empty-tree lie wearing a denominator: not
    a wrong answer, a right answer to a narrower question than the reader thinks
    was asked, and this campaign exists because of denominators nobody printed.

    Two causes were measured, and two more were HYPOTHESISED AND DISPROVED —
    both stated here because "I looked and there was nothing" is a result:

      A. A CLAUSE KIND THE KEY TEST DID NOT NAME — 28 `optional_program_exit_zero`.
         `flow_compliance_check` runs all three kinds; this census read two.
      B. THE MAPPING SPELLING of a kind it did name — 3 clauses written
         `{command: …, condition_files_exist: […]}` rather than as a bare
         string, one of them BLOCKING (`clock_plan_check`). See `_clause_spec`.
      -  NOT a cause: a clause hidden under a `condition:` subtree the walker
         skips. Measured: 0 of 167.
      -  NOT a cause: a clause declared outside any `gate:` key, or in another
         flow file. Measured: 0 of 167, and `phase1_phase2_phase3.yaml` is the
         only YAML in the plugin that contains the string at all.

    WHAT THIS RETURNS, AND WHY IT IS OPEN-ENDED
    ===========================================
    Not a list of known gaps — a list of everything inside a `gate:` subtree
    that this file does not recognise. `_GATE_STRUCTURE_KEYS` and `CLAUSE_KINDS`
    are the closed vocabulary; ANY other key becomes an `unrecognised` entry and
    is printed. That is the point of the disclosure surviving the repair: the
    NEXT clause shape somebody invents must not drop out of the population in
    silence the way `optional_program_exit_zero` did.

    Keys:
      swept          clauses `discover_clauses` returns
      by_kind        {clause kind: count} over everything declared
      unswept        [{kind, cmd, why}] — declared, program-bearing, not swept
      non_program    {key: count} — gate clauses that run NO program, so no
                     probe here can address them (today: `json_field_true`)
      unrecognised   {key: count} — a shape this file has never seen
    """
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(flow_yaml.read_text(errors="replace"))
    by_kind: Dict[str, int] = {}
    declared: List[Tuple[str, str, List[str]]] = []
    non_program: Dict[str, int] = {}
    unrecognised: Dict[str, int] = {}

    def in_gate(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                spec = _clause_spec(key, val)
                if spec is not None:
                    by_kind[key] = by_kind.get(key, 0) + 1
                    declared.append((key, spec[0], spec[1]))
                    continue                     # a clause node is a leaf here
                if key in CLAUSE_KINDS:
                    # the KIND is known, the SPELLING is not — never silent
                    by_kind[key] = by_kind.get(key, 0) + 1
                    declared.append((key, f"<unparseable {type(val).__name__}>", []))
                    continue
                if key in _NON_PROGRAM_CLAUSE_KEYS:
                    non_program[key] = non_program.get(key, 0) + 1
                    continue                     # runs no program: not our subject
                if key not in _GATE_STRUCTURE_KEYS:
                    unrecognised[key] = unrecognised.get(key, 0) + 1
                in_gate(val)
        elif isinstance(node, list):
            for val in node:
                in_gate(val)

    def find_gates(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "gate":
                    in_gate(val)
                else:
                    find_gates(val)
        elif isinstance(node, list):
            for val in node:
                find_gates(val)

    find_gates(doc)

    swept = discover_clauses(flow_yaml)
    seen = {(c.kind, c.cmd) for c in swept}
    unswept = [{"kind": k, "cmd": c,
                "why": ("the KIND is not in CLAUSE_KINDS" if k not in CLAUSE_KINDS
                        else "declared in a spelling `_clause_spec` cannot parse")}
               for k, c, _ in declared if (k, c) not in seen]
    return {"swept": len(swept), "declared": len(declared), "by_kind": by_kind,
            "unswept": unswept, "non_program": non_program,
            "unrecognised": unrecognised}


# --------------------------------------------------------------- invocation
def _expand_globs_like_the_flow(args: List[str], project: Path) -> List[str]:
    """The consumer's own argument expansion, IMPORTED, never reimplemented.

    `flow_compliance_check.__check_program_exit_zero` does not hand the clause's
    argv to the gate verbatim: it goes through `_resolve_program_cmd`, which
    `shlex.split`s the string and expands globs relative to the project with
    bash `nullglob` semantics. Twenty-two of the 136 clauses carry a glob
    (`rtl_hygiene_lint phase2/stage1/rtl/*.sv …`), and a census that passed the
    literal `*.sv` would be measuring an invocation nobody runs — the gate would
    lint zero files and PASS, and the census would score that as the gate's
    behaviour rather than as its own.

    Degrades LOUDLY, exactly like `_consumer_reads_the_refusal`: if the consumer
    cannot be imported, the census says so on stderr and falls back to verbatim
    args, which UNDER-drives every globbed clause.
    """
    try:
        sys.path.insert(0, str(PLUGIN / "programs"))
        from flow_compliance_check import _expand_globs  # noqa: PLC0415
    except Exception as exc:                                   # pragma: no cover
        print(f"liar_census: CANNOT IMPORT the flow's argument expander ({exc}) — "
              f"globbed clauses will be handed a literal pattern, which is NOT how "
              f"the flow runs them; this run UNDER-drives them", file=sys.stderr)
        return list(args)
    return _expand_globs(list(args), project)


def _argv_for(cmd: str, project: Path) -> List[str]:
    """Turn a clause command string into an argv, exactly as the flow would run it.

    The clause is written relative to a project root (`prog . --json reports/x.json`),
    so `.` means the tree under test. We keep the clause's ARGUMENTS verbatim -- with
    the single exception of the glob expansion the consumer itself performs, above.
    Rewriting anything else here would be measuring an invocation nobody actually runs,
    which is the error that made `--root` return a confident `[PASS] 504 cells` for a
    question nobody asked.
    """
    import shlex  # noqa: PLC0415
    parts = shlex.split(cmd)
    prog = PROGRAMS / f"{parts[0]}.py"
    return [sys.executable, str(prog)] + _expand_globs_like_the_flow(parts[1:], project)


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


# ------------------------------------------- shape 12: proxy, not property
#: SHAPE 12 — "every step is correct, it is simply answering a different
#: question." The hardest of the twelve and the most common. Its instances in
#: this repo are all the same silhouette:
#:
#:   * vibe-ic#663  — wanting "can current reach this pin" and measuring
#:     "does the pin's net pointer resolve". `PG_NET_OWNERSHIP_AUDIT: no_net=0`
#:     answered its own question correctly; the rail it certified had ZERO
#:     geometry. (It was published as `PG_CONNECT_AUDIT: unconnected=0` — "N/N
#:     connected" — through v1.9.62, which is the same defect in the LABEL.)
#:   * vibe-ic#1012 — wanting "is this checker wired into the flow" and
#:     measuring "does its name appear in the flow file's bytes", so a COMMENT
#:     counted. That one is in this file's own founding list.
#:   * vibe-ic#1011 — wanting "was a DFT requirement stated" and measuring
#:     "does the token appear", so a sentence DENYING it counted as evidence FOR
#:     it.
#:   * `gds_size_check` — wanting "is this a layout" and measuring "is the file
#:     over 100 KB". `gds_substance_check`'s docstring records the measurement:
#:     150 KB of `os.urandom()` behind a 4-byte HEADER signs off clean.
#:
#: WHAT IS AND IS NOT MECHANISABLE HERE
#: ------------------------------------
#: Deciding in general whether a gate's question IS the flow's question needs
#: the flow's intent, and no amount of AST gets there. Building a probe that
#: pretended to decide it would itself be shape 12 — a measurement of something
#: adjacent, reported as the answer — so this file does not have one.
#:
#: What IS decidable is the strictly weaker, strictly observable question:
#:
#:     given a project, does the gate's PASS actually depend on that project?
#:
#: A gate cannot be measuring the property if its verdict never touched the
#: artefact, and it cannot be measuring CONTENT if the same verdict survives
#: the content being replaced. Both are NECESSARY conditions, never sufficient:
#: a gate that reads every byte can still be answering the wrong question, and
#: this census cannot tell. That residue is stated in the summary, with the
#: cases found by hand, rather than papered over with a probe.
_SEED_BY_SUFFIX = {
    ".json": b'{"liar_census_seed": true, "items": [], "n": 0}\n',
    ".yaml": b"liar_census_seed: true\nitems: []\n",
    ".yml": b"liar_census_seed: true\nitems: []\n",
    ".md": b"# liar_census seed\n\nA declared output, present and shaped.\n",
    ".v": b"module liar_census_seed (input wire a, output wire y);\n"
          b"  assign y = a;\nendmodule\n",
    ".sv": b"module liar_census_seed (input wire a, output wire y);\n"
           b"  assign y = a;\nendmodule\n",
}
_SEED_DEFAULT = b"# liar_census seed: a declared output, present and shaped.\n" + b"#\n" * 24


def _seed_bytes(rel: str) -> bytes:
    return _SEED_BY_SUFFIX.get(Path(rel).suffix.lower(), _SEED_DEFAULT)


def _mutant_bytes(rel: str, n: int) -> bytes:
    """Different bytes, IDENTICAL length. Deterministic, so the repro reproduces.

    Length is held fixed on purpose: it is what separates "the verdict depends
    on the content" from "the verdict depends on the file being N bytes long",
    and the second is `gds_size_check`'s exact shape.
    """
    import hashlib  # noqa: PLC0415
    block = hashlib.sha256(rel.encode()).digest()
    return (block * (n // len(block) + 1))[:n]


#: flags whose value is where the gate WRITES, not what it reads. A gate's own
#: report is not its subject, and seeding it would put the census's bytes where
#: the gate is about to put its own.
_OUTPUT_FLAGS = {"--json", "--out", "--output", "--report", "--report-json",
                 "--coverage-json", "--out-json", "--summary-json"}


def _looks_like_a_path(tok: str) -> bool:
    return ("/" in tok or any(ch in tok for ch in "*?")) and not tok.startswith("-")


def clause_subject_paths(cl: Clause) -> Tuple[List[str], List[str]]:
    """What the FLOW points this clause at, and where it tells it to write.

    Both come out of the clause command string the flow itself declares, plus
    the enclosing step's `required_outputs` — never a per-gate table.

    The distinction matters and getting it wrong is how this probe would commit
    its own shape 12: `required_outputs` is frequently the gate's OWN REPORT
    (`rtl_hygiene_lint` declares `reports/phase2/lint/rtl_hygiene.json`), while
    its SUBJECT is the positional argument beside it
    (`phase2/stage1/rtl/*.sv`). Seeding the report and calling it the subject
    would measure whether the gate reads its own output.
    """
    subjects: List[str] = []
    outputs: List[str] = []
    parts = cl.cmd.split()[1:]
    i = 0
    while i < len(parts):
        tok = parts[i]
        if tok in _OUTPUT_FLAGS and i + 1 < len(parts):
            outputs.append(parts[i + 1])
            i += 2
            continue
        if _looks_like_a_path(tok):
            subjects.append(tok)
        i += 1
    for pat in cl.step_outputs:
        if pat not in outputs:
            subjects.append(pat)
    return subjects, outputs


def _concrete(pat: str) -> List[str]:
    """Concrete instances of a declared path pattern, deterministically.

    Two flow spellings are honoured, and BOTH are read the way the consumer
    reads them rather than invented here:

      * `" OR "` is the flow's ANY-OF separator inside a single
        `required_outputs` entry (`flow_compliance_check`: "the ` OR ` spelling
        exists for one artefact with two accepted names"). Every alternative is
        materialised — a tree may legitimately carry all of them, and seeding
        more of the gate's possible subjects makes a "never read it" finding
        harder to reach, not easier. Splitting on it was not optional: without
        it the census wrote ONE file whose NAME was the whole `A OR B OR C`
        string, and then reported what the gate did with that.
      * a glob declares that SOME file matching it must exist, so materialising
        one instance is an instance of the declaration, not an invention.
        Skipping globs instead would drop whole steps — every one of step 37's
        outputs is a glob — and report the gap as coverage. `**` and `*`
        collapse to one fixed token so the name is stable and the repro line
        reproduces.
    """
    out: List[str] = []
    for alt in str(pat).split(" OR "):
        alt = alt.strip()
        if not alt or alt.startswith(("/", "~")) or ".." in alt.split("/"):
            continue                     # never write outside the sandbox
        rel = re.sub(r"\*\*/?", "liar_census_seed/", alt)
        rel = rel.replace("*", "liar_census_seed").replace("?", "x")
        rel = re.sub(r"\[([^\]]+)\]", lambda m: m.group(1)[0], rel)
        rel = re.sub(r"/+", "/", rel).strip("/")
        if rel:
            out.append(rel)
    return out


def seed_declared_tree(root: Path, cl: Clause, mutate: bool = False) -> List[str]:
    """A project carrying every artefact the flow points this clause at.

    Returns the project-relative paths actually written — the manifest the
    probes use as ground truth for "this file existed when the gate looked".
    """
    seed_minimal_tree(root)
    subjects, _outputs = clause_subject_paths(cl)
    written: List[str] = []
    for pat in subjects:
        for rel in _concrete(pat):
            dest = root / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                payload = _seed_bytes(rel)
                dest.write_bytes(_mutant_bytes(rel, len(payload)) if mutate else payload)
            except OSError:
                continue
            written.append(rel)
    return sorted(set(written))


@dataclass
class Trace:
    """What one traced invocation actually did to the project it was pointed at."""
    rc: int
    out: str
    instrumentation: str
    read: List[str] = field(default_factory=list)
    wrote: List[str] = field(default_factory=list)
    looked: List[str] = field(default_factory=list)
    spawned: bool = False

    @property
    def usable(self) -> bool:
        return self.instrumentation == "COMPLETE" and not self.spawned and self.rc != 70


TRACE_SHIM = HERE / "_liar_census_trace.py"


def _run_traced(cmd: str, project: Path, timeout: int = 60) -> Trace:
    """`_run`, but with `_liar_census_trace` recording every file the gate touched.

    Still a subprocess, still `cwd=project`, still the clause command VERBATIM —
    the only difference from `_run` is the shim wrapper inside it.
    """
    base = _argv_for(cmd, project)          # same resolution as `_run`, glob expansion included
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
        tracef = Path(fh.name)
    try:
        argv = [sys.executable, str(TRACE_SHIM), base[1], str(tracef)] + base[2:]
        try:
            proc = subprocess.run(
                argv, cwd=str(project), capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return Trace(124, "<TIMEOUT>", "INCOMPLETE: timed out")
        except OSError as exc:
            return Trace(127, f"<NOT RUNNABLE: {exc}>", "INCOMPLETE: not runnable")
        try:
            payload = json.loads(tracef.read_text())
        except (OSError, ValueError):
            return Trace(rc, out, "INCOMPLETE: the shim wrote no trace")
    finally:
        tracef.unlink(missing_ok=True)

    tr = Trace(rc=payload.get("rc", rc), out=out,
               instrumentation=str(payload.get("instrumentation", "INCOMPLETE: absent")))
    proj = os.path.realpath(project)
    for raw, channels in (payload.get("touched") or {}).items():
        if "spawn" in channels:
            tr.spawned = True
        full = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(proj, raw))
        if not (full == proj or full.startswith(proj + os.sep)):
            continue                    # the PDK, the plugin, the stdlib: not the subject
        rel = os.path.relpath(full, proj)
        if "read" in channels:
            tr.read.append(rel)
        if "write" in channels:
            tr.wrote.append(rel)
        if "look" in channels:
            tr.looked.append(rel)
    for lst in (tr.read, tr.wrote, tr.looked):
        lst[:] = sorted(set(lst))
    return tr


def _shape12_na(reason: str, repro: str) -> List[ProbeResult]:
    return [ProbeResult("pass_without_reading", NA, reason, repro),
            ProbeResult("content_blind_pass", NA, reason, repro)]


def probe_proxy_not_property(cl: Clause, tmp: Path, idx: int,
                             timeout: int) -> List[ProbeResult]:
    """P6+P7 — shape 12, in the only two forms that can be OBSERVED rather than argued.

    Both run over a tree seeded with everything the flow declares this step
    produces, so the gate is looking at a project that has the evidence its own
    step is supposed to leave behind.

    P6 `pass_without_reading` — the gate returned 0 and never opened a single
    file inside the project. Whatever it measured, it was not this project.
    Two tiers, and the second is deliberately the weaker verdict:

      NEVER TOUCHED   no read, no write, no stat, no listdir inside the tree.
                      The verdict is a function of argv. LIAR if BLOCKING.
      LOOKED, NEVER READ  it stat'd or listed a file that WAS THERE and never
                      opened it: existence stood in for substance. Scored
                      SUSPECT and never LIAR, because a gate whose declared
                      property IS presence is measuring exactly the right
                      thing, and NOTHING IN THE STRUCTURE DISTINGUISHES THE
                      TWO. Saying otherwise would be this probe committing
                      shape 12 on its way to reporting it.

    P7 `content_blind_pass` — the CONTROL on P6, and the only construct here
    that demonstrates rather than infers. Run again on a tree differing in
    exactly one respect: the bytes inside the seeded artefacts, at IDENTICAL
    length. Holding length fixed separates "the verdict reads the file" from
    "the verdict reads the file's SIZE" — the second is `gds_size_check`'s exact
    shape (150 KB of `os.urandom()` behind a HEADER record signs off clean, per
    `gds_substance_check`'s own measurement).

    P7 IS SCORED ONLY WHERE P6 ALREADY FIRED, and that restriction is not
    timidity — it is the correction of a real false positive this probe had
    when it was written the obvious way. `l_doc_todo_stub_count_check` READS
    every L-doc, counts `TODO`, and passes on both arms because neither arm
    contains a TODO. Its verdict is perfectly content-sensitive; the mutation
    simply handed it a second compliant input. A byte-scramble is not a
    SEMANTIC mutation — it cannot turn a conformant artefact into a
    non-conformant one, only into a different conformant one — so "the verdict
    did not move" is evidence of nothing on its own. Where P6 has already
    established that the gate never opened the file, P7 turns that inference
    into a demonstration; everywhere else it reports CLEAN and says what it
    could not decide.

    WHAT IS DROPPED, AND IT IS PRINTED
    ----------------------------------
    Neither probe scores a clause that:
      * SPAWNED A CHILD PROCESS — the audit hook does not follow children, so a
        gate whose real reading happens in `klayout`/`yosys` looks like a gate
        that read nothing. Accusing it would be the census reporting its own
        blindness as a finding.
      * ran under INCOMPLETE instrumentation (a `stat` channel that failed its
        own self-test on this host),
      * crashed, timed out, or is not runnable,
      * did not PASS on the seeded tree — there is no PASS whose basis could be
        tested, and P7 has nothing to hold constant,
      * has NO path the flow points it at, so the tree carries nothing to read.
    Every one is counted and listed under DROPPED in the summary. A bounded
    probe that does not say what it skipped reads as coverage it never had.

    TWO GUARDS, both structural, both found the way #1054 found its own
    -------------------------------------------------------------------
    * DISCLOSED VACUITY — a gate may print `VACUOUS_PASS:` and still exit 0;
      `flow_compliance_check` reads that on the passing path and records
      VACUOUS_PASS, not PASS. Such a gate is not certifying the project, it is
      declining to, out loud, on the channel the flow actually reads. The
      predicate is IMPORTED from the consumer, never restated.
    * ASSERTS ABSENCE — this probe's fail-safe class, and it is the same one
      #1051's `empty_tree` probe had: a gate whose property is that a forbidden
      artefact is NOT THERE reads nothing because there is nothing to read, and
      that is the correct behaviour, not a proxy. Decided by structure, not by
      name: if the gate performed no read at all and EVERY path it looked at
      inside the project was ABSENT from the seeded tree, its subject is
      absence. `analog_a0_skip_forbidden_check` is the live instance —
      `[PASS] forbidden A0_skip_decision.json not present`.

      THE GUARD'S OWN LIMIT, measured rather than assumed. It cannot separate
      "this artefact is forbidden and is correctly absent" from "my evidence
      was missing, so I passed", because from outside the two are the same
      trace. `professional_tb_check` is the second kind and is forgiven here:
      `NOT_APPLICABLE: no professional_tb.json (step did not run)`, rc 0,
      BLOCKING at step 4. A presence-flip experiment was tried as a
      discriminator and does not work — materialising the path with generic
      content leaves BOTH gates at rc 0, since neither `{}` nor random bytes is
      a skip verdict or a TB report. So the guard forgives and PRINTS, and the
      adjudication is a human's. Guessing between them would be this probe
      doing the thing it exists to report.
    """
    repro = (f"python3 tools/_liar_census_trace.py programs/{cl.program}.py /tmp/t.json "
             f"{' '.join(cl.cmd.split()[1:])}  # in a tree seeded with the step's "
             f"required_outputs; then again with those files' bytes replaced at equal length")

    seed_dir = tmp / f"s12a{idx}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    manifest = seed_declared_tree(seed_dir, cl)
    if not manifest:
        return _shape12_na("dropped: the flow points this clause at no path at all, "
                           "so there is nothing to seed and nothing to mutate", repro)
    present = {os.path.relpath(str(p), str(seed_dir))
               for p in seed_dir.rglob("*") if p.is_file()}

    ta = _run_traced(cl.cmd, seed_dir, timeout)
    if ta.rc in (70, 124, 127):
        return _shape12_na(f"dropped: not observable (rc={ta.rc}) — {ta.out.strip()[:120]}", repro)
    if ta.spawned:
        return _shape12_na("dropped: the gate spawned a child process, and this hook does "
                           "not follow children — its real reading may all be in there", repro)
    if ta.instrumentation != "COMPLETE":
        return _shape12_na(f"dropped: {ta.instrumentation} — a partly blind instrument "
                           f"must not produce a finding", repro)
    if ta.rc != 0:
        return _shape12_na(f"dropped: does not PASS on the seeded tree (rc={ta.rc}), so there "
                           f"is no PASS whose basis can be tested", repro)
    if _consumer_reads_the_refusal(ta.out):
        line = next((l.strip() for l in ta.out.splitlines() if _REFUSAL_LEAD.match(l)), "")
        return [ProbeResult("pass_without_reading", GUARDED,
                            f"exits 0 having read nothing, but discloses it on the channel "
                            f"flow_compliance_check reads on the passing path, so the flow "
                            f"records VACUOUS_PASS rather than PASS — {line[:90]!r}", repro),
                ProbeResult("content_blind_pass", GUARDED,
                            "same disclosure — the flow does not record this as a PASS", repro)]

    # ---- P6
    looked_at_something_there = sorted(set(ta.looked) & present)
    # A path still carrying a glob metacharacter is a PATTERN the gate stat'd,
    # not a file it found missing, so it can never be evidence that the gate's
    # subject is an absence.
    looked_concrete = [p for p in ta.looked if not any(c in p for c in "*?[")]
    if not ta.read and looked_concrete and not looked_at_something_there:
        guard = ProbeResult(
            "pass_without_reading", GUARDED,
            f"reads nothing, but every one of the {len(ta.looked)} path(s) it looked at "
            f"inside the project was ABSENT ({', '.join(ta.looked[:3])}) — its subject may "
            f"BE the absence, and a gate asserting a forbidden artefact is not there has "
            f"nothing to read. THE GUARD CANNOT SEPARATE THAT from 'my evidence was "
            f"missing, so I passed': both look identical from outside. Forgiven here and "
            f"listed for a human, because a probe that guesses between them is the shape "
            f"this census reports. Measured example of the second kind, adjudicated by "
            f"hand: professional_tb_check → 'NOT_APPLICABLE: no professional_tb.json "
            f"(step did not run)', rc 0, BLOCKING at step 4",
            repro)
        shutil.rmtree(seed_dir, ignore_errors=True)
        return [guard, ProbeResult("content_blind_pass", GUARDED,
                                   "same: a verdict about absence is content-blind by "
                                   "construction, which is correct, not a finding", repro)]

    if not (ta.read or ta.looked or ta.wrote):
        sev = LIAR if cl.blocking else SUSPECT
        p6 = ProbeResult(
            "pass_without_reading", sev,
            f"exits 0 over a project carrying all {len(manifest)} artefact(s) the flow "
            f"points it at, and never opened, stat'd or listed ANY path inside it — the "
            f"verdict is not a function of the project it was pointed at",
            repro)
    elif not ta.read and looked_at_something_there:
        p6 = ProbeResult(
            "pass_without_reading", SUSPECT,
            f"exits 0 having LOOKED at {len(looked_at_something_there)} artefact(s) that "
            f"were present ({', '.join(looked_at_something_there[:3])}) and READ none of "
            f"them — existence stood in for substance. SUSPECT and never LIAR: a gate whose "
            f"declared property IS presence measures exactly this, and nothing in the "
            f"structure distinguishes the two",
            repro)
    else:
        p6 = ProbeResult("pass_without_reading", CLEAN,
                         f"read {len(ta.read)} path(s) inside the project", repro)

    # ---- P7: the control on P6. Same paths, same lengths, different bytes.
    if p6.verdict not in (LIAR, SUSPECT):
        shutil.rmtree(seed_dir, ignore_errors=True)
        return [p6, ProbeResult(
            "content_blind_pass", CLEAN,
            f"not scored: the gate read {len(ta.read)} path(s), so a byte-scramble at equal "
            f"length cannot decide anything — it produces a DIFFERENT COMPLIANT input, not a "
            f"violating one, and an unchanged verdict over it is evidence of nothing",
            repro)]

    mut_dir = tmp / f"s12b{idx}"
    mut_dir.mkdir(parents=True, exist_ok=True)
    seed_declared_tree(mut_dir, cl, mutate=True)
    tb = _run_traced(cl.cmd, mut_dir, timeout)
    if not tb.usable or tb.rc in (124, 127):
        p7 = ProbeResult("content_blind_pass", NA,
                         f"dropped: the mutated arm was not observable (rc={tb.rc}, "
                         f"{tb.instrumentation})", repro)
    elif tb.rc == 0 and not _consumer_reads_the_refusal(tb.out):
        p7 = ProbeResult(
            "content_blind_pass", p6.verdict,      # a confirmation, not a second charge
            f"CONFIRMED by mutation, not inferred: the same PASS comes back when all "
            f"{len(manifest)} artefact(s) have their bytes replaced at UNCHANGED length, so "
            f"the verdict is a function of presence and size, never of content",
            repro)
    else:
        p7 = ProbeResult("content_blind_pass", CLEAN,
                         f"REFUTES the P6 finding on this clause — the verdict moved when "
                         f"the bytes moved (rc {ta.rc} → {tb.rc}), so the gate is reading "
                         f"content through a path this hook did not attribute to it",
                         repro)

    shutil.rmtree(seed_dir, ignore_errors=True)
    shutil.rmtree(mut_dir, ignore_errors=True)
    return [p6, p7]


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


def run_census(clauses: List[Clause], probes: List[str], timeout: int) -> List[ClauseReport]:
    reports: List[ClauseReport] = []
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
            if "proxy" in probes:
                rep.probes.extend(probe_proxy_not_property(cl, Path(tmp), i, timeout))
            reports.append(rep)
            print(f"  [{i}/{len(clauses)}] step {cl.step:>4}  {cl.program[:52]:<52} {rep.worst}",
                  file=sys.stderr, flush=True)
    return reports


def _coverage_block(pop: Dict[str, Any], scored: int, filtered: bool) -> str:
    """The coverage line, printed on EVERY run — including the runs where it is
    100%, and that is the requirement, not an oversight.

    A census whose numbers imply full coverage when they do not is the empty-tree
    lie one level up: a right answer to a narrower question than the reader
    thinks was asked. Printing it only when there is a gap would mean the gap's
    ABSENCE is the thing nobody can audit — and the next clause shape somebody
    invents would drop out of the population exactly as quietly as
    `optional_program_exit_zero` did for this entire campaign.
    """
    lines = ["-" * 78]
    declared, unswept = pop["declared"], pop["unswept"]
    if filtered:
        lines.append(f"COVERAGE — {scored} clause(s) scored under --only, out of "
                     f"{pop['swept']} swept of {declared} program clause(s) declared.")
    else:
        lines.append(f"COVERAGE — swept {pop['swept']} of {declared} program clause(s) "
                     f"the flow declares"
                     + ("." if not unswept else f"; {len(unswept)} NOT reachable by this "
                                               f"instrument, listed below:"))
        for kind, n in sorted(pop["by_kind"].items()):
            lines.append(f"    {n:>4}  {kind}"
                         + ("   [BLOCKING]" if kind != "advisory_program_exit_zero" else ""))
    for u in unswept:
        lines.append(f"  NOT SWEPT  {u['kind']}: {u['cmd'].split()[0] if u['cmd'] else '?'}"
                     f"  — {u['why']}")
    for key, n in sorted(pop["non_program"].items()):
        lines.append(f"  OUT OF SUBJECT  {n} x `{key}` — a gate clause that dispatches no "
                     f"program, so no probe here can address it (every probe runs one).")
    for key, n in sorted(pop["unrecognised"].items()):
        lines.append(f"  UNRECOGNISED SHAPE  {n} x `{key}` inside a `gate:` subtree — this "
                     f"instrument has never seen it and is NOT scoring it. Widen "
                     f"CLAUSE_KINDS/_GATE_STRUCTURE_KEYS or say why it is out of subject.")
    return "\n".join(lines) + "\n"


ALL_PROBES = ["empty", "prose", "zero", "writes", "selector", "proxy"]

#: probes whose N/A is a BOUNDED COVERAGE decision rather than an inapplicable
#: question — every one of these has to be listed, with its reason, or the run
#: reads as coverage it never had.
_BOUNDED = ("pass_without_reading", "content_blind_pass")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flow", type=Path, default=FLOW_YAML)
    ap.add_argument("--probes", default=",".join(ALL_PROBES),
                    help=f"comma-separated subset of {ALL_PROBES}")
    ap.add_argument("--only", action="append", default=[],
                    help="restrict to clauses whose program name contains this (repeatable)")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    clauses = discover_clauses(args.flow)
    if args.only:
        clauses = [c for c in clauses if any(o in c.program for o in args.only)]

    if not clauses:
        print("REFUSE — no gate clauses discovered. A census over nothing is not a census.")
        return 2

    probes = [p.strip() for p in args.probes.split(",") if p.strip()]
    pop = population_report(args.flow)
    print(f"liar_census: {len(clauses)} clause(s) x {len(probes)} probe(s)", file=sys.stderr)
    reports = run_census(clauses, probes, args.timeout)

    liars = [r for r in reports if r.worst == LIAR]
    suspects = [r for r in reports if r.worst == SUSPECT]
    guarded = [r for r in reports if r.worst == GUARDED]
    blocking_liars = [r for r in liars if r.blocking]
    # every discounted probe result, however its clause was finally scored
    discounted = sum(1 for r in reports for p in r.probes if p.verdict == GUARDED)

    print()
    print("=" * 78)
    print(f"LIAR CENSUS — {len(reports)} clause(s), probes: {','.join(probes)}")
    print("=" * 78)
    print(f"  LIAR     {len(liars):>4}   ({len(blocking_liars)} of them BLOCKING)")
    print(f"  SUSPECT  {len(suspects):>4}")
    print(f"  GUARDED  {len(guarded):>4}   ({discounted} probe result(s) declined, listed below)")
    print(f"  CLEAN    {len(reports) - len(liars) - len(suspects) - len(guarded):>4}")
    print()
    print(_coverage_block(pop, len(reports), bool(args.only)))
    for r in liars + suspects:
        tag = "BLOCKING" if r.blocking else "advisory"
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

    # BOUNDED COVERAGE, printed. `probe_proxy_not_property` scores only the
    # clauses it can actually observe, and silent truncation reads as "covered
    # everything" when it did not. Every drop is named with its reason.
    dropped = [(r, p) for r in reports for p in r.probes
               if p.probe in _BOUNDED and p.verdict == NA]
    if dropped:
        scored = sum(1 for r in reports for p in r.probes
                     if p.probe in _BOUNDED and p.verdict != NA)
        print("-" * 78)
        print(f"DROPPED — {len(dropped)} shape-12 probe result(s) NOT scored "
              f"({scored} were). These are coverage this run does NOT have:")
        why: Dict[str, int] = {}
        for _r, p in dropped:
            why[p.detail.split("—")[0].strip()] = why.get(p.detail.split("—")[0].strip(), 0) + 1
        for reason, n in sorted(why.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>4}  {reason}")
        print()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"clauses": len(reports), "probes": probes,
             "liar": len(liars), "suspect": len(suspects),
             "guarded": len(guarded), "declined_probe_results": discounted,
             "blocking_liar": len(blocking_liars),
             "dropped_probe_results": len(dropped),
             "reports": [asdict(r) for r in reports]}, indent=1), encoding="utf-8")

    return 1 if liars else 0


if __name__ == "__main__":
    sys.exit(main())
