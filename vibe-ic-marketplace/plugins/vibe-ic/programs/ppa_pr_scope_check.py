#!/usr/bin/env python3
"""ppa_pr_scope_check.py — the PR review checklist, answered by machine.

ENFORCEMENT: blocking
=====================
rc 1 is a finding about the PR and it REFUSES the merge. `gatekeeper_review`
spawns this program and maps its exit status to a GateResult whose `green` is
false, which lands the gate in `Verdict.blocking` and turns MERGE_OK into
REQUEST_CHANGES. That is proved by a run, not by reading the aggregation:
`test_a_refused_author_override_turns_the_whole_review_REQUEST_CHANGES` drives
the real `review()` twice over one synthetic repository whose only difference
is the presence of the answers document, and asserts the verdict moves while
no other gate blocks.

ONE ARM IS NOT BLOCKING YET, AND IT IS A CLAIM WITH AN EXPIRY. When NO answers
document exists at `.github/ppa_pr_answers.json`, every applicable question is
necessarily unbacked, and blocking on that today would refuse every open PR in
the repository at once -- measured: no answers document exists anywhere in this
tree, and 6 questions already apply to a two-commit branch. That arm therefore
REPORTS, naming how many questions apply, on every review. The moment an
answers-document convention is required repo-wide it becomes blocking, and
nothing in this program changes: it already returns rc 1 for that case.

WHY THIS PROGRAM EXISTS
=======================
Appendix C of the PPA specification is twenty review questions. Asking a human
to answer all twenty on every PR does not produce twenty answers; it produces
twenty rituals. The questions that matter get the same three lines as the ones
that do not apply, and the one question that would have caught the defect is
answered "N/A" by the person least motivated to say otherwise.

So this program does two things a human reviewer cannot do reliably:

  1. It decides WHICH questions apply, from the change-set itself.
  2. It checks that each applicable one is backed by evidence a machine can
     re-verify, and that each inapplicable one carries a reason a machine can
     re-derive.

THE MERGE CONDITION, VERBATIM FROM THE SPEC
===========================================
    Every applicable question has verifiable evidence, and every inapplicable
    question has a machine-checkable reason.

It is NOT "all twenty questions have long answers". Prose never satisfies a
question here, however good the prose is. That is deliberate and it is the
whole difference between this and a checklist template.

THE AUTHOR DOES NOT GET TO SAY N/A
==================================
The changed-surface detector decides applicability. An author may DECLARE extra
scope (`declared_scope` in the answers document), which can only ADD questions.
An author who marks an applicable question N/A gets `AUTHOR_OVERRIDE_REFUSED`
and rc=1. If that rule were the other way round, the checklist would be exactly
as strong as the least careful author's self-assessment, which is to say not a
checklist at all.

TWO ARMS, BECAUSE A PATH LIST CAN BE ROUTED AROUND
==================================================
A detector that watches a list of filenames is defeated by writing the code
somewhere else. That is not a hypothetical; it is the failure mode this lane
was told to design against. So applicability is decided by TWO independent
arms over the same change-set:

  PATH ARM      the file's identity. `programs/_ppa/agent_policy.py` is an
                action-registry surface because of what that module IS, per the
                frozen module map in `docs/PPA_INTERFACES.md` §4.

  CONTENT ARM   what the change SAYS. Every line the diff ADDS, anywhere in the
                repository, is scanned for the signature of a surface —
                `shell=True`, a subprocess whose argv is not a literal list, an
                MCP dispatch, an allow-list, an actuator, a rollback, an
                outward claim. A file the path arm has never heard of still
                trips the content arm the moment it acquires the surface.

The arms are OR-ed. Neither can veto the other. A token found by either makes
its questions apply.

WHEN ONE ARM CANNOT RUN, THE ANSWER IS NOT "CLEAN"
==================================================
The content arm needs a diff. Given only a list of changed PATHS (`--changed-file`)
there is no diff to read, and the honest report of a one-armed run is not that
the content-reachable surfaces are absent — it is that they were NOT LOOKED FOR.
Every question whose tokens the content arm could have supplied then reports
`UNDETERMINED`, and the program exits 2. It does not report N/A.

This is hard rule 9 of this repository, applied to the detector itself: "I could
not read it" and "I read it and it was empty" must never produce the same
verdict.

EXIT CODES — and the one place this program had to choose a reading
===================================================================
    0  the merge condition is met
    1  the merge condition is VIOLATED — a finding about the PR
    2  the merge condition could not be evaluated
    3  bad invocation

`docs/PPA_INTERFACES.md` §1 lists "REQUIRED EVIDENCE MISSING" under rc=2. That
phrase describes THIS PROGRAM'S OWN inputs being missing — no change-set, no
answers document, an unreadable catalogue. It does not describe "I read the
answers document and question 19 has nothing behind it", which is a finding
about the PR and therefore rc=1.

If both mapped to 2, the negative fixture and the vacuous fixture would produce
the identical verdict, and the gate would have lost exactly the distinction it
exists to make. FAIL beats UNDETERMINED, the same precedence `_vacuous_exit`
uses for the same reason: a real finding is never silenced by a skip.

THE CATALOGUE IS DATA
=====================
`ppa_pr_scope_checklist.v1.json` holds the twenty questions, their section,
their scope tokens and their minimum evidence kinds. Editing a question is a
data change. The `v1` in the filename is the schema version: once something has
hashed against it, a change is a `v2` file, never an edit.

THE ANSWERS DOCUMENT
===================
    {
      "schema": "vibeic.ppa.pr_answers.v1",
      "declared_scope": ["casebook"],          optional; may only ADD questions
      "answers": [
        {"question": 3,
         "evidence": [{"kind": "artefact", "ref": "phase3/sta.rpt",
                       "sha256": "sha256:..."}]},
        {"question": 11,
         "evidence": [{"kind": "test",
                       "ref": "programs/tests/test_x.py::test_negative"}]},
        {"question": 1,
         "evidence": [{"kind": "path", "ref": "programs/x.py"},
                      {"kind": "prose", "text": "context, never an answer"}]}
      ]
    }

An `"applicability": "N/A"` key is ACCEPTED in an answer and then REFUSED if the
detector disagrees, rather than rejected as malformed — the author is allowed to
state their belief, and the report is where the disagreement is recorded.

Usage:
    ppa_pr_scope_check.py --base <ref> --head <ref> --answers <answers.json>
    ppa_pr_scope_check.py --changed-file <paths.txt> [--diff-file <diff>] ...
    ppa_pr_scope_check.py ... --json <report.json>
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json as atomic_write_json  # noqa: E402
from _ppa.canonical_json import digest_of  # noqa: E402

try:                                                          # pragma: no cover
    import _vacuous_exit as _vx
except Exception:                                             # pragma: no cover
    _vx = None

GATE_NAME = "ppa_pr_scope_check"
REPORT_SCHEMA = "vibeic.ppa.pr_scope.v1"
ANSWERS_SCHEMA = "vibeic.ppa.pr_answers.v1"
CATALOGUE_NAME = "ppa_pr_scope_checklist.v1.json"

RC_PASS, RC_FAIL, RC_UNDETERMINED, RC_BAD_INVOCATION = 0, 1, 2, 3

#: A changed file belongs to one of three classes, and the class decides which
#: content rules can meaningfully fire on it.
#:
#:   code    it executes. Every rule applies.
#:   config  it is structured data that can GRANT a capability but cannot run
#:           one. A config's field names are a VOCABULARY, not a surface: a
#:           checklist that lists the word "pareto" has not acquired a Pareto
#:           frontier. What a config genuinely can carry is an allow-list, a
#:           tool name, a provider, a command string — so those rules apply and
#:           the domain-vocabulary rules do not.
#:   prose   it is documentation. A document that QUOTES `shell=True` has not
#:           acquired a shell surface. What a document genuinely can carry is
#:           an outward claim, and an agent-facing instruction to reach a tool.
#:
#: This split is not a loosening. No rule was weakened and no path was removed
#: from the scan; a rule is simply not asked a question its file class cannot
#: answer. Measured on this lane's own PR, it takes the content arm from 44
#: hits (its own regex table and docstrings) to the hits that are real.
PROSE_SUFFIXES = {".md", ".rst", ".txt"}
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}

CLASS_CODE, CLASS_CONFIG, CLASS_PROSE = "code", "config", "prose"


def file_class(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in PROSE_SUFFIXES:
        return CLASS_PROSE
    if suffix in CONFIG_SUFFIXES:
        return CLASS_CONFIG
    return CLASS_CODE

VERIFIABLE_KINDS = ("artefact", "test", "path")


# --------------------------------------------------------------------------
# The PATH arm.
#
# Every rule cites WHY the path carries the token. Where the reason is the
# frozen module map, the citation is `PPA_INTERFACES.md §4` — so a reader can
# check the rule against the contract instead of against this author's memory.
# --------------------------------------------------------------------------
PATH_RULES: Tuple[Tuple[str, str, Tuple[str, ...], str], ...] = (
    ("ppa_agent_policy", r"(^|/)programs/_ppa/agent_policy\.py$",
     ("agent", "ai", "action_registry", "blast_radius", "security", "runtime"),
     "PPA_INTERFACES §4: agent_policy IS the allow-list, autonomy level, blast "
     "radius and budget — the typed action registry question 15 asks about."),
    ("ppa_agent_router", r"(^|/)programs/_ppa/agent_router\.py$",
     ("agent", "ai", "runtime", "provider"),
     "PPA_INTERFACES §4: agent_router owns Program-First diagnosis and the "
     "explicit handoff, so it is the AI/provider boundary."),
    ("ppa_agent_context", r"(^|/)programs/_ppa/agent_context\.py$",
     ("agent", "ai", "security"),
     "PPA_INTERFACES §4: agent_context is the read-only, hash-bound evidence "
     "context — the surface a prompt injection would attack."),
    ("ppa_closure", r"(^|/)programs/_ppa/closure\.py$",
     ("closure", "controller"),
     "PPA_INTERFACES §4: closure is the controller state machine — actuator, "
     "remeasure, rollback, stop."),
    ("ppa_search", r"(^|/)programs/_ppa/search\.py$",
     ("search", "candidate"),
     "PPA_INTERFACES §4: search owns the candidate lifecycle and budget."),
    ("ppa_contract", r"(^|/)programs/_ppa/contract\.py$",
     ("contract", "claim_surface"),
     "PPA_INTERFACES §4: contract owns authority order and conflict detection "
     "— what a later claim is measured against."),
    ("ppa_feasibility", r"(^|/)programs/_ppa/feasibility\.py$",
     ("feasibility", "gate"),
     "PPA_INTERFACES §4: feasibility IS the hard gate."),
    ("ppa_pareto", r"(^|/)programs/_ppa/pareto\.py$",
     ("pareto", "feasibility"),
     "PPA_INTERFACES §4: pareto is the frontier over the triple."),
    ("ppa_benchmark", r"(^|/)programs/_ppa/benchmark\.py$",
     ("benchmark",),
     "PPA_INTERFACES §4: benchmark owns arms, fairness and the scorer."),
    ("ppa_casebook", r"(^|/)programs/_ppa/(casebook|distillation)\.py$",
     ("casebook", "recovery"),
     "PPA_INTERFACES §4: casebook and distillation are the recovery lifecycle."),
    ("ppa_metric_domain", r"(^|/)programs/_ppa/(metrics|timing|power|area)\.py$",
     ("metric", "parser"),
     "PPA_INTERFACES §4: these construct or parse the canonical metric record."),
    ("ppa_backend", r"(^|/)programs/_ppa/backends/[^/]+\.py$",
     ("parser", "tool"),
     "PPA_INTERFACES §4: a backend parses one tool's output and nothing else."),
    ("ppa_identity", r"(^|/)programs/_ppa/(identity|provenance|canonical_json)\.py$",
     ("contract", "metric"),
     "PPA_INTERFACES §3: these decide what a fact IS, so every claim built on "
     "them moves when they move."),
    ("flow_yaml", r"(^|/)flow/phase1_phase2_phase3\.yaml$",
     ("flow_step", "gate", "blast_radius", "controller"),
     "flow-change-acceptance SKILL.md:15 — the blast radius of a flow change "
     "is every design and every future design."),
    ("skill_md", r"(^|/)skills/[^/]+/SKILL\.md$",
     ("skill", "docs", "agent", "ai"),
     "A skill is the instructions an agent follows, so changing one changes AI "
     "behaviour without changing a program — and a prompt surface is exactly "
     "where question 19's injection lands. `agents/` and `commands/` already "
     "carry these tokens; skills carrying only `docs` was the inconsistency, "
     "not this."),
    ("schema_json", r"(^|/)schemas/.*\.schema\.json$",
     ("schema", "contract"),
     "PPA_INTERFACES §5: a schema is the contract an instance document is "
     "hashed against."),
    ("gate_program", r"(^|/)programs/[^/]*(_check|_gate|_guard)[^/]*\.py$",
     ("gate",),
     "Repo convention: _check / _gate / _guard programs are the gates."),
    ("parser_program", r"(^|/)programs/[^/]*(_parse|_extract|_scan)[^/]*\.py$",
     ("parser",),
     "Repo convention: these turn tool output into structured facts."),
    ("controller_program", r"(^|/)programs/[^/]*(_runner|_loop|_orchestrat)[^/]*\.py$",
     ("controller",),
     "Repo convention: these drive a sequence and decide when to stop."),
    ("report_program", r"(^|/)programs/[^/]*_report[^/]*\.py$",
     ("report", "claims", "claim_surface"),
     "A report program renders the outward claim; question 12 asks whether its "
     "scope exceeds its evidence."),
    ("ppa_top_program", r"(^|/)programs/ppa_[^/]*\.py$",
     ("metric",),
     "A top-level ppa_* program is by definition part of the PPA measurement "
     "surface."),
    ("docs_md", r"(^|/)(docs/.*\.md|README\.md)$",
     ("docs", "claims", "claim_surface"),
     "Documentation is where an outward claim is actually made."),
    ("agent_definitions", r"(^|/)(agents|commands)/",
     ("agent", "ai", "tool"),
     "An agent definition or slash command is an AI entry point."),
    ("mcp_surface", r"(^|/)(\.mcp\.json|mcp-eda[^/]*/)",
     ("tool", "runtime", "provider", "agent"),
     "The MCP surface is where an agent reaches a tool."),
    ("ci_harness", r"(^|/)tools/ci/[^/]*\.(py|sh)$",
     ("gate", "controller"),
     "tools/ci is the harness that decides what runs and whether it passed."),
)

# --------------------------------------------------------------------------
# The CONTENT arm.
#
# These run over the lines a diff ADDS, in any file anywhere in the repository.
# This is the arm that cannot be defeated by choosing a different filename.
# --------------------------------------------------------------------------
CONTENT_RULES: Tuple[Tuple[str, str, Tuple[str, ...], str,
                          Tuple[str, ...]], ...] = (
    ("shell_true", r"shell\s*=\s*True|\"shell\"\s*:\s*true",
     ("security", "tool"),
     "A shell is a metacharacter interpreter; question 19 names it directly.",
     (CLASS_CODE, CLASS_CONFIG)),
    ("os_system", r"\bos\.(system|popen)\s*\(",
     ("security", "tool"),
     "os.system / os.popen run a string through a shell.",
     (CLASS_CODE,)),
    ("dynamic_argv",
     r"\bsubprocess\.(run|Popen|call|check_output|check_call)\s*\(\s*(?!\[)",
     ("security", "tool"),
     "A subprocess whose argv is not a literal list takes its argv from data. "
     "The literal-list form is the safe one and is deliberately not matched.",
     (CLASS_CODE,)),
    ("eval_exec", r"(?<![\w.])(eval|exec)\s*\(",
     ("security",),
     "Question 19's 'raw script' and 'arbitrary shell' in their in-process form.",
     (CLASS_CODE,)),
    ("unsafe_deserialize",
     r"\b(pickle|marshal)\.loads?\s*\(|\byaml\.load\s*\(",
     ("security",),
     "Deserialising untrusted bytes executes whatever they describe.",
     (CLASS_CODE,)),
    ("archive_extract", r"\.extractall\s*\(|\bshutil\.unpack_archive\s*\(",
     ("security",),
     "extractall is the classic path-traversal write primitive.",
     (CLASS_CODE,)),
    ("symlink_surface", r"\bos\.symlink\s*\(|follow_symlinks\s*=\s*True",
     ("security",),
     "Question 19 names path/symlink traversal.",
     (CLASS_CODE,)),
    ("mcp_dispatch",
     r"\bmcp__|\b(call_tool|invoke_tool|tool_call|tool_use|dispatch_tool)\b",
     ("tool", "agent", "security", "runtime"),
     "Question 19 names generic MCP bypass; this is where a tool is reached. "
     "It applies to prose too: a skill or command document that tells an agent "
     "to reach a tool has granted that reach as surely as a call site.",
     (CLASS_CODE, CLASS_CONFIG, CLASS_PROSE)),
    ("llm_surface",
     r"\b(anthropic|system_prompt|user_prompt|llm_client)\b|\bcompletion\s*\(",
     ("ai", "agent", "provider"),
     "An LLM call site is an AI surface whether or not it lives in _ppa/.",
     (CLASS_CODE, CLASS_CONFIG)),
    ("action_registry_surface",
     r"\b(ACTION_REGISTRY|action_registry|ALLOWLIST|ALLOW_LIST|allow_list|"
     r"allowlist|autonomy_level|blast_radius|action_budget)\b",
     ("action_registry", "blast_radius", "agent", "security"),
     "Question 15 asks whether the action is inside the typed registry, the "
     "budget, the blast radius and the autonomy level. An allow-list declared "
     "in a config IS that registry.",
     (CLASS_CODE, CLASS_CONFIG)),
    ("closure_actuator",
     r"\b(actuator|rollback|roll_back|remeasure|re_measure)\b",
     ("closure", "controller"),
     "Questions 8-10 are about the actuator, the re-measurement and the "
     "rollback by name.",
     (CLASS_CODE,)),
    ("pareto_surface", r"\bpareto\b|\bfrontier\b|\bdominated_by\b",
     ("pareto", "feasibility"),
     "Question 7 asks whether an infeasible candidate can enter the frontier.",
     (CLASS_CODE,)),
    ("candidate_search_surface",
     r"\bcandidate_(id|set|pool|lifecycle)\b|\bsearch_space\b|"
     r"\bmulti_fidelity\b",
     ("candidate", "search"),
     "Question 6 asks whether a candidate can win by modifying the problem.",
     (CLASS_CODE,)),
    ("casebook_surface", r"\b(casebook|distillation|case_lifecycle)\b",
     ("casebook", "recovery"),
     "Question 18 asks whether an AI recovery can be distilled.",
     (CLASS_CODE,)),
    ("benchmark_surface",
     r"pass@1|\b(arm_a|arm_b|fairness_condition|independent_scorer)\b",
     ("benchmark",),
     "Question 20 separates an AI-attributed gain from more trials.",
     (CLASS_CODE,)),
    ("metric_surface",
     r"vibeic\.ppa\.metric|\b(wns_ns|tns_ns|slack_ns|leakage_w|area_um2|"
     r"activity_basis)\b",
     ("metric",),
     "A canonical metric field is a measurement surface (questions 1-3).",
     (CLASS_CODE,)),
    ("verdict_surface", r"\[CANNOT CHECK\]|\[REFUSE\]|VACUOUS_PASS:",
     ("gate",),
     "These markers exist only in something that renders a verdict.",
     (CLASS_CODE,)),
    ("outward_claim",
     r"\b(tapeout-ready|production-ready|guarantee[sd]?|certified|proven)\b|"
     r"\b100\s?%",
     ("claims", "claim_surface", "report"),
     "Question 12 asks whether an outward claim's scope exceeds its evidence; "
     "these are the words an over-broad claim is written in.",
     (CLASS_CODE, CLASS_PROSE)),
)

#: Every token the content arm is capable of producing. A run without the
#: content arm cannot report N/A for any question that depends on one of these
#: — it did not look.
CONTENT_REACHABLE_TOKENS: Set[str] = set()
for _r in CONTENT_RULES:
    CONTENT_REACHABLE_TOKENS.update(_r[2])


class _Refusal(Exception):
    """Raised when the program cannot evaluate the merge condition at all.

    Carries the machine code that goes into the report, so the printed refusal
    and the recorded one come from the same object rather than from two
    separately maintained strings.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------
# Change-set acquisition.
# --------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def changed_paths_from_git(repo: Path, base: str, head: str) -> List[str]:
    rc, out, err = _git(repo, "diff", "--name-only", f"{base}..{head}")
    if rc != 0:
        raise _Refusal(
            "CHANGE_SET_UNREADABLE",
            f"git diff --name-only {base}..{head} failed: "
            f"{err.strip() or 'non-zero exit'}")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def diff_text_from_git(repo: Path, base: str, head: str) -> str:
    rc, out, err = _git(repo, "diff", "--unified=0", f"{base}..{head}")
    if rc != 0:
        raise _Refusal(
            "DIFF_UNREADABLE",
            f"git diff {base}..{head} failed: {err.strip() or 'non-zero exit'}")
    return out


_HUNK_RX = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff_text: str) -> Tuple[List[Tuple[str, int, str]],
                                           List[Tuple[str, int, str]]]:
    """(added, removed), each as (path, line number in ITS OWN version, text).

    Both sides, and the removed side is not an afterthought. A PR that DELETES
    the allow-list check adds no line at all: an added-lines-only detector sees
    an empty change and reports the security question N/A. Deleting the guard is
    the cheapest way to defeat a detector that only reads what was written.

    The added side is keyed on `+++ b/<path>` and the removed side on
    `--- a/<path>`, so a rename attributes each side to the name it had there.
    Line numbers come from the hunk header because the masking pass has to line
    a match up against the tokens of the corresponding file version.
    """
    adds: List[Tuple[str, int, str]] = []
    removes: List[Tuple[str, int, str]] = []
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    old_no = new_no = 0

    def _strip(target: str) -> Optional[str]:
        if target == "/dev/null":
            return None
        return target[2:] if target.startswith(("a/", "b/")) else target

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            old_path = new_path = None
            continue
        if line.startswith("--- "):
            old_path = _strip(line[4:].strip())
            continue
        if line.startswith("+++ "):
            new_path = _strip(line[4:].strip())
            continue
        m = _HUNK_RX.match(line)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(2))
            continue
        if line.startswith("\\"):          # "\ No newline at end of file"
            continue
        if line.startswith("+"):
            if new_path:
                adds.append((new_path, new_no, line[1:]))
            new_no += 1
        elif line.startswith("-"):
            if old_path:
                removes.append((old_path, old_no, line[1:]))
            old_no += 1
        else:
            old_no += 1
            new_no += 1
    return adds, removes


#: `tokenize` token types whose text is data, not executable code. A rule match
#: inside one of these is a MENTION of a surface, not the surface. Python 3.12
#: splits f-strings into their own token types; they are picked up by name so a
#: newer interpreter masks them too and an older one simply has fewer types.
_DATA_TOKENS = tuple(
    t for t in (
        getattr(tokenize, "STRING", None),
        getattr(tokenize, "COMMENT", None),
        getattr(tokenize, "FSTRING_START", None),
        getattr(tokenize, "FSTRING_MIDDLE", None),
        getattr(tokenize, "FSTRING_END", None),
    ) if t is not None)


def data_spans(source: str) -> Optional[Dict[int, List[Tuple[int, int]]]]:
    """line number -> the (col_start, col_end) ranges that are string/comment.

    `None` means the source could not be tokenized. That is NOT the same as "it
    had no strings", and the caller must not treat it as such: an untokenizable
    file gets no masking, so every match stands. Failing toward DETECTING is the
    only safe direction for a detector whose job is to be hard to route around.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except Exception:
        return None
    spans: Dict[int, List[Tuple[int, int]]] = {}
    for tok in toks:
        if tok.type not in _DATA_TOKENS:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for row in range(srow, erow + 1):
            lo = scol if row == srow else 0
            hi = ecol if row == erow else _COL_MAX
            spans.setdefault(row, []).append((lo, hi))
    return spans


_COL_MAX = 1 << 30


def _is_masked(spans: Optional[Dict[int, List[Tuple[int, int]]]],
               lineno: int, col: int) -> bool:
    if not spans:
        return False
    return any(lo <= col < hi for lo, hi in spans.get(lineno, ()))


# --------------------------------------------------------------------------
# The two arms.
# --------------------------------------------------------------------------
def detect_path_surfaces(paths: Sequence[str]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for rule_id, pattern, tokens, why in PATH_RULES:
        rx = re.compile(pattern)
        for p in paths:
            norm = p.replace("\\", "/")
            if rx.search(norm):
                hits.append({"arm": "path", "rule": rule_id, "path": norm,
                             "tokens": list(tokens), "why": why})
    return hits


def detect_content_surfaces(
        adds: Sequence[Tuple[str, int, str]],
        removes: Sequence[Tuple[str, int, str]] = (),
        source_of: Optional[Any] = None,
        base_source_of: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Scan both sides of the diff, and report how each file was masked.

    `source_of(path)` returns the POST-CHANGE text of a `.py` file and
    `base_source_of(path)` the PRE-CHANGE text; each is what makes masking
    possible on its own side. When one cannot supply a file, that file is
    scanned unmasked and says so in the returned masking map. The second return
    value exists so the report can never imply a precision the run did not have.
    """
    hits: List[Dict[str, Any]] = []
    masking: Dict[str, str] = {}
    compiled = [(rid, re.compile(pat), tok, why, klasses)
                for rid, pat, tok, why, klasses in CONTENT_RULES]
    by_class = {k: [r for r in compiled if k in r[4]]
                for k in (CLASS_CODE, CLASS_CONFIG, CLASS_PROSE)}
    spans_cache: Dict[Tuple[str, str], Optional[Dict[int, List[Tuple[int, int]]]]] = {}

    def spans_for(path: str, side: str) -> Optional[Dict[int, List[Tuple[int, int]]]]:
        key = (path, side)
        if key in spans_cache:
            return spans_cache[key]
        reader = source_of if side == "added" else base_source_of
        result: Optional[Dict[int, List[Tuple[int, int]]]] = None
        if Path(path).suffix.lower() != ".py":
            state = "NOT_APPLICABLE_NOT_PYTHON"
        elif reader is None:
            state = "NOT_APPLIED_SOURCE_UNAVAILABLE"
        else:
            src = reader(path)
            if src is None:
                state = "NOT_APPLIED_SOURCE_UNAVAILABLE"
            else:
                result = data_spans(src)
                state = ("APPLIED" if result is not None
                         else "NOT_APPLIED_UNTOKENIZABLE")
        # A file scanned on both sides records the WEAKER of the two states.
        # If masking worked on the post-change text but the base text could not
        # be read, saying "APPLIED" would advertise a precision only half the
        # scan had — and "I could not read it" must never look like "I read it".
        prior = masking.get(path)
        if prior is None or (state.startswith("NOT_APPLIED")
                             and not prior.startswith("NOT_APPLIED")):
            masking[path] = state
        spans_cache[key] = result
        return result

    for side, stream in (("added", adds), ("removed", removes)):
        for path, lineno, text in stream:
            rules = by_class[file_class(path)]
            spans = spans_for(path, side)
            for rule_id, rx, tokens, why, _klasses in rules:
                for m in rx.finditer(text):
                    if _is_masked(spans, lineno, m.start()):
                        continue
                    hits.append({"arm": "content", "side": side,
                                 "rule": rule_id, "path": path,
                                 "line": lineno,
                                 "evidence_line": text.strip()[:200],
                                 "tokens": list(tokens), "why": why})
                    break
    return hits, masking


# --------------------------------------------------------------------------
# Evidence verification.
# --------------------------------------------------------------------------
def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _resolve_inside(repo: Path, ref: str) -> Optional[Path]:
    """Resolve a repo-relative reference, refusing anything that escapes.

    An evidence link is written by the author of the PR under review, so it is
    exactly the kind of input question 19 asks about. `..` and absolute paths
    are refused rather than normalised: a link that points outside the tree is
    not evidence about this tree.
    """
    if not ref or ref.startswith("/") or "\\" in ref:
        return None
    candidate = (repo / ref)
    try:
        resolved = candidate.resolve()
        root = repo.resolve()
    except OSError:
        return None
    if root != resolved and root not in resolved.parents:
        return None
    return resolved


def verify_evidence(repo: Path, entry: Any) -> Dict[str, Any]:
    """One evidence entry -> a verdict on whether a machine confirmed it."""
    if not isinstance(entry, dict):
        return {"kind": "?", "status": "INVALID",
                "reason": "evidence entry is not an object"}
    kind = str(entry.get("kind", "")).strip()
    ref = str(entry.get("ref", "")).strip()
    rec: Dict[str, Any] = {"kind": kind, "ref": ref}

    if kind == "prose":
        rec["status"] = "UNVERIFIABLE_BY_DESIGN"
        rec["reason"] = ("prose may accompany an answer and can never satisfy "
                         "one")
        return rec

    if kind not in VERIFIABLE_KINDS:
        rec["status"] = "INVALID"
        rec["reason"] = (f"unknown evidence kind {kind!r}; verifiable kinds are "
                         f"{list(VERIFIABLE_KINDS)} (prose is accepted but "
                         f"never satisfies)")
        return rec

    if kind == "test":
        if "::" not in ref:
            rec["status"] = "INVALID"
            rec["reason"] = "a test reference must be <file>::<test name>"
            return rec
        rel, _, name = ref.partition("::")
        target = _resolve_inside(repo, rel)
        if target is None:
            rec["status"] = "INVALID"
            rec["reason"] = "test file reference escapes the repository"
            return rec
        if not target.is_file():
            rec["status"] = "UNVERIFIED"
            rec["reason"] = f"test file does not exist: {rel}"
            return rec
        text = target.read_text(encoding="utf-8", errors="ignore")
        if re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(",
                     text, re.M):
            rec["status"] = "VERIFIED"
            rec["sha256"] = _sha256_file(target)
        else:
            rec["status"] = "UNVERIFIED"
            rec["reason"] = f"{rel} does not define {name}"
        return rec

    target = _resolve_inside(repo, ref)
    if target is None:
        rec["status"] = "INVALID"
        rec["reason"] = "reference escapes the repository or is not relative"
        return rec
    if not target.is_file():
        rec["status"] = "UNVERIFIED"
        rec["reason"] = f"file does not exist: {ref}"
        return rec

    computed = _sha256_file(target)
    rec["sha256"] = computed
    if kind == "artefact":
        declared = str(entry.get("sha256", "")).strip()
        if not declared:
            rec["status"] = "UNVERIFIED"
            rec["reason"] = ("question 3 asks for the artifact AND its hash; "
                             "no sha256 was declared")
        elif declared != computed:
            rec["status"] = "MISMATCH"
            rec["reason"] = (f"declared {declared} but the file hashes to "
                             f"{computed}")
        else:
            rec["status"] = "VERIFIED"
    else:
        rec["status"] = "VERIFIED"
    return rec


# --------------------------------------------------------------------------
# Applicability + the merge condition.
# --------------------------------------------------------------------------
def question_applicability(question: Dict[str, Any], tokens: Set[str],
                           content_arm_ran: bool) -> Dict[str, Any]:
    applies = question.get("applies", {})
    mode = applies.get("mode")
    if mode == "always":
        return {"status": "APPLICABLE", "reason_code": "ALWAYS_REQUIRED",
                "matched_tokens": []}
    if mode != "any_token":
        return {"status": "UNDETERMINED",
                "reason_code": "CATALOGUE_MODE_UNKNOWN",
                "matched_tokens": []}

    want = set(applies.get("tokens", []))
    matched = sorted(want & tokens)
    if matched:
        return {"status": "APPLICABLE", "reason_code": "SURFACE_MATCHED",
                "matched_tokens": matched}
    if not content_arm_ran and (want & CONTENT_REACHABLE_TOKENS):
        return {
            "status": "UNDETERMINED",
            "reason_code": "CONTENT_ARM_NOT_RUN",
            "matched_tokens": [],
            "detail": ("no diff was available, so the content arm did not "
                       "look for " + ", ".join(sorted(want & CONTENT_REACHABLE_TOKENS))
                       + "; absence was not established"),
        }
    return {"status": "NOT_APPLICABLE",
            "reason_code": applies.get("na_reason_code", "NO_SURFACE_MATCHED"),
            "matched_tokens": [],
            "searched_tokens": sorted(want)}


def evaluate(repo: Path, catalogue: Dict[str, Any], tokens: Set[str],
             content_arm_ran: bool,
             answers_by_id: Dict[int, Dict[str, Any]],
             answers_present: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for q in catalogue.get("questions", []):
        qid = int(q["id"])
        app = question_applicability(q, tokens, content_arm_ran)
        row: Dict[str, Any] = {
            "question": qid,
            "section": q.get("section"),
            "text": q.get("text"),
            "applicability": app["status"],
            "applicability_reason_code": app["reason_code"],
            "matched_tokens": app.get("matched_tokens", []),
        }
        for extra in ("searched_tokens", "detail"):
            if extra in app:
                row[extra] = app[extra]

        answer = answers_by_id.get(qid)
        min_kinds = q.get("min_evidence_kinds") or list(VERIFIABLE_KINDS)
        row["accepted_evidence_kinds"] = list(min_kinds)

        if app["status"] == "NOT_APPLICABLE":
            row["status"] = "NOT_APPLICABLE"
            rows.append(row)
            continue

        if app["status"] == "UNDETERMINED":
            row["status"] = "UNDETERMINED"
            rows.append(row)
            continue

        # APPLICABLE from here.
        if answer is not None and \
                str(answer.get("applicability", "")).upper() in (
                    "N/A", "NA", "NOT_APPLICABLE"):
            row["status"] = "AUTHOR_OVERRIDE_REFUSED"
            row["detail"] = (
                "the author marked this N/A but the changed-surface detector "
                "says it applies (" + ", ".join(app.get("matched_tokens", []))
                + "). The detector decides applicability, never the author.")
            rows.append(row)
            continue

        if not answers_present:
            row["status"] = "MISSING_EVIDENCE"
            row["detail"] = "no answers document was supplied"
            rows.append(row)
            continue

        entries = (answer or {}).get("evidence") or []
        verdicts = [verify_evidence(repo, e) for e in entries]
        row["evidence"] = verdicts
        satisfying = [v for v in verdicts
                      if v.get("status") == "VERIFIED"
                      and v.get("kind") in min_kinds]
        if satisfying:
            row["status"] = "SATISFIED"
        else:
            row["status"] = "MISSING_EVIDENCE"
            if any(v.get("status") == "MISMATCH" for v in verdicts):
                row["detail"] = ("an artefact's declared hash does not match "
                                 "the file")
            elif any(v.get("status") == "VERIFIED" for v in verdicts):
                row["detail"] = (
                    "evidence was verified but none of it is of an accepted "
                    "kind for this question (" + ", ".join(min_kinds) + ")")
            elif verdicts:
                row["detail"] = "no evidence entry could be verified"
            else:
                row["detail"] = "the question carries no evidence entries"
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Report assembly.
# --------------------------------------------------------------------------
def _classify_changed(paths: Sequence[str]) -> Dict[str, List[str]]:
    """The C.3 'changed schemas / programs / flow steps / skills' emission."""
    out: Dict[str, List[str]] = {"schemas": [], "programs": [],
                                 "flow_files": [], "skills": [], "tests": [],
                                 "docs": [], "other": []}
    for p in paths:
        n = p.replace("\\", "/")
        if re.search(r"(^|/)schemas/.*\.schema\.json$", n):
            out["schemas"].append(n)
        elif re.search(r"(^|/)programs/tests/", n):
            out["tests"].append(n)
        elif re.search(r"(^|/)programs/.*\.py$", n):
            out["programs"].append(n)
        elif re.search(r"(^|/)flow/.*\.ya?ml$", n):
            out["flow_files"].append(n)
        elif re.search(r"(^|/)skills/[^/]+/SKILL\.md$", n):
            out["skills"].append(n)
        elif n.endswith(".md"):
            out["docs"].append(n)
        else:
            out["other"].append(n)
    return {k: sorted(set(v)) for k, v in out.items()}


def _changed_flow_steps(repo: Path, base: Optional[str], head: Optional[str],
                        paths: Sequence[str]) -> Dict[str, Any]:
    """Which flow STEP ids the change touches, or an honest 'not determined'.

    The flow YAML is one of the three files this lane may not edit, but it can
    and must be READ: 'the flow file changed' is a much weaker statement than
    'step 37.5 changed', and the checklist is about the latter.
    """
    flow_files = [p for p in paths
                  if re.search(r"(^|/)flow/.*\.ya?ml$", p.replace("\\", "/"))]
    if not flow_files:
        return {"status": "NO_FLOW_FILE_CHANGED", "steps": []}
    if not base or not head:
        return {"status": "NOT_DETERMINED",
                "reason": "a flow file changed but no git range was supplied, "
                          "so the changed step ids were not read",
                "files": flow_files, "steps": []}
    steps: Set[str] = set()
    for f in flow_files:
        rc, out, _ = _git(repo, "diff", "--unified=8", f"{base}..{head}", "--", f)
        if rc != 0:
            return {"status": "NOT_DETERMINED",
                    "reason": f"git diff of {f} failed",
                    "files": flow_files, "steps": []}
        for line in out.splitlines():
            m = re.search(r"^[+\- ]?\s*-?\s*(?:id|step)\s*:\s*[\"']?"
                          r"([0-9][0-9A-Za-z._-]*)", line)
            if m:
                steps.add(m.group(1))
    return {"status": "DETERMINED" if steps else "NO_STEP_ID_IN_DIFF_CONTEXT",
            "files": flow_files, "steps": sorted(steps)}


def _required_fixtures(tokens: Set[str], rows: List[Dict[str, Any]],
                       changed: Dict[str, List[str]]) -> Dict[str, Any]:
    """PPA_INTERFACES §7: four fixtures, and they are required of a GATE.

    'Required' here is a statement about what the PR owes, not a claim that it
    was delivered — delivery is evidenced through the questions that name a
    test (4, 5, 11, 19). Conflating the two would let a program announce a
    requirement and credit itself with meeting it.
    """
    gate_like = bool(tokens & {"gate", "parser", "controller"})
    if not gate_like:
        return {"required": False,
                "reason": "no gate / parser / controller surface in the "
                          "change-set",
                "fixtures": []}
    by_id = {r["question"]: r for r in rows}
    mapping = [("positive", 11), ("negative", 11), ("vacuous", 4),
               ("mutation", 11)]
    fixtures = []
    for name, qid in mapping:
        row = by_id.get(qid, {})
        fixtures.append({
            "fixture": name,
            "evidenced_through_question": qid,
            "status": row.get("status", "UNDETERMINED"),
        })
    return {"required": True,
            "reason": "PPA_INTERFACES §7 requires all four of a gate",
            "changed_test_files": changed.get("tests", []),
            "fixtures": fixtures}


def _required_mutation_tests(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The named tests the PR offered as its mutation proof, and their state."""
    by_id = {r["question"]: r for r in rows}
    row = by_id.get(11, {})
    if row.get("applicability") != "APPLICABLE":
        return {"required": False,
                "reason": "question 11 does not apply to this change-set",
                "tests": []}
    named = [e.get("ref") for e in row.get("evidence", [])
             if isinstance(e, dict) and e.get("kind") == "test"]
    return {"required": True,
            "reason": "a gate / parser / controller changed, so a named test "
                      "must go red when the change is reverted",
            "tests": sorted(t for t in named if t),
            "question_11_status": row.get("status", "UNDETERMINED")}


def build_report(repo: Path, catalogue: Dict[str, Any],
                 paths: List[str], path_hits: List[Dict[str, Any]],
                 content_hits: List[Dict[str, Any]], content_arm_ran: bool,
                 declared_scope: List[str], answers_present: bool,
                 answers_doc: Optional[Dict[str, Any]],
                 rows: List[Dict[str, Any]],
                 base: Optional[str], head: Optional[str],
                 tokens: Set[str],
                 masking: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    changed = _classify_changed(paths)
    detected = sorted({t for h in path_hits + content_hits
                       for t in h["tokens"]})
    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "gate": GATE_NAME,
        "catalogue": {
            "file": CATALOGUE_NAME,
            "schema": catalogue.get("schema"),
            "version": catalogue.get("catalogue_version"),
            "digest": digest_of(catalogue),
            "question_count": len(catalogue.get("questions", [])),
        },
        "change_set": {
            "base": base, "head": head,
            "path_count": len(paths),
            "digest": digest_of(sorted(paths)),
            "changed": changed,
        },
        "detector": {
            "arms": {
                "path": "RUN",
                "content": "RUN" if content_arm_ran else "NOT_RUN",
            },
            "content_arm_note": (
                "the content arm read the added lines of the diff"
                if content_arm_ran else
                "NO DIFF WAS AVAILABLE. Content-reachable surfaces were NOT "
                "LOOKED FOR; their absence is not established and the "
                "questions that depend on them report UNDETERMINED, never N/A."
            ),
            "content_masking": dict(sorted((masking or {}).items())),
            "content_masking_note": (
                "APPLIED: string and comment tokens of the post-change file "
                "were excluded, so a rule that matched only a MENTION of a "
                "surface did not fire. NOT_APPLIED_*: the file was scanned "
                "unmasked and every match stands — the safe direction for a "
                "detector, and stated here rather than implied."),
            "detected_tokens": detected,
            "declared_scope": sorted(set(declared_scope)),
            "effective_tokens": sorted(tokens),
            "declared_only_tokens": sorted(set(declared_scope) - set(detected)),
            "detected_not_declared": sorted(set(detected) - set(declared_scope)),
            "path_hits": path_hits,
            "content_hits": content_hits,
        },
        "affected_metric_domains": sorted(
            {t for t in tokens
             if t in {"metric", "feasibility", "pareto", "benchmark",
                      "contract", "closure", "search", "candidate"}}),
        "action_registry_or_blast_radius_changes": [
            h for h in path_hits + content_hits
            if {"action_registry", "blast_radius"} & set(h["tokens"])],
        "contract_or_claim_surface_changes": [
            h for h in path_hits + content_hits
            if {"contract", "claim_surface", "claims", "schema"} & set(h["tokens"])],
        "flow_steps": _changed_flow_steps(repo, base, head, paths),
        "questions": rows,
    }
    report["required_fixtures"] = _required_fixtures(tokens, rows, changed)
    report["required_mutation_tests"] = _required_mutation_tests(rows)
    report["missing_evidence"] = [
        {"question": r["question"], "text": r["text"],
         "status": r["status"], "detail": r.get("detail", ""),
         "accepted_evidence_kinds": r.get("accepted_evidence_kinds", [])}
        for r in rows
        if r["status"] in ("MISSING_EVIDENCE", "AUTHOR_OVERRIDE_REFUSED")]
    report["answers_document_present"] = answers_present
    if answers_doc is not None:
        report["answers_document_schema"] = answers_doc.get("schema")

    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    report["summary"] = {
        "by_status": dict(sorted(counts.items())),
        "applicable": sum(1 for r in rows
                          if r["applicability"] == "APPLICABLE"),
        "not_applicable": sum(1 for r in rows
                              if r["applicability"] == "NOT_APPLICABLE"),
        "undetermined": sum(1 for r in rows
                            if r["applicability"] == "UNDETERMINED"),
    }
    report["merge_condition"] = catalogue.get("merge_condition", "")
    report["digest"] = digest_of(
        {k: v for k, v in report.items() if k != "digest"})
    return report


def verdict_of(report: Dict[str, Any]) -> Tuple[int, str]:
    """FAIL beats UNDETERMINED beats PASS — the `_vacuous_exit` precedence.

    A real finding is never silenced by something the run could not determine;
    that is the direction in which a mistake is survivable.
    """
    rows = report["questions"]
    hard = [r for r in rows
            if r["status"] in ("MISSING_EVIDENCE", "AUTHOR_OVERRIDE_REFUSED")]
    if hard:
        return RC_FAIL, "FAIL"
    if any(r["status"] == "UNDETERMINED" for r in rows):
        return RC_UNDETERMINED, "UNDETERMINED"
    return RC_PASS, "PASS"


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------
class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; here 2 means UNDETERMINED.

    A malformed command line is rc=3 in this contract, and letting argparse's
    default stand would make "you typed it wrong" indistinguishable from "the
    evidence was not there to read".
    """

    def error(self, message: str) -> Any:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"[REFUSE] {GATE_NAME}: bad invocation: {message}",
              file=sys.stderr)
        raise SystemExit(RC_BAD_INVOCATION)


def _load_catalogue(explicit: Optional[str]) -> Dict[str, Any]:
    path = Path(explicit) if explicit else \
        Path(__file__).resolve().parent / CATALOGUE_NAME
    if not path.is_file():
        raise _Refusal("CATALOGUE_MISSING",
                       f"checklist catalogue not found: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise _Refusal("CATALOGUE_UNREADABLE",
                       f"checklist catalogue is not readable JSON: {exc}")
    if not isinstance(doc, dict) or not doc.get("questions"):
        raise _Refusal("CATALOGUE_EMPTY",
                       f"checklist catalogue has no questions: {path}")
    return doc


def _load_answers(path_str: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """(present, document). A missing FILE is a refusal; an empty DOCUMENT is not.

    Hard rule 9 of this repository lives here. `--answers` pointing at nothing
    means the program could not look, and it exits 2. `--answers` pointing at a
    document that answers nothing means the program looked and found nothing,
    which is a finding about the PR and exits 1.
    """
    if path_str is None:
        return False, None
    p = Path(path_str)
    if not p.is_file():
        raise _Refusal("ANSWERS_MISSING",
                       f"answers document not found: {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise _Refusal("ANSWERS_UNREADABLE",
                       f"answers document is not readable JSON: {exc}")
    if not isinstance(doc, dict):
        raise _Refusal("ANSWERS_UNREADABLE",
                       "answers document is not a JSON object")
    return True, doc


def _find_repo_root(start: Path) -> Path:
    proc = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return start


def _source_reader(repo: Path, head_ref: Optional[str],
                   base_side: bool = False) -> Any:
    """A reader for the POST-CHANGE text of a file, for the masking pass.

    Preference order, and the order is the point: the HEAD revision first,
    because that is the text the diff describes; the working tree only as a
    fallback for `--diff-file` runs where no ref was named. A working tree that
    has moved on from the diff would mask the wrong lines, so a ref is used
    whenever one exists.
    """
    cache: Dict[str, Optional[str]] = {}

    def read(path: str) -> Optional[str]:
        if path in cache:
            return cache[path]
        text: Optional[str] = None
        if head_ref:
            rc, out, _ = _git(repo, "show", f"{head_ref}:{path}")
            if rc == 0:
                text = out
        if text is None and not base_side:
            candidate = repo / path
            if candidate.is_file():
                try:
                    text = candidate.read_text(encoding="utf-8")
                except OSError:
                    text = None
        cache[path] = text
        return text

    return read


def _refuse(code: str, detail: str, json_path: Optional[str] = None) -> int:
    """Say, on stderr AND in the report, that the merge condition was not judged.

    The document matters as much as the message. A consumer that only ever sees
    "no report was written" cannot tell a refusal from a crash, and the two need
    different responses. So a refusal writes a report of its own, carrying the
    same machine code that was printed, and `verdict: UNDETERMINED` — never an
    absent file that a reader is left to interpret.
    """
    print(f"[CANNOT CHECK] {GATE_NAME}: {detail}", file=sys.stderr)
    if _vx is not None:
        _vx.announce_vacuous(GATE_NAME, code)
    else:                                                     # pragma: no cover
        print(f"VACUOUS_PASS: {GATE_NAME} examined nothing (reason: {code})",
              file=sys.stderr)
    if json_path:
        doc = {
            "schema": REPORT_SCHEMA,
            "gate": GATE_NAME,
            "verdict": "UNDETERMINED",
            "rc": RC_UNDETERMINED,
            "refusal": {"code": code, "detail": detail},
            "questions": [],
            "note": "The merge condition was NOT evaluated. This document "
                    "records a refusal to judge, which is not a pass and not "
                    "a finding.",
        }
        doc["digest"] = digest_of(doc)
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out, doc, indent=2)
    return RC_UNDETERMINED


def main(argv: Optional[List[str]] = None) -> int:
    ap = _Parser(
        prog="ppa_pr_scope_check.py",
        description="Decide which Appendix C review questions apply to a "
                    "change-set, and whether each applicable one is backed by "
                    "evidence a machine can re-verify.")
    ap.add_argument("--repo", default=None,
                    help="repository root (default: the git root of this file)")
    ap.add_argument("--base", default=None, help="base git ref")
    ap.add_argument("--head", default=None, help="head git ref")
    ap.add_argument("--changed-file", default=None,
                    help="file of changed paths, one per line; enables the "
                         "PATH arm only")
    ap.add_argument("--diff-file", default=None,
                    help="unified diff to feed the CONTENT arm when no git "
                         "range is available")
    ap.add_argument("--answers", default=None,
                    help="the PR's answers document "
                         f"({ANSWERS_SCHEMA})")
    ap.add_argument("--catalogue", default=None,
                    help=f"override the question catalogue (default: "
                         f"{CATALOGUE_NAME} beside this program)")
    ap.add_argument("--json", default=None, help="write the report JSON here")
    args = ap.parse_args(argv)

    # `GATEKEEPER_CHANGED_PATHS` is this repository's existing change-set
    # channel (`tools/ci/_gate_dispatch.sh`, `tools/ci/test_gate_scope.sh`).
    # Honouring it means a gate added to the dispatcher needs no new plumbing.
    # It is a FALLBACK, never an override: an explicit flag always wins, and a
    # value that names a file which is not there is a refusal, not a skip.
    if not args.changed_file and not (args.base and args.head):
        env_paths = os.environ.get("GATEKEEPER_CHANGED_PATHS", "").strip()
        if env_paths:
            args.changed_file = env_paths
    if not args.changed_file and not (args.base and args.head):
        ap.error("supply either --base and --head, or --changed-file "
                 "(or set GATEKEEPER_CHANGED_PATHS)")

    repo = Path(args.repo).resolve() if args.repo else \
        _find_repo_root(Path(__file__).resolve().parent)

    try:
        catalogue = _load_catalogue(args.catalogue)
        answers_present, answers_doc = _load_answers(args.answers)

        if args.changed_file:
            cp = Path(args.changed_file)
            if not cp.is_file():
                raise _Refusal("CHANGE_SET_MISSING",
                               f"--changed-file not found: {cp}")
            paths = [ln.strip() for ln in
                     cp.read_text(encoding="utf-8").splitlines() if ln.strip()]
        else:
            paths = changed_paths_from_git(repo, args.base, args.head)

        if not paths:
            raise _Refusal("CHANGE_SET_EMPTY",
                           "the change-set contains no paths, so there is no "
                           "surface to decide applicability from")

        diff_text: Optional[str] = None
        if args.diff_file:
            dp = Path(args.diff_file)
            if not dp.is_file():
                raise _Refusal("DIFF_MISSING",
                               f"--diff-file not found: {dp}")
            diff_text = dp.read_text(encoding="utf-8", errors="ignore")
        elif args.base and args.head:
            diff_text = diff_text_from_git(repo, args.base, args.head)
    except _Refusal as exc:
        return _refuse(exc.code, exc.detail, args.json)

    content_arm_ran = diff_text is not None
    path_hits = detect_path_surfaces(paths)
    if content_arm_ran:
        adds, removes = changed_lines(diff_text)
        content_hits, masking = detect_content_surfaces(
            adds, removes,
            source_of=_source_reader(repo, args.head),
            base_source_of=_source_reader(repo, args.base, base_side=True))
    else:
        content_hits, masking = [], {}

    declared_scope = []
    if answers_doc:
        raw = answers_doc.get("declared_scope") or []
        if isinstance(raw, list):
            declared_scope = [str(t).strip() for t in raw if str(t).strip()]

    tokens: Set[str] = {t for h in path_hits + content_hits for t in h["tokens"]}
    tokens |= set(declared_scope)

    answers_by_id: Dict[int, Dict[str, Any]] = {}
    if answers_doc:
        for a in answers_doc.get("answers") or []:
            if isinstance(a, dict) and "question" in a:
                try:
                    answers_by_id[int(a["question"])] = a
                except (TypeError, ValueError):
                    continue

    rows = evaluate(repo, catalogue, tokens, content_arm_ran,
                    answers_by_id, answers_present)
    report = build_report(repo, catalogue, paths, path_hits, content_hits,
                          content_arm_ran, declared_scope, answers_present,
                          answers_doc, rows, args.base, args.head, tokens,
                          masking)
    rc, verdict = verdict_of(report)
    report["verdict"] = verdict
    report["rc"] = rc
    report["digest"] = digest_of(
        {k: v for k, v in report.items() if k != "digest"})

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out, report, indent=2)

    print(f"[{verdict}] {GATE_NAME}: "
          f"{report['summary']['applicable']} applicable, "
          f"{report['summary']['not_applicable']} N/A, "
          f"{report['summary']['undetermined']} undetermined "
          f"(arms: path=RUN content="
          f"{'RUN' if content_arm_ran else 'NOT_RUN'})")
    print(f"  tokens: {', '.join(report['detector']['effective_tokens']) or '(none)'}")
    for r in rows:
        if r["status"] in ("SATISFIED", "NOT_APPLICABLE"):
            continue
        print(f"  [{r['status']}] Q{r['question']} ({r['section']}): "
              f"{r['text']}")
        if r.get("detail"):
            print(f"      {r['detail']}")
    if rc == RC_UNDETERMINED:
        print(f"[CANNOT CHECK] {GATE_NAME}: applicability of "
              f"{report['summary']['undetermined']} question(s) was not "
              f"established; this is not a pass", file=sys.stderr)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - the guard, not the path
        # PPA_INTERFACES §1: 3 is INTERNAL ERROR. A traceback here exits 1, the
        # code reserved for a FINDING about the change under review -- so a crash
        # would read as "this PR fails the checklist", a verdict nothing reached.
        print(f"[REFUSE] {GATE_NAME}: internal error "
              f"{type(exc).__name__}: {exc}. Nothing was decided. rc=3 "
              f"(NOT a finding about the change under review).", file=sys.stderr)
        sys.exit(3)
