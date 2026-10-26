"""_step_verdict_table.py — the ONE reader that turns a compliance artefact into
a per-step verdict TABLE, and the ONE differ that says which way a step moved.

CHIP_AGNOSTIC: strict-logic — the LOGIC below reads two JSON documents; the ICs
appear only in this docstring, as the evidence for the rules.

WHY THIS EXISTS (OWNER RULING R-0915-86 (1), 2026-09-16)
========================================================
3,713 test files; 173 invoke a real EDA tool; NONE runs an IC end-to-end. The
flow-matrix suite checks that steps have gates WIRED — 45 of 61 cells in one
dimension are stand-ins. Every rule bug found on 2026-09-16 surfaced only when a
REAL run reached a later step: the r26 `stage_on_pass_review` cascade, run16's
INCONCLUSIVE booked as SKIP, the DRV census taken with no parasitics in STA.

So a landing gate has to answer one question about a REAL IC: *did this change
move any step's verdict, and in which direction?* Two programs ask it —
`real_ic_gate` (run the front door on a live checkout) and `audit_replay`
(re-judge a frozen snapshot with the current tree's programs). This module is
the half they share, so there is ONE table shape and ONE direction rule rather
than two that drift. R-0915-85 ("不要設計的疊床架屋"): a second copy of a rule is
the layering the owner banned, and a rule nobody can find is the rule everybody
re-invents.

TWO ARTEFACTS, ONE TABLE — MEASURED, NOT ASSUMED
================================================
`flow_compliance_check` writes the same table under two key names:

    reports/audit/phase23_completion_audit.json   `verdict`  `step_counts`  `command_argv`
    the path given to --json                      `overall`  `counts`       (no argv)

MEASURED 2026-09-16 on `<home>/_frozen/subservient_r26`: one invocation
with `--json` and one without produced `steps[]` lists that are element-for-
element identical (69 steps, identical 18-key step records, identical counts);
only the two top-level key names differ. A reader that knew one shape would read
the other as a table with no verdict, so this one accepts either and says which
it found.

THE DIRECTION RULE IS DERIVED, NOT ENUMERATED
=============================================
`programs/verdict.py` is "the ONE place a flow verdict word is classified"
(R-0915-85 reduced the vocabulary to five AT THE PRODUCERS and folded
`_flow_verdict_tiers` into it). This module therefore adds NO vocabulary. It
ranks a word with that module's own predicates:

    3 FULL_PASS       `is_full_pass`      the only word that satisfies a
                                          predecessor outright
    2 QUALIFIED_DONE  `is_qualified_done` ran, did not fail, measured/certified
                                          less than a full pass
    1 EXCUSED         `is_excused`        exactly what the producer SUBTRACTS
                                          from `total_required` — it did not run
    0 NON_GREEN       `is_non_green`      the producer's failing/missing buckets

A rank DECREASE is a REGRESSION, an INCREASE an IMPROVEMENT, and a word change
at the same rank a LATERAL (a rename or a re-classification that moves nothing).
The lateral tier is not decoration: R-0915-85 is reducing 23 verdict words to 5
AT THE PRODUCERS, and the whole point of this gate during that reform is to tell
a rename apart from a judgement change. A rename that is NOT lateral — say
`SKIPPED-CONDITION` (EXCUSED, rank 1) re-spelled to a word registered nowhere
(a done-claim by subtraction, rank 2) — shows up here as 27 IMPROVEMENTS on SPM,
which is exactly the signal that the new word owes `_flow_verdict_tiers` a home.
That is the anti-drift device working, not a false alarm to be papered over.

EXCUSED RANKS BELOW QUALIFIED-DONE ON PURPOSE. `PASS -> SKIPPED-CONDITION` is the
SKIP laundering R-0915-85 names in its own text ("today's cascade and the SKIP
laundering"): a step that used to run and pass, now not run at all. Ranking
"not run" above "ran and measured little" would make laundering the cheapest way
to green a table, which is the incentive inversion `_flow_verdict_tiers` was
written to delete.

TWO TABLES ARE COMPARABLE ONLY IF THE SAME EXPERIMENT PRODUCED THEM
===================================================================
There are TWO ways two tables can be answers to different questions, and this
module refuses on both. The second one was found BY USING THIS GATE, on its very
first real run, and it cost a wrong headline.

  1. THE INSTRUMENT'S SCOPE — `command_argv`. See the section below.

  2. THE RUN SHAPE — did an AGENT answer the flow's hand-offs, or did a program
     run alone? The flow is program-first + AI-BACKUP: several steps complete by
     handing work to an agent and consuming its answer. `flow_compliance_check`
     names that state itself, in `_AWAITING_EXIT_CODE`'s own comment: *"pass one
     completed and pass two is somebody else's move … a PROGRAM cannot spawn the
     subagent pass two needs."*

     MEASURED 2026-09-16 (R-0915-88), SPM, the published cell
     `ic/spm/v1.21.6_gf180mcuD` versus a program-only run of the same input:

         D1  phase1_expert_parse_track --check-report   cell rc 0 PASS   /  program-only rc 4 INCOMPLETE
         5   formal_proof_evidence_check                cell PASS        /  program-only FAIL

     and the SAME split at SIX trees spanning `845ef5247..a8d39cb70` plus current
     main — the tree never moved either verdict. The cell's own artefacts say why:
     `expert_parse_track.json` records `ai_subtrack.status=CONSUMED,
     observed_ai_consumed=6`, and `phase2/stage1/formal/formal_expert_review.json`
     records `invocation_status=INVOKED, invoked_by="lane icspm3 (formal-verify
     expert role)"` with 5 hand-authored properties. A landing gate runs the front
     door with no agent attached, so it CANNOT reproduce either — and diffing the
     two tables reported "SPM regressed" about a landing that had done nothing.

     `run_shape` is DERIVED, never declared by the reader and never a per-step
     exception list: the run's own `gate_execution_ledger` already records every
     gate's `exit_code`, and the set of gates that exited AWAITING is the set of
     second passes nobody answered. A tier invented tomorrow inherits this for
     free, because the constant is imported from the module that defines it.

     THE LIMIT, STATED. Root (b) above leaves NO awaiting row — its gate exits 1
     like any other failure — so on these two runs it is caught only because D1's
     awaiting row refuses the whole table. A future run whose ONLY difference is
     a (b)-shaped one would still diff. That is the honest bound of a derived
     signal, and the remedy is the one this module already recommends for the
     replay: make the reference a prior run of the SAME gate, where the shape is
     equal by construction.

COMPARABILITY IS CHECKED BEFORE ANY DIFF IS PRINTED
===================================================
MEASURED 2026-09-16, and the reason this section exists: the LAST compliance
invocation of a run overwrites `reports/audit/phase23_completion_audit.json`, so
a stage-scoped invocation replaces the full table with its own. On the two frozen
snapshots the orchestrator supplied:

    <home>/_frozen/subservient_r26      9 steps, argv stage4_compliance.py . --exclude-step 39
    <home>/_frozen/sha256_run16_pass2   9 steps, argv flow_compliance_check.py ... --stage-id stage_analog

while a full `--strict` pass over the same trees yields 69. Diffing 69 against 9
would report 60 REMOVED steps and read as a catastrophic regression; it is an
instrument answering about a different subject. So `diff_tables` REFUSES
(`comparable=False`) unless both tables name the same program and the same
scoping flags, and the caller exits 2 — a refusal, never a pass and never a
"regression" it cannot support.

chip-AGNOSTIC and tool-AGNOSTIC: every function here reads two JSON documents.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import verdict as _tiers

#: Rank names, lowest first. Exposed so a report can print the word rather than
#: the integer, and so a test can pin the ordering without re-typing it.
RANK_NAMES: Dict[int, str] = {
    0: "NON_GREEN",
    1: "EXCUSED",
    2: "QUALIFIED_DONE",
    3: "FULL_PASS",
}

REGRESSION = "REGRESSION"
IMPROVEMENT = "IMPROVEMENT"
LATERAL = "LATERAL"
UNCHANGED = "UNCHANGED"
#: R-0915-139 — a row the reference never had, on a subject that measures HOW
#: EXISTING ROWS ARE READ. Its own direction, not LATERAL: a lateral is a move
#: between two measured words, and there was no first word to move from. It
#: belongs to `added` and to none of `regressions` / `improvements` / `laterals`.
ADDED_NO_REFERENCE = "ADDED_NO_REFERENCE"

#: The two subject kinds the real-IC arm runs, and the ONE thing they disagree
#: about. See `diff_tables`.
SUBJECT_AUDIT_REPLAY = "audit_replay"
SUBJECT_REAL_IC_GATE = "real_ic_gate"

#: Flags that do not change WHICH steps a compliance pass measures, so two
#: invocations differing only in these are still comparable. `--flow 109` is
#: handled explicitly in `_scope_flags`: it is equal to the omitted current
#: default, while a historical public flow name remains part of the frozen
#: experiment's identity. Everything else — `--stage`, `--stage-id`, `--phase`,
#: `--exclude-step`, `--skip-*` — narrows the population and makes the two
#: tables answers to different questions.
_SCOPE_NEUTRAL_FLAGS = {"--json", "--read-only", "--flow-def"}


#: Cached so a consumer that builds many tables pays the owning module's import
#: once. The VALUE is never re-typed here — see `awaiting_exit_code`.
_AWAITING: Optional[int] = None


def awaiting_exit_code() -> int:
    """The flow's OWN constant for "pass one completed and pass two is somebody
    else's move", imported from the module that DEFINES the tier.

    `flow_compliance_check._AWAITING_EXIT_CODE` is the single place this repo
    decides that an exit code means a pending agent pass, and its comment there
    is the contract. A literal `4` here would be a second copy of a rule, which
    is precisely what this module exists to avoid; the import costs 0.44 s and
    is taken lazily so a reader that never asks about run shape never pays it.
    `test_the_awaiting_code_is_the_flows_own` pins the two together.
    """
    global _AWAITING
    if _AWAITING is None:
        import flow_compliance_check as _fcc      # lazy: see docstring
        _AWAITING = int(_fcc._AWAITING_EXIT_CODE)
    return _AWAITING


def run_shape(audit: Dict[str, Any]) -> Dict[str, Any]:
    """WHO ran this flow — a program alone, or a program whose hand-offs an
    AGENT answered.

    DERIVED from the run's own `gate_execution_ledger`, which already records
    every invoked gate's `exit_code`. The gates that exited AWAITING are exactly
    the second passes nobody answered; a run with none of them either had its
    hand-offs answered or was never asked, and in both cases it is a different
    experiment from one that has them.

    Returns `unanswered_second_pass: None` when the artefact carries no ledger —
    "not recorded" is its own outcome, never an empty set. An absent ledger read
    as "nothing was left unanswered" would make every pre-ledger artefact look
    like an agent-driven run, which is the fail-DANGEROUS direction.
    """
    ledger = audit.get("gate_execution_ledger")
    if not isinstance(ledger, list):
        return {"source": "NOT_RECORDED",
                "unanswered_second_pass": None,
                "agent_answered_every_handoff": None,
                "ledger_rows": None}
    aw = awaiting_exit_code()
    gates = sorted({str(r.get("gate")) for r in ledger
                    if isinstance(r, dict) and r.get("exit_code") == aw})
    return {"source": "gate_execution_ledger",
            "awaiting_exit_code": aw,
            "ledger_rows": len(ledger),
            "unanswered_second_pass": gates,
            "agent_answered_every_handoff": not gates}


class TableUnreadable(Exception):
    """The artefact is absent, unparsable, or carries no `steps` list. Raised
    rather than returning an empty table: an empty table diffs as "every step
    removed", which is the fabricated catastrophe this module refuses to print.
    """


def rank(status: Optional[str]) -> int:
    """Where a verdict word sits, using `verdict.py`'s own predicates.

    Order of the tests matters only for cost, not for the answer: the four
    predicates partition the vocabulary.

    R-0915-85 — WHAT THE REDUCTION DID TO THIS LADDER, and why it did not need
    re-designing. The five words map ONE TO ONE onto the four ranks:

        3 FULL_PASS       PASS
        2 QUALIFIED_DONE  PASS_WITH_WAIVERS
        1 EXCUSED         NOT_APPLICABLE
        0 NON_GREEN       FAIL and NOT_MEASURED

    and the last line is the one worth reading twice. Under the old vocabulary
    `INCOMPLETE`, `NOT-MEASURED`, `VACUOUS-PASS` and `STRUCTURE-ONLY` were in
    neither negative set, so by subtraction they ranked 2 — a step that had
    measured NOTHING scored as a qualified done-claim. They are `NOT_MEASURED`
    now and rank 0, so a run that stops measuring something reads as a
    REGRESSION here instead of as a lateral. That is the direction this gate
    exists to catch, and the docstring above predicted it: a rename that is not
    lateral is the signal, not the false alarm.
    """
    try:
        if _tiers.is_full_pass(status):
            return 3
        if _tiers.is_non_green(status):
            return 0
        if _tiers.is_excused(status):
            return 1
        if _tiers.is_done_claim(status):
            return 2
    except _tiers.UnknownVerdictWord:
        # A WORD OUTSIDE THE FIVE, RANKED NON_GREEN AND NEVER TRANSLATED.
        #
        # THIS IS THE ONE PLACE A PRE-REFORM WORD MAY BE READ AT ALL, and the
        # reason is what this module is for: it DIFFS a frozen baseline against
        # the current tree, and every baseline frozen before R-0915-85 speaks
        # the deleted vocabulary. A hard refusal here would make the landing
        # gate unable to read its own three frozen snapshots — it would not
        # stop the old words existing, it would stop anyone measuring them.
        #
        # IT IS NOT A TRANSLATION TABLE, and the difference is the whole point:
        # nothing here maps `SKIPPED-CONDITION` to `NOT_APPLICABLE` or lets a
        # producer go on writing it. The word is ranked 0 — the FAIL-SAFE
        # direction, identical to the empty-word case below — so an unreadable
        # word can only ever make a diff look like a REGRESSION, never like an
        # improvement. `table_from_audit` records which words these were under
        # `pre_reform_words`, so a reader is told the baseline is old rather
        # than being handed a silently-degraded table.
        return 0
    # Only reachable for an empty/None word — a step record with no status at
    # all. That is an absence, not a pass.
    return 0


def rank_name(status: Optional[str]) -> str:
    return RANK_NAMES[rank(status)]


def direction(ref_status: Optional[str], cur_status: Optional[str]) -> str:
    """Which way the word moved. LATERAL is a word change at the same rank."""
    # R-0915-85 deleted `normalize`: with five words there is ONE spelling each
    # and tolerating a second is how a third arrives. A word outside the five
    # reaches `rank` below, where `parse` refuses it by name.
    rs, cs = str(ref_status or ""), str(cur_status or "")
    if rs == cs:
        return UNCHANGED
    rr, cr = rank(ref_status), rank(cur_status)
    if cr < rr:
        return REGRESSION
    if cr > rr:
        return IMPROVEMENT
    return LATERAL


# ── reading a table out of either artefact shape ─────────────────────────────

def table_from_audit(audit: Dict[str, Any], source: str = "") -> Dict[str, Any]:
    """The per-step verdict table, from a completion audit OR a --json report.

    `verdict_refusal_reason` is carried verbatim because it is the artefact's
    OWN statement that its top-level word is a refusal (`INSUFFICIENT_DATA`) and
    not a judgement — see `flow_compliance_check.completion_audit_verdict`. A
    refusal is ranked NON_GREEN: it measured nothing, and "measured nothing"
    must never out-rank "ran and reported little".
    """
    if not isinstance(audit, dict):
        raise TableUnreadable("the artefact is not a JSON object")
    steps = audit.get("steps")
    if not isinstance(steps, list):
        raise TableUnreadable(
            "the artefact carries no `steps` list — it is not a compliance "
            "table (keys: %s)" % ", ".join(sorted(audit)[:12]))

    # Both spellings, measured identical above. `verdict` first: when an
    # artefact carries both, the completion audit's own field is the one its
    # consumers key on.
    verdict = audit.get("verdict", audit.get("overall"))
    verdict_key = "verdict" if "verdict" in audit else (
        "overall" if "overall" in audit else None)
    counts = audit.get("step_counts", audit.get("counts"))

    rows: Dict[str, Dict[str, Any]] = {}
    duplicates: List[str] = []
    #: Words this artefact carries that R-0915-85 deleted. Named, so a reader
    #: knows a baseline predates the reform instead of wondering why half its
    #: steps rank NON_GREEN.
    pre_reform: List[str] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).strip()
        if not sid:
            continue
        if sid in rows:
            # Two records for one step id: the table can no longer say what that
            # step's verdict is. Recorded, never silently last-wins.
            duplicates.append(sid)
        if (s.get("status")
                and _tiers.as_verdict_or_none(s.get("status")) is None):
            pre_reform.append(str(s.get("status")))
        rows[sid] = {
            "status": s.get("status"),
            "stage": s.get("stage"),
            "name": s.get("name"),
            "rank": rank(s.get("status")),
            "rank_name": rank_name(s.get("status")),
        }

    refusal = audit.get("verdict_refusal_reason")
    return {
        "source": source,
        "run_shape": run_shape(audit),
        "verdict": verdict,
        "verdict_key": verdict_key,
        "verdict_refusal_reason": refusal,
        "verdict_rank": 0 if refusal else rank(verdict),
        "version": audit.get("version"),
        "run_at": audit.get("run_at"),
        "command_argv": audit.get("command_argv"),
        "step_count": len(rows),
        "duplicate_step_ids": sorted(set(duplicates)),
        # R-0915-85 — the words in this artefact that the reform deleted. A
        # baseline frozen before it carries them; `rank` ranks each NON_GREEN
        # and never translates one (see `rank`). Empty on any artefact a
        # migrated producer wrote.
        "pre_reform_words": sorted(set(pre_reform)),
        "step_counts": counts,
        "steps": rows,
    }


def load_table(path: Path) -> Dict[str, Any]:
    """Read a table off disk. A table nested inside a prior `real_ic_gate.json`
    / `audit_replay.json` is accepted under its own `table` key, so THIS gate's
    own output is usable as the next run's reference without re-deriving it."""
    p = Path(path)
    if not p.is_file():
        raise TableUnreadable("no such file: %s" % p)
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:                                # pragma: no cover
        raise TableUnreadable("unparsable JSON in %s: %s" % (p, exc))
    if isinstance(doc, dict) and isinstance(doc.get("table"), dict):
        t = dict(doc["table"])
        t.setdefault("source", str(p))
        t["source"] = str(p)
        return t
    return table_from_audit(doc, source=str(p))


# ── comparability ────────────────────────────────────────────────────────────

def _scope_flags(argv: Optional[List[Any]]) -> Optional[Tuple[str, frozenset]]:
    """(program basename, the scoping flags) for a recorded argv, or None when
    the argv was not recorded at all."""
    if not isinstance(argv, list) or not argv:
        return None
    prog = Path(str(argv[0])).name
    flags = set()
    i = 1
    while i < len(argv):
        tok = str(argv[i])
        if tok.startswith("-"):
            name = tok.split("=", 1)[0]
            if name == "--flow":
                if "=" in tok:
                    value = tok.split("=", 1)[1]
                elif i + 1 < len(argv) and not str(argv[i + 1]).startswith("-"):
                    value = str(argv[i + 1])
                    i += 1
                else:
                    value = "<missing>"
                # 109 is the sole current public runtime identity, whether the
                # caller spells it or relies on the public default. Retain any
                # other value only to keep immutable old evidence distinguishable.
                if value != "109":
                    flags.add("--flow=" + value)
                i += 1
                continue
            if name not in _SCOPE_NEUTRAL_FLAGS:
                # A narrowing flag carries its VALUE into the identity:
                # `--exclude-step 39` and `--exclude-step 7` scope differently.
                val = ""
                if "=" in tok:
                    val = tok.split("=", 1)[1]
                elif i + 1 < len(argv) and not str(argv[i + 1]).startswith("-"):
                    val = str(argv[i + 1])
                flags.add(name + ("=" + val if val else ""))
            if name in _SCOPE_NEUTRAL_FLAGS and "=" not in tok \
                    and i + 1 < len(argv) and not str(argv[i + 1]).startswith("-"):
                i += 1
        i += 1
    return prog, frozenset(flags)


def comparability(ref: Dict[str, Any], cur: Dict[str, Any]) -> Tuple[bool, str]:
    """May these two tables be diffed at all?

    The subject is held fixed by the CALLER (the same IC, the same snapshot);
    what this checks is that the INSTRUMENT asked the same question. Two
    invocations are comparable when they name the same program and the same
    scoping flags — the project path is expected to differ and is ignored.
    """
    rs, cs = _scope_flags(ref.get("command_argv")), _scope_flags(cur.get("command_argv"))
    if rs is None or cs is None:
        which = []
        if rs is None:
            which.append("reference")
        if cs is None:
            which.append("current")
        return False, ("the %s table records no `command_argv`, so the scope it "
                       "was produced at is unknown and the two tables cannot be "
                       "shown to answer the same question"
                       % " and ".join(which))
    if rs[0] != cs[0]:
        return False, ("different producer: reference was written by %s, current "
                       "by %s" % (rs[0], cs[0]))
    if rs[1] != cs[1]:
        only_ref = sorted(rs[1] - cs[1])
        only_cur = sorted(cs[1] - rs[1])
        return False, ("different scope: reference flags %s, current flags %s "
                       "(reference-only %s; current-only %s)"
                       % (sorted(rs[1]) or ["<none>"], sorted(cs[1]) or ["<none>"],
                          only_ref or ["<none>"], only_cur or ["<none>"]))

    # SECOND AXIS — the RUN SHAPE. The module docstring carries the
    # measurement: a program-only run and an agent-driven one disagree on the
    # steps whose second pass is an agent's, at every tree, so their tables are
    # answers to different questions and the difference is not about a landing.
    # (The IC name stays in the module docstring; this file declares
    # CHIP_AGNOSTIC: strict-logic, and its own test refuses one here.)
    ok, why = _run_shape_comparability(ref, cur)
    if not ok:
        return False, why
    return True, ("same producer (%s), same scoping flags %s, and %s"
                  % (rs[0], sorted(rs[1]) or ["<none>"], why))


def _run_shape_comparability(ref: Dict[str, Any],
                             cur: Dict[str, Any]) -> Tuple[bool, str]:
    """Did the same KIND of run produce both tables?

    A table with no recorded shape cannot be shown to match one that has a
    shape, so it REFUSES — the same fail-safe direction as an unrecorded
    `command_argv`. The refusal NAMES the gates whose second pass went
    unanswered and says what to do instead, because "NOT_COMPARABLE" on its own
    sends a reader looking for a defect that is not there.
    """
    rshape = ref.get("run_shape") or {}
    cshape = cur.get("run_shape") or {}
    rset, cset = (rshape.get("unanswered_second_pass"),
                  cshape.get("unanswered_second_pass"))
    if rset is None or cset is None:
        which = [n for n, v in (("reference", rset), ("current", cset))
                 if v is None]
        return False, (
            "the %s table(s) record no gate execution ledger, so the RUN SHAPE "
            "they were produced at is unknown — a program-only run and an agent-driven "
            "one disagree on every step whose second pass is an agent's, and the "
            "two cannot be shown to be the same experiment"
            % " and ".join(which))
    if set(rset) != set(cset):
        return False, (
            "different RUN SHAPE: the flow is program-first + AI-backup, and the "
            "two runs disagree about which hand-offs an agent answered. "
            "Unanswered second pass — reference: %s; current: %s. The difference "
            "between these tables is about who ran the flow, not about the tree. "
            "Use a reference produced by the SAME kind of run (for a landing "
            "gate: a prior headless run of this gate), not a published cell an "
            "agent-driven lane produced."
            % (sorted(rset) or ["<none>"], sorted(cset) or ["<none>"]))
    return True, ("the same run shape (unanswered second pass: %s)"
                  % (sorted(rset) or ["<none>"]))


# ── the diff ─────────────────────────────────────────────────────────────────

def diff_tables(ref: Dict[str, Any], cur: Dict[str, Any], *,
                subject_kind: str = SUBJECT_REAL_IC_GATE) -> Dict[str, Any]:
    """Which steps moved, in both directions, plus the top-level verdict.

    A step present in one table and not the other is NOT a silent omission:

      REMOVED  the reference measured it and this table does not. Held as a
               REGRESSION when the reference's word was a done-claim (rank >= 2)
               — a step that used to prove something and is now not even in the
               table is the laundering shape, seen from the other side.
      ADDED    listed, and — on a `real_ic_gate` subject — a REGRESSION when the
               new step's own word is NON_GREEN: a new red is a new red however
               it arrived.

    R-0915-139 — WHAT THE TWO SUBJECTS MEASURE IS NOT THE SAME THING, and one
    rule for both booked a class of finding that cannot exist.

    `real_ic_gate` runs the CANDIDATE TREE's own flow: every step it declares is a
    step this tree owns, so a new row at NON_GREEN is a new red this change
    brought and the rule above is right.

    `audit_replay` replays a FROZEN run tree and measures HOW EXISTING ROWS ARE
    READ. A step the frozen run's flow never declared has no reference and cannot
    have one: the row can only read missing there, whatever the candidate does.
    MEASURED on SLT53E: step 37.3 arrived with the fidelity producer, the
    end-to-end subject read it PASS (0 design-layer differences across 46 layers),
    and the four frozen replays read it None -> FAIL/missing_artefact — booked as
    four regressions for a step those trees predate. Its siblings 37 and 37.5ip
    read FAIL on the same trees for the same reason. (The design is deliberately
    not named here: `test_no_chip_vendor_or_SKU_token_appears_in_the_LOGIC_of_any
    _of_them` refuses a design token in this module, and it is right — the subject
    comes from the call site, never from a literal.)

    So on a replay subject a reference-None row is `ADDED_NO_REFERENCE`: recorded
    under `added`, and in none of `regressions`, `improvements` or `laterals`. The
    `real_ic_gate` rule is untouched, and it is the one that caught the
    NOT_DETERMINED -> FAIL defect in SLT53D — which is exactly why this change
    must not reach it.

    `regressed` is the single boolean a caller keys its exit code on.
    """
    if subject_kind not in (SUBJECT_AUDIT_REPLAY, SUBJECT_REAL_IC_GATE):
        # FAIL CLOSED on an unknown subject: keep the stricter rule rather than
        # silently granting the replay exemption to a caller nobody reviewed.
        subject_kind = SUBJECT_REAL_IC_GATE
    comparable, reason = comparability(ref, cur)

    rsteps: Dict[str, Any] = ref.get("steps") or {}
    csteps: Dict[str, Any] = cur.get("steps") or {}

    changed: List[Dict[str, Any]] = []
    unchanged = 0
    for sid in sorted(set(rsteps) & set(csteps), key=_step_sort_key):
        r, c = rsteps[sid], csteps[sid]
        d = direction(r.get("status"), c.get("status"))
        if d == UNCHANGED:
            unchanged += 1
            continue
        changed.append({
            "id": sid,
            "name": c.get("name") or r.get("name"),
            "stage": c.get("stage") or r.get("stage"),
            "reference": r.get("status"),
            "current": c.get("status"),
            "reference_rank": rank(r.get("status")),
            "current_rank": rank(c.get("status")),
            "direction": d,
        })

    removed = [{
        "id": sid,
        "name": rsteps[sid].get("name"),
        "stage": rsteps[sid].get("stage"),
        "reference": rsteps[sid].get("status"),
        "current": None,
        "reference_rank": rank(rsteps[sid].get("status")),
        "current_rank": None,
        "direction": (REGRESSION if rank(rsteps[sid].get("status")) >= 2
                      else LATERAL),
    } for sid in sorted(set(rsteps) - set(csteps), key=_step_sort_key)]

    added = [{
        "id": sid,
        "name": csteps[sid].get("name"),
        "stage": csteps[sid].get("stage"),
        "reference": None,
        "current": csteps[sid].get("status"),
        "reference_rank": None,
        "current_rank": rank(csteps[sid].get("status")),
        "direction": (
            ADDED_NO_REFERENCE if subject_kind == SUBJECT_AUDIT_REPLAY
            else REGRESSION if rank(csteps[sid].get("status")) == 0
            else LATERAL),
    } for sid in sorted(set(csteps) - set(rsteps), key=_step_sort_key)]

    every = changed + removed + added
    regressions = [e for e in every if e["direction"] == REGRESSION]
    improvements = [e for e in every if e["direction"] == IMPROVEMENT]
    laterals = [e for e in every if e["direction"] == LATERAL]

    vdir = direction(ref.get("verdict"), cur.get("verdict"))
    # A refusal is ranked 0 by `table_from_audit`, so a run that refuses cannot
    # read as an improvement over a run that judged.
    if ref.get("verdict_refusal_reason") or cur.get("verdict_refusal_reason"):
        rr = ref.get("verdict_rank", rank(ref.get("verdict")))
        cr = cur.get("verdict_rank", rank(cur.get("verdict")))
        vdir = (UNCHANGED if (rr == cr
                              and str(ref.get("verdict") or "")
                              == str(cur.get("verdict") or ""))
                else REGRESSION if cr < rr else IMPROVEMENT if cr > rr
                else LATERAL)

    return {
        "comparable": comparable,
        "comparability_reason": reason,
        # WHICH RULE RAN, in the document itself: a reader of a diff that books
        # no regression for an added red must be able to see WHY without knowing
        # which program produced it.
        "subject_kind": subject_kind,
        "verdict": {
            "reference": ref.get("verdict"),
            "current": cur.get("verdict"),
            "reference_refusal_reason": ref.get("verdict_refusal_reason"),
            "current_refusal_reason": cur.get("verdict_refusal_reason"),
            "direction": vdir,
        },
        "reference_step_count": len(rsteps),
        "current_step_count": len(csteps),
        "unchanged_step_count": unchanged,
        "changed": changed,
        "added": added,
        "removed": removed,
        "regressions": regressions,
        "improvements": improvements,
        "laterals": laterals,
        "regressed": bool(regressions) or vdir == REGRESSION,
    }


def _step_sort_key(sid: str):
    """Canonical step ids are '0.5ic', '2', '37.4', 'P0', 'D1', 'A3'. Sort them
    so a printed diff reads in flow order where the id is numeric, and
    alphabetically where it is not, instead of '10' before '2'."""
    head = sid.split(".")[0]
    try:
        return (0, float(sid.replace("ic", "").rstrip(".") or head), sid)
    except ValueError:
        return (1, 0.0, sid)


def render(table: Dict[str, Any], diff: Optional[Dict[str, Any]] = None) -> str:
    """The human line-per-step rendering both programs print. One function so
    two reports cannot describe the same table differently."""
    out: List[str] = []
    v = table.get("verdict")
    ref = table.get("verdict_refusal_reason")
    out.append("TOP-LEVEL VERDICT: %s%s  (%d steps, produced by %s)"
               % (v, (" REFUSAL=%s" % ref) if ref else "",
                  table.get("step_count", 0),
                  " ".join(str(a) for a in (table.get("command_argv") or []))
                  or "<argv not recorded>"))
    shape = table.get("run_shape") or {}
    unanswered = shape.get("unanswered_second_pass")
    out.append("RUN SHAPE: %s (%s)"
               % ("PROGRAM-ONLY — %d hand-off(s) an agent never answered: %s"
                  % (len(unanswered), ", ".join(unanswered))
                  if unanswered else
                  "no unanswered hand-off" if unanswered == []
                  else "NOT RECORDED — this table cannot say who ran the flow",
                  shape.get("source", "?")))
    if table.get("duplicate_step_ids"):
        out.append("DUPLICATE STEP IDS (the table cannot say what these are): %s"
                   % ", ".join(table["duplicate_step_ids"]))
    for sid in sorted(table.get("steps") or {}, key=_step_sort_key):
        row = table["steps"][sid]
        out.append("  %-8s %-22s %s" % (sid, row.get("status"), row.get("name")))
    if diff is None:
        return "\n".join(out)

    out.append("")
    if not diff.get("comparable"):
        out.append("DIFF REFUSED — NOT_COMPARABLE: %s"
                   % diff.get("comparability_reason"))
        return "\n".join(out)
    out.append("DIFF vs reference (%s): verdict %s -> %s [%s]"
               % (diff.get("comparability_reason"),
                  diff["verdict"]["reference"], diff["verdict"]["current"],
                  diff["verdict"]["direction"]))
    for bucket in ("regressions", "improvements", "laterals"):
        rows = diff.get(bucket) or []
        out.append("  %s: %d" % (bucket.upper(), len(rows)))
        for e in rows:
            out.append("    %-8s %-22s -> %-22s %s"
                       % (e["id"], e["reference"], e["current"], e["name"]))
    if not (diff.get("changed") or diff.get("added") or diff.get("removed")):
        out.append("  DIFF IS EMPTY — %d step(s) identical to the reference"
                   % diff.get("unchanged_step_count", 0))
    return "\n".join(out)
