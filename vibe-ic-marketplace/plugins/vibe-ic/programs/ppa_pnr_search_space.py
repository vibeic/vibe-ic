#!/usr/bin/env python3
"""ppa_pnr_search_space.py — the PLACE-AND-ROUTE search space, MEASURED against
the runner that would have to apply it.

WHY THIS PROGRAM EXISTS (F-1)
=============================
`crosslayer_search_space.py` emits the cross-layer space and publishes eight
place-and-route levers it deliberately withholds, with this reason:

    "these are the place-and-route knobs the PnR-only search already owns"

MEASURED on the tree that shipped it: there was no PnR-only search. No program
under `programs/` emitted a space containing those levers, so a downloaded
plugin that wanted to search the knobs its OWN runner exposes had no space
document to feed `ppa_search_run.py`, and the sentence above named an owner that
did not exist. A search still ran -- the end-to-end lane hand-authored a space
-- which is the part that matters: a published search record cited a space that
nothing could re-emit, so nobody else could draw from the same one.

This program is that owner. It emits a space in `crosslayer_search_space.py`'s
output shape, so `_ppa.search.values_from_space` reads it unchanged.

NOTHING HERE IS ASSERTED ABOUT THE FLOW. IT IS MEASURED.
========================================================
A space document that DECLARED "this flow can search cell padding" would be a
sentence with the same failure mode as the one above: true when written, silent
when it stops being true. So admission is measured, twice over, against
`phase3_one_shot_runner.py` itself:

    which levers are ADMITTED   the runner's argparse surface, read from its
                                source. A lever is admitted when a flag that
                                applies it is actually on the CLI, and REFUSED
                                as NOT_EXPOSED when none is -- naming the flags
                                that were looked for.
    whether a VALUE is real     the runner's OWN normaliser is called on it.
                                `--util 1.5` is not an error, it is silently
                                read as 1.5 % and becomes 0.015; two candidates
                                that differ only there are the same run wearing
                                two names. A value the runner would CHANGE is
                                refused here, before it reaches a manifest.

THIS PROGRAM INVENTS NO VALUE
=============================
It does not decide that utilisation should be searched at 0.20/0.30/0.40. That
is a decision about a design and a machine budget, and a program that made it
would be choosing what the search should try first while claiming to describe
what may be searched. So an admitted lever's domain is PROSE by default --
`_ppa.search.values_from_space` records it NOT_ENUMERABLE and says the lever was
not varied -- and the caller supplies values with `--values LEVER=a,b,c`, which
are recorded as the CALLER's, round-tripped through the runner, and published
with the invocation that chose them.

A LEVER CAN BE REAL AND STILL NOT BE FREE BELOW A FLOOR
======================================================
Admission here is measured against the runner's CLI, and that is the right
question for "can this flow apply the lever". It is NOT the whole question for
"may a search visit this VALUE".

MEASURED. `--spare-density` is on the runner's command line, so this program
admitted it, and its own note said: "0 disables spare insertion, which is a
legitimate arm of a search and not the same as leaving the flag out". A
cross-layer search took that at its word, ran `--spare-density 0`, deleted all
ten of one design's spare/ECO cells, and won on area. Spares are what make a
bug found after tape-out fixable by a metal-only ECO instead of a base-layer
respin, so what that arm actually searched was whether the design should remain
repairable -- and nothing in the space said that was not on the table.

The sentence was not wrong, it was UNCONDITIONAL. Disabling spare insertion is
a legitimate arm for a design that has declared it needs no spare population.
For a design that has DECLARED one, zero is not a point in the space: it is a
full place-and-route run spent producing a candidate the promotion gate must
refuse. So when `--eco-declaration` supplies a design-for-ECO requirement,
`spare_cell_density` is admitted BOUNDED BELOW and a zero value is refused with
the declaration cited.

WHAT THIS PROGRAM STILL CANNOT DO, AND SAYS SO. A declared floor is a COUNT of
spare cells; this lever is a DENSITY as a fraction of placed cells. Converting
one to the other needs the design's placed-cell count, which is a property of a
run that has not happened yet, so a positive density cannot be refused here.
Zero can: zero density inserts zero spares on a design of any size. The
count is enforced downstream by `_ppa/feasibility.py`'s `eco_readiness` axis,
and the space row says that rather than implying it checked.

EXIT CODES (docs/PPA_INTERFACES.md 1)
=====================================
    0  a space was emitted (it may legitimately admit nothing)
    1  REFUSED -- a value the runner would not apply as written, a value below
       a declared design-for-ECO floor, or a space whose self-audit failed
    2  [CANNOT CHECK] -- the runner could not be read, or could not be asked
       about a value the caller supplied. Never rc=0: a space measured against
       a runner nobody looked at is a space that describes nothing.
    3  bad invocation

chip-AGNOSTIC: no IC, vendor, SKU, process or PDK name appears in this file.
The lever vocabulary is ordinary place-and-route terminology.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_json as atomic_write_json  # noqa: E402
from _ppa import cli_exit  # noqa: E402 — PPA_INTERFACES §1: a bad invocation is 3
# The ONE reader of a design-for-ECO declaration. This program does not parse
# the block itself: the space and the promotion gate must agree about what
# "this design requires spares" means, and two parsers is how they stop
# agreeing.
from _ppa import feasibility as feas  # noqa: E402

PROGRAM = "ppa_pnr_search_space"
DEFAULT_JSON_REL = "reports/ppa_pnr_search_space.json"

RC_PASS = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

MARK_CANNOT_CHECK = "[CANNOT CHECK]"
MARK_REFUSE = "[REFUSE]"

#: The runner this space is measured against. It is the program that would have
#: to APPLY every lever, so it is the only thing that can say which exist.
RUNNER_REL = "phase3_one_shot_runner.py"

STATUS_EXPOSED = "EXPOSED"
STATUS_NOT_EXPOSED = "NOT_EXPOSED"
#: Admitted, and NOT free across its whole range: a declared requirement puts a
#: floor under it. Distinct from EXPOSED so a reader of the space can see at a
#: glance that a lever carries a bound, rather than having to find the bound.
STATUS_BOUNDED_BELOW = "BOUNDED_BELOW"

#: No `--eco-declaration` was supplied. Deliberately NOT the same string as the
#: gate's `NOT_DECLARED`, which means a document WAS read and declares no
#: requirement. "nobody told this program" and "the design says it needs none"
#: are different facts and only one of them is a statement about the design.
ECO_NOT_SUPPLIED = "NOT_SUPPLIED"

#: The eight names `crosslayer_search_space.py` withholds, plus the two this
#: flow additionally drives. Every one gets a row whether or not the runner
#: exposes it, because "this flow cannot search cell padding" is a fact a
#: reader of a search record needs, and an absent row does not state it.
#:
#: `flags` is every spelling that would apply the lever. `normaliser` names the
#: runner's own guard for that flag -- the function the runner really calls --
#: or None where the flag takes no normalised scalar.
LEVERS: Tuple[Dict[str, Any], ...] = (
    {
        "lever": "placement_density",
        "layer": "placement",
        "kind": "fraction",
        "flags": ("--util",),
        "normaliser": "_normalize_util",
        "domain": ("a global-placement density FRACTION; the runner's own "
                   "guard normalises and clamps it, and a value it would "
                   "change is refused by this program rather than searched"),
        "note": ("passed to the placer as its density target. It is NOT the "
                 "die-sizing utilisation: this flow keeps those two "
                 "decoupled and only one of them is on the CLI"),
    },
    {
        "lever": "die_geometry",
        "layer": "floorplan",
        "kind": "categorical_or_dimension",
        "flags": ("--die-um",),
        "normaliser": None,
        "domain": ("`auto`, or an explicit die W x H in microns. The explicit "
                   "values are a statement about ONE design's geometry, so "
                   "this program does not propose any; supply them"),
        "note": ("`auto` sizes the die from the synthesised cell count and "
                 "the PDK site area; an explicit W x H overrides that "
                 "outright"),
    },
    {
        "lever": "spare_cell_density",
        "layer": "design_for_eco",
        "kind": "fraction",
        "flags": ("--spare-density",),
        "normaliser": "_compute_spare_density",
        "domain": ("the design-for-ECO spare-cell density as a fraction of "
                   "placed cells; the runner clamps it and a clamped value is "
                   "refused here rather than searched"),
        "note": ("0 disables spare insertion. That is a legitimate arm of a "
                 "search ONLY for a design that has declared it needs no "
                 "spare/ECO population. Where a declaration requires one, "
                 "zero is refused with the declaration cited: spares are what "
                 "make a post-tape-out bug fixable by a metal-only ECO rather "
                 "than a base-layer respin, and deleting them is not a "
                 "cheaper implementation of the same chip"),
        "eco_bounded": True,
    },
    {"lever": "core_utilisation", "layer": "floorplan", "kind": "fraction",
     "flags": ("--core-util", "--core-utilisation", "--core-utilization"),
     "normaliser": None,
     "domain": "the floorplan core utilisation target",
     "note": ("this flow computes its die-sizing utilisation target from a "
              "module constant, not from a flag, so a search cannot move it")},
    {"lever": "core_aspect_ratio", "layer": "floorplan", "kind": "ratio",
     "flags": ("--aspect-ratio", "--core-aspect-ratio"),
     "normaliser": None,
     "domain": "core height / core width",
     "note": ("a non-square die is expressible only by naming both dimensions "
              "through the die-geometry lever, which is a different lever "
              "with a different domain")},
    {"lever": "cell_padding", "layer": "placement", "kind": "integer",
     "flags": ("--cell-padding", "--pad-left", "--pad-right"),
     "normaliser": None, "domain": "site columns of padding per instance",
     "note": "no flag applies it in this flow"},
    {"lever": "cts_cluster_size", "layer": "cts", "kind": "integer",
     "flags": ("--cts-cluster-size",), "normaliser": None,
     "domain": "sinks per clock-tree cluster",
     "note": "no flag applies it in this flow"},
    {"lever": "cts_cluster_diameter", "layer": "cts", "kind": "number",
     "flags": ("--cts-cluster-diameter",), "normaliser": None,
     "domain": "clock-tree cluster diameter in microns",
     "note": "no flag applies it in this flow"},
    {"lever": "routing_layer_adjust", "layer": "route", "kind": "fraction",
     "flags": ("--layer-adjust", "--routing-layer-adjust"),
     "normaliser": None, "domain": "per-layer routing resource derate",
     "note": "no flag applies it in this flow"},
    {"lever": "clock_period", "layer": "constraints", "kind": "number",
     "flags": ("--clock-period", "--period"), "normaliser": None,
     "domain": "target clock period in nanoseconds",
     "note": ("the period comes from the design's own constraints, not from "
              "the runner's CLI. A search that moved it would be searching a "
              "different requirement, not a different implementation")},
)


# ---------------------------------------------------------------------------
# the design's design-for-ECO declaration -- read, never invented
# ---------------------------------------------------------------------------
def read_eco_declaration(path: Optional[str]
                         ) -> Tuple[Dict[str, Any], Optional[str]]:
    """(the ECO context this space is bounded by, reason-it-could-not-be-read).

    A declaration that was NAMED and could not be read is not "no requirement".
    It is a [CANNOT CHECK], and the caller turns the second return value into
    rc=2 -- because publishing an unbounded space from an unreadable
    requirement is exactly how a search comes to visit the value the
    requirement forbade.

    The block is parsed by `_ppa/feasibility.eco_requirement_state` and not
    here. The space and the gate must agree about what "this design requires
    spares" means, and two parsers is how they stop agreeing.
    """
    if not path:
        return ({"state": ECO_NOT_SUPPLIED, "declared_in": None,
                 "min_spare_cells": None,
                 "reason": ("no --eco-declaration was supplied, so this "
                            "program was not told whether this design "
                            "requires a spare/ECO population. That is not a "
                            "finding that it requires none")}, None)
    p = Path(path)
    if not p.is_file():
        return {}, f"{p} does not exist"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {}, f"{p} is unreadable: {exc}"
    if not isinstance(doc, dict):
        return {}, f"{p} is a {type(doc).__name__}, not an object"
    block = doc.get("eco_readiness", doc)
    state, code, detail = feas.eco_requirement_state(block)
    if state == feas.ECO_UNREADABLE:
        return {}, (f"{p} states a design-for-ECO requirement this program "
                    f"cannot read ({code}): "
                    f"{detail.get('reason', 'no reason given')}")
    obligations = detail.get("obligations") or {}
    return ({"state": state,
             "declared_in": str(p),
             "min_spare_cells": obligations.get("min_spare_cells"),
             "obligations": dict(obligations),
             "reason": detail.get("reason"),
             "declaration": dict(block) if isinstance(block, dict) else None},
            None)


def eco_floor_row(eco: Mapping[str, Any]) -> Dict[str, Any]:
    """What the `spare_cell_density` row publishes about its own floor.

    Emitted whatever the declaration says, including when there is none: the
    absence of a bound is a fact a reader of a search space needs stated, not
    a blank they have to interpret.
    """
    state = str(eco.get("state") or ECO_NOT_SUPPLIED)
    floor = eco.get("min_spare_cells")
    bounds = state == feas.ECO_REQUIRED
    row: Dict[str, Any] = {
        "state": state,
        "declared_in": eco.get("declared_in"),
        "min_spare_cells": floor,
        "bounds_this_lever": bounds,
    }
    if bounds:
        row["refuses"] = (
            "any value this runner would apply as 0. Zero spare density "
            "inserts zero spares on a design of any size, so a candidate at "
            "zero cannot meet a declared floor of "
            f"{floor} and running it would spend a full place-and-route on a "
            "result the promotion gate must refuse.")
        row["not_enforced_here"] = (
            "a POSITIVE density. The declared floor is a COUNT of spare "
            "cells and this lever is a FRACTION of placed cells; converting "
            "one to the other needs the design's placed-cell count, which is "
            "a property of a run that has not happened. This program refuses "
            "only what it can prove from the knob alone.")
        row["enforced_downstream_by"] = (
            "_ppa/feasibility.py, axis `eco_readiness`, which compares the "
            "measured spare population against this same declaration")
    else:
        row["reason"] = eco.get("reason") or (
            "the declaration states no spare/ECO requirement, so this lever "
            "is free across its whole range")
    return row


# ---------------------------------------------------------------------------
# measuring the runner -- admission comes from its source, never from here
# ---------------------------------------------------------------------------
def cli_flags(source: str) -> Dict[str, int]:
    """Every `--flag` the runner's argparse declares, and the line it is on.

    Read from the SOURCE rather than by running `--help`, because running it
    would import forty thousand lines to answer a question about nine strings,
    and because a citation a reader can open is worth more than a captured
    stream.
    """
    out: Dict[str, int] = {}
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                    and a.value.startswith("--"):
                out.setdefault(a.value, node.lineno)
    return out


def read_runner(programs_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """(source, reason-it-could-not-be-read). Exactly one is None."""
    p = programs_dir / RUNNER_REL
    if not p.is_file():
        return None, (f"{p} does not exist, so nothing could say which "
                      "place-and-route knobs this flow exposes")
    try:
        src = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{p} could not be read: {exc}"
    try:
        ast.parse(src)
    except SyntaxError as exc:
        return None, f"{p} could not be parsed: {exc}"
    return src, None


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# asking the runner what it would do with a value
# ---------------------------------------------------------------------------
def _load_runner_module():
    """The runner as a module, or None with the reason it could not be loaded.

    Only needed to EXERCISE a normaliser. Admission never needs it, so a host
    where the import fails still gets a space -- with the value check reported
    as UNDETERMINED rather than skipped silently.
    """
    try:
        import importlib
        return importlib.import_module(RUNNER_REL[:-3]), None
    except Exception as exc:                            # pragma: no cover
        return None, f"{RUNNER_REL} could not be imported: {exc!r}"


def value_survives(mod: Any, normaliser: str, raw: str,
                   ) -> Tuple[bool, Any, Optional[str]]:
    """(unchanged?, what the runner would use, the runner's own warning).

    THE DEFECT THIS CATCHES. `--util 1.5` is not rejected by the runner; it is
    read as a percentage and becomes 0.015. A space that offered 0.3 and 1.5 as
    two points would produce two candidates whose knobs differ and whose RUNS
    are 0.3 and 0.015 -- and the manifest would publish the knob, not the
    value. So a value the runner would change is not a point in this space.
    """
    fn = getattr(mod, normaliser, None)
    if fn is None:
        return False, None, (f"{RUNNER_REL} declares no {normaliser}(), so "
                             "this value could not be checked")
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return False, None, f"{raw!r} is not a number"
    try:
        used, warn = fn(num)
    except Exception as exc:                            # pragma: no cover
        return False, None, f"{normaliser}({raw}) raised {exc!r}"
    return (used == num and not warn), used, warn


# ---------------------------------------------------------------------------
# building the space
# ---------------------------------------------------------------------------
def build_space(flags: Dict[str, int], runner_digest: str,
                explicit: Optional[Dict[str, List[str]]] = None,
                checked: Optional[Dict[str, Dict[str, Any]]] = None,
                eco: Optional[Mapping[str, Any]] = None,
                ) -> Dict[str, Any]:
    """One entry per lever, admitted or refused, and the flag that decided it."""
    explicit = dict(explicit or {})
    checked = dict(checked or {})
    eco = dict(eco or {"state": ECO_NOT_SUPPLIED})
    levers: List[Dict[str, Any]] = []
    for spec in LEVERS:
        name = str(spec["lever"])
        found = [f for f in spec["flags"] if f in flags]
        row: Dict[str, Any] = {
            "lever": name,
            "layer": spec["layer"],
            "kind": spec["kind"],
            "note": spec["note"],
            "flags_looked_for": list(spec["flags"]),
            "applies_via": found[0] if found else None,
            "citation": ({"path": RUNNER_REL, "line": flags[found[0]],
                          "literal": found[0]} if found else None),
        }
        if not found:
            row.update({
                "admitted": False, "status": STATUS_NOT_EXPOSED,
                "domain": spec["domain"],
                "justification": (
                    f"none of {list(spec['flags'])} is on "
                    f"{RUNNER_REL}'s command line, so this flow cannot apply "
                    "this lever. A space that admitted it would propose "
                    "candidates no run could distinguish."),
            })
            levers.append(row)
            continue
        row.update({
            "admitted": True, "status": STATUS_EXPOSED,
            "justification": (
                f"{found[0]} is declared at {RUNNER_REL}:{flags[found[0]]}, "
                "so a candidate that names a value for this lever is a run "
                "this flow can actually perform"),
        })
        if spec.get("eco_bounded"):
            floor_row = eco_floor_row(eco)
            row["eco_floor"] = floor_row
            if floor_row["bounds_this_lever"]:
                row["status"] = STATUS_BOUNDED_BELOW
                row["justification"] += (
                    "; and the design declares a spare/ECO population of at "
                    f"least {floor_row['min_spare_cells']}, so this lever is "
                    "admitted BOUNDED BELOW -- a zero value is not a point in "
                    "this space")
        if name in explicit:
            row["domain"] = " | ".join(explicit[name])
            row["values_source"] = "caller"
            row["values_checked_against_runner"] = checked.get(name, {})
        else:
            row["domain"] = spec["domain"]
            row["values_source"] = "not_enumerated"
            row["values_hint"] = (
                f"this program proposes no value for {name}: which values to "
                "try is a decision about a design and a machine budget, not a "
                "description of what may be searched. Supply them with "
                f"--values {name}=a,b,c here, or to ppa_search_run.py.")
        levers.append(row)

    admitted = [l for l in levers if l["admitted"]]
    return {
        "program": PROGRAM,
        "status": "MEASURED",
        "measured_against": {"path": RUNNER_REL, "sha256": runner_digest,
                             "cli_flags": sorted(flags)},
        "eco_declaration": dict(eco),
        "levers": levers,
        "admitted_count": len(admitted),
        "refused_count": len(levers) - len(admitted),
        "admitted_levers": [l["lever"] for l in admitted],
        "enumerated_levers": [l["lever"] for l in admitted
                              if l.get("values_source") == "caller"],
    }


def audit_space(space: Dict[str, Any]) -> List[str]:
    """Every way this space could be dishonest. Empty list = clean.

    The program's own output is made falsifiable here rather than trusted: an
    admitted lever with no flag citation is precisely the claim this file
    exists to stop being unbacked.
    """
    problems: List[str] = []
    levers = space.get("levers")
    if not isinstance(levers, list) or not levers:
        return ["the space carries no `levers` list — nothing to audit."]
    seen = set()
    for l in levers:
        name = l.get("lever", "<unnamed>")
        if name in seen:
            problems.append(f"{name}: named twice; one lever, one verdict.")
        seen.add(name)
        if not l.get("admitted"):
            if l.get("status") != STATUS_NOT_EXPOSED:
                problems.append(
                    f"{name}: refused with status {l.get('status')!r}; the "
                    f"only reason this program may refuse a lever is that no "
                    f"flag applies it.")
            if l.get("applies_via"):
                problems.append(
                    f"{name}: refused as not exposed while naming the flag "
                    f"{l['applies_via']!r} that applies it.")
            continue
        cite = l.get("citation")
        if not l.get("applies_via") or not isinstance(cite, dict):
            problems.append(
                f"{name}: admitted with no flag citation. A lever nobody can "
                f"point at in {RUNNER_REL} is a lever this flow cannot apply.")
            continue
        if not all(k in cite for k in ("path", "line", "literal")):
            problems.append(
                f"{name}: its citation is missing path/line/literal, so a "
                f"reader cannot go and check it.")
        if l.get("values_source") == "caller" and "|" not in str(
                l.get("domain", "")):
            problems.append(
                f"{name}: declares caller-supplied values but its domain is "
                f"not an enumerable list.")
        problems.extend(_audit_eco_floor(name, l))
    return problems


def _audit_eco_floor(name: str, lever: Mapping[str, Any]) -> List[str]:
    """Every way an ECO-bounded lever's row could be dishonest.

    Split out because it is the newest rule here and the one most likely to be
    quietly dropped: a lever that carries a floor and does not SAY so publishes
    a space in which zero looks like an ordinary point.
    """
    spec = {str(s["lever"]): s for s in LEVERS}.get(name)
    if not spec or not spec.get("eco_bounded"):
        return []
    floor = lever.get("eco_floor")
    if not isinstance(floor, dict):
        return [f"{name}: is bounded by the design-for-ECO declaration and "
                f"publishes no `eco_floor` block. A lever that carries a "
                f"floor and does not state it is a space in which the "
                f"forbidden value looks like an ordinary point."]
    problems: List[str] = []
    if "state" not in floor or "bounds_this_lever" not in floor:
        problems.append(
            f"{name}: its `eco_floor` names no state or no "
            f"`bounds_this_lever`, so a reader cannot tell an absent "
            f"declaration from one that requires nothing.")
    if floor.get("bounds_this_lever"):
        if lever.get("status") != STATUS_BOUNDED_BELOW:
            problems.append(
                f"{name}: its floor bounds the lever but its status is "
                f"{lever.get('status')!r}, not {STATUS_BOUNDED_BELOW!r}.")
        zeros = [v for v in str(lever.get("domain", "")).split("|")
                 if _is_zero_literal(v)]
        if zeros:
            problems.append(
                f"{name}: a declared spare/ECO floor bounds this lever and "
                f"its published domain still offers {zeros}. Zero spare "
                f"density inserts zero spares, which cannot meet any floor.")
    return problems


def _is_zero_literal(text: str) -> bool:
    """True when `text` is a number equal to zero. `'0.00'` and `'0'` are the
    same forbidden point and a string comparison would catch only one."""
    try:
        return float(str(text).strip()) == 0.0
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
def _parse_values(specs: Sequence[str]) -> Tuple[Dict[str, List[str]],
                                                 List[str]]:
    out: Dict[str, List[str]] = {}
    bad: List[str] = []
    for spec in specs:
        lever, sep, rhs = spec.partition("=")
        vals = [v.strip() for v in rhs.split(",") if v.strip()]
        if not sep or not lever.strip() or not vals:
            bad.append(spec)
            continue
        out[lever.strip()] = vals
    return out, bad


def _eco_value_refusals(explicit: Mapping[str, List[str]],
                        checked: Mapping[str, Dict[str, Any]],
                        eco: Mapping[str, Any]) -> List[str]:
    """Refuse every supplied value a declared spare/ECO floor forbids.

    Only zero is refusable from a knob alone -- see `eco_floor_row`'s
    `not_enforced_here`. That is a narrow rule and it is the whole rule: this
    program will not guess how many spares a positive density yields on a
    design it has never placed.
    """
    if str(eco.get("state")) != feas.ECO_REQUIRED:
        return []
    floor = eco.get("min_spare_cells")
    bounded = {str(s["lever"]) for s in LEVERS if s.get("eco_bounded")}
    out: List[str] = []
    for name in sorted(set(explicit) & bounded):
        rows = (checked.get(name) or {}).get("values") or []
        applied = {str(r.get("value")): r.get("applied_as") for r in rows}
        for raw in explicit[name]:
            used = applied.get(str(raw), raw)
            if not _is_zero_literal(used):
                continue
            out.append(
                f"{name}={raw}: the runner would apply {used!r}, and this "
                f"design declares a spare/ECO population of at least {floor} "
                f"in {eco.get('declared_in')}. Zero spare density inserts "
                "zero spares on a design of any size, so this point cannot "
                "meet the declared floor. Spare/ECO cells are what make a "
                "bug found after tape-out fixable by a metal-only ECO "
                "instead of a base-layer respin; deleting them is not a "
                "cheaper implementation of the same chip, and a search that "
                "visits this point spends a full place-and-route producing a "
                "candidate the promotion gate must refuse.")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ppa_pnr_search_space.py",
        description="Emit the place-and-route search space, measured against "
                    "the runner that would have to apply it.")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help=f"write the space here (default: ./{DEFAULT_JSON_REL})")
    ap.add_argument("--values", action="append", default=[],
                    metavar="LEVER=a,b,c",
                    help="values for one admitted lever; repeatable. Every "
                         "value is round-tripped through the runner's own "
                         "normaliser and a value the runner would change is "
                         "REFUSED, not searched.")
    ap.add_argument("--verify", default=None, metavar="SPACE",
                    help="audit an existing space against this tree's runner "
                         "instead of emitting one")
    ap.add_argument("--programs-dir", default=None,
                    help="where the runner lives (default: this file's "
                         "directory)")
    ap.add_argument("--eco-declaration", default=None, metavar="PATH",
                    help="a JSON document carrying the design's design-for-ECO "
                         "requirement (an `eco_readiness` block, or a document "
                         "that IS one). When it requires a spare population, "
                         "`spare_cell_density` is admitted BOUNDED BELOW and a "
                         "zero value is refused. Without it this program is "
                         "not told whether the design requires spares, and the "
                         "space says so rather than implying it does not.")
    # §1: argparse exits 2 on a usage error and 2 is UNDETERMINED here, so a
    # caller that skips on 2 swallows the typo. `parse_or_refuse` maps it to
    # 3 and keeps `--help` at 0. Pinned by
    # test_ppa_layer_exit_contract::test_unknown_flag_is_bad_invocation_not_undetermined.
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    programs = Path(args.programs_dir).resolve() if args.programs_dir \
        else Path(__file__).resolve().parent
    out_path = Path(args.json) if args.json else Path(DEFAULT_JSON_REL)

    explicit, bad = _parse_values(args.values)
    if bad:
        print(f"--values entries must be LEVER=a,b,c; malformed: {bad}",
              file=sys.stderr)
        return RC_BAD_INVOCATION
    if args.verify and (explicit or args.json):
        print("--verify audits a space that exists; it neither enumerates "
              "values nor writes one", file=sys.stderr)
        return RC_BAD_INVOCATION

    eco, eco_why = read_eco_declaration(args.eco_declaration)
    if eco_why is not None:
        print(f"{MARK_CANNOT_CHECK} [{PROGRAM}] {eco_why}", file=sys.stderr)
        print("  A design-for-ECO declaration was NAMED and could not be read. "
              "Publishing an unbounded space from it would let a search visit "
              "the value the requirement may have forbidden, so no space is "
              "published.", file=sys.stderr)
        return RC_UNDETERMINED

    src, why = read_runner(programs)
    if why is not None:
        print(f"{MARK_CANNOT_CHECK} [{PROGRAM}] {why}", file=sys.stderr)
        print("  Nothing was measured and no space is published. A space "
              "measured against a runner nobody looked at describes nothing.",
              file=sys.stderr)
        return RC_UNDETERMINED
    flags = cli_flags(src)
    if not flags:
        # The runner parsed and declared no option at all. That is far more
        # likely a parse this program got wrong than a runner with no CLI, and
        # publishing "every lever NOT_EXPOSED" from it would be a confident
        # wrong answer dressed as a measurement.
        print(f"{MARK_CANNOT_CHECK} [{PROGRAM}] {RUNNER_REL} parsed but "
              "declares no command-line option; this program cannot tell a "
              "runner with no CLI from a surface it failed to read, so it "
              "refuses to publish either.", file=sys.stderr)
        return RC_UNDETERMINED

    if args.verify:
        vp = Path(args.verify)
        if not vp.is_file():
            print(f"{MARK_CANNOT_CHECK} [{PROGRAM}] {vp} does not exist — an "
                  "audit that cannot read its subject is not a clean audit.",
                  file=sys.stderr)
            return RC_UNDETERMINED
        try:
            space = json.loads(vp.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            print(f"{MARK_CANNOT_CHECK} [{PROGRAM}] {vp} is unreadable: {exc}",
                  file=sys.stderr)
            return RC_UNDETERMINED
        problems = audit_space(space if isinstance(space, dict) else {})
        for l in (space.get("levers") or []) if isinstance(space, dict) else []:
            via = l.get("applies_via")
            if l.get("admitted") and via not in flags:
                problems.append(
                    f"{l.get('lever')}: admitted via {via!r}, which is not on "
                    f"{RUNNER_REL}'s command line on this tree.")
            if not l.get("admitted"):
                still = [f for f in (l.get("flags_looked_for") or [])
                         if f in flags]
                if still:
                    problems.append(
                        f"{l.get('lever')}: refused as not exposed, but "
                        f"{still} IS on {RUNNER_REL}'s command line on this "
                        f"tree.")
        for p in problems:
            print(f"{MARK_REFUSE} [{PROGRAM}] {p}", file=sys.stderr)
        print(f"[{PROGRAM}] audit: {len(problems)} problem(s)")
        return RC_REFUSED if problems else RC_PASS

    # --- value checking, and the honest degrade when the runner cannot load --
    checked: Dict[str, Dict[str, Any]] = {}
    refusals: List[str] = []
    by_name = {str(s["lever"]): s for s in LEVERS}
    if explicit:
        unknown = [n for n in explicit if n not in by_name]
        not_exposed = [n for n in explicit if n in by_name
                       and not any(f in flags for f in by_name[n]["flags"])]
        if unknown or not_exposed:
            for n in unknown:
                print(f"{MARK_REFUSE} [{PROGRAM}] {n!r} is not a lever this "
                      f"program knows; known: {sorted(by_name)}",
                      file=sys.stderr)
            for n in not_exposed:
                print(f"{MARK_REFUSE} [{PROGRAM}] values were supplied for "
                      f"{n!r}, which {RUNNER_REL} exposes no flag for. A "
                      "space may not admit a lever because a caller asked for "
                      "it.", file=sys.stderr)
            return RC_REFUSED
        mod, load_why = _load_runner_module()
        for name, vals in sorted(explicit.items()):
            norm = by_name[name]["normaliser"]
            if norm is None:
                checked[name] = {
                    "checked": False,
                    "reason": (f"{by_name[name]['flags'][0]} takes no "
                               "normalised scalar, so there is no runner "
                               "guard to round-trip these values through")}
                continue
            if mod is None:
                print(f"{MARK_CANNOT_CHECK} [{PROGRAM}] {load_why}",
                      file=sys.stderr)
                print(f"  Values were supplied for {name!r} and could not be "
                      "checked against the runner. Publishing them unchecked "
                      "would put points in a space that the flow may collapse "
                      "onto each other.", file=sys.stderr)
                return RC_UNDETERMINED
            rows = []
            for raw in vals:
                ok, used, warn = value_survives(mod, norm, raw)
                rows.append({"value": raw, "applied_as": used,
                             "unchanged": ok, "runner_warning": warn})
                if not ok:
                    refusals.append(
                        f"{name}={raw}: {RUNNER_REL}.{norm}() would apply "
                        f"{used!r}, not {raw!r}"
                        + (f" — {warn}" if warn else "")
                        + ". A candidate naming a value the runner does not "
                          "use is a candidate whose knobs do not describe its "
                          "run.")
            checked[name] = {"checked": True, "normaliser": norm,
                             "values": rows}
        # The floor, applied to the values the CALLER supplied. It runs after
        # the normaliser round-trip so the judgement is on what the runner
        # would APPLY, not on how the caller spelled it: `--values
        # spare_cell_density=-1` is applied as 0 by the runner's own clamp,
        # and a check on the literal would have let it through.
        refusals.extend(_eco_value_refusals(explicit, checked, eco))

        dupes = {n: v for n, v in explicit.items() if len(set(v)) != len(v)}
        for n, v in sorted(dupes.items()):
            refusals.append(
                f"{n}: the value list repeats a value ({v}); a search that "
                "proposes the same point twice reports a trial count that is "
                "not a count of distinct configurations.")
        if refusals:
            for r in refusals:
                print(f"{MARK_REFUSE} [{PROGRAM}] {r}", file=sys.stderr)
            return RC_REFUSED

    space = build_space(flags, _sha256(src), explicit, checked, eco)
    problems = audit_space(space)
    space["self_audit_problems"] = problems
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Through the atomic writer (vibe-ic#1082): a reader that opens this space
    # while it is being rewritten must see the old document or the new one,
    # never half of one -- and a half-written space is a lever list with no
    # citations, which is the shape this program exists to refuse.
    atomic_write_json(out_path, space, indent=2)

    print(f"[{PROGRAM}] admitted {space['admitted_count']} lever(s): "
          f"{', '.join(space['admitted_levers']) or '(none)'}")
    print(f"[{PROGRAM}] design-for-ECO declaration: {eco.get('state')}"
          + (f" (min_spare_cells={eco.get('min_spare_cells')}, from "
             f"{eco.get('declared_in')})"
             if str(eco.get("state")) == feas.ECO_REQUIRED else ""))
    for l in space["levers"]:
        if not l["admitted"]:
            print(f"[{PROGRAM}]   REFUSED {l['lever']}: {l['status']} — "
                  f"none of {l['flags_looked_for']}")
        elif l.get("values_source") == "caller":
            print(f"[{PROGRAM}]   {l['lever']} via {l['applies_via']}: "
                  f"{l['domain']}")
        else:
            print(f"[{PROGRAM}]   {l['lever']} via {l['applies_via']}: "
                  "no values enumerated (supply --values to search it)")
    print(f"[{PROGRAM}] space: {out_path}")
    if problems:
        for pr in problems:
            print(f"{MARK_REFUSE} [{PROGRAM}] SELF-AUDIT FAILED: {pr}",
                  file=sys.stderr)
        return RC_REFUSED
    return RC_PASS


if __name__ == "__main__":                              # pragma: no cover
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:                            # pragma: no cover
        # §1: 3 is INTERNAL ERROR. Letting this propagate exits 1, which is
        # reserved for a finding about a design, and nothing about a crash in
        # this program is a fact about one.
        print(f"{cli_exit.MARK_REFUSE} {PROGRAM}: internal error "
              f"{type(exc).__name__}: {exc}. Nothing was measured and no "
              f"space was published. rc=3 (NOT a finding about any design).",
              file=sys.stderr)
        raise SystemExit(cli_exit.RC_BAD_INVOCATION)
