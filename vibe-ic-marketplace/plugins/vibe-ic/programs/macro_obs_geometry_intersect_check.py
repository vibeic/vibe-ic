#!/usr/bin/env python3
"""Emitted metal that crosses a placed macro's declared obstruction. vibe-ic#686.

THIS GATE BLOCKS (rc=1) — a statement about this program's VERDICT SEVERITY,
not about where its verdict is consumed. Those are two different axes, and the
second one is declared immediately below: a gate that says nothing about it is
the defect `flow_gate_enforcement_audit` exists to catch, and silence there is
not a decision.

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 21 while step 21 is running. What it DOES have, and this is why `advisory`
here is not "ignorable": it is a gate leg of step 21 in the flow's BLOCKING
slot (`program_exit_zero`, never `advisory_program_exit_zero`), so when
`flow_compliance_check` evaluates that clause an rc=1 FAILs the step, and that
verdict reaches the run's headline through
`reports/audit/phase23_completion_audit.json`, which
`phase3_one_shot_runner._derive_headline_verdict` reads. MEASURED on a copy of
a published run-root: the evaluator's own step report lists this program under
step 21's `measures`. What `flow_gate_enforcement_audit` scores is the narrower
question "can this verdict stop the step it guards", and the answer there is
no; `advisory` is that audit's token for that answer.

WHY IT IS NOT PROMOTED TO INLINE-BLOCKING, MEASURED. The one inline pattern the
phase-3 runner has — `_DECLARED_SIGNOFF_GATES` / `_run_declared_signoff_gate` —
routes every rc other than 0 and 1 to BLOCKED (non-green), deliberately, because
for a sign-off gate "could not check" is not a pass. This gate's rc=2 means
something different: no DEF, no macro LEF, no placed macro, or no OBS in any of
them, i.e. there was legitimately no obstruction to cross. Over the 15 published
phase-3 run-roots under `benchmark-data/ic`, invoked exactly as a caller would:
rc 2 on all 15, rc 0 and rc 1 on none. Wiring it into that table would therefore
turn every one of those published runs non-green for owning no macro
obstruction, which is the false alarm this gate's own rc-2 branch was written to
avoid. The flow's rc=2 -> VACUOUS_PASS encoding is the correct consumer; that
table is not. Promotion needs an inline consumer that PRESERVES
rc=2 -> VACUOUS_PASS at the step that owns the subject — a flow-owner change
with its own blast radius, not a side effect of recording this decision.

WHY IT EXISTS
-------------
A hard macro's `OBS` rectangle is the macro vendor's statement of where the
integrator may not put metal. The flow reads that LEF, uses its `PIN` section,
and discards its `OBS`. Follow-pins, core straps and the macro grid are all
emitted without consulting it, and NOTHING anywhere intersects emitted geometry
with a placed macro's obstructions.

MEASURED on a routed DEF from a run the flow called clean but for one unrelated
integration gap: **28 of 292 MET1 FOLLOWPIN segments run straight through a
placed macro's full-footprint MET1 obstruction** — an obstruction declared in
the very LEF the run loaded.

THE FAILURE IS SILENT BY CONSTRUCTION, which is the part worth naming. Every
existing check is either

  * a COUNT OF ATTACHMENTS — `PG_NET_OWNERSHIP_AUDIT: total=3337 no_net=1` tests
    `[$_pg_t getNet] eq "NULL"`, i.e. whether a terminal has a net. A wire that
    crosses a blockage is attached to exactly the right net. (Spelled
    `PG_CONNECT_AUDIT: unconnected=N` through v1.9.62, until vibe-ic#699 renamed
    it to what it measures.)
  * a GEOMETRIC DRC AGAINST THE PDK DECK — `drc_signoff.json: passed: true,
    real_violation_total: 0`, `detailed route: violation report: 0`. A macro
    obstruction is not in the PDK deck; it is in the macro's LEF.

A macro obstruction is neither, so it was invisible to all of them at once.

WHAT IT MEASURES
----------------
For every macro instance PLACED in the DEF, transform the macro's `OBS` rects to
placed coordinates and intersect them with the routed metal on the same layer.
A segment counts as a violation when it SPANS the obstruction — enters one side
and leaves the other — not when it merely touches near an edge, because a
fragment at the boundary is ordinary and flagging it would bury the real finding
in noise.

Orientation is honoured: `N/S/FN/FS` keep the macro's own axes, `E/W/FE/FW`
swap them. A checker that ignored orientation would measure a rotated macro
against an unrotated obstruction and report crossings that are not there — a
fabricated finding is worse than none.

chip-AGNOSTIC and PDK-AGNOSTIC: pure LEF/DEF grammar. No design, PDK, vendor or
layer-name literal appears in the logic.

USAGE
-----
    macro_obs_geometry_intersect_check.py <project_dir> [--json OUT]
                                          [--def PATH] [--macro-lef PATH ...]

    exit 0 = no emitted metal spans a declared obstruction, AND every placed
             master resolved to a LEF
    exit 1 = at least one does (BLOCKING)
    exit 2 = could not be determined — no DEF, no macro LEF, no placed macro,
             no OBS in any of them, an INCOMPLETE LEF set (a master is
             PLACED and no LEF read declares it, so its OBS — if it has one —
             was never in the comparison), or DISCARDED OBS EVIDENCE (see
             below). NEVER a vacuous pass: this gate has been wrong about
             nothing before, and "found no crossings" must not be the same
             sentence as "had nothing to look at".

THE COMPLETENESS CLAIM NAMES THE PROPERTY THE VERDICT CONSUMES
---------------------------------------------------------------
MEASURED on a blocking run, and every clause of it is TRUE:

    [PASS] macro_obs_geometry_intersect: 1698 placed instance(s) of 325
           master(s) with OBS, 489 supply segment(s), 0 path(s) abandoned —
           none spans an obstruction. All 79 placed master(s) resolved to a LEF.

28 supply segments spanning a declared obstruction went unreported underneath
that sentence. The master DID resolve to a LEF. The file it resolved to did not
carry the obstruction — and **"resolved to a LEF" is not "its obstructions were
read"**. The published completeness line was computed from a PRECONDITION
(membership in `obs_by_master`, i.e. some file names this master) while the
verdict consumes a STRICTLY STRONGER property (that master's OBS rects reached
`with_obs` and were intersected). A claim derived from a proxy for the thing
the verdict depends on answers an adjacent question, and reads as the real one.

TWO CHANGES, AND THE SECOND IS THE NARROW ONE:

1. The PASS line publishes the CONSUMED count SEPARATELY from the precondition
   count — how many placed masters actually supplied obstruction geometry, and
   how many resolved to a LEF that declares none. Both numbers, side by side,
   so the reader sees the gap instead of inferring its absence. This changes no
   verdict; a partial denominator is legitimate, and many placed masters
   genuinely have no obstruction. What is not legitimate is publishing the
   larger number and letting it read as the smaller one.

2. DISCARDED OBS EVIDENCE is rc=2. `audit` merges LEFs in read order and the
   last declaration of a master wins. When a placed master is declared by more
   than one file that was read, and the WINNING declaration omits obstruction
   rects that ANOTHER read declaration carries, the verdict was decided by glob
   order over contradictory inputs — an OBS-less abstract silently revoking a
   declared obstruction is exactly the measured failure. The gate does NOT
   promote the richer declaration: an obsolete LEF left in the tree would then
   FABRICATE a crossing on a gate that blocks, and a fabricated finding is
   worse than a missed one. It refuses to certify and names both files.

   NARROW BY CONSTRUCTION — the condition is `winner_rects != union_rects` for
   a PLACED master, so it is silent on: a master declared once; the same file
   staged twice (identical rects, union equals winner); a master whose winning
   declaration is the RICHEST one (union equals winner); and any master that is
   never placed. It fires only where the input set contained obstruction
   evidence that this verdict did not consume.

DISCOVERY (#828). With no `--macro-lef`, every `*.lef` under the project that
DECLARES A MACRO is read. The previous default was `input/pdk/**/*.lef` +
`phase3/**/macro*.lef`; an IP LEF legitimately lives outside `input/pdk/`, and
a staged macro LEF need not be named `macro*`, so discovery decided the verdict
at least as much as the geometry did. A file's content answers "does this
define a MACRO" directly; its path and name only guess at it.

WHERE IT RUNS (#828 part 2, closed). This file used to say: "It is not
registered in `flow/phase1_phase2_phase3.yaml` and no runner invokes it; its
only caller is `tools/ci/repo_hygiene_gates.sh`." A gate whose verdict is
blocking and that no flow step runs enforces nothing on a real design — it
reproduced this defect in seconds on a routed DEF and was never asked to.

It is now a gate leg of STEP 21 (Routing), the step that PRODUCES routed.def,
so the metal it examines exists by the time it is asked. The clause is
UNCONDITIONAL — the sentence here previously said it was conditioned on staging
a LEF, and the flow definition says the opposite in the comment above the clause
itself: a `**/*.lef` trigger is what `flow_condition_reachability_check` calls
SELF-DISABLING, so the gate is asked on every run and answers for itself. Every
refusal it makes (no LEF at all, an incomplete LEF set, discarded OBS evidence,
a truncated read) reaches the flow as rc=2 -> VACUOUS_PASS and is disclosed
rather than passed. The CI caller in `tools/ci/repo_hygiene_gates.sh` is
unchanged and still sweeps the tracked cells.

SEE ALSO `macro_obs_load_parity_check`, which asks the prior question this gate
cannot: whether the obstructions this file PARSES are the obstructions the tool
LOADED. This gate reads the LEF with the plugin's own parser, so on a design
whose OBS section the reader discarded it measures geometry the run never had.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import _routed_checker_progress as _routed_progress
import _semantic_child_progress as _semantic_progress
import _flow_reason_taxonomy as _reason_taxonomy  # noqa: E402  vibe-ic#1978


PROGRESS_SCOPE = "routed-def:macro-obs-geometry-intersect"
_ACTIVE_INPUT_PLAN: Optional[_routed_progress.FiniteInputPlan] = None

#: Where the FLOW says a design declares that it integrates a macro. These are
#: the `condition_files_exist` triggers of step 15's `ip_integration_check`
#: clause in `flow/phase1_phase2_phase3.yaml`, whose `absent_condition_reason`
#: states the doctrine this module borrows: "Both triggers are DECLARATIONS --
#: a user-supplied local PDK tree and the analog hardmacro handoff -- and a
#: design that integrates no macro has no macro LEF/GDS/Liberty file set."
#:
#: WHY A GATE THAT READS LEFs NEEDS THIS (vibe-ic#2013, #1978). Both
#: obstruction gates refuse with rc=2 when they find no macro abstract to read.
#: Since #1978 a refusal carries a typed `reason_class`, and the class decides
#: the tier: a design-declared N/A stays a disclosed skip (VACUOUS_PASS), an
#: absent upstream artefact is BLOCKED. "No macro LEF under the project" is
#: BOTH of those, depending on a fact the LEF set cannot supply — whether the
#: design integrates a macro at all. The flow's own declaration sites supply
#: it: no site present, no macro declared, so no abstract is owed and the
#: refusal is the design's N/A; a site present and still no readable abstract
#: is a declared macro whose LEF never reached this gate, which is BLOCKED and
#: must not be laundered into an N/A. Before this, the untyped refusal fell
#: closed to EXECUTION_ERROR, and a real published run read
#: "INCOMPLETE: the gate reports its input was applicable and was NOT examined"
#: on step 21 for a design that integrates no macro. MEASURED, spm@1.15.55.
#:
#: Kept as a tuple of flow-layout paths, not design/PDK/vendor literals. The
#: test `test_macro_obs_gates_type_their_refusals` pins it to the yaml so the
#: two copies cannot drift apart silently.
_MACRO_DECLARATION_SITES: Tuple[str, ...] = (
    "input/pdk_local", "phase3/analog/hardmacro")


def macro_declaration_sites(project: Path) -> List[str]:
    """The flow's macro-declaration sites that EXIST under *project*."""
    return [rel for rel in _MACRO_DECLARATION_SITES
            if (Path(project) / rel).exists()]


def _typed_refusal(json_out: Optional[Path], check: str, reason_class: str,
                   reason: str, rep: Optional[Dict[str, Any]] = None) -> int:
    """rc=2, with the reason TYPED where the consumer reads it (#1978).

    The `[CANNOT DETERMINE]` line the caller already printed is the human
    disclosure and is left exactly as it was. What was missing is the
    machine-readable half: `flow_compliance_check` classifies every rc=2 by
    `reason_class`, reading the JSON report the clause names FIRST and falling
    closed to EXECUTION_ERROR when nothing typed is there. Every refusal in
    this module was falling closed, so a design that integrates no macro
    graded the same as a gate that crashed. The record written here carries
    the audit's own counts when the refusal came after one (`rep`), so a
    reader can see WHAT was examined before the question was declined.

    The verdict word is the taxonomy's own `record_verdict` for the class
    (SKIP / BLOCKED / INCOMPLETE), so this module invents no vocabulary the
    consumer has to learn.
    """
    payload: Dict[str, Any] = dict(rep or {})
    payload.update({
        "check": check,
        "verdict": _reason_taxonomy.record_verdict(reason_class),
        "rc": 2,
        "reason_class": reason_class,
        "reason": reason,
    })
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"  reason_class={reason_class} -> "
          f"{payload['verdict']}", file=sys.stderr)
    return 2


def _read_input_text(path: Path) -> str:
    if _ACTIVE_INPUT_PLAN is not None:
        return _ACTIVE_INPUT_PLAN.text_for(path, errors="replace")
    return Path(path).read_text(errors="replace")


def _is_default_routed_def(relative: str) -> bool:
    path = Path(relative)
    return (path.parent.as_posix() == "phase3/stage3/pnr"
            and path.name.startswith("routed")
            and path.suffix == ".def")


def _default_macro_lef_population(project: Path) -> List[Path]:
    """Historical triple-glob order before content-based LEF filtering."""
    ordered: List[Path] = []
    seen = set()
    for pattern in (
            "input/pdk/**/*.lef", "phase3/**/macro*.lef", "**/*.lef"):
        for path in sorted(Path(project).glob(pattern)):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            ordered.append(path)
    return ordered


def _input_plan(project: Path) -> _routed_progress.FiniteInputPlan:
    project = Path(project)
    index = _routed_progress.IndexSnapshot(project)
    routed = index.select(
        _is_default_routed_def,
        sorted(project.glob("phase3/stage3/pnr/routed*.def")),
        population="macro OBS routed DEF population")
    lefs = index.select(
        lambda relative: relative.endswith(".lef"),
        _default_macro_lef_population(project),
        population="macro OBS LEF population")
    reads = [
        *_routed_progress.planned_reads("routed-def", routed),
        *_routed_progress.planned_reads("macro-lef", lefs),
    ]
    return _routed_progress.FiniteInputPlan(
        [index.population_unit("macro-obs:git-index")], reads)


def semantic_progress_units(cell: Path) -> List[str]:
    """Trusted parent's exact finite manifest for the default cell argv."""
    return _input_plan(Path(cell)).units

_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\s*$", re.S | re.M)
_SIZE_RE = re.compile(r"^\s*SIZE\s+([\d.-]+)\s+BY\s+([\d.-]+)\s*;", re.M)
_OBS_RE = re.compile(r"^\s*OBS\s*$(.*?)(?=^\s*(?:PIN|END)\b)", re.S | re.M)
_LAYER_RE = re.compile(r"\s*LAYER\s+(\S+)\s*;")
_RECT_RE = re.compile(r"\s*RECT\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s*;")
_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", re.M)
_COMP_RE = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+)[^;]*?\+\s*(?:FIXED|PLACED|COVER)\s*\(\s*"
    r"(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)", re.M)
_COMPONENTS_SEC_RE = re.compile(
    r"^\s*COMPONENTS\b(.*?)^\s*END\s+COMPONENTS", re.S | re.M)


def parse_macro_obs(lef_text: str) -> Dict[str, Dict[str, Any]]:
    """{master: {"size": (w,h) um, "obs": [(layer, x1,y1,x2,y2) um]}}.

    `LAYER OVERLAP` is a LEF keyword declaring the macro's own extent, not a
    metal layer, and is excluded — treating it as one would make every macro
    block every layer."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(lef_text, str):
        return out
    for mm in _MACRO_RE.finditer(lef_text):
        master, body = mm.group(1), mm.group(2)
        sm = _SIZE_RE.search(body)
        rects: List[Tuple[str, float, float, float, float]] = []
        om = _OBS_RE.search(body)
        if om:
            layer = None
            for line in om.group(1).splitlines():
                lm = _LAYER_RE.match(line)
                if lm:
                    layer = lm.group(1)
                    continue
                rm = _RECT_RE.match(line)
                if rm and layer and layer.upper() != "OVERLAP":
                    x1, y1, x2, y2 = (float(v) for v in rm.groups())
                    rects.append((layer, min(x1, x2), min(y1, y2),
                                  max(x1, x2), max(y1, y2)))
        out[master] = {
            "size": ((float(sm.group(1)), float(sm.group(2))) if sm else None),
            "obs": rects,
        }
    return out


def place_rect(rect: Tuple[float, float, float, float],
               size: Tuple[float, float], ox: float, oy: float,
               orient: str) -> Tuple[float, float, float, float]:
    """A macro-local rect in PLACED coordinates.

    Orientation is honoured because ignoring it measures a rotated macro against
    an unrotated obstruction — a fabricated finding, which is worse than none.
    Only the axis mapping matters here: a bounding box is symmetric under the
    mirror flips, so N/FN/S/FS all keep the macro's axes and E/FE/W/FW swap
    them."""
    x1, y1, x2, y2 = rect
    w, h = size
    o = (orient or "N").upper()
    if o in ("N", "FN", "S", "FS"):
        return (ox + x1, oy + y1, ox + x2, oy + y2)
    if o in ("E", "FE", "W", "FW"):
        # 90-degree rotation: the macro occupies h x w in placed space.
        return (ox + y1, oy + x1, ox + y2, oy + x2)
    return (ox + x1, oy + y1, ox + x2, oy + y2)


def parse_placed_macros(def_text: str,
                        masters: Sequence[str]) -> List[Dict[str, Any]]:
    """Every COMPONENT whose master is one of `masters`, with its placement."""
    want = set(masters)
    out = []
    for m in _COMP_RE.finditer(def_text):
        inst, master, x, y, orient = m.groups()
        if master in want:
            out.append({"inst": inst, "master": master,
                        "x": int(x), "y": int(y), "orient": orient})
    return out


def parse_placed_masters(def_text: str) -> Set[str]:
    """Every distinct master PLACED in this DEF, whether or not any LEF was
    read for it.

    `parse_placed_macros` answers "which instances of the masters I already
    know about are placed". This answers the prior question — "what did the
    DEF actually place" — which is what makes "I found no LEF for that
    master" expressible at all.

    Scoped to the COMPONENTS section, and the scoping is load-bearing.
    `_COMP_RE` has `[^;]*?` between the master token and the placement, and
    a negated character class matches newlines, so run over a whole routed
    DEF it also reaches into the PINS section. A pin with a placed port —

        - clk + NET clk + DIRECTION INPUT + USE SIGNAL
          + PORT
            + LAYER Metal2 ( -100 -360 ) ( 100 360 )
            + PLACED ( 109920 360 ) N ;

    matches with inst=`clk` and MASTER=`+`. Measured on the three tracked
    DEFs, the whole-file scan over-counts by exactly 36 on each — one per
    pin — and mints that single phantom master:

        spm/v1.5.58_ihp-sg13g2  COMPONENTS 1826 ; -> whole 1862 / section 1826
        spm/v1.5.65_sky130A     COMPONENTS  558 ; -> whole  594 / section  558
        spm/v1.5.66_gf180mcuD   COMPONENTS 2007 ; -> whole 2043 / section 2007

    Section-scoped, the match count equals the declared count exactly on all
    three and the `+` artifact disappears. A phantom master would otherwise
    be permanently unresolvable and would make this gate cry wolf on every
    design. If the DEF has no delimited COMPONENTS section the whole text is
    scanned, which is the pre-existing behaviour and no worse than it.

    chip-AGNOSTIC: pure DEF grammar."""
    if not isinstance(def_text, str):
        return set()
    sm = _COMPONENTS_SEC_RE.search(def_text)
    body = sm.group(1) if sm else def_text
    out: Set[str] = set()
    for m in _COMP_RE.finditer(body):
        out.add(m.group(2))
    return out


# A wiring path inside a SPECIALNETS entry. DEF introduces the FIRST path of a
# net with `+ ROUTED` (or FIXED / COVER) and every SUBSEQUENT path of that same
# net with the bare keyword `NEW` — no `+`. Anchoring on `+` therefore sees one
# path per net and silently discards the rest.
_PATH_HEAD_RE = re.compile(
    r"(?:\+\s*(?:ROUTED|FIXED|COVER|SHAPE\s+\w+)?\s*|\bNEW\s+)(\w+)\s+\d+",
    re.I)

# `( x y )`, with an optional third value (the wire extension). Either
# coordinate may be `*`, which DEF defines as "repeat the one before it".
_PATH_POINT_RE = re.compile(r"\(\s*(-?\d+|\*)\s+(-?\d+|\*)(?:\s+-?\d+)?\s*\)")

# `+ SHAPE <token>` — a per-PATH declaration, which is the whole point of
# reading it here rather than over the net entry. See
# `parse_routed_segments_with_gaps`.
_SHAPE_RE = re.compile(r"\+\s*SHAPE\s+(\w+)", re.I)


# A via placed INSIDE a wiring path: a bare identifier sitting between two
# coordinate groups. LEF/DEF 5.8: "If you specify a via, layerName for the next
# routing coordinates (if any) is implicitly changed to the other routing layer
# for the via." So the head layer governs only up to the first via.
_PATH_TOKEN_RE = re.compile(
    r"\(\s*(-?\d+|\*)\s+(-?\d+|\*)(?:\s+-?\d+)?\s*\)"      # a point
    r"|([A-Za-z_][A-Za-z0-9_]*)")                          # or a bare name

# `- <viaName> ... + LAYERS <lower> <cut> <upper> ...` in the DEF's own VIAS
# section. That is where a via's two routing layers are stated.
_VIAS_SEC_RE = re.compile(r"^\s*VIAS\s+\d+\s*;(.*?)^\s*END\s+VIAS",
                          re.S | re.M)
_VIA_LAYERS_RE = re.compile(r"\+\s*LAYERS\s+(\S+)\s+(\S+)\s+(\S+)", re.I)

# DEF's own vocabulary, which occupies the same syntactic slot as a via name
# inside a wiring path. Not vias.
_PATH_KEYWORDS = {
    "NEW", "ROUTED", "FIXED", "COVER", "SHAPE", "USE", "STYLE", "MASK",
    "RECT", "VIRTUAL", "NONDEFAULTRULE", "TAPER", "TAPERRULE",
    "FOLLOWPIN", "STRIPE", "IOWIRE", "COREWIRE", "BLOCKWIRE", "BLOCKAGEWIRE",
    "FILLWIRE", "FILLWIREOPC", "DRCFILL", "RING", "PADRING", "BLOCKRING",
    "POWER", "GROUND", "SIGNAL", "CLOCK", "TIEOFF", "ANALOG", "RESET", "SCAN",
}


def parse_via_layers(def_text: str) -> Dict[str, Tuple[str, str]]:
    """{viaName: (lowerRoutingLayer, upperRoutingLayer)} from the VIAS section.

    Only vias DEFINED IN THIS DEF are resolvable here. A via that comes from the
    tech LEF is not, and the caller must treat it as unknown rather than guess —
    see `_path_segments`."""
    out: Dict[str, Tuple[str, str]] = {}
    sec = _VIAS_SEC_RE.search(def_text)
    if not sec:
        return out
    for entry in re.split(r"\n\s*-\s+", sec.group(1)):
        nm = re.match(r"\s*(\S+)", entry)
        lm = _VIA_LAYERS_RE.search(entry)
        if nm and lm:
            out[nm.group(1)] = (lm.group(1), lm.group(3))
    return out


def _path_segments(body: str, head_layer: str,
                   via_layers: Dict[str, Tuple[str, str]]
                   ) -> Tuple[List[Tuple[str, int, int, int, int]],
                              Optional[Dict[str, Any]]]:
    """`([(layer, x1, y1, x2, y2)], abandonment_or_None)` for ONE wiring path.

    Two things the head layer alone cannot tell you:

    * `*` is not a missing coordinate — DEF defines it as the PREVIOUS point's
      coordinate, and it is how every real writer spells an orthogonal segment.
      Dropping those points drops the segments they describe.
    * a via inside the path switches the layer for everything after it. Stamping
      the whole path with the head layer puts upper-layer metal on the lower
      layer, which on a BLOCKING gate does not merely miss a violation — it
      FABRICATES one, against an obstruction the metal never went near.

    When a via cannot be resolved (it is defined in the tech LEF, which this gate
    does not read), the layer after it is UNKNOWN. This stops emitting rather
    than continuing under the previous layer: an unreported segment is a gap, an
    unreported segment attributed to the wrong layer is a false accusation, and
    on a gate that blocks the second is strictly worse.

    The SECOND return value is what makes that choice survivable. Stopping is
    only better than guessing if the stop is VISIBLE: a truncated path that
    reports nothing is indistinguishable from a path with nothing to report, and
    a partial denominator published as a clean verdict is the same defect this
    gate exists to catch, one scale down. So the abandonment is returned —
    `{via, layer_at_stop, points_read, points_unread}` — and every caller up to
    the exit code carries it.

    An abandonment is recorded only when coordinate points REMAIN. A path whose
    unresolvable via is its last token left nothing unexamined, so reporting it
    as abandoned reports a gap that does not exist — and because any gap forces
    rc=2, one via-only entry withheld a verdict on the whole design. See the
    comment at the via branch."""
    segs: List[Tuple[str, int, int, int, int]] = []
    layer = head_layer
    px: Optional[int] = None
    py: Optional[int] = None
    read = 0

    def _stop(via: str, why: str, unread: int
              ) -> Tuple[List[Any], Dict[str, Any]]:
        return segs, {"via": via, "reason": why, "layer_at_stop": layer,
                      "head_layer": head_layer, "points_read": read,
                      "points_unread": unread}

    for tm in _PATH_TOKEN_RE.finditer(body):
        a, b, name = tm.group(1), tm.group(2), tm.group(3)
        if name is not None:
            # A via is an identifier sitting BETWEEN coordinates. The same
            # position also carries DEF's own keywords (`+ SHAPE FOLLOWPIN`
            # before the first point, `+ USE POWER ;` after the last), so a
            # bare-identifier rule alone reads `SHAPE` as an unresolvable via
            # and abandons the whole path. Require both: we are mid-path, and
            # the token is not vocabulary.
            if px is None or name.upper() in _PATH_KEYWORDS:
                continue
            # AN UNRESOLVABLE VIA COSTS NOTHING WHEN THE PATH ENDS AT IT.
            # A via-only entry — `NEW <layer> 0 ( x y ) <viaName>` — is how DEF
            # spells a bare via drop in a special net, and it is ordinary: a
            # PDN's layer-to-layer stack is written that way. The via is the
            # LAST token of its path, so there is no metal after it whose layer
            # could be unknown, and a via is a point, which cannot SPAN an
            # obstruction under any reading. Treating it as an abandoned path
            # made this gate return rc=2 CANNOT DETERMINE for every design that
            # contains one, i.e. for essentially every real PDN — a refusal
            # earned by nothing that was actually left unexamined.
            #
            # The condition is COUNTED, not assumed: the remaining coordinate
            # points are re-scanned from the via's own position. Where metal
            # really does follow an unresolvable via the gap is recorded
            # exactly as before, because that metal's layer really is unknown
            # and this gate does not guess a layer on a verdict that blocks.
            # Counting from the position (rather than `total - read`) also
            # avoids the pre-existing off-by-one from a leading `*` point,
            # which `read` never counts but `total` does.
            unread = len(_PATH_POINT_RE.findall(body[tm.end():]))
            pair = via_layers.get(name)
            if pair is None:
                if not unread:
                    break
                return _stop(name, "via not defined in this DEF's VIAS section",
                             unread)
            lo, hi = pair
            # the via connects two routing layers; move to whichever is not the
            # one we are on. If neither matches, the path is not describable.
            if layer.lower() == lo.lower():
                layer = hi
            elif layer.lower() == hi.lower():
                layer = lo
            else:
                if not unread:
                    break
                return _stop(name, f"via connects {lo}/{hi}, path is on {layer}",
                             unread)
            continue
        x = px if a == "*" else int(a)
        y = py if b == "*" else int(b)
        if x is None or y is None:
            continue      # a `*` in a path's first point has nothing to repeat
        if px is not None and py is not None:
            segs.append((layer, px, py, x, y))
        px, py = x, y
        read += 1
    return segs, None


def parse_routed_segments_with_gaps(
        def_text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """`(segments, abandoned_paths)` — the segments AND what was not read.

    SPECIALNETS only: this gate is about supply metal crossing an obstruction,
    which is what follow-pins and straps are. A signal route over a blockage is
    the router's business and the PDK deck's.

    A path is a POLYLINE: N points describe N-1 segments, and every one of them
    is metal that can cross an obstruction. Reading only the first pair reports
    on the first leg of each path and stays silent about the others.

    `abandoned_paths` is the honest denominator. A path this parser could not
    follow to its end is metal it did not look at, and the caller must be able
    to tell that from metal it looked at and cleared.

    SHAPE IS A PROPERTY OF THE PATH, NOT OF THE NET. DEF states it per path
    (`+ ROUTED <layer> <w> + SHAPE FOLLOWPIN`), and one supply net carries many
    paths of different shapes — that is what a power grid IS: follow-pins on the
    lowest layer and STRIPEs above them, all on the same net. Deriving the flag
    from `"FOLLOWPIN" in entry`, i.e. from a substring of the WHOLE net entry,
    labels every strap of a net that has any follow-pin anywhere as a follow-pin
    itself. The label then names the wrong kind of metal on a gate whose finding
    a person has to act on, and it cannot be off in the other direction, so it
    reads as corroboration: every finding agreeing on the shape looks like a
    coherent story about the cell rows.

    The shape is read from the PATH's own text, and its absence means the path
    declared none — not that a sibling path declared one. The head match is
    searched too, because `_PATH_HEAD_RE` can consume a leading `+ SHAPE <tok>`
    before the layer token."""
    segs: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    sec = re.search(r"^\s*SPECIALNETS\b(.*?)^\s*END\s+SPECIALNETS",
                    def_text, re.S | re.M)
    if not sec:
        return segs, gaps
    via_layers = parse_via_layers(def_text)
    for entry in re.split(r"\n\s*-\s+", sec.group(1)):
        nm = re.match(r"\s*(\S+)", entry)
        net = nm.group(1) if nm else "?"
        heads = list(_PATH_HEAD_RE.finditer(entry))
        for i, hm in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(entry)
            body = entry[hm.end():end]
            shm = _SHAPE_RE.search(hm.group(0) + " " + body)
            shape = shm.group(1).upper() if shm else None
            fp = (shape == "FOLLOWPIN")
            path_segs, gap = _path_segments(body, hm.group(1), via_layers)
            for layer, x1, y1, x2, y2 in path_segs:
                segs.append({"layer": layer, "net": net, "followpin": fp,
                             "shape": shape,
                             "x1": min(x1, x2), "y1": min(y1, y2),
                             "x2": max(x1, x2), "y2": max(y1, y2)})
            if gap is not None:
                gaps.append({"net": net, **gap})
    return segs, gaps


def parse_routed_segments(def_text: str) -> List[Dict[str, Any]]:
    """The segments only. `parse_routed_segments_with_gaps` for the denominator.

    Kept because it is the shape every existing caller reads; a caller that
    takes only this is asserting it does not care how much was read, and no
    caller inside this program does that any more."""
    return parse_routed_segments_with_gaps(def_text)[0]


def spans(seg: Dict[str, Any], box: Tuple[float, float, float, float]) -> bool:
    """Does the segment cross the box, entering one side and leaving the other?

    SPANNING, not merely touching: a fragment near an edge is ordinary, and
    flagging it would bury the real finding under noise. Horizontal and vertical
    are handled separately because a segment is one or the other."""
    bx1, by1, bx2, by2 = box
    horizontal = (seg["y2"] - seg["y1"]) <= (seg["x2"] - seg["x1"])
    if horizontal:
        return (seg["x1"] < bx1 and seg["x2"] > bx2
                and by1 <= seg["y1"] <= by2)
    return (seg["y1"] < by1 and seg["y2"] > by2
            and bx1 <= seg["x1"] <= bx2)


def merge_macro_obs(per_file: Sequence[Dict[str, Dict[str, Any]]],
                    labels: Sequence[str] = ()
                    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge per-file `parse_macro_obs` results, and never let a file that
    describes NO obstructions erase one that does.

    A plain `dict.update` is last-wins, and discovery order is `sorted()`, so
    the winner is decided by filename. That is fine while every declaration of
    a master carries the same geometry. It is not fine when one of them carries
    none — because "this file does not describe obstructions" and "this macro
    has no obstructions" are different facts, and last-wins collapses the first
    onto the second.

    MEASURED on a real post-route project. Six LEFs in one IP directory declare
    the same macro: five metal-stack variants carrying 61-65 OBS rects, and one
    antenna-data file carrying zero. `sorted()` puts the antenna file LAST (the
    byte `a` follows `M`), so it won:

        LEF order                       merged OBS rects   crossings   verdict
        sorted()      (antenna last)                   0           0   PASS
        reversed      (antenna first)                 61          28   FAIL
        antenna excluded                              65          45   FAIL

    The gate reported `[PASS] ... All 79 placed master(s) resolved to a LEF` —
    a completeness claim that is TRUE and does not mean what it reads as. The
    master resolved; its obstructions did not load. 45 supply segments spanning
    a declared obstruction went unreported because of alphabetical order.

    So: an empty declaration never displaces a non-empty one.

    When two NON-EMPTY declarations of one master disagree, that is a real
    ambiguity — a vendor ships metal-stack variants of the same macro, and this
    gate cannot know from LEF alone which one the run loaded. Keeping "the
    first" would leave the answer decided by filename again, one layer down. So
    the rule is stated rather than incidental: **keep the SMALLEST obstruction
    set, and report the conflict.**

    Smallest, because this gate BLOCKS and the two errors are not symmetric.
    Under-reporting leaves a violation unfound — a gap. Over-reporting accuses
    metal of crossing an obstruction the loaded variant never declared — a
    fabricated finding that stops a clean design, which this program's own
    header calls worse than none. Choosing the floor is the only choice that
    cannot manufacture a finding out of an ambiguity.

    That also makes the result independent of the order files are supplied in,
    which is the property the caller actually needs. Reporting an ambiguity is
    not resolving it; the conflict list says a choice existed, and says which
    way it was taken.

    Returns `(merged, conflicts)`."""
    merged: Dict[str, Dict[str, Any]] = {}
    kept_from: Dict[str, str] = {}
    conflicts: List[Dict[str, Any]] = []
    for i, d in enumerate(per_file):
        label = labels[i] if i < len(labels) else f"LEF#{i + 1}"
        for master, entry in d.items():
            rects = entry.get("obs") or []
            prev = merged.get(master)
            if prev is None:
                merged[master] = entry
                kept_from[master] = label
                continue
            prev_rects = prev.get("obs") or []
            if not rects:
                continue          # an empty declaration cannot displace anything
            if not prev_rects:
                merged[master] = entry        # first real geometry for it
                kept_from[master] = label
                continue
            if sorted(map(repr, rects)) == sorted(map(repr, prev_rects)):
                continue          # the same macro shipped twice; not a conflict
            take_new = len(rects) < len(prev_rects)
            keep, drop = ((entry, prev) if take_new else (prev, entry))
            kept_label = label if take_new else kept_from.get(master, "?")
            drop_label = kept_from.get(master, "?") if take_new else label
            merged[master] = keep
            kept_from[master] = kept_label
            conflicts.append({
                "master": master,
                "kept_from": kept_label,
                "other_from": drop_label,
                "kept_rect_count": len(keep.get("obs") or []),
                "other_rect_count": len(drop.get("obs") or []),
                "rule": "smallest-obstruction-set: on a blocking gate an "
                        "under-report is a gap, an over-report is a false "
                        "accusation",
            })
    return merged, conflicts


def audit(def_text: str, macro_lef_texts: Sequence[str]) -> Dict[str, Any]:
    obs_by_master, obs_conflicts = merge_macro_obs(
        [parse_macro_obs(t) for t in macro_lef_texts],
        [(lef_labels[i] if i < len(lef_labels) else f"LEF#{i + 1}")
         for i in range(len(macro_lef_texts))])

def audit(def_text: str, macro_lef_texts: Sequence[str],
          lef_labels: Sequence[str] = ()) -> Dict[str, Any]:
    """The verdict, plus the denominator the verdict actually consumed.

    `lef_labels` names the files behind `macro_lef_texts` so a discarded
    declaration can be attributed to one; it is optional and positional-safe,
    so every existing two-argument caller keeps working unchanged."""
    # Every declaration of every master, in READ ORDER. The previous shape was
    # a single `dict.update` merge, which keeps only the last and cannot say
    # that there WAS another — so an OBS-less abstract read after an OBS-
    # bearing LEF silently removed a macro from the comparison while the run
    # still reported that master as "resolved to a LEF".
    decls: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for i, t in enumerate(macro_lef_texts):
        label = (lef_labels[i] if i < len(lef_labels) else f"LEF#{i + 1}")
        for master, entry in parse_macro_obs(t).items():
            decls.setdefault(master, []).append((str(label), entry))
    # The WINNER is chosen by `merge_macro_obs`, not by read order. Those are
    # two separate fixes and they compose: this function's contribution is that
    # the DISCARDED declarations stay in hand so a completeness claim can name
    # what it consumed; `merge_macro_obs`'s is that an OBS-less abstract read
    # last can no longer be the winner in the first place. Taking read order
    # here would silently undo the second while keeping its tests green.
    obs_by_master, obs_conflicts = merge_macro_obs(
        [parse_macro_obs(t) for t in macro_lef_texts],
        [(lef_labels[i] if i < len(lef_labels) else f"LEF#{i + 1}")
         for i in range(len(macro_lef_texts))])
    with_obs = {m: e for m, e in obs_by_master.items() if e["obs"]}
    um = _UNITS_RE.search(def_text)
    units = int(um.group(1)) if um else 1000
    placed = parse_placed_macros(def_text, list(with_obs))
    segs, gaps = parse_routed_segments_with_gaps(def_text)

    findings: List[Dict[str, Any]] = []
    for inst in placed:
        e = with_obs[inst["master"]]
        if not e["size"]:
            continue
        ox, oy = inst["x"] / units, inst["y"] / units
        for (layer, x1, y1, x2, y2) in e["obs"]:
            box = place_rect((x1, y1, x2, y2), e["size"], ox, oy,
                             inst["orient"])
            box_du = tuple(v * units for v in box)
            for s in segs:
                if s["layer"].lower() != layer.lower():
                    continue
                if spans(s, box_du):
                    findings.append({
                        "inst": inst["inst"], "master": inst["master"],
                        "layer": layer, "net": s["net"],
                        "followpin": s["followpin"],
                        "shape": s.get("shape"),
                        "seg": [s["x1"], s["y1"], s["x2"], s["y2"]],
                    })
    # THE COMPARISON, PER LAYER — and the layers it never had metal for.
    #
    # A crossing can only be found on a layer where BOTH an obstruction rect and
    # a supply segment exist. The verdict publishes one number over all layers,
    # so a layer that contributed an obstruction but for which the reader
    # produced NO segment at all is indistinguishable from a layer that was
    # compared and came back clean. It is not the same fact, and it is the one
    # the reader most needs: an upper-layer strap is normally reached THROUGH a
    # via, so a truncated path removes that layer's metal entirely and the layer
    # then silently drops out of the comparison while the total still reads as
    # if it covered everything.
    #
    # Stated rather than inferred. `_no_segment_layers` is what this gate was
    # SILENT about; it is not a finding and does not move the verdict.
    _obs_layers = sorted({layer.lower()
                          for m in placed
                          for (layer, *_r) in with_obs[m["master"]]["obs"]})
    _seg_layers = {s["layer"].lower() for s in segs}
    _no_segment_layers = [ly for ly in _obs_layers if ly not in _seg_layers]

    findings_by_layer: Dict[str, int] = {}
    for _f in findings:
        k = _f["layer"].lower()
        findings_by_layer[k] = findings_by_layer.get(k, 0) + 1

    # #828 — the denominator this gate could not see. A master that is
    # PLACED but that no supplied LEF declares at all is a master whose OBS,
    # if it has one, was never in the comparison. Disclosed here rather than
    # left for the reader to infer from a silent [PASS]; `main` refuses to
    # call that a pass.
    placed_masters = parse_placed_masters(def_text)
    without_lef = sorted(placed_masters - set(obs_by_master))

    # THE CONSUMED PROPERTY, counted. `placed_masters` answers "did some file
    # name this master"; the verdict reads OBS RECTS, and only a master whose
    # winning declaration carries at least one contributed anything to it.
    # Published as its own number so the reader is not left to read the
    # precondition count as this one.
    placed_with_obs = sorted(
        m for m in placed_masters if obs_by_master.get(m, {}).get("obs"))
    placed_lef_no_obs = sorted(
        m for m in placed_masters
        if m in obs_by_master and not obs_by_master[m]["obs"])
    obs_rects_consumed = sum(
        len(obs_by_master[m]["obs"]) for m in placed_with_obs)

    # OBS evidence the INPUT SET carried and this verdict did NOT consume,
    # because the merge is by read order. `union != winner` is the whole
    # condition: silent on a single declaration, on the same file staged
    # twice, and on a winner that is already the richest.
    discarded: List[Dict[str, Any]] = []
    for m in sorted(placed_masters):
        d = decls.get(m) or []
        if len(d) < 2:
            continue
        winner = set(d[-1][1]["obs"])
        union: Set[Tuple[str, float, float, float, float]] = set()
        for _lbl, e in d:
            union |= set(e["obs"])
        if winner != union:
            discarded.append({
                "master": m,
                "chosen_from": d[-1][0],
                "chosen_obs_rects": len(winner),
                "obs_rects_not_consumed": len(union - winner),
                "declarations": [{"lef": lbl, "obs_rects": len(e["obs"])}
                                 for lbl, e in d],
            })

    # WHY THE COUNT MAY NOT BE QUOTED AS A TOTAL.
    #
    # `len(findings)` is the number of crossings this comparison FOUND. It is
    # the number of crossings that EXIST only when the comparison saw all of its
    # own inputs. Three conditions, each already measured above, break that:
    #
    #   * an abandoned path      — supply metal whose layer is unknown, so it
    #                              was never intersected with anything;
    #   * discarded OBS evidence — obstruction rects the LEF set carried and the
    #                              merge did not consume;
    #   * a placed master with no LEF — a footprint whose obstructions, if any,
    #                              were never in the comparison at all.
    #
    # Under any of them the number is a FLOOR. `main` already said so in prose
    # at the bottom of a FAIL report; the report a consumer actually parses said
    # nothing, so `len(rep["findings"])` was quotable as a total with no way to
    # learn it was not one. The flag travels WITH the count, in the same object,
    # because a caveat in a different place from the number it qualifies is a
    # caveat that will be separated from it.
    _floor_reasons: List[str] = []
    if gaps:
        _floor_reasons.append(
            f"{len(gaps)} wiring path(s) abandoned before their end "
            f"({sum(g['points_unread'] for g in gaps)} coordinate point(s) "
            f"unread) — that supply metal was never intersected")
    if discarded:
        _floor_reasons.append(
            f"{len(discarded)} placed master(s) had OBS rect(s) in the LEF set "
            f"that this comparison did not consume")
    if without_lef:
        _floor_reasons.append(
            f"{len(without_lef)} placed master(s) have no LEF declaration in "
            f"the set that was read, so their obstructions — if any — were "
            f"never compared")
    # NOT a floor reason on its own, and the distinction is the whole point. A
    # macro may declare an obstruction on a layer the design simply carries no
    # supply metal on; 0 findings there is then a TRUE clearance, and calling it
    # a gap would be this gate crying wolf. It becomes a gap only in the
    # presence of truncation — an upper-layer strap is normally reached THROUGH
    # a via, so an abandoned path removes that layer's metal entirely and the
    # layer drops out of the comparison while the total reads as if it covered
    # everything. That conjunction is the condition, and it is stated as one.
    if gaps and _no_segment_layers:
        _floor_reasons.append(
            "no supply segment was read on obstruction layer(s) "
            + ", ".join(_no_segment_layers)
            + " AND the read was truncated, so metal on those layer(s) may "
              "exist unread — a count of 0 there is silence, not a clearance")

    return {
        "masters_with_obs": sorted(with_obs),
        "placed_instances": len(placed),
        "special_segments": len(segs),
        # The consumed property, separate from the precondition below it.
        "placed_masters_with_obs": placed_with_obs,
        "placed_masters_lef_declares_no_obs": placed_lef_no_obs,
        "obs_rects_consumed": obs_rects_consumed,
        "obs_evidence_discarded": discarded,
        # The denominator's hole, named. Every entry is supply metal this gate
        # did NOT look at; `findings` is a verdict over the rest.
        "truncated_paths": gaps,
        "unread_points": sum(g["points_unread"] for g in gaps),
        "findings": findings,
        # The count, and whether it may be read as a total. See above.
        "findings_count": len(findings),
        "findings_by_layer": findings_by_layer,
        "count_is_floor": bool(_floor_reasons),
        "count_floor_reasons": _floor_reasons,
        # Layers an obstruction was declared on and for which the reader
        # produced no supply metal. The gate is SILENT about these; a 0 in
        # `findings_by_layer` for such a layer is not a clean result.
        "obs_layers_compared": _obs_layers,
        "obs_layers_with_no_supply_segment_read": _no_segment_layers,
        "placed_masters": len(placed_masters),
        "masters_declared_by_lef": sorted(obs_by_master),
        "placed_masters_without_lef": without_lef,
        # A master two supplied LEFs describe DIFFERENTLY. Not resolvable from
        # LEF alone, so it is disclosed rather than decided: the reader can see
        # that a choice existed, which a silent last-wins merge never showed.
        "obs_declaration_conflicts": obs_conflicts,
    }


def discover_macro_lefs(proj: Path) -> List[Path]:
    """Every LEF under the project that DECLARES A MACRO, in a stable order.

    #828 — the previous default was two globs,
    `input/pdk/**/*.lef` + `phase3/**/macro*.lef`, and both miss by one
    step: an IP LEF legitimately lives outside `input/pdk/` (e.g. under a
    `pdk_local` tree, which is not `pdk`), and a macro LEF staged under
    `phase3/` need not have a filename beginning `macro`. A file's LOCATION
    and its NAME are weak proxies for "this file defines a MACRO"; its
    CONTENT answers that question directly and cheaply, so that is what is
    asked here.

    The two original globs are searched FIRST and keep their relative order,
    so every project that already resolved keeps resolving identically —
    `audit` merges with `dict.update`, so discovery order decides which file
    wins a master declared twice. Files that were previously invisible are
    appended after; a master declared BOTH in a previously-visible file and
    in a previously-invisible one therefore now resolves to the latter. That
    is a deliberate consequence of no longer ignoring a file that is in the
    project.

    Only the DEFAULT discovery filters on content. An explicit `--macro-lef`
    is the operator naming the file, and is honoured verbatim.

    chip-AGNOSTIC: pure LEF grammar; no vendor, PDK or path literal beyond
    the two legacy globs it preserves."""
    if _ACTIVE_INPUT_PLAN is not None:
        # The held, verified population is the decision input.  Re-globbing or
        # restatting the pathname here would reopen a transient TOCTOU window.
        ordered = _ACTIVE_INPUT_PLAN.paths("macro-lef")
    else:
        ordered = _default_macro_lef_population(proj)
    out: List[Path] = []
    for p in ordered:
        try:
            text = _read_input_text(p)
        except OSError:
            continue
        if _MACRO_RE.search(text):
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--def", dest="def_path", type=Path, default=None)
    ap.add_argument("--macro-lef", dest="macro_lefs", type=Path, action="append",
                    default=None)
    ap.add_argument("--json", dest="json_out", type=Path, default=None)
    a = ap.parse_args(argv)

    global _ACTIVE_INPUT_PLAN
    with _semantic_progress.child_progress(PROGRESS_SCOPE) as progress:
        try:
            if progress.enabled:
                if (a.def_path is not None or a.macro_lefs is not None
                        or a.json_out is not None):
                    raise _semantic_progress.ProgressProtocolError(
                        "routed parent progress covers the default DEF/LEF "
                        "population only")
                _ACTIVE_INPUT_PLAN = _input_plan(a.project_dir)
                _ACTIVE_INPUT_PLAN.materialize(progress)
            rc = _main_parsed(a)
            if _ACTIVE_INPUT_PLAN is not None:
                _ACTIVE_INPUT_PLAN.checkpoint_decision(
                    fresh_plan=_input_plan(a.project_dir))
            return rc
        finally:
            _ACTIVE_INPUT_PLAN = None


def _main_parsed(a) -> int:

    proj = a.project_dir
    def_p = a.def_path
    if def_p is None:
        cands = (_ACTIVE_INPUT_PLAN.paths("routed-def")
                 if _ACTIVE_INPUT_PLAN is not None else
                 sorted(proj.glob("phase3/stage3/pnr/routed*.def")))
        def_p = cands[0] if cands else None
    if (def_p is None
            or (_ACTIVE_INPUT_PLAN is None and not def_p.is_file())):
        reason = f"no routed DEF under {proj}. NOT a pass."
        print(f"[CANNOT DETERMINE] macro_obs_geometry_intersect: {reason}",
              file=sys.stderr)
        # The routed DEF is the artefact step 21 exists to produce; a tree
        # without one has not reached this gate's subject at all.
        return _typed_refusal(a.json_out, "macro_obs_geometry_intersect",
                              _reason_taxonomy.BLOCKED_BY_UPSTREAM, reason)

    lefs = list(a.macro_lefs or [])
    if not lefs:
        lefs = discover_macro_lefs(proj)
    texts = []
    labels = []
    for p in lefs:
        try:
            texts.append(_read_input_text(p))
        except OSError:
            continue
        labels.append(str(p))
    if not texts:
        declared = macro_declaration_sites(proj)
        reason = ("no macro LEF found. A run with no macro LEF is not a run "
                  "with no obstruction — it is one this gate could not read. "
                  "NOT a pass.")
        if declared:
            reason += (f" The project DECLARES a macro at "
                       f"{', '.join(declared)} and its abstract never reached "
                       f"this gate.")
            cls = _reason_taxonomy.BLOCKED_BY_UPSTREAM
        else:
            reason += (f" The project declares no macro at any of "
                       f"{', '.join(_MACRO_DECLARATION_SITES)}, so no abstract "
                       f"is owed: the design integrates no macro.")
            cls = _reason_taxonomy.DESIGN_DECLARED_NA
        print(f"[CANNOT DETERMINE] macro_obs_geometry_intersect: {reason}",
              file=sys.stderr)
        return _typed_refusal(a.json_out, "macro_obs_geometry_intersect",
                              cls, reason)

    rep = audit(_read_input_text(def_p), texts, labels)
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, indent=2) + "\n")

    unresolved = rep["placed_masters_without_lef"]
    # #828 — when the LEF set is incomplete, say so in the SAME breath as the
    # other two refusals. "No macro declares an OBS" reads as a statement
    # about the design; if half the placed masters have no LEF at all it is a
    # statement about the input, and the reader must not have to guess which.
    _incomplete = (
        f" {len(unresolved)} of {rep['placed_masters']} placed master(s) have "
        f"NO LEF declaration in the set that was read "
        f"({', '.join(unresolved[:6])}"
        f"{f', +{len(unresolved) - 6} more' if len(unresolved) > 6 else ''}),"
        f" so the LEF set is INCOMPLETE."
    ) if unresolved else ""

    if not rep["masters_with_obs"]:
        # The LEF set was read in full and declares no obstruction: that is
        # the design's own statement, examined, not an absence inferred.
        reason = ("no macro in the supplied LEF(s) declares an OBS. NOT a "
                  f"pass — nothing was checked.{_incomplete}")
        print(f"[CANNOT DETERMINE] macro_obs_geometry_intersect: {reason}",
              file=sys.stderr)
        return _typed_refusal(a.json_out, "macro_obs_geometry_intersect",
                              _reason_taxonomy.DESIGN_DECLARED_NA, reason, rep)
    if not rep["placed_instances"]:
        # The DEF is the design's own placement record and it places no
        # instance of any OBS-bearing master: examined, and N/A by the design.
        reason = (f"{len(rep['masters_with_obs'])} master(s) declare an OBS "
                  f"and none is PLACED in this DEF. NOT a pass.{_incomplete}")
        print(f"[CANNOT DETERMINE] macro_obs_geometry_intersect: {reason}",
              file=sys.stderr)
        return _typed_refusal(a.json_out, "macro_obs_geometry_intersect",
                              _reason_taxonomy.DESIGN_DECLARED_NA, reason, rep)

    f = rep["findings"]
    gaps = rep["truncated_paths"]
    discarded = rep["obs_evidence_discarded"]

    def _name_the_discarded() -> None:
        print(f"\n  {len(discarded)} placed master(s) are declared by MORE THAN "
              f"ONE LEF that was read, and the\n  declaration this run USED "
              f"omits obstruction rect(s) that another read\n  declaration of "
              f"the same master DOES carry. LEFs merge in read order, so the\n"
              f"  file read last decided what this verdict was able to see:")
        for d in discarded[:8]:
            where = "; ".join(f"{x['lef']} ({x['obs_rects']} OBS rect(s))"
                              for x in d["declarations"])
            print(f"   master {d['master']}: used {d['chosen_from']} with "
                  f"{d['chosen_obs_rects']} OBS rect(s); "
                  f"{d['obs_rects_not_consumed']} rect(s) declared elsewhere "
                  f"were NOT in the comparison  [{where}]")
        if len(discarded) > 8:
            print(f"   … {len(discarded) - 8} more")

    def _name_the_gaps() -> None:
        print(f"\n  {len(gaps)} wiring path(s) were ABANDONED before their end "
              f"and NOT examined\n  ({rep['unread_points']} coordinate point(s) "
              f"unread). A via that is not declared in\n  this DEF's own VIAS "
              f"section comes from the tech LEF, which this gate does\n  not "
              f"read, so the layer of everything after it is unknown:")
        for gp in gaps[:8]:
            print(f"   net {gp['net']}  path head {gp['head_layer']}  "
                  f"stopped at via '{gp['via']}' — {gp['reason']}  "
                  f"({gp['points_read']} read, {gp['points_unread']} unread)")
        if len(gaps) > 8:
            print(f"   … {len(gaps) - 8} more")

    is_floor = rep["count_is_floor"]

    def _name_the_floor() -> None:
        """Say WHY the number is a floor, next to the number itself."""
        print("\n  THIS COUNT IS A FLOOR, NOT A TOTAL — it is what this "
              "comparison found, not\n  what the layout contains, because the "
              "comparison did not see all of its\n  own inputs:")
        for r in rep["count_floor_reasons"]:
            print(f"   - {r}")

    if f:
        fp = sum(1 for x in f if x["followpin"])
        # "at least N", not "N", whenever the read was incomplete. The gate
        # already conceded this in prose at the BOTTOM of the report, three
        # screens below the number a reader quotes — and a caveat that far from
        # its number is a caveat that gets separated from it. The headline is
        # the only place that cannot be read without the qualifier.
        _n = f"at least {len(f)}" if is_floor else f"{len(f)}"
        _fpn = f"at least {fp}" if is_floor else f"{fp}"
        print(f"[FAIL] {_n} supply segment(s) SPAN a placed macro's declared "
              f"obstruction ({_fpn} of them follow-pins):")
        for x in f[:12]:
            # The path's OWN declared shape, not a flag derived from a
            # substring of the whole net entry. `SHAPE (none)` is a real and
            # different fact from `SHAPE STRIPE`, so it is printed rather than
            # collapsed into the absence of a FOLLOWPIN token.
            print(f"   {x['inst']} ({x['master']}) {x['layer']}: net {x['net']}"
                  f"  SHAPE {x.get('shape') or '(none)'}  seg {x['seg']}")
        if len(f) > 12:
            print(f"   … {len(f) - 12} more")
        print("\n  A macro OBS is the vendor's statement of where the integrator "
              "may not put\n  metal. It is not in the PDK deck, so sign-off DRC "
              "cannot see this; and the\n  wire is attached to the right net, so "
              "a connectivity audit cannot either.")
        # The per-layer split, published BY the gate rather than left to a
        # consumer to derive from `findings` — because a layer missing from
        # that derivation is invisible, and a layer with no supply metal read
        # is exactly the case that goes missing.
        print("\n  BY LAYER: " + ", ".join(
            f"{ly}={n}" for ly, n in sorted(rep["findings_by_layer"].items()))
            + f"   (obstruction layer(s) compared: "
              f"{', '.join(rep['obs_layers_compared']) or 'none'})")
        if gaps and rep["obs_layers_with_no_supply_segment_read"]:
            print("  SILENT ON: "
                  + ", ".join(rep["obs_layers_with_no_supply_segment_read"])
                  + " — an obstruction was declared on these layer(s), NO "
                    "supply\n  segment was read on any of them, and the read "
                    "was truncated. Their metal may\n  exist unread, so the "
                    "absence of a finding there is silence, not a clearance.")
        if gaps:
            _name_the_gaps()
        if discarded:
            _name_the_discarded()
        if is_floor:
            _name_the_floor()
        return 1

    # #828 — reached only when nothing was found to complain about. Whether
    # that means "clean" or "I did not have the file that would have told me"
    # is decided HERE, not left to the reader of a [PASS] line. A run in which
    # a placed master has no OBS source is not a clean run.
    if unresolved:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no crossing "
              f"found among {rep['placed_instances']} placed instance(s) of "
              f"{len(rep['masters_with_obs'])} master(s) with OBS, but"
              f"{_incomplete} An unread LEF may declare an OBS that is "
              "being crossed, so this is not the same sentence as 'none spans "
              "an obstruction'. NOT a pass. Name the missing LEF(s) with "
              "--macro-lef, or stage them under the project.",
              file=sys.stderr)
        return _typed_refusal(
            a.json_out, "macro_obs_geometry_intersect",
            _reason_taxonomy.BLOCKED_BY_UPSTREAM,
            f"no crossing found, but {len(unresolved)} of "
            f"{rep['placed_masters']} placed master(s) have no LEF declaration "
            f"in the set that was read; an unread LEF may declare an OBS that "
            f"is being crossed. NOT a pass.", rep)

    # The measured defect. A master that resolved to a LEF satisfies the
    # PRECONDITION; supplying the OBS rects the verdict reads is the CONSUMED
    # property, and the two are not the same claim. Where the input set held
    # obstruction evidence that the read-order merge threw away, this run's
    # "none spans an obstruction" is a statement about a comparison that was
    # missing part of its own input.
    if discarded:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no crossing "
              f"found among {rep['placed_instances']} placed instance(s), but "
              "the OBS evidence this comparison consumed is not the OBS "
              "evidence the LEF set contained.", file=sys.stderr)
        _name_the_discarded()
        # Both refusals are rc=2, so returning here would swallow the other
        # one's evidence and publish half a reason — the same shape this
        # branch exists to catch. Name the truncation too when it is present.
        if gaps:
            _name_the_gaps()
        print("\n  This gate does NOT promote the richer declaration. An "
              "obsolete LEF left in the\n  project would then FABRICATE a "
              "crossing on a gate that blocks, and a fabricated\n  finding is "
              "worse than a missed one. It refuses to certify instead.\n"
              "\n  Remedy: name the authoritative file with --macro-lef, or "
              "remove the stale\n  declaration from the project"
              + ("; and supply the tech LEF so the layer\n  after each via is "
                 "known" if gaps else "") + ". NOT a pass.")
        return _typed_refusal(
            a.json_out, "macro_obs_geometry_intersect",
            _reason_taxonomy.EXECUTION_ERROR,
            f"no crossing found, but the OBS evidence this comparison consumed "
            f"is not the OBS evidence the LEF set contained "
            f"({len(discarded)} placed master(s) declared by more than one "
            f"file). The input set contradicts itself. NOT a pass.", rep)

    # No finding, but part of the supply metal was never read. "I could not
    # look" must not share an exit code with "I looked and it was clean" — that
    # is this gate's own rule, and a truncated path is exactly the first case.
    # rc=2 is what `run_tolerating_uncheckable` is for; rc=0 here would be a
    # partial denominator published as a clean verdict, which is the defect the
    # gate exists to catch, one scale down.
    if gaps:
        print(f"[CANNOT DETERMINE] macro_obs_geometry_intersect: "
              f"{rep['placed_instances']} placed instance(s) of "
              f"{len(rep['masters_with_obs'])} master(s) with OBS; "
              f"{rep['special_segments']} supply segment(s) examined and none "
              f"spans an obstruction — but the read is INCOMPLETE. NOT a pass.",
              file=sys.stderr)
        _name_the_gaps()
        print("\n  Remedy: pass the tech LEF's vias in the DEF's VIAS section, "
              "or supply the\n  tech LEF, so the layer after each via is known.")
        return _typed_refusal(
            a.json_out, "macro_obs_geometry_intersect",
            _reason_taxonomy.BLOCKED_BY_UPSTREAM,
            f"{rep['special_segments']} supply segment(s) examined and none "
            f"spans an obstruction — but {len(gaps)} routed path(s) could not "
            f"be read to the end (the layer after a via is unknown without "
            f"the tech LEF). NOT a pass.", rep)

    # The completeness claim is computed from the property the verdict READS —
    # obstruction geometry that reached the comparison — and the weaker
    # precondition it used to be derived from ("resolved to a LEF") is printed
    # NEXT TO it rather than in place of it. A reader must be able to see the
    # gap without re-deriving it; that is the entire point of the two numbers.
    consumed = rep["placed_masters_with_obs"]
    silent = rep["placed_masters_lef_declares_no_obs"]
    print(f"[PASS] macro_obs_geometry_intersect: {rep['placed_instances']} placed "
          f"instance(s) of {len(consumed)} placed master(s) whose LEF declares an "
          f"OBS, {rep['special_segments']} supply segment(s), 0 path(s) abandoned "
          f"— none spans an obstruction.")
    # NO BARE UNIVERSAL QUANTIFIER over the precondition count. "All N placed
    # master(s) resolved to a LEF" is true and reads as the verdict's own
    # denominator; stating both ratios keeps the reader from having to know
    # which of the two numbers the result is about. The rule this line obeys
    # is machine-checkable and its test states it: no "all N" may appear whose
    # N exceeds the number of masters that supplied the consumed evidence.
    print(f"  EVIDENCE CONSUMED: {len(consumed)} of {rep['placed_masters']} placed "
          f"master(s) supplied obstruction geometry to this comparison "
          f"({rep['obs_rects_consumed']} OBS rect(s)). "
          f"{rep['placed_masters']} of {rep['placed_masters']} resolved to a LEF "
          f"— that is the PRECONDITION, not this property: the {len(silent)} that "
          f"resolved to a LEF declaring NO OBS contributed nothing to the "
          f"verdict, because 'resolved to a LEF' is not 'its obstructions were "
          f"read'. This result covers the {len(consumed)} and is SILENT about "
          f"the {len(silent)}."
          + (f" Not consulted: {', '.join(silent[:6])}"
             f"{f', +{len(silent) - 6} more' if len(silent) > 6 else ''}."
             if silent else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
