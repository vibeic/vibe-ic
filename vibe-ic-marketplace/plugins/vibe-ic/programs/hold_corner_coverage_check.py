#!/usr/bin/env python3
"""
hold_corner_coverage_check.py — confirm hold is analysed at the FAST (FF)
corner, the worst-case corner for hold.

From `skills/hold-fix/SKILL.md` Step 1 + Step 6:
  "Run STA at the FF corner (fast process, high voltage, low temperature)."
  "Hold must be verified across all fast corners: FF, high voltage, low
   temperature (worst hold). ... If using MCMM, the hold analysis view must use
   the FF corner."

This is the narrow, hold-SPECIFIC corner rule — distinct from the broad PVT
presence audit in `corner_coverage_audit.py` (which only checks that SS/TT/FF
Liberty files exist somewhere in the tree). Here we verify that the LIBERTY /
operating-condition actually consumed by the HOLD analysis is a FAST corner.
A flow can have FF `.lib` files present (corner_coverage_audit PASS) yet still
read the SS/TT Liberty for its hold check — that is the real defect this gate
catches: hold analysed at the WRONG (non-FF) corner under-reports hold
violations and ships a hold-broken chip.

What it scans
-------------
A hold-analysis Tcl/SDC/log artefact (the file that drives the hold check).
It looks for the Liberty / operating-condition that the hold path consumes:
  * `read_liberty ...ff...lib`            (OpenSTA)
  * `report_checks -path_delay min ...`   (the hold-report invocation)
  * `set_operating_conditions ... ff...`  (MCMM hold view)
  * any explicit "hold corner = ff" / "min view = ff" assignment.

A process corner is FAST when its designator is `ff` / `fast_fast` / `fast`.
SS / TT (slow / typical) used for the hold (min) analysis is the FAIL.

HOW THE CORNER IS DECIDED (rewritten when this gate was first wired)
--------------------------------------------------------------------
The first version demanded that EVERY corner designator on EVERY
`read_liberty` line classify FF. Measured against the flow's own emitter, that
is wrong on correct work: `phase3_one_shot_runner._emit_mcorner_ocv_sta._pass`
writes the sign-off corner liberty and then interpolates `macro_libs_tcl` — one
`read_liberty` per HARD-MACRO liberty — into the same hold script, and the
runner deliberately narrows multi-corner macro libs to the TYPICAL ones. So any
design carrying a hard macro (SRAM, an analog A8 hardmacro, vendor IP) produced
`read_liberty …ff….lib` + `read_liberty …_tt_….lib` and was failed
`HOLD_NOT_AT_FF ['FF','TT']` for a hold sign-off that was in fact at FF. The
corpus hid this: the only two runs that retained the script belong to a
macro-free design.

The decision is now layered, strongest evidence first:

  1. DECLARED STANCE. `reports/phase3/mcorner_ocv_stance.json` records
     `hold_process_corner` — the label the run actually assigned to the hold
     role. It is durable (it survives when the Tcl is pruned from a published
     run) and unambiguous (no parsing). Judged directly.
     It is NOT a tie-breaker over the script — see A DECLARED FIELD DOES NOT
     OUTRANK THE EVIDENCE below.
  2. EXPLICIT HOLD-VIEW LINES. Lines that tie hold/min to a corner — the
     emitter's own `=== HOLD corner: process=FF liberty=… ===` banner, or an
     MCMM `set_hold_view` / `-corner` assignment. When any exist, ONLY they are
     judged; a macro liberty read elsewhere in the file cannot outvote the
     script's own statement of which corner the hold analysis runs at.
     WITHIN such a line there are THREE outcomes and not two — see THE CORNER
     WAS NOT ALWAYS MEASURED below.
  3. LIBERTY / OPERATING-CONDITION FEED. Otherwise the union of designators on
     `read_liberty` / `set_operating_conditions` / hold-view lines is taken and
     the rule is: a FAST designator anywhere in that set means a fast corner
     feeds the hold analysis -> PASS, and the remaining designators are
     DISCLOSED as `extra_library_corners` (they are additional models, not the
     process corner of the sign-off). No FF anywhere -> FAIL: the hold analysis
     was run with only slow/typical libraries, which is the defect.
     The corner a line contributes is the corner its Liberty DECLARES when that
     Liberty can be opened — see THE EVIDENCE ON A LINE IS THE LIBERTY below.

THE EVIDENCE ON A LINE IS THE LIBERTY IT NAMES, NOT THE TOKENS IN ITS TEXT
--------------------------------------------------------------------------
Rules 2 and 3 mine the corner designator out of the TEXT of the line — in
practice, out of the Liberty FILENAME. Two measured consequences:

  * A PDK that does not spell `ff`/`ss`/`tt` in its Liberty filenames could not
    be classified AT ALL. Measured on a hold script whose sole `read_liberty`
    names a Liberty declaring `operating_conditions (fast)`, `nom_voltage`
    high, `nom_temperature` low — an unambiguous FAST corner — this gate
    answered `NO_FEED_CORNER: no Liberty / operating condition corner could be
    identified feeding it`. It had the Liberty's path on the line it was
    reading and never opened it. Best-case/worst-case corner naming,
    vendor-internal corner names and customer renames are all ordinary, and
    none of them spell `ff`/`ss`/`tt`.
  * The delimiter class of `_PROC_RE` omitted `=` and the bracket forms, so the
    emitter's OWN hold-view banner — `=== HOLD corner: process=FF liberty=… ===`
    — and a Liberty's own `operating_conditions (fast) {` were both invisible
    to the rule that documents itself as reading them.

Both are the same shape: a check measuring something ADJACENT to its question
(does a corner token appear in this line's text) and publishing the answer to
the question (no corner could be identified). So:

  A line that NAMES a Liberty we can open contributes the corner that Liberty
  DECLARES (`default_operating_conditions`, else the `operating_conditions`
  groups), and the line's own text tokens are discarded as an unverified
  restatement of it.

Fail-SAFE, never fail-open: a Liberty that is absent, unreadable, or whose
declared conditions do not classify contributes NOTHING and the line falls
back to its text tokens, exactly as before. Every Liberty actually opened and
classified is published under `liberty_declared_corners`, so a reader can tell
a content-backed verdict from one that fell back to a filename.

WHERE THAT EVIDENCE PLUGS IN — AND WHERE IT MUST NOT
-----------------------------------------------------
The Liberty's declared corner is EVIDENCE, and evidence has exactly one seat
in this gate: it is the side of `_judge_view_line` that the banner LABEL is
arbitrated AGAINST (see THE CORNER WAS NOT ALWAYS MEASURED below). It is NOT a
second contributor UNIONed in beside the label.

That distinction is the whole composition and it is measured, not stylistic.
Union the two and the emitter's own banner

    === HOLD corner: process=FF liberty=/foss/pdks/…/…__ss_….lib, SPEF=… ===

resolves to {FF, SS}, `FF in judged` is true, and the gate answers PASS on a
hold sign-off that read the SLOW library — the exact defect it exists to
catch. Arbitrate instead and the same line is a CONTRADICTION: FAIL. The
emitter says why the path is on that line, in its own comment:

    "a section headed process=SS proved nothing about which file was read"

The label is the claim; the Liberty is the evidence. Note also that the path
that emitter prints is a CONTAINER path (`_to_container_path` -> `/foss/pdks/…`)
and is therefore normally UNOPENABLE on the host running this gate — so on the
flow's own artefacts `_line_corners` contributes nothing and the arbitration
falls back to the filename tokens on the line. That fallback is what fails the
banner above, and it is why the evidence side must still be READ from the line
when the Liberty cannot be opened rather than treated as "no evidence".

A DECLARED FIELD DOES NOT OUTRANK THE EVIDENCE IT CLAIMS TO SUMMARISE
---------------------------------------------------------------------
The first wiring of this gate read the stance and STOPPED: in project-directory
mode `_discover` returned the moment `reports/phase3/mcorner_ocv_stance.json`
existed and the hold Tcl was never opened. MEASURED false PASS that produced —
a stance saying

    "hold_process_corner": "FF"

beside a hold script whose only `read_liberty` is `…__ss_100C_1v60.lib` and
whose own banner reads `=== HOLD corner: process=SS … ===`:

    project directory  -> rc=0 PASS   (stance believed, script discarded)
    the identical Tcl  -> rc=1 FAIL   HOLD_NOT_AT_FF

Every non-rc=2 verdict this gate produced over the published corpus came from
the stance, and two published roots (`sha256/clean_run_v1422_20260715`,
`…v1427…`) carry BOTH artefacts — so the discarded input was not hypothetical.
That is the shape `de8e98b3e` had just repaired elsewhere: a DECLARED field
standing in for the measurement it names.

So project-directory mode now judges EVERY source it finds and takes the WORST:

    FAIL   >   PASS   >   NOT CHECKED

read as "worst of the verdicts that were REACHED". FAIL wins outright — a
contradiction between the label and the script is resolved against the label,
in either direction, and both readings are published under `sources` with
`contradiction: true`. PASS outranks NOT CHECKED deliberately and it is the
same rule, not an exception to it: a source that reached NO verdict (an
unreadable stance, a stance with no `hold_process_corner` at all) is not
evidence, and letting it mask a source that DID reach one would discard
evidence in the other direction.

The input SET is unchanged — the same single hold Tcl the fallback would have
picked (most specific candidate first, then the glob). This repair is "stop
discarding the script", not "widen what counts as a script".

  RESIDUALS, disclosed on purpose — two, and neither is closed by the above:

  1. A run that publishes ONLY the stance is still judged on its declared field
     alone, with nothing to corroborate it. MEASURED: 26 of the 34 published
     phase-3 run roots have neither artefact (rc=2), 6 have the stance alone
     and 2 have both — so the corroborated case is 2 roots today. What closes
     this is the flow RETAINING the hold script on a published run, not a
     checker change: with no script there is nothing to read.
  2. A hand-written MCMM script that reads ss/tt/ff libraries and then assigns
     the hold view to ss WITHOUT any hold/min-tagged line reaches rule 3 and
     passes on the presence of the ff library. Rule 2 covers every script that
     says which view is the hold view. The alternative — rule 3 as an
     all-must-be-FF rule — is a FALSE FAIL on every macro-bearing design, which
     is strictly worse.

THE CORNER WAS NOT ALWAYS MEASURED, AND THAT IS ITS OWN ANSWER
---------------------------------------------------------------
Rule 2's line carries two different kinds of thing and they can disagree. The
emitter writes `=== HOLD corner: process=<label> liberty=<path> ===`, and it
says in its own comment why the path is there:

    "a section headed process=SS proved nothing about which file was read"

So on that line the LABEL is a declaration and the PATH is the evidence — the
file `read_liberty` actually took. Reading the union of the two lets an `_ff_`
filename supply an FF a `process=SS` declaration never claimed (a false PASS on
the exact defect this gate exists to catch). Promoting the label to sole
arbiter is the SAME error mirrored: `process=FF` beside an `_ss_` filename then
certifies FF off a printed sentence while the tool read the slow library.
Neither is a reading of the line; each is a preference for one corner.

Nor is a declaration always readable. `process=$::env(HOLD_CORNER)`,
`process=$corner`, `process=SF` (a cross corner outside this gate's FF/SS/TT
model) and `process=bci` (a PDK's own corner name) all ASSIGN the process
corner and none of them resolve. Treating that as "no assignment" drops the
line straight back onto the Liberty filename — the evidence the assignment had
superseded — and answers PASS with nothing in the report saying so.

So the states are THREE, everywhere:

    measured-clean   -> PASS
    measured-defect  -> FAIL   HOLD_NOT_AT_FF
    NOT measured     -> FAIL   HOLD_CORNER_CONTRADICTION      (the line
                               disagrees with itself: two explicit assignments
                               that differ, or an assignment that differs from
                               a corner named elsewhere on the same line)
                       FAIL   HOLD_CORNER_UNRESOLVED          (an assignment
                               is present and its value cannot be read)
                       FAIL   NO_FEED_CORNER                  (pre-existing)

and every report carries `hold_corner_measured` so the third state is
machine-readable rather than inferred from a reason string. The two new states
are SYMMETRIC in the corner — `process=SS` beside an `_ff_` filename and
`process=FF` beside an `_ss_` filename are one defect seen from two sides.

rc=1, NOT rc=2, and that is load-bearing. rc=2 is the disclosed-SKIP tier for a
run that published no hold sign-off at all, and `_SEVERITY` ranks NOT CHECKED
BELOW PASS so that an unreadable stance cannot mask a script that did reach a
verdict. MEASURED: with these two branches returning rc=2, `judge_project` on a
tree whose stance declares `hold_process_corner: "FF"` beside a script reading
`process=$::env(X)` returns rc=0 PASS — the third state silently resolving to
the thing it must never be. An artefact that exists and contradicts itself is
not an absent artefact.

  RESIDUAL, disclosed: the strict `process|pvt|operating_condition|opcond`
  key set fires UNRESOLVED on any unreadable value, including English prose in
  a comment that happens to say `… corner selection process: automatic`. That
  direction is fail-safe (never a PASS) and it is empirically quiet: across the
  291 published Tcl decks the only value any of those four keys carries on a
  hold-view line is `FF`. `corner` / `view` / `mode` are excluded from the
  strict set for the opposite reason — measured, they carry `max-RC`, `min-RC`,
  `drive` and the nested string `process=FF`.

Verdicts
--------
* PASS (rc=0) — a hold/min analysis is present AND a FAST (FF) corner feeds it.
* FAIL (rc=1) — the hold/min analysis is driven by a NON-fast (SS/TT) corner,
                OR no hold/min analysis is present in an artefact that exists
                (nothing was verified — honest FAIL, not a vacuous pass), OR an
                explicitly NAMED input file is missing/empty/garbage, OR the
                hold corner could NOT BE MEASURED at all
                (`HOLD_CORNER_CONTRADICTION` / `HOLD_CORNER_UNRESOLVED` /
                `NO_FEED_CORNER`, each carrying `hold_corner_measured: false`).
* NOT CHECKED (rc=2) — PROJECT-DIRECTORY mode only: the run produced neither a
                multi-corner OCV stance record nor a hold STA script, so there
                is no hold sign-off to judge. rc=2 is the flow's disclosed-skip
                tier. This tier is what lets the gate be wired UNCONDITIONALLY:
                gating it on the very artefact whose absence would be
                interesting is the self-disabling shape
                `flow_condition_reachability_check` refuses, and without the
                tier an unconditional wire reddened 31 of 33 published runs for
                INPUT_MISSING.

chip-AGNOSTIC: corner designators are matched by the same general convention
patterns used by corner_coverage_audit.py; no PDK / vendor cell is hard-coded.

Usage
-----
    python3 hold_corner_coverage_check.py <hold_tcl_or_log> [--json <out>]
    python3 hold_corner_coverage_check.py <project_dir> [--json <out>]
    python3 hold_corner_coverage_check.py --stance <mcorner_ocv_stance.json>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_TOOL = "hold_corner_coverage_check"

# Process-corner designators (subset of corner_coverage_audit.PROCESS_CORNER_MAP).
_FAST = {"ff", "fast_fast", "fastfast", "fast"}
_SLOW = {"ss", "slow_slow", "slowslow", "slow"}
_TYP = {"tt", "typical", "typ", "nom"}

_CORNER_ALT = (r"ss|tt|ff|sf|fs|slow_slow|fast_fast|typical|slowslow|fastfast|"
               r"slow_fast|fast_slow|slowfast|fastslow|slow|fast|typ|nom")

_PROC_RE = re.compile(
    # The delimiter class carries `=`, the quote forms and the bracket forms on
    # purpose. The emitter's own hold-view banner is a key=value spelling
    # (`=== HOLD corner: process=FF liberty=… ===`, cited as the canonical
    # rule-2 line in the module docstring) and a Liberty declares its corner as
    # `operating_conditions (fast) {`. Without `=` / `(` / `)` in the class this
    # gate could not read either of the two lines it documents itself as
    # reading, and answered NO_FEED_CORNER on evidence it was holding.
    r"(?:^|[_/\-.\s:,=()\[\]{}\"'])"
    r"(" + _CORNER_ALT + r")"
    r"(?:[_/\-.\s:,=()\[\]{}\"']|$)",
    re.IGNORECASE,
)

#: An EXPLICIT corner ASSIGNMENT — `process=FF`, `corner: ss`, `pvt=tt`. This is
#: the script STATING which corner the hold analysis runs at, as opposed to a
#: corner designator that merely occurs somewhere on the line (most often inside
#: a Liberty FILENAME, `…__ff_n40C_1v95.lib`).
#:
#: The two are not the same claim and they can disagree. MEASURED, on the
#: emitter's own banner, with no PDK material involved:
#:
#:   read_liberty /pdk/lib/acme_sc__ff_n40C_1v95.lib
#:   puts $_f "=== HOLD corner: process=SS liberty=/pdk/lib/acme_sc__ff_n40C_1v95.lib ==="
#:   report_checks -path_delay min
#:
#: -> rc=0 PASS "HOLD_AT_FF", basis `declared_hold_view`. The script says SS —
#: the defect this gate exists to catch — and the gate certified FF off the
#: FILENAME while claiming to have judged the declaration. `=` was absent from
#: the delimiter class above, so `=SS` was not merely outranked, it was
#: invisible; the only corner the line yielded was the filename's.
#:
#: The mirror case cost a real run: a PDK whose Liberty filenames carry NO
#: corner designator (a perfectly ordinary naming convention) produced
#: `hold_feed_corners: []` and rc=1 `NO_FEED_CORNER` on a hold sign-off whose
#: own banner reads `process=FF` and whose stance record independently declares
#: HOLD_AT_FF. The gate reported "no corner could be identified" while quoting,
#: in its own `hold_feed_lines`, the line that identifies it.
#:
#: So on a hold-view line an explicit assignment DECIDES and the incidental
#: tokens are disclosed, not judged. This is narrower than the old behaviour in
#: the direction that matters (a declared SS can no longer be masked by an ff
#: filename) and wider only where the line said so itself. Lines with no
#: assignment — `set_hold_view -corner ff_view` — are unaffected and still fall
#: through to the union rule.
_CORNER_ASSIGN_RE = re.compile(
    r"\b(?:process|corner|pvt|view|mode|operating_condition|opcond)\s*[=:]\s*"
    r"\"?'?(" + _CORNER_ALT + r")(?![\w-])",
    re.IGNORECASE,
)


#: An assignment SITE — `<process-key> = <whatever>` — with the RAW value, read
#: WITHOUT requiring the value to be a corner at all. `_CORNER_ASSIGN_RE` above
#: answers "does this line assign a corner"; this one answers the prior
#: question "does this line assign the process corner AT ALL", and the two are
#: not the same. An assignment whose value the gate cannot read —
#: `process=$::env(HOLD_CORNER)`, `process=$corner`, `process=SF` (a cross
#: corner this gate's FF/SS/TT model does not cover), `process=bci` (a PDK's own
#: corner name) — produces NO assigned corner, and without this regex that is
#: indistinguishable from a line that made no assignment: the code falls
#: straight back to the union of tokens on the line, i.e. to the Liberty
#: FILENAME. MEASURED on the head of this branch before this repair:
#:
#:   read_liberty /pdk/lib/acme_sc__ff_n40C_1v95.lib
#:   puts $_f "=== HOLD corner: process=$::env(HOLD_CORNER) liberty=…__ff_…lib ==="
#:   report_checks -path_delay min
#:
#: -> rc=0 PASS "HOLD_AT_FF" — certified off the very filename the line above
#: had just been rewritten to distrust, with nothing in the report saying the
#: declaration had been unreadable.
#:
#: KEYS. `process` / `pvt` / `operating_condition` / `opcond` only. `corner`,
#: `view` and `mode` are deliberately NOT here, and that is measured rather than
#: taste: across the 291 Tcl decks published under `benchmark-data/` the values
#: those keys actually carry on a hold-view line are `max-RC`, `min-RC`, `drive`
#: and — on the emitter's own banner, `HOLD corner: process=FF` — the string
#: `process=FF` itself. RC corners, a repair mode and a nested key: none of them
#: a statement about the process corner, so a value they fail to resolve is not
#: evidence that the process corner went unstated. They remain readable in the
#: POSITIVE direction through `_CORNER_ASSIGN_RE` (`corner=ff` still decides).
_PROCESS_ASSIGN_SITE_RE = re.compile(
    r"\b(process|pvt|operating_condition|opcond)\s*[=:]\s*"
    r"[\"']?([^\s,\"'()\[\]]*)",
    re.IGNORECASE,
)

#: The three states a hold-view line can be in. The whole point of naming them
#: is that the third one EXISTS: measured-clean and measured-defect are both
#: verdicts about the corner, and everything else is the gate saying it could
#: not measure — which may never be spelled PASS.
_LINE_MEASURED = "measured"
_LINE_CONTRADICTION = "contradiction"
_LINE_UNRESOLVED = "unresolved"


def _assigned_corners_in(text: str) -> List[str]:
    """Corners named by an EXPLICIT `<key>=<corner>` assignment on this line."""
    out = []
    for m in _CORNER_ASSIGN_RE.finditer(text):
        c = _classify_corner(m.group(1))
        if c in ("FF", "SS", "TT"):
            out.append(c)
    return out


def _process_assignment_sites(text: str) -> List[Tuple[str, str]]:
    """Every `<process-key>=<value>` site on the line, value RAW and unjudged."""
    return [(m.group(1).lower(), m.group(2))
            for m in _PROCESS_ASSIGN_SITE_RE.finditer(text)]


def _judge_view_line(line: str, base: Optional[Path] = None,
                     cache: Optional[dict] = None,
                     named: Optional[list] = None
                     ) -> Tuple[str, List[str], dict]:
    """Resolve ONE hold-view line to (state, corners, detail).

    THE EVIDENCE SIDE is `_line_corners`: the corner the Liberty named on this
    line DECLARES when that Liberty can be opened, and the line's own text
    tokens when it cannot. It is arbitrated AGAINST the explicit `process=`
    label, never UNIONed with it — see WHERE THAT EVIDENCE PLUGS IN in the
    module docstring for the measured false PASS the union produces.

    PRECEDENCE, stated because it is a choice and not an accident: UNRESOLVED
    is decided BEFORE the evidence is consulted. An unreadable
    `process=$::env(HOLD_CORNER)` stays UNRESOLVED even when the Liberty beside
    it opens and declares FAST. Promoting that to MEASURED-FF would be the one
    widening in this whole composition that moves a verdict TOWARD pass on an
    artefact whose own declaration could not be read, and `_judge_view_line`'s
    entire reason to exist is that "could not measure" may never be spelled
    PASS. The Liberty is still opened by the rule-3 feed loop below, so it is
    still DISCLOSED under `liberty_declared_corners`; it just does not decide.

    A line can support the gate's claim, refute it, or fail to settle it, and
    the third outcome is not a weaker form of the first two — it is a different
    answer. Collapsing it into either direction is how a checker starts
    certifying the thing it did not measure.

      * UNRESOLVED — the line assigns the process corner and the gate cannot
        read the value. Assignment PRESENT beats tokens-on-the-line, so falling
        back to the filename here would be reading the evidence the line itself
        superseded; and reporting no assignment at all would be false.
      * CONTRADICTION — the line makes two claims that cannot both hold: two
        explicit assignments that disagree, or an assignment that disagrees
        with the EVIDENCE on that SAME line (the corner its Liberty declares,
        or failing that the corner designators in its text). The emitter's
        banner is `process=<label> liberty=<path>`, and `<path>` is the file
        `read_liberty` actually took — the emitter says so in its own comment,
        "a section headed process=SS proved nothing about which file was read",
        which is WHY the path was added beside the label. So on that line the
        label is the declaration and the path is the evidence, and the module
        docstring's own rule applies: A DECLARED FIELD DOES NOT OUTRANK THE
        EVIDENCE IT CLAIMS TO SUMMARISE. Neither side wins; the disagreement
        is the finding.
      * MEASURED — one corner class, or none and the line falls through to the
        union rule exactly as before.

    Both non-measured states are SYMMETRIC in the corner: `process=SS` beside
    an `_ff_` Liberty and `process=FF` beside an `_ss_` Liberty are the same
    defect seen from two sides, and a rule that fails one and passes the other
    is not reading the line, it is preferring a corner.
    """
    sites = _process_assignment_sites(line)
    unreadable = [{"key": k, "value": v} for k, v in sites
                  if _classify_corner(v.strip("\"'")) not in ("FF", "SS", "TT")]
    if unreadable:
        return _LINE_UNRESOLVED, [], {"assignments": unreadable}

    assigned = sorted(set(_assigned_corners_in(line)))
    if len(assigned) > 1:
        return _LINE_CONTRADICTION, [], {
            "kind": "assignments_disagree", "assigned": assigned}
    evidence, source = _line_evidence(
        line, base, cache if cache is not None else {},
        named if named is not None else [])
    if assigned:
        other = sorted({c for c in evidence if c not in assigned})
        if other:
            return _LINE_CONTRADICTION, [], {
                "kind": "declaration_disagrees_with_the_line",
                "assigned": assigned, "also_on_line": other,
                "evidence_source": source}
        return _LINE_MEASURED, assigned, {"assigned": assigned}
    return _LINE_MEASURED, sorted(set(evidence)), {}


# Lines that introduce a Liberty / operating-condition used by the MIN (hold)
# analysis. We mine the Liberty read AND any min-path / hold view assignment.
_LIB_READ_RE = re.compile(r"\bread_liberty\b(.*)$", re.I)
_MIN_VIEW_RE = re.compile(
    r"(?:hold|min)[^\n]*?(?:corner|view|operating_condition|lib)\b(.*)$", re.I)
_SET_OC_RE = re.compile(r"\bset_operating_conditions\b(.*)$", re.I)
# The invocation that runs the hold report (proves a hold analysis exists).
_HOLD_RUN_RE = re.compile(
    r"report_checks[^\n]*-path_delay\s+min|"
    r"report_worst_slack[^\n]*-min|report_tns[^\n]*-min|"
    r"\b-path_delay\s+min\b|\bcheck_hold\b", re.I)


def _classify_corner(token: str) -> str:
    t = token.lower()
    if t in _FAST:
        return "FF"
    if t in _SLOW:
        return "SS"
    if t in _TYP:
        return "TT"
    return "OTHER"


def _corners_in(text: str) -> List[str]:
    out = []
    for m in _PROC_RE.finditer(text):
        c = _classify_corner(m.group(1))
        if c in ("FF", "SS", "TT"):
            out.append(c)
    return out


# ─────────────── the corner a Liberty DECLARES, not the one its name spells ──
#
# A `.lib` states its own process corner in the library header, in the
# `operating_conditions` group and the `default_operating_conditions` pointer.
# That is the ground truth for "which corner feeds this analysis"; the corner
# token in the FILENAME is a naming convention, and a great many PDKs do not
# follow it (best-case/worst-case naming, vendor-internal corner names, a
# customer rename). Reading only the filename is measuring something ADJACENT
# to the question and publishing it as the answer.
#
# Fail-SAFE, never fail-open: a Liberty that is absent, unreadable, or whose
# declared conditions do not classify contributes NOTHING and the line falls
# back to its text tokens — exactly the pre-existing behaviour. That fallback
# is load-bearing rather than a courtesy: the flow's own banner names a
# CONTAINER path, so on the artefacts this gate actually reads the Liberty is
# usually unopenable and the filename tokens are the only evidence there is.

#: A Liberty path as it appears on a Tcl line, bare or quoted/braced.
_LIB_PATH_RE = re.compile(r"[^\s\"'{}\[\]()=,;]+\.lib(?:\.gz)?\b", re.I)
#: `operating_conditions (fast) {` — the group that names a corner.
_OC_GROUP_RE = re.compile(
    r"^[ \t]*operating_conditions\s*\(\s*([^)\s]+?)\s*\)", re.I | re.M)
#: `default_operating_conditions : fast;` — which group is THE one.
_DEFAULT_OC_RE = re.compile(
    r"^[ \t]*default_operating_conditions\s*:\s*([^;\s]+)\s*;", re.I | re.M)
#: Liberty files run to hundreds of MB of cell groups; every declaration we
#: read lives in the library header, so bound the read instead of slurping.
_LIB_HEAD_BYTES = 1 << 20


def _liberty_declared_corners(path: Path) -> List[str]:
    """The FF/SS/TT corners this Liberty DECLARES in its header. `[]` when the
    file cannot be read or declares nothing we can classify — never a guess."""
    try:
        with path.open("r", errors="replace") as fh:
            head = fh.read(_LIB_HEAD_BYTES)
    except OSError:
        return []
    default = _DEFAULT_OC_RE.search(head)
    if default:
        got = _corners_in(default.group(1))
        if got:
            return got
    out: List[str] = []
    for m in _OC_GROUP_RE.finditer(head):
        out.extend(_corners_in(m.group(1)))
    return out


#: Where a line's evidence came from. Published in the contradiction detail
#: because the two call for DIFFERENT repairs: `liberty_content` says the file
#: the tool read declares a corner the banner denies (fix the corner resolution
#: or the banner), `line_tokens` says a filename disagrees with the banner and
#: the Liberty could not be opened to break the tie (usually a container path —
#: retain the Liberty, or emit a host-resolvable one).
_EV_CONTENT = "liberty_content"
_EV_TOKENS = "line_tokens"


def _line_evidence(line: str, base: Optional[Path],
                   cache: dict, named: list) -> Tuple[List[str], str]:
    """The EVIDENCE this ONE line carries about the corner feeding hold, and
    WHERE it came from.

    Liberty CONTENT when the line names a Liberty we can open and classify;
    otherwise the line's own text tokens (unchanged behaviour). `cache` is
    keyed by resolved path so a deck reading the same Liberty on twenty lines
    opens it once; `named` accumulates the disclosure list published as
    `liberty_declared_corners`.

    This is the EVIDENCE side and nothing else. It is fed to
    `_judge_view_line`, which arbitrates it against the line's explicit
    `process=` LABEL, and to the rule-3 feed union. It is deliberately NOT
    unioned with the label on a hold-view line — see WHERE THAT EVIDENCE PLUGS
    IN in the module docstring: the union is what produces the false PASS.
    """
    content: List[str] = []
    for raw in _LIB_PATH_RE.findall(line):
        p = Path(raw)
        if not p.is_absolute():
            if base is None:
                continue
            p = base / raw
        key = str(p)
        if key not in cache:
            cache[key] = _liberty_declared_corners(p) if p.is_file() else []
            if cache[key]:
                named.append({"liberty": key, "declared_corners":
                              sorted(set(cache[key]))})
        content.extend(cache[key])
    if content:
        return content, _EV_CONTENT
    return _corners_in(line), _EV_TOKENS


def _line_corners(line: str, base: Optional[Path],
                  cache: dict, named: list) -> List[str]:
    """`_line_evidence` without the provenance — the rule-3 feed union does not
    arbitrate anything, so it has nothing to attribute."""
    return _line_evidence(line, base, cache, named)[0]


def evaluate(text: Optional[str],
             base: Optional[Path] = None) -> Tuple[str, int, dict]:
    """`base` is the directory a RELATIVE Liberty path on a feed line resolves
    against (the hold script's own directory). Absolute paths resolve without
    it; when it is None only absolute paths are opened, so a caller that has no
    directory context keeps exactly the pre-existing text-token behaviour."""
    report = {"tool": _TOOL}
    if text is None:
        report.update(verdict="FAIL", reason="INPUT_MISSING",
                      message="hold-analysis artefact missing/unreadable — "
                              "cannot verify the hold corner (honest FAIL)")
        return "FAIL", 1, report
    if not text.strip():
        report.update(verdict="FAIL", reason="INPUT_EMPTY",
                      message="hold-analysis artefact is empty")
        return "FAIL", 1, report

    has_hold_run = bool(_HOLD_RUN_RE.search(text))
    report["hold_analysis_present"] = has_hold_run
    if not has_hold_run:
        report.update(verdict="FAIL", reason="NO_HOLD_ANALYSIS",
                      message="no hold (min-path) analysis found "
                              "(report_checks -path_delay min / "
                              "report_worst_slack -min) — nothing was verified")
        return "FAIL", 1, report

    # Collect the corners that feed the hold/min analysis: every read_liberty,
    # set_operating_conditions, and explicit min/hold view line.
    feed_lines: List[str] = []
    view_lines: List[str] = []
    for line in text.splitlines():
        is_view = bool(_MIN_VIEW_RE.search(line))
        if _LIB_READ_RE.search(line) or _SET_OC_RE.search(line) or is_view:
            feed_lines.append(line)
        if is_view:
            view_lines.append(line)

    # RULE 2 — a line that explicitly ties hold/min to a corner outranks every
    # other liberty in the file (see the module docstring).
    #
    # WITHIN such a line there are THREE outcomes, not two — see
    # `_judge_view_line`. A line that states the hold corner and states it
    # consistently is measured; a line that states it twice over and disagrees
    # with itself, or states a value the gate cannot read, is NOT a weaker
    # measurement, it is the absence of one, and it is resolved below into its
    # own verdict rather than allowed to fall back onto the Liberty FILENAME.
    #
    # ONE Liberty cache spans both loops: a deck that reads the same Liberty on
    # its banner and on its `read_liberty` opens the file once, and `libs_read`
    # is the single disclosure list both loops append to.
    lib_cache: dict = {}
    libs_read: list = []
    view_corners: List[str] = []
    view_assigned: List[str] = []
    contradictions: List[dict] = []
    unreadable: List[dict] = []
    for line in view_lines:
        state, corners, detail = _judge_view_line(
            line, base, lib_cache, libs_read)
        if state == _LINE_CONTRADICTION:
            contradictions.append(dict(detail, line=line.strip()))
        elif state == _LINE_UNRESOLVED:
            unreadable.append(dict(detail, line=line.strip()))
        else:
            view_corners.extend(corners)
            view_assigned.extend(detail.get("assigned") or [])
    if view_assigned:
        report["view_line_assigned_corners"] = sorted(set(view_assigned))

    feed_corners: List[str] = []
    for line in feed_lines:
        feed_corners.extend(_line_corners(line, base, lib_cache, libs_read))
    report["hold_feed_corners"] = sorted(set(feed_corners))
    report["hold_feed_lines"] = feed_lines
    # Publish EVERY Liberty whose declared conditions were actually opened and
    # classified, so a reader can tell a content-backed verdict from one that
    # fell back to a filename token.
    if libs_read:
        report["liberty_declared_corners"] = libs_read

    # THE THIRD STATE. Reached before any corner is judged, because there is
    # nothing to judge: the hold sign-off names its own corner and the naming
    # does not settle. rc=1 and NOT rc=2 on purpose — rc=2 is the flow's
    # disclosed-SKIP tier for a run that published no hold sign-off at all, and
    # `_SEVERITY` ranks NOT CHECKED BELOW PASS, so a project whose stance says
    # FF would swallow an unmeasurable script whole and answer PASS. MEASURED:
    # with these branches returning rc=2, `judge_project` on a tree carrying
    # `hold_process_corner: "FF"` beside a script reading `process=$::env(X)`
    # returns rc=0 PASS. An artefact that exists and contradicts itself is not
    # a skip.
    if contradictions or unreadable:
        report["hold_corner_measured"] = False
        report["hold_view_lines"] = view_lines
        report["corner_basis"] = "unmeasurable"
        if contradictions:
            report["hold_corner_contradictions"] = contradictions
            report.update(
                verdict="FAIL", reason="HOLD_CORNER_CONTRADICTION",
                message="the hold sign-off contradicts itself about its own "
                        "process corner — an explicit corner assignment on a "
                        "hold-view line disagrees with the corner named "
                        f"elsewhere on that same line ({contradictions}). "
                        "Neither reading outranks the other (a declared field "
                        "does not outrank the evidence it claims to "
                        "summarise), so the corner the hold analysis ran at "
                        "was NOT measured — this is not a PASS with a caveat")
            return "FAIL", 1, report
        report["hold_corner_unreadable_assignments"] = unreadable
        report.update(
            verdict="FAIL", reason="HOLD_CORNER_UNRESOLVED",
            message="a hold-view line ASSIGNS the process corner and the "
                    f"assigned value cannot be resolved to FF/SS/TT "
                    f"({unreadable}) — an unresolved variable, or a corner "
                    "outside this gate's FF/SS/TT model. The assignment "
                    "supersedes the corner designators sitting elsewhere on "
                    "the line (typically a Liberty filename), so there is "
                    "nothing left to read: the hold corner was NOT measured")
        return "FAIL", 1, report

    if view_corners:
        judged, basis = sorted(set(view_corners)), "declared_hold_view"
        report["hold_view_lines"] = view_lines
    else:
        judged, basis = sorted(set(feed_corners)), "liberty_feed"
    report["corner_basis"] = basis
    report["judged_corners"] = judged

    if not judged:
        # A hold analysis runs but we cannot find ANY Liberty / OC corner
        # designator feeding it — we cannot certify it is FF. Honest FAIL.
        # Third state as well: nothing was measured, so it is flagged as such
        # and can never read as a pass.
        report["hold_corner_measured"] = False
        report.update(verdict="FAIL", reason="NO_FEED_CORNER",
                      message="hold analysis present but no Liberty / operating "
                              "condition corner could be identified feeding it "
                              "— cannot confirm the FF corner is used")
        return "FAIL", 1, report

    if "FF" not in judged:
        non_fast = [c for c in judged if c != "FF"]
        report["hold_corner_measured"] = True
        report.update(verdict="FAIL", reason="HOLD_NOT_AT_FF",
                      message=f"hold (min) analysis is driven by a NON-fast "
                              f"corner {non_fast} and by no fast corner at all "
                              f"(basis: {basis}) — hold is worst at FF "
                              f"(fast/high-V/low-T); signing hold off at "
                              f"{non_fast} under-reports hold violations")
        return "FAIL", 1, report

    extra = [c for c in judged if c != "FF"]
    if extra:
        # DISCLOSED, not failed: additional libraries (hard-macro / IP models,
        # which the flow narrows to the typical corner by design) are not the
        # process corner of the hold sign-off.
        report["extra_library_corners"] = extra
    report["hold_corner_measured"] = True
    report.update(verdict="PASS", reason="HOLD_AT_FF",
                  message="hold (min) analysis is driven by the FF corner — "
                          "the worst-case corner for hold"
                          + (f" (additional library corners {extra} disclosed, "
                             f"not judged as the sign-off corner)"
                             if extra else ""))
    return "PASS", 0, report


# ───────────────────────── declared-stance mode ──────────────────────────
#: The durable record of which PROCESS corner each sign-off role resolved to.
#: Written by `phase3_one_shot_runner` on every run that reaches multi-corner
#: OCV, INCLUDING the runs that then decline to execute it — which is exactly
#: the case a Tcl-only gate cannot see.
_STANCE_REL = "reports/phase3/mcorner_ocv_stance.json"


def evaluate_stance(data: Optional[dict]) -> Tuple[str, int, dict]:
    """Judge `hold_process_corner` from a multi-corner OCV stance record."""
    report = {"tool": _TOOL, "mode": "stance"}
    if not isinstance(data, dict):
        report.update(verdict="NOT CHECKED", reason="STANCE_UNREADABLE",
                      message="stance record missing or unparseable")
        return "NOT CHECKED", 2, report
    hold = data.get("hold_process_corner")
    report["hold_process_corner"] = hold
    report["setup_process_corner"] = data.get("setup_process_corner")
    report["multi_process_corner"] = data.get("multi_process_corner")
    report["report"] = data.get("report")
    if hold is None:
        report.update(verdict="NOT CHECKED", reason="NO_DECLARED_HOLD_CORNER",
                      message="the run declared no hold process corner at all "
                              "(no SS/TT/FF liberty resolved) — there is no "
                              "hold sign-off corner to judge")
        return "NOT CHECKED", 2, report
    cls = _classify_corner(str(hold))
    report["hold_corner_class"] = cls
    if cls == "FF":
        report.update(verdict="PASS", reason="HOLD_AT_FF",
                      message=f"hold sign-off role is declared at "
                              f"{hold} — the fast corner, worst-case for hold")
        return "PASS", 0, report
    report.update(
        verdict="FAIL", reason="HOLD_NOT_AT_FF",
        message=f"the run declares hold_process_corner={hold!r} — hold is "
                f"worst at FF (fast/high-V/low-T), so a hold role assigned to "
                f"{hold!r} under-reports hold violations. multi_process_corner="
                f"{data.get('multi_process_corner')!r}, report="
                f"{data.get('report')!r}: no fast-corner hold analysis was "
                f"performed on this run.")
    return "FAIL", 1, report


#: Hold STA scripts a project-directory run may have produced, most specific
#: first. The multi-corner OCV hold pass is the one that carries a declared
#: hold corner; the glob is the fallback for a hand-run script.
_HOLD_TCL_CANDIDATES = (
    "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl",
    "phase3/stage3/sta/sta_spef_hold.tcl",
)
_HOLD_TCL_GLOB = "phase3/stage3/sta/*hold*.tcl"


def _find_hold_tcl(project: Path) -> Optional[Path]:
    """The ONE hold script this gate reads: most specific candidate first,
    then the glob. Unchanged by the worst-of repair on purpose — that repair
    stops the script being DISCARDED, it does not widen what counts as one."""
    for rel in _HOLD_TCL_CANDIDATES:
        c = project / rel
        if c.is_file():
            return c
    hits = sorted(project.glob(_HOLD_TCL_GLOB))
    return hits[0] if hits else None


def _discover(project: Path) -> List[Tuple[str, Path]]:
    """EVERY hold-sign-off source a PROJECT DIRECTORY published, in the order
    they are reported. `[]` when the run published none.

    It returns a LIST, and that is the whole repair: the previous version
    returned the FIRST hit and the stance was first, so a hold script that
    contradicted the declared field was never opened.
    """
    found: List[Tuple[str, Path]] = []
    stance = project / _STANCE_REL
    if stance.is_file():
        found.append(("stance", stance))
    tcl = _find_hold_tcl(project)
    if tcl is not None:
        found.append(("tcl", tcl))
    return found


#: Worst-of ordering. Read as "worst of the verdicts that were REACHED":
#: NOT CHECKED is the ABSENCE of a verdict, so it can neither raise nor mask
#: one — see the module docstring.
_SEVERITY = {"FAIL": 2, "PASS": 1, "NOT CHECKED": 0}


def _judge_source(kind: str, path: Path) -> Tuple[str, int, dict]:
    """Judge ONE discovered source with the mode-appropriate evaluator."""
    if kind == "stance":
        data = None
        try:
            data = json.loads(path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            data = None
        verdict, rc, report = evaluate_stance(data)
    else:
        try:
            text: Optional[str] = path.read_text(errors="replace")
        except OSError:
            text = None
        verdict, rc, report = evaluate(text, base=path.parent)
        report["mode"] = "tcl"
    report["artefact"] = str(path)
    report["source"] = kind
    return verdict, rc, report


def judge_project(project: Path) -> Tuple[str, int, dict]:
    """Judge a project directory: every published source, WORST wins.

    The deciding source's report is what the caller sees at top level (so the
    JSON shape a reader already knows is preserved), with every source's
    reading published under `sources` and a `contradiction` flag when two
    sources disagree.
    """
    sources = _discover(project)
    if not sources:
        # DISCLOSED SKIP — this run produced no hold sign-off record at all.
        # Not a pass (nothing was verified) and not a failure (nothing claims
        # otherwise); rc=2 is the flow's tier for that.
        return "NOT CHECKED", 2, {
            "tool": _TOOL, "mode": "project",
            "verdict": "NOT CHECKED",
            "reason": "NO_HOLD_SIGNOFF_ARTEFACT",
            "artefact": str(project),
            "project": str(project),
            "sources": [],
            "message": f"no multi-corner OCV stance record ({_STANCE_REL}) "
                       f"and no hold STA script under phase3/stage3/sta — "
                       f"this run has no hold sign-off corner to judge"}

    judged = [(k, *_judge_source(k, p)) for k, p in sources]
    worst = max(judged, key=lambda j: _SEVERITY.get(j[1], 0))
    _kind, verdict, rc, report = worst
    report = dict(report)
    report["deciding_source"] = _kind
    report["sources"] = [
        {"source": k, "artefact": r.get("artefact"), "verdict": v,
         "reason": r.get("reason"), "message": r.get("message")}
        for k, v, _rc, r in judged]
    distinct = {v for _k, v, _rc, _r in judged}
    if len(distinct) > 1:
        report["contradiction"] = True
        pairs = ", ".join(f"{k}={v}" for k, v, _rc, _r in judged)
        report["message"] = (
            f"{report.get('message', '')} "
            f"[CONTRADICTION — this run's hold sign-off sources DISAGREE "
            f"({pairs}); the worst reading decides, because a declared field "
            f"does not outrank the evidence it claims to summarise]").strip()
    report["project"] = str(project)
    return verdict, rc, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Confirm hold analysis uses the FF (fast) corner. The "
                    "positional may be a hold-analysis artefact OR a project "
                    "directory (in which case EVERY hold sign-off source the "
                    "run published — the declared multi-corner OCV stance AND "
                    "its hold STA script — is judged and the WORST decides).")
    ap.add_argument("hold_artefact", nargs="?",
                    help="hold-analysis Tcl / SDC / log that drives the "
                         "min-path (hold) check, or a project directory")
    ap.add_argument("--stance",
                    help="judge hold_process_corner from this "
                         "mcorner_ocv_stance.json directly")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    if not args.hold_artefact and not args.stance:
        ap.error("supply a hold artefact / project directory, or --stance")

    report: dict
    if args.stance:
        sp = Path(args.stance)
        data = None
        if sp.is_file():
            try:
                data = json.loads(sp.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError):
                data = None
        verdict, rc, report = evaluate_stance(data)
        report["artefact"] = str(sp)
    else:
        p = Path(args.hold_artefact)
        if p.is_dir():
            verdict, rc, report = judge_project(p)
        else:
            text: Optional[str]
            if not p.is_file():
                text = None
            else:
                try:
                    text = p.read_text(errors="replace")
                except OSError:
                    text = None
            verdict, rc, report = evaluate(text, base=p.parent)
            report["artefact"] = str(p)

    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"=== {_TOOL} === verdict: {verdict}")
    if rc == 2:
        # The flow reads rc=2 as the disclosed-skip tier; print the sentinel so
        # a human reading the log sees the same thing the aggregator does.
        print(f"VACUOUS_PASS: {_TOOL} — NOT CHECKED "
              f"[{report.get('reason')}]: {report.get('message')}")
    if report.get("judged_corners"):
        print(f"  judged corners: {report['judged_corners']} "
              f"(basis: {report.get('corner_basis')})")
    if report.get("extra_library_corners"):
        print(f"  extra library corners (disclosed, not judged): "
              f"{report['extra_library_corners']}")
    # Which verdicts are CONTENT-backed. A reader who cannot tell a corner
    # read out of a Liberty header from one guessed off a filename cannot tell
    # how much the verdict is worth.
    for lb in report.get("liberty_declared_corners") or []:
        print(f"  liberty DECLARES {lb['declared_corners']}: {lb['liberty']}")
    # The third state, printed as itself. A reader who only sees "FAIL" cannot
    # tell "the hold corner is wrong" from "the hold corner was never read",
    # and those call for different repairs.
    for c in report.get("hold_corner_contradictions") or []:
        print(f"  NOT MEASURED — the line contradicts itself: {c}")
    for u in report.get("hold_corner_unreadable_assignments") or []:
        print(f"  NOT MEASURED — corner assignment unreadable: {u}")
    if report.get("hold_process_corner") is not None:
        print(f"  declared hold_process_corner: "
              f"{report['hold_process_corner']!r}")
    # Every source that was read, whether or not it decided — a reader who
    # only ever sees the winning line cannot tell a corroborated verdict from
    # an uncorroborated one, which is the distinction this repair added.
    for s in report.get("sources") or []:
        mark = " <- DECIDES" if s["source"] == report.get(
            "deciding_source") else ""
        print(f"  source[{s['source']}] {s['verdict']} "
              f"[{s.get('reason')}] {s.get('artefact')}{mark}")
    if report.get("contradiction"):
        print("  CONTRADICTION: the sources disagree; the WORST reading "
              "decides — a declared field does not outrank the evidence it "
              "claims to summarise")
    if verdict == "FAIL":
        print(f"  FAIL [{report.get('reason')}]: {report.get('message')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
