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

THE PROBES, AND WHAT EACH ONE CAN SEE
=====================================
Five probes ask about the GATE — what it prints, what it exits, what it writes,
what it selects. Three more ask about the WIRING, and they exist because a gate
can be perfectly correct and still be mounted somewhere its answer is thrown
away. No amount of looking at the gate finds that; you have to trace the CALLER.

    empty_tree           passes over a tree containing nothing
    prose_vs_exit        says it did not check, exits 0 anyway     (#1017)
    zero_denominator     reports a zero population and passes      (#1002)
    writes_its_subject   modifies the tree it is judging           (#1029)
    selector_reaches_..  its input walk can reach the fixtures     (#1037)
  ---- the wiring, not the gate ----
    never_blocks         runs, produces a verdict, and no consumer
                         can act on it. On a dashboard this is
                         indistinguishable from coverage.        (SHAPE 7)
    depth_pinned_walk    its population is a function of how many
                         path components the caller typed          (#1025)
    path_spelling        the same directory, spelled differently,
                         gets a different answer                 (SHAPE 11)

The last two are one family asked two ways, and the split is the finding: a
fixed-depth walk agrees across every SPELLING of a directory and still reaches
nothing when the caller types a different DEPTH of the same corpus. A single
probe would have reported a confident zero over the half it could see.

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

def _plugin_on_path() -> None:
    """Put the real plugin's `programs/` on `sys.path`, ONCE.

    Not `PROGRAMS`: that one is redirected at a planted tree under test, and a
    fixture must never get to decide what the census imports as authority.
    """
    p = str(PLUGIN / "programs")
    if p not in sys.path:
        sys.path.insert(0, p)


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
        _plugin_on_path()
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
class FlowGraph:
    """The flow's own ORDERING declarations, as the two consumers read them.

    `probe_never_blocks` needs to answer "can anything act on a non-pass here?",
    and that is a question about CALLERS, not about the gate. Two consumers
    decide it, and both read this graph rather than the gate:

      * `flow_compliance_check._evaluate_gate` — turns a clause's non-zero exit
        into the step's FAIL, but only from a blocking SLOT.
      * `flow_step_execution_coverage_check.analyze()` — "forces Overall FAIL
        when a PASS step's transitive `blocks_on` ancestry reaches a non-PASS
        applicable step". That is the ONLY consumer that can contradict a step
        which passed its own gate over an input its producer never made.

    Both are parsed from the YAML structure, never its text (#1012).
    """
    step_ids: set = field(default_factory=set)
    #: step id -> the steps it declares it waits for
    blocks_on: Dict[str, List[str]] = field(default_factory=dict)
    #: step id -> the `required_inputs[].from` producers it declares it READS
    inputs_from: Dict[str, List[str]] = field(default_factory=dict)

    def ancestry(self, sid: str) -> set:
        """Transitive `blocks_on` ancestry — the same BFS the ordering guard
        runs (`flow_step_execution_coverage_check._ancestry`), cycle-safe."""
        seen: set = set()
        queue = list(self.blocks_on.get(sid, []))
        while queue:
            nxt = queue.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.extend(self.blocks_on.get(nxt, []))
        return seen


def discover_flow_graph(flow_yaml: Path) -> FlowGraph:
    """Every step's declared dependencies and declared input producers.

    A step node is anything carrying an `id` together with a `name` — the same
    shape `flow_dependency_graph_check.load_steps` and
    `flow_step_execution_coverage_check.load_blocks_on` walk, so this census
    reads the graph the flow's own consumers read rather than a second opinion
    about it.
    """
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(flow_yaml.read_text(errors="replace"))
    g = FlowGraph()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "name" in node:
                sid = str(node["id"])
                if not sid.startswith("stage"):
                    g.step_ids.add(sid)
                    g.blocks_on[sid] = [str(x) for x in (node.get("blocks_on") or [])]
                    froms = []
                    for entry in (node.get("required_inputs") or []):
                        if isinstance(entry, dict) and entry.get("from") is not None:
                            froms.append(str(entry["from"]))
                    g.inputs_from[sid] = froms
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)

    walk(doc)
    return g


#: A gate program's OWN declaration of whether it is meant to block, read the
#: way `flow_gate_enforcement_audit` reads it (#886): a declaration OPENS its
#: line. A mention of the token inside a sentence is not one, and reading
#: mentions as declarations is how several gates were credited with an intent
#: they never stated. `[ \t]` and not `\s`, because `\s` crosses newlines.
_ENFORCEMENT_DECL = re.compile(
    r"""^[ \t]*(?:\#[ \t]*|["']{3})?ENFORCEMENT:[ \t]*(blocking|advisory)\b""",
    re.M | re.I,
)


def _declared_enforcement(program: str) -> Optional[str]:
    src = PROGRAMS / f"{program}.py"
    if not src.is_file():
        return None
    hit = _ENFORCEMENT_DECL.search(src.read_text(errors="replace"))
    return hit.group(1).lower() if hit else None


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


def probe_never_blocks(cl: Clause, graph: FlowGraph) -> ProbeResult:
    """P6 -- it runs, it produces a verdict, and it is wired where it can never
    block.  (SHAPE 7 of the 63x9 catalogue)

    On a dashboard this is indistinguishable from coverage: the step shows a
    gate, the gate shows a program, the program prints a verdict. Nothing that
    verdict says can change what the flow does. THE QUESTION IS ABOUT THE
    CALLER, NOT THE GATE -- a gate can be perfectly correct and still be wired
    somewhere its answer is discarded, which is why no amount of looking at the
    gate finds this.

    Two consumers can act on a non-pass, and this probe asks both. They are
    read from the flow's own structure, never from a list of step or gate
    names, which would rot the moment either is renamed.

    CONSUMER 1 -- `flow_compliance_check._evaluate_gate`, the SLOT
    -------------------------------------------------------------
    `advisory_program_exit_zero` ends in `return True, reasons  # advisory:
    never blocks, always recorded`. A clause in that slot cannot fail its step,
    ever, whatever it prints. That is not itself a lie: the slot IS the
    disclosure, declared in the flow's own grammar where any reader can see it.

    It becomes a lie when the gate's own docstring says the opposite. A program
    that opens a line with `ENFORCEMENT: blocking` and is wired advisory has
    stated an intent the wiring cannot honour, and a reader who trusts the
    declaration is reading coverage that stops nothing. MEASURED on this tree:
    ZERO clauses are in that state (34 advisory clauses -- 15 declare advisory,
    19 declare nothing). A measured zero, with a control that fires on a planted
    one, is a different claim from a probe that has never looked.

    CONSUMER 2 -- the ORDERING GUARD, and this is where the population is
    --------------------------------------------------------------------
    `flow_step_execution_coverage_check.analyze()` "forces Overall FAIL when a
    PASS step's transitive `blocks_on` ancestry reaches a non-PASS applicable
    step". It is the only consumer that can contradict a step which passed its
    own gate over an input whose PRODUCER failed.

    So when a step declares `required_inputs: [{from: X}]` -- the flow saying,
    in its own words, that this step READS X's output -- and X is not in the
    step's transitive `blocks_on` ancestry, the guard is disarmed for that
    edge. The step's gate runs, prints PASS, and a FAILED X cannot contradict
    it. This flow has already paid for exactly that once, and says so at the
    step it happened to:

        "With `blocks_on: []` NO edge in this flow named D1 (62 blocks_on
        lines, zero D1 references), so the ordering guard ... was structurally
        blind to a FAILED Phase 1: Step 1 self-certified on the presence of RTL
        files alone."

    That one was repaired by declaring `blocks_on: [D1]`. This probe asks the
    same question of all 63 steps instead of the one somebody collided with.

    THE FAIL-SAFE CLASS, BY STRUCTURE
    ---------------------------------
    `from: external` is the flow's way of saying the input comes from outside
    the flow -- the user's documents, the PDK, a board. No `blocks_on` edge can
    exist to a step that does not exist, so demanding one would be a false
    positive on every genuine entry point. Decided by asking whether the `from`
    value is the id of a step this flow declares, which is the same test
    `flow_dependency_graph_check` uses for a dangling reference -- not by
    matching the word `external`, which would be a name list with one name in
    it and would miss the next spelling of the same idea.
    """
    step = cl.step
    repro = (f"python3 -c \"import yaml; d=yaml.safe_load(open('flow/"
             f"phase1_phase2_phase3.yaml'))\" — for step {step}, compare its "
             f"`required_inputs[].from` against its transitive `blocks_on`")

    declared = _declared_enforcement(cl.program)
    if not cl.blocking and declared == "blocking":
        return ProbeResult(
            "never_blocks", LIAR,
            f"wired `advisory_program_exit_zero`, which "
            f"flow_compliance_check._evaluate_gate answers with an "
            f"unconditional `return True` — but the program's own docstring "
            f"opens a line with `ENFORCEMENT: blocking`. It states an intent "
            f"its wiring cannot honour, so its verdict is coverage that stops "
            f"nothing", repro)

    froms = graph.inputs_from.get(step, [])
    if not froms:
        return ProbeResult("never_blocks", CLEAN,
                           f"step {step} declares no `required_inputs`, so it "
                           f"claims to consume no other step's verdict", repro)

    ancestry = graph.ancestry(step)
    intra = [f for f in froms if f in graph.step_ids]
    external = [f for f in froms if f not in graph.step_ids]
    missing = [f for f in intra if f not in ancestry]

    if missing:
        sev = LIAR if cl.blocking else SUSPECT
        return ProbeResult(
            "never_blocks", sev,
            f"step {step} declares it READS step {', '.join(missing)}'s output "
            f"(`required_inputs.from`) but declares blocks_on="
            f"{graph.blocks_on.get(step, [])}, whose transitive ancestry is "
            f"{sorted(ancestry) or '{}'} — so the ordering guard in "
            f"flow_step_execution_coverage_check cannot red this step when "
            f"{missing[0]} FAILs, and this clause's PASS is uncontradictable "
            f"by the very input it audits", repro)

    if external and not intra:
        return ProbeResult(
            "never_blocks", GUARDED,
            f"step {step}'s only declared input producer(s) {external} name no "
            f"step this flow declares, so they are inputs from outside the "
            f"flow — no `blocks_on` edge to them is possible and this probe "
            f"cannot establish a lie here", repro)

    return ProbeResult("never_blocks", CLEAN,
                       f"every declared input producer {intra} is in step "
                       f"{step}'s transitive blocks_on ancestry", repro)


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


# ------------------------------------------------- SHAPE 11: path spelling
#: A count beside a population word — the same vocabulary `_ZERO_POP` uses,
#: but for ANY number rather than only zero. `probe_path_spelling` compares
#: these across spellings: two runs of the same gate over the SAME directory
#: that report different populations have made the answer a function of how
#: the caller typed the path.
_POP_COUNT = re.compile(
    r"\b(\d+)\s+(run|cell|file|report|net|pin|gate|check|document|doc|entry|"
    r"entries|segment|sample|corner|step|instance|point|library|librar|block|"
    r"tree|module|clause)s?\b", re.I
)


def _bare_caller_paths(tree: "ast.Module") -> set:
    """Names bound DIRECTLY to a path the caller typed, with nothing appended.

    The distinction `probe_depth_pinned_walk` turns on. `corpus` in
    `def _published_run_trees(corpus: Path)` is one: whatever the caller passed
    IS the root, so a fixed-depth pattern under it is measured from the
    caller's phrasing. `analog_dir = _pl.analog_dir(project)` is NOT one: the
    program APPENDS a known anchor, so `phase3/analog/*/spec.json` means the
    same thing however the project was spelled.

    Conservative in the forgiving direction: any construction at all — a `/`
    append, `.parent`, `.joinpath`, or a call other than `Path`/`str` —
    disqualifies the name, so a constructed anchor is never accused.
    """
    constructed: set = set()
    candidates: set = set()

    def _is_construction(node: Any) -> bool:
        for n in ast.walk(node):
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                return True
            if isinstance(n, ast.Attribute) and n.attr in (
                    "parent", "parents", "joinpath", "with_name", "with_suffix"):
                return True
            if isinstance(n, ast.Call):
                fn = n.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else "")
                if name not in ("Path", "str", "resolve", "absolute", "expanduser"):
                    return True
        return False

    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = fn.args
            for a in (list(args.posonlyargs) + list(args.args)
                      + list(args.kwonlyargs)):
                candidates.add(a.arg)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        targets = {t.id for t in n.targets if isinstance(t, ast.Name)}
        if _is_construction(n.value):
            constructed |= targets
            continue
        leaves = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
        if leaves & {"argv", "args", "sys"} or any(
                isinstance(x, ast.Attribute) and x.attr == "argv"
                for x in ast.walk(n.value)):
            candidates |= targets
    return candidates - constructed


def _glob_root_name(call: "ast.Call") -> Optional[str]:
    """The name the walk is rooted at, seeing THROUGH a `Path(...)` wrapper.

    `Path(base).glob(...)` is rooted at `base`, not at `Path`. Answering `Path`
    would silently decline every wrapped root — a discount nobody could audit,
    which is the shape this file exists to find.
    """
    cur: Any = call.func
    if isinstance(cur, ast.Attribute):
        cur = cur.value
    while True:
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name) \
                and cur.func.id in ("Path", "str") and cur.args:
            cur = cur.args[0]
        elif isinstance(cur, ast.Subscript):
            cur = cur.value
        else:
            break
    return cur.id if isinstance(cur, ast.Name) else None


def probe_depth_pinned_walk(cl: Clause) -> ProbeResult:
    """P7 -- is its population pinned to a depth the caller has to guess?
    (vibe-ic#1025, SHAPE 11)

    STATIC. `step_internal_fail_bubble_up_check` searched
    `corpus.glob("*/clean_run_*")`, which matches run trees exactly ONE level
    below whatever the caller passed. Measured at the commit that repaired it,
    on ONE tree at ONE commit asking ONE question:

        --corpus benchmark-data      ->  0 tree(s),  VACUOUS_PASS, rc 2
        --corpus benchmark-data/ic   -> 13 tree(s),  5 unacknowledged FAILs

    Five real failures were never hidden. They were never looked at, because
    the sweep's population was a function of how many path components somebody
    typed — and it refused HONESTLY about examining nothing, which is what made
    it survive. `rglob` makes the two invocations agree by construction rather
    than by the caller remembering the right depth.

    THE RULE IS WHERE THE PATTERN IS ANCHORED, and both halves are load-bearing:

      * the pattern's FIRST component is a wildcard and is not `**` — "some
        directory whose name I do not know, exactly one level down". A pattern
        like `reports/*.json` is anchored: it names the directory, so its depth
        is a fact about the layout, not about the caller.
      * the walk is rooted at a BARE caller path — a parameter, or a name bound
        straight from `argv`/`args` with nothing appended. This is the half
        that decides, and it is why the probe reports what it reports.

    MEASURED over all 136 clauses: 6 leading-wildcard globs exist, and ALL SIX
    are rooted at a CONSTRUCTED anchor (`analog_dir = _pl.analog_dir(project)`,
    `_pl.sim_dir(proj).parent / "sim_professional"`). The flow declares that
    same one-level shape itself — `phase3/analog/*/spec.json` is a
    `required_outputs` entry — so their depth is the layout's contract and not
    the caller's phrasing. Scoring them would have been six false positives on
    a rule that is really about the root.

    So this probe reports ZERO on the current tree, and the test that makes
    that believable is the one that restores the pre-#1025 source in place and
    watches it fire.
    """
    src = PROGRAMS / f"{cl.program}.py"
    repro = (f"python3 -c \"import ast;…\" over programs/{cl.program}.py — find "
             f"every glob whose FIRST pattern component is a wildcard and ask "
             f"whether its root is a bare caller-supplied path")
    if not src.is_file():
        return ProbeResult("depth_pinned_walk", NA, "program not found", repro)
    try:
        tree = ast.parse(src.read_text(errors="replace"))
    except SyntaxError as exc:
        return ProbeResult("depth_pinned_walk", SUSPECT,
                           f"cannot parse, so cannot answer: {exc}", repro)

    bare = _bare_caller_paths(tree)
    pinned: List[str] = []
    anchored: List[str] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "glob"):
            continue
        if not (n.args and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)):
            continue
        pat = n.args[0].value
        head = pat.split("/")[0]
        if "/" not in pat or head == "**" or not any(c in head for c in "*?["):
            continue
        root = _glob_root_name(n)
        where = f"{root}.glob({pat!r}) (line {n.lineno})"
        (pinned if root in bare else anchored).append(where)

    if pinned:
        sev = LIAR if cl.blocking else SUSPECT
        return ProbeResult(
            "depth_pinned_walk", sev,
            f"{len(pinned)} fixed-depth walk(s) rooted at a BARE caller-supplied "
            f"path, so the population is a function of how many path components "
            f"the caller typed and a shallower or deeper spelling of the same "
            f"corpus reaches nothing: {', '.join(pinned[:3])}", repro)
    if anchored:
        return ProbeResult(
            "depth_pinned_walk", CLEAN,
            f"{len(anchored)} fixed-depth walk(s), all rooted at an anchor the "
            f"program CONSTRUCTS rather than at what the caller typed, so the "
            f"depth is the layout's contract: {', '.join(anchored[:2])}", repro)
    return ProbeResult("depth_pinned_walk", CLEAN, "no fixed-depth walk", repro)


def _materialise(patterns: List[str], root: Path) -> int:
    """Turn the flow's declared path patterns into real files under `root`.

    `probe_path_spelling` needs a tree with a POPULATION in it: two spellings of
    an empty directory agree trivially, and an agreement over nothing is not
    evidence of anything. What to put there is read from the same YAML the rest
    of the census reads — the step's own `required_outputs` — so the tree is
    the one the FLOW says this step operates on, not one this file invented.
    """
    made = 0
    for pattern in patterns:
        for alt in str(pattern).split(" OR "):
            rel = alt.strip().lstrip("/")
            if not rel or rel.startswith(".."):
                continue
            concrete = rel.replace("**", "d").replace("*", "x").replace("?", "x")
            if any(c in concrete for c in "[]"):
                continue
            target = root / concrete
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_text("{}\n" if target.suffix == ".json" else "\n")
                    made += 1
            except OSError:
                continue
    return made


#: How the same directory can be spelled. Each is a real thing a caller types,
#: and every one of them names the SAME directory as `.` when the process cwd
#: is that directory — so any disagreement between them is a property of the
#: gate, not of the tree.
SPELLINGS: List[Tuple[str, str]] = [
    ("dot_slash", "./"),
    ("absolute", "{abs}"),
    ("absolute_trailing_slash", "{abs}/"),
    ("up_and_back", "../{base}"),
    ("through_a_symlink", "../{link}"),
]


def probe_path_spelling(cl: Clause, sandbox: Path,
                        variants: int = len(SPELLINGS)) -> ProbeResult:
    """P8 -- spell the same directory differently; does the answer change?
    (SHAPE 11)

    The flow always types `.`, so `.` is the only spelling anybody has ever
    measured. Every other caller — a runner, a corpus sweep, a human pasting an
    absolute path, a CI job whose workspace is a symlink — types one of the
    others, and gets whatever this probe finds.

    DELIBERATELY, THE CWD NEVER MOVES. Only the ARGUMENT changes, and every
    argument names the directory the process is already sitting in. That
    removes the one confound that would make this probe useless: a gate writing
    `reports/x.json` relative to cwd would otherwise appear to "change its
    answer" when it had only changed where it put its report. With cwd pinned,
    a disagreement can only come from how the gate resolved the path it was
    handed.

    What is compared is the VERDICT and the POPULATION: the exit code, and every
    `<number> <population-word>` the gate printed. The gate's own echo of the
    path it was given is normalised out first — a gate quoting its argument back
    is not a gate that disagreed with itself.

    COVERAGE IS BOUNDED AND THE BOUND IS PRINTED. This probe costs one extra
    subprocess per spelling per clause, which is the most expensive thing in
    this file by a wide margin. Clauses that take no project path at all are
    scored N/A rather than silently skipped, and the summary prints how many —
    a probe that quietly drops a third of its population reports a confident
    number about a sweep it never ran.
    """
    parts = cl.cmd.split()
    repro = (f"cd <tree> && python3 programs/{cl.program}.py . ; then the SAME "
             f"tree as ./ , as $PWD , as $PWD/ , as ../<base> , via a symlink")
    if "." not in parts[1:]:
        return ProbeResult(
            "path_spelling", NA,
            "the clause passes no project path — nothing to spell differently",
            repro)

    def _signature(rc: int, out: str, spelling: str) -> Tuple:
        norm = out.replace(str(sandbox.resolve()), "<P>").replace(str(sandbox), "<P>")
        norm = norm.replace(spelling, "<P>")
        return rc, tuple(sorted(f"{m[0]} {m[1].lower()}" for m in _POP_COUNT.findall(norm)))

    base_rc, base_out = _run(cl.cmd, sandbox)
    if base_rc in (124, 127):
        return ProbeResult("path_spelling", NA,
                           "baseline invocation did not run", repro)
    base_sig = _signature(base_rc, base_out, ".")

    link = sandbox.parent / f"{sandbox.name}__link"
    try:
        if not link.exists():
            link.symlink_to(sandbox, target_is_directory=True)
    except OSError:
        pass

    for name, template in SPELLINGS[:variants]:
        spelling = template.format(abs=str(sandbox.resolve()),
                                   base=sandbox.name, link=link.name)
        if name == "through_a_symlink" and not link.is_symlink():
            continue
        cmd = " ".join(spelling if tok == "." else tok for tok in parts)
        rc, out = _run(cmd, sandbox)
        if rc in (124, 127):
            continue
        sig = _signature(rc, out, spelling)
        if sig != base_sig:
            sev = LIAR if cl.blocking else SUSPECT
            what = ("exit code" if sig[0] != base_sig[0] else "population")
            return ProbeResult(
                "path_spelling", sev,
                f"the SAME directory, spelled `{spelling}` instead of `.` with "
                f"the cwd unmoved, changed the {what}: rc {base_rc}->{rc}, "
                f"population {list(base_sig[1])[:3]}->{list(sig[1])[:3]} — the "
                f"answer is a function of how the caller typed the path, not of "
                f"what is in the tree ({name})", repro)
    return ProbeResult("path_spelling", CLEAN,
                       f"{min(variants, len(SPELLINGS))} spelling(s) of the same "
                       f"directory, same rc and same population", repro)
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

# ------------------------------------------------- corpus, tracing, mutation
# P6 and P9 cannot be answered on an empty directory or a skeleton. Both ask
# what a gate does with a REAL artefact, so both need a populated tree and both
# need to know which files the gate actually touched. That is one shared
# apparatus and it is built here.
#
# WHY A TRACER AND NOT STATIC ANALYSIS
# ------------------------------------
# The flow HAS a declared producer/consumer relation and `flow_compliance_check`
# already owns it (`_flow_command_input_atoms` / `_flow_path_atoms` /
# `_flow_paths_meet`, the vibe-ic#776 "declared-dependency relation"). Asking P9
# of that relation was the first thing tried, and MEASURED IT RETURNS ZERO: of
# 136 clauses, exactly 0 program clauses name, positionally, a path their own
# step declares producing. Only 6 clauses carry any positional path atom at all.
#
# That zero is not a clean bill of health, it is the wrong population — the same
# error #1054 found in the selector probe, which "could not have found its own
# founding defect" because the defect lived in a tree it never scanned. The
# cycles are in what the programs ACTUALLY OPEN, which the flow never declares.
# So the census observes it: every gate runs once with `io.open`/`os.open`
# instrumented, and the graph is built from the syscalls, not from the YAML.
#
# THE TRACER'S OWN FAILURE MODE, AND THE CONTROL FOR IT
# ----------------------------------------------------
# `sitecustomize` is imported by `site` only if it is the FIRST one on the path.
# A host with its own `sitecustomize` earlier on `PYTHONPATH` silently wins, the
# log stays empty, and every trace-derived probe reports a confident CLEAN over
# a population it never observed. So the tracer's first act is to write a
# liveness marker, and a trace with no marker is scored `N/A` and said out loud —
# never CLEAN. "What would this look like if it were broken?" must not have the
# same answer as "what does it look like when it is fine".
_TRACE_MARKER = "!\tTRACER_LOADED"

_TRACER_SRC = r'''
"""Written by liar_census into a scratch dir and put FIRST on PYTHONPATH.

Records every open() of a path inside the project under test, in order, with
its direction. Order is the load-bearing part: a gate that READS a path before
it WRITES it consumed a PREVIOUS run's artefact; one that reads it after is
reading back what it just produced, which is a different (and honest) thing.
"""
import builtins
import io
import os

_log = os.environ.get("LIAR_TRACE")
_root = os.path.abspath(os.environ.get("LIAR_TRACE_ROOT", "."))

if _log:
    _f = open(_log, "a", buffering=1)
    _f.write("!\tTRACER_LOADED\n")

    def _rec(path, write):
        if isinstance(path, bytes):
            return
        try:
            p = os.path.abspath(path)
            if not (p == _root or p.startswith(_root + os.sep)):
                return
            _f.write(("w\t" if write else "r\t") + os.path.relpath(p, _root) + "\n")
        except Exception:
            return

    _real_open = io.open

    def _traced_open(file, mode="r", *a, **k):
        if isinstance(file, (str, os.PathLike)):
            _rec(os.fspath(file),
                 isinstance(mode, str) and any(c in mode for c in "wax+"))
        return _real_open(file, mode, *a, **k)

    # AN INSTANCE, NOT A BARE FUNCTION — and the difference is load-bearing.
    #
    # `sitecustomize` runs at interpreter startup, BEFORE `pathlib` is imported.
    # `pathlib` then executes `class _NormalAccessor: open = io.open`, capturing
    # whatever `io.open` is at that moment — i.e. this shim.
    #
    # The substitution is not type-neutral. `io.open` is a C builtin and is NOT
    # a descriptor; a Python function IS one. As a class attribute the bare
    # function therefore BINDS, so `self._accessor.open(self, mode, ...)`
    # arrives as `_traced_open(accessor, path, mode, ...)`: `file` gets the
    # accessor and `mode` gets a PosixPath, raising
    #     TypeError: open() argument 'mode' must be str, not PosixPath
    # on EVERY pathlib read inside a traced program.
    #
    # That is worse than a crash. The tracer still loads — `trace.log` carries
    # `!\tTRACER_LOADED` — so the liveness marker says the instrument is live
    # while the instrument destroys its own subject, and the probes then score a
    # real zero (`0 written path(s), 0 producer->consumer edge(s)`). A probe that
    # changes what it measures and reports the change AS the measurement is the
    # exact shape this census exists to find.
    #
    # An instance of a `__call__` class is not a descriptor, so it does not bind
    # and the arguments arrive as written. Verified on CPython 3.10.12; note
    # `_NormalAccessor` was removed in 3.11, so a newer interpreter hides this
    # rather than fixing it — which is why it is pinned here explicitly.
    class _TracedOpen:
        def __call__(self, file, mode="r", *a, **k):
            return _traced_open(file, mode, *a, **k)

    _shim = _TracedOpen()
    io.open = _shim
    builtins.open = _shim

    _real_os_open = os.open

    def _traced_os_open(path, flags, *a, **k):
        if isinstance(path, (str, os.PathLike)):
            _rec(os.fspath(path),
                 bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)))
        return _real_os_open(path, flags, *a, **k)

    os.open = _traced_os_open
'''


def make_tracer(where: Path) -> Path:
    """Materialise the tracer and hand back the dir to prepend to PYTHONPATH."""
    where.mkdir(parents=True, exist_ok=True)
    (where / "sitecustomize.py").write_text(_TRACER_SRC, encoding="utf-8")
    return where


def _run_traced(cmd: str, project: Path, tracer: Path, timeout: int
                ) -> Tuple[int, str, Optional[List[Tuple[str, str]]]]:
    """`_run`, plus the ordered list of project-relative file accesses.

    Returns `events=None` when the tracer did not load — the caller must score
    that `N/A`, never CLEAN.
    """
    log = tracer / "trace.log"
    log.write_text("", encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "LIAR_TRACE": str(log), "LIAR_TRACE_ROOT": str(project.resolve()),
           "PYTHONPATH": os.pathsep.join(
               [str(tracer)] + ([os.environ["PYTHONPATH"]]
                                if os.environ.get("PYTHONPATH") else []))}
    try:
        proc = subprocess.run(_argv_for(cmd, project), cwd=str(project),
                              capture_output=True, text=True, timeout=timeout, env=env)
        rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "<TIMEOUT>", None
    except OSError as exc:
        return 127, f"<NOT RUNNABLE: {exc}>", None
    raw = log.read_text(errors="replace").splitlines()
    if _TRACE_MARKER not in raw:
        return rc, out, None
    events = [(ln[0], ln[2:]) for ln in raw
              if len(ln) > 2 and ln[0] in "rw" and ln[1] == "\t"]
    return rc, out, events


def declared_atoms(cl: Clause) -> List[str]:
    """The path patterns the FLOW says this clause's step must deliver.

    Split on the flow's own ` OR ` alternation by the same helper
    `flow_compliance_check` uses, so the census reads these strings exactly as
    the thing that actually resolves them does. Imported, never reimplemented —
    #1054's rule, for #1054's reason.
    """
    try:
        _plugin_on_path()
        from flow_compliance_check import _flow_path_atoms  # noqa: PLC0415
    except Exception:                                          # pragma: no cover
        return [a.strip() for e in cl.step_outputs for a in str(e).split(" OR ")
                if a.strip() and a.strip() != "."]
    return _flow_path_atoms(cl.step_outputs)


def declared_entries(cl: Clause) -> List[List[str]]:
    """The step's `required_outputs`, one list of ALTERNATIVES per entry.

    `declared_atoms` flattens the flow's ` OR ` notation, which is right for
    "is this path declared" and WRONG for "is this path load-bearing". An entry
    spelled `a.rpt OR b.json` says the step must deliver ONE of them, so taking
    the content out of `b.json` while `a.rpt` still carries it removes nothing
    the flow asked for.

    Found by hand-adjudicating this probe's own step-9 finding, which sits on
    exactly such an entry (`phase2/stage2/synth/area.rpt OR
    phase2/stage2/synth/stats.json`). That finding SURVIVES — `area.rpt` does
    not exist on the root, so `stats.json` is the entry's only satisfier — but
    it would not have on a root that produced both, and without this the census
    would have had no way to tell the two cases apart.
    """
    out: List[List[str]] = []
    for entry in cl.step_outputs:
        atoms = declared_atoms(Clause(step=cl.step, kind=cl.kind, cmd=cl.cmd,
                                      program=cl.program, step_outputs=[entry]))
        if atoms:
            out.append(atoms)
    return out


def _satisfied_alternative(rel: str, cl: Clause, root: Path) -> Optional[str]:
    """A sibling ALTERNATIVE of `rel`'s entry that still carries content."""
    for entry in declared_entries(cl):
        if len(entry) < 2 or not any(_glob_re(a).match(rel) for a in entry):
            continue
        for alt in entry:
            if _glob_re(alt).match(rel):
                continue
            for hit in sorted(root.glob(alt)):
                try:
                    if hit.is_file() and hit.stat().st_size > 0:
                        return str(hit.relative_to(root))
                except OSError:
                    continue
    return None


def _glob_re(pattern: str) -> "re.Pattern[str]":
    try:
        _plugin_on_path()
        from flow_compliance_check import _flow_glob_re  # noqa: PLC0415
        return _flow_glob_re(pattern)
    except Exception:                                          # pragma: no cover
        return re.compile(re.escape(pattern).replace(r"\*\*", ".*")
                          .replace(r"\*", "[^/]*") + "$")


def discover_corpus_roots(corpus: Path, clauses: List[Clause],
                          limit: int, scanned_cap: int = 4000) -> List[Tuple[Path, int]]:
    """Populated project roots, found by STRUCTURE — never a path list.

    A directory is a candidate when one of its own children is named by the
    first segment of a pattern the FLOW declares (`phase1/`, `reports/`, …), so
    the shape of a run root is read out of `required_outputs` and would follow
    the flow if the layout were renamed. Candidates are then SCORED by how many
    declared output atoms actually resolve under them, and the best `limit` are
    used.

    vibe-ic#1025 is why the walk is unbounded in depth and the count is printed:
    that `--corpus` sweep "reached NOTHING unless the caller typed the right
    path depth", and refused honestly about it — which is better than this
    census would have managed, because a corpus probe that reaches nothing
    reports CLEAN unless somebody makes it refuse.
    """
    atoms = sorted({a for cl in clauses for a in declared_atoms(cl)})
    prefixes = {a.split("/")[0] for a in atoms if "/" in a and "*" not in a.split("/")[0]}
    if not corpus.is_dir() or not prefixes:
        return []
    scored: List[Tuple[Path, int]] = []
    scanned = 0
    stack = [corpus]
    while stack and scanned < scanned_cap:
        cur = stack.pop()
        try:
            kids = [e for e in os.scandir(cur) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        scanned += 1
        names = {e.name for e in kids}
        if names & prefixes:
            n = sum(1 for a in atoms if next(cur.glob(a), None) is not None)
            if n:
                scored.append((cur, n))
        stack.extend(Path(e.path) for e in kids)
    scored.sort(key=lambda t: (-t[1], str(t[0])))
    return scored[:limit]


@dataclass
class Traced:
    """One clause's baseline behaviour on a pristine copy of a corpus root."""
    rc: int
    out: str
    events: Optional[List[Tuple[str, str]]]

    @property
    def reads(self) -> List[str]:
        return [p for m, p in (self.events or []) if m == "r"]

    @property
    def writes(self) -> List[str]:
        return [p for m, p in (self.events or []) if m == "w"]

    def reads_before_writing(self, path: str) -> bool:
        """Did it consume `path` BEFORE producing it in this invocation?

        The whole discriminator for P9. Reading after writing is a read-back of
        a value this run produced; reading before is inheriting the PREVIOUS
        run's artefact — including, when the gate is its own producer, its own
        last verdict.
        """
        seq = [m for m, p in (self.events or []) if p == path]
        return "r" in seq and (("w" not in seq) or seq.index("r") < seq.index("w"))


@dataclass
class CorpusCtx:
    """Everything the populated-tree probes share for one corpus root."""
    root: Path
    tmp: Path
    tracer: Path
    timeout: int
    budget: int
    notes: List[str]
    #: step id -> verdict on the UNMUTATED tree, straight from the consumer
    base_status: Dict[str, str] = field(default_factory=dict)
    #: (subject, mutation) -> the same map with that mutation applied. Keyed by
    #: the mutation and not the clause: one mutation of one file is one tree,
    #: whichever clause asked about it.
    authority: Dict[Tuple[str, str], Optional[Dict[str, str]]] = field(default_factory=dict)
    sib_cache: Dict[Tuple[str, str, str], Optional[str]] = field(default_factory=dict)
    by_step: Dict[str, List[Clause]] = field(default_factory=dict)


def _flow_step_status(project: Path, tmp: Path, timeout: int) -> Optional[Dict[str, str]]:
    """What verdict does the FLOW record for each step over this tree?

    THE CONSUMER IS THE AUTHORITY AND IT IS ASKED, NOT MODELLED. #1054's
    finding was that scoring a refusal by its exit code alone was the probe
    "reading a verdict off prose without asking what consumes it"; the same
    trap is one step further along here. Emptying a declared artefact and
    watching the GATE stay green does not establish that the FLOW stayed green:
    `flow_compliance_check` owns tiers the gate never sees, and one of them is
    exactly this question —

        EVIDENCE_MISSING (#433): verdict artifact(s) reference evidence that
        does not exist or is empty — a PASS nothing substantiates is not a PASS

    MEASURED, and it is why this call exists: on
    `benchmark-data/ic/spm/v1.10.18_sky130A`, emptying `reports/phase3/ir_drop.json`
    leaves BOTH of step 24's gate clauses at rc 0, and the step still moves
    PASS-VOIDED -> FAIL. A version of this probe that stopped at the gate scored
    that clause LIAR. It is not one, and the census had produced its own false
    positive on its first real root.
    """
    out = tmp / f"fcc_{abs(hash(str(project)))}.json"
    try:
        subprocess.run(
            [sys.executable, str(PROGRAMS / "flow_compliance_check.py"), ".",
             "--json", str(out)],
            cwd=str(project), capture_output=True, text=True, timeout=max(timeout, 300),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        doc = json.loads(out.read_text(errors="replace"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    steps = doc.get("steps")
    if not isinstance(steps, list):
        return None
    return {str(s.get("id")): str(s.get("status")) for s in steps if isinstance(s, dict)}


#: Verdict tiers in which the flow is WAVING THE STEP THROUGH. A mutation that
#: leaves the step in one of these, unchanged, was seen by nothing at all.
_PASSING_TIERS = {"PASS", "PASS-STRUCTURAL", "WARN"}

#: Tiers where THIS GATE'S rc is not what decides the step: it never ran
#: (`SKIPPED-CONDITION` — #1051's `[condition]` guard, arriving from the
#: consumer this time), a human excused it (`WAIVED`), its declared outputs did
#: not resolve so the verdict was never read (`MISSING` — #1051's
#: `[required_outputs]` guard, likewise), or the gate itself disclosed vacuity
#: and the flow recorded that tier (`VACUOUS_PASS` — #1054's consumer channel).
#: A blind ruler behind any of these certifies nothing, so the census declines.
#:
#: `PASS_VOIDED_BY_DEPENDENCY` is deliberately NOT here, and the distinction is
#: the one that decides whether this probe reaches the corpus at all. A voided
#: step is one whose gate DID return PASS and which an upstream failure then
#: voided — the ruler was consulted and answered, so its blindness is measured;
#: only the consequence is missing. That is the SUSPECT cap below, not a
#: discount. Sorting it as a discount put 9 of 63 steps on the spm root out of
#: reach for no reason the measurement supported.
_GATE_NOT_DECIDING = {"SKIPPED-CONDITION", "WAIVED", "MISSING",
                      "VACUOUS_PASS", "NOT-APPLICABLE", "N/A"}


def probe_ruler_blind(cl: Clause, tr: Traced, ctx: CorpusCtx) -> ProbeResult:
    """P6 — EMPTY an artefact the gate declares, and watch it stay green.

    "The ruler cannot measure the thing it says it measures."

    WHY EMPTYING AND NOT DELETING, and this is the whole design
    ----------------------------------------------------------
    Deleting is already caught, one layer up and by something else:
    `flow_compliance_check` resolves `required_outputs` FIRST and ALL-of-N
    (`_glob_first`), so a step whose declared artefact is gone is MISSING before
    its gate verdict is ever read. That is #1051's `[required_outputs]` guard,
    and it covers deletion completely.

    MEASURED on the published root `benchmark-data/ic/spm/v1.10.18_sky130A`:
    75 of 75 declared-output atoms that resolve there resolve to EXACTLY ONE
    file. Deleting any one of them therefore un-resolves its pattern and the
    presence check catches it — every time, for every atom. So "delete it and
    see" is a question the flow already answers, and asking it again would have
    produced 75 findings that are all somebody else's PASS.

    Emptying is the question nobody asks. `_glob_first` answers about DIRECTORY
    ENTRIES; a zero-byte file is an entry. The presence tier stays green and the
    step's own gate is the only ruler left standing. The repo already knows this
    seam exists — `gds_substance_check`, `chip_gds_canonical_real_file_check`,
    and the field on `StepResult` recording "which question this step's
    `required_outputs` verdict answers" are all it — but nothing has ever swept
    it.

    THE SUBJECT IS PER-CLAUSE AND IT IS EARNED TWICE
    -----------------------------------------------
    A subject is a file that is BOTH (a) matched by an atom of the step's
    declared `required_outputs` — the flow says this step must deliver it — and
    (b) actually OPENED FOR READING by this clause in the green baseline run.
    Both halves are needed. (a) alone over-attributes: step D1 declares 14 L-docs
    and carries 24 clauses, and `l7_debug_access_grounding_check` is not lying
    when emptying `L11_OTP_CONTENT.json` does not move it. (b) alone is not the
    flow's claim about the step. Together they are exact: this clause opened this
    declared artefact, the artefact became empty, and the clause still says PASS.

    FAIL-SAFE CLASSES, all structural, all measured rather than assumed
    ------------------------------------------------------------------
    * PRODUCER — the file is non-empty again after the run. The clause rewrote
      what it was handed, so it is that artefact's producer and not its ruler.
      (This is the P4 producer class arriving from the other direction.)
    * MEASURED SIBLING — some other clause in the SAME step's gate turns red on
      the same mutation. The gate is an `all_of`, so the conjunction fails there
      and this clause's rc 0 cannot wave anything through. #1051 derived this
      guard from DECLARED `files_exist` siblings; here it is not declared, it is
      run, which is strictly stronger: it catches a sibling that objects on
      substance rather than on presence.
    * ALREADY EMPTY — a zero-byte file cannot be emptied. Skipped and counted,
      never scored, because a mutation that changes nothing proves nothing.
    * THE CONSUMER SAW IT — the authority (`_flow_step_status`) records a
      different verdict for this step on the mutated tree. This is the one that
      matters and it is the one a gate-only probe cannot have: see
      `_flow_step_status` for the root on which it turned this census's own
      first real finding into its own first false positive.
    """
    root, tmp, tracer = ctx.root, ctx.tmp, ctx.tracer
    timeout, budget, notes = ctx.timeout, ctx.budget, ctx.notes
    siblings = [c for c in ctx.by_step.get(cl.step, []) if c.program != cl.program]
    sib_cache = ctx.sib_cache
    if tr.events is None:
        return ProbeResult("ruler_blind", NA, "no trace — the tracer did not load", "")
    if tr.rc != 0:
        return ProbeResult("ruler_blind", NA,
                           f"not green on this corpus root (rc={tr.rc}); a ruler that "
                           f"is already objecting cannot be shown blind here", "")
    # Cheapest guard first. THE FINDING IS THAT THE VERDICT DOES NOT MOVE, not
    # that it is green: a gate blind to its declared artefact is blind whatever
    # tier the step happens to sit in on this particular root. What the tier
    # decides is SEVERITY. But where the gate's rc is not what the step turns
    # on at all — it never ran, it was waived, it was already voided upstream,
    # or it disclosed vacuity — a blind ruler certifies nothing and the census
    # declines instead of counting it.
    before = ctx.base_status.get(cl.step)
    if ctx.base_status and before in _GATE_NOT_DECIDING:
        return ProbeResult(
            "ruler_blind", GUARDED,
            f"the flow records step {cl.step} as {before} on the UNMUTATED root, so "
            f"this clause's rc is not what the step turns on and a blindness here "
            f"certifies nothing", "")
    atoms = declared_atoms(cl)
    pats = [_glob_re(a) for a in atoms]
    subjects, already_empty = [], 0
    for rel in dict.fromkeys(tr.reads):
        if not any(p.match(rel) for p in pats):
            continue
        f = root / rel
        try:
            if not f.is_file():
                continue
            if f.stat().st_size == 0:
                already_empty += 1
                continue
        except OSError:
            continue
        subjects.append(rel)
    if already_empty:
        notes.append(f"{cl.program}: {already_empty} declared subject(s) already "
                     f"zero-byte on this root — not mutable, not scored")
    if not subjects:
        return ProbeResult("ruler_blind", NA,
                           "reads nothing this step declares producing, so there is "
                           "no declared artefact to empty under it", "")
    dropped = max(0, len(subjects) - budget)
    if dropped:
        notes.append(f"{cl.program}: {dropped} of {len(subjects)} declared subject(s) "
                     f"NOT mutated (--max-mutations={budget}) — coverage is bounded, "
                     f"not complete: {', '.join(sorted(subjects)[budget:][:3])}")
    worst: Optional[ProbeResult] = None
    for rel in sorted(subjects)[:budget]:
        alt = _satisfied_alternative(rel, cl, root)
        if alt:
            if worst is None:
                worst = ProbeResult(
                    "ruler_blind", GUARDED,
                    f"{rel} is one ALTERNATIVE of a ` OR ` required_outputs entry and "
                    f"{alt} still carries content, so taking this file's content away "
                    f"removes nothing the flow asked the step to deliver", "")
            continue
        for label, payload in _mutations(root / rel):
            repro = (f"cp -r {root.name} /tmp/t && printf '%s' {payload!r} > /tmp/t/{rel}"
                     f" && cd /tmp/t && python3 programs/{cl.program}.py "
                     f"{' '.join(cl.cmd.split()[1:])}; echo rc=$?")
            work = _fresh(root, tmp)
            try:
                (work / rel).write_text(payload, encoding="utf-8")
                rc, _out, _ev = _run_traced(cl.cmd, work, tracer, timeout)
                rewrote = ((work / rel).is_file()
                           and (work / rel).read_text(errors="replace") != payload)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            if rc != 0:
                if worst is None:
                    worst = ProbeResult("ruler_blind", CLEAN,
                                        f"{rel} {label} turns it rc={rc} — it measures it",
                                        repro)
                continue
            if rewrote:
                if worst is None or worst.verdict == CLEAN:
                    worst = ProbeResult(
                        "ruler_blind", GUARDED,
                        f"stays rc=0 with {rel} {label}, but it REWROTE that file during "
                        f"the run — it is that artefact's producer, not its ruler, so "
                        f"this probe cannot establish a lie here", repro)
                continue

            key = (cl.step, rel, label)
            if key not in sib_cache:
                sib_cache[key] = _sibling_objects(rel, payload, root, tmp, tracer,
                                                  timeout, siblings, notes)
            catcher = sib_cache[key]
            if catcher:
                if worst is None or worst.verdict == CLEAN:
                    worst = ProbeResult(
                        "ruler_blind", GUARDED,
                        f"stays rc=0 with {rel} {label}, but {catcher} — another clause "
                        f"in step {cl.step}'s OWN all_of gate — turns red on the same "
                        f"mutation, so the conjunction fails there and this clause "
                        f"cannot wave it through", repro)
                continue

            # Nothing cheap objected. Only now is the ~6-second authority worth
            # paying for, and it is cached by (SUBJECT, MUTATION) because one
            # mutation of one file yields one tree, whichever clause asked.
            akey = (rel, label)
            if akey not in ctx.authority:
                work = _fresh(root, tmp)
                try:
                    (work / rel).write_text(payload, encoding="utf-8")
                    ctx.authority[akey] = _flow_step_status(work, tmp, timeout)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            after = ctx.authority[akey]
            if after is None or not ctx.base_status:
                notes.append(f"{cl.program}/{rel} [{label}]: the consumer could not be "
                             f"asked (flow_compliance_check produced no step map), so "
                             f"this mutation is UNSCORED rather than scored on the gate "
                             f"alone")
                continue
            # EVERY step, not just this clause's. The claim about to be made is
            # "nothing ANYWHERE reacted", and a check scoped to one step cannot
            # support it -- a later auditor reading this artefact across a step
            # boundary is precisely the #1029 shape the campaign is about. The
            # whole map is already in hand, so the wider check is free and the
            # narrower one would have been the census overclaiming past its own
            # measurement.
            moved = {k: (v, after.get(k)) for k, v in ctx.base_status.items()
                     if after.get(k) != v}
            if moved:
                where = cl.step if cl.step in moved else sorted(moved)[0]
                was, now = moved[where]
                if worst is None or worst.verdict == CLEAN:
                    worst = ProbeResult(
                        "ruler_blind", GUARDED,
                        f"stays rc=0 with {rel} {label} and no sibling conjunct objects, "
                        f"but the CONSUMER moves step {where} {was} -> {now} "
                        f"({len(moved)} step verdict(s) changed); the flow owns tiers "
                        f"this gate never sees (EVIDENCE_MISSING #433 reads emptiness "
                        f"directly), so the artefact is measured — just not here", repro)
                continue
            blind = (f"declares {rel} and READS it, yet with that file {label} this "
                     f"clause stays rc=0, every sibling conjunct in step {cl.step}'s "
                     f"gate stays rc=0, and NOT ONE of the flow's "
                     f"{len(ctx.base_status)} step verdicts moves (step {cl.step} stays "
                     f"{before}) — the file still exists so the presence tier is "
                     f"satisfied, and nothing anywhere in the flow reacted to the "
                     f"artefact this step is required to deliver losing its content")
            if before not in _PASSING_TIERS:
                # Real blindness, unproven consequence. The step is already red
                # for some other reason, so the flow is not waving THIS through
                # on THIS root -- capped at SUSPECT and said, rather than
                # promoted on a severity the measurement does not carry.
                if worst is None or worst.verdict in (CLEAN, GUARDED):
                    worst = ProbeResult(
                        "ruler_blind", SUSPECT,
                        blind + f"; capped at SUSPECT because step {cl.step} is {before} "
                        f"here anyway, so the blindness is measured and its consequence "
                        f"is not", repro)
                continue
            return ProbeResult("ruler_blind", LIAR if cl.blocking else SUSPECT,
                               blind, repro)
    return worst or ProbeResult("ruler_blind", CLEAN,
                                "every declared subject it reads changes its verdict", "")


def _fresh(root: Path, tmp: Path) -> Path:
    """A pristine copy of the corpus root.

    EVERY run gets one. Gates write into the tree they judge — `ir_drop_report_check`
    says so in its own docstring ("evaluating step 24 was read-only ... it now
    creates reports/phase3/ir_drop_signoff.json ... auditing a PUBLISHED
    benchmark-data run therefore dirties the working tree") — so reusing one copy
    across clauses would let clause N-1 seed the evidence clause N reads. That is
    vibe-ic#1029 exactly, and an instrument that reproduces the defect it hunts is
    not an instrument. It also means the census NEVER touches `benchmark-data/`.
    """
    dst = Path(tempfile.mkdtemp(prefix="corpus", dir=str(tmp))) / "proj"
    shutil.copytree(root, dst, symlinks=True)
    return dst


def _mutations(path: Path) -> List[Tuple[str, str]]:
    """Ways to take an artefact's CONTENT away without taking the artefact away.

    TRUNCATION IS TOO BLUNT ON ITS OWN, and finding that out is what this
    function is. The first version of P6 emptied the file to zero bytes and
    nothing else. Calibrated against a real historical positive — the pre-#219
    `transition_coverage_check`, whose fix message is "an absent or HOLLOW
    at-speed ATPG result must never read as a pass" — the red arm came back
    CLEAN, indistinguishable from the repaired gate:

        arm      md5(transition_coverage_check.py)   emptied-to-zero-bytes
        GREEN    ef9d0bf8c1c9419d…                   CLEAN (rc 0 -> 1)
        RED      48bc336894a72177…                   CLEAN (rc 0 -> 1)

    Both "measured" it — because zero bytes is not JSON, so BOTH versions died
    in the parser. A mutation that makes every gate red proves nothing about
    any of them, and a probe calibrated only against a mutation like that would
    have shipped reporting a confident zero.

    So the mutation is derived FROM THE ARTEFACT: a file that parses as JSON is
    replaced with the EMPTY CONTAINER OF ITS OWN TOP-LEVEL TYPE, which still
    parses, still satisfies every presence tier, and carries no measurement.
    That is exactly the "hollow" of #219. Truncation is kept as the second
    mutation, for artefacts that are not JSON at all.

    No schema is assumed and no field name is known — the shape is read off the
    file, so this stays chip-AGNOSTIC and does not rot when a report gains a key.
    """
    out: List[Tuple[str, str]] = []
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict) and doc:
        out.append(("hollowed to {} (still valid JSON, no content)", "{}"))
    elif isinstance(doc, list) and doc:
        out.append(("hollowed to [] (still valid JSON, no content)", "[]"))
    out.append(("emptied to zero bytes", ""))
    return out


_MAX_SIBLINGS = 16


def _sibling_objects(rel: str, payload: str, root: Path, tmp: Path, tracer: Path,
                     timeout: int, siblings: List[Clause],
                     notes: List[str]) -> Optional[str]:
    """The first conjunct in the same step's gate that turns red on this mutation.

    Bounded, and the bound is DISCLOSED: with the cap hit, a `None` means "none
    of the first N objected", not "the gate is blind" — so the cap can only ever
    make the census claim MORE, and the note is what keeps that auditable.
    """
    for i, sib in enumerate(siblings):
        if i >= _MAX_SIBLINGS:
            notes.append(f"step {sib.step}/{rel}: only the first {_MAX_SIBLINGS} of "
                         f"{len(siblings)} sibling conjunct(s) were run for the "
                         f"sibling guard — a guard may have been missed, which would "
                         f"OVERSTATE this finding")
            break
        work = _fresh(root, tmp)
        try:
            (work / rel).write_text(payload, encoding="utf-8")
            rc, _o, _e = _run_traced(sib.cmd, work, tracer, timeout)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if rc not in (0, 124, 127):
            return sib.program
    return None


def probe_self_upstream(cl: Clause, tr: Traced, ctx: CorpusCtx,
                        producers: Dict[str, set], cycle: Optional[List[str]],
                        same_step: set) -> ProbeResult:
    """P9 — is the gate its own upstream?  "It reads a report it wrote itself."

    Every clause's inputs are traced to their producer, and a cycle that returns
    to the clause is the defect: the verdict rests on an artefact the verdict
    produced. The degenerate one-node case is the literal shape — the gate opens
    its own report before it writes it, so what it read is its OWN LAST VERDICT.

    THE DISCRIMINATOR IS ORDER, and it is the fail-safe class
    ---------------------------------------------------------
    A gate that writes its report and then reads it back has read a value THIS
    run produced; nothing was inherited and nothing is circular. A gate that
    reads first consumed the artefact a previous run left behind. Only the
    second is a cycle, and the two are indistinguishable in any set-based view —
    which is why the trace keeps order. `_run_traced` is what makes this
    decidable at all; the flow's declared relation cannot see it (measured: 0).

    LOAD-BEARING OR MERELY PRESENT — the causality arm
    -------------------------------------------------
    A cycle is not automatically a lie: the gate might open the file and ignore
    what it finds. So the cycle is CONFIRMED by mutation rather than asserted
    from the trace — empty the artefact it read-before-writing and re-run. A
    verdict that moves proves the prior artefact was carrying it. A verdict that
    does not is reported SUSPECT and said plainly, not promoted and not dropped.

    A gate that CRASHES on the emptied file is scored SUSPECT too, never LIAR:
    a traceback is a robustness defect, not evidence that the gate was laundering
    its own output, and reading it as the latter would be the census inferring a
    verdict from an exit code it did not understand.
    """
    root, tmp, tracer, timeout = ctx.root, ctx.tmp, ctx.tracer, ctx.timeout
    if tr.events is None:
        return ProbeResult("self_upstream", NA, "no trace — the tracer did not load", "")
    own = [p for p in dict.fromkeys(tr.writes) if tr.reads_before_writing(p)]
    ring = [p for p in dict.fromkeys(tr.reads)
            if cycle and (producers.get(p, set()) & set(cycle)) - {cl.program}]
    repro = (f"PYTHONPATH=<tracer> LIAR_TRACE=t.log python3 programs/{cl.program}.py "
             f"{' '.join(cl.cmd.split()[1:])} — then read t.log in order")
    if not own and not ring:
        readbacks = [p for p in dict.fromkeys(tr.writes)
                     if p in tr.reads and not tr.reads_before_writing(p)]
        if readbacks:
            return ProbeResult("self_upstream", GUARDED,
                               f"reads {readbacks[0]} but only AFTER writing it in the "
                               f"same invocation — a read-back of what this run produced, "
                               f"not an artefact inherited from a previous one", repro)
        return ProbeResult("self_upstream", CLEAN,
                           f"{len(set(tr.reads))} input(s), none produced by itself "
                           f"and none on a cycle back to it", repro)

    rel = (own or ring)[0]
    shape = ("reads its OWN report before writing it" if own else
             f"is on a producer cycle {' -> '.join((cycle or [])[:4])}")
    if own and same_step and producers.get(rel, set()) & same_step:
        return ProbeResult("self_upstream", GUARDED,
                           f"{shape} ({rel}), but the other producer is a clause in step "
                           f"{cl.step}'s own gate — the flow declares them as one "
                           f"conjunction, not evidence crossing a step boundary", repro)

    work = _fresh(root, tmp)
    try:
        (work / rel).write_text("", encoding="utf-8") if (work / rel).is_file() else None
        rc2, out2, _e = _run_traced(cl.cmd, work, tracer, timeout)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if tr.rc != 0:
        return ProbeResult("self_upstream", SUSPECT,
                           f"{shape} ({rel}) — but it is rc={tr.rc} on this root, so "
                           f"nothing was laundered here; the cycle is real and the "
                           f"laundering is unproven", repro)
    if "Traceback (most recent call last)" in out2:
        return ProbeResult("self_upstream", SUSPECT,
                           f"{shape} ({rel}) and CRASHES when that artefact is emptied — "
                           f"a robustness defect, and not evidence that its own prior "
                           f"output was carrying the verdict", repro)
    if rc2 == 0:
        return ProbeResult("self_upstream", SUSPECT,
                           f"{shape} ({rel}), but emptying that artefact does not move "
                           f"the verdict (rc stays 0), so the cycle exists and is not "
                           f"load-bearing on this root", repro)
    sev = LIAR if cl.blocking else SUSPECT
    return ProbeResult("self_upstream", sev,
                       f"{shape} ({rel}) AND its verdict depends on it: rc 0 -> {rc2} "
                       f"when that artefact is emptied — the gate is passing on evidence "
                       f"it produced itself", repro)


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


def _strongly_connected(graph: Dict[str, set]) -> List[List[str]]:
    """Tarjan, iterative. Every component of size > 1 is a producer CYCLE.

    Iterative on purpose: the recursive form blows the stack on a graph this
    census builds from an arbitrary corpus, and a probe that dies on a big
    corpus is a probe that reports nothing on exactly the runs worth sweeping.
    """
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: List[str] = []
    on: set = set()
    out: List[List[str]] = []
    counter = 0
    for start in list(graph):
        if start in index:
            continue
        work: List[Tuple[str, Any]] = [(start, iter(sorted(graph.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        while work:
            v, it = work[-1]
            nxt = next(it, None)
            if nxt is None:
                work.pop()
                if low[v] == index[v]:
                    comp = []
                    while True:
                        u = stack.pop()
                        on.discard(u)
                        comp.append(u)
                        if u == v:
                            break
                    out.append(comp)
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                continue
            if nxt not in index:
                index[nxt] = low[nxt] = counter
                counter += 1
                stack.append(nxt)
                on.add(nxt)
                work.append((nxt, iter(sorted(graph.get(nxt, ())))))
            elif nxt in on:
                low[v] = min(low[v], index[nxt])
    return out


def corpus_pass(clauses: List[Clause], root: Path, tmp: Path, probes: List[str],
                timeout: int, budget: int, notes: List[str]
                ) -> Dict[int, List[ProbeResult]]:
    """The populated-tree phase: one traced baseline per clause, then mutations.

    The baseline pass is shared. P6 needs to know which declared artefacts a
    clause actually opened; P9 needs the read/write ORDER and the cross-program
    producer graph. Both come out of the same run, so the corpus is walked once.
    """
    tracer = make_tracer(tmp / "tracer")
    base: Dict[int, Traced] = {}
    dead = 0
    for i, cl in enumerate(clauses):
        work = _fresh(root, tmp)
        try:
            rc, out, ev = _run_traced(cl.cmd, work, tracer, timeout)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        base[i] = Traced(rc=rc, out=out, events=ev)
        if ev is None and rc not in (124, 127):
            dead += 1
        print(f"  [corpus {i + 1}/{len(clauses)}] {cl.program[:48]:<48} rc={rc} "
              f"r={len(base[i].reads)} w={len(base[i].writes)}",
              file=sys.stderr, flush=True)
    if dead:
        print(f"liar_census: the TRACER DID NOT LOAD for {dead} clause(s) — every "
              f"trace-derived probe is N/A for them, NOT clean. A host sitecustomize "
              f"earlier on PYTHONPATH is the usual cause.", file=sys.stderr)
        notes.append(f"tracer failed to load on {dead} clause(s); their P6/P9 results "
                     f"are N/A and this run UNDERSTATES both probes")

    producers: Dict[str, set] = {}
    consumers: Dict[str, set] = {}
    for i, cl in enumerate(clauses):
        for p in base[i].writes:
            producers.setdefault(p, set()).add(cl.program)
        for p in base[i].reads:
            consumers.setdefault(p, set()).add(cl.program)
    graph: Dict[str, set] = {}
    for path, ws in producers.items():
        for a in ws:
            for b in consumers.get(path, ()):
                if a != b:
                    graph.setdefault(a, set()).add(b)
    cycles = [c for c in _strongly_connected(graph) if len(c) > 1]
    by_prog_cycle = {p: c for c in cycles for p in c}
    notes.append(f"producer graph on {root}: {len(producers)} written path(s), "
                 f"{sum(len(v) for v in graph.values())} producer->consumer edge(s), "
                 f"{len(cycles)} multi-node cycle(s)")

    by_step: Dict[str, List[Clause]] = {}
    for cl in clauses:
        by_step.setdefault(cl.step, []).append(cl)
    ctx = CorpusCtx(root=root, tmp=tmp, tracer=tracer, timeout=timeout,
                    budget=budget, notes=notes, by_step=by_step)
    if "ruler" in probes:
        # The unmutated arm of every P6 comparison. Without it a step that was
        # ALREADY failing would read as "the mutation changed nothing", which is
        # the census scoring its own missing control as a finding.
        pristine = _fresh(root, tmp)
        try:
            ctx.base_status = _flow_step_status(pristine, tmp, timeout) or {}
        finally:
            shutil.rmtree(pristine, ignore_errors=True)
        if not ctx.base_status:
            notes.append("the consumer (flow_compliance_check) produced no step map on "
                         "the UNMUTATED root, so P6 has no control arm and every subject "
                         "is UNSCORED — this run establishes nothing about P6")
        else:
            waved = sum(1 for v in ctx.base_status.values() if v in _PASSING_TIERS)
            notes.append(
                f"P6 control arm on the unmutated root: {waved} of "
                f"{len(ctx.base_status)} step(s) in a passing tier. Only those can "
                f"carry a LIAR; a step that is FAIL or PASS-VOIDED here is capped at "
                f"SUSPECT (blindness measured, consequence unproven) and one that never "
                f"ran, was waived, was MISSING or disclosed vacuity is GUARDED")
    out: Dict[int, List[ProbeResult]] = {}
    for i, cl in enumerate(clauses):
        got: List[ProbeResult] = []
        if "cycle" in probes:
            got.append(probe_self_upstream(
                cl, base[i], ctx, producers, by_prog_cycle.get(cl.program),
                {c.program for c in by_step.get(cl.step, [])} - {cl.program}))
        if "ruler" in probes:
            got.append(probe_ruler_blind(cl, base[i], ctx))
        out[i] = got
        print(f"  [mutate {i + 1}/{len(clauses)}] {cl.program[:48]:<48} "
              f"{','.join(p.verdict for p in got)}", file=sys.stderr, flush=True)
    return out


def run_census(clauses: List[Clause], probes: List[str], timeout: int,
               graph: Optional[FlowGraph] = None,
               spelling_variants: int = len(SPELLINGS),
               corpus: Optional[Path] = None, corpus_roots: int = 1,
               budget: int = 3, notes: Optional[List[str]] = None,
               ) -> List[ClauseReport]:
    reports: List[ClauseReport] = []
    graph = graph or FlowGraph()
    notes = notes if notes is not None else []
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
            if "blocks" in probes:
                rep.probes.append(probe_never_blocks(cl, graph))
            if "depth" in probes:
                rep.probes.append(probe_depth_pinned_walk(cl))
            if "spelling" in probes:
                # a POPULATED tree, seeded from what the flow says this step
                # writes: two spellings of an empty directory agree trivially.
                sp = Path(tmp) / f"sp{i}"
                shutil.copytree(skeleton, sp)
                _materialise(cl.step_outputs, sp)
                rep.probes.append(probe_path_spelling(cl, sp, spelling_variants))
                shutil.rmtree(sp, ignore_errors=True)
            if "proxy" in probes:
                rep.probes.extend(probe_proxy_not_property(cl, Path(tmp), i, timeout))
            reports.append(rep)
            print(f"  [{i}/{len(clauses)}] step {cl.step:>4}  {cl.program[:52]:<52} {rep.worst}",
                  file=sys.stderr, flush=True)

        # P6/P9 need a POPULATED tree, so they are a second pass over a real
        # published run root rather than over the empty dir and the skeleton.
        if {"ruler", "cycle"} & set(probes):
            roots = discover_corpus_roots(corpus, clauses, corpus_roots) if corpus else []
            if not roots:
                # A corpus probe that reached nothing must REFUSE, loudly. Left
                # silent it prints CLEAN over a population it never opened, which
                # is the confident zero this whole census exists to prevent.
                where = corpus if corpus else "<none given>"
                msg = (f"NO POPULATED CORPUS ROOT under {where} — the corpus probes "
                       f"scored N/A for every clause and this run establishes NOTHING "
                       f"about P6/P9")
                print(f"liar_census: {msg}", file=sys.stderr)
                notes.append(msg)
                for rep in reports:
                    for name in ("cycle", "ruler"):
                        if name in probes:
                            rep.probes.append(ProbeResult(
                                {"cycle": "self_upstream", "ruler": "ruler_blind"}[name],
                                NA, "no corpus root", ""))
            else:
                for root, score in roots:
                    notes.append(f"corpus root {root} — {score} declared output atom(s) "
                                 f"resolve under it")
                    got = corpus_pass(clauses, root, Path(tmp), probes, timeout,
                                      budget, notes)
                    for i, rep in enumerate(reports):
                        rep.probes.extend(got.get(i, []))
    return reports


<<<<<<< HEAD
ALL_PROBES = ["empty", "prose", "zero", "writes", "selector",
              "blocks", "depth", "spelling", "ruler", "cycle"]
=======
ALL_PROBES = ["empty", "prose", "zero", "writes", "selector", "blocks", "depth", "spelling", "proxy"]
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



#: probes whose N/A is a BOUNDED COVERAGE decision rather than an inapplicable
#: question — every one of these has to be listed, with its reason, or the run
#: reads as coverage it never had.
_BOUNDED = ("pass_without_reading", "content_blind_pass")
>>>>>>> refs/tmp/pr/1071


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flow", type=Path, default=FLOW_YAML)
    ap.add_argument("--probes", default=",".join(ALL_PROBES),
                    help=f"comma-separated subset of {ALL_PROBES}")
    ap.add_argument("--only", action="append", default=[],
                    help="restrict to clauses whose program name contains this (repeatable)")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--spelling-variants", type=int, default=len(SPELLINGS),
                    help=f"how many of the {len(SPELLINGS)} path spellings to "
                         f"try per clause. Lowering it BOUNDS the most "
                         f"expensive probe in this file; whatever is dropped "
                         f"is printed in the summary, never silently")
    ap.add_argument("--corpus", type=Path, default=REPO / "benchmark-data",
                    help="tree of published run roots the ruler/cycle probes mutate "
                         "(COPIED first, never touched in place)")
    ap.add_argument("--corpus-roots", type=int, default=1,
                    help="how many of the best-scoring roots to sweep")
    ap.add_argument("--max-mutations", type=int, default=3,
                    help="declared artefacts emptied per clause; the remainder is "
                         "DISCLOSED in the BOUNDS section, never silently dropped")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    clauses = discover_clauses(args.flow)
    graph = discover_flow_graph(args.flow)
    if args.only:
        clauses = [c for c in clauses if any(o in c.program for o in args.only)]

    if not clauses:
        print("REFUSE — no gate clauses discovered. A census over nothing is not a census.")
        return 2

    probes = [p.strip() for p in args.probes.split(",") if p.strip()]
    variants = max(0, min(args.spelling_variants, len(SPELLINGS)))
    pop = population_report(args.flow)
    print(f"liar_census: {len(clauses)} clause(s) x {len(probes)} probe(s)", file=sys.stderr)
    notes: List[str] = []
    reports = run_census(clauses, probes, args.timeout, graph=graph,
                         spelling_variants=variants, corpus=args.corpus,
                         corpus_roots=args.corpus_roots,
                         budget=args.max_mutations, notes=notes)

    liars = [r for r in reports if r.worst == LIAR]
    suspects = [r for r in reports if r.worst == SUSPECT]
    guarded = [r for r in reports if r.worst == GUARDED]
    # NOT MEASURED AT ALL — every probe that ran on this clause returned N/A.
    # This line was arithmetic before it was a line: CLEAN used to be computed
    # as "everything that is not LIAR/SUSPECT/GUARDED", which quietly folded
    # the unmeasured clauses into the clean count. Running the census with a
    # single probe that scores 10 clauses N/A printed `CLEAN 136` over 126
    # measurements — a census reporting a population it never reached, which is
    # the shape this file exists to find, in this file.
    unmeasured = [r for r in reports if r.worst == NA]
    blocking_liars = [r for r in liars if r.blocking]
    # every discounted probe result, however its clause was finally scored
    discounted = sum(1 for r in reports for p in r.probes if p.verdict == GUARDED)
    clean = (len(reports) - len(liars) - len(suspects)
             - len(guarded) - len(unmeasured))

    print()
    print("=" * 78)
    print(f"LIAR CENSUS — {len(reports)} clause(s), probes: {','.join(probes)}")
    print("=" * 78)
    print(f"  LIAR     {len(liars):>4}   ({len(blocking_liars)} of them BLOCKING)")
    print(f"  SUSPECT  {len(suspects):>4}")
    print(f"  GUARDED  {len(guarded):>4}   ({discounted} probe result(s) declined, listed below)")
    print(f"  CLEAN    {clean:>4}")
    print(f"  N/A      {len(unmeasured):>4}   (every probe returned N/A — NOT measured, "
          f"and deliberately NOT counted clean)")
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

    # WHAT THIS RUN DID NOT REACH. A probe that quietly skips part of its
    # population reports a number about a sweep it never ran, and reads as
    # "covered everything" -- the #1054 finding about the selector probe, which
    # returned a confident zero over a tree it had never scanned. So every
    # unmeasured clause is counted per probe and printed, even when it is zero.
    na = {p: sum(1 for r in reports for x in r.probes
                 if x.probe == p and x.verdict == NA)
          for p in sorted({x.probe for r in reports for x in r.probes})}
    if any(na.values()) or variants < len(SPELLINGS):
        print("-" * 78)
        print("COVERAGE — what this run did NOT measure:")
        for name, count in na.items():
            if count:
                print(f"  {name:<24} {count:>4} of {len(reports)} clause(s) "
                      f"scored N/A (unrunnable, or the probe's question does "
                      f"not apply to that clause's wiring)")
        if variants < len(SPELLINGS):
            dropped = [n for n, _ in SPELLINGS[variants:]]
            print(f"  path_spelling            BOUNDED to {variants} of "
                  f"{len(SPELLINGS)} spellings; NOT tried: {', '.join(dropped)}")
<<<<<<< HEAD

    # WHAT THIS RUN DID NOT COVER. The mutation probes are bounded by
    # construction -- corpus roots, artefacts per clause, siblings per guard --
    # and a bound nobody printed reads exactly like complete coverage. Every
    # truncation, every unmutable subject and every tracer failure lands here.
    if notes:
        print("-" * 78)
        print(f"BOUNDS — {len(notes)} disclosure(s) about what this run did NOT establish:")
        for n in notes:
            print(f"  * {n}")
=======
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
>>>>>>> refs/tmp/pr/1071
        print()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"clauses": len(reports), "probes": probes,
             "liar": len(liars), "suspect": len(suspects),
             "guarded": len(guarded), "declined_probe_results": discounted,
             "clean": clean, "unmeasured": len(unmeasured),
             "blocking_liar": len(blocking_liars),
             "not_measured": na,
             "spelling_variants_tried": variants,
             "spelling_variants_available": len(SPELLINGS),
<<<<<<< HEAD
             "bounds": notes,
=======
             "dropped_probe_results": len(dropped),
>>>>>>> refs/tmp/pr/1071
             "reports": [asdict(r) for r in reports]}, indent=1), encoding="utf-8")

    return 1 if liars else 0


if __name__ == "__main__":
    sys.exit(main())
