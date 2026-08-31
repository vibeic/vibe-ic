#!/usr/bin/env python3
"""sta_corner_record_completeness_check.py — the timing RECORD-completeness gate.

ENFORCEMENT: blocking — Step 23 invokes this gate through
``program_exit_zero``; a non-zero verdict stops post-route STA completion.

The defect (measured, not hypothetical)
---------------------------------------
A campaign ledger carried NO STA column at all while two ICs violated setup at
the slow sign-off corner — worst setup slack -4.33 ns (TNS -259.13) and
-2.35 ns (TNS -10.36) — both persisting unchanged through the post-fix verify
runs. Because timing was simply ABSENT from the record, the campaign narrative
became "the phase-3 failures were LVS tooling artifacts": true of the LVS part,
but it was allowed to sound like the whole explanation while real timing
violations sat unreported.

The same shape recurs across the corpus: a run MET at the typ/nominal corner
while its slow corner VIOLATED. **A typ-only "MET" is a misleading pass.** A run
may not report timing as satisfied while a sign-off corner is violating or
unreported.

What this gate is (and what it deliberately is NOT)
--------------------------------------------------
This gate judges the COMPLETENESS and HONESTY of the timing record.
`post_route_signoff_corner_check` (#147) already FAILs on a negative worst-slack
inside the multicorner report, and that slack rule is NOT re-implemented here.
The hole this gate closes is that #147 is wired in the flow YAML as

    optional_program_exit_zero:
      command: "post_route_signoff_corner_check . --json ..."
      condition_files_exist: ["phase3/stage3/sta/sta_spef_multicorner.rpt"]

so when the report is ABSENT the condition is false, the gate never runs, and
Step 23 passes. An unreported corner is thereby indistinguishable from a met
one — which is exactly how -4.33 ns went unnoticed. This gate is UNCONDITIONAL:
it starts from the corners the flow DECLARED and fails when the record fails to
account for each of them.

Rules
-----
R1 REPORTED-CORNER COMPLETENESS — every corner appearing in the timing record
   must be identified BY NAME, and a corner report that carries no declared
   sign-off role (a bare per-corner characterisation) must carry BOTH a worst
   setup and a worst hold slack. Half a corner is an incomplete record.
   EXEMPT: the declared nominal/primary corner. It holds no sign-off role —
   setup is signed off at the slow corner and hold at the fast one — so its
   single-corner report legitimately carries setup only. Requiring hold from it
   would be a FABRICATED violation that fails every run in the corpus, the
   clean ones included. Its datapoint still appears in the evidence table, and
   R3 still uses it to expose the typ-MET-while-sign-off-VIOLATED shape.

R2 DECLARED-BUT-UNREPORTED — every (corner, role) the flow was CONFIGURED to
   analyse must have a slack datapoint for that role. A declared sign-off corner
   with no timing datapoint FAILs; it does not silently vanish. This is also the
   rule that makes a typ-only record fail rather than pass.
   R2 additionally covers the starkest form of the same defect: an STA artifact
   that CITES the report its numbers came from (`post_route_signoff_corner.json`
   and the two stance files all carry such a citation) while that report is
   gone. The citation proves corners were analysed; the missing target proves
   nothing survived to substantiate it. Measured in the corpus: a run carrying
   a `"verdict": "FAIL", "setup_worst_slack_ns": -52.48` verdict whose cited
   `sta_spef_multicorner.rpt` does not exist.

R3 NO TYP-ONLY PASS — if any SIGN-OFF corner violates, the run's timing verdict
   is VIOLATION regardless of what the primary/typ corner says. A sign-off
   corner is judged only on the datapoint for the role it was declared to
   serve: setup at the setup corner, hold at the hold corner. Other datapoints
   on the same row remain disclosed, but cannot turn a met sign-off role into a
   violation (for example, a pre-layout setup estimate carried beside a
   post-route hold result). When the primary corner MET while a sign-off corner
   violated, the finding says so explicitly, because that combination is the
   misleading pass this gate exists to stop.

R4 CORNER-LIBRARY RESOLUTION — a multi-corner claim must be backed by multiple
   corner LIBRARIES, and a degradation to fewer must be LOUD.
   Measured: a run reported three corners while reading the SAME typ liberty
   three times, varying only the SPEF. The multi-corner degradation path is
   DESIGNED behaviour — the runner's own docstring says that when corner libs
   are unavailable "it degrades to the single-corner read_liberty
   (byte-identical to the pre-multi-corner emission)". The degradation is not
   the defect; the SILENCE about it is. A degraded run was byte-indistinguishable
   in its output from a genuine multi-corner run.
   R4 is judged at RUN level, across every sign-off axis at once. A
   single-library RC axis is NOT a degradation: the RC axis varies PARASITICS,
   and analysing its corners with one process library is correct by design.
   The degradation is when the run AS A WHOLE reports several corners while
   never analysing more than one distinct library on ANY axis. Judging this per
   axis would label every healthy run degraded — the mirror image of the defect,
   and just as useless.
   R4 then splits the outcome rather than collapsing it into one verdict:
     * collapse with a multi-corner claim and NO disclosure -> FAIL
       (`R4_MULTI_CORNER_CLAIM_UNSUPPORTED`). Reporting N corners backed by one
       library is a false claim regardless of intent.
     * collapse the run DISCLOSES about itself -> verdict `SINGLE_CORNER_ONLY`,
       exit 0. A PDK that genuinely ships one library CANNOT do better, and
       FAILing it would fabricate a violation on every single-library PDK — the
       same error the R1 nominal-corner exemption exists to avoid. But it is
       never allowed to read as multi-corner sign-off: the verdict STRING
       carries the limitation, so no downstream summary can quote a bare "PASS".
     * a multi-corner claim whose library resolution was never RECORDED at all
       -> FAIL (`R4_LIBRARY_RESOLUTION_UNRECORDED`). Unverifiable multi-corner
       sign-off is the exact shape being fixed; letting it pass silently for
       want of a record would re-create the defect inside its own gate.
   Which corners collapsed onto which library, and why the others could not be
   resolved, are named in the finding and in the evidence table.

R5 DRV (max_slew / max_capacitance / max_fanout) MUST BE SURFACED — measured:
   139 max_slew violations at the slow corner, entirely invisible to the flow's
   check. Two distinct failures, both FAIL:
     * `R5_DRV_VIOLATION` — the record SHOWS DRV violations. They are real
       sign-off violations and are reported as such, with per-corner counts.
     * `R5_DRV_UNQUERIED` — a sign-off corner report exists but OpenSTA was
       never asked for DRV at all (no `report_check_types`, no check-types
       marker), or the query errored. An unqueried DRV limit is
       indistinguishable from a met one — the same disease as an unreported
       corner, which is what R2 already says about slack.

How sign-off corners are learned (READ from the flow, never hardcoded)
----------------------------------------------------------------------
This was determined by reading `phase3_one_shot_runner.py`, not assumed. The
flow declares sign-off roles EXPLICITLY, but on two axes with two different
corner vocabularies, and there is NO single unified corner registry:

  PROCESS axis — `reports/phase3/mcorner_ocv_stance.json`, emitted alongside
    `sta_mcorner_ocv.rpt`, names the roles outright:
        {"setup_process_corner": "SS", "hold_process_corner": "FF", ...}

  RC axis — `reports/phase3/multi_corner_spef_stance.json`, emitted alongside
    `sta_spef_multicorner.rpt`:
        {"setup_corner": "max", "hold_corner": "min",
         "corners_extracted": ["max", "min", "nom"], ...}
    with the same roles restated in the report header as
        `# SETUP corner: max-RC   HOLD corner: min-RC`
    which this gate falls back to parsing when the stance JSON is absent.

  NOMINAL — `phase2/stage2/constraints/pvt_matrix.json` carries a
    `primary_corner` field (e.g. "TT") naming the nominal corner, plus the
    `corners: [{name, label}]` matrix whose labels come from the runner's own
    `_classify_corner_from_name` (vocabulary SS/TT/FF/unknown).

Two consequences are load-bearing and are the reason this gate is not a naive
set-difference:

  * `corners_extracted` / `corners_available` / the `pvt_matrix` corner list are
    AVAILABILITY lists, not run lists. `nom` is extracted on every run and
    deliberately never analysed (setup is signed off at the slow corner and hold
    at the fast one — correct practice). Such corners are shown in the evidence
    table as `available_not_selected` and NEVER trigger R2. Treating availability
    as configuration would make this gate fire on every run in the corpus.

  * a corner is judged for the ROLE it was declared to serve. Demanding hold
    slack at the slow setup corner would be a fabricated violation, not a found
    one. A corner carrying NO declared role must still carry both.

A declared corner whose label is `unknown`, or a run that declares no primary,
is treated as SIGN-OFF, never as nominal: silently demoting an unclassifiable
corner to "informational" would be this very bug in a new costume.

If nothing at all is declared and nothing was recorded, the gate returns
NOT_APPLICABLE with `no_corner_declaration` in its findings — it says so out
loud rather than inventing a sign-off corner set.

Evidence emission (the absence of this table IS the defect)
-----------------------------------------------------------
The gate ALWAYS emits the full per-corner table it judged on — corner name,
axis, declared role(s), sign-off class, setup WNS, hold WNS, TNS and the source
artifact path for each — to stdout and into the verdict JSON, on PASS and FAIL
alike. A gate that reproduced the missing-table defect while policing it would
be absurd.

Exit: 0 PASS / NOT_APPLICABLE / SINGLE_CORNER_ONLY · 1 FAIL · 2 IO-or-arg error.

chip-AGNOSTIC / benchmark-AGNOSTIC: no design, IC, PDK, vendor or corner-name
literal drives any verdict; corner identity and sign-off role come from the
run's own declaration artifacts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _path_layout as _pl  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _pl = None

_PROGRAM = "sta_corner_record_completeness_check"

# Float-noise guard (ns): a slack this close to zero is met, so STA rounding
# never manufactures a phantom violation. Real misses are orders larger.
_DEFAULT_SLACK_TOL_NS = 0.001

AXIS_PROCESS = "process"
AXIS_RC = "rc"

# ── declaration artifacts ───────────────────────────────────────────────────
_PROCESS_STANCE_CANDIDATES = (
    "reports/phase3/mcorner_ocv_stance.json",
    "reports/phase3/sta/mcorner_ocv_stance.json",
)
_RC_STANCE_CANDIDATES = (
    "reports/phase3/multi_corner_spef_stance.json",
    "reports/phase3/sta/multi_corner_spef_stance.json",
)
_PVT_CANDIDATES = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "constraints/pvt_matrix.json",
    "phase3/stage3/constraints/pvt_matrix.json",
)

# ── record artifacts ────────────────────────────────────────────────────────
_MULTICORNER_CANDIDATES = (
    "phase3/stage3/sta/sta_spef_multicorner.rpt",
    "reports/phase3/sta_spef_multicorner.rpt",
    "reports/phase3/sta/sta_spef_multicorner.rpt",
)
_MCORNER_OCV_CANDIDATES = (
    "phase3/stage3/sta/sta_mcorner_ocv.rpt",
    "reports/phase3/sta_mcorner_ocv.rpt",
    "reports/phase3/sta/sta_mcorner_ocv.rpt",
)
_NOMINAL_SPEF_CANDIDATES = (
    "phase3/stage3/sta/sta_spef_based.rpt",
    "reports/phase3/sta_spef_based.rpt",
    "reports/phase3/sta/sta_spef_based.rpt",
)
_PER_CORNER_DIRS = (
    "phase3/stage3/sta/per_corner",
    "reports/phase3/sta/per_corner",
)

# STA artifacts that CITE the report their numbers came from. A citation whose
# target is gone is a verdict that outlived its evidence — the record no longer
# substantiates the claim, so the cited corners are unreported by definition.
_CITING_ARTIFACTS = (
    ("reports/phase3/sta/post_route_signoff_corner.json", "report"),
    ("reports/phase3/post_route_signoff_corner.json", "report"),
    ("reports/phase3/mcorner_ocv_stance.json", "report"),
    ("reports/phase3/multi_corner_spef_stance.json", "multicorner_sta_report"),
)

# `worst slack max -1.71` / `worst slack min 0.54` (OpenSTA max=setup, min=hold)
_WORST_SLACK_RE = re.compile(
    r"worst\s+slack\s+(max|min)\s+(-?\d+(?:\.\d+)?)", re.IGNORECASE)
# `worst slack max INF` — OpenSTA's NO-PATHS-ANALYSED sentinel, not a number.
# `worst_slack` starts at infinity and takes the min over the analysed paths,
# so it is still INF exactly when the path set was EMPTY. Measured in the
# corpus: three published reports whose whole body is
#     No paths found. / tns max 0.00 / wns max 0.00 / worst slack max INF
# The `wns 0.00` there is arithmetically derived (`wns = min(0, worst_slack)`)
# and carries NO independent evidence — it reads 0.00 *because* nothing was
# analysed, not because timing was met. Reading it as a met +0.000 ns is this
# gate's own founding defect ("an unreported corner is indistinguishable from
# a met one") reproduced inside its own reader, so the sentinel is matched
# BEFORE `_WORST_SLACK_RE` — which would otherwise scrape a bogus `1` out of
# an exponent-form `1e+30`.
_WORST_SLACK_NO_PATH_RE = re.compile(
    r"worst\s+slack\s+(max|min)\s+[-+]?(?:inf(?:inity)?|1(?:\.0+)?e\+?30)\b",
    re.IGNORECASE)
# `WNS -0.05` and `WNS = -0.05` are both real summary-line dialects (some
# tools/scripts insert the `=`, OpenSTA's own `report_wns`/report_tns` do
# not) — `[:=]?` accepts the separator without requiring it, widening
# neither the token nor the value grammar.
_WNS_RE = re.compile(r"\bwns\s*[:=]?\s*(max|min)?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_TNS_RE = re.compile(r"\btns\s*[:=]?\s*(max|min)?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
# `=== SETUP (max-RC corner, SPEF=max) ===`  (multicorner SPEF report)
# `=== SETUP corner: process=SS liberty, SPEF=x.max.spef ===` (mcorner OCV)
_SECTION_RE = re.compile(r"===\s*(SETUP|HOLD)\b", re.IGNORECASE)
_SECTION_PROCESS_RE = re.compile(
    r"===\s*(SETUP|HOLD)\s+corner:\s*process=([\w.+-]+)", re.IGNORECASE)
# `# SETUP corner: max-RC   HOLD corner: min-RC`
_SIGNOFF_HEADER_RE = re.compile(
    r"#\s*SETUP\s+corner:\s*([\w.+-]+?)(?:-RC)?\s+HOLD\s+corner:\s*"
    r"([\w.+-]+?)(?:-RC)?\s*$", re.IGNORECASE)
_CORNERS_AVAIL_RE = re.compile(r"#\s*corners_available:\s*(.+)", re.IGNORECASE)
_PER_CORNER_RPT_RE = re.compile(r"^sta_(.+)\.rpt$", re.IGNORECASE)

# ── R4: corner -> liberty resolution ───────────────────────────────────────
# The emitter records which liberty each reported corner was actually analysed
# with, both as a header line and inside the per-section banner. Without this
# record a "multi-corner" report cannot be told apart from N reads of one lib.
#   `# corner_liberty: max=/pdk/.../lib__ss_100C_1v60.lib`
_CORNER_LIBERTY_RE = re.compile(
    r"#\s*corner_liberty:\s*([\w.+-]+)\s*=\s*(\S+)", re.IGNORECASE)
#   `=== SETUP (max-RC corner, SPEF=max, liberty=/pdk/.../x.lib) ===`
#   `=== SETUP corner: process=SS liberty=/pdk/.../x.lib, SPEF=... ===`
_SECTION_LIBERTY_RE = re.compile(r"liberty=(\S+?)[,)\s]", re.IGNORECASE)
# The stance JSONs gain an explicit resolution block (authoritative when present)
_LIB_RESOLUTION_FIELD = "corner_library_resolution"

# ── R5: DRV (design-rule violation) evidence ───────────────────────────────
# `report_check_types -max_slew -max_capacitance ...` prints one titled table
# per check kind. Titles are matched loosely so an OpenSTA wording change
# degrades to "no DRV section found" (loud) rather than to a silent clean pass.
_DRV_KINDS = {
    "max slew": "max_slew",
    "max transition": "max_slew",
    "max capacitance": "max_capacitance",
    "max cap": "max_capacitance",
    "max fanout": "max_fanout",
}
_DRV_TITLE_RE = re.compile(
    r"^(max\s+(?:slew|transition|capacitance|cap|fanout))\s*$", re.IGNORECASE)
# A non-DRV table title ends the current DRV table.
_OTHER_TITLE_RE = re.compile(
    r"^(min\s+pulse\s+width|recovery|removal|setup|hold|clock\s+gating|"
    r"data\s+check|latch\s+check|unconstrained)\b.*$", re.IGNORECASE)
_VIOLATED_RE = re.compile(r"\(VIOLATED\)", re.IGNORECASE)
# Fallback when the build does not print the (VIOLATED) tag: a table row whose
# trailing column (the slack) is negative.
_TRAILING_NEG_RE = re.compile(r"(-\d+(?:\.\d+)?)\s*$")
# The emitter's authoritative attestation that the check types actually ran
# (see phase3_one_shot_runner._SIGNOFF_CHECK_TYPES_MARKER). Its ABSENCE is what
# distinguishes "queried and clean" from "never asked".
_CHECK_TYPES_OK_RE = re.compile(
    r"SIGNOFF_CHECK_TYPES_REPORTED\b(.*)$", re.IGNORECASE)
_CHECK_TYPES_FAIL_RE = re.compile(
    r"SIGNOFF_CHECK_TYPES_FAILED\s+reason=(.*)$", re.IGNORECASE)


# ── small helpers ──────────────────────────────────────────────────────────
def _first_existing(project: Path, rels: Tuple[str, ...]) -> Optional[Path]:
    for rel in rels:
        p = project / rel
        if p.is_file():
            return p
    return None


def _load_json(path: Optional[Path]) -> Optional[Dict[str, object]]:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _rel(project: Path, p: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:
        return str(p)


def _key(axis: str, corner: str) -> Tuple[str, str]:
    return (axis, str(corner).strip().lower())


def _merge_slack(cur: Optional[float], new: Optional[float]) -> Optional[float]:
    if new is None:
        return cur
    return new if cur is None else min(cur, new)


# ── report basis ───────────────────────────────────────────────────────────
#: A report's own `STA_BASIS:` stamp, the same self-disclosure
#: `eda_report_audit` already reads. PRE-PnR emitters stamp
#: `PRE_LAYOUT_ESTIMATE`; post-route emitters stamp `POST_ROUTE_SPEF` /
#: `POST_ROUTE_NO_SPEF` or carry no stamp at all.
_STA_BASIS_STAMP_RE = re.compile(r"^\s*#?\s*STA_BASIS\s*:\s*([A-Z_]+)",
                                 re.MULTILINE)

BASIS_PRE_LAYOUT = "PRE_LAYOUT"
BASIS_SIGNOFF = "SIGNOFF"


def report_basis(text: str) -> str:
    """Which side of place-and-route a report DISCLOSES ITSELF to be from.

    Only an EXPLICIT `PRE_LAYOUT*` stamp is treated as pre-layout. Everything
    else — a `POST_ROUTE*` stamp, an unrecognised stamp, or no stamp at all —
    is `SIGNOFF`. That asymmetry is deliberate and is the safe direction: an
    unstamped report keeps exactly the standing it has today, so this function
    can only ever DEMOTE a report that went out of its way to say it is not
    sign-off evidence.
    """
    m = _STA_BASIS_STAMP_RE.search(text or "")
    if m and m.group(1).upper().startswith("PRE_LAYOUT"):
        return BASIS_PRE_LAYOUT
    return BASIS_SIGNOFF


# ── slack extraction ───────────────────────────────────────────────────────
def extract_slacks(text: str) -> Dict[str, Optional[float]]:
    """Worst SETUP slack, worst HOLD slack and TNS from an OpenSTA report body.

    Setup is the `max` (late) analysis and hold the `min` (early) one, per
    OpenSTA convention. An UNLABELLED `wns`/`tns` is attributed to setup (the
    `report_checks` default is the max path) unless an enclosing HOLD section
    says otherwise — hold is then left None, which is honest: a report that
    never labelled a min analysis did not report hold, and the rules say so
    rather than inventing a number.

    An axis whose authoritative `worst slack` line is the NO-PATHS sentinel
    (`INF`) analysed nothing, so its non-negative `wns`/`tns` summary lines are
    withheld rather than returned as a met 0.000 ns — see
    `_WORST_SLACK_NO_PATH_RE`. A NEGATIVE summary value is never withheld: it
    cannot be an echo of infinity, and a completeness gate must not suppress
    evidence of a violation. The return shape is unchanged (three
    Optional[float] fields) because callers iterate `.values()` numerically."""
    section: Optional[str] = None
    # Accumulate per SECTION and resolve at the END. Two reasons the resolution
    # cannot be done inline: OpenSTA prints the `wns`/`tns` summary lines BEFORE
    # the `worst slack` line they derive from, so vacuity is not yet known when
    # a summary is read; and vacuity is a property of ONE section, not of the
    # body — a report can carry an empty section beside a real one, and the
    # empty section's 0.00 must not drag down the corner that did analyse
    # paths. A body with no banners is simply one section.
    b_ws: List[Dict[str, List[float]]] = []    # `worst slack` lines, per block
    b_wns: List[Dict[str, List[float]]] = []   # `wns` summary lines, per block
    b_tns: List[Dict[str, List[float]]] = []
    b_np: List[Dict[str, bool]] = []           # no-paths sentinel seen, per axis

    def _open_block() -> None:
        b_ws.append({"max": [], "min": []})
        b_wns.append({"max": [], "min": []})
        b_tns.append({"max": [], "min": []})
        b_np.append({"max": False, "min": False})

    _open_block()

    for raw in text.splitlines():
        line = raw.strip()

        msec = _SECTION_RE.search(line)
        if msec:
            section = msec.group(1).upper()
            _open_block()
            continue

        mnp = _WORST_SLACK_NO_PATH_RE.search(line)
        if mnp:
            b_np[-1][mnp.group(1).lower()] = True
            continue

        mws = _WORST_SLACK_RE.search(line)
        if mws:
            b_ws[-1][mws.group(1).lower()].append(float(mws.group(2)))
            continue

        mwns = _WNS_RE.search(line)
        if mwns:
            mode = (mwns.group(1) or "").lower()
            if not mode:
                mode = "min" if section == "HOLD" else "max"
            b_wns[-1][mode].append(float(mwns.group(2)))
            continue

        mtns = _TNS_RE.search(line)
        if mtns:
            mode = (mtns.group(1) or "").lower()
            if not mode:
                mode = "min" if section == "HOLD" else "max"
            b_tns[-1][mode].append(float(mtns.group(2)))

    pool: Dict[str, List[float]] = {"max": [], "min": []}
    tns_pool: List[float] = []
    for ws, wns, tns_v, no_path in zip(b_ws, b_wns, b_tns, b_np):
        for axis in ("max", "min"):
            # Vacuous: this section declared the axis had no paths and produced
            # no finite worst slack of its own. Its NON-NEGATIVE summaries are
            # the arithmetic echo of the empty path set and are dropped; a
            # NEGATIVE one is kept, because it cannot be an echo of infinity
            # and a completeness gate must not suppress a violation.
            vacuous = no_path[axis] and not ws[axis]
            keep_wns = ([v for v in wns[axis] if v < 0] if vacuous
                        else wns[axis])
            keep_tns = ([v for v in tns_v[axis] if v < 0] if vacuous
                        else tns_v[axis])
            pool[axis].extend(ws[axis])
            pool[axis].extend(keep_wns)
            tns_pool.extend(keep_tns)

    return {"setup_wns_ns": min(pool["max"]) if pool["max"] else None,
            "hold_wns_ns": min(pool["min"]) if pool["min"] else None,
            "tns_ns": min(tns_pool) if tns_pool else None}


def _row_instance(line: str) -> str:
    """The INSTANCE a DRV row belongs to.

    OpenSTA prints `<instance>/<pin>` in the first column:

        _07014_/A2                              1.50   27.34  -25.84 (VIOLATED)

    Hierarchical names contain `/` too, so the PIN is the last segment and the
    instance is everything before it. Returns "" when the row has no leading
    identifier, which is not the same as an instance named "".
    """
    tok = line.split()[0] if line.split() else ""
    if "/" not in tok:
        return ""
    return tok.rsplit("/", 1)[0]


def spare_instances(project: Path) -> Optional[Set[str]]:
    """Instance names the SPARE-CELL producer recorded, or None if it recorded
    nothing here.

    THE PRODUCER ALREADY KNOWS (vibe-ic#582). `_build_spare_postfix_tcl`
    (#563 r2) deliberately ties every unconnected spare INPUT to one
    `spare_tielo` net, because floating spare inputs make netgen wire their
    pins to a neighbour's pseudo-net and LVS mismatches. That is correct and
    must not be undone — but it puts every spare input on ONE net, and a net
    with hundreds of sinks has an enormous transition, so those pins land in
    the max-slew table as if they were design violations.

    Read from `spare_cells.json` rather than re-derived: the producer states
    `tied_off` and lists every instance, so no name heuristic is needed. A
    `spare_`-prefix rule would be exactly the keyword an differently-named pool
    escapes, and this repo has removed several of those.

    None means "no spare record here" — NOT "no spare cells". The caller must
    not report an attribution it could not compute.
    """
    for cand in (project / "phase3" / "stage3" / "pnr" / "spare_cells.json",
                 project / "reports" / "phase3" / "spare_cells.json"):
        if not cand.is_file():
            continue
        try:
            d = json.loads(cand.read_text(errors="replace"))
        except (OSError, ValueError):
            return None
        if not d.get("tied_off"):
            # Not tied off -> its inputs are floating, not sinks on one net,
            # and none of this applies.
            return set()
        return {i.get("name") for i in (d.get("instances") or [])
                if i.get("name")}
    return None


def attribute_drv(rows: Dict[str, List[str]],
                  spares: Optional[Set[str]]) -> Dict[str, object]:
    """Split a DRV row population into design rows and tie-off rows.

    DISCLOSED, NEVER SUBTRACTED. A DC-constant net's slew is meaningless, but a
    total that quietly shrinks is the defect this repo keeps removing; both
    numbers are published and their sum is still the total.
    """
    if spares is None:
        return {"attributed": False,
                "reason": "no spare_cells.json under this project"}
    per_kind = {}
    d_tot = s_tot = 0
    for kind, insts in rows.items():
        s_n = sum(1 for i in insts if i in spares)
        per_kind[kind] = {"design": len(insts) - s_n, "constant_net": s_n}
        d_tot += len(insts) - s_n
        s_tot += s_n
    return {"attributed": True, "per_kind": per_kind,
            "design": d_tot, "constant_net": s_tot, "total": d_tot + s_tot}


def extract_drv(text: str) -> Dict[str, object]:
    """DRV evidence from one STA report body: was OpenSTA ASKED for max_slew /
    max_capacitance / max_fanout, and what did it answer?

    Returns `queried` (the check-types marker, or a real DRV table, is present),
    `violations` (per-kind counts) and `total`. `queried` False means the run
    never asked — which this gate treats as a failure, not as a clean result,
    because an unqueried limit and a met limit look identical downstream."""
    counts: Dict[str, int] = {}
    #: kind -> the INSTANCE each violating row belongs to, so a total can be
    #: attributed instead of only sized (vibe-ic#582).
    rows: Dict[str, List[str]] = {}
    queried = False
    query_error: Optional[str] = None
    kinds_seen: List[str] = []
    # Explicit 3-state walk (IDLE -> HEADER -> ROWS) rather than "am I under a
    # title": `report_check_types` prints SEVERAL tables back to back, so an
    # open-ended table would keep counting rows belonging to the NEXT one (the
    # `Group Slack` / `Required Width` tables OpenSTA emits alongside). A table
    # ends at the first NON-BLANK line carrying no digit, which is where the
    # next title begins. Blank lines are interior to a table (OpenSTA separates
    # `max capacitance` rows with them) and only suspend it — see the
    # ROWS_BLANK branch below.
    kind: Optional[str] = None
    state = "IDLE"

    for raw in text.splitlines():
        line = raw.strip()

        mok = _CHECK_TYPES_OK_RE.search(line)
        if mok:
            queried = True
            # The marker names the check types the emitter asked for.
            for token, canon in _DRV_KINDS.items():
                if token.replace(" ", "_") in mok.group(1).lower() \
                        and canon not in kinds_seen:
                    kinds_seen.append(canon)
            continue
        merr = _CHECK_TYPES_FAIL_RE.search(line)
        if merr:
            query_error = merr.group(1).strip()
            continue

        # A new === SETUP/HOLD === banner ends any open table.
        if _SECTION_RE.search(line):
            kind, state = None, "IDLE"
            continue

        mt = _DRV_TITLE_RE.match(line)
        if mt:
            kind = _DRV_KINDS[re.sub(r"\s+", " ", mt.group(1).strip().lower())]
            queried = True
            state = "HEADER"
            if kind not in kinds_seen:
                kinds_seen.append(kind)
            counts.setdefault(kind, 0)
            continue
        if _OTHER_TITLE_RE.match(line):
            kind, state = None, "IDLE"
            continue
        if kind is None or state == "IDLE":
            continue

        dashes = bool(line) and set(line) <= set("-=")
        if state == "HEADER":
            # The dashed rule under the column header opens the data rows; a
            # tagged violator opens them too, for builds that print no rule.
            if dashes or _VIOLATED_RE.search(line):
                state = "ROWS"
            if not _VIOLATED_RE.search(line):
                continue
        elif dashes:
            continue

        # state == ROWS: the table ends at the first line with no digit in it.
        #
        # ...but a BLANK line is NOT that terminator, and treating it as one
        # under-counted a whole check kind. MEASURED on caravel_user_project x
        # sky130A (bit-identical routes on two hosts, plugin v1.10.18): OpenSTA
        # prints the `max capacitance` table with a blank line BETWEEN EVERY
        # ROW, while `max slew` and `max fanout` print theirs contiguously. The
        # walk therefore closed the cap table after its FIRST row in each
        # corner, and a sign-off report holding 48 VIOLATED capacitance rows
        # (24 setup + 24 hold) was recorded as `max_capacitance x2`. A 24x
        # under-count, in the LENIENT direction — the record understated the
        # design's own sign-off DRV population.
        #
        # A blank therefore only SUSPENDS the table; the next line decides.
        # Every real terminator (a DRV title, a non-DRV title, an
        # `=== SECTION ===` banner, the check-types markers) is consumed
        # earlier in this loop, so each still closes or re-opens a table
        # exactly as it did before — this can only stop the walk from ending
        # a table early, never keep one open across a title.
        if not line:
            state = "ROWS_BLANK"
            continue
        if not any(ch.isdigit() for ch in line):
            kind, state = None, "IDLE"
            continue
        if state == "ROWS_BLANK":
            state = "ROWS"
        if _VIOLATED_RE.search(line):
            counts[kind] = counts.get(kind, 0) + 1
            rows.setdefault(kind, []).append(_row_instance(line))
            continue
        mneg = _TRAILING_NEG_RE.search(line)
        # Only a data row (a name followed by numbers) counts, never the title
        # underline or a stray negative in prose.
        if mneg and len(line.split()) >= 3:
            counts[kind] = counts.get(kind, 0) + 1
            rows.setdefault(kind, []).append(_row_instance(line))

    violations = {k: v for k, v in counts.items() if v > 0}
    _rows = {k: v for k, v in rows.items() if v}
    # vibe-ic#573 — a check type the run ASKED FOR whose table never appeared.
    #
    # `kinds_seen` is what the emitter's marker says was queried; `counts` gets a
    # key only when a table with that title is actually PRINTED. The difference is
    # a check that was requested and produced no table at all, which is NOT the
    # same fact as a table with zero violator rows:
    #
    #   table present, no rows   the check ran over a real population and found
    #                            nothing  ->  a genuine zero
    #   no table at all          the check had nothing to report ON  ->  UNMEASURED
    #
    # Measured on caravel_user_project x sky130A: `set_max_fanout 16` IS declared
    # in the sign-off SDC, and `report_check_types -max_fanout -violators` prints
    # no fanout table whatsoever, because OpenSTA excludes constant-driven pins
    # (`CheckFanouts::checkPin` -> `!sim()->isConstant(pin)`) and every tie cell
    # present at link time is one. The design's tie-off net carries 30 loads
    # against that limit of 16 and is silently outside the check.
    #
    # The pre-existing `SIGNOFF_MAX_FANOUT_SEMANTICS` note covers only the case
    # where the SDC declares NO limit. This is the other one: a limit IS declared
    # and the table is still empty by construction, which that note cannot
    # distinguish and a reader would take for a clean result.
    silent = [k for k in kinds_seen if k not in counts]
    return {
        "queried": queried,
        "query_error": query_error,
        "kinds_queried": kinds_seen,
        "kinds_without_table": silent,
        "violations": violations,
        "total": sum(violations.values()),
        # The INSTANCE each violating row belongs to, so a caller can attribute
        # the total rather than only size it (vibe-ic#582). Kept out of the
        # count so no existing consumer changes.
        "rows": _rows,
    }


def extract_corner_libraries(text: str) -> Dict[str, str]:
    """{corner: liberty path} recorded in an STA report — from the
    `# corner_liberty:` header lines and from any `liberty=` in a section
    banner. Empty when the report carries no such record (which R4 treats as
    unrecorded, not as resolved)."""
    out: Dict[str, str] = {}
    for m in _CORNER_LIBERTY_RE.finditer(text):
        out.setdefault(m.group(1).strip().lower(), m.group(2).strip())
    for raw in text.splitlines():
        line = raw.strip()
        if not _SECTION_RE.search(line):
            continue
        mlib = _SECTION_LIBERTY_RE.search(line)
        if not mlib:
            continue
        mproc = _SECTION_PROCESS_RE.search(line)
        mrc = re.search(r"\(\s*([\w.+-]+?)(?:-RC)?\s+corner", line, re.I)
        name = (mproc.group(2) if mproc else
                mrc.group(1) if mrc else None)
        if name:
            out.setdefault(name.strip().lower(), mlib.group(1).strip())
    return out


def _split_sections(text: str) -> List[Tuple[str, Optional[str], str]]:
    """Split a sectioned STA report into (kind, corner_or_None, body) chunks.
    `kind` is SETUP/HOLD; `corner` is the process corner when the section header
    names one (`process=SS`), else None."""
    out: List[Tuple[str, Optional[str], str]] = []
    kind: Optional[str] = None
    corner: Optional[str] = None
    buf: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        msec = _SECTION_RE.search(line)
        if msec:
            if kind is not None:
                out.append((kind, corner, "\n".join(buf)))
            kind = msec.group(1).upper()
            mproc = _SECTION_PROCESS_RE.search(line)
            corner = mproc.group(2) if mproc else None
            buf = []
            continue
        if kind is not None:
            buf.append(line)
    if kind is not None:
        out.append((kind, corner, "\n".join(buf)))
    return out


# ── declaration discovery ──────────────────────────────────────────────────
def read_declarations(project: Path) -> Dict[str, object]:
    """Collect every (axis, corner, role) the flow DECLARED it would analyse,
    plus the availability lists and the declared nominal corner. All read from
    the run's own artifacts — nothing is assumed about corner naming."""
    declared: List[Dict[str, str]] = []      # {axis, corner, role, source}
    available: List[Dict[str, str]] = []     # {axis, corner, source}
    aliases: Dict[Tuple[str, str], List[str]] = {}   # (axis, corner) -> names
    sources: Dict[str, Optional[str]] = {}
    primary: Optional[Dict[str, str]] = None

    # -- PROCESS axis: mcorner_ocv_stance.json names setup/hold process corners
    p_stance_path = _first_existing(project, _PROCESS_STANCE_CANDIDATES)
    p_stance = _load_json(p_stance_path)
    sources["process_stance"] = (_rel(project, p_stance_path)
                                 if p_stance_path else None)
    if p_stance:
        src = sources["process_stance"] or ""
        for field, role in (("setup_process_corner", "setup"),
                            ("hold_process_corner", "hold")):
            val = p_stance.get(field)
            if isinstance(val, str) and val.strip():
                declared.append({"axis": AXIS_PROCESS, "corner": val.strip(),
                                 "role": role, "source": src})

    # -- RC axis: multi_corner_spef_stance.json, else the report header
    rc_stance_path = _first_existing(project, _RC_STANCE_CANDIDATES)
    rc_stance = _load_json(rc_stance_path)
    sources["rc_stance"] = (_rel(project, rc_stance_path)
                            if rc_stance_path else None)
    rc_declared_any = False
    if rc_stance:
        src = sources["rc_stance"] or ""
        for field, role in (("setup_corner", "setup"),
                            ("hold_corner", "hold")):
            val = rc_stance.get(field)
            if isinstance(val, str) and val.strip():
                declared.append({"axis": AXIS_RC, "corner": val.strip(),
                                 "role": role, "source": src})
                rc_declared_any = True
        extracted = rc_stance.get("corners_extracted")
        if isinstance(extracted, list):
            for c in extracted:
                if isinstance(c, str) and c.strip():
                    available.append({"axis": AXIS_RC, "corner": c.strip(),
                                      "source": src})

    mc_path = _first_existing(project, _MULTICORNER_CANDIDATES)
    sources["multicorner_report"] = _rel(project, mc_path) if mc_path else None
    if mc_path is not None:
        try:
            head = mc_path.read_text(errors="replace")
        except OSError:
            head = ""
        for raw in head.splitlines():
            line = raw.strip()
            mso = _SIGNOFF_HEADER_RE.search(line)
            if mso and not rc_declared_any:
                src = sources["multicorner_report"] or ""
                declared.append({"axis": AXIS_RC, "corner": mso.group(1).strip(),
                                 "role": "setup", "source": src})
                declared.append({"axis": AXIS_RC, "corner": mso.group(2).strip(),
                                 "role": "hold", "source": src})
                rc_declared_any = True
            mav = _CORNERS_AVAIL_RE.search(line)
            if mav:
                src = sources["multicorner_report"] or ""
                for c in mav.group(1).split(","):
                    if c.strip():
                        available.append({"axis": AXIS_RC, "corner": c.strip(),
                                          "source": src})

    # -- NOMINAL + the process availability matrix: pvt_matrix.json
    pvt_path = _first_existing(project, _PVT_CANDIDATES)
    pvt = _load_json(pvt_path)
    sources["pvt_matrix"] = _rel(project, pvt_path) if pvt_path else None
    labels: Dict[str, str] = {}
    if pvt:
        src = sources["pvt_matrix"] or ""
        prim = pvt.get("primary_corner")
        if isinstance(prim, str) and prim.strip():
            primary = {"axis": AXIS_PROCESS, "corner": prim.strip(),
                       "source": src}
        corners = pvt.get("corners")
        if isinstance(corners, list):
            for c in corners:
                if isinstance(c, dict):
                    name = c.get("name")
                    label = c.get("label")
                    if isinstance(name, str) and name.strip():
                        # The matrix names each corner by its full Liberty stem
                        # while the sign-off stance and the report headers speak
                        # in LABELS (SS/TT/FF). Register availability under the
                        # label when one exists — carrying the Liberty stem as an
                        # alias — so the two vocabularies denote ONE corner row
                        # instead of two half-empty ones.
                        if isinstance(label, str) and label.strip():
                            lbl = label.strip()
                            labels[lbl.lower()] = lbl
                            aliases.setdefault(
                                _key(AXIS_PROCESS, lbl), []).append(name.strip())
                            available.append({"axis": AXIS_PROCESS,
                                              "corner": lbl, "source": src})
                        else:
                            available.append({"axis": AXIS_PROCESS,
                                              "corner": name.strip(),
                                              "source": src})
                elif isinstance(c, str) and c.strip():
                    available.append({"axis": AXIS_PROCESS, "corner": c.strip(),
                                      "source": src})

    # -- citations: an STA artifact naming the report its numbers came from.
    dangling: List[Dict[str, str]] = []
    for rel, field in _CITING_ARTIFACTS:
        art = project / rel
        if not art.is_file():
            continue
        data = _load_json(art)
        if not data:
            continue
        cited = data.get(field)
        if not isinstance(cited, str) or not cited.strip():
            continue
        target = Path(cited)
        if not target.is_absolute():
            target = project / cited
        if not target.is_file():
            dangling.append({"citing_artifact": rel, "cited_report": cited})

    return {
        "declared": declared, "available": available, "primary": primary,
        "labels": labels, "aliases": aliases, "sources": sources,
        "dangling_citations": dangling,
    }


# ── record discovery ───────────────────────────────────────────────────────
def read_records(project: Path,
                 decl: Dict[str, object]) -> Dict[Tuple[str, str], Dict[str, object]]:
    """Every per-corner timing datapoint the run actually produced, keyed by
    (axis, corner)."""
    recs: Dict[Tuple[str, str], Dict[str, object]] = {}

    def _put(axis: str, corner: str, source: str,
             vals: Dict[str, Optional[float]],
             basis: str = BASIS_SIGNOFF) -> None:
        """Record one report's datapoints for (axis, corner), KEEPING BASIS.

        Datapoints are pooled PER BASIS rather than merged across bases. A
        pre-layout estimate and a post-route measurement of the SAME corner are
        two measurements of two different things, and `min()` across them
        reports the pre-layout number as the corner's sign-off slack — which is
        wrong by as much as the resizer is effective (measured: 100x on a
        two-report fixture). Resolution happens once, in `_resolve`, after every
        source has been read.
        """
        k = _key(axis, corner)
        rec = recs.setdefault(k, {"corner": corner, "axis": axis,
                                  "setup_wns_ns": None, "hold_wns_ns": None,
                                  "tns_ns": None, "source": source,
                                  "_pool": {}, "_src": {}})
        pool = rec["_pool"].setdefault(basis, {})           # type: ignore[index]
        for f in ("setup_wns_ns", "hold_wns_ns", "tns_ns"):
            pool[f] = _merge_slack(pool.get(f), vals.get(f))
        srcs = rec["_src"].setdefault(basis, [])            # type: ignore[index]
        if source not in srcs:
            srcs.append(source)
        if source not in str(rec["source"]).split(", "):
            rec["source"] = f"{rec['source']}, {source}"

    def _resolve() -> None:
        """Collapse the per-basis pools onto the row the rules read.

        SIGN-OFF basis wins PER FIELD when it has a value; a field the sign-off
        reports do not carry falls back to the pre-layout pool UNCHANGED, so a
        project with only pre-layout evidence keeps exactly today's numbers and
        today's verdict. Superseded pre-layout values are retained on the row
        for disclosure, never discarded silently.
        """
        for rec in recs.values():
            pools = rec["_pool"]                             # type: ignore[index]
            signoff = pools.get(BASIS_SIGNOFF, {})
            prelay = pools.get(BASIS_PRE_LAYOUT, {})
            used, superseded = {}, {}
            for f in ("setup_wns_ns", "hold_wns_ns", "tns_ns"):
                if signoff.get(f) is not None:
                    rec[f] = signoff[f]
                    used[f] = BASIS_SIGNOFF
                    if prelay.get(f) is not None:
                        superseded[f] = prelay[f]
                else:
                    rec[f] = prelay.get(f)
                    if rec[f] is not None:
                        used[f] = BASIS_PRE_LAYOUT
            rec["basis_used"] = used
            if superseded:
                rec["pre_layout_superseded_ns"] = superseded
                rec["pre_layout_sources"] = list(
                    rec["_src"].get(BASIS_PRE_LAYOUT, []))   # type: ignore[index]
            del rec["_pool"], rec["_src"]

    declared = decl.get("declared") or []
    rc_role_corner = {d["role"]: d["corner"] for d in declared  # type: ignore[index]
                      if d["axis"] == AXIS_RC}                  # type: ignore[index]
    proc_role_corner = {d["role"]: d["corner"] for d in declared  # type: ignore[index]
                        if d["axis"] == AXIS_PROCESS}            # type: ignore[index]

    # -- multicorner SPEF report (RC axis): sections carry the roles
    mc = _first_existing(project, _MULTICORNER_CANDIDATES)
    if mc is not None:
        try:
            text = mc.read_text(errors="replace")
        except OSError:
            text = ""
        src = _rel(project, mc)
        for kind, _corner, body in _split_sections(text):
            role = "setup" if kind == "SETUP" else "hold"
            corner = rc_role_corner.get(role)
            if corner is None:
                corner = kind.lower()
            vals = extract_slacks(body)
            # A SETUP section contributes the setup datapoint only, and a HOLD
            # section the hold datapoint only; TNS travels with its section.
            _put(AXIS_RC, corner, src, {
                "setup_wns_ns": vals["setup_wns_ns"] if role == "setup" else None,
                "hold_wns_ns": vals["hold_wns_ns"] if role == "hold" else None,
                "tns_ns": vals["tns_ns"],
            }, report_basis(text))

    # -- multi-corner OCV report (PROCESS axis): headers name the process corner
    ocv = _first_existing(project, _MCORNER_OCV_CANDIDATES)
    if ocv is not None:
        try:
            text = ocv.read_text(errors="replace")
        except OSError:
            text = ""
        src = _rel(project, ocv)
        for kind, corner, body in _split_sections(text):
            role = "setup" if kind == "SETUP" else "hold"
            name = corner or proc_role_corner.get(role) or kind.lower()
            vals = extract_slacks(body)
            _put(AXIS_PROCESS, name, src, {
                "setup_wns_ns": vals["setup_wns_ns"] if role == "setup" else None,
                "hold_wns_ns": vals["hold_wns_ns"] if role == "hold" else None,
                "tns_ns": vals["tns_ns"],
            }, report_basis(text))

    # -- per-corner sweep (PROCESS axis): one report per corner, name in filename
    for rel in _PER_CORNER_DIRS:
        pc_dir = project / rel
        if not pc_dir.is_dir():
            continue
        for rpt in sorted(pc_dir.glob("sta_*.rpt")):
            m = _PER_CORNER_RPT_RE.match(rpt.name)
            if not m:
                continue
            try:
                body = rpt.read_text(errors="replace")
            except OSError:
                body = ""
            _put(AXIS_PROCESS, m.group(1), _rel(project, rpt),
                 extract_slacks(body), report_basis(body))

    # -- nominal single-corner SPEF report: the typ datapoint. Named from the
    #    flow's own RC availability list (the extracted corner that was NOT
    #    assigned the setup or hold role); falls back to a descriptive label
    #    rather than guessing a corner name.
    nom = _first_existing(project, _NOMINAL_SPEF_CANDIDATES)
    if nom is not None:
        avail_rc = [a["corner"] for a in (decl.get("available") or [])  # type: ignore[index]
                    if a["axis"] == AXIS_RC]                            # type: ignore[index]
        roled = {str(c).strip().lower() for c in rc_role_corner.values()}
        leftover = [c for c in dict.fromkeys(avail_rc)
                    if str(c).strip().lower() not in roled]
        name = leftover[0] if len(leftover) == 1 else "nominal"
        try:
            body = nom.read_text(errors="replace")
        except OSError:
            body = ""
        _put(AXIS_RC, name, _rel(project, nom), extract_slacks(body),
             report_basis(body))

    _resolve()
    return recs


# ── per-axis evidence: library resolution (R4) + DRV (R5) ──────────────────
_AXIS_ARTIFACTS = (
    (AXIS_RC, _MULTICORNER_CANDIDATES, _RC_STANCE_CANDIDATES,
     ("multi_corner",)),
    (AXIS_PROCESS, _MCORNER_OCV_CANDIDATES, _PROCESS_STANCE_CANDIDATES,
     ("multi_process_corner",)),
)


def _drv_with_attribution(project: Path, text: str):
    """`extract_drv` plus the tie-off split, attached where it is EMITTED.

    #582 landed `attribute_drv` and never called it. The capability existed and
    no artefact carried the answer — a gate can be perfectly correct and wired
    into a place where it answers nothing. The issue's acceptance asks for the
    excluded count "reported separately and visibly in the SAME artefact", and
    that is this dict, which is what the report writes out.

    NOTHING IS SUBTRACTED: `total` and `violations` are byte-identical to what
    they were, and `attribution.total` is asserted to equal `total`.
    """
    if not text:
        return None
    drv = extract_drv(text)
    rows = drv.get("rows") or {}
    drv["attribution"] = attribute_drv(rows, spare_instances(project))
    return drv


def read_axis_evidence(project: Path,
                       decl: Dict[str, object]) -> List[Dict[str, object]]:
    """For each sign-off axis that produced a report: the multi-corner CLAIM it
    makes, how each reported corner resolved to a LIBERTY, and the DRV evidence.

    The stance JSON's `corner_library_resolution` block is authoritative when
    present; otherwise the record is recovered from the report itself. Nothing
    is inferred from a corner NAME — a corner called `ss` proves nothing about
    which file was read, and believing the name is how this defect survived."""
    out: List[Dict[str, object]] = []
    declared: List[Dict[str, str]] = decl.get("declared") or []  # type: ignore[assignment]

    for axis, rpt_cands, stance_cands, claim_fields in _AXIS_ARTIFACTS:
        rpt = _first_existing(project, rpt_cands)
        stance_path = _first_existing(project, stance_cands)
        stance = _load_json(stance_path)
        if rpt is None and stance is None:
            continue
        try:
            text = rpt.read_text(errors="replace") if rpt is not None else ""
        except OSError:
            text = ""

        # -- the multi-corner CLAIM this axis makes ------------------------
        claim = False
        claim_src: Optional[str] = None
        for f in claim_fields:
            if stance and stance.get(f) is True:
                claim, claim_src = True, f"{_rel(project, stance_path)}:{f}"
                break
        axis_roles = {d["corner"].strip().lower() for d in declared
                      if d["axis"] == axis}
        if not claim and len(axis_roles) >= 2 and text:
            claim = True
            claim_src = (f"{len(axis_roles)} distinct sign-off corners declared "
                         f"on the {axis} axis")

        # -- how each reported corner resolved to a liberty -----------------
        block = stance.get(_LIB_RESOLUTION_FIELD) if stance else None
        lib_by_corner: Dict[str, str] = {}
        unresolved: List[str] = []
        unresolved_reason: Optional[str] = None
        res_src: Optional[str] = None
        if isinstance(block, dict):
            raw = block.get("liberty_by_corner")
            if isinstance(raw, dict):
                lib_by_corner = {str(k).strip().lower(): str(v)
                                 for k, v in raw.items() if v}
            raw_u = block.get("unresolved_corners")
            if isinstance(raw_u, list):
                unresolved = [str(c) for c in raw_u if c]
            ru = block.get("unresolved_reason")
            unresolved_reason = str(ru) if ru else None
            res_src = f"{_rel(project, stance_path)}:{_LIB_RESOLUTION_FIELD}"
        if not lib_by_corner and text:
            lib_by_corner = extract_corner_libraries(text)
            if lib_by_corner:
                res_src = _rel(project, rpt) if rpt else None

        distinct = sorted({v for v in lib_by_corner.values()})
        groups: Dict[str, List[str]] = {}
        for corner, lib in sorted(lib_by_corner.items()):
            groups.setdefault(lib, []).append(corner)
        collapsed = [{"liberty": lib, "corners": cs}
                     for lib, cs in sorted(groups.items()) if len(cs) > 1]

        # Did the flow record that it KNOWS the resolution collapsed? A collapse
        # the run states about itself is a disclosure; one only the gate can see
        # is the silence this rule exists to break.
        collapse_disclosed = bool(
            isinstance(block, dict) and (block.get("collapsed") is True
                                         or block.get("degradation_disclosure")))

        out.append({
            "axis": axis,
            "report": _rel(project, rpt) if rpt is not None else None,
            "multi_corner_claim": claim,
            "claim_source": claim_src,
            "collapse_disclosed": collapse_disclosed,
            "degradation_disclosure": (
                str(block.get("degradation_disclosure"))
                if isinstance(block, dict) and block.get("degradation_disclosure")
                else None),
            "liberty_by_corner": lib_by_corner,
            "distinct_library_count": len(distinct),
            "reported_corner_count": len(lib_by_corner),
            "collapsed_groups": collapsed,
            "unresolved_corners": unresolved,
            "unresolved_reason": unresolved_reason,
            "resolution_source": res_src,
            "resolution_recorded": bool(lib_by_corner),
            "drv": _drv_with_attribution(project, text),
        })
    return out


# ── evaluation ─────────────────────────────────────────────────────────────
def evaluate(project: Path,
             slack_tol: float = _DEFAULT_SLACK_TOL_NS) -> Dict[str, object]:
    """Pure evaluator over a run dir. ALWAYS returns the full per-corner
    evidence table under `corners`, whatever the verdict."""
    decl = read_declarations(project)
    records = read_records(project, decl)
    axes = read_axis_evidence(project, decl)

    declared: List[Dict[str, str]] = decl.get("declared") or []   # type: ignore[assignment]
    available: List[Dict[str, str]] = decl.get("available") or []  # type: ignore[assignment]
    primary = decl.get("primary")
    labels: Dict[str, str] = decl.get("labels") or {}              # type: ignore[assignment]
    aliases: Dict[Tuple[str, str], List[str]] = decl.get("aliases") or {}  # type: ignore[assignment]

    primary_names = set()
    if isinstance(primary, dict):
        pname = str(primary.get("corner", "")).strip().lower()
        if pname:
            primary_names.add(pname)
            for nm, lb in labels.items():
                if lb.strip().lower() == pname:
                    primary_names.add(nm)

    # Roles per (axis, corner).
    roles: Dict[Tuple[str, str], List[str]] = {}
    decl_src: Dict[Tuple[str, str], str] = {}
    for d in declared:
        k = _key(d["axis"], d["corner"])
        roles.setdefault(k, [])
        if d["role"] not in roles[k]:
            roles[k].append(d["role"])
        decl_src.setdefault(k, d.get("source", ""))

    # Build the union of every corner worth showing.
    all_keys: Dict[Tuple[str, str], str] = {}
    for d in declared:
        all_keys[_key(d["axis"], d["corner"])] = d["corner"]
    for a in available:
        all_keys.setdefault(_key(a["axis"], a["corner"]), a["corner"])
    for k, r in records.items():
        all_keys.setdefault(k, str(r["corner"]))

    findings: List[str] = []
    rules: List[str] = []
    table: List[Dict[str, object]] = []

    for k in sorted(all_keys, key=lambda x: (x[0], x[1])):
        axis, _lower = k
        name = all_keys[k]
        rec = records.get(k)
        corner_roles = roles.get(k, [])
        is_declared = k in roles
        if is_declared:
            role_class = "signoff"
        elif _lower in primary_names and axis == AXIS_PROCESS:
            role_class = "primary"
        elif rec is not None and not corner_roles:
            # Reported but never assigned a role: still evidence. If it is the
            # nominal corner name on the RC axis, call it primary.
            role_class = "primary" if _lower in {"nom", "nominal", "typ", "tt"} \
                else "unroled_reported"
        else:
            role_class = "available_not_selected"

        table.append({
            "corner": name,
            "axis": axis,
            "label": labels.get(_lower),
            "liberty_aliases": aliases.get(k) or [],
            "roles": corner_roles,
            "role_class": role_class,
            "declared": is_declared,
            "reported": rec is not None,
            # Which side of PnR each number came from, and — when a sign-off
            # datapoint superseded a pre-layout one for the same corner — what
            # the pre-layout estimate said. Carried so the correction is
            # DISCLOSED on the artefact rather than applied silently.
            "basis_used": (rec.get("basis_used") or None) if rec else None,
            "pre_layout_superseded_ns": (rec.get("pre_layout_superseded_ns")
                                         or None) if rec else None,
            "setup_wns_ns": rec.get("setup_wns_ns") if rec else None,
            "hold_wns_ns": rec.get("hold_wns_ns") if rec else None,
            "tns_ns": rec.get("tns_ns") if rec else None,
            "source": (rec.get("source") if rec else decl_src.get(k)) or None,
        })

    # ---- a verdict that outlived the report it cites -----------------------
    # This is R2 in its starkest form: the citation proves corners WERE
    # analysed, and the missing target proves nothing survived to substantiate
    # it. Judged BEFORE the not-applicable escape, so a run whose only STA
    # trace is a dangling verdict cannot exit as "nothing to judge".
    dangling: List[Dict[str, str]] = decl.get("dangling_citations") or []  # type: ignore[assignment]
    for dc in dangling:
        rules.append("R2_DECLARED_BUT_UNREPORTED")
        findings.append(
            f"R2 {dc['citing_artifact']} reports STA results but cites "
            f"'{dc['cited_report']}', which does NOT exist — the verdict has "
            f"outlived the evidence it rests on, so its corners are unreported")

    # ---- nothing declared and nothing recorded → say so, invent nothing -----
    if not declared and not records and not dangling:
        return {
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "reasons": ["no_corner_declaration: no stance file, pvt_matrix or "
                        "STA report declares or records any corner — there is "
                        "no timing record to judge (this gate does not invent "
                        "a sign-off corner set)"],
            "corners": table, "primary_corner": primary,
            "declaration_sources": decl.get("sources"),
            "axis_evidence": axes,
            "slack_tol_ns": slack_tol, "rules_violated": [],
        }

    # ---- R2: every declared (corner, role) needs that role's datapoint -----
    for k, corner_roles in sorted(roles.items()):
        axis, _lower = k
        name = all_keys.get(k, k[1])
        rec = records.get(k)
        for role in corner_roles:
            field = "setup_wns_ns" if role == "setup" else "hold_wns_ns"
            if rec is None:
                rules.append("R2_DECLARED_BUT_UNREPORTED")
                findings.append(
                    f"R2 sign-off corner '{name}' ({axis} axis, declared as the "
                    f"{role.upper()} corner by {decl_src.get(k) or 'the flow'}) "
                    f"has NO timing datapoint anywhere in the record — an "
                    f"unreported corner is indistinguishable from a met one")
            elif rec.get(field) is None:
                rules.append("R2_DECLARED_BUT_UNREPORTED")
                findings.append(
                    f"R2 sign-off corner '{name}' ({axis} axis) was declared as "
                    f"the {role.upper()} corner but its record carries no worst "
                    f"{role} slack (source: {rec.get('source')})")

    # ---- R1: reported corners must be named + complete when unroled --------
    for row in table:
        if not row.get("reported"):
            continue
        if not str(row.get("corner") or "").strip():
            rules.append("R1_INCOMPLETE_CORNER_RECORD")
            findings.append(
                f"R1 a timing datapoint in {row.get('source')} is not "
                f"identified by corner name")
            continue
        if row.get("roles"):
            continue  # judged by R2 against its declared role(s)
        if row.get("role_class") == "primary":
            # The nominal/typ corner carries NO sign-off role: setup is signed
            # off at the slow corner and hold at the fast one, so the nominal
            # single-corner report legitimately reports setup only. Demanding
            # hold from it would be a FABRICATED violation — it would fail every
            # run in the corpus including the genuinely clean ones. The nominal
            # datapoint is still shown in the evidence table, and R3 still uses
            # it to expose the typ-MET-while-signoff-VIOLATED misleading pass.
            continue
        missing = [k for k in ("setup_wns_ns", "hold_wns_ns")
                   if row.get(k) is None]
        if missing:
            rules.append("R1_INCOMPLETE_CORNER_RECORD")
            pretty = " and ".join(
                {"setup_wns_ns": "setup", "hold_wns_ns": "hold"}[m]
                for m in missing)
            findings.append(
                f"R1 corner '{row['corner']}' ({row['axis']} axis) ran and is "
                f"reported but carries no declared sign-off role and omits "
                f"worst {pretty} slack — an incomplete corner characterisation "
                f"(source: {row.get('source')})")

    # ---- R3: a violated sign-off ROLE governs, whatever typ says -----------
    typ_met: List[str] = []
    signoff_violated: List[str] = []
    for row in table:
        if not row.get("reported"):
            continue
        vals = [float(row[f]) for f in ("setup_wns_ns", "hold_wns_ns")   # type: ignore[arg-type]
                if row.get(f) is not None]
        if not vals:
            continue
        worst = min(vals)
        if row.get("role_class") == "primary" and worst >= -slack_tol:
            typ_met.append(f"{row['corner']} ({row['axis']})")
        if row.get("role_class") != "signoff":
            continue

        # A row may carry more than the sign-off datapoint it was declared to
        # serve. In particular, the per-corner sweep can contribute a
        # PRE_LAYOUT setup estimate to the fast/hold row while the OCV report
        # contributes its SIGNOFF hold result. Both numbers belong in the
        # evidence table, but only the declared role is a sign-off verdict.
        # Taking min(setup, hold) here made an unrelated pre-layout setup miss
        # manufacture a post-route HOLD-corner violation. R2 immediately above
        # already requires each declared role's own datapoint to exist, so R3
        # projects the row onto exactly those declared roles and no others.
        role_fields = [
            ("setup_wns_ns", "setup")
            for role in (row.get("roles") or []) if role == "setup"
        ] + [
            ("hold_wns_ns", "hold")
            for role in (row.get("roles") or []) if role == "hold"
        ]
        violated = [
            (field, tag, float(row[field]))
            for field, tag in role_fields
            if row.get(field) is not None and float(row[field]) < -slack_tol
        ]
        if violated:
            rules.append("R3_SIGNOFF_CORNER_VIOLATION")
            signoff_violated.append(str(row["corner"]))
            detail = [f"{tag} {value:+.3f} ns"
                      for _field, tag, value in violated]
            tns_s = ("" if row.get("tns_ns") is None
                     else f", TNS {float(row['tns_ns']):.2f}")   # type: ignore[arg-type]
            findings.append(
                f"R3 SIGN-OFF corner '{row['corner']}' ({row['axis']} axis, "
                f"role {'/'.join(row.get('roles') or []) or 'signoff'}) is "
                f"VIOLATED: {', '.join(detail) or f'{worst:+.3f} ns'}{tns_s} "
                f"(source: {row.get('source')})")

    if signoff_violated and typ_met:
        findings.append(
            f"R3 the primary/typ corner(s) {', '.join(sorted(set(typ_met)))} "
            f"MET while sign-off corner(s) "
            f"{', '.join(sorted(set(signoff_violated)))} VIOLATED — a typ-only "
            f"'MET' is a MISLEADING PASS and does not satisfy this run's timing")

    # ---- R4: a multi-corner claim needs multiple corner LIBRARIES ----------
    # The degradation itself is designed and legitimate; the silence is not.
    # `degraded_disclosed` collects collapses that were honestly recorded and
    # make no multi-corner claim — those set SINGLE_CORNER_ONLY, not FAIL.
    # R4 is judged at RUN level, not per axis. A single-library RC axis is NOT
    # a degradation — the RC axis varies parasitics, and one process library
    # across its corners is correct by design. The degradation is when the RUN
    # AS A WHOLE reports several corners while never analysing more than one
    # distinct library on ANY axis. Judging per axis would label every healthy
    # run degraded, which is the mirror-image of the defect.
    degraded_disclosed: List[str] = []
    claiming = [ax for ax in axes if ax.get("multi_corner_claim")]
    unrecorded = [ax for ax in claiming if not ax.get("resolution_recorded")]
    all_libs = {lib for ax in axes
                for lib in (ax.get("liberty_by_corner") or {}).values()}
    corners_reported = sum(int(ax.get("reported_corner_count") or 0)
                           for ax in axes)

    if claiming and unrecorded:
        rules.append("R4_LIBRARY_RESOLUTION_UNRECORDED")
        for ax in unrecorded:
            findings.append(
                f"R4 the {ax['axis']} axis claims multi-corner sign-off "
                f"({ax['claim_source']}) but "
                f"{ax.get('report') or 'the timing record'} records NO "
                f"corner-to-liberty resolution, so a run that read N distinct "
                f"corner libraries is indistinguishable from one that read the "
                f"SAME library N times — the multi-corner claim is "
                f"UNVERIFIABLE from its own record")
    elif claiming and corners_reported >= 2 and len(all_libs) <= 1:
        # Several corners reported, one library analysed anywhere in the run.
        groups = [g for ax in axes
                  for g in (ax.get("collapsed_groups") or [])]
        detail = "; ".join(
            f"{', '.join(g['corners'])} all resolved to "                # type: ignore[index]
            f"{Path(str(g['liberty'])).name}" for g in groups)           # type: ignore[index]
        why = next((str(ax["unresolved_reason"]) for ax in axes
                    if ax.get("unresolved_reason")), None)
        missing = sorted({str(c) for ax in axes
                          for c in (ax.get("unresolved_corners") or [])})
        why_s = why or "the run records no reason"
        missing_s = (f"; corner libraries that could NOT be resolved: "
                     f"{', '.join(missing)}" if missing else "")
        disclosed = any(ax.get("collapse_disclosed") for ax in axes)
        shared = f" — {detail}" if detail else ""
        if not disclosed:
            rules.append("R4_MULTI_CORNER_CLAIM_UNSUPPORTED")
            findings.append(
                f"R4 the run reports {corners_reported} corners but analysed "
                f"only {len(all_libs)} distinct corner library{shared}, while "
                f"claiming multi-corner sign-off ({claiming[0]['claim_source']}) "
                f"and NOWHERE disclosing the degradation. Reporting "
                f"{corners_reported} corners backed by one library is a FALSE "
                f"CLAIM regardless of intent. Why the others could not be "
                f"resolved: {why_s}{missing_s}")
        else:
            degraded_disclosed.append(
                f"SINGLE-CORNER DEGRADATION: {corners_reported} corners "
                f"reported, {len(all_libs)} distinct corner library analysed "
                f"across every sign-off axis{shared}. Why the others could not "
                f"be resolved: {why_s}{missing_s}. The run DISCLOSES this, and "
                f"a PDK that ships one library cannot do better — so it is not "
                f"a FAIL. But it is NOT multi-corner sign-off and must not be "
                f"read as one: setup and hold were not separated by process, so "
                f"a violation that appears only at an unanalysed corner CANNOT "
                f"be seen in this record")

    # ---- R5: DRV (max_slew / max_capacitance / max_fanout) must be surfaced -
    for ax in axes:
        drv = ax.get("drv")
        if not isinstance(drv, dict) or not ax.get("report"):
            continue
        axis, rpt = str(ax["axis"]), str(ax["report"])
        if not drv.get("queried"):
            rules.append("R5_DRV_UNQUERIED")
            why = (f" (the query errored: {drv['query_error']})"
                   if drv.get("query_error") else
                   " — no report_check_types output and no check-types marker")
            findings.append(
                f"R5 {rpt} ({axis} axis) carries sign-off timing but OpenSTA "
                f"was never asked for DRV (max_slew / max_capacitance / "
                f"max_fanout){why}. An unqueried DRV limit is indistinguishable "
                f"from a met one, so this record cannot show a slew violation "
                f"even if every net has one")
            continue
        # vibe-ic#573 — a check type that was ASKED FOR and printed no table.
        # Reported BEFORE the violation branch because the two are independent:
        # a record can carry real max_slew violations AND a silently absent
        # max_fanout table, and reporting only the former would let the reader
        # conclude the rest was checked and clean.
        #
        # DISCLOSED, NOT BLOCKING, and that is a deliberate split rather than
        # timidity. The cause is in OpenSTA (`CheckFanouts::checkPin` excludes
        # constant-driven pins, and every tie cell linked in from disk is one), so
        # EVERY design with a tie-off would fail this the moment it blocked —
        # which is a gate people switch off, not a gate that gets answered. The
        # fix belongs in the fork; until it lands, the honest record is that the
        # limit was declared, the check was requested, and nothing was measured.
        silent = drv.get("kinds_without_table") or []
        if silent:
            rules.append("R5_DRV_KIND_UNMEASURED")
            findings.append(
                f"R5 {rpt} ({axis} axis) requested {', '.join(sorted(silent))} "
                f"and OpenSTA printed no table for it. An ABSENT table is not a "
                f"table with zero rows: the check reported on nothing, so this "
                f"record cannot show a violation of that kind even if the design "
                f"has one. On max_fanout this is reproducible — a declared "
                f"set_max_fanout with every tie cell excluded as constant-driven "
                f"(vibe-ic#573). DISCLOSED, not blocking.")

        viol: Dict[str, int] = drv.get("violations") or {}   # type: ignore[assignment]
        if viol:
            rules.append("R5_DRV_VIOLATION")
            pretty = ", ".join(f"{k} x{v}" for k, v in sorted(viol.items()))
            # #582: the total could be SIZED and not ATTRIBUTED. On the run
            # that raised it, 602 of 1767 max-slew rows were the ECO spare
            # pool's inputs, all tied to one 614-fanout constant net by
            # `_build_spare_postfix_tcl` — a net whose transition is enormous
            # and whose slew is meaningless. Both numbers are stated and their
            # sum is still the total; the count is NOT reduced.
            att = drv.get("attribution") or {}
            split = ""
            if att.get("attributed"):
                split = (f" — of which {att['design']} are design rows and "
                         f"{att['constant_net']} are the preserved spare "
                         f"pool's tied-off inputs on a constant net "
                         f"(DISCLOSED, not subtracted)")
            elif att:
                split = (f" — NOT attributed ({att.get('reason','?')}), so "
                         f"whether any of these are tie-off rows is unknown "
                         f"rather than zero")
            findings.append(
                f"R5 {rpt} ({axis} axis) reports {drv['total']} DRV violation"
                f"{'' if drv['total'] == 1 else 's'}: {pretty}{split} — "
                f"design-rule violations are sign-off violations and are "
                f"surfaced here, not left in the report body for nobody to "
                f"read")

    ordered = [r for r in ("R1_INCOMPLETE_CORNER_RECORD",
                           "R2_DECLARED_BUT_UNREPORTED",
                           "R3_SIGNOFF_CORNER_VIOLATION",
                           "R4_MULTI_CORNER_CLAIM_UNSUPPORTED",
                           "R4_LIBRARY_RESOLUTION_UNRECORDED",
                           "R5_DRV_UNQUERIED",
                           "R5_DRV_VIOLATION") if r in rules]

    if ordered:
        verdict = "FAIL"
    elif degraded_disclosed:
        # Not a failure, but never a multi-corner sign-off either. The verdict
        # STRING carries the limitation so no downstream summary can quote a
        # bare "PASS" and have it read as multi-corner closure.
        verdict = "SINGLE_CORNER_ONLY"
    else:
        verdict = "PASS"

    # DENOMINATORS (vibe-ic#447). R3 — the sign-off MET rule — only examines
    # rows whose `role_class` is "signoff"; it SKIPS every other role. So on a
    # run whose only corner is `primary`, R3 examines ZERO rows and the verdict
    # line still said "every sign-off corner MET". Measured on a published
    # cell: one `nominal` corner, role primary, and that sentence.
    #
    # A claim over zero is not false — vacuously every one of them is MET — but
    # printing it identically to a real multi-corner closure is the defect this
    # repo has now removed from five separate programs.
    _signoff_rows = sum(1 for r in table if r.get("role_class") == "signoff")
    _total_rows = len(table)
    reasons = findings + degraded_disclosed
    if not reasons:
        if _signoff_rows == 0:
            reasons = [f"NO SIGN-OFF CORNER WAS REPORTED: {_total_rows} corner "
                       f"row(s) present, none carrying the `signoff` role, so "
                       f"the sign-off MET rule (R3) examined nothing. Every "
                       f"other rule passed — the record is internally "
                       f"consistent — but this run is NOT evidence that a "
                       f"sign-off corner was met, because none was analysed."]
        else:
            reasons = [f"timing record complete: {_total_rows} corner row(s), "
                       f"{_signoff_rows} of them sign-off; every corner the "
                       f"flow declared is reported for the role it serves, "
                       f"every sign-off corner MET (tol {slack_tol} ns), each "
                       f"reported corner was analysed with its own corner "
                       f"library, and DRV was queried and clean"]
    return {
        "verdict": verdict,
        "status": verdict,
        "reasons": reasons,
        "corners": table,
        "primary_corner": primary,
        "declaration_sources": decl.get("sources"),
        "axis_evidence": axes,
        "single_corner_only": bool(degraded_disclosed),
        "corner_rows": _total_rows,
        "signoff_corner_rows": _signoff_rows,
        "slack_tol_ns": slack_tol,
        "rules_violated": ordered,
    }


def render_table(res: Dict[str, object]) -> str:
    """The per-corner evidence table. Emitted on PASS and FAIL alike — the
    absence of this table is the very defect this gate exists to prevent."""
    rows = res.get("corners") or []
    hdr = (f"{'corner':<38} {'axis':<8} {'role':<22} {'rep':<4} "
           f"{'setup_wns':>10} {'hold_wns':>10} {'tns':>12}  source")
    lines = [hdr, "-" * len(hdr)]
    if not rows:
        lines.append("(no corners declared or reported)")
    for r in rows:  # type: ignore[union-attr]
        def _f(key: str) -> str:
            v = r.get(key)
            return "n/a" if v is None else f"{float(v):+.3f}"
        tns = r.get("tns_ns")
        role = str(r.get("role_class") or "")
        if r.get("roles"):
            role = f"{role}:{'/'.join(r['roles'])}"
        lines.append(
            f"{str(r.get('corner'))[:38]:<38} {str(r.get('axis')):<8} "
            f"{role[:22]:<22} {'yes' if r.get('reported') else 'NO':<4} "
            f"{_f('setup_wns_ns'):>10} {_f('hold_wns_ns'):>10} "
            f"{('n/a' if tns is None else f'{float(tns):.2f}'):>12}  "
            f"{r.get('source') or '-'}")

    # The corner-library resolution and the DRV answer, per axis. Emitted on
    # every verdict: a degradation that is not visible in the evidence is the
    # defect R4 exists to stop, and this table is where it becomes visible.
    axes = res.get("axis_evidence") or []
    if axes:
        lines.append("")
        lines.append("corner-library resolution + DRV (per sign-off axis)")
        lines.append("-" * len(hdr))
        for ax in axes:  # type: ignore[union-attr]
            n_c = ax.get("reported_corner_count") or 0
            n_l = ax.get("distinct_library_count") or 0
            claim = "CLAIMS multi-corner" if ax.get("multi_corner_claim") \
                else "no multi-corner claim"
            state = ("UNRECORDED" if not ax.get("resolution_recorded")
                     else "COLLAPSED" if ax.get("collapsed_groups")
                     else "distinct")
            lines.append(
                f"  {str(ax.get('axis')):<8} {claim:<22} "
                f"corners={n_c} libraries={n_l} [{state}]  "
                f"{ax.get('report') or '-'}")
            for corner, lib in sorted(
                    (ax.get("liberty_by_corner") or {}).items()):
                lines.append(f"      {corner:<14} <- {lib}")
            for c in (ax.get("unresolved_corners") or []):
                lines.append(f"      {str(c):<14} <- UNRESOLVED")
            drv = ax.get("drv")
            if isinstance(drv, dict):
                if not drv.get("queried"):
                    lines.append("      DRV            NOT QUERIED "
                                 "(max_slew/max_capacitance/max_fanout)")
                elif drv.get("violations"):
                    pretty = ", ".join(
                        f"{k} x{v}"
                        for k, v in sorted(drv["violations"].items()))
                    lines.append(f"      DRV            VIOLATED: {pretty}")
                else:
                    lines.append("      DRV            queried, clean")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--slack-tol", type=float, default=_DEFAULT_SLACK_TOL_NS,
                   help="float-noise guard (ns); a slack below -slack_tol is a "
                        "violation (default 0.001)")
    p.add_argument("--json", default=None, help="write the verdict JSON here")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2

    res = evaluate(project, slack_tol=args.slack_tol)

    out_path = None
    if args.json:
        out_path = Path(args.json)
        if not out_path.is_absolute():
            out_path = project / args.json
    elif _pl is not None:
        try:
            out_path = _pl.report_path(
                project, "phase3/sta/sta_corner_record_completeness.json")
        except Exception:
            out_path = None
    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(out_path, json.dumps(res, indent=2) + "\n")
        except OSError as e:
            print(f"{_PROGRAM}: cannot write {out_path}: {e}", file=sys.stderr)
            return 2

    tag = str(res["verdict"])
    # SINGLE_CORNER_ONLY exits 0 (the degradation may be unavoidable) but is
    # NEVER printed as PASS — the banner has to carry the limitation, or the
    # verdict reads as multi-corner sign-off, which is the defect itself.
    ok = tag in ("PASS", "NOT_APPLICABLE", "SINGLE_CORNER_ONLY")
    banner = "PASS" if tag in ("PASS", "NOT_APPLICABLE") else tag
    print(f"[{banner}] {_PROGRAM}: {tag}")
    if tag == "NOT_APPLICABLE":
        # vibe-ic#1115. This gate already knew -- "no stance file, pvt_matrix or
        # STA report declares or records any corner -- there is no timing record
        # to judge". It said so inside a `[PASS]` banner, and the only channel
        # `flow_compliance_check` reads on the passing path is this prefix, so
        # the step was recorded as ordinary multi-corner sign-off over zero
        # corners.
        print(f"VACUOUS_PASS: {_PROGRAM} judged 0 corner(s) — "
              + "; ".join(str(r) for r in res.get("reasons", []))[:200])
    print(render_table(res))
    for reason in res.get("reasons", []):  # type: ignore[union-attr]
        print(f"  - {reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
