#!/usr/bin/env python3
"""
flow_gate_enforcement_audit.py — which flow gates can actually STOP a run, and
which only get to complain afterwards (#306).

The defect
----------
`cts_quality_check` exists, is wired into `flow/phase1_phase2_phase3.yaml`, has
tests, and FAILed correctly on the SAME cell across three consecutive plugin
versions. The flow ran to completion every time: post_cts.def 44 MB,
routed.def 181 MB, post_hold.def 44 MB. It is the one gate that could have
caught #300 (the clock port bound to a 0-sink decoy) at source. It caught it
three times and stopped nothing. Eleven gates FAILed in that same run.

Root cause, measured by this program: the step runners execute the flow's
`program_exit_zero` gates NOWHERE. The gates are evaluated only by
`flow_compliance_check`, which the runner invokes as `final_audit` — the LAST
step, after every artefact has already been written. So a gate cannot block the
step it guards; it can only describe, afterwards, a run that already happened.

A gate that FAILs but cannot block differs from no gate at all only in that the
failure is searchable later.

What this audits
----------------
For every `program_exit_zero` gate in the flow definition:

  ENFORCED    a runner spawns it inline AND the EXIT STATUS of that spawn
              reaches a control-flow decision, so it can stop the step it
              guards
  AUDIT_ONLY  its verdict cannot stop the step. The per-gate `wiring` field
              says WHY (see #884 below): the runner may never name it, may
              spawn it and throw the status away, or the status's journey may
              leave the set of shapes this analysis can decide.
  DECLARED    the gate program declares its own intent in its docstring via
              `ENFORCEMENT: blocking` or `ENFORCEMENT: advisory`
  UNDECLARED  no declaration — the intent is unknown, which is how 66 of 72
              gates ended up de-facto advisory without anyone deciding that

A note on what counts as a declaration (#886): the two lines above MENTION the
token in prose. Until #886 this audit read them as a declaration about ITSELF,
because the pattern was unanchored. A declaration must OPEN its line; a mention
inside a sentence is not one. Several gates say in prose that they carry no
declaration, and the old pattern read each of those as declaring one.

Silence is not a decision (#886)
--------------------------------
UNDECLARED + AUDIT_ONLY was, until #886, the one state this audit could never
fail on. The only failing shape was "DECLARES blocking, wired AUDIT_ONLY", so
the audit could only fail a gate that had already gone to the trouble of
stating an intent — and saying nothing was the reliable way to stay clean.
Measured on this tree after #885: 113 of 150 gates are in that state while the
audit prints PASS. The class is now RECORDED in its own shrink-only register
and any NEW member fails.

Its OWN register, deliberately. `known` is documented — in this file, in
`flow_gate_enforcement_baseline.json` and in `test_316_the_recorded_debt_is_
named_not_hidden` — as "gates that DECLARE an intent they are not wired for".
A gate that declares NOTHING is not a member of that set, and merging the two
grew a shrink-only register from 0 to 86 entries in one commit, which
`test_306_register_never_grows` correctly refused. Different debt, different
paydown (state an intent, or invoke it inline), so: two registers, one file.

What ENFORCED used to mean (ORGANIC #884, fixed 2026-08-09)
----------------------------------------------------------
It meant the gate's FILENAME appeared inside a string literal in a runner. A
runner that spawns a gate and discards its exit status is textually identical
to one that stops the step on it, so four gates were reported ENFORCED while
their verdict was thrown away: `bsdl_emit`, `dfm_screen_check`,
`rtl_hygiene_lint`, `sdc_syntax_check`. MEASURED on the real tree: ENFORCED 21
-> 16 once the status, rather than the name, decides.

This program DESCRIBES; it does not change flow behaviour. Turning audit-only
gates into blocking ones is a deliberate product decision with real blast
radius (11 gates FAILing in one run means those runs start failing — correctly,
but that is an owner's call, not a side effect of an audit tool).

How the flow definition is read (ORGANIC #885, fixed 2026-08-09)
---------------------------------------------------------------
Until #885 this audit found gates by matching a REGEX over the flow YAML's raw
text. `\\s*` in that pattern spans newlines, so against the NESTED clause form
the flow uses for every conditional gate the match ran off the end of the line
and captured the next YAML key: 31 clauses collapsed into one literal gate
named `command`. The audit reported 120 gates where 150 are wired, so 31 real
gate programs were audited by nothing — and `post_route_signoff_corner_check`,
which IS invoked inline and CAN block, was credited with nothing.

The flow definition is now PARSED with PyYAML — the same loader
`flow_compliance_check` uses to execute these clauses — and walked
structurally, so this audit reads the grammar the engine runs rather than an
approximation of it. A flow it cannot parse is a hard error (rc 2), never a
shorter gate list: an under-count here is indistinguishable from a flow with
fewer gates, which is the exact class of lie this program exists to catch.

Where an intent can be WIRED (three venues, 2026-08-17)
-------------------------------------------------------
`orphan` asserts something strong — "declares an intent and NOTHING runs it" —
so it is only as sound as the list of places it looked:

  1. `flow/phase1_phase2_phase3.yaml`   the flow definition
  2. `tools/ci/*.sh`                    the repo-hygiene shell suite (#886)
  3. `gatekeeper_review.py`             the repo-gate suite's PYTHON entry
                                        point, added 2026-08-17

Venue 3 exists because #1696 moved where the hygiene tier is ENTERED.
`gatekeeper_review.repo_hygiene_gate` runs `repo_hygiene_parallel.py` when the
tree has one and only falls back to `tools/ci/repo_hygiene_gates.sh` when it
does not; the coordinator then shards that shell suite beneath itself. So the
tier's entry point is a Python program that no `.sh` file names. v1.10.59 gave
`repo_hygiene_parallel` a truthful `ENFORCEMENT: blocking` docstring and this
audit answered ORPHANED — "reachable from nothing at all" — about a program
whose rc turns the landing verdict to REQUEST_CHANGES. The gate had not
regressed; the audit was reading two venues out of three.

The venue list is PRINTED with every ORPHANED finding, and a venue that is not
present on the tree under audit is reported as such rather than counted as
having cleared anybody.

Where this audit itself runs
---------------------------
`tools/ci/repo_hygiene_gates.sh` invokes it BLOCKING (since v1.6.29, whose
subject was "a checker only its own TEST runs has judged nothing"), and
`tools/gatekeeper-land.sh` invokes that suite before any landing. Two tests
also execute it against the shipped tree. It reports the whole gap on every run
and still exits 0, because the gap is RECORDED below rather than silently
enforced — which is what lets a loud finding ride in a blocking gate without
turning the tree red on debt nobody has decided to pay yet.

Exit codes:
    0  audit completed
    1  a finding NEW since the recorded baseline, in EITHER register:
         `known`             contradiction  declares blocking, wired AUDIT_ONLY
                             orphan         declares an intent and is reachable
                                            from nothing at all — checked
                                            against THREE venues, which the
                                            report names (see below)
         `undeclared_known`  undeclared     AUDIT_ONLY and declares nothing
                                            (#886). Before #886 only the first
                                            two shapes could fail, so a gate
                                            that said nothing was exempt by
                                            construction — 113 of 150 gates
                                            were in that state while this audit
                                            printed PASS.
       A recorded entry that NO LONGER HOLDS is not a failure and never was
       one honestly: it is the debt being PAID, the direction this register
       exists to encourage. It is reported as a TIGHTENING and recorded by
       `--record-shrink`, which writes `previous & current` and cannot add.
       Failing it made the cheapest way to keep this audit green "fix nothing",
       and the remedy it named — `--write-baseline` — is the one write that
       would ALSO record every new finding of the same run as accepted debt.
    2  NOT CHECKED: I/O error, the flow definition could not be parsed, or the
       residual baseline states no readable measurement (absent, unreadable,
       truncated). An explicitly empty register is still a measurement and
       the first offender against it still exits 1.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet_baseline as _ratchet  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None  # type: ignore[assignment]

_HERE = Path(__file__).resolve().parent
_RUNNERS = ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
            "vibe_ic_one_shot_runner.py", "phase23_one_shot_runner.py",
            "phase1_one_shot_runner.py", "analog_one_shot_runner.py")
# The three gate slots `flow_compliance_check._evaluate_gate` actually
# dispatches on. This audit must read the SAME grammar the flow engine reads —
# see `gates_in_flow` for the defect that motivated parsing instead of matching.
# #306 — `advisory_` is the non-blocking slot; a gate wired there IS wired.
_GATE_SLOTS = ("program_exit_zero", "optional_program_exit_zero",
               "advisory_program_exit_zero")
# A DECLARATION is a line that IS the declaration — `ENFORCEMENT:` opens the
# line, allowing only what can legitimately precede it: indentation, a `#`
# comment marker, or the quote that opens a one-line docstring
# (`"""ENFORCEMENT: advisory"""`). A MENTION of the token inside prose is not a
# declaration. Backticks are deliberately NOT in that prefix set: in this repo
# they are how a docstring quotes the token while talking ABOUT it.
#
# #886: the unanchored form read PROSE as intent. The worst case was this very
# file: the sentence above documenting the convention names both values, and
# the audit read it as a declaration ABOUT ITSELF. It stayed hidden only
# because the orphan glob could not reach a `*_audit.py`; widening that glob
# made the audit report itself as an ORPHAN declaring blocking. Same false
# positive in `analog_corner_margin_check`, `drc_report_check`,
# `lvs_report_check`, `professional_tb_check` and `phase3_one_shot_runner`,
# all of which discuss the token in backticks — several of them precisely to
# say they carry NO declaration.
#
# `[ \t]` and not `\s`: `\s` crosses newlines, so a bare `ENFORCEMENT:` at the
# end of one line would bind to a `blocking` that is prose on the next.
# Measured over all 120 in-flow gates: anchoring changes no gate's verdict.
#: THE ANCHORED-DECLARATION SHAPE, SPELT ONCE (2026-08-30).
#: The prefix set above is a RULE, and a rule that is re-typed at a second
#: declaration token is a rule with two values. `advisory_clause_states_its_
#: reason` reads an `ADVISORY_REASON:` declaration and must read it by the same
#: rule this file already applies to `ENFORCEMENT:` — including the #886
#: anchoring that keeps prose from counting — so the shape is a BUILDER here
#: and the token is its argument. Nothing about `ENFORCEMENT:` changes: the
#: pattern this produces for it is byte-for-byte the one it replaced, which
#: `test_declaration_shape_is_spelt_once` pins.
def declaration_re(token: str, value: str) -> "re.Pattern[str]":
    """A compiled matcher for `<TOKEN>: <value>` as a DECLARATION.

    A declaration OPENS its line, allowing only what can legitimately precede
    it: indentation, a `#` comment marker, or the quote that opens a one-line
    docstring. Backticks are deliberately excluded — in this repo they are how
    a docstring quotes a token while talking ABOUT it, and reading that as a
    declaration is #886.
    """
    return re.compile(
        r"""^[ \t]*(?:\#[ \t]*)?(?:["']{1,3}[ \t]*)?"""
        + re.escape(token) + r""":[ \t]*""" + value,
        re.IGNORECASE | re.MULTILINE)


_DECL_RE = declaration_re("ENFORCEMENT", r"(blocking|advisory)\b")
# The second channel: intent stated in the JSON the gate emits. Captures the
# WHOLE right-hand side, not just a leading string literal — see
# `declared_intent` for why a value-only match reads a conditional expression
# as an unconditional declaration.
#: How far into a gate's source the ENFORCEMENT declaration is looked for.
#: NAMED because it is a rule two places have to agree on, and a number that
#: exists in two places is a number that will disagree. A declaration past this
#: point is PRESENT AND UNREAD -- correctly spelt, opening its own line, and
#: reported as UNDECLARED -- so the tests that guard a gate's declaration
#: import this rather than re-typing it. Measured 2026-08-22: two paragraphs of
#: prose added above a declaration moved it to byte 4371 and silently undid it.
DECL_WINDOW_BYTES = 4000

_VERDICT_MODE_RE = re.compile(r'"verdict_mode":\s*([^,\n}]+)')
_LONE_MODE_RE = re.compile(r'^"(BLOCKS|ADVISES)"$')


def _flow_def(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    return _HERE.parent / "flow" / "phase1_phase2_phase3.yaml"


class FlowGrammarError(RuntimeError):
    """The flow definition could not be read with the flow engine's own
    grammar. Never downgraded to a partial gate list: a shorter list reads as
    `fewer gates exist`, which is the exact lie this audit was written to
    catch."""


def _first_token(cmd: str) -> Optional[str]:
    """The gate PROGRAM name is the first whitespace-delimited token of the
    command, exactly as `_check_program_exit_zero` shlex-splits it."""
    parts = cmd.split()
    return parts[0] if parts else None


#: The ONE top-level section of the flow document the engine dispatches from.
#:
#: `flow_compliance_check.main` reads `steps = flow.get("steps", [])` and every
#: gate it evaluates comes from that list. A clause anywhere else in the
#: document is declared and DISPATCHED BY NOTHING — see
#: `_undispatchable_rows` for the measurement that put this constant here, and
#: `test_on_pass_review_clauses_are_dispatched_by_nothing` for the control that
#: fails if `flow_compliance_check` ever stops reading exactly this key.
DISPATCHED_SECTION = "steps"


def _walk_clauses(node, out: List[dict], section: Optional[str] = None) -> None:
    """Collect every gate clause in the document, at any nesting depth.

    The flow definition nests gates under `gate:`, `all_of:`, `any_of:` and
    per-step lists, so the walk is recursive and structural rather than
    positional — a gate is wherever one of `_GATE_SLOTS` is a mapping key.

    `section` is the TOP-LEVEL key the clause was found under, carried down so
    a caller can tell a clause the engine dispatches from one it does not.
    """
    if isinstance(node, dict):
        for key, val in node.items():
            if key in _GATE_SLOTS:
                # Both shapes the flow engine accepts (see
                # `flow_compliance_check._evaluate_gate`): a bare command
                # STRING, or a MAPPING carrying `command:` (plus optional
                # `condition_files_exist:`).
                cmd = val.get("command") if isinstance(val, dict) else val
                name = _first_token(cmd) if isinstance(cmd, str) else None
                # `clause` is the clause MAPPING as written, or `{}` for the
                # bare-string form. Carried so a caller can read a per-clause
                # key -- `absent_condition_reason`, `advisory_reason` -- without
                # opening the YAML a second time with a second walk. An
                # ADDITIVE key: every existing consumer reads this dict by
                # name, and none enumerates its keys.
                out.append({"slot": key, "gate": name, "command": cmd,
                            "clause": val if isinstance(val, dict) else {},
                            "section": section,
                            "dispatchable": section == DISPATCHED_SECTION})
            _walk_clauses(val, out, section)
    elif isinstance(node, list):
        for item in node:
            _walk_clauses(item, out, section)


def clauses_in_flow(flow: Path) -> List[dict]:
    """Every gate clause IN THE DOCUMENT, in document order, each tagged with
    whether the flow engine would dispatch on it.

    THE FIRST LINE OF THIS DOCSTRING USED TO SAY "every gate clause the flow
    engine would dispatch on", AND IT WAS A SUPERSET. The walk starts at the
    whole document; `flow_compliance_check` reads `flow.get("steps", [])` and
    nothing else. MEASURED on 4689d581d: 226 clauses, 221 under `steps:` and 5
    under `stages:` — the five `on_pass_review:` gates, one per stage — so five
    clauses were counted as wired into an engine that cannot reach them. Each
    clause now carries `section` and `dispatchable`; nothing is dropped from
    the list, so every count this audit publishes is unchanged.

    THE DEFECT THIS REPLACED (ORGANIC #885, measured 2026-08-09). The previous
    implementation matched
    `(?:optional_|advisory_)?program_exit_zero:\\s*["']?([\\w./-]+)` over the
    RAW TEXT. `\\s*` spans newlines, so against the nested clause form the flow
    definition uses everywhere for conditional gates:

        - optional_program_exit_zero:
            command: "spare_cell_preservation_check . --json ..."
            condition_files_exist: [...]

    the match ran past the end of the line and captured the NEXT YAML key. All
    31 such clauses collapsed into one literal gate named `command`, so the
    audit reported 120 gates instead of 150 and 31 real gate programs — among
    them `post_route_signoff_corner_check`, which IS wired inline and blocking
    — were audited by nothing at all. An enforcement audit that cannot see a
    gate cannot report that gate is unenforced, so the gap it exists to measure
    was under-reported by 31.

    Parsing with PyYAML — the same loader `flow_compliance_check` uses — means
    the audit reads the grammar the engine executes, not an approximation of
    it, so a future clause shape cannot silently drop out again.
    """
    if yaml is None:
        raise FlowGrammarError(
            "PyYAML required to read the flow definition (pip install pyyaml)")
    try:
        doc = yaml.safe_load(flow.read_text(errors="replace"))
    except yaml.YAMLError as exc:
        raise FlowGrammarError(f"cannot parse {flow}: {exc}") from exc
    out: List[dict] = []
    # Descend one level FIRST so every clause carries the top-level section it
    # was found under. A non-mapping document walks with `section=None`, which
    # is `dispatchable=False` — the safe direction: a document shape this
    # function does not understand is reported as unreachable, never as wired.
    if isinstance(doc, dict):
        for section, val in doc.items():
            _walk_clauses(val, out, section)
    else:
        _walk_clauses(doc, out, None)
    return out


def gates_in_flow(flow: Path) -> List[str]:
    """Unique gate program names wired into the flow definition."""
    return sorted({c["gate"] for c in clauses_in_flow(flow) if c["gate"]})


def runner_source(programs: Path) -> str:
    out = []
    for r in _RUNNERS:
        p = programs / r
        if p.is_file():
            out.append(p.read_text(errors="replace"))
    return "\n".join(out)


def repo_gate_source(programs: Path) -> str:
    """The repo-wide hygiene gate suite, if the tree under audit has one.

    THE SECOND PLACE A DECLARATION CAN BE WIRED (#886). `orphan` asserts
    something strong — "declares an intent and NOTHING runs it, so it fires
    only if somebody types it by hand". Until this function existed the audit
    knew ONE venue, the flow definition, so it made that claim about any
    program absent from a flow YAML, including programs that were never meant
    to appear in one.

    It cost a false positive the moment the orphan glob widened past
    `*_check.py`. `silent_decline_audit` declares `ENFORCEMENT: advisory`, is
    absent from the flow definition, and runs BLOCKING on every landing at
    `tools/ci/repo_hygiene_gates.sh:646` with `--ratchet`. Reporting it as
    unreachable is false, and it would have been recorded as debt nobody could
    pay: it is not a flow gate, so the only way to clear the entry would have
    been to wire it somewhere it does not belong.

    Derived from the tree UNDER AUDIT, never from this file's own location: a
    synthetic tree in a temp dir has no `tools/ci`, gets the empty string, and
    is judged only on what it actually contains.

    COMMENT LINES ARE STRIPPED, for the same reason `_invoked` refuses a bare
    mention in a runner comment: this suite documents heavily, and several
    gates are named in prose explaining why they are NOT wired here. Counting
    that as wiring would be the false negative that mirrors the false positive
    this function removes.
    """
    for base in (programs, *programs.parents[:4]):
        ci = base / "tools" / "ci"
        if ci.is_dir():
            text = "\n".join(p.read_text(errors="replace")
                             for p in sorted(ci.glob("*.sh")))
            return "\n".join(ln for ln in text.splitlines()
                             if not ln.lstrip().startswith("#"))
    return ""


def skill_doc_source(programs: Path) -> str:
    """The plugin's skill documents, if the tree under audit carries any.

    THE FIFTH PLACE A DECLARATION CAN BE WIRED (2026-08-25). A skill line is the
    WEAKEST runner in this repo — an agent reads it and types the command — but
    it is a runner, and for one class of program it is the only correct one.

    The class: a census whose subject is this repo's own source, which answers
    rc 0 with findings BY CONSTRUCTION ("THIS RECORDS DEBT AND NEVER REFUSES").
    Wired into `tools/ci/*.sh` such a program is a gate that CANNOT FAIL;
    declared as a flow clause it bills a per-project run for measuring the
    plugin. `skills/core-agent-loop/SKILL.md` already homes four of them for
    exactly that reason, and `checker_execution_wiring_audit` models the same
    thing as its disclosed "skill-only" class.

    Until this venue existed, those four stayed clean only because none of them
    DECLARES an intent. That is the wrong incentive and this audit's own
    docstring says why: "until a gate states its intent in the one place the
    audit reads, 'wired where it cannot block' and 'nobody decided' are the same
    record." A program that declares `ENFORCEMENT: advisory` and is honestly
    homed in a skill was being told the declaration is what got it accused —
    so the reliable way to stay clean was to say nothing. Measured: 2 gates.

    Read for the same reason and with the same limits as `repo_gate_source` —
    from the tree UNDER AUDIT, so a synthetic tree with no `skills/` gets the
    empty string and is judged on what it actually contains.

    Markdown has no comment syntax to strip, and the risk `repo_gate_source`
    strips comments for does not arise the same way here: a skill that MENTIONS
    a program without a `programs/<name>.py` path does not match, because
    `_invoked_by_suite` requires the `.py`.
    """
    for base in (programs, *programs.parents[:4]):
        skills = base / "skills"
        if skills.is_dir():
            return "\n".join(f.read_text(errors="replace")
                              for f in sorted(skills.rglob("*.md")))
    return ""


def _invoked_by_suite(ci_src: str, gate: str) -> bool:
    """The shell suite invokes a program by PATH, quoted or not (`python3
    "$PG/x.py"` and `python3 programs/x.py` both occur). `ci_src` has already
    had its comment lines removed, so a bare token match is sound here in a way
    it is not in Python source."""
    stem = gate[:-3] if gate.endswith(".py") else gate
    return bool(re.search(r"\b" + re.escape(stem) + r"\.py\b", ci_src))


#: THE THIRD PLACE A DECLARATION CAN BE WIRED (2026-08-17).
#:
#: `repo_gate_source` knew the hygiene tier only as `tools/ci/*.sh`. Since
#: v1.10.46 (772c31dcb, #1696) that is no longer where the tier is ENTERED:
#: `gatekeeper_review.repo_hygiene_gate` picks `repo_hygiene_parallel.py` when
#: the tree has one and falls back to `tools/ci/repo_hygiene_gates.sh` only
#: when it does not, and the coordinator then shards the shell suite beneath
#: itself. So the entry point of the repo-gate suite is a PYTHON program that
#: no `.sh` file names, and the shell-only venue could not see it.
#:
#: MEASURED, not assumed. v1.10.59 (97d5e57a2) added `ENFORCEMENT: blocking` to
#: `repo_hygiene_parallel`'s docstring — a true statement: its rc reaches
#: `GateResult.green`, a red one makes the verdict REQUEST_CHANGES, and
#: `tools/gatekeeper-land.sh` refuses to land on that. The audit answered
#: ORPHANED, i.e. "reachable from nothing at all", which was false. The gate
#: had not regressed; only its declaration was new, and a declaration is what
#: makes a program a candidate for this scan at all.
#:
#: SCOPE, measured 2026-08-17 over all 1173 `*.py` in this directory:
#: `gatekeeper_review`
#: names 18 programs in string literals, and exactly ONE of them declares an
#: intent — `repo_hygiene_parallel`. Widening the venue therefore changes one
#: verdict, the one that was wrong, and clears nothing else. That is the same
#: measurement #886 ran before adding the shell venue for `silent_decline_audit`
#: and it is the bar any FOURTH venue has to clear too: a venue admitted
#: without counting what it excuses is how an orphan scan stops finding orphans.
_REPO_GATE_RUNNERS = ("gatekeeper_review.py",)


def repo_gate_runner_source(programs: Path) -> str:
    """Source of the repo-gate suite's PYTHON entry point, if this tree has one.

    Kept SEPARATE from `repo_gate_source` rather than concatenated into it,
    because the two venues need different matchers and merging them would
    silently apply the loose one to both. `repo_gate_source` strips comment
    lines and is then matched with a bare token, which is sound for shell.
    Python's prose lives in DOCSTRINGS, which are not comment lines and survive
    that stripping — this very file names dozens of gates in its docstrings —
    so a bare token match over Python source would count documentation as
    wiring and quietly excuse every gate anyone wrote a paragraph about.
    `_invoked` is used instead: a string literal or a direct call, never a
    mention in prose.

    Derived from the tree UNDER AUDIT. A synthetic tree with no
    `gatekeeper_review.py` gets the empty string and is judged only on what it
    actually contains.
    """
    out = []
    for name in _REPO_GATE_RUNNERS:
        p = programs / name
        if p.is_file():
            out.append(p.read_text(errors="replace"))
    return "\n".join(out)


def _invoked(src: str, gate: str) -> bool:
    """A runner NAMES the gate — as a subprocess command string or as an
    imported call. A bare mention in a comment does not count.

    #884: this answers "does a runner name this gate", NOT "can this gate stop
    the step". Being named is necessary for enforcement and nowhere near
    sufficient — a runner that spawns a gate and discards its exit status is
    textually identical to one that stops on it. `audit()` uses this only as a
    cheap pre-filter (a gate nobody names cannot be wired under any control
    flow, and skipping the parse for it costs nothing) and decides ENFORCED
    with `gate_wiring()`, which reads the exit status instead of the filename.
    """
    stem = gate[:-3] if gate.endswith(".py") else gate
    if re.search(r"[\"'][^\"'\n]*\b" + re.escape(stem) + r"\.py\b", src):
        return True
    return bool(re.search(r"\b" + re.escape(stem) + r"\s*\.\s*(?:main|check|audit)\s*\(", src))


# ---------------------------------------------------------------------------
# #884 — ENFORCED MUST BE A PROOF ABOUT AN EXIT STATUS, NOT A FACT ABOUT TEXT
#        (and it must survive a refactor that changes nothing)
#
# ROUND 1 of this fix replaced `_invoked()`'s substring search with a parse.
# That was right and insufficient. An independent verifier refuted it with one
# move, reproduced here before this code was written:
#
#     MEASURED. Applying the textbook `extract method` refactor to the very
#     call site the finding names -- design_one_shot_runner.py:11128, the
#     `bsdl_emit` spawn -- moved it from AUDIT_ONLY / INLINE_STATUS_IGNORED to
#     ENFORCED / INLINE_BLOCKING. The refactor changes NOTHING about what the
#     program does: the same argv, the same `except Exception` swallow, the
#     same discarded result at the one call site. Only the shape of the source
#     changed, and the verdict changed with it. ENFORCED went 16 -> 17.
#
# The reason is precise. Round 1 treated a `return` as a control-flow decision
# (it marked every `return` value as an "escape", alongside `raise` and
# `sys.exit`). A `return` is not a decision. It is DELEGATION: the frame hands
# the value to whoever called it, and whether ANYONE acts on it is a different
# question, asked one frame up. Round 1 already knew this for the runners'
# `_run(cmd) -> (rc, out, err)` helper -- it judged that at the CALL SITE
# precisely because the helper returns rather than decides -- and then failed
# to apply the same rule when the returned thing was a whole
# `CompletedProcess` instead of an `rc`. Same delegation, different spelling,
# opposite verdict. That is a check keyed on how the source looks.
#
# WHAT THIS ANALYSIS CAN AND CANNOT DO -- stated up front, because the honest
# answer is not "yes".
#
# "Is this exit status consumed?" is not statically decidable in Python in
# general. `getattr`, a dict of callables, a decorator, `globals()`, a caller
# in a module this audit never parsed -- each of them breaks any whole-program
# claim. So this does NOT attempt a general answer. It answers for a BOUNDED,
# ENUMERATED set of shapes in which every step of the status's journey is
# locally visible (`_site_fate`), and it answers UNPROVEN for everything else.
# UNPROVEN is not a failure of the analysis; it is the analysis refusing to
# guess. The one thing that would be a defect is answering ENFORCED without
# the proof, because ENFORCED is what everyone downstream acts on.
#
# The asymmetry that makes this sound (`_fate_across_return`):
#
#     BLOCKS  is an EXISTENCE claim. ONE visible caller that tests the status
#             proves the gate can stop that run. Partial knowledge is enough.
#     IGNORED is a UNIVERSAL claim -- "no one anywhere reads this". That needs
#             EVERY caller, which cannot be enumerated. So IGNORED is only ever
#             concluded INSIDE ONE FRAME, where the whole live range of the
#             value is visible. Across a frame boundary the strongest negative
#             this reports is UNPROVEN.
#
# The four wiring verdicts; only the first can stop a step:
#
#   INLINE_BLOCKING        a runner spawns the gate and its exit status
#                          reaches a control-flow decision -- an
#                          if/while/assert/ternary test, a comprehension
#                          filter, the argument of `sys.exit`, or a
#                          `check_returncode()`/`check=True` raise nothing
#                          swallows.
#   INLINE_STATUS_IGNORED  a runner spawns the gate and the status provably
#                          has no reader at all, within the frame that
#                          produced it. The #884 class: it costs the runtime
#                          of a real gate and buys nothing, and it looks wired
#                          both to a reader and to this audit's previous self.
#   INLINE_UNPROVEN        named in a runner, but the status's journey leaves
#                          the set of shapes above. NOT enforcement: unknown
#                          is not yes.
#   NOT_INVOKED            no runner names it at all.
#
# ROUND 2b -- WHAT ATTACKING ROUND 2 THE SAME WAY TURNED UP. Round 2 was then
# put through the same treatment it had just survived, with a wider battery of
# behaviour-preserving spellings (20 drops, 6 genuinely-wired controls). Four
# more verdicts turned out to depend on spelling rather than meaning, and all
# four are fixed here rather than written down as caveats:
#
#   1. `if cp.returncode != 0: pass` came back INLINE_BLOCKING. Adding a branch
#      that does nothing is behaviour-preserving by the strictest reading, and
#      it manufactured ENFORCED -- #884 in one more spelling. A branch with no
#      effect at all is no longer a decision (`_is_inert_branch`).
#   2. `_dispatch(project, "g.py")` and `prog = "g.py"` / `_dispatch(project,
#      prog)` disagreed: the name-flow was seeded only from ASSIGNMENTS, so
#      only the second reached the dispatcher (`_carries`).
#   3. Delegation CHAINS -- `_emit` returning `_spawn(...)` -- went cold one
#      frame short, so a caller that really did test the status was invisible
#      (`_return_carriers` now runs to a fixed point).
#   4. Caught only because a claim in this very comment was CHECKED instead of
#      asserted. It first read "no runner aliases `subprocess`, so not
#      recognising an alias is harmless". `grep` says otherwise:
#      phase3_one_shot_runner.py:38406 does `import subprocess as _sp_fc` and
#      spawns `flow_compliance_check.py` through it. That launch site was
#      invisible to this analysis. It happens to DISCARD its status, so no
#      number moved -- but "no number moved" was luck, not the argument that
#      had been written down. `_collect_subprocess_names` now reads the module
#      under every name it is bound to.
#
# 2, 3 and 4 were wrong in the SAFE direction (a real blocker read as
# UNPROVEN), and they are still fixed: a verdict that moves when an author
# renames a module or binds a local is the defect this file is about, whichever
# way it moves.
#
# KNOWN RESIDUAL, stated rather than hidden: reaching a branch TEST is where
# "consumed" is drawn. A branch that reads the status, and whose arms DO
# something but nothing that stops the step (`"PASS" if rc == 0 else
# "PASS_W_WARN"`), is still counted as consumption. `_is_inert_branch` closes
# only the case where the branch has no effect whatsoever, which is decidable
# from the branch alone. Going further means knowing what "stops a step" means
# in each runner -- a question about the branch BODY and about runner
# semantics, not about the call site -- so it is a separate finding, and it is
# not reachable by reshaping a call site, which is the vector this round
# answers.
#
# chip-AGNOSTIC by construction: nothing here knows a design, PDK, vendor or
# cell name. It reads Python control flow.
# ---------------------------------------------------------------------------

#: THE SECOND MODULE THAT STARTS A PROCESS. `_progress_run` is the
#: progress-supervised drop-in for `subprocess.run`; a runner that spawns a
#: gate through `_pr.run(...)` is spawning it just as surely as one that spawns
#: it through `subprocess.run(...)`.
#:
#: MEASURED, and this is the failure it fixes. When the direct-timeout lane
#: converted the runners, three gates — slot_pad_budget_check, pad_ring_check
#: and pad_assignment_gen — went from wired to "declares an intent it is not
#: wired for" WITHOUT ANY WIRING CHANGING. The launches were still there; this
#: audit could no longer see them, so it answered from the launcher's spelling.
#: That is the same species of defect the `sp_aliases` note below already
#: names: answering from a nickname instead of from the control flow.
_PROGRESS_RUN_MODULE = "_progress_run"

#: `subprocess.<attr>(...)` entry points that start a process, and WHAT each
#: hands back. The carrier matters: `run` returns an object you must ask for
#: the status, `call` returns the status itself, `check_call` raises instead.
#: Round 1 collapsed these into one "spawn" notion and then had to special-case
#: its way back out.
_SPAWN_CARRIER = {
    "run": "process",
    "Popen": "process",
    "call": "status",
    "check_call": "raise",
    "check_output": "raise",
    # `_progress_run.run_best_effort` — the progress-supervised drop-in's
    # tolerant face. Same carrier as `run`: it hands back a CompletedProcess
    # and the caller must ask it for the status.
    "run_best_effort": "process",
}
_SPAWN_ATTRS = frozenset(_SPAWN_CARRIER)
#: THE SECOND SANCTIONED WAY TO START A PROCESS.
#:
#: This module could read exactly one launch vocabulary, `subprocess.<attr>`.
#: The plugin has another, and is actively being MOVED onto it:
#: `loop_watchdog_compliance_check` REFUSES a raw `subprocess.run` and directs
#: the author to `_watchdog.run_supervised`, because a wall-clock timeout
#: answers "how long has it been" instead of "is it working". So the two gates
#: pulled against each other -- satisfying the one that demands supervision
#: took the launch site out of the vocabulary of the one that traces exit
#: statuses, and a gate whose status was PROVABLY ignored silently became
#: merely UNPROVEN. Measured on `design_one_shot_runner._run`:
#: `rtl_hygiene_lint` INLINE_STATUS_IGNORED -> INLINE_UNPROVEN, on a change
#: that altered nothing about whether anybody reads its rc.
#:
#: Losing resolution is not a neutral outcome here: UNPROVEN is this audit's
#: "unknown", and #884's whole subject is that unknown must not be reported as
#: enforcement. An audit that goes blind as the tree migrates would report a
#: shrinking debt that is not shrinking.
#:
#: `completed_process(cmd, res)` adapts a supervised run to a real
#: `CompletedProcess`, so its result IS a process carrier and is read through
#: the ordinary `.returncode` -- no new status attribute is introduced, and a
#: supervised launch is traced exactly as a `subprocess.run` one is.
_WD_SPAWN_CARRIER = {
    "completed_process": "process",
}
_WD_SPAWN_ATTRS = frozenset(_WD_SPAWN_CARRIER)
#: Attributes of a `CompletedProcess`/`Popen` that ARE the exit status.
_STATUS_ATTRS = frozenset({"returncode", "check_returncode", "wait", "poll"})
#: `sys.exit(rc)` / `os._exit(rc)` — the status becomes the process's own exit
#: code, which is as load-bearing as an `if`.
_EXIT_ATTRS = frozenset({"exit", "_exit"})
_EXIT_NAMES = frozenset({"exit", "SystemExit"})
#: How many renames to follow while the status stays in one frame
#: (`ok = rc == 0` ... `if not ok:`). Bounded so the audit always terminates.
_MAX_VALUE_HOPS = 4
#: How many hops to follow a gate NAME from its literal to the process that
#: spawns it (`"g.py"` -> table -> loop variable -> argv list).
_MAX_NAME_HOPS = 4
#: How many FRAME boundaries to cross when a status is returned. Two is enough
#: for `spawn -> helper -> caller`; past that, UNPROVEN.
_MAX_FRAME_HOPS = 2

INLINE_BLOCKING = "INLINE_BLOCKING"
INLINE_STATUS_IGNORED = "INLINE_STATUS_IGNORED"
INLINE_UNPROVEN = "INLINE_UNPROVEN"
NOT_INVOKED = "NOT_INVOKED"
#: Weakest to strongest; `audit()` keeps the strongest wiring across runners.
_WIRING_ORDER = (NOT_INVOKED, INLINE_UNPROVEN, INLINE_STATUS_IGNORED,
                 INLINE_BLOCKING)
#: Everything that is not this cannot stop the step it guards.
BLOCKING_WIRING = INLINE_BLOCKING

#: module scope, for the (scope, name) pairs the name-flow analysis carries
_MODULE_SCOPE = 0

#: per-launch-site verdicts, weakest to strongest
_IGNORED, _UNPROVEN, _BLOCKS = "IGNORED", "UNPROVEN", "BLOCKS"
_SITE_ORDER = (_IGNORED, _UNPROVEN, _BLOCKS)
#: how a launch site's verdict names the gate's wiring
_SITE_TO_WIRING = {_BLOCKS: INLINE_BLOCKING,
                   _UNPROVEN: INLINE_UNPROVEN,
                   _IGNORED: INLINE_STATUS_IGNORED}


def _mark(root: ast.AST, sink: Set[int]) -> None:
    for n in ast.walk(root):
        sink.add(id(n))


def _stored_names(target: ast.AST) -> List[str]:
    return [n.id for n in ast.walk(target)
            if isinstance(n, ast.Name) and n.id != "_"]


def _is_inert_stmt(node: ast.AST) -> bool:
    """A statement with no effect whatsoever: `pass`, `...`, a bare string."""
    return (isinstance(node, ast.Pass)
            or (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)))


def _is_inert_branch(node: ast.AST) -> bool:
    """An `if` BOTH of whose arms provably do nothing.

    MEASURED HOLE, found by attacking this program's own round-2 fix:

        cp = subprocess.run([... "gate.py" ...])
        if cp.returncode != 0:
            pass

    came back INLINE_BLOCKING. Adding a dead branch changes nothing a process
    can observe, so it is a behaviour-preserving edit — and it moved a gate
    into the ENFORCED column. That is the #884 defect in one more spelling, so
    it is closed here rather than written down as a caveat.

    The rule is deliberately NARROW, and it is about the branch, not about the
    runner: it does not ask the unanswerable question "does this branch body
    STOP the step" (that needs each runner's notion of stopping — a separate
    finding). It asks only whether the branch has any effect AT ALL. `while`
    is excluded: `while cond: pass` spins forever, which is very much an
    effect. `assert` is excluded: it raises.
    """
    if not isinstance(node, ast.If):
        return False
    return (all(_is_inert_stmt(s) for s in node.body)
            and all(_is_inert_stmt(s) for s in node.orelse))


def _strongest(verdicts: Sequence[str]) -> str:
    return max(verdicts, key=_SITE_ORDER.index)


class _RunnerModule:
    """One runner module, parsed and indexed for the only question ENFORCED
    can honestly mean: does the exit status of the process that runs this gate
    reach a decision?

    Conservative in ONE direction throughout. Every branch that runs out of
    road answers UNPROVEN, never ENFORCED.
    """

    def __init__(self, text: str, name: str = "<runner>") -> None:
        self.name = name
        self.tree = ast.parse(text)
        self.parent: Dict[int, ast.AST] = {}
        self.func_of: Dict[int, Optional[ast.AST]] = {}
        self.module_funcs: Dict[str, ast.AST] = {}
        #: ids of nodes inside an if/while/ternary/assert test or a
        #: comprehension filter — reaching one of these IS a decision.
        self.test_ids: Set[int] = set()
        #: ids of nodes passed to `sys.exit`/`os._exit` — the status becomes
        #: the process's exit code.
        self.exit_arg_ids: Set[int] = set()
        #: ids of nodes inside a `return` value. NOT a decision — delegation.
        #: Round 1's defect was filing these with `sys.exit`.
        self.return_ids: Set[int] = set()
        self.loads: Dict[Tuple[int, str], List[ast.Name]] = {}
        self.stores: Dict[Tuple[int, str], List[int]] = {}
        #: every string constant naming a `.py` file, for gate lookup
        self.py_consts: List[ast.Constant] = []
        #: name-flow carriers, collected once — these modules are tens of
        #: thousands of lines and the flow analysis revisits them per gate.
        self.binders: List[ast.AST] = []
        self.calls: List[ast.Call] = []
        self.calls_by_name: Dict[str, List[ast.Call]] = {}
        #: module-level function names that appear somewhere OTHER than as the
        #: callee of a call. Such a name may have been handed to a table, a
        #: decorator or a scheduler, so this audit cannot claim to see its
        #: callers and will not resolve a `return` through it.
        self.aliased_names: Set[str] = set()
        #: names the `subprocess` MODULE is reachable under. `subprocess`
        #: itself, plus every `import subprocess as X`. Measured need: one
        #: runner does `import subprocess as _sp_fc` inside a function and
        #: spawns through it. Recognising only the literal spelling would make
        #: that launch site invisible — the analysis would be answering from
        #: the module's nickname, which is the same species of defect as
        #: answering from the gate's filename.
        # UNION OF TWO LANES, and the audit must see BOTH vocabularies or it
        # goes blind on whichever one it was not taught. `_watchdog` arrived at
        # v1.12.22; `_progress_run` arrives with this lane. They are different
        # modules, so neither replaces the other: a spawn reached through either
        # is still a spawn, and an audit that follows only one reports
        # INLINE_UNPROVEN about code that is provably enforced.
        self.sp_aliases: Set[str] = {"subprocess", _PROGRESS_RUN_MODULE}
        #: the same, for the watchdog module — `import _watchdog as _wd`.
        self.wd_aliases: Set[str] = {"_watchdog"}
        #: bare names bound by `from _watchdog import completed_process`.
        self.wd_funcs: Dict[str, str] = {}
        #: bare names bound to a subprocess entry point by `from subprocess
        #: import run as r` — name -> the entry point it is.
        self.sp_funcs: Dict[str, str] = {}
        self._assign_index: Dict[Tuple[int, str], List[ast.Assign]] = {}
        self._collect_subprocess_names()
        self._build()
        #: name -> carrier, for module functions that hand a spawn's result
        #: back to their caller. A function that RETURNS the result has
        #: DELEGATED the decision, so it is judged at its call sites.
        self.wrappers: Dict[str, tuple] = self._return_carriers()
        #: (call, carrier, arg_names, arg_node_ids)
        self.launches: List[tuple] = self._launch_sites()
        self._wiring_cache: Dict[str, str] = {}

    # -- construction ------------------------------------------------------
    def _collect_subprocess_names(self) -> None:
        """Every name through which this module can start a process.

        Deliberately scope-INSENSITIVE: a local `import subprocess as _sp` in
        one function is recorded for the whole module. That over-approximates
        only if some unrelated variable shares the alias, which would at worst
        make an extra call site visible — and every call site is then judged on
        its own exit status, so a spurious one cannot reach INLINE_BLOCKING
        without a real decision behind it.
        """
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in ("subprocess", _PROGRESS_RUN_MODULE):
                        self.sp_aliases.add(a.asname or a.name)
                    elif a.name == "_watchdog":
                        self.wd_aliases.add(a.asname or "_watchdog")
            elif isinstance(node, ast.ImportFrom) and node.module in (
                    "subprocess", _PROGRESS_RUN_MODULE):
                for a in node.names:
                    if a.name in _SPAWN_ATTRS:
                        self.sp_funcs[a.asname or a.name] = a.name
            elif isinstance(node, ast.ImportFrom) and node.module == "_watchdog":
                for a in node.names:
                    if a.name in _WD_SPAWN_ATTRS:
                        self.wd_funcs[a.asname or a.name] = a.name

    def _build(self) -> None:
        stack: List[tuple] = [(self.tree, None)]
        while stack:
            node, fn = stack.pop()
            self.func_of[id(node)] = fn
            for ch in ast.iter_child_nodes(node):
                self.parent[id(ch)] = node
                nf = ch if isinstance(
                    ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                stack.append((ch, nf))
        for f in self.tree.body:
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.module_funcs.setdefault(f.name, f)
        callee_ids: Set[int] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
                # An `if` whose arms provably do nothing is not a decision —
                # see `_is_inert_branch`. Marking its test would let dead code
                # manufacture ENFORCED.
                if not _is_inert_branch(node):
                    _mark(node.test, self.test_ids)
            elif isinstance(node, ast.comprehension):
                self.binders.append(node)
                for t in node.ifs:
                    _mark(t, self.test_ids)
            elif isinstance(node, ast.Return) and node.value is not None:
                # DELEGATION, not a decision — see `_fate_across_return`.
                _mark(node.value, self.return_ids)
            elif isinstance(node, ast.Call):
                self.calls.append(node)
                f = node.func
                if isinstance(f, ast.Name):
                    callee_ids.add(id(f))
                    self.calls_by_name.setdefault(f.id, []).append(node)
                if ((isinstance(f, ast.Attribute) and f.attr in _EXIT_ATTRS
                     and isinstance(f.value, ast.Name)
                     and f.value.id in ("sys", "os"))
                        or (isinstance(f, ast.Name) and f.id in _EXIT_NAMES)):
                    for a in node.args:
                        _mark(a, self.exit_arg_ids)
            if isinstance(node, (ast.For, ast.AsyncFor, ast.Assign)):
                self.binders.append(node)
            if isinstance(node, ast.Name):
                key = (self._scope(node), node.id)
                if isinstance(node.ctx, ast.Load):
                    self.loads.setdefault(key, []).append(node)
                else:
                    self.stores.setdefault(key, []).append(node.lineno)
            elif (isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and ".py" in node.value):
                self.py_consts.append(node)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign):
                sc = self._scope(node)
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self._assign_index.setdefault(
                            (sc, t.id), []).append(node)
        for name, fn in self.module_funcs.items():
            if getattr(fn, "decorator_list", None):
                # A decorator rebinds the name; the callers we can see are not
                # necessarily calling THIS function body.
                self.aliased_names.add(name)
        for (sc, nm), nodes in self.loads.items():
            if nm not in self.module_funcs:
                continue
            if any(id(n) not in callee_ids for n in nodes):
                self.aliased_names.add(nm)
        for (sc, nm) in self.stores:
            if nm in self.module_funcs and sc == _MODULE_SCOPE:
                self.aliased_names.add(nm)

    def _scope(self, node: ast.AST) -> int:
        f = self.func_of.get(id(node))
        return id(f) if f is not None else _MODULE_SCOPE

    # -- what a spawn / a helper hands back --------------------------------
    def _spawn_carrier(self, call: ast.Call) -> Optional[tuple]:
        """`("process"|"status"|"raise", None)` if this call starts a process.

        Reads the module through EVERY name it is bound to (`self.sp_aliases`,
        `self.sp_funcs`), not the literal token `subprocess`.
        """
        f = call.func
        attr = None
        if isinstance(f, ast.Attribute) and f.attr in _SPAWN_ATTRS:
            base = f.value
            if isinstance(base, ast.Name) and base.id in self.sp_aliases:
                attr = f.attr
        elif isinstance(f, ast.Name):
            if f.id in self.sp_funcs:
                attr = self.sp_funcs[f.id]
            elif f.id in ("check_call", "check_output"):
                attr = f.id
        if attr is None:
            # The watchdog vocabulary, read through every name it is bound to,
            # exactly as the subprocess one is.
            if isinstance(f, ast.Attribute) and f.attr in _WD_SPAWN_ATTRS:
                base = f.value
                if isinstance(base, ast.Name) and base.id in self.wd_aliases:
                    return (_WD_SPAWN_CARRIER[f.attr], None)
            elif isinstance(f, ast.Name) and f.id in self.wd_funcs:
                return (_WD_SPAWN_CARRIER[self.wd_funcs[f.id]], None)
            return None
        if attr == "run" and _RunnerModule._check_true(call):
            return ("raise", None)
        return (_SPAWN_CARRIER[attr], None)

    def _assigns_of(self, scope: int, name: str) -> List[ast.Assign]:
        return self._assign_index.get((scope, name), [])

    def _origin(self, node: ast.AST, scope: int, depth: int = 0,
                known: Optional[Dict[str, tuple]] = None) -> Optional[str]:
        """`"status"` / `"process"` / None — what this expression carries.

        STRUCTURAL ONLY. Round 1 also accepted a bare name SPELLED like an exit
        status (`rc`, `code`, `ret`, ...) as proof that it WAS one. That is a
        name coincidence deciding a verdict — the same species as the defect
        being fixed, one level down. A name is now believed only when it can be
        traced to a `.returncode` or to a spawn that returns the status.

        `known` carries the wrappers found so far, so `return _spawn(...)` —
        delegation to a function that itself returns a spawn result — is
        recognised as carrying that same result. Without it a two-frame chain
        reads as "no spawn here" and the analysis stops one frame short.
        """
        if depth > 2 or node is None:
            return None
        if isinstance(node, ast.Attribute) and node.attr in _STATUS_ATTRS:
            return "status"
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in _STATUS_ATTRS:
                return "status"          # `p.wait()` / `p.poll()`
            c = self._spawn_carrier(node)
            if c and c[0] in ("status", "process"):
                return c[0]
            if known and isinstance(f, ast.Name):
                k = known.get(f.id)
                if k and k[0] in ("status", "process"):
                    return k[0]
            return None
        if isinstance(node, ast.Name):
            for a in self._assigns_of(scope, node.id):
                o = self._origin(a.value, scope, depth + 1, known)
                if o:
                    return o
        return None

    def _return_carriers(self) -> Dict[str, tuple]:
        """Module functions that hand a spawn's result back to their caller.

        Three carriers, because the runners use all three and Round 1 only
        recognised two:

            ("status", None)   `return cp.returncode`
            ("process", None)  `return subprocess.run(...)`   <-- the shape the
                               verifier's extract-method refactor produces, and
                               the one Round 1 scored as a control-flow decision
            ("tuple", i)       `return cp.returncode, cp.stdout, cp.stderr`
                               — the runners' `_run` house helper

        In every case the function has DELEGATED: enforcement is decided at its
        CALL SITES, not by the `return` itself.

        RUN TO A FIXED POINT, because delegation CHAINS. `_emit` may do nothing
        but `return _spawn(project)`, and `_spawn` is the one that touches
        `subprocess`. A single pass sees no spawn inside `_emit`, so `_emit`
        was not a wrapper, so a caller that DID test the status one frame
        further out was invisible and a genuinely blocking gate came back
        INLINE_UNPROVEN. That is the mirror image of #884 — the same verdict
        moving on the same non-difference in spelling — so it is fixed in the
        same change rather than left as a convenient under-count.
        """
        out: Dict[str, tuple] = {}
        for _ in range(_MAX_NAME_HOPS):
            grew = False
            for name, fn in self.module_funcs.items():
                if name in out:
                    continue
                sc = id(fn)
                if not any(self._spawn_carrier(c) or self._delegates_to(c, out)
                           for c in ast.walk(fn) if isinstance(c, ast.Call)):
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Return) or node.value is None:
                        continue
                    v = node.value
                    if isinstance(v, ast.Tuple):
                        # CZT2-17 — BOTH CARRIER KINDS, exactly as the scalar
                        # branch below already accepts both. This branch matched
                        # only "status", so a helper that returns the PROCESS
                        # inside a tuple -- `return cp, None`, the shape of a
                        # helper that hands back both the result and an early
                        # exit -- was not recognised as delegating at all. The
                        # spawn inside it was then judged INSIDE ITS OWN FRAME,
                        # where the value is returned and never tested, and came
                        # back INLINE_STATUS_IGNORED.
                        #
                        # That contradicts this module's own soundness rule,
                        # stated a hundred lines up: IGNORED is a UNIVERSAL
                        # claim and "is only ever concluded INSIDE ONE FRAME
                        # ... across a frame boundary the strongest negative
                        # this reports is UNPROVEN". A returned value HAS
                        # crossed the boundary. So this was not a missing
                        # feature, it was the asymmetry producing the one
                        # verdict the module promises never to guess.
                        #
                        # MEASURED: `phase3_one_shot_runner._run_producer`
                        # returns `(CompletedProcess, StepResult | None)` and
                        # every caller reads `cp.returncode` to decide the step
                        # -- `signoff_metrics_aggregate` came back AUDIT_ONLY /
                        # INLINE_STATUS_IGNORED against a `declared: blocking`,
                        # i.e. a contradiction manufactured by the spelling of
                        # a return.
                        idx = kind = None
                        for i, e in enumerate(v.elts):
                            o = self._origin(e, sc, known=out)
                            if o in ("status", "process"):
                                idx, kind = i, o
                                break
                        if idx is not None:
                            out[name], grew = ("tuple" if kind == "status"
                                       else "tuple_process",
                                       idx), True
                            break
                        continue
                    o = self._origin(v, sc, known=out)
                    if o in ("status", "process"):
                        out[name], grew = (o, None), True
                        break
            if not grew:
                break
        return out

    @staticmethod
    def _delegates_to(call: ast.Call, known: Dict[str, tuple]) -> bool:
        """Is this a call to an already-known wrapper? Then the value coming
        back from it is a spawn result at one remove."""
        f = call.func
        return isinstance(f, ast.Name) and known.get(f.id, ("", None))[0] in (
            "status", "process", "tuple", "tuple_process")

    def _launch_sites(self) -> List[tuple]:
        sites = []
        for node in self.calls:
            carrier = self._spawn_carrier(node)
            if carrier is None:
                f = node.func
                if isinstance(f, ast.Name) and f.id in self.wrappers:
                    carrier = self.wrappers[f.id]
            if carrier is None:
                continue
            names: Set[str] = set()
            ids: Set[int] = set()
            for a in list(node.args) + [k.value for k in node.keywords]:
                for n in ast.walk(a):
                    ids.add(id(n))
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                        names.add(n.id)
            sites.append((node, carrier, names, ids))
        return sites

    # -- "does the exit status reach a decision?" --------------------------
    def _site_fate(self, call: ast.Call, carrier: tuple,
                   depth: int = 0) -> str:
        """_BLOCKS / _IGNORED / _UNPROVEN for the status produced HERE.

        The three are kept apart because they are DIFFERENT repairs, and
        collapsing them repeats #884's mistake in the other direction.
        `_IGNORED` is a claim — "the status provably has no reader" — and is
        only ever concluded inside the one frame that produced the value,
        where the whole live range is visible.
        """
        kind, idx = carrier
        if kind == "raise":
            # A non-zero exit raises here. That IS control flow — unless an
            # enclosing handler swallows it, which is the `bsdl_emit` shape.
            return _IGNORED if self._swallowed(call) else _BLOCKS
        scope = self._scope(call)
        skip = self._handler_ranges(call)
        p = self.parent.get(id(call))
        if kind == "status":
            # the call expression IS the exit status
            return self._fate_of([call], scope, skip, depth)
        if isinstance(p, ast.Expr):
            # a bare statement: the result is not even bound, so nothing can
            # read the status. This is the dfm / bsdl shape.
            return _IGNORED
        if isinstance(p, ast.Return):
            return self._fate_across_return(call, depth)
        if kind == "process":
            if isinstance(p, ast.Attribute) and p.attr in _STATUS_ATTRS:
                return self._fate_of([p], scope, skip, depth)
            if (isinstance(p, ast.Assign) and len(p.targets) == 1
                    and isinstance(p.targets[0], ast.Name)):
                nm = p.targets[0].id
                if nm == "_":
                    return _IGNORED               # explicitly thrown away
                readers = self._attr_loads(scope, nm, p.lineno, skip)
                if not readers:
                    # bound, but the STATUS is never asked for. `sdc_syntax_
                    # check`'s shape: `r = subprocess.run(...)` and `r`
                    # thereafter only ever yields `.stdout`.
                    return _IGNORED
                return self._fate_of(readers, scope, skip, depth)
            return _UNPROVEN
        if kind == "tuple_process":
            # ("tuple_process", i) — element i is the PROCESS, and the status
            # is whatever reads `.returncode` off the name it is bound to.
            # Mirrors the scalar `process` unpack above; the only difference is
            # which element of the tuple target carries it.
            if idx is None:
                return _UNPROVEN
            if (isinstance(p, ast.Assign) and len(p.targets) == 1
                    and isinstance(p.targets[0], ast.Tuple)):
                elts = p.targets[0].elts
                if idx < len(elts) and isinstance(elts[idx], ast.Name):
                    nm = elts[idx].id
                    if nm == "_":
                        return _IGNORED
                    readers = self._attr_loads(scope, nm, p.lineno, skip)
                    if not readers:
                        return _IGNORED
                    return self._fate_of(readers, scope, skip, depth)
            return _UNPROVEN
        # ("tuple", i) — the status is element i of what came back
        if idx is None:
            return _UNPROVEN
        if (isinstance(p, ast.Subscript) and isinstance(p.slice, ast.Constant)
                and p.slice.value == idx):
            return self._fate_of([p], scope, skip, depth)
        if (isinstance(p, ast.Assign) and len(p.targets) == 1
                and isinstance(p.targets[0], ast.Tuple)):
            elts = p.targets[0].elts
            if idx < len(elts) and isinstance(elts[idx], ast.Name):
                nm = elts[idx].id
                if nm == "_":
                    return _IGNORED
                readers = self._loads(scope, nm, p.lineno, skip)
                if not readers:
                    # `rtl_hygiene_lint`'s shape: `rc, out, err = _run(...)`
                    # and `rc` is never read again.
                    return _IGNORED
                return self._fate_of(readers, scope, skip, depth)
        return _UNPROVEN

    def _fate_of(self, nodes: Sequence[ast.AST], scope: int,
                 skip: Sequence[Tuple[int, int]], depth: int) -> str:
        """Where these occurrences of the status value end up.

        An occurrence is one of: a decision (test / `sys.exit` argument /
        unswallowed `check_returncode()`), a `return` (resolved one frame up),
        a rename (followed, bounded), or something this analysis will not
        follow (UNPROVEN). No occurrences at all means nobody reads it, which
        is the only way to earn _IGNORED.
        """
        frontier: List[ast.AST] = list(nodes)
        seen: Set[int] = set()
        unproven = False
        for _ in range(_MAX_VALUE_HOPS):
            nxt: List[ast.AST] = []
            for n in frontier:
                if id(n) in seen:
                    continue
                seen.add(id(n))
                if id(n) in self.test_ids or id(n) in self.exit_arg_ids:
                    return _BLOCKS
                # `cp.check_returncode()` as a bare statement raises on a
                # non-zero exit. Nothing needs to READ the status for it to
                # stop the step, so requiring an `if` here would under-report.
                if (isinstance(n, ast.Attribute)
                        and n.attr == "check_returncode"
                        and isinstance(self.parent.get(id(n)), ast.Call)
                        and not self._swallowed(n)):
                    return _BLOCKS
                if id(n) in self.return_ids:
                    if self._fate_across_return(n, depth) == _BLOCKS:
                        return _BLOCKS
                    unproven = True
                    continue
                a = self._enclosing_assign(n)
                if a is None:
                    if isinstance(self.parent.get(id(n)), ast.Expr):
                        continue      # value discarded as a bare statement
                    # used as a call argument, folded into a message, appended
                    # to a list ... not a decision, and not traceable further.
                    unproven = True
                    continue
                for t in a.targets:
                    for nm in _stored_names(t):
                        nxt.extend(self._loads(scope, nm, a.lineno, skip))
            if not nxt:
                frontier = []
                break
            frontier = nxt
        if frontier:
            unproven = True           # hop budget spent with work outstanding
        return _UNPROVEN if unproven else _IGNORED

    def _fate_across_return(self, node: ast.AST, depth: int) -> str:
        """The status leaves the frame. THIS IS WHERE ROUND 1 WAS REFUTED.

        Round 1 filed `return` with `raise` and `sys.exit` as an "escape" and
        scored it as control flow. It is not: a `return` DECIDES nothing, it
        hands the value to a caller. So this resolves FORWARD into the callers
        instead, and does so asymmetrically:

          * _BLOCKS is an EXISTENCE claim — one visible caller that tests the
            status proves the gate can stop that run. Partial knowledge of the
            caller set is enough to prove it.
          * _IGNORED is a UNIVERSAL claim — "no caller anywhere reads this".
            No static pass over this repo can enumerate every caller of a
            Python function (`getattr`, a table of callables, an importer this
            audit never parsed). So this NEVER answers _IGNORED across a frame
            boundary; the strongest negative it gives is _UNPROVEN.

        The practical consequence, and the point: reshaping a call site can
        move a gate between INLINE_STATUS_IGNORED and INLINE_UNPROVEN — both of
        which say "cannot block" — but it cannot manufacture INLINE_BLOCKING,
        because that still requires finding a caller that actually tests the
        status.

        The carrier is read from `self.wrappers`, i.e. from what the FUNCTION
        returns, never from what the caller of this method guessed: `return
        cp.returncode, cp.stdout, cp.stderr` hands back a TUPLE, and treating
        the caller as receiving a bare status would misread `_run`'s every
        call site.
        """
        if depth >= _MAX_FRAME_HOPS:
            return _UNPROVEN
        fn = self.func_of.get(id(node))
        if fn is None or self.parent.get(id(fn)) is not self.tree:
            return _UNPROVEN                      # nested / method: not indexed
        carrier = self.wrappers.get(fn.name)
        if carrier is None:
            return _UNPROVEN        # what it hands back is not a status at all
        if fn.name in self.aliased_names:
            return _UNPROVEN                      # callers not enumerable
        sites = self.calls_by_name.get(fn.name) or []
        if not sites:
            return _UNPROVEN                      # dead, or dispatched
        for c in sites:
            if self._site_fate(c, carrier, depth + 1) == _BLOCKS:
                return _BLOCKS
        return _UNPROVEN

    def _handler_ranges(self, call: ast.AST) -> List[Tuple[int, int]]:
        """Line spans of the `except` handlers guarding this call.

        A store inside one is a FALLBACK binding, not a rebinding that ends the
        first one's life: `snc = subprocess.run(...)` / `except: snc = None` /
        `if snc is not None and snc.returncode != 0:` is enforcement, and
        treating the handler's assignment as a rebind would hide it.
        """
        out: List[Tuple[int, int]] = []
        cur: Optional[ast.AST] = call
        while cur is not None:
            par = self.parent.get(id(cur))
            if isinstance(par, ast.Try) and cur in par.body:
                for h in par.handlers:
                    out.append((h.lineno, h.end_lineno or h.lineno))
            cur = par
        return out

    @staticmethod
    def _check_true(call: ast.Call) -> bool:
        for k in call.keywords:
            if k.arg == "check":
                return bool(isinstance(k.value, ast.Constant)
                            and k.value.value is True)
        return False

    @staticmethod
    def _catches_process_error(h: ast.ExceptHandler) -> bool:
        """Could this handler catch the error a raising spawn produces?

        A bare `except:` or one naming `Exception`/`CalledProcessError` can.
        `except subprocess.TimeoutExpired:` cannot — a non-zero exit sails past
        it and still stops the step, so counting that handler as a swallow
        would accuse a runner of dropping a verdict it actually enforces.
        """
        if h.type is None:
            return True
        names = set()
        for n in ast.walk(h.type):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
        return bool(names & {"Exception", "BaseException",
                             "CalledProcessError", "SubprocessError"})

    def _swallowed(self, node: ast.AST) -> bool:
        """Is `node` inside a `try` whose handler catches the raise and drops
        it? Then the exception cannot stop anything.
        """
        cur: Optional[ast.AST] = node
        while cur is not None:
            par = self.parent.get(id(cur))
            if isinstance(par, ast.Try) and cur in par.body:
                for h in par.handlers:
                    if (self._catches_process_error(h)
                            and not any(isinstance(n, ast.Raise)
                                        for n in ast.walk(h))):
                        return True
            cur = par
        return False

    @staticmethod
    def _in_ranges(line: int, ranges: Sequence[Tuple[int, int]]) -> bool:
        return any(lo <= line <= hi for lo, hi in ranges)

    def _next_store(self, scope: int, name: str, after: int,
                    skip: Sequence[Tuple[int, int]]) -> int:
        later = [ln for ln in self.stores.get((scope, name), ())
                 if ln > after and not self._in_ranges(ln, skip)]
        return min(later) if later else sys.maxsize

    def _loads(self, scope: int, name: str, after: int,
               skip: Sequence[Tuple[int, int]] = ()) -> List[ast.Name]:
        """Loads of `name` in `scope` between its binding and any rebinding.

        The window matters: `bsdl_emit`'s runner reads `r.returncode` from a
        DIFFERENT `r` (bound eleven lines earlier for the ATPG run). A
        scope-wide search would call that consumption — the same
        proximity-as-evidence mistake #884 is about, one level down.
        """
        stop = self._next_store(scope, name, after, skip)
        return [n for n in self.loads.get((scope, name), ())
                if after < n.lineno < stop]

    def _attr_loads(self, scope: int, name: str, after: int,
                    skip: Sequence[Tuple[int, int]] = ()) -> List[ast.AST]:
        out = []
        for n in self._loads(scope, name, after, skip):
            p = self.parent.get(id(n))
            if isinstance(p, ast.Attribute) and p.attr in _STATUS_ATTRS:
                out.append(p)
        return out

    def _enclosing_assign(self, node: ast.AST) -> Optional[ast.Assign]:
        cur: Optional[ast.AST] = node
        while cur is not None:
            par = self.parent.get(id(cur))
            if isinstance(par, ast.Assign) and cur is par.value:
                return par
            if isinstance(par, (ast.stmt,)) and not isinstance(par, ast.Assign):
                return None
            cur = par
        return None

    # -- "which process runs this gate?" -----------------------------------
    def _taint(self, seed: Set[Tuple[int, str, int]]) -> Set[Tuple[int, str, int]]:
        """(scope, name) pairs that can carry a value onward from `seed`.

        Covers the shapes the runners use: a local (`fixer = PROGRAMS_DIR /
        "g.py"`), a dict/tuple table iterated or `.get()`-ed, and an argv list
        built from either.

        EVERY ENTRY CARRIES ITS BINDING LINE (#884, round 3). Until it did, a
        tainted name was live for the whole scope, and `bsdl_emit` scored
        ENFORCED because a DIFFERENT program's spawn eleven lines earlier
        happened to use a local of the same name. Hoisting an argv into a local
        called `cmd` — the name that function already uses — moved ENFORCED
        16 -> 17; renaming that one local to `bsdl_cmd`, changing nothing else,
        moved it back. A verdict that depends on how a local is SPELLED is the
        exact defect this file is about, so the name side now gets the same
        live-range window `_loads` already applies to the status side: a name
        is live from its binding to its next store in that scope, and nowhere
        else.
        """
        taint = set(seed)
        for _ in range(_MAX_NAME_HOPS):
            grew = False
            for node in self.binders:
                if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                    it = node.iter
                    if not self._mentions(it, taint, self._scope(it)):
                        continue
                    tsc = self._scope(node.target)
                    for nm in _stored_names(node.target):
                        # `ast.comprehension` carries NO lineno of its own, so
                        # falling back to 0 would open the window before the
                        # target exists and close it at the target's own store
                        # — which read a genuinely table-dispatched gate as
                        # unwired. Take the line from the target itself.
                        _ln = (getattr(node, "lineno", None)
                               or getattr(node.target, "lineno", 0))
                        e = (tsc, nm, _ln)
                        if e not in taint:
                            taint.add(e)
                            grew = True
                elif isinstance(node, ast.Assign):
                    sc = self._scope(node)
                    if not self._mentions(node.value, taint, sc):
                        continue
                    for t in node.targets:
                        for nm in _stored_names(t):
                            e = (sc, nm, node.lineno)
                            if e not in taint:
                                taint.add(e)
                                grew = True
            if not grew:
                break
        return taint

    def _live_here(self, taint: Set[Tuple[int, str, int]], scope: int,
                   name: str, line: int) -> bool:
        """Is `name` carrying the gate AT THIS LINE (#884, round 3)?

        A tainted binding reaches from its own line to the next store of that
        name in that scope — the same window `_loads` uses. Outside it the name
        holds someone else's value, and crediting a launch site there is the
        name-coincidence this audit exists to refuse.
        """
        for (s, n, b) in taint:
            if n != name or s not in (scope, _MODULE_SCOPE):
                continue
            # vibe-ic#898 — A MODULE BINDING IS INVISIBLE INSIDE A FUNCTION
            # THAT BINDS THE SAME NAME.
            #
            # Python scoping: a name assigned ANYWHERE in a function body is
            # local for the WHOLE body, so the module-level binding is shadowed
            # there — including on lines above the local assignment. The window
            # test alone could not see this, because it closed a module entry
            # with `_next_store(_MODULE_SCOPE, ...)`, which only knows about
            # module-level stores.
            #
            # Measured: inserting ONE dead module-level line
            # `cmd = "bsdl_emit.py"` — never read, never executed — moved
            # bsdl_emit AUDIT_ONLY -> ENFORCED and the tree 16 -> 17. That is
            # this file's own defect one scope up from where #884 fixed it, and
            # CHEAPER to trigger than the refactor that refuted round 2: dead
            # code sufficed.
            if (s == _MODULE_SCOPE and scope != _MODULE_SCOPE
                    and (scope, n) in self.stores):
                continue
            if b <= line < self._next_store(s, n, b, ()):
                return True
        return False

    def _taint_from_const(self, const: ast.Constant) -> Set[Tuple[int, str, int]]:
        seed: Set[Tuple[int, str, int]] = set()
        a = self._enclosing_assign(const)
        if a is not None:
            sc = self._scope(a)
            for t in a.targets:
                for nm in _stored_names(t):
                    seed.add((sc, nm, a.lineno))
        return self._taint(seed) if seed else set()

    def _mentions(self, expr: ast.AST, taint: Set[Tuple[int, str, int]],
                  scope: int) -> bool:
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if self._live_here(taint, scope, n.id, n.lineno):
                    return True
        return False

    def _carries(self, expr: ast.AST, taint: Set[Tuple[int, str, int]], scope: int,
                 const: Optional[ast.Constant]) -> bool:
        """Does this expression carry the gate name — through a tainted NAME,
        or as the literal itself?

        The literal arm matters because a gate name reaches a dispatcher in two
        spellings that mean the same thing:

            fixer = PROGRAMS_DIR / "g.py"   ...   _dispatch(project, fixer)
            _dispatch(project, PROGRAMS_DIR / "g.py")

        Only the first passes through a binding, so a taint seeded exclusively
        from assignments sees the first and not the second. That is a verdict
        decided by whether the author happened to name an intermediate — a
        spelling difference, which is the whole species of defect #884 is
        about. The dispatcher-blocks direction was measurably lost to it: with
        the literal handed straight to the helper, a gate whose status IS
        tested inside that helper came back INLINE_UNPROVEN.
        """
        if const is not None:
            for n in ast.walk(expr):
                if n is const:
                    return True
        return self._mentions(expr, taint, scope)

    def _site_runs(self, site: tuple, const: ast.Constant,
                   taint: Set[Tuple[int, str, int]]) -> bool:
        call, _carrier, names, ids = site
        if id(const) in ids:
            return True
        # #884 round 3: a name is only evidence WHERE IT IS LIVE. Without this
        # line test, a spawn of a different program was credited to this gate
        # because the two shared a local's name.
        sc = self._scope(call)
        return any(self._live_here(taint, sc, n, call.lineno) for n in names)

    # -- one dispatch hop, argument-precise --------------------------------
    def _param_names(self, fn: ast.AST) -> List[str]:
        a = fn.args
        return [p.arg for p in
                (list(getattr(a, "posonlyargs", [])) + list(a.args))]

    def _tainted_params(self, call: ast.Call, fn: ast.AST,
                        taint: Set[Tuple[int, str, int]], scope: int,
                        const: Optional[ast.Constant] = None) -> Set[str]:
        """WHICH parameters of `fn` receive the gate name at this call.

        THIS IS THE SECOND THING ROUND 1 GOT PATTERN-SHAPED. It asked only
        whether `fn` contained ANY blocking launch site — so a gate name handed
        to a dispatcher that happens to spawn something ELSE blockingly was
        scored ENFORCED on a coincidence of co-location. The name must reach
        the argv of the launch site that is judged.
        """
        params = self._param_names(fn)
        kwonly = {p.arg for p in fn.args.kwonlyargs}
        out: Set[str] = set()
        for i, a in enumerate(call.args):
            if isinstance(a, ast.Starred):
                if self._carries(a.value, taint, scope, const):
                    # `f(project, *g)` — the star expands into every positional
                    # from here on, so the name could land in any of them. It
                    # cannot land in an EARLIER one, which is what keeps this
                    # from tainting the whole signature.
                    out.update(params[i:])
                continue
            if self._carries(a, taint, scope, const) and i < len(params):
                out.add(params[i])
        for k in call.keywords:
            if not self._carries(k.value, taint, scope, const):
                continue
            if k.arg is None:
                out.update(params)
                out.update(kwonly)
            elif k.arg in params or k.arg in kwonly:
                out.add(k.arg)
        return out

    def _dispatch_fate(self, taint: Set[Tuple[int, str, int]],
                       const: Optional[ast.Constant] = None) -> Optional[str]:
        """One hop: the gate name is an ARGUMENT to a helper that spawns it.

        That is how the genuinely-wired step-23/25 sign-off gates and the
        analog A1-A9 gates reach a process. Only launch sites whose argv
        mentions the tainted PARAMETER are judged.

        `const` is threaded through so the literal handed STRAIGHT to the
        helper counts as well as one that went via a local — see `_carries`.
        """
        best: Optional[str] = None
        for call in self.calls:
            f = call.func
            if not isinstance(f, ast.Name):
                continue
            fn = self.module_funcs.get(f.id)
            if fn is None or f.id in self.wrappers:
                # a wrapper RETURNS the status, so its call site was already
                # judged above; following it again would double-count.
                continue
            params = self._tainted_params(call, fn, taint, self._scope(call),
                                          const)
            if not params:
                continue
            inner = self._taint({(id(fn), p, fn.lineno) for p in params})
            lo, hi = fn.lineno, (fn.end_lineno or fn.lineno)
            for site in self.launches:
                scall, carrier, names, _ids = site
                if not (lo <= scall.lineno <= hi):
                    continue
                if not any(self._live_here(inner, id(fn), n, scall.lineno)
                           for n in names):
                    continue
                v = self._site_fate(scall, carrier, 0)
                best = v if best is None else _strongest([best, v])
                if best == _BLOCKS:
                    return best
        return best

    # -- public ------------------------------------------------------------
    def gate_wiring(self, stem: str) -> str:
        if stem in self._wiring_cache:
            return self._wiring_cache[stem]
        self._wiring_cache[stem] = w = self._gate_wiring(stem)
        return w

    def _gate_wiring(self, stem: str) -> str:
        pat = re.compile(r"\b" + re.escape(stem) + r"\.py\b")
        mentions = [c for c in self.py_consts if pat.search(c.value)]
        if not mentions:
            return NOT_INVOKED
        best = NOT_INVOKED
        for m in mentions:
            best = max(best, self._wiring_for(m), key=_WIRING_ORDER.index)
            if best == INLINE_BLOCKING:
                break
        return best

    def _wiring_for(self, const: ast.Constant) -> str:
        taint = self._taint_from_const(const)
        best_site: Optional[str] = None
        for site in self.launches:
            if not self._site_runs(site, const, taint):
                continue
            v = self._site_fate(site[0], site[1], 0)
            if v == _BLOCKS:
                return INLINE_BLOCKING
            best_site = v if best_site is None else _strongest([best_site, v])
        # The dispatch hop is asked EVEN WHEN a direct launch site was found.
        # A gate can be spawned twice — once with its status dropped, once
        # through a helper that tests it — and stopping at the first site would
        # make the answer depend on which spelling the walk happened to reach
        # first. Only the strongest wiring is enforcement, so both are asked
        # and the strongest wins.
        d = self._dispatch_fate(taint, const)
        if d is not None:
            best_site = d if best_site is None else _strongest([best_site, d])
        if best_site is not None:
            return _SITE_TO_WIRING[best_site]
        return INLINE_UNPROVEN


#: Parsing the six runners costs seconds — they are tens of thousands of lines
#: — and callers (this program's own tests among them) audit repeatedly. Keyed
#: on the file's identity AND its mtime/size so a mutated copy is never served
#: from a stale entry: a mutation control that silently re-read the pristine
#: tree would prove nothing, which is this campaign's own failure mode.
_MODULE_CACHE: Dict[tuple, Optional["_RunnerModule"]] = {}


def runner_modules(programs: Path) -> List[_RunnerModule]:
    """Every runner present, parsed. A runner that will not parse is SKIPPED
    rather than assumed enforcing — the audit reports less, never more."""
    mods = []
    for r in _RUNNERS:
        p = programs / r
        if not p.is_file():
            continue
        try:
            st = p.stat()
            key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
        except OSError:
            continue
        if key not in _MODULE_CACHE:
            try:
                _MODULE_CACHE[key] = _RunnerModule(
                    p.read_text(errors="replace"), r)
            except (SyntaxError, ValueError, RecursionError, OSError):
                _MODULE_CACHE[key] = None
        mod = _MODULE_CACHE[key]
        if mod is not None:
            mods.append(mod)
    return mods


def gate_wiring(mods: Sequence[_RunnerModule], gate: str) -> str:
    """The strongest wiring this gate has across all runners."""
    stem = gate[:-3] if gate.endswith(".py") else gate
    best = NOT_INVOKED
    for m in mods:
        best = max(best, m.gate_wiring(stem), key=_WIRING_ORDER.index)
        if best == INLINE_BLOCKING:
            break
    return best



def program_header(text: str) -> str:
    """The part of a program that carries its OWN declaration.

    A program declares its enforcement intent in its HEADER — the leading
    comment block and the module docstring. A `ENFORCEMENT: blocking` line
    inside a nested function's docstring is a note about that STEP, not a
    declaration by the program, and reading it as one is the same class of
    error as counting a prose mention: MEASURED at 2010063c1,
    `design_one_shot_runner.py` carries exactly one anchored declaration, at
    byte 361904, inside `step_step4_functional_evidence`'s docstring in a
    950 KB file. A survey that searched the whole file reported that runner as
    "declaring an intent the audit never reads" and advised moving it above
    the prose, which would have made the runner claim, as a whole program,
    something only one of its steps says.

    `declared_intent` reads `text[:DECL_WINDOW_BYTES]`, which is a PREFIX of
    this header for every shipped gate (measured: the two agree on all of
    them), so the guard and the reader stay one rule rather than two numbers.
    """
    try:
        mod = ast.parse(text)
    except SyntaxError:
        # Unparseable is not a licence to widen: fall back to the window the
        # reader itself uses, never to the whole file.
        return text[:DECL_WINDOW_BYTES]
    body = mod.body
    if body and isinstance(body[0], ast.Expr) and \
            isinstance(body[0].value, ast.Constant) and \
            isinstance(body[0].value.value, str):
        end = body[0].end_lineno or 1
    elif body:
        end = max((body[0].lineno or 1) - 1, 0)
    else:
        return text
    lines = text.splitlines(keepends=True)
    return "".join(lines[:end])


def program_declaration_offset(text: str) -> Optional[int]:
    """Byte offset of a PROGRAM's own enforcement declaration, or None."""
    m = _DECL_RE.search(program_header(text))
    return None if m is None else m.start()


def declared_intent(programs: Path, gate: str) -> Optional[str]:
    stem = gate if gate.endswith(".py") else gate + ".py"
    p = programs / stem
    if not p.is_file():
        return None
    text = p.read_text(errors="replace")
    m = _DECL_RE.search(text[:DECL_WINDOW_BYTES])
    if m:
        return m.group(1).lower()
    # SECOND DECLARATION CHANNEL, measured 2026-07-26. Some gates state their
    # intent in the JSON they EMIT (`"verdict_mode": "BLOCKS" / "ADVISES"`)
    # rather than in an `ENFORCEMENT:` docstring line. This audit read only
    # the docstring, so it reported those gates as UNDECLARED and a wiring
    # decision could be made without ever seeing what they said about
    # themselves.
    #
    # A CONDITIONAL mode is deliberately NOT read as a declaration:
    # `"BLOCKS" if strict else "ADVISES"` says the intent depends on a flag,
    # so claiming either would be inventing a declaration the program did not
    # make. Those stay UNDECLARED, which is the truth.
    modes = set()
    for rhs in _VERDICT_MODE_RE.findall(text):
        m2 = _LONE_MODE_RE.match(rhs.strip())
        if not m2:
            # A conditional / computed value (`"BLOCKS" if strict else
            # "ADVISES"`) is NOT a declaration. The first version of this
            # guard failed on exactly the case it was written for: matching
            # only the string VALUE after the key saw `"BLOCKS"` and nothing
            # else, so a gate whose default mode is ADVISES was reported as
            # declaring blocking. Capture the whole RHS and require it to be
            # a lone literal.
            return None
        modes.add(m2.group(1))
    if len(modes) == 1:
        return {"BLOCKS": "blocking", "ADVISES": "advisory"}[modes.pop()]
    return None


# ---------------------------------------------------------------------------
# THE FOURTH VENUE — a gate the flow names DISPATCHES another gate (2026-08-20)
#
# The three venues above answer "is this program named by the flow, by the CI
# shell suite, or by a repo-gate runner". A program can be reachable by a fourth
# route that none of them can see: a gate the flow DOES name runs it as a
# subprocess. Step 37.5ic is the case that surfaced it — its gate names
# `tapeout_precheck`, which runs `general_precheck` and `tapeout_readiness_check`
# as its two ARMS. Both were reported ORPHANED ("reachable from nothing at all")
# while being dispatched on every evaluation of that step, which is a FALSE
# claim of the exact kind #886 added `repo_gate_source` to stop making.
#
# CLOSURE, NOT ONE HOP. A delegate of a delegate is still reached; stopping at
# one hop would answer a question adjacent to the one being asked. The closure
# is seeded ONLY by programs already reachable through another venue, so a
# cluster of programs that reference each other and are named by nothing cannot
# bootstrap itself into being wired — the seed is what makes the claim true, and
# an unseeded component contributes nothing.
#
# IT USES `_invoked`, THE SAME PREDICATE THE OTHER VENUES USE: a bare mention in
# a comment does not count; the program has to be named as a `<stem>.py`
# subprocess argument or called as `<stem>.main(...)`. A weaker rule here would
# excuse orphans by prose, and "widening the population without widening what
# counts as wired" is the failure this file already records twice.
# ---------------------------------------------------------------------------
def dispatched_by_reachable_gates(programs: Path,
                                  seeds: "set[str]") -> "set[str]":
    """Every program stem transitively DISPATCHED by an already-reachable one.

    Returns the closure MINUS the seeds, so a caller can tell "reached only via
    this venue" from "was already reachable". An unreadable source file is
    skipped rather than treated as empty: a file we could not read is a file we
    did not look in, and crediting it with naming nothing would be this repo's
    recurring "could not read == read and empty" defect.
    """
    stems = {f.stem for f in programs.glob("*.py")}
    reached = set(seeds) & stems
    frontier = set(reached)
    while frontier:
        nxt: "set[str]" = set()
        for stem in frontier:
            f = programs / f"{stem}.py"
            try:
                src = f.read_text(errors="replace")
            except OSError:
                # A FILE WE COULD NOT READ IS A FILE WE DID NOT LOOK IN. It
                # contributes nothing, which is the strict direction: the worst
                # this can do is fail to clear an orphan, never invent a wiring.
                continue
            # CANDIDATES FIRST, `_invoked` SECOND. Asking `_invoked` about all
            # ~1100 stems per source is ~1.2M regex searches over the whole
            # directory and does not finish in a usable time — measured, the
            # audit ran past 900 s. So the names are EXTRACTED in two linear
            # passes over the same regions `_invoked` looks at, and every
            # candidate is then confirmed with `_invoked` itself. The predicate
            # that decides is unchanged; only the number of times it is asked.
            for cand in _dispatch_candidates(src) & (stems - reached):
                if _invoked(src, cand):
                    nxt.add(cand)
        reached |= nxt
        frontier = nxt
    return reached - set(seeds)


#: One quoted string region, exactly the span `_invoked`'s first rule searches
#: (an opening quote up to the next quote or newline).
_QUOTED_REGION_RE = re.compile(r"[\"'][^\"'\n]*")
_DOT_PY_RE = re.compile(r"\b(\w+)\.py\b")
_ENTRY_CALL_RE = re.compile(r"\b(\w+)\s*\.\s*(?:main|check|audit)\s*\(")


def _dispatch_candidates(src: str) -> "set[str]":
    """Every program stem this source could possibly be naming.

    A SUPERSET by construction — it is a cheap pre-filter, and `_invoked` is
    what actually decides. Under-collecting here would silently create orphans,
    so the two rules mirror `_invoked`'s two rules and nothing narrower.
    """
    out: "set[str]" = set(_ENTRY_CALL_RE.findall(src))
    for region in _QUOTED_REGION_RE.findall(src):
        out.update(_DOT_PY_RE.findall(region))
    return out


#: A program stem the candidate regexes above can capture: `\b(\w+)\.py\b`
#: and `\b(\w+)\s*\.\s*(?:main|check|audit)\s*\(` both capture a bare word,
#: so for a stem that IS a bare word "the candidate pass found it" and "the
#: deciding predicate would match it" are the same statement. Anything else is
#: outside what a candidate pass can see and is handed to the predicate.
_WORD_STEM_RE = re.compile(r"\A\w+\Z")


def _suite_candidates(src: str) -> "set[str]":
    r"""Every `<stem>.py` token a shell or markdown venue names, in ONE pass.

    The mirror of `_dispatch_candidates` for `_invoked_by_suite`, whose single
    rule is `\b<stem>\.py\b` over a venue with its comment lines already
    removed. `\b(\w+)\.py\b` captures the SAME token: if `\b<stem>\.py\b`
    matches at some offset then the character before `<stem>` is a non-word one,
    so the greedy `\w+` starting there captures exactly `<stem>` and nothing
    longer — which is why `barfoo.py` yields `barfoo` and never `foo`, exactly
    as the per-stem search refuses it.
    """
    return set(_DOT_PY_RE.findall(src))


def _named_in(names: "set[str]", src: str, stem: str, decide) -> bool:
    """`decide(src, stem)`, not asked when one pass has already ruled it out.

    ONE PASS PER VENUE, NOT ONE PASS PER STEM. `audit` asks four venues about
    every program in the directory, and each question used to be a regex search
    over the whole venue: 1290 stems x a 949 KB skill corpus is the shape this
    file's own `dispatch_candidates` note already measured as "does not finish
    in a usable time", reintroduced for the venues added since. MEASURED at
    c43fe4057 on this tree: 15.66 s for the skill venue, 3.93 s for the
    repo-gate runner, 1.98 s for the shell suite.

    The DECIDER is unchanged — it is still `decide` that says yes. This only
    stops asking it about stems no candidate pass found, and a stem the
    candidate regexes cannot capture is always asked.
    """
    if _WORD_STEM_RE.match(stem) and stem not in names:
        return False
    return decide(src, stem)



def audit(flow: Path, programs: Path) -> dict:
    clauses = clauses_in_flow(flow)
    # A clause the walk reached but could not name is NOT dropped. Silently
    # discarding it would reintroduce #885 in a new shape: an unnamed gate
    # would once again be a gate the audit does not report on. It is surfaced
    # so the flow author sees an unrunnable clause rather than a short tally.
    malformed = [{"slot": c["slot"], "command": c["command"]}
                 for c in clauses if not c["gate"]]
    gates = sorted({c["gate"] for c in clauses if c["gate"]})
    slots: Dict[str, set] = {}
    for c in clauses:
        if c["gate"]:
            slots.setdefault(c["gate"], set()).add(c["slot"])
    src = runner_source(programs)
    src_names = _dispatch_candidates(src)
    mods = runner_modules(programs)
    rows = []
    for g in gates:
        # #884 — ENFORCED is decided by `gate_wiring`, which follows the exit
        # status; `_invoked` only skips the parse for gates no runner names.
        stem_g = g[:-3] if g.endswith(".py") else g
        wiring = (gate_wiring(mods, g)
                  if _named_in(src_names, src, stem_g, _invoked)
                  else NOT_INVOKED)
        rows.append({
            "gate": g,
            "enforcement": ("ENFORCED" if wiring == BLOCKING_WIRING
                            else "AUDIT_ONLY"),
            "wiring": wiring,
            "declared": declared_intent(programs, g),
            "slots": sorted(slots[g]),
        })
    # DECLARED IN THE DOCUMENT, DISPATCHED BY NOTHING — the gap between
    # AUDIT_ONLY and ORPHANED, and until now it fell through it.
    #
    # `ORPHANED` below already carries the right words for this state: "not
    # even the final compliance audit reaches it, so it runs only if someone
    # invokes it by hand". But ORPHANED is defined as "not referenced by the
    # flow definition at all", and these clauses ARE referenced — they are just
    # referenced somewhere the engine never looks. So they were scored
    # AUDIT_ONLY, whose own definition at the top of this file is "its verdict
    # cannot stop the step", which says the final audit RUNS it.
    #
    # MEASURED on 4689d581d, and this is the pair that shows the two states
    # were sharing one word. `provenance_check` and `stage_on_pass_review` come
    # back as byte-identical rows — AUDIT_ONLY / NOT_INVOKED — and on a real
    # published cell (ic/spm/v1.10.18_sky130A) `flow_compliance_check` dispatched
    # 125 gates: `provenance_check` is in that ledger and `stage_on_pass_review`
    # appears zero times. Same row, opposite fact.
    #
    # A gate is listed here only when EVERY clause naming it is outside
    # `DISPATCHED_SECTION`. One dispatchable clause is enough to reach it, so a
    # gate wired in both places is not a finding.
    by_gate: Dict[str, List[dict]] = {}
    for c in clauses:
        if c.get("gate"):
            by_gate.setdefault(c["gate"], []).append(c)
    undispatchable = [
        {"gate": g,
         "sections": sorted({str(c.get("section")) for c in cs}),
         "clauses": len(cs)}
        for g, cs in sorted(by_gate.items())
        if cs and not any(c.get("dispatchable") for c in cs)]

    # #886: a gate that is AUDIT_ONLY and declares NOTHING. This class was
    # structurally exempt from every failing branch below, which is the defect
    # in one line: the audit could only fail on gates that had already gone to
    # the trouble of stating an intent, so NOT stating one was the reliable way
    # to stay clean. 85 of 120 gates were in this class while the audit exited
    # 0 with a PASS. Silence is not a decision — it is the absence of one.
    undeclared_audit_only = [
        {"gate": r["gate"], "enforcement": "AUDIT_ONLY", "declared": None}
        for r in rows
        if r["enforcement"] == "AUDIT_ONLY" and not r["declared"]]
    # ORPHANED: a gate program that DECLARES an enforcement intent but is not
    # referenced by the flow definition at all. Worse than AUDIT_ONLY — not
    # even the final compliance audit reaches it, so it runs only if someone
    # invokes it by hand. Found this way: two gates added earlier in this
    # campaign were never wired into the flow, so they could not fire at all.
    in_flow = {r["gate"] for r in rows}
    orphaned = []
    # #886, TWO changes that are only sound together.
    #
    # (1) The glob used to be `*_check.py` + `*_disclosure.py`, which decided
    # what could be an orphan by FILENAME. A declaration is the signal, not the
    # suffix, and that suffix list could not reach a `*_audit.py` or a `*_lint.py`
    # at all. Every `*.py` is now offered to `declared_intent`; it decides.
    #
    # (2) Widening the POPULATION without widening "what counts as wired" is how
    # a scan turns into noise. Measured over all 1127 `*.py` in this directory,
    # the wider glob surfaces exactly ONE new orphan candidate —
    # `silent_decline_audit` — and it is a FALSE POSITIVE: it runs blocking on
    # every landing from the repo-hygiene suite. An earlier draft of this change
    # recorded it as debt on the strength of not appearing in a flow YAML it was
    # never meant to appear in. `repo_gate_source` is that second venue.
    #
    # (3) 2026-08-17: the repo-gate suite grew a PYTHON entry point above the
    # shell one, so "no repo-gate suite invokes it" stopped being answerable
    # from `tools/ci/*.sh` alone. See `_REPO_GATE_RUNNERS`. The venue list is
    # named in the report, because an unreachability claim that does not say
    # where it looked cannot be checked by the person it accuses.
    src_ci = repo_gate_source(programs)
    src_gate_runner = repo_gate_runner_source(programs)
    src_skill = skill_doc_source(programs)
    # The candidate pass for each venue, computed ONCE — see `_named_in`.
    ci_names = _suite_candidates(src_ci)
    skill_names = _suite_candidates(src_skill)
    gate_runner_names = _dispatch_candidates(src_gate_runner)
    # The fourth venue. Seeded by the flow definition ONLY, so the closure
    # cannot be bootstrapped by a cluster of programs nothing else names.
    dispatched = dispatched_by_reachable_gates(
        programs, {r["gate"] for r in rows}
        | {r["gate"][:-3] for r in rows if r["gate"].endswith(".py")})
    for f in sorted(programs.glob("*.py")):
        stem = f.stem
        if stem in in_flow or f"{stem}.py" in in_flow:
            continue
        if stem in dispatched:
            continue
        if _named_in(ci_names, src_ci, stem, _invoked_by_suite):
            continue
        # The fifth venue — see `skill_doc_source`. Matched with the SAME
        # predicate as the shell suite, so "a skill names it" means a skill
        # gave a runnable `programs/<name>.py` path, not that the name appears
        # somewhere in prose.
        if _named_in(skill_names, src_skill, stem, _invoked_by_suite):
            continue
        # A venue does not get to exempt ITSELF. #886 measured this exact
        # hazard from the other direction: widening the population made the
        # audit read its own docstring as a declaration and report itself as an
        # orphan. `gatekeeper_review.py` names its own path in string literals,
        # so without this guard the suite runner would be its own proof of
        # being wired — which is not a proof of anything.
        if f.name not in _REPO_GATE_RUNNERS and _named_in(
                gate_runner_names, src_gate_runner, stem, _invoked):
            continue
        intent = declared_intent(programs, stem)
        if intent:
            orphaned.append({"gate": stem, "declared": intent,
                             "enforcement": "ORPHANED"})
    contradictions = [r for r in rows
                      if r["declared"] == "blocking"
                      and r["enforcement"] == "AUDIT_ONLY"]
    # What the ORPHANED verdict actually consulted. Reported so the claim is
    # falsifiable: "nothing invokes it" is only as strong as the list of places
    # looked at, and a venue that was EMPTY on this tree (a synthetic fixture
    # with no `tools/ci`, say) is a different fact from a venue that was read
    # and did not name the gate.
    orphan_venues = [
        {"venue": "flow definition", "present": True},
        {"venue": "tools/ci/*.sh", "present": bool(src_ci.strip())},
        {"venue": "/".join(_REPO_GATE_RUNNERS),
         "present": bool(src_gate_runner.strip())},
        # PRESENT is the count, not a boolean, because "no gate dispatches
        # another" and "we never computed the closure" are different facts and
        # a bare False would read as both.
        {"venue": "dispatched by a gate the flow names (transitive)",
         "present": bool(dispatched), "reached": sorted(dispatched)},
        {"venue": "skills/**/*.md (an agent runs it by hand)",
         "present": bool(src_skill.strip())},
    ]
    # See the note beside `declared_weaker_than_wired` in the report below.
    # Computed from the SAME rows the rest of this report is built from, so it
    # cannot describe a different tree than the one just audited.
    declared_weaker_than_wired = [
        {"gate": r["gate"], "declared": r["declared"], "wiring": r["wiring"]}
        for r in rows
        if r["declared"] == "advisory" and r["wiring"] == INLINE_BLOCKING]

    return {
        "orphan_venues": orphan_venues,
        "total_gates": len(rows),
        "total_clauses": len(clauses),
        "enforced": sum(1 for r in rows if r["enforcement"] == "ENFORCED"),
        "audit_only": sum(1 for r in rows if r["enforcement"] == "AUDIT_ONLY"),
        # #884 — the breakdown BEHIND `audit_only`. `status_ignored` is the
        # class this audit used to score as ENFORCED: a real gate really is
        # spawned, and its verdict is thrown away. `unproven` is the honest
        # residue — named by a runner, but the status's journey leaves the set
        # of shapes this analysis can decide, so it is reported as undecided
        # rather than guessed in either direction.
        "wiring": {w: sum(1 for r in rows if r["wiring"] == w)
                   for w in _WIRING_ORDER},
        "status_ignored": sum(1 for r in rows
                              if r["wiring"] == INLINE_STATUS_IGNORED),
        "unproven": sum(1 for r in rows if r["wiring"] == INLINE_UNPROVEN),
        "declared": sum(1 for r in rows if r["declared"]),
        "undeclared": sum(1 for r in rows if not r["declared"]),
        "contradictions": contradictions,
        # THE OTHER DIRECTION, WHICH `contradictions` CANNOT SEE (2026-08-22).
        #
        # `contradictions` is one-directional by construction: it fails a gate
        # that DECLARES blocking and is wired AUDIT_ONLY. The reverse — wired
        # INLINE_BLOCKING while its own file says `advisory` — passed this audit
        # silently, and a reader of that file is told the gate cannot stop the
        # step when it can.
        #
        # MEASURED on origin/main a4caccefe: ONE gate is in that state. It is
        # reported and NOT failed, deliberately, because its case is a genuine
        # collision over what the token means rather than a mistake: it writes
        # `ENFORCEMENT: advisory` and immediately says "(Advisory describes the
        # FINDINGS. The track's EXECUTION is mandatory.)" — finding SEVERITY,
        # which is a different axis from the one this audit measures. Failing it
        # would decide that dispute by reddening a blocking hygiene gate, which
        # is not this program's call. Disclosing it puts the dispute where a
        # flow owner can see it, and stops the next one being added silently.
        "declared_weaker_than_wired": declared_weaker_than_wired,
        "orphaned": orphaned,
        "malformed_clauses": malformed,
        "undeclared_audit_only": undeclared_audit_only,
        # Declared in the document, dispatched by nothing. Reported, never
        # failed: WHERE these clauses should be wired is a flow owner's
        # decision — a step's `gate:` cannot express "after the stage passed",
        # which is what `fires_on: stage_pass` asks for — and #1253's rule
        # applies, "wiring a RED gate turns 'unverified' into 'blocking', which
        # is a different change and not this one".
        "undispatchable": undispatchable,
        "gates": rows,
    }


def _load_baseline_doc(path: Path) -> Optional[dict]:
    """A readable baseline document, or ``None`` when none was measured.

    ``None`` and an explicit empty list are intentionally different values.
    This audit attributes findings with ``current - baseline``; treating an
    absent or truncated artefact as ``{}`` turns every inherited finding into
    a regression, while treating the same state on a clean tree fabricates a
    PASS.  A partial older document may still carry one measured register, so
    it remains readable and the existing UNRECORDED-register logic below owns
    the missing key.
    """
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    registers = ("known", "undeclared_known")
    if not any(key in loaded for key in registers):
        return None
    if any(key in loaded and not isinstance(loaded[key], list)
           for key in registers):
        return None
    if any(not isinstance(entry, str)
           for key in registers
           for entry in loaded.get(key, [])):
        return None
    return loaded


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit which flow gates can actually stop a run.")
    ap.add_argument("--flow", help="flow definition YAML")
    ap.add_argument("--programs", help="programs dir (default: this one)")
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--baseline", help="known-debt file carrying BOTH "
                    "registers: `known` (contradiction/orphan) and "
                    "`undeclared_known` (#886). NEW entries in either fail, "
                    "the recorded ones do not. A register the file does not "
                    "mention is UNRECORDED, which is not the same as empty")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT set; it may only ever shrink")
    ap.add_argument(_ratchet.RECORD_FLAG, dest="record_shrink",
                    action="store_true",
                    help="record a measured TIGHTENING only: write `previous "
                         "& current` for BOTH registers, which can remove "
                         "entries and can never add one. Needs no reason "
                         "string and accepts none, because there is no "
                         "growth for a reason to excuse")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the audit now LOOKS at more than it did (>=30 chars; "
                         "recorded in the baseline beside the previous size)")
    ap.add_argument("--retire-scope-reason", action="store_true",
                    dest="retire_scope_reason",
                    help="acknowledge that this --record-shrink write will "
                         "DELETE the recorded `*_scope_expanded` text, and "
                         "that it has been preserved wherever it belongs. "
                         "Refused without this flag; the refusal prints the "
                         "text verbatim so the write cannot destroy the only "
                         "copy of it")
    a = ap.parse_args(argv)
    flow = _flow_def(a.flow)
    programs = Path(a.programs) if a.programs else _HERE
    if not flow.is_file():
        print(f"IO_ERROR: no flow definition at {flow}", file=sys.stderr)
        return 2
    bl_path = Path(a.baseline) if a.baseline else (
        _HERE / "flow_gate_enforcement_baseline.json")
    doc = _load_baseline_doc(bl_path)
    if doc is None:
        # ``--write-baseline`` is the one operation that CREATES the missing
        # measurement.  It may bootstrap an absent path, but it must not
        # overwrite an existing unreadable/truncated artefact as though the
        # previous measurement had been empty.
        bootstrapping = (a.write_baseline and not bl_path.exists()
                         and not bl_path.is_symlink())
        if not bootstrapping:
            print(
                "NOT CHECKED: no flow-gate enforcement baseline states a "
                f"readable measurement at {bl_path} — absent, unreadable, or "
                "truncated is not a measurement of zero, so no current "
                "finding can be called NEW. Measure this tree and record the "
                "baseline before asking this audit to attribute anything. "
                "See vibe-ic#1705.",
                file=sys.stderr)
            return 2
        doc = {}
    try:
        rep = audit(flow, programs)
    except FlowGrammarError as exc:
        # NEVER degrade to a partial read. A gate list that is short because
        # the parser failed is indistinguishable from a flow with fewer gates,
        # and this audit exists to stop exactly that confusion.
        print(f"IO_ERROR: {exc}", file=sys.stderr)
        return 2
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    pct = 100 * rep["audit_only"] // max(1, rep["total_gates"])
    print("=== flow gate enforcement audit ===")
    print(f"gate clauses in flow def : {rep['total_clauses']}")
    print(f"gates in flow definition : {rep['total_gates']}")
    print(f"  ENFORCED (can block)   : {rep['enforced']}")
    print(f"  AUDIT_ONLY (describes) : {rep['audit_only']}  ({pct}%)")
    print(f"declared intent          : {rep['declared']} "
          f"({rep['undeclared']} UNDECLARED)")
    if rep.get("malformed_clauses"):
        print("\nMALFORMED — a gate slot with no runnable `command`. It runs "
              "nothing,\nso it certifies nothing:")
        for m in rep["malformed_clauses"]:
            print(f"  {m['slot']}: {m['command']!r}")
    if rep.get("orphaned"):
        print("\nORPHANED — declare an intent, are NOT in the flow definition,\n"
              "and no repo-gate suite invokes them either, so not even the\n"
              "final audit reaches them:")
        for o in rep["orphaned"]:
            print(f"  {o['gate']}  (declared {o['declared']})")
        # An unreachability claim that does not say where it looked cannot be
        # checked. A venue marked `not present on this tree` did NOT clear the
        # gate — it was not there to be read — and that is stated rather than
        # folded into the verdict.
        print("  venues consulted for reachability:")
        for v in rep.get("orphan_venues") or []:
            print(f"    {v['venue']}: "
                  f"{'read' if v['present'] else 'not present on this tree'}")
    if rep.get("undeclared_audit_only"):
        print(f"\nUNDECLARED and AUDIT_ONLY — {len(rep['undeclared_audit_only'])} "
              f"gate(s): no runner invokes them inline, and nothing in the gate "
              f"says\nthat was intended. Until #886 this class could not fail "
              f"this audit at all,\nso not declaring an intent was the reliable "
              f"way to stay clean.")
    # A gate that DECLARES blocking and is wired audit-only, or that declares
    # an intent and is reachable from nothing at all, is the very defect this
    # audit names — measured in a gate's own terms. The register held four when
    # #306 opened it and holds ZERO today, all four paid down. Fixing one
    # changes what a real run BLOCKS on, which is the flow owner's decision and
    # not this audit's, so they are recorded as DEBT while this audit blocks
    # anything NEW — the class stops growing without the audit quietly deciding
    # enforcement policy on its own.
    #
    # TWO REGISTERS, NOT ONE (#886). `known`'s stated contract — in this file,
    # in the baseline's own `_comment`, and asserted by
    # `test_316_the_recorded_debt_is_named_not_hidden` — is "gates that DECLARE
    # an intent they are not wired for". A gate that declares NOTHING cannot
    # join that set without making the register's own description false, and an
    # earlier draft that merged them grew a SHRINK-ONLY register from 0 to 86
    # entries in a single commit, which `test_306_register_never_grows`
    # correctly refused. The undeclared class is real debt and must ratchet,
    # but it is DIFFERENT debt, paid down differently: by the gate stating an
    # intent, or by a runner invoking it inline, where a `contradiction::` is
    # paid by reconciling a declaration that already exists.
    now = sorted([f"contradiction::{c['gate']}" for c in rep["contradictions"]]
                 + [f"orphan::{o['gate']}" for o in (rep.get("orphaned") or [])])
    now_u = sorted(f"undeclared::{u['gate']}"
                   for u in (rep.get("undeclared_audit_only") or []))
    def _recorded(key: str) -> Optional[List[str]]:
        """A register that is ABSENT is UNRECORDED, not empty. The two differ:
        an empty register asserts "no debt", an absent one asserts nothing at
        all, and reading absence as emptiness would report every pre-existing
        entry as `paid` the first time a baseline written by an older version
        of this program is read."""
        if key not in doc:
            return None
        return sorted(str(x) for x in (doc.get(key) or []))

    prev = _recorded("known")
    prev_u = _recorded("undeclared_known")
    if a.record_shrink:
        # THE TIGHTENING PATH, AND WHY IT IS NOT `--write-baseline` RENAMED.
        #
        # It writes `previous & current` for each register, which is a SUBSET
        # of what that register already held for every possible measurement.
        # An entry this run found for the first time is absent from `previous`
        # by definition, so it cannot arrive through here — there is no flag,
        # threshold or reason string that changes that, and `write_shrunk`
        # re-checks it on the finished document rather than trusting these two
        # expressions. `--scope-expanded` is therefore not accepted: it exists
        # to excuse GROWTH, and this path has none to excuse.
        #
        # An UNRECORDED register is left unrecorded. Creating one here would be
        # writing a measurement, not shrinking one, and the read path below
        # already says so in its own words.
        if prev is None and prev_u is None:
            print(f"NOT CHECKED: neither register is recorded in "
                  f"{bl_path.name}, so there is no set for a tightening to "
                  f"shrink. Record a measurement first.", file=sys.stderr)
            return 2
        new_known = now if prev is None else _ratchet.shrunk(prev, now)
        new_undecl = now_u if prev_u is None else _ratchet.shrunk(prev_u, now_u)
        left = {"known": _ratchet.departed(prev or [], new_known),
                "undeclared_known": _ratchet.departed(prev_u or [], new_undecl)}
        if not any(left.values()):
            print(f"nothing to record: {bl_path.name} already holds the "
                  f"tightened sets ({len(new_known)} contradiction/orphan, "
                  f"{len(new_undecl)} undeclared)")
            return 0
        doc_out = dict(doc)
        doc_out.update({
            "previous_size": None if prev is None else len(prev),
            "known": new_known,
            "undeclared_previous_size": None if prev_u is None else len(prev_u),
            "undeclared_known": new_undecl,
        })
        # A tightening never widens scope, so any reason recorded against a
        # PREVIOUS widening is cleared rather than carried forward — a reason
        # that outlives the growth it explained reads to the next writer as
        # standing permission.
        #
        # THAT RULE IS RIGHT AND IT DESTROYED A DEFECT REPORT (vibe-ic G17).
        # The clearing used to be SILENT, and `undeclared_scope_expanded` had
        # accumulated an observation that had nothing to do with the scope
        # reason it was appended to:
        #
        #     sdc_syntax_check additionally carries a real hole worth its own
        #     issue: flow declares both required_outputs
        #     reports/phase2/sdc_check.json and program_exit_zero, but the
        #     program writes that JSON UNCONDITIONALLY before exiting 1 ...
        #
        # #2014 G6 ran this write, the field went to `null`, and after that
        # commit the observation existed NOWHERE IN THE TREE. Nothing was
        # wrong with the rule; what was wrong is that a write which deletes
        # prose said nothing about deleting it.
        #
        # SO THE CLEARING IS UNCHANGED AND THE SILENCE IS NOT. A write that
        # would drop a non-empty reason REFUSES, prints the text VERBATIM so
        # the refusal itself is a copy of it, and names the flag that performs
        # the deletion deliberately. A register with no reason recorded is
        # untouched by this — `--record-shrink` behaves exactly as before, or
        # the guard would have cost the shrink to save the prose.
        _reason_fields = ("scope_expanded", "undeclared_scope_expanded")
        _standing = {k: doc.get(k) for k in _reason_fields
                     if isinstance(doc.get(k), str) and doc[k].strip()}
        if _standing and not a.retire_scope_reason:
            print("\n[FAIL] flow_gate_enforcement baseline: this "
                  f"{_ratchet.RECORD_FLAG} write would DELETE a recorded "
                  "reason, and deleting the only copy of a written reason is "
                  "not a side effect a tightening gets to have.", file=sys.stderr)
            for _k, _v in sorted(_standing.items()):
                print(f"\n  {_k}:\n    " + "\n    ".join(_v.strip().splitlines()),
                      file=sys.stderr)
            print("\n  The text above is printed in full so this refusal is "
                  "itself a copy of it. Preserve anything worth keeping where "
                  "it belongs — an issue, a docstring, a test — and then "
                  "re-run with --retire-scope-reason. The reason is still "
                  "spent by the tightening; only the silence is refused.",
                  file=sys.stderr)
            return 1
        doc_out["scope_expanded"] = None
        doc_out["undeclared_scope_expanded"] = None
        if _standing:
            print("retiring the recorded scope reason(s) as asked: "
                  + ", ".join(sorted(_standing)))
        guarded = {}
        if prev is not None:
            guarded["known"] = prev
        if prev_u is not None:
            guarded["undeclared_known"] = prev_u
        try:
            _ratchet.write_shrunk(bl_path, doc_out,
                                  previous_by_register=guarded,
                                  ensure_ascii=False)
        except _ratchet.ShrinkRefused as exc:
            print(f"\n[FAIL] flow_gate_enforcement baseline: {exc}",
                  file=sys.stderr)
            return 1
        for label, entries in sorted(left.items()):
            if entries:
                before = len(prev if label == "known" else prev_u)
                print(_ratchet.report_line(label, entries, before,
                                           before - len(entries)))
        print(f"\nwrote {bl_path} ({len(new_known)} contradiction/orphan, "
              f"{len(new_undecl)} undeclared)")
        return 0
    if a.write_baseline:
        # vibe-ic#900 — RATCHET ON MEMBERSHIP, NOT ON COUNT.
        #
        # `len(n) > len(p)` is not a shrink-only guard. Any write that removes
        # as many entries as it adds passes it, so the register admitted
        # unlimited NEW debt at constant size while its own comment asserted it
        # could only shrink. MEASURED: a prev register holding 76 real entries
        # plus 40 names absent from the tree recomputes to 116 with 40 members
        # prev lacked — `--write-baseline` with NO reason exited 0 and recorded
        # `scope_expanded: null`.
        #
        # And the bypass sat on the normal workflow, which is what made it
        # sharp: the READ path DOES catch the swap and exits 1, and the thing
        # it tells you to run is the WRITE path that does not check membership.
        # The guard was weakest at the exact moment it was consulted.
        added = {"known": sorted(set(now) - set(prev or [])),
                 "undeclared_known": sorted(set(now_u) - set(prev_u or []))}
        if a.scope_expanded is not None:
            reason = a.scope_expanded.strip()
            if len(reason) < 30:
                print("\n[FAIL] --scope-expanded needs a real reason (>=30 "
                      "chars) naming what the audit now looks at that it did "
                      "not before.")
                return 1
            # A LENGTH TEST IS A KEYSTROKE COUNT. `'a' * 34` satisfied the old
            # one. Requiring the reason to NAME an entry it is excusing cannot
            # be met by padding, and is checkable.
            # Match the STEM as well as the filename: entries are recorded as
            # `undeclared::foo_check.py`, but a human writing the reason says
            # "foo_check". Demanding the extension would make an honest reason
            # fail on a technicality — a naming rule that rejects the natural
            # spelling teaches people to paste the raw entry instead of
            # explaining, which is the padding problem again in another form.
            new_names = set()
            for v in added.values():
                for e in v:
                    nm = e.split("::", 1)[-1]
                    new_names.add(nm)
                    if nm.endswith(".py"):
                        new_names.add(nm[:-3])
            if new_names and not any(nm in reason for nm in new_names):
                print("\n[FAIL] --scope-expanded must NAME at least one of the "
                      "entries it excuses, so the reason is about specific "
                      "debt rather than about a number. New entries:\n   "
                      + "\n   ".join(sorted(new_names)))
                return 1
        widened = {}
        for label, p, n in (("known", prev, now),
                            ("undeclared_known", prev_u, now_u)):
            # A register that GREW, or that is being CREATED non-empty, is a
            # claim about scope and needs the reason recorded against IT. A
            # register that did not move records `null`, so a reason given for
            # one can never read afterwards as standing permission for the
            # other — which is how a single flag would have silently licensed
            # future growth in a register it was never about.
            widened[label] = ((p is None and bool(n))
                              or (p is not None and bool(added[label])))
            if widened[label] and a.scope_expanded is None:
                _new = added[label]
                print(f"\n[FAIL] refusing to GROW the baseline `{label}` "
                      f"({'unrecorded' if p is None else len(p)} -> {len(n)}"
                      + (f", {len(_new)} NEW: {', '.join(_new[:8])}"
                         + (" ..." if len(_new) > 8 else "") if _new else "")
                      + f"): "
                      f"this register records debt that must be paid down, "
                      f"never permission to add more. If the audit now LOOKS "
                      f"at more than it did, say so with --scope-expanded "
                      f"'<why>' — a wider scope finding pre-existing debt is "
                      f"not a regression, but it must be recorded, not "
                      f"assumed.")
                return 1
        bl_path.write_text(json.dumps(
            {"_comment": ("Gates that declare an intent they are not wired "
                          "for (vibe-ic#306/#316). MAY ONLY SHRINK. Fixing "
                          "one changes what a real run blocks on — a flow-"
                          "owner decision — so they are recorded, not "
                          "silently enforced here."),
             "previous_size": None if prev is None else len(prev),
             "scope_expanded": a.scope_expanded if widened["known"] else None,
             "known": now,
             "undeclared_comment": (
                 "Gates that are AUDIT_ONLY and declare NO intent at all "
                 "(vibe-ic#886) — enforcement was never decided, which is a "
                 "DIFFERENT defect from declaring one thing and being wired "
                 "another, so it is a SEPARATE shrink-only register. Paid down "
                 "by the gate stating `ENFORCEMENT:` / `verdict_mode`, or by a "
                 "runner invoking it inline. NOT by deleting the entry: the "
                 "audit recomputes this set on every run, so a deleted line "
                 "comes straight back as NEW and fails."),
             "undeclared_previous_size": (
                 None if prev_u is None else len(prev_u)),
             "undeclared_scope_expanded": (
                 a.scope_expanded if widened["undeclared_known"] else None),
             "undeclared_known": now_u}, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {bl_path} ({len(now)} contradiction/orphan, "
              f"{len(now_u)} undeclared)")
        return 0
    rc = 0
    # An UNRECORDED register with findings exits 1 and SAYS why. The previous
    # shape returned 1 here and printed nothing at all, so the one caller that
    # can hit it — a baseline written before the register existed — got a bare
    # non-zero exit from a program whose whole subject is verdicts that do not
    # explain themselves.
    if prev is None:
        if now:
            print(f"\n[FAIL] `known` is UNRECORDED in {bl_path.name} and "
                  f"{len(now)} finding(s) stand. Record them with "
                  f"--write-baseline --scope-expanded '<why>':")
            for k in now:
                print(f"   {k}")
            rc = 1
    else:
        new = [k for k in now if k not in set(prev)]
        paid = [k for k in prev if k not in set(now)]
        if paid:
            # A RATCHET THAT FAILS WHEN IT TIGHTENS IS BROKEN. This branch used
            # to return 1 and tell the operator to run `--write-baseline`, so
            # paying a debt cost a red board and the remedy on offer would also
            # have recorded that run's NEW findings as accepted debt. Reported
            # and recorded now, never failed.
            print(_ratchet.report_line("known", paid,
                                       len(prev), len(prev) - len(paid)))
            for k in paid:
                print(f"   (resolved) {k}")
            print(f"   Record it with:  flow_gate_enforcement_audit.py "
                  f"{_ratchet.RECORD_FLAG}")
        if new:
            print(f"\n[FAIL] {len(new)} NEW gate(s) declare an intent they are "
                  f"not wired for:")
            for k in new:
                print(f"   {k}")
            rc = 1
    # The #886 register reports in its OWN words. The sentence above is FALSE
    # about this class — an `undeclared::` gate declares nothing, so it cannot
    # "declare an intent it is not wired for" — and reusing it would have made
    # this audit's own report a small lie about the defect it had just found.
    if prev_u is None:
        if now_u:
            print(f"\n[FAIL] `undeclared_known` is UNRECORDED in "
                  f"{bl_path.name} and {len(now_u)} gate(s) are AUDIT_ONLY "
                  f"while declaring no intent at all. This class was exempt "
                  f"from this audit by construction until #886; it is debt, "
                  f"not absence of debt. Record it with --write-baseline "
                  f"--scope-expanded '<why>'.")
            rc = 1
    else:
        new_u = [k for k in now_u if k not in set(prev_u)]
        paid_u = [k for k in prev_u if k not in set(now_u)]
        if paid_u:
            # Same ruling as `known` above, in this register's own words: a
            # gate that has since stated an intent, or that a runner now
            # invokes inline, is the debt being paid.
            print(_ratchet.report_line("undeclared_known", paid_u,
                                       len(prev_u), len(prev_u) - len(paid_u)))
            for k in paid_u:
                print(f"   (resolved) {k}")
            print(f"   Record it with:  flow_gate_enforcement_audit.py "
                  f"{_ratchet.RECORD_FLAG}")
        if new_u:
            print(f"\n[FAIL] {len(new_u)} NEW gate(s) are AUDIT_ONLY and "
                  f"declare no intent at all — nothing invokes them where they "
                  f"could block, and nothing in the gate says that was the "
                  f"decision:")
            for k in new_u:
                print(f"   {k}")
            rc = 1
    # PRINTED ON BOTH PATHS, unlike the disclosure below it. That one is about
    # what a PASS is read as meaning; this one is about a gate that is not
    # running at all, and a reader who needs that fact needs it whichever way
    # the exit code went.
    undisp = rep.get("undispatchable") or []
    if undisp:
        print(f"\n  DISCLOSURE — {len(undisp)} gate(s) are declared in the flow "
              f"document but sit OUTSIDE `{DISPATCHED_SECTION}:`, which is the "
              f"only section `flow_compliance_check` reads "
              f"(`steps = flow.get(\"steps\", [])`). Nothing dispatches them: "
              f"not a runner inline, and not the final compliance audit "
              f"either. Not failed here — WHERE they should be wired is a flow "
              f"owner's call, and a step's `gate:` cannot express `fires_on: "
              f"stage_pass`:")
        for u in undisp:
            print(f"    {u['gate']}  {u['clauses']} clause(s) under "
                  f"{', '.join(u['sections'])}:")

    if rc:
        return rc
    print(f"\n[PASS] no NEW enforcement contradiction "
          f"({len(now)} recorded as debt; {len(now_u)} gate(s) recorded as "
          f"UNDECLARED and audit-only)")
    # DISCLOSED ON THE PASS PATH, because the PASS is what gets read as "every
    # declaration matches its wiring". It does not: this class is the one the
    # `contradiction` scan above cannot see, and it does not affect the exit
    # code — see the note beside `declared_weaker_than_wired` in `audit()`.
    weaker = rep.get("declared_weaker_than_wired") or []
    if weaker:
        print(f"  DISCLOSURE — {len(weaker)} gate(s) are wired so they CAN stop "
              f"a step while their own file declares `advisory`. Not failed "
              f"here: `advisory` is used by at least one of them for finding "
              f"SEVERITY, a different axis from the one this audit measures, "
              f"and settling that is a flow owner's call:")
        for w in weaker:
            print(f"    {w['gate']}  declared={w['declared']} "
                  f"wiring={w['wiring']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
