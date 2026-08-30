#!/usr/bin/env python3
"""stage_on_pass_review.py — the ON-PASS review harness: after a stage PASSES,
read the INTENT and the ARTEFACT and say whether they contradict each other.

WHAT WAS MISSING
================
`skills/_classification.json` declares a `verification` tier whose own
description is "Run AFTER program PASS to spot-check the deterministic output.
AI MUST invoke before claiming PASS to user", with EIGHT members. MEASURED on
v1.12.83: all eight appear ZERO times in `flow/phase1_phase2_phase3.yaml`, and
so do `on_pass` / `after_pass` / `review_on` / `verify_artefact` /
`artefact_review`. Every `skills:` array in the flow hangs on a FAILURE trigger
or on a `condition:`. The AI was wired as an AUTHOR (when no program can) and
as a REPAIRER (when a program failed). There was no place where a program
PASSES and anything reads the artefact against what was asked for.

THE LADDER THIS IMPLEMENTS
==========================
PROGRAM first; what the program cannot fully catch falls to the GATE; what the
gate cannot catch falls to the SKILL. This program is the on-pass rung: it runs
AFTER the stage's own programs have passed, reads only what they left behind,
and hands the residue to the skill the flow names. It DOES NOT RE-DERIVE THE
ARTEFACT — it regenerates no RTL, invokes no tool, and starts no subprocess.
A reviewer that rebuilds the thing it is reviewing has replaced the program
rather than reviewed it.

THE DECLARATION LIVES IN THE FLOW, NOT HERE
===========================================
Everything this program does for a stage is read from that stage's
`on_pass_review:` block in `flow/phase1_phase2_phase3.yaml` — which skill owns
the residue, what counts as INTENT, what counts as ARTEFACT, what a rejection
must carry, and whether the verdict blocks. There are already three mappings on
this repo (the flow yaml, `benchmark/CAPTURE_ROUTING.json`,
`skills/_classification.json`) and a premise written in four places is a known
failure here, so this program adds a fourth of nothing: a stage with no
`on_pass_review:` block is NOT CHECKED, never a pass.

ENFORCEMENT: advisory — and it is stated HERE, one heading after "the
declaration lives in the flow", because those are two different declarations
and `flow_gate_enforcement_audit` can only read one of them. That audit reads a
gate's OWN source for what its rc means to a landing; a gate that says nothing
is `undeclared`, and before #886 saying nothing was the reliable way to stay
clean, which is how 113 of 150 gates came to be in that class. This line does
NOT add a fourth mapping of the kind the paragraph above refuses: every
stage-specific rule still comes from the flow and this program still adds none.
It records what an rc from THIS program means, which is a property of this
program, and it agrees with EVERY `on_pass_review:` block the flow carries:
each states `verdict: advisory`, and the audit measures the wiring as
AUDIT_ONLY. If a stage is ever wired to block, the flow is what changes and
this line changes with it.

THAT SENTENCE DELIBERATELY STATES NO COUNT, AND THE REASON IS MEASURED TWICE
OVER. It said "both wirings — stage1 and stage2", written against v1.13.3. It
was ALREADY FALSE when v1.13.7 landed it, because v1.13.4 (#1848) had wired
stage3 in between. Correcting it to "three" would have been false again inside
a day: v1.13.11 (#1849) wired `stage_analog`, making four. Two stale counts in
one sentence in nine versions is not carelessness, it is what a hand-typed
count DOES, and the remedy is the one this repo already applies to every stated
programs/ count — do not write the number, let the check read it. The guard
below compares SETS taken from the flow, so a fifth wiring moves it with no
edit and only a genuine DISAGREEMENT reddens it.

RULE R1 — INTENT_TOP_NOT_BUILT (stage1)
=======================================
The intent (`L9_INTEGRATION_SPEC.json`) names the design's top module. The
stage's artefact (`phase2/stage1/rtl/`) declares modules. When the intent names
a top the stage's own RTL never declares, every stage-1 report then stamps that
name as `design_identity.top` (`design_one_shot_runner._design_identity_fields`
copies it verbatim out of L9), and the whole stage certifies a subject the
design does not contain.

The refutation itself is NOT new: `_design_module_set.reconcile_declared_top`
(vibe-ic#760) already computes it, and TWO programs already call it —
`bit_level_full_stack_tb_check` (substitutes the structural root so it does not
mis-attribute the defect to the testbench) and `sdc_validator_check` (drops the
superseded deck). Both consume the ABSENT verdict to SUPPRESS a wrong finding
elsewhere. NEITHER REPORTS IT. So on a run where the intent and the artefact
disagree about what the chip is called, the fact is derived and thrown away,
and the stage goes green. This program is the reader that was missing.

WHEN R1 DISARMS, AND WHY THAT IS NOT A WEAKENING
------------------------------------------------
Phase 1 discloses when it could not read a top out of the input: it sets
`no_top_module_in_input: true` and `top_module_extraction_strategy:
canonical_chip_top_sentinel`, and publishes the placeholder `chip_top`. A
review cannot call a contradiction against a declaration of ignorance — the
intent is not claiming the design is called that. R1 therefore DISARMS on the
self-declared sentinel and says so as an observation. MEASURED over the
published corpus (105 cells, 30 with stage-1 RTL): the disarm moves 12 cells
out of the rejection set, leaving 3 rejections and 16 acceptances. A rule that
fired on all 30 would be the same failure as a detector that fires on 21 of 21
subjects.

RULE R3 — SIGNOFF_CLOCK_SLOWER_THAN_INTENT (stage3)
===================================================
Stage 3's own gates grade the LAYOUT against the NETLIST and the PDK: LVS
against the netlist, DRC against the rules, STA against the SDC. Every one of
them is measured against the SIGN-OFF CONSTRAINT DECK, and no gate in the flow
reads that deck against the design intent.

`phase3/stage3/pnr/constraint.sdc` is the deck. `pnr.tcl` `read_sdc`s it, and
steps 16 (clock planning), 17 (placement), 19 (CTS), 20 (hold fixing) and 23
(post-route STA) all close against it. `sdc_validator_check` DOES cross-check a
deck against L8 — but its `_SEARCH_ROOTS` are `phase2/stage1/fpga` and
`phase2/stage2/constraints`, so the stage-2 deck is graded and THE STAGE-3
SIGN-OFF DECK IS NEVER READ BY IT. `clock_plan_check` grades the plan's
substance and names no L-doc at all. `achieved_period_recorded_check` says in
its own docstring that "it does not judge the number", and reads the asked
period out of the run's own record rather than out of the intent.

So when `sdc_gen` misses every tier of its precedence walk it writes
`_DEFAULT_MHZ` (50.0 MHz -> 20.0 ns) into the sign-off deck, the design is
placed, CTS'd and timed at that period, and each of those steps goes green
because each is graded against the deck. MEASURED on the published corpus,
`evaluation/phase1_parity/sgmii`: L8 and L9 both declare `clk_main` at 625.0
MHz (`period_ns: 1.6`), the emitted deck says so out loud in its own header
("no constraints/*.sdc supplied; clk_period_ns=20.0"), and
`phase3/stage3/sta/post_route_timing.rpt` closes a path at 2.04 ns arrival
against a `20.00 clock clk (rise edge)`. Steps 16, 17, 19 and 20 are all PASS on
that run. The layout is signed off 12.5x slower than the design is specified to
run, and nothing in the flow says a word.

WHEN R3 DISARMS, AND WHY EACH NARROWING IS NOT A WEAKENING
----------------------------------------------------------
  * A DECK STRICTER THAN THE INTENT IS NOT A CONTRADICTION. R3 fires only when
    the deck's period is LONGER than the one the intent asks for. A design
    timed at a shorter period than it was asked for meets the asked one with
    margin — rejecting it would be the reviewer complaining about
    conservatism. MEASURED: `evaluation/phase1_parity/espi` declares 20.0 MHz
    (50.0 ns) and carries the same fabricated 20.0 ns deck; without this
    narrowing the rejection set over the corpus's five sign-off decks is 2, with
    it 1. The one it drops is the one where the artefact is not worse than the
    intent.
  * AN ABSENT DECLARATION IS NOT AN AGREEMENT. When the intent declares no
    frequency at all (`evaluation/phase1_parity/mdio`: L8.clock_mhz is null and
    both clock-domain lists are empty) there is nothing for the deck to
    contradict, and R3 is NOT CHECKED rather than ACCEPT.
  * A CONTRADICTORY INTENT CANNOT PUT THE QUESTION. Two PRIMARY records
    disagreeing about the period make the review NOT CHECKED — the same verdict
    `sdc_validator_check` reaches for the same shape. Note this does NOT fire on
    the corpus's incidental `role: extracted_from_doc_freq_mention` records,
    which are document mentions rather than a declared domain.
  * AN ABSENT DECK REFUTES NOTHING. A run with no `constraint.sdc`, or one with
    no `create_clock` in it, is NOT CHECKED, never ACCEPT.
  * WHEN THE DECK CREATES SEVERAL CLOCKS the SHORTEST period is the one
    compared, which is the reading most favourable to the artefact: R3 rejects
    only when EVERY clock the deck constrains is slower than the intent asks.

A REJECTION CARRIES EVIDENCE OR IT IS NOT A REJECTION
======================================================
The doctrine is that an AI rejection must be proven by a prompt-derived
executable test before repair. It is enforced here for the deterministic rung
too: a finding is emitted as a rejection only when it carries all four of the
stage's `rejection_requires:` — the INTENT it read (file, field, value), the
ARTEFACT fact it read (file/dir, what was found), the CONTRADICTION in one
sentence, and the executable TEST that fails today and passes when repaired. A
finding missing any of them is NOT downgraded to a warning and NOT emitted as a
rejection: the run is NOT CHECKED (rc 2), because an unproven rejection is a
reviewer manufacturing confidence, which is the failure this whole rung exists
to prevent.

§4.05
=====
`intent:` is the design INPUT. `intent_deny:` is enforced, not documentation: a
declared intent path whose resolved location carries any denied segment makes
the review REFUSE (rc 2) rather than read it. A reviewer that may read the
oracle is not reviewing, it is grading itself.

chip-AGNOSTIC: reads only the project's own L docs and its own staged RTL. No
IC, vendor, node or SKU literal.

CLI
===
    python3 stage_on_pass_review.py <project> --stage <stage-id> [--json OUT]
                                    [--compliance <flow_compliance --json>]
                                    [--stage-verdict PASS]
                                    [--flow-def <yaml>]

Exit codes
==========
    0 = ACCEPT — the stage's artefact and the intent do not contradict
    1 = REJECT — at least one proven contradiction, evidence in the report
    2 = NOT CHECKED — no declaration, stage PASS not established, a denied
        intent path, an unreadable input, or a finding that could not be proven
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _design_module_set as _dms  # noqa: E402
from _atomic_artefact import write_json as atomic_write_json  # vibe-ic#1082 (helper from PR #1094)  # noqa: E402

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - environment without pyyaml
    yaml = None  # type: ignore

_NAME = "stage_on_pass_review"

#: Default flow definition, relative to the plugin root.
_DEFAULT_FLOW = Path(__file__).resolve().parents[1] / "flow" / "phase1_phase2_phase3.yaml"

#: The four evidence parts a rejection must carry. The flow's
#: `rejection_requires:` is the live declaration; this is the fallback for a
#: stage that declares the review but omits the list.
_DEFAULT_REJECTION_REQUIRES = ("intent", "artefact", "contradiction", "test")

#: Where a rejection's emitted regression goes when the stage declares no
#: `emit_test_dir:`. Inside the run tree, beside the stage's other evidence.
_DEFAULT_EMIT_DIR = "reports/phase2/gates/on_pass_review"

#: The intent field L9 uses to disclose that it could not read a top out of the
#: design input, and the strategy value that goes with it.
_SENTINEL_STRATEGY = "canonical_chip_top_sentinel"


#: The clock-domain roles that mean "this is the design's clock", as the
#: published corpus spells them. Everything else in a `clock_domains[]` list is
#: an incidental record (`extracted_from_doc_freq_mention` is a document
#: mention, not a declared domain) and is NOT read as the design's period.
_PRIMARY_ROLES = frozenset({"primary", "master"})

#: Float-representation slack ONLY. 10.0 ns asked against a deck that stores
#: 10.000000000000002 is the same number; this is not a timing margin and must
#: never be widened into one. A deck 1 ps slower than the intent is still
#: slower than the intent.
_PERIOD_EPS_REL = 1e-6

#: `create_clock -period <ns>` in the sign-off deck, in either argument order
#: (`create_clock -name c -period 20.0 [get_ports c]` and
#: `create_clock [get_ports clk] -name core_clock -period 25.9` both occur in
#: the published corpus).
_CREATE_CLOCK_RE = re.compile(r"(?m)^[ \t]*create_clock\b(?P<args>[^\n]*)")
_PERIOD_ARG_RE = re.compile(r"-period\s+([0-9]*\.?[0-9]+)")
_NAME_ARG_RE = re.compile(r"-name\s+(\S+)")
_GET_PORTS_RE = re.compile(r"get_ports\s+([\w\\\[\]:$.]+)")

#: A `clock <name> (rise edge)` row in an OpenSTA path report, whose two equal
#: leading numbers are the period the path was closed against.
_STA_EDGE_RE = re.compile(
    r"(?m)^\s*(\d+(?:\.\d+)?)\s+\1\s+clock\s+(\S+)\s+\(rise edge\)")


# ─────────────────────────────────────────────────────────────────────────────
# declaration
# ─────────────────────────────────────────────────────────────────────────────
def load_declaration(flow_def: Path, stage_id: str) -> Dict[str, Any]:
    """The stage's `on_pass_review:` block, or {} when the stage declares none.

    Raises ValueError when the flow file itself cannot be read, so "the flow is
    unreadable" never comes out as "this stage declares no review".
    """
    if yaml is None:
        raise ValueError("pyyaml is not importable; the flow cannot be parsed")
    try:
        doc = yaml.safe_load(flow_def.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"{flow_def}: {e}") from e
    except Exception as e:  # yaml error
        raise ValueError(f"{flow_def} is not parsable YAML: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"{flow_def} is not a mapping")
    for st in doc.get("stages") or []:
        if isinstance(st, dict) and str(st.get("id")) == stage_id:
            blk = st.get("on_pass_review")
            return dict(blk) if isinstance(blk, dict) else {}
    raise ValueError(f"{flow_def} declares no stage {stage_id!r}")


# ─────────────────────────────────────────────────────────────────────────────
# fires-on-success
# ─────────────────────────────────────────────────────────────────────────────
def stage_passed(compliance: Optional[Path], stage_id: str,
                 explicit: Optional[str]) -> Dict[str, Any]:
    """Did this stage PASS? Returns {"passed": bool|None, "why": str}.

    `passed=None` means UNESTABLISHED — nobody said, and this program does not
    guess. An on-pass review that runs on an unestablished verdict is a review
    of nothing that reports a pass.
    """
    if explicit is not None:
        ok = str(explicit).strip().upper() == "PASS"
        return {"passed": ok, "why": f"--stage-verdict {explicit!r}",
                "source": "explicit"}
    if compliance is None:
        return {"passed": None,
                "why": ("no --compliance report and no --stage-verdict: the "
                        "stage's verdict is unestablished"),
                "source": None}
    try:
        rep = json.loads(compliance.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"passed": None, "why": f"{compliance}: {e}", "source": None}
    rows = rep.get("steps") if isinstance(rep, dict) else None
    if not isinstance(rows, list):
        return {"passed": None,
                "why": f"{compliance} carries no `steps` list", "source": None}
    mine = [r for r in rows
            if isinstance(r, dict) and str(r.get("stage") or "") == stage_id]
    if not mine:
        return {"passed": None,
                "why": f"{compliance} carries no row for stage {stage_id!r}",
                "source": str(compliance)}
    bad = sorted({str(r.get("status") or "?") for r in mine
                  if str(r.get("status") or "").upper()
                  not in ("PASS", "SKIPPED", "SKIPPED-CONDITION",
                          "VACUOUS-PASS", "WAIVED-DEFERRED")})
    return {"passed": not bad,
            "why": (f"{len(mine)} row(s) for {stage_id}"
                    + (f"; non-green: {', '.join(bad)}" if bad else
                       "; all green")),
            "source": str(compliance)}


# ─────────────────────────────────────────────────────────────────────────────
# §4.05
# ─────────────────────────────────────────────────────────────────────────────
def denied_intent_paths(project: Path, intent: List[str],
                        deny: List[str]) -> List[Dict[str, str]]:
    """Declared intent paths whose location carries a denied segment."""
    out: List[Dict[str, str]] = []
    for rel in intent:
        parts = [p.lower() for p in Path(str(rel)).parts]
        for seg in deny:
            s = str(seg).lower()
            if any(s in p for p in parts):
                out.append({"path": str(rel), "denied_segment": str(seg)})
                break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# R1
# ─────────────────────────────────────────────────────────────────────────────
def read_intent_top(l9_path: Path) -> Dict[str, Any]:
    """The intent's top-module declaration, INCLUDING its own disclosure of
    whether it could read one out of the design input at all."""
    try:
        d = json.loads(l9_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        return {"readable": False, "why": str(e)}
    if not isinstance(d, dict):
        return {"readable": False, "why": "L9 is not a mapping"}
    strategy = d.get("top_module_extraction_strategy")
    return {
        "readable": True,
        "file": str(l9_path),
        "field": "top_module",
        "value": d.get("top_module"),
        "top_module_extraction_strategy": strategy,
        "no_top_module_in_input": d.get("no_top_module_in_input"),
        "declares_no_top": (d.get("no_top_module_in_input") is True
                            or strategy == _SENTINEL_STRATEGY),
    }


def restamped_in(project: Path, reports_rel: List[str],
                 name: str) -> List[str]:
    """Stage report JSONs that carry `design_identity.top == name`.

    This is the blast radius, not the finding: the stamp is copied verbatim out
    of L9 by `design_one_shot_runner._design_identity_fields`, so each of these
    files certifies the refuted subject.
    """
    hits: List[str] = []
    for rel in reports_rel:
        root = project / rel
        if not root.is_dir():
            continue
        for fp in sorted(root.rglob("*.json")):
            try:
                d = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            ident = d.get("design_identity") if isinstance(d, dict) else None
            if isinstance(ident, dict) and ident.get("top") == name:
                hits.append(str(fp.relative_to(project)))
    return hits


def rule_intent_top_not_built(project: Path, decl: Dict[str, Any]) -> Dict[str, Any]:
    """R1. Returns {"verdict", "finding"|"observation", ...}."""
    intent_rel = [str(x) for x in (decl.get("intent") or [])]
    artefact_rel = [str(x) for x in (decl.get("artefact") or [])]
    l9 = next((project / r for r in intent_rel
               if r.endswith("L9_INTEGRATION_SPEC.json")), None)
    if l9 is None:
        return {"verdict": "NOT_CHECKED",
                "why": ("the stage's `intent:` names no L9_INTEGRATION_SPEC.json; "
                        "R1 has no intent to read")}
    if not l9.exists():
        return {"verdict": "NOT_CHECKED",
                "why": f"{l9} does not exist; the intent was never published"}
    intent = read_intent_top(l9)
    intent["intent_rel"] = str(l9.relative_to(project))
    if not intent.get("readable"):
        return {"verdict": "NOT_CHECKED",
                "why": f"{l9}: {intent.get('why')}"}

    rtl_dirs = [project / r for r in artefact_rel
                if (project / r).is_dir() and "rtl" in str(r).lower()]
    module_set = _dms.design_module_set(rtl_dirs)
    files = sorted(str(p.relative_to(project))
                   for d in rtl_dirs for g in _dms.SOURCE_GLOBS
                   for p in d.glob(g))
    artefact = {"rtl_dirs": [str(d.relative_to(project)) for d in rtl_dirs],
                "files": files,
                "module_count": len(module_set),
                "modules": sorted(module_set)}

    rec = _dms.reconcile_declared_top(intent.get("value"), module_set)

    # AN EMPTY MODULE SET IS NOT AN ACCEPTANCE. `reconcile_declared_top`
    # answers UNVERIFIABLE when nothing was staged or nothing parsed, and
    # NO_DECLARATION when the intent names no top at all. Reading either as
    # "no contradiction found" is how a review of nothing reports a pass —
    # the same defect as a gate that certifies an empty corpus. Both are
    # NOT CHECKED, and the reason says which.
    if rec["verdict"] == _dms.UNVERIFIABLE:
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": artefact,
                "reconcile": rec,
                "why": ("the stage staged no readable module: "
                        + (", ".join(artefact["rtl_dirs"])
                           or "no rtl dir among the declared artefact paths")
                        + " yields an EMPTY module set, which refutes nothing "
                          "and certifies nothing")}
    if rec["verdict"] == _dms.NO_DECLARATION:
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": artefact,
                "reconcile": rec,
                "why": (f"{l9.name} declares no `top_module`; there is no "
                        f"intent for the artefact to contradict, and an "
                        f"absent declaration is not an agreement")}

    # The disarm is NARROW BY DESIGN: it fires only when the intent DECLARES
    # that it read no top out of the design input. It deliberately does NOT
    # fire on a fallback strategy that names something while disclosing
    # `no_top_module_in_input: false` — MEASURED on the published corpus,
    # `l1_ic_name_fallback` publishes the project's own name as the top while
    # claiming the input supplied one. Disarming on the strategy string would
    # be the reviewer inferring a disclosure the intent refused to make, which
    # is manufacturing agreement.
    if intent.get("declares_no_top"):
        return {"verdict": "DISARMED", "intent": intent, "artefact": artefact,
                "reconcile": rec,
                "observation": (
                    "the intent DECLARES it could not read a top module out of "
                    f"the design input (no_top_module_in_input="
                    f"{intent.get('no_top_module_in_input')!r}, "
                    f"top_module_extraction_strategy="
                    f"{intent.get('top_module_extraction_strategy')!r}); "
                    f"{intent.get('value')!r} is a placeholder, not a claim "
                    "about this design, so there is nothing for the artefact "
                    "to contradict")}

    if rec["verdict"] != _dms.ABSENT:
        return {"verdict": "ACCEPT", "intent": intent, "artefact": artefact,
                "reconcile": rec}

    name = str(intent.get("value"))
    stamped = restamped_in(project,
                           [r for r in artefact_rel
                            if "report" in str(r).lower()], name)
    return {
        "verdict": "REJECT",
        "intent": intent,
        "artefact": artefact,
        "reconcile": rec,
        "restamped_in": stamped,
        "contradiction": (
            f"the intent names top module {name!r} "
            f"({intent.get('top_module_extraction_strategy')!r}, "
            f"no_top_module_in_input="
            f"{intent.get('no_top_module_in_input')!r}), and the stage's own "
            f"RTL declares {len(module_set)} module(s), none of them {name!r} "
            f"({', '.join(sorted(module_set)[:8])}"
            f"{', …' if len(module_set) > 8 else ''}). "
            f"{len(stamped)} stage report(s) stamp design_identity.top="
            f"{name!r}, so the stage certifies a subject this design does not "
            f"contain."),
        # `test` is filled in by `emit_test` once the run's own regression has
        # actually been WRITTEN. It is deliberately absent here: naming a test
        # that does not exist yet would satisfy the evidence contract with a
        # promise, and the contract exists to refuse promises.
    }


# ─────────────────────────────────────────────────────────────────────────────
# R2 — stage 2
# ─────────────────────────────────────────────────────────────────────────────
#: Port-direction keywords, in the NON-ANSI form every synthesised netlist uses
#: (`input clk;` / `output [7:0] q;`, one per line). This reader parses the
#: ARTEFACT the stage left behind; it elaborates nothing and runs nothing.
_NETLIST_PORT_RE = re.compile(
    r"(?m)^[ \t]*(input|output|inout)\b[ \t]*"
    r"(?:(?:wire|reg|logic|signed|unsigned)[ \t]+)*"
    r"(?:\[[ \t]*(-?\d+)[ \t]*:[ \t]*(-?\d+)[ \t]*\][ \t]*)?"
    r"([A-Za-z_][A-Za-z0-9_$]*)[ \t]*[;,]")

#: The roles an intent may give a pin to declare it a SUPPLY rather than a
#: signal. Read off the intent's OWN fields — never off the pin's name. See the
#: disarm note in `rule_intent_pin_not_in_netlist`.
_SUPPLY_ROLES = ("power", "ground", "supply")

#: Where the intent publishes the chip's external pin list, most specific
#: first. `phase1_doc_one_shot_runner` promotes L1's pin table into all three.
_INTENT_PIN_FIELDS = ("top_ports", "ports", "top_module_pins")


def _supply_declared(pin: Dict[str, Any]) -> Optional[str]:
    """The intent's OWN declaration that this pin is a supply, or None.

    Reads only declared ROLE fields. A name-shaped test ("does it start with a
    known rail prefix") would be this reviewer inventing a fact the intent did
    not state, and would silence a real signal pin that happens to be named
    like a rail.
    """
    for key in ("io", "type", "kind", "role", "pin_type"):
        v = pin.get(key)
        if isinstance(v, str) and v.strip().lower() in _SUPPLY_ROLES:
            return f"{key}={v!r}"
    for key in ("power", "supply", "is_supply", "is_power"):
        if pin.get(key) is True:
            return f"{key}=True"
    for key in ("direction", "mode"):
        v = pin.get(key)
        if isinstance(v, str) and v.strip().lower().startswith("supply"):
            return f"{key}={v!r}"
    return None


def read_intent_pins(l9_path: Path) -> Dict[str, Any]:
    """The intent's declared external pin list, and which field carried it."""
    try:
        d = json.loads(l9_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        return {"readable": False, "why": str(e)}
    if not isinstance(d, dict):
        return {"readable": False, "why": "L9 is not a mapping"}
    for field in _INTENT_PIN_FIELDS:
        rows = d.get(field)
        if isinstance(rows, list) and rows:
            pins = [p for p in rows if isinstance(p, dict) and p.get("name")]
            if pins:
                return {"readable": True, "file": str(l9_path), "field": field,
                        "value": [str(p["name"]) for p in pins],
                        "pins": pins}
    return {"readable": True, "file": str(l9_path), "field": None,
            "value": [], "pins": []}


def netlist_port_directions(text: str) -> Dict[str, str]:
    """`{port name: direction}` for one module body. PURE."""
    out: Dict[str, str] = {}
    for direction, _msb, _lsb, name in _NETLIST_PORT_RE.findall(text):
        out.setdefault(name, direction)
    return out


def read_netlist_interface(netlist: Path) -> Dict[str, Any]:
    """The interface of the module the netlist TOPS OUT AT.

    The top is STRUCTURAL — the module no other module in the file
    instantiates — not the one the intent names. That is deliberate: the
    question this rule puts is "does the thing that will be built carry the
    pins the design was asked for", and the thing that will be built is
    whatever the netlist roots at. Reading the intent's name here would let a
    netlist that roots at a different module answer for a module nobody
    builds.
    """
    try:
        text = netlist.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"readable": False, "why": str(e)}
    bodies = _dms.module_bodies_in_text(text)
    if not bodies:
        return {"readable": False,
                "why": f"{netlist.name} declares no module"}
    roots = sorted(_dms.instantiation_roots(bodies))
    if len(roots) != 1:
        return {"readable": False, "modules": sorted(bodies),
                "roots": roots,
                "why": (f"{netlist.name} has {len(roots)} structural root(s) "
                        f"({', '.join(roots) or 'none'}); a netlist with no "
                        f"single root has no one interface to compare against "
                        f"the intent")}
    top = roots[0]
    ports = netlist_port_directions(bodies[top])
    return {"readable": True, "file": str(netlist), "top": top,
            "modules": sorted(bodies), "ports": ports,
            "port_names": sorted(ports)}


def rule_intent_pin_not_in_netlist(project: Path,
                                   decl: Dict[str, Any]) -> Dict[str, Any]:
    """R2. The intent declares a pin the synthesised netlist does not build.

    THE INTENT is the design INPUT's pin table, promoted into L9. THE ARTEFACT
    is the netlist step 9 produces and step 14 hands to place-and-route — the
    first artefact in the flow in which the interface is CONCRETE: parameters
    resolved, wrapper chosen, widths fixed. A pin the intent declares and this
    module does not carry is a pin the fabricated chip will not have.

    WHY THE REVERSE DIRECTION IS AN OBSERVATION AND NOT A REJECTION. Ports the
    netlist carries and the intent does not are ROUTINE and legitimately
    flow-authored: DFT insertion adds a scan interface, the chip_top wrapper
    adds its own, tie cells add theirs. MEASURED over the published corpus, 2
    of the 11 comparable cells carry extra ports and BOTH are legitimate, so a
    rule that rejected on them would be firing on the flow's own correct
    behaviour. This rule is therefore one-directional by construction, and the
    extra ports are reported so the reader can see what the reviewer saw.

    THE DISARM, and why it is a narrowing rather than a weakening. A pin the
    intent itself marks POWER or GROUND is legitimately absent from a
    non-power-aware synthesised netlist — supply connectivity is stage 3's
    (the power grid, and power-aware LVS), and Yosys emits no supply ports
    unless asked. MEASURED over the published corpus: without this disarm the
    rejection set is 3 of 11 cells, and 2 of those 3 are the same cell's two
    supply pins. With it the set is 1 of 11. The disarm reads the intent's own
    declared ROLE field and nothing else — see `_supply_declared`.
    """
    intent_rel = [str(x) for x in (decl.get("intent") or [])]
    artefact_rel = [str(x) for x in (decl.get("artefact") or [])]
    l9 = next((project / r for r in intent_rel
               if r.endswith("L9_INTEGRATION_SPEC.json")), None)
    if l9 is None:
        return {"verdict": "NOT_CHECKED",
                "why": ("the stage's `intent:` names no L9_INTEGRATION_SPEC.json; "
                        "R2 has no intent to read")}
    if not l9.exists():
        return {"verdict": "NOT_CHECKED",
                "why": f"{l9} does not exist; the intent was never published"}
    intent = read_intent_pins(l9)
    intent["intent_rel"] = str(l9.relative_to(project))
    if not intent.get("readable"):
        return {"verdict": "NOT_CHECKED", "why": f"{l9}: {intent.get('why')}"}
    if not intent["pins"]:
        return {"verdict": "NOT_CHECKED", "intent": intent,
                "why": (f"{l9.name} declares no external pin in any of "
                        f"{', '.join(_INTENT_PIN_FIELDS)}; there is no intent "
                        f"for the artefact to contradict, and an absent "
                        f"declaration is not an agreement")}

    nets = [project / r for r in artefact_rel
            if str(r).endswith(".v") and (project / r).is_file()]
    if not nets:
        return {"verdict": "NOT_CHECKED", "intent": intent,
                "why": ("none of the declared artefact paths resolves to a "
                        "netlist file: "
                        + (", ".join(artefact_rel) or "(no artefact declared)")
                        + " — the stage published no netlist to compare, which "
                          "refutes nothing and certifies nothing")}
    netlist = nets[0]
    art = read_netlist_interface(netlist)
    art["artefact_rel"] = str(netlist.relative_to(project))
    if not art.get("readable"):
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": art,
                "why": f"{netlist}: {art.get('why')}"}
    if not art["ports"]:
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": art,
                "why": (f"the netlist's structural top {art['top']!r} declares "
                        f"NO port; an empty interface refutes nothing and "
                        f"certifies nothing")}

    built = set(art["ports"])
    absent_signal: List[Dict[str, Any]] = []
    disarmed: List[Dict[str, Any]] = []
    for pin in intent["pins"]:
        name = str(pin["name"])
        if name in built:
            continue
        why_supply = _supply_declared(pin)
        row = {"name": name,
               "direction": pin.get("direction") or pin.get("mode"),
               "evidence": pin.get("evidence")}
        if why_supply:
            row["intent_declares_supply"] = why_supply
            disarmed.append(row)
        else:
            absent_signal.append(row)
    extra = sorted(built - {str(p["name"]) for p in intent["pins"]})

    art["extra_ports_not_in_intent"] = extra
    common = {"intent": intent, "artefact": art, "disarmed": disarmed,
              "extra_ports_not_in_intent": extra}

    if not absent_signal:
        out = {"verdict": "ACCEPT", **common}
        if disarmed:
            out["verdict"] = "DISARMED"
            out["observation"] = (
                f"{len(disarmed)} intent pin(s) are absent from the netlist's "
                f"top {art['top']!r} and every one of them is a pin THE INTENT "
                f"ITSELF declares a supply rather than a signal ("
                + "; ".join(f"{r['name']} [{r['intent_declares_supply']}]"
                            for r in disarmed)
                + "); a non-power-aware synthesised netlist carries no supply "
                  "port, and supply connectivity is signed off in stage 3 by "
                  "the power grid and power-aware LVS, not here")
        return out

    names = [r["name"] for r in absent_signal]
    return {
        "verdict": "REJECT", **common,
        "absent_signal_pins": absent_signal,
        "contradiction": (
            f"the intent declares {len(intent['pins'])} external pin(s) in "
            f"{Path(intent['intent_rel']).name}::{intent['field']}, and the "
            f"netlist this stage hands to place-and-route tops out at "
            f"{art['top']!r} carrying {len(built)} port(s) — "
            f"{len(absent_signal)} declared pin(s) are not among them: "
            f"{', '.join(names[:8])}{', …' if len(names) > 8 else ''}. "
            f"The netlist builds {', '.join(sorted(built)[:8])}"
            f"{', …' if len(built) > 8 else ''}. "
            f"A pin the design input asks for and the synthesised top does not "
            f"carry is a pin the fabricated chip will not have, and every "
            f"stage-3 sign-off downstream is correct about the interface that "
            f"was built rather than the one that was asked for."),
        # `test` is filled in by `emit_test` once the run's own regression has
        # actually been WRITTEN — see the note on R1.
    }


# ─────────────────────────────────────────────────────────────────────────────
# R3
# ─────────────────────────────────────────────────────────────────────────────
def _pos_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _primary_period_from_domains(doc: Dict[str, Any], src: str) -> List[Dict[str, Any]]:
    """Every PRIMARY clock-domain record in `doc`, as a declared period.

    Returns one entry per PRIMARY record — plural on purpose, so a doc that
    declares two disagreeing primaries is visible to the caller as a
    contradiction rather than silently resolved by list order.
    """
    out: List[Dict[str, Any]] = []
    for i, cd in enumerate(doc.get("clock_domains") or []):
        if not isinstance(cd, dict):
            continue
        if str(cd.get("role") or "").strip().lower() not in _PRIMARY_ROLES:
            continue
        ns = _pos_float(cd.get("period_ns"))
        if ns is None:
            mhz = _pos_float(cd.get("freq_mhz")) or _pos_float(cd.get("freq_low_mhz"))
            ns = (1000.0 / mhz) if mhz else None
        if ns is None:
            continue
        out.append({"file": src, "field": f"clock_domains[{i}]",
                    "clock": cd.get("name"), "role": cd.get("role"),
                    "period_ns": ns})
    return out


def read_intent_period(l8: Optional[Path], l9: Optional[Path],
                       project: Path) -> Dict[str, Any]:
    """The period the DESIGN ASKS FOR, read the way the generator claims to.

    The precedence is `sdc_gen`'s own first two tiers, which is the point: the
    review reads the intent through the same walk the deck's producer says it
    uses, so a disagreement is the producer having missed it rather than the
    reviewer having invented a different question. Tier 3 (the design's own
    staged SDC) and tier 4 (`_DEFAULT_MHZ`) are deliberately NOT read — neither
    is the design INPUT, and tier 4 is the fabrication this rule exists to see.
    """
    read: List[str] = []
    docs: List[tuple] = []
    for path in (l8, l9):
        if path is None:
            continue
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as e:
            return {"declared": None, "why": f"{path}: {e}"}
        if not isinstance(d, dict):
            return {"declared": None, "why": f"{path} is not a mapping"}
        rel = str(path.relative_to(project)) if project in path.parents else str(path)
        read.append(rel)
        docs.append((rel, d))
    if not docs:
        return {"declared": None,
                "why": "none of the declared intent documents exist"}

    # tier 1 — the scalar the design owns.
    for rel, d in docs:
        mhz = _pos_float(d.get("clock_mhz"))
        if mhz:
            return {"declared": True, "read": read, "file": rel,
                    "field": "clock_mhz", "value": d.get("clock_mhz"),
                    "unit": "MHz", "period_ns": 1000.0 / mhz,
                    "tier": "L-doc clock_mhz"}

    # tier 2 — the PRIMARY clock-domain record.
    for rel, d in docs:
        cands = _primary_period_from_domains(d, rel)
        if not cands:
            continue
        distinct = sorted({round(c["period_ns"], 9) for c in cands})
        if len(distinct) > 1:
            return {"declared": None, "read": read, "candidates": cands,
                    "why": (f"{rel} declares {len(distinct)} DIFFERENT periods "
                            f"under a primary role ({distinct} ns); an SDC "
                            f"cannot be validated against a contradictory "
                            f"constraint set, and picking one of them would be "
                            f"the reviewer resolving a disagreement the intent "
                            f"has not resolved")}
        c = cands[0]
        return {"declared": True, "read": read, "file": c["file"],
                "field": c["field"], "value": c["clock"],
                "clock": c["clock"], "role": c["role"],
                "period_ns": c["period_ns"],
                "tier": "L-doc primary clock_domains[]"}

    return {"declared": False, "read": read,
            "why": ("no declared intent document carries a clock frequency: "
                    "`clock_mhz` is absent or null and no clock_domains[] "
                    "record carries a primary role with a period")}


def read_signoff_deck(sdc: Path, project: Path) -> Dict[str, Any]:
    """Every `create_clock` in the deck stage 3 signed off against."""
    try:
        text = sdc.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"readable": False, "why": str(e)}
    clocks: List[Dict[str, Any]] = []
    for m in _CREATE_CLOCK_RE.finditer(text):
        args = m.group("args")
        per = _PERIOD_ARG_RE.search(args)
        if not per:
            continue
        ns = _pos_float(per.group(1))
        if ns is None:
            continue
        nm = _NAME_ARG_RE.search(args)
        pt = _GET_PORTS_RE.search(args)
        clocks.append({"name": nm.group(1) if nm else None,
                       "port": pt.group(1) if pt else None,
                       "period_ns": ns,
                       "line": m.group(0).strip()})
    return {"readable": True,
            "file": str(sdc.relative_to(project)) if project in sdc.parents
                    else str(sdc),
            "clocks": clocks}


def signed_off_under(project: Path, rels: List[str],
                     period_ns: float) -> List[Dict[str, Any]]:
    """Stage-3 sign-off evidence produced under the deck's period.

    The BLAST RADIUS, not the finding: each of these files is a step that went
    green against the refuted number. Kept out of `rejection_requires` on
    purpose — the contradiction is between the intent and the deck, and a run
    that has not reached STA yet still carries it.
    """
    hits: List[Dict[str, Any]] = []
    for rel in rels:
        base = project / rel
        paths = ([base] if base.is_file()
                 else sorted(base.rglob("*")) if base.is_dir() else [])
        for fp in paths:
            if not fp.is_file() or fp.suffix not in (".rpt", ".json"):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rp = str(fp.relative_to(project))
            if fp.suffix == ".rpt":
                for num, clk in _STA_EDGE_RE.findall(text):
                    if abs(float(num) - period_ns) <= period_ns * _PERIOD_EPS_REL:
                        hits.append({"file": rp, "period_ns": float(num),
                                     "evidence": f"clock {clk} (rise edge) at "
                                                 f"{num}"})
                        break
                continue
            try:
                d = json.loads(text)
            except ValueError:
                continue
            for c in (d.get("clocks") or []) if isinstance(d, dict) else []:
                ns = _pos_float(isinstance(c, dict) and c.get("period_ns"))
                if ns is not None and abs(ns - period_ns) <= period_ns * _PERIOD_EPS_REL:
                    hits.append({"file": rp, "period_ns": ns,
                                 "evidence": f"clocks[].period_ns={ns} "
                                             f"({c.get('name')})"})
                    break
    return hits


def rule_signoff_clock_slower_than_intent(project: Path,
                                          decl: Dict[str, Any]) -> Dict[str, Any]:
    """R3. Returns {"verdict", ...} in the same shape R1 does."""
    intent_rel = [str(x) for x in (decl.get("intent") or [])]
    artefact_rel = [str(x) for x in (decl.get("artefact") or [])]

    def _named(suffix):
        return next((project / r for r in intent_rel if r.endswith(suffix)), None)

    l8, l9 = _named("L8_TIMING_WAVEFORM.json"), _named("L9_INTEGRATION_SPEC.json")
    if l8 is None and l9 is None:
        return {"verdict": "NOT_CHECKED",
                "why": ("the stage's `intent:` names neither "
                        "L8_TIMING_WAVEFORM.json nor L9_INTEGRATION_SPEC.json; "
                        "R3 has no intent to read")}

    sdc = next((project / r for r in artefact_rel
                if r.endswith("constraint.sdc")), None)
    if sdc is None:
        return {"verdict": "NOT_CHECKED",
                "why": ("the stage's `artefact:` names no sign-off "
                        "constraint.sdc; R3 has no artefact to read")}
    if not sdc.exists():
        return {"verdict": "NOT_CHECKED",
                "why": (f"{sdc.relative_to(project)} does not exist: this run "
                        f"staged no stage-3 sign-off deck, which refutes "
                        f"nothing and certifies nothing")}

    deck = read_signoff_deck(sdc, project)
    if not deck.get("readable"):
        return {"verdict": "NOT_CHECKED", "why": f"{sdc}: {deck.get('why')}"}
    artefact = {"file": deck["file"], "clocks": deck["clocks"],
                "clock_count": len(deck["clocks"])}
    if not deck["clocks"]:
        return {"verdict": "NOT_CHECKED", "artefact": artefact,
                "why": (f"{deck['file']} creates no clock with a period; the "
                        f"deck constrains nothing, so there is no sign-off "
                        f"period for the intent to contradict")}

    intent = read_intent_period(l8, l9, project)
    if intent.get("declared") is None:
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": artefact,
                "why": intent.get("why")}
    if intent.get("declared") is False:
        # AN ABSENT DECLARATION IS NOT AN AGREEMENT — the same rule R1 applies
        # to a missing `top_module`. Answering ACCEPT here would certify every
        # deck on every run whose intent never stated a frequency.
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": artefact,
                "why": intent.get("why")}

    asked = float(intent["period_ns"])
    fastest = min(deck["clocks"], key=lambda c: c["period_ns"])
    artefact["fastest_clock"] = fastest
    tol = asked * _PERIOD_EPS_REL

    if fastest["period_ns"] <= asked + tol:
        out = {"verdict": "ACCEPT", "intent": intent, "artefact": artefact}
        if fastest["period_ns"] < asked - tol:
            out["observation"] = (
                f"the sign-off deck constrains {fastest['period_ns']} ns, "
                f"SHORTER than the {asked:.6g} ns the intent asks for. A deck "
                f"stricter than the intent is not a contradiction: timing that "
                f"closes at the shorter period closes at the longer one, so "
                f"the artefact is not worse than what was asked.")
        return out

    stamped = signed_off_under(project, artefact_rel, fastest["period_ns"])
    return {
        "verdict": "REJECT",
        "intent": intent,
        "artefact": artefact,
        "signed_off_under": stamped,
        "contradiction": (
            f"the intent asks for {asked:.6g} ns "
            f"({intent['file']} :: {intent['field']} = {intent['value']!r}"
            f"{', ' + str(intent.get('unit')) if intent.get('unit') else ''}), "
            f"and {deck['file']} — the deck stage 3 placed, CTS'd and closed "
            f"timing against — constrains {len(deck['clocks'])} clock(s) whose "
            f"FASTEST is {fastest['period_ns']} ns "
            f"({fastest['line']}), a factor of "
            f"{fastest['period_ns'] / asked:.3g} slower. Every stage-3 gate is "
            f"graded against this deck, so each one goes green while the "
            f"layout is signed off at a clock the design was never specified "
            f"to run at. {len(stamped)} sign-off artefact(s) carry the refuted "
            f"period."),
    }


# ─────────────────────────────────────────────────────────────────────────────
# R_ANALOG
# ─────────────────────────────────────────────────────────────────────────────
#: The numeric keys an L5 spec row / an A1 spec.json row may carry. A row with
#: none of them states no number and is therefore not a requirement a artefact
#: can contradict.
_SPEC_NUMERIC_KEYS = ("target", "min", "max", "value", "typ")


def _spec_numbers(row: Dict[str, Any]) -> Dict[str, float]:
    """The numeric content of one spec row, keyed by bound."""
    out: Dict[str, float] = {}
    for k in _SPEC_NUMERIC_KEYS:
        v = row.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out[k] = float(v)
    return out


def _spec_key(name: Any) -> str:
    """Compare spec names by their letters and digits alone.

    MEASURED, and this is why it is not a plain equality: the intent writes
    `Vin (diff)` and `Vdd (core)` where the artefact writes `vin_diff` and
    `vdd`. A strict compare reported both as DROPPED on a run that had in fact
    carried them, which is the reviewer inventing a contradiction out of a
    spelling. The value fallback in `_dropped_and_contradicted` covers what
    this still cannot align (`Vdd (core)` -> `vdd`).
    """
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _dropped_and_contradicted(requirements: List[Dict[str, Any]],
                              artefact_rows: List[Dict[str, Any]]):
    """The two shapes of "the graded spec is not the declared spec".

    DROPPED       an intent requirement that appears in the artefact under
                  neither its name nor its numbers.
    CONTRADICTED  an artefact row that DOES carry the intent's requirement by
                  name, and states a target the intent's own declared range
                  excludes.

    A requirement matched by VALUE and not by name is counted as carried: the
    artefact renamed it, which is not the defect this rule is about.
    """
    by_key = {}
    for row in artefact_rows:
        by_key.setdefault(_spec_key(row.get("name")), _spec_numbers(row))
    value_sets = [set(v.values()) for v in by_key.values() if v]

    dropped: List[Dict[str, Any]] = []
    contradicted: List[Dict[str, Any]] = []
    for req in requirements:
        key = _spec_key(req.get("name"))
        want = _spec_numbers(req)
        if key not in by_key:
            if not any(set(want.values()) <= vs for vs in value_sets):
                dropped.append({"name": req.get("name"),
                                "unit": req.get("unit"),
                                "declared": want})
            continue
        got = by_key[key]
        target = got.get("target", got.get("value", got.get("typ")))
        lo, hi = want.get("min"), want.get("max")
        if target is None or (lo is None and hi is None):
            continue
        if (lo is not None and target < lo) or (hi is not None and target > hi):
            contradicted.append({"name": req.get("name"),
                                 "unit": req.get("unit"),
                                 "declared": want, "graded_target": target})
    return dropped, contradicted


def _analog_spec_artefact(project: Path, artefact_rel: List[str],
                          block: str) -> Optional[Path]:
    """`<declared analog dir>/<block>/spec.json`, canonical spelling first.

    The flow declares BOTH spellings for every A-step's artefact and says why
    (`phase3/analog/` is what every producer writes; `phase1/analog/` is where
    `migrate_to_layout_p` moves a project-root tree). This resolver reads the
    declaration in the order the flow writes it and does not add a third.
    """
    for rel in artefact_rel:
        cand = project / rel / block / "spec.json"
        if cand.is_file():
            return cand
    return None


def rule_intent_spec_not_the_graded_spec(project: Path,
                                         decl: Dict[str, Any]) -> Dict[str, Any]:
    """R_ANALOG. Returns {"verdict", "finding"|"observation", ...}.

    THE CONTRADICTION, AND WHY NOTHING ELSE IN THE FLOW HOLDS IT
    ------------------------------------------------------------
    A1 reads the intent (`L5_ADI_SPEC.json`) ONCE and writes
    `phase3/analog/<block>/spec.json`. From A2 to A9 that file IS the spec:
    the topology is chosen against it, the deck is sized against it, the PVT
    sweep is graded against it (`corner_yield_vs_spec_check` parses "yield
    table vs spec.json limits"), the layout and the hardmacro are signed off
    on the result. MEASURED on this tree: of the 54 `analog_*` programs, SEVEN
    open `L5_ADI_SPEC.json`. FIVE are PRODUCERS (`analog_a1_spec_emit`,
    `analog_a2_topology_emit`, `analog_a3_netlist_emit`,
    `analog_real_corner_sweep`, `analog_one_shot_runner`). The other two are
    checkers asking a different question: `analog_a0_skip_forbidden_check`
    uses `analog_blocks_detected=false` as a waiver for a forbidden skip file
    and never reads a block's requirements, and
    `analog_content_detected_must_emit_l5_check` grades L5 against the input
    DOCS and never opens a `spec.json`. NO A1-A9 GATE READS A BLOCK'S
    REQUIREMENTS OUT OF L5 AT ALL. (One A-gate does open an L doc, for an
    unrelated layer: `analog_netlist_pdk_check` reads L19_CONSTRAINTS_PDK,
    the PDK constraint layer, not the analog spec.)

    So the intent's numbers are copied once and never re-read. When the copy
    is short or wrong, every downstream gate is green, because each of them
    compares the artefact with the artefact. A1's own gate is explicit about
    its threshold — `analog_a1_spec_extract_check` certifies a block that
    "declares >= 1 spec field" — and MEASURED it reports "PASS: 2/2 block(s)
    clean" on a `spec.json` whose single row is `vout target 1.0 V` while the
    intent declares `Vout 1.2 V (1.1-1.3)` and five further requirements.

    WHEN IT DISARMS
    ---------------
    On the INTENT's own disclosure, never on the artefact's. L5 saying
    `no_analog: true` / `analog_blocks_detected: false`, a block L5 itself
    marks `spurious: true` or `low_confidence: true`, and a block for which L5
    declares no numeric requirement at all, are all the intent declining to
    state a requirement — there is nothing for the artefact to contradict.
    A `spec.json` that discloses `extraction_strategy: deterministic_stub` is
    NOT a disarm and that is the point: the artefact saying it made the number
    up does not retract the six the intent supplied.
    """
    intent_rel = [str(x) for x in (decl.get("intent") or [])]
    artefact_rel = [str(x) for x in (decl.get("artefact") or [])]
    l5 = next((project / r for r in intent_rel
               if r.endswith("L5_ADI_SPEC.json")), None)
    if l5 is None:
        return {"verdict": "NOT_CHECKED",
                "why": ("the stage's `intent:` names no L5_ADI_SPEC.json; "
                        "R_ANALOG has no intent to read")}
    if not l5.exists():
        return {"verdict": "NOT_CHECKED",
                "why": f"{l5} does not exist; the intent was never published"}
    try:
        doc = json.loads(l5.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        return {"verdict": "NOT_CHECKED", "why": f"{l5}: {e}"}
    if not isinstance(doc, dict):
        return {"verdict": "NOT_CHECKED", "why": f"{l5} is not a mapping"}

    intent: Dict[str, Any] = {
        "file": str(l5), "intent_rel": str(l5.relative_to(project)),
        "field": "analog_blocks[].spec.specs[]",
    }
    analog_dirs = [str(r) for r in artefact_rel
                   if (project / r).is_dir() and "analog" in str(r).lower()]

    if doc.get("no_analog") is True or doc.get("analog_blocks_detected") is False:
        intent["value"] = {"no_analog": doc.get("no_analog"),
                           "analog_blocks_detected":
                               doc.get("analog_blocks_detected")}
        return {"verdict": "DISARMED", "intent": intent,
                "artefact": {"analog_dirs": analog_dirs},
                "observation": (
                    "the intent DECLARES this design carries no analog content "
                    f"(no_analog={doc.get('no_analog')!r}, "
                    f"analog_blocks_detected="
                    f"{doc.get('analog_blocks_detected')!r}), so it states no "
                    "analog requirement for the stage's artefact to "
                    "contradict")}

    in_scope: List[Dict[str, Any]] = []
    disarmed: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    for blk in (doc.get("analog_blocks") or []):
        if not isinstance(blk, dict):
            continue
        name = str(blk.get("name") or "")
        if not name:
            continue
        if blk.get("spurious") is True or blk.get("low_confidence") is True:
            disarmed.append({"block": name, "why": (
                f"the intent marks it spurious={blk.get('spurious')!r} "
                f"low_confidence={blk.get('low_confidence')!r}")})
            continue
        spec = blk.get("spec") if isinstance(blk.get("spec"), dict) else {}
        rows = [r for r in (spec.get("specs") or []) if isinstance(r, dict)]
        reqs = [r for r in rows if _spec_numbers(r)]
        if not reqs:
            disarmed.append({"block": name, "why": (
                "the intent declares no numeric requirement for this block; "
                "an absent declaration is not an agreement, and it is also "
                "not a contradiction")})
            continue
        art = _analog_spec_artefact(project, artefact_rel, name)
        if art is None:
            unreadable.append({"block": name, "why": (
                "the intent declares "
                f"{len(reqs)} numeric requirement(s) and no spec.json for this "
                f"block resolves under "
                + (", ".join(analog_dirs) or "any declared analog dir"))})
            continue
        try:
            adoc = json.loads(art.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as e:
            unreadable.append({"block": name, "why": f"{art}: {e}"})
            continue
        arows = [r for r in ((adoc.get("specs") or [])
                             if isinstance(adoc, dict) else [])
                 if isinstance(r, dict)]
        dropped, contradicted = _dropped_and_contradicted(reqs, arows)
        entry = {
            "block": name,
            "artefact_rel": str(art.relative_to(project)),
            "intent_requirements": [
                {"name": r.get("name"), "unit": r.get("unit"),
                 "declared": _spec_numbers(r)} for r in reqs],
            "artefact_specs": [r.get("name") for r in arows],
            "artefact_extraction_strategy": (
                adoc.get("extraction_strategy") if isinstance(adoc, dict)
                else None),
            "dropped": dropped,
            "contradicted": contradicted,
        }
        in_scope.append(entry)
        if dropped or contradicted:
            findings.append(entry)

    artefact = {"analog_dirs": analog_dirs,
                "artefact_rels": [str(r) for r in artefact_rel],
                "files": sorted(e["artefact_rel"] for e in in_scope),
                "block_count": len(in_scope),
                "blocks": in_scope}
    intent["value"] = {e["block"]: [r["name"] for r in e["intent_requirements"]]
                       for e in in_scope}

    # AN EMPTY SCOPE IS NOT AN ACCEPTANCE. Every block was disarmed by the
    # intent's own disclosure or had no artefact to read, so the denominator
    # is zero and nothing was measured. Reporting that as "no contradiction
    # found" is how a review of nothing reports a pass.
    if not in_scope:
        return {"verdict": "NOT_CHECKED", "intent": intent, "artefact": artefact,
                "disarmed": disarmed, "unreadable": unreadable,
                "why": ("no analog block is in scope: "
                        f"{len(disarmed)} disarmed by the intent's own "
                        f"disclosure, {len(unreadable)} with no readable "
                        "spec.json, 0 measured")}

    if not findings:
        n_req = sum(len(e["intent_requirements"]) for e in in_scope)
        return {"verdict": "ACCEPT", "intent": intent, "artefact": artefact,
                "disarmed": disarmed, "unreadable": unreadable,
                "observation": (
                    f"{n_req} numeric requirement(s) across {len(in_scope)} "
                    f"block(s) are each carried by the spec the stage grades "
                    f"against; {len(disarmed)} block(s) disarmed by the "
                    f"intent's own disclosure")}

    parts = []
    for e in findings:
        if e["dropped"]:
            parts.append(
                f"for block {e['block']!r} the intent declares "
                f"{len(e['intent_requirements'])} numeric requirement(s) and "
                f"{e['artefact_rel']} — the only spec every A2-A9 gate grades "
                f"against — carries {len(e['artefact_specs'])} row(s) and none "
                f"matching "
                + ", ".join(f"{d['name']!r}" for d in e["dropped"]))
        for c in e["contradicted"]:
            lo, hi = c["declared"].get("min"), c["declared"].get("max")
            parts.append(
                f"for block {e['block']!r} the intent declares "
                f"{c['name']!r} = {c['declared'].get('target')} "
                f"{c['unit'] or ''} (range {lo}-{hi}) and "
                f"{e['artefact_rel']} grades it at {c['graded_target']}, "
                f"outside the intent's own declared range")
    return {
        "verdict": "REJECT",
        "intent": intent,
        "artefact": artefact,
        "disarmed": disarmed,
        "unreadable": unreadable,
        "findings_per_block": findings,
        "contradiction": (
            "; ".join(parts)
            + ". A1 copies the intent into spec.json once and no gate reads "
              "the intent again, so the stage sized, swept, laid out and "
              "packaged these block(s) against a spec that is not the one "
              "asked for, and every A-gate is green because each compares "
              "the artefact with the artefact."),
        # `test` is filled in by `emit_test` once the run's own regression
        # has actually been WRITTEN — see the note on R1.
    }

# ─────────────────────────────────────────────────────────────────────────────
# the rejection's executable test
# ─────────────────────────────────────────────────────────────────────────────
# THE TEST BELONGS TO THE RUN, NOT TO THE PLUGIN. The doctrine is that a
# rejection must be proven by an executable test that FAILS TODAY and passes
# when the defect is repaired. A test that fails today cannot be a test in the
# plugin's own suite — it would be a permanent red about someone else's design.
# So the review EMITS it into the run tree it is reviewing: the run's own
# regression, red until the run is fixed. The plugin's suite then proves the
# only thing that is the plugin's business — that the emitted test really does
# fail on the defective artefact and really does pass on the repaired one.
#
# The emitted file is self-contained (stdlib only), is a valid pytest module
# AND a valid `python3 <file>` script, and resolves the run root by walking up
# from itself to the directory carrying `phase1/generated_docs`, so moving the
# run does not break it and no absolute path is baked in.
_EMITTED_TEST = r'''#!/usr/bin/env python3
"""AUTO-EMITTED by `{program}` from a stage-{stage} ON-PASS review rejection.

    {contradiction}

This test FAILS while that is true of this run tree and PASSES once it is
repaired. It reads only this run's own INTENT and ARTEFACT — no oracle, no
harness, no golden — and it re-derives nothing: it runs no tool and rebuilds no
artefact.

REPAIR is one of exactly two things, and which one is a design decision this
test does not make:
  * the stage builds the module the intent names, or
  * the intent is corrected to name the module the design actually tops out
    at, and the {n_restamped} report(s) carrying design_identity.top are
    regenerated from it.
"""
import json
import re
import sys
from pathlib import Path

INTENT_REL = {intent_rel!r}
RTL_RELS = {rtl_rels!r}
_MODULE_RE = re.compile(r"(?m)^[ \t]*module\s+([A-Za-z_]\w*)")


def run_root() -> Path:
    for d in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
        if (d / "phase1" / "generated_docs").is_dir():
            return d
    raise AssertionError("no run root above %s" % __file__)


def test_the_intent_names_a_top_module_this_run_actually_builds():
    root = run_root()
    intent = json.loads((root / INTENT_REL).read_text(encoding="utf-8",
                                                      errors="replace"))
    declared = intent.get("top_module")
    modules = set()
    for rel in RTL_RELS:
        d = root / rel
        if not d.is_dir():
            continue
        for ext in ("*.v", "*.sv", "*.vh", "*.svh"):
            for f in sorted(d.glob(ext)):
                modules |= set(_MODULE_RE.findall(
                    f.read_text(encoding="utf-8", errors="replace")))
    assert modules, (
        "%s staged no readable module; this test refutes nothing over an empty "
        "artefact" % ", ".join(RTL_RELS))
    assert declared, "%s declares no top_module" % INTENT_REL
    assert declared in modules, (
        "%s declares top_module=%r and this run builds %d module(s), none of "
        "them %r: %s" % (INTENT_REL, declared, len(modules), declared,
                         ", ".join(sorted(modules))))


if __name__ == "__main__":
    try:
        test_the_intent_names_a_top_module_this_run_actually_builds()
    except AssertionError as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    print("PASS: the intent names a top module this run builds")
'''


_EMITTED_TEST_R2 = r'''#!/usr/bin/env python3
"""AUTO-EMITTED by `{program}` from a stage-{stage} ON-PASS review rejection.

    {contradiction}

This test FAILS while that is true of this run tree and PASSES once it is
repaired. It reads only this run's own INTENT and ARTEFACT — no oracle, no
harness, no golden — and it re-derives nothing: it runs no synthesis and
rebuilds no netlist.

REPAIR is one of exactly two things, and which one is a design decision this
test does not make:
  * the stage synthesises a top that carries the declared pin(s), or
  * the intent is corrected to declare the interface this design actually has,
    and every artefact derived from the old pin list is regenerated from it.

It deliberately does NOT assert the reverse direction. Ports the netlist
carries and the intent does not are routine — scan insertion, the wrapper, tie
cells — and asserting on them would make this file red for the flow doing its
job. It also does not assert on a pin the intent itself marks a supply: a
non-power-aware netlist carries no supply port, and that is stage 3's to sign
off.
"""
import json
import re
import sys
from pathlib import Path

INTENT_REL = {intent_rel!r}
INTENT_FIELD = {intent_field!r}
NETLIST_REL = {netlist_rel!r}
SUPPLY_ROLES = ("power", "ground", "supply")
_PORT_RE = re.compile(
    r"(?m)^[ \t]*(input|output|inout)\b[ \t]*"
    r"(?:(?:wire|reg|logic|signed|unsigned)[ \t]+)*"
    r"(?:\[[ \t]*-?\d+[ \t]*:[ \t]*-?\d+[ \t]*\][ \t]*)?"
    r"([A-Za-z_][A-Za-z0-9_$]*)[ \t]*[;,]")
_MODULE_RE = re.compile(
    r"(?ms)^[ \t]*module[ \t]+([A-Za-z_]\w*)\b(.*?)^[ \t]*endmodule")


def run_root() -> Path:
    for d in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
        if (d / "phase1" / "generated_docs").is_dir():
            return d
    raise AssertionError("no run root above %s" % __file__)


def _is_supply(pin) -> bool:
    for key in ("io", "type", "kind", "role", "pin_type"):
        v = pin.get(key)
        if isinstance(v, str) and v.strip().lower() in SUPPLY_ROLES:
            return True
    for key in ("power", "supply", "is_supply", "is_power"):
        if pin.get(key) is True:
            return True
    for key in ("direction", "mode"):
        v = pin.get(key)
        if isinstance(v, str) and v.strip().lower().startswith("supply"):
            return True
    return False


def test_every_pin_the_intent_declares_is_built_by_the_synthesised_top():
    root = run_root()
    intent = json.loads((root / INTENT_REL).read_text(encoding="utf-8",
                                                      errors="replace"))
    pins = [p for p in (intent.get(INTENT_FIELD) or [])
            if isinstance(p, dict) and p.get("name")]
    assert pins, "%s::%s declares no external pin" % (INTENT_REL, INTENT_FIELD)

    text = (root / NETLIST_REL).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    bodies = dict((m.group(1), m.group(2)) for m in _MODULE_RE.finditer(text))
    assert bodies, (
        "%s declares no module; this test refutes nothing over an empty "
        "artefact" % NETLIST_REL)
    # The SAME instantiation shape `_design_module_set._instantiates` uses:
    # `<module> [#(params)] <inst> (`. A looser match (a bare name anywhere in
    # a body) would call a wire named after a module an instantiation, and
    # this file would then disagree with the review that emitted it.
    instantiated = set()
    for name in bodies:
        pat = re.compile(r"\b" + re.escape(name)
                         + r"\s+(?:#\s*\((?:[^;]*?)\)\s*)?[A-Za-z_]\w*\s*"
                         + r"(?:\[[^\]]*\]\s*)?\(")
        for other, body in bodies.items():
            if other != name and pat.search(body):
                instantiated.add(name)
    roots = sorted(set(bodies) - instantiated)
    assert len(roots) == 1, (
        "%s has %d structural roots (%s); with no single root there is no one "
        "interface to compare" % (NETLIST_REL, len(roots), ", ".join(roots)))
    built = set(n for _d, n in _PORT_RE.findall(bodies[roots[0]]))
    assert built, (
        "the netlist's structural top %r declares no port; an empty interface "
        "refutes nothing" % roots[0])

    absent = sorted(str(p["name"]) for p in pins
                    if str(p["name"]) not in built and not _is_supply(p))
    assert not absent, (
        "%s::%s declares %d pin(s); the netlist %s tops out at %r carrying %d "
        "port(s), and %d declared signal pin(s) are not among them: %s. The "
        "top builds: %s" % (INTENT_REL, INTENT_FIELD, len(pins), NETLIST_REL,
                            roots[0], len(built), len(absent),
                            ", ".join(absent), ", ".join(sorted(built))))


if __name__ == "__main__":
    try:
        test_every_pin_the_intent_declares_is_built_by_the_synthesised_top()
    except AssertionError as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    print("PASS: the synthesised top builds every pin the intent declares")
'''


_EMITTED_TEST_R3 = r"""#!/usr/bin/env python3
'''AUTO-EMITTED by `{program}` from a stage-{stage} ON-PASS review rejection.

    {contradiction}

This test FAILS while that is true of this run tree and PASSES once it is
repaired. It reads only this run's own INTENT (the L-docs) and ARTEFACT (the
sign-off deck) — no oracle, no harness, no golden — and it re-derives nothing:
it runs no tool, invokes no router and rebuilds no deck.

REPAIR is one of exactly two things, and which one is a design decision this
test does not make:
  * the sign-off deck is regenerated at the period the intent asks for and
    stage 3 is re-run against it, or
  * the intent is corrected to the period this design is actually specified to
    run at, and the {n_stamped} sign-off artefact(s) closed under the old
    number are regenerated from it.
'''
import json
import re
import sys
from pathlib import Path

INTENT_RELS = {intent_rels!r}
DECK_REL = {deck_rel!r}
ASKED_NS = {asked_ns!r}
PRIMARY_ROLES = ("primary", "master")
_CC = re.compile(r"(?m)^[ \t]*create_clock\b([^\n]*)")
_PER = re.compile(r"-period\s+([0-9]*\.?[0-9]+)")


def run_root():
    for d in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
        if (d / "phase1" / "generated_docs").is_dir():
            return d
    raise AssertionError("no run root above %s" % __file__)


def _pos(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def asked_period_ns(root):
    docs = []
    for rel in INTENT_RELS:
        fp = root / rel
        if fp.is_file():
            docs.append((rel, json.loads(fp.read_text(encoding="utf-8",
                                                      errors="replace"))))
    for rel, d in docs:
        mhz = _pos(d.get("clock_mhz"))
        if mhz:
            return 1000.0 / mhz, "%s::clock_mhz=%s" % (rel, d.get("clock_mhz"))
    for rel, d in docs:
        for i, cd in enumerate(d.get("clock_domains") or []):
            if not isinstance(cd, dict):
                continue
            if str(cd.get("role") or "").lower() not in PRIMARY_ROLES:
                continue
            ns = _pos(cd.get("period_ns"))
            if ns is None:
                mhz = _pos(cd.get("freq_mhz")) or _pos(cd.get("freq_low_mhz"))
                ns = (1000.0 / mhz) if mhz else None
            if ns is not None:
                return ns, "%s::clock_domains[%d] %s" % (rel, i, cd.get("name"))
    return None, "no intent document declares a clock frequency"


def test_the_signoff_deck_is_not_slower_than_the_period_the_intent_asks_for():
    root = run_root()
    asked, why = asked_period_ns(root)
    assert asked is not None, (
        "%s; this test refutes nothing over an intent that asks for no period"
        % why)
    deck = root / DECK_REL
    assert deck.is_file(), (
        "%s does not exist; an absent sign-off deck refutes nothing and "
        "certifies nothing" % DECK_REL)
    text = deck.read_text(encoding="utf-8", errors="replace")
    periods = []
    for m in _CC.finditer(text):
        per = _PER.search(m.group(1))
        if per:
            ns = _pos(per.group(1))
            if ns is not None:
                periods.append(ns)
    assert periods, (
        "%s creates no clock with a period; this test refutes nothing over a "
        "deck that constrains nothing" % DECK_REL)
    fastest = min(periods)
    assert fastest <= asked * (1 + 1e-6), (
        "%s signs off at %s ns (fastest of %d clock(s)) while the intent asks "
        "for %.6g ns (%s): the layout is timed %.3gx slower than the design is "
        "specified to run" % (DECK_REL, fastest, len(periods), asked, why,
                              fastest / asked))


if __name__ == "__main__":
    try:
        test_the_signoff_deck_is_not_slower_than_the_period_the_intent_asks_for()
    except AssertionError as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    print("PASS: the sign-off deck is not slower than the intent (asked "
          "%.6g ns)" % ASKED_NS)
"""


# The stage_analog counterpart. Same contract as the templates above:
# stdlib only, a valid pytest module AND a valid `python3 <file>` script,
# no absolute path baked in, and it RE-DERIVES NOTHING — it runs no
# simulator and rebuilds no deck. It reads this run's own L5 and this
# run's own per-block spec.json and recomputes the comparison the flow
# never makes.
_EMITTED_TEST_ANALOG = r'''#!/usr/bin/env python3
"""AUTO-EMITTED by `{program}` from a stage-{stage} ON-PASS review rejection.

    {contradiction}

This test FAILS while that is true of this run tree and PASSES once it is
repaired. It reads only this run's own INTENT and ARTEFACT — no oracle, no
harness, no golden — and it re-derives nothing: it runs no simulator and
rebuilds no deck.

REPAIR is one of exactly two things, and which one is a design decision this
test does not make:
  * A1 re-extracts the block's spec.json so it carries every numeric
    requirement the intent declares, at the values the intent declares, and
    A2-A9 are RE-RUN on it — a spec change that was never re-simulated is not
    a fix; or
  * the intent is corrected to declare the requirements this design is
    actually held to, and the blocks are re-graded from it.
"""
import json
import sys
from pathlib import Path

INTENT_REL = {intent_rel!r}
ANALOG_RELS = {analog_rels!r}
BLOCKS = {blocks!r}
NUMERIC_KEYS = ("target", "min", "max", "value", "typ")


def run_root() -> Path:
    for d in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
        if (d / "phase1" / "generated_docs").is_dir():
            return d
    raise AssertionError("no run root above %s" % __file__)


def numbers(row):
    out = dict()
    for k in NUMERIC_KEYS:
        v = row.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out[k] = float(v)
    return out


def spec_key(name):
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def test_the_spec_this_run_grades_against_is_the_spec_the_intent_declares():
    root = run_root()
    intent = json.loads((root / INTENT_REL).read_text(encoding="utf-8",
                                                      errors="replace"))
    problems = []
    measured = 0
    for blk in intent.get("analog_blocks") or []:
        if not isinstance(blk, dict):
            continue
        name = str(blk.get("name") or "")
        if name not in BLOCKS:
            continue
        spec = blk.get("spec") if isinstance(blk.get("spec"), dict) else dict()
        reqs = [r for r in (spec.get("specs") or [])
                if isinstance(r, dict) and numbers(r)]
        if not reqs:
            continue
        art = None
        for rel in ANALOG_RELS:
            cand = root / rel / name / "spec.json"
            if cand.is_file():
                art = cand
                break
        assert art is not None, (
            "%s declares %d numeric requirement(s) for block %r and no "
            "spec.json resolves under %s" % (INTENT_REL, len(reqs), name,
                                             ", ".join(ANALOG_RELS)))
        adoc = json.loads(art.read_text(encoding="utf-8", errors="replace"))
        arows = [r for r in (adoc.get("specs") or []) if isinstance(r, dict)]
        by_key = dict()
        for r in arows:
            by_key.setdefault(spec_key(r.get("name")), numbers(r))
        value_sets = [set(v.values()) for v in by_key.values() if v]
        measured += 1
        for req in reqs:
            k = spec_key(req.get("name"))
            want = numbers(req)
            if k not in by_key:
                if not any(set(want.values()) <= vs for vs in value_sets):
                    problems.append(
                        "%s: block %r requires %r %s and %s carries no such "
                        "row" % (INTENT_REL, name, req.get("name"), want,
                                 art.relative_to(root)))
                continue
            got = by_key[k]
            target = got.get("target", got.get("value", got.get("typ")))
            lo, hi = want.get("min"), want.get("max")
            if target is None or (lo is None and hi is None):
                continue
            if (lo is not None and target < lo) or (hi is not None
                                                    and target > hi):
                problems.append(
                    "%s: block %r requires %r in [%s, %s] and %s grades it at "
                    "%s" % (INTENT_REL, name, req.get("name"), lo, hi,
                            art.relative_to(root), target))
    assert measured, (
        "no block of %s was measured; this test refutes nothing over an empty "
        "scope" % ", ".join(BLOCKS))
    assert not problems, (
        "the spec %d block(s) are graded against is not the spec the intent "
        "declares:\n  " % measured + "\n  ".join(problems))


if __name__ == "__main__":
    try:
        test_the_spec_this_run_grades_against_is_the_spec_the_intent_declares()
    except AssertionError as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    print("PASS: every declared numeric requirement is in the graded spec")
'''

def _body_r1(finding: Dict[str, Any], stage_id: str) -> str:
    return _EMITTED_TEST.format(
        program=_NAME, stage=stage_id,
        contradiction=finding["contradiction"],
        n_restamped=len(finding.get("restamped_in") or []),
        intent_rel=finding["intent"]["intent_rel"],
        rtl_rels=list(finding["artefact"]["rtl_dirs"]))


def _body_r2(finding: Dict[str, Any], stage_id: str) -> str:
    return _EMITTED_TEST_R2.format(
        program=_NAME, stage=stage_id,
        contradiction=finding["contradiction"],
        intent_rel=finding["intent"]["intent_rel"],
        intent_field=finding["intent"]["field"],
        netlist_rel=finding["artefact"]["artefact_rel"])


def _body_r3(finding: Dict[str, Any], stage_id: str) -> str:
    return _EMITTED_TEST_R3.format(
        program=_NAME, stage=stage_id,
        contradiction=finding["contradiction"],
        n_stamped=len(finding.get("signed_off_under") or []),
        intent_rels=list(finding["intent"].get("read") or []),
        deck_rel=finding["artefact"]["file"],
        asked_ns=float(finding["intent"]["period_ns"]))


def _body_analog(finding: Dict[str, Any], stage_id: str) -> str:
    """The BODY only. `emit_test` is the one writer and does the rest.

    Every argument is read back out of the finding the rule already published,
    so there is nothing for the rule to smuggle through the record a landing
    reads.
    """
    return _EMITTED_TEST_ANALOG.format(
        program=_NAME, stage=stage_id,
        contradiction=finding["contradiction"],
        intent_rel=finding["intent"]["intent_rel"],
        analog_rels=list(finding["artefact"]["artefact_rels"]),
        blocks=[b["block"] for b in finding["artefact"]["blocks"]])

def emit_test(dest: Path, finding: Dict[str, Any], stage_id: str) -> Path:
    """Write the run's own regression for this rejection and return its path.

    A rule with no emitter raises KeyError here rather than writing somebody
    else's test — `review()` then leaves `test` absent and the
    unproven-rejection branch refuses the rejection, which is correct: a
    rejection whose test could not be written is not proven.
    """
    body = _EMITTERS[finding["rule"]](finding, stage_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return dest


#: The rules this program runs, per stage. A stage with no rule is NOT CHECKED.
#:
#: ONE RULE PER STAGE, AND WHY EACH IS THE STAGE'S OWN. R1 reads the intent
#: against stage 1's RTL — the only artefact in the flow that is a TRANSLATION
#: of the intent. R2 reads it against stage 2's NETLIST, which is the first
#: artefact whose interface is CONCRETE (parameters resolved, wrapper chosen)
#: and the artefact stage 3 builds. They are not the same question and neither
#: subsumes the other: MEASURED on the published corpus, R1 DISARMS on
#: `ic/opentitan_aes` (its intent declares it read no top out of the input) and
#: R2 rejects it.
_RULES = {
    "stage1": [("R1_INTENT_TOP_NOT_BUILT", rule_intent_top_not_built)],
    "stage2": [("R2_INTENT_PIN_NOT_IN_NETLIST", rule_intent_pin_not_in_netlist)],
    "stage3": [("R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT",
                rule_signoff_clock_slower_than_intent)],    "stage_analog": [("R_ANALOG_INTENT_SPEC_NOT_THE_GRADED_SPEC",
                       rule_intent_spec_not_the_graded_spec)],

}

#: The emitter for each rule's own regression. Keyed by rule id, beside
#: `_RULES`, so a rule added without one fails loudly at emit time.
_EMITTERS = {"R1_INTENT_TOP_NOT_BUILT": _body_r1,
             "R2_INTENT_PIN_NOT_IN_NETLIST": _body_r2,
             "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT": _body_r3,
             "R_ANALOG_INTENT_SPEC_NOT_THE_GRADED_SPEC": _body_analog}


# ─────────────────────────────────────────────────────────────────────────────
# the evidence contract
# ─────────────────────────────────────────────────────────────────────────────
def unproven(finding: Dict[str, Any], requires) -> List[str]:
    """Parts of `rejection_requires:` this rejection does not carry."""
    missing = []
    for part in requires:
        v = finding.get(str(part))
        if v is None or (isinstance(v, (str, list, dict)) and len(v) == 0):
            missing.append(str(part))
    return missing


def review(project: Path, stage_id: str, decl: Dict[str, Any],
           emit_dir: Optional[Path] = None) -> Dict[str, Any]:
    requires = tuple(decl.get("rejection_requires")
                     or _DEFAULT_REJECTION_REQUIRES)
    emit_dir = emit_dir or (project / str(decl.get("emit_test_dir")
                                          or _DEFAULT_EMIT_DIR))
    rec: Dict[str, Any] = {
        "program": _NAME, "stage": stage_id, "project": str(project),
        "skill": decl.get("skill"), "verdict_policy": decl.get("verdict"),
        "rejection_requires": list(requires),
        "rules": [], "rejections": [], "observations": [],
        "unproven_rejections": [], "not_checked": [],
    }
    for rule_id, fn in _RULES.get(stage_id, []):
        out = fn(project, decl)
        out["rule"] = rule_id
        rec["rules"].append({"rule": rule_id, "verdict": out["verdict"]})
        if out["verdict"] == "REJECT":
            # WRITE the run's own regression FIRST, then judge the evidence.
            # The order is the point: `test` is a path that exists, not a
            # citation. An emit that fails leaves `test` absent, and the
            # unproven-rejection branch below then refuses the rejection —
            # which is correct, because nothing was proven.
            try:
                dest = emit_test(emit_dir / f"test_{rule_id.lower()}.py",
                                 out, stage_id)
                out["test"] = str(dest.relative_to(project)) \
                    if dest.is_absolute() and project in dest.parents \
                    else str(dest)
            except OSError as e:
                out["emit_error"] = str(e)
            missing = unproven(out, requires)
            if missing:
                out["missing_evidence"] = missing
                rec["unproven_rejections"].append(out)
            else:
                rec["rejections"].append(out)
        elif out["verdict"] in ("DISARMED", "ACCEPT"):
            rec["observations"].append(out)
        else:
            rec["not_checked"].append(out)
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# how each rule renders the evidence it read
# ─────────────────────────────────────────────────────────────────────────────
# The four required parts are the SAME for every rule; what INTENT and ARTEFACT
# look like is not. R1's artefact is a directory of RTL and a module set; R2's
# is one netlist file and a port list. One printer that tried to render both
# would have to speak in a vocabulary that fits neither.
def _print_r1(f: Dict[str, Any]) -> None:
    i, art = f["intent"], f["artefact"]
    print(f"    INTENT   {i['file']} :: {i['field']} = {i['value']!r}")
    print(f"    ARTEFACT {', '.join(art['rtl_dirs']) or '(none)'} "
          f"declares {art['module_count']} module(s): "
          f"{', '.join(art['modules'][:8])}"
          f"{', …' if len(art['modules']) > 8 else ''}")
    if f.get("restamped_in"):
        print(f"    RESTAMPED design_identity.top={i['value']!r} in "
              f"{len(f['restamped_in'])} report(s), e.g. "
              f"{f['restamped_in'][0]}")


def _print_r2(f: Dict[str, Any]) -> None:
    i, art = f["intent"], f["artefact"]
    absent = [r["name"] for r in f["absent_signal_pins"]]
    print(f"    INTENT   {i['file']} :: {i['field']} declares "
          f"{len(i['pins'])} external pin(s): {', '.join(i['value'][:8])}"
          f"{', …' if len(i['value']) > 8 else ''}")
    print(f"    ARTEFACT {art['artefact_rel']} tops out at {art['top']!r} "
          f"carrying {len(art['ports'])} port(s): "
          f"{', '.join(art['port_names'][:8])}"
          f"{', …' if len(art['port_names']) > 8 else ''}")
    print(f"    ABSENT   {len(absent)} declared signal pin(s) the netlist does "
          f"not build: {', '.join(absent)}")
    for r in f["absent_signal_pins"][:8]:
        print(f"               {r['name']} ({r['direction']}) declared in "
              f"{r['evidence']}")
    if f.get("disarmed"):
        print(f"    DISARMED {len(f['disarmed'])} further absent pin(s) the "
              f"intent itself declares a supply, not counted: "
              + ", ".join(f"{r['name']} [{r['intent_declares_supply']}]"
                          for r in f["disarmed"]))
    if art.get("extra_ports_not_in_intent"):
        print(f"    NOT A FINDING the netlist also carries "
              f"{len(art['extra_ports_not_in_intent'])} port(s) the intent "
              f"does not declare "
              f"({', '.join(art['extra_ports_not_in_intent'][:8])}"
              f"{', …' if len(art['extra_ports_not_in_intent']) > 8 else ''}); "
              f"scan insertion and the wrapper add ports legitimately, so this "
              f"rule never rejects on them")


def _print_r3(f: Dict[str, Any]) -> None:
    i, art, fc = f["intent"], f["artefact"], f["artefact"]["fastest_clock"]
    print(f"    INTENT   {i['file']} :: {i['field']} = {i['value']!r} asks for "
          f"{float(i['period_ns']):.6g} ns ({i['tier']})")
    print(f"    ARTEFACT {art['file']} — the deck stage 3 signed off against — "
          f"creates {art['clock_count']} clock(s); fastest {fc['period_ns']} "
          f"ns: {fc['line']}")
    if f.get("signed_off_under"):
        s = f["signed_off_under"]
        print(f"    SIGNED OFF UNDER {fc['period_ns']} ns in {len(s)} "
              f"artefact(s):")
        for r in s[:8]:
            print(f"               {r['file']} ({r['evidence']})")
    else:
        print(f"    SIGNED OFF UNDER no sign-off artefact in this run yet "
              f"carries the refuted period; the contradiction is between the "
              f"intent and the deck and does not depend on one existing")


def _print_analog(f: Dict[str, Any]) -> None:
    """R_ANALOG's own evidence lines.

    Neither of the printers above fits: R1 renders a declared top against a
    module set and R2 a pin list against a netlist's ports. This rule's pair is
    a per-block REQUIREMENT SET against the spec.json the stage grades on, and
    it measures SEVERAL subjects — so the denominator is part of the evidence
    and is printed, not left for a reader to infer from a count of rules.
    """
    i, art = f["intent"], f["artefact"]
    n_req = sum(len(b["intent_requirements"]) for b in art["blocks"])
    print(f"    INTENT   {i['file']} :: {i['field']} declares {n_req} numeric "
          f"requirement(s) over {art['block_count']} block(s) in scope")
    for b in art["blocks"]:
        print(f"               {b['block']}: "
              + ", ".join(str(r["name"]) for r in b["intent_requirements"]))
    print(f"    ARTEFACT the spec every A2-A9 gate grades against:")
    for b in art["blocks"]:
        print(f"               {b['artefact_rel']} carries "
              f"{len(b['artefact_specs'])} row(s)"
              + (f" (extraction_strategy="
                 f"{b['artefact_extraction_strategy']!r})"
                 if b.get("artefact_extraction_strategy") else "")
              + ": " + (", ".join(str(n) for n in b["artefact_specs"])
                        or "(none)"))
    for b in f["findings_per_block"]:
        if b["dropped"]:
            print(f"    DROPPED  {b['block']}: {len(b['dropped'])} declared "
                  f"requirement(s) absent from {b['artefact_rel']} under "
                  f"neither name nor value: "
                  + ", ".join(f"{d['name']!r} {d['declared']}"
                              for d in b["dropped"]))
        for c in b["contradicted"]:
            print(f"    OUT OF RANGE {b['block']}: the intent declares "
                  f"{c['name']!r} in "
                  f"[{c['declared'].get('min')}, {c['declared'].get('max')}] "
                  f"{c['unit'] or ''} and {b['artefact_rel']} grades it at "
                  f"{c['graded_target']}")
    print(f"    DENOMINATOR {len(f['findings_per_block'])} of "
          f"{art['block_count']} block(s) measured contradict the intent; "
          f"{len(f.get('disarmed') or [])} disarmed by the intent's own "
          f"disclosure, {len(f.get('unreadable') or [])} with no readable "
          f"spec.json")

_PRINTERS = {"R1_INTENT_TOP_NOT_BUILT": _print_r1,
             "R2_INTENT_PIN_NOT_IN_NETLIST": _print_r2,
             "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT": _print_r3,
             "R_ANALOG_INTENT_SPEC_NOT_THE_GRADED_SPEC": _print_analog}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog=_NAME, description="ON-PASS review of a flow stage's artefact "
                                "against the design intent")
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--stage", required=True, help="stage id, e.g. stage1")
    p.add_argument("--flow-def", type=Path, default=_DEFAULT_FLOW)
    p.add_argument("--compliance", type=Path,
                   help="flow_compliance_check --json report; the source of "
                        "the stage's PASS")
    p.add_argument("--stage-verdict",
                   help="state the stage's verdict directly instead of "
                        "reading a compliance report")
    p.add_argument("--json", type=Path, help="write the review record here")
    p.add_argument("--emit-test", type=Path,
                   help="directory for the run's own regression emitted with "
                        "each rejection (default: the stage's "
                        "`emit_test_dir:`, else "
                        f"{_DEFAULT_EMIT_DIR})")
    a = p.parse_args(argv)

    project = Path(a.project_dir).resolve()

    def emit(rec: Dict[str, Any]) -> None:
        # vibe-ic#1082 — ATOMIC, because this record is a VERDICT.
        #
        # Every `emit()` call below carries the review's answer: NOT_CHECKED
        # with its reason, or the rejections a landing acts on. A `write_text`
        # that dies mid-write leaves a half-parsed verdict at the declared
        # destination, and the next reader takes it as this step's evidence —
        # the exact lie #1082 exists to remove.
        #
        # `ensure_ascii=True` and `sort_keys=True` reproduce `json.dumps`'s
        # defaults for the call this replaces, so the BYTES do not move; the
        # trailing newline comes from `write_json` itself.
        if a.json:
            a.json.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(a.json, rec, indent=2, ensure_ascii=True,
                              sort_keys=True)

    try:
        decl = load_declaration(a.flow_def, a.stage)
    except ValueError as e:
        emit({"program": _NAME, "stage": a.stage, "verdict": "NOT_CHECKED",
              "why": str(e)})
        print(f"{_NAME}: rc=2 NOT CHECKED — {e}")
        return 2
    if not decl:
        emit({"program": _NAME, "stage": a.stage, "verdict": "NOT_CHECKED",
              "why": "the stage declares no on_pass_review"})
        print(f"{_NAME}: rc=2 NOT CHECKED — stage {a.stage!r} declares no "
              f"`on_pass_review:` block in {a.flow_def}. The review is "
              f"declared in the flow; a stage that does not declare one has "
              f"not been reviewed.")
        return 2

    denied = denied_intent_paths(project, [str(x) for x in decl.get("intent") or []],
                                 [str(x) for x in decl.get("intent_deny") or []])
    if denied:
        emit({"program": _NAME, "stage": a.stage, "verdict": "NOT_CHECKED",
              "why": "denied intent path", "denied": denied})
        print(f"{_NAME}: rc=2 NOT CHECKED — §4.05: {len(denied)} declared "
              f"intent path(s) resolve under a denied segment:")
        for d in denied:
            print(f"    {d['path']}  (denied segment {d['denied_segment']!r})")
        print("    The review reads the design INPUT. A reviewer allowed to "
              "read the oracle, the harness or the golden is grading itself.")
        return 2

    fired = stage_passed(a.compliance, a.stage, a.stage_verdict)
    if fired["passed"] is None:
        emit({"program": _NAME, "stage": a.stage, "verdict": "NOT_CHECKED",
              "why": fired["why"], "fires_on": decl.get("fires_on")})
        print(f"{_NAME}: rc=2 NOT CHECKED — {fired['why']}. The review fires "
              f"on {decl.get('fires_on')!r}; it does not run on an "
              f"unestablished verdict.")
        return 2
    if not fired["passed"]:
        emit({"program": _NAME, "stage": a.stage, "verdict": "NOT_CHECKED",
              "why": fired["why"], "fires_on": decl.get("fires_on")})
        print(f"{_NAME}: rc=2 NOT CHECKED — stage {a.stage} did not pass "
              f"({fired['why']}). This review reviews a PASS; a stage that "
              f"failed is the repair tier's, not this one's.")
        return 2

    if a.stage not in _RULES:
        emit({"program": _NAME, "stage": a.stage, "verdict": "NOT_CHECKED",
              "why": "no on-pass rule is implemented for this stage"})
        print(f"{_NAME}: rc=2 NOT CHECKED — stage {a.stage!r} declares an "
              f"on-pass review but this program implements no rule for it.")
        return 2

    rec = review(project, a.stage, decl,
                 emit_dir=a.emit_test.resolve() if a.emit_test else None)
    rec["stage_pass"] = fired
    emit(rec)

    if rec["unproven_rejections"]:
        print(f"{_NAME}: rc=2 NOT CHECKED — {len(rec['unproven_rejections'])} "
              f"finding(s) could not be proven and were NOT emitted as "
              f"rejections:")
        for f in rec["unproven_rejections"]:
            print(f"    {f['rule']}: missing {', '.join(f['missing_evidence'])}")
        print("    A rejection must carry the intent it read, the artefact "
              "fact it read, the contradiction, and an executable test that "
              "fails today. An unproven rejection manufactures confidence, "
              "which is what this review exists to prevent.")
        return 2

    if rec["not_checked"]:
        print(f"{_NAME}: rc=2 NOT CHECKED — {len(rec['not_checked'])} rule(s) "
              f"could not read what they need:")
        for f in rec["not_checked"]:
            print(f"    {f['rule']}: {f.get('why')}")
        return 2

    for f in rec["observations"]:
        if f["verdict"] == "DISARMED":
            print(f"{_NAME}: [INFO] {f['rule']} DISARMED — {f['observation']}")
        # A RULE THAT MEASURES SEVERAL SUBJECTS REPORTS ITS OWN DENOMINATOR.
        # The summary line at the end counts RULES, so a rule that accepted
        # after the intent's disclosure took some of its own subjects out of
        # scope would otherwise be summarised as "0 disarmed" over a non-empty
        # disarm set. INERT for R1 and R2: neither carries `observation` on an
        # ACCEPT, and `test_the_accept_observation_branch_is_inert_for_the_
        # other_stages` in tests/test_stage_analog_on_pass_review.py pins that.
        elif f["verdict"] == "ACCEPT" and f.get("observation"):
            print(f"{_NAME}: [INFO] {f['rule']} ACCEPT — {f['observation']}")

    if rec["rejections"]:
        print(f"{_NAME}: REJECT — {len(rec['rejections'])} proven "
              f"contradiction(s) between the intent and the stage-{a.stage} "
              f"artefact:")
        for f in rec["rejections"]:
            print(f"  [{f['rule']}]")
            _PRINTERS[f["rule"]](f)
            print(f"    CONTRADICTION {f['contradiction']}")
            print(f"    TEST     {f['test']}  (emitted; FAILS on this run, "
                  f"passes when repaired — run it with `python3` or pytest)")
        print(f"    verdict policy: {decl.get('verdict')!r} — this review "
              f"reports; the test above is what blocks. Residue for "
              f"`{decl.get('skill')}`.")
        return 1

    n_ok = sum(1 for f in rec["observations"] if f["verdict"] == "ACCEPT")
    n_dis = sum(1 for f in rec["observations"] if f["verdict"] == "DISARMED")
    print(f"{_NAME}: ACCEPT — stage {a.stage} passed and its artefact does not "
          f"contradict the intent ({n_ok} rule(s) accepted, {n_dis} disarmed "
          f"by the intent's own disclosure).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
