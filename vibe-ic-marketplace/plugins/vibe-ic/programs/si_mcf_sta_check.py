#!/usr/bin/env python3
"""si_mcf_sta_check.py — GATE for the MCF-bounded SI-aware STA (si_mcf_sta.py).

WHAT IT VERIFIES (false-clean-proof)
====================================
The emitter (`si_mcf_sta.py`) folds every coupling cap ``Cc`` into the victim's
grounded cap at the corner's Miller Coupling Factor, then re-runs OpenSTA. A
dishonest / buggy emitter could SILENTLY DROP the ``Cc*MCF`` (leave the bounded
SPEF at the plain grounded caps) and then report an unchanged, rosy slack — a
false-clean. This gate INDEPENDENTLY re-derives the fold from the ORIGINAL
coupling SPEF (trusting none of the emitter's arithmetic) and proves the bounded
SPEF actually carries it:

  1. RE-DERIVE, per victim net, the window-justified fold ``Cc*MCF`` from the
     original SPEF + the tool-produced timing-window JSON (exact). If that JSON
     is unavailable, fall back to the window-INDEPENDENT floor (setup: every Cc
     at MCF>=1; hold: MCF>=0) so a dropped Cc is still caught.
  2. MEASURE each net's grounded-cap increase in the bounded SPEF and require it
     to be >= the re-derived fold (minus tolerance). A silently-dropped Cc*MCF
     -> increase ~0 while expected > 0 -> FAIL.
  3. Require the bounded SPEF to retain NO coupling (2-node) caps — they must
     have been folded to ground; and require the fold not to EXCEED the MCF
     ceiling (setup: 2*sum(Cc)) so an inflated fold is caught too.
  4. MONOTONICITY: folding MORE cap can only DEGRADE setup slack, folding LESS
     can only degrade hold slack. If the report claims the SI-bounded slack is
     BETTER than the nominal grounded slack (after > before), that contradicts
     the physics of the bound -> FAIL ("reported slack better than the bound").

THE ZERO THIS GATE USED TO SIGN OFF
===================================
Every re-derivation above is denominated in COUPLING PAIRS. The gate counted
them (``coupling_pairs``), printed the count in its summary, and then never
turned it into anything: rules 1-3 iterate ``expected``, which is derived from
the pairs, so with zero pairs ``nets_checked`` is 0, ``violations`` is empty,
``ok`` is True — and the verdict was ``PASS`` with ``findings: []``. A SPEF
carrying only grounded caps therefore produced a sign-off byte-identical to one
whose fold was fully re-derived and proved. That is precisely the false-clean
the gate exists to prevent, one level up from the one it was written to catch.

MEASURED, ON THIS REPO'S OWN PUBLISHED BENCHMARK DATA — not a hypothetical. The
tracked corpus (``git ls-files | grep '\\.spef$'`` -> 20 files) carries the same
tracked design extracted under three PDK variants. Two of them carry 4,932 and
5,292 coupling ``*CAP`` entries; the third carries 2,184 grounded entries across
465 net records and **0** coupling entries, and its committed
``reports/phase3/si_mcf_sta.json`` records ``coupling_pairs: 0`` beside
``verdict: PASS``. Running this gate on those tracked artefacts, pre-change:
``verdict PASS``, ``rc 0``, ``nets_checked {setup: 0, hold: 0}``. Post-change:
``VACUOUS_PASS``, ``rc 2``, with the reason written down. The coupled siblings
compare 366 nets per corner and PASS on both trees (365 / 364 of those
comparisons are falsifiable — see the denominator note below). The false-clean
was landed and published.

AND IT IS NOT RE-DERIVABLE FROM THE TREE AS PUBLISHED, WHICH IS ITS OWN BUG.
That committed report's ``spef`` field is an ABSOLUTE PATH inside the authoring
machine's campaign directory. On any other host ``Path(orig_spef).exists()`` is
False, this gate exits down its ``NO_SPEF`` branch at rc 1, and the
coupling-count decision under discussion is never reached — so a reviewer
re-running the published before/after measures a DIFFERENT BRANCH of this gate
and cannot confirm either number. (Repairing the path in a scratch copy of the
same tracked BYTES reproduces the table above exactly; the artefact is sound,
its recorded path is not.) ``shipped_path_portability_check`` covers plugin
source and does not look at ``benchmark-data`` reports, so nothing in the repo
catches it. NOT FIXED HERE — the emitter still writes absolute paths and this
change does not alter that.

So the demonstration is pinned on a fixture that ships with the repo:
``programs/tests/fixtures/si_mcf_zero_coupling/`` holds two complete project
directories differing by exactly one 4-token coupling ``*CAP`` line and naming
no path outside themselves. Pre-change both exit ``rc 0 PASS`` with identical
``pass`` / ``errors_count`` / ``findings_count``; post-change the grounded-only
one exits ``rc 2 VACUOUS_PASS`` (examined 0 of 0) and the coupled one still
exits ``rc 0 PASS`` (examined 2 of 4, ``folds_proved_per_corner
{setup: 2, hold: 0}`` — the same structural hold-corner hole as the 1,558-pair
tracked sibling's ``{setup: 365, hold: 0}``). Pinned by
``test_si_zero_coupling_fixture_transition.py``, which drives the real CLI and
reads rc plus the emitted JSON.

NO SIGN-OFF WITHOUT A DENOMINATOR. The gate now states, in
``summary.denominator`` (``_gate_denominator``), how many victim-net fold
re-derivations it actually PROVED — and when that number is 0 it is not a
PASS. It is a DISCLOSED SKIP: verdict ``VACUOUS_PASS``, rc 2, a
``VACUOUS_PASS:`` token on stderr, and a written reason.

AND THE DENOMINATOR COUNTS PROOFS, NOT VISITS — the first cut of this fix did
not, and an adversarial pass broke it there. ``independent_recount``'s own
``nets_checked`` counts nets that ENTERED its loop; a net whose re-derived
expectation is 0.0 enters it and its assertion becomes ``increase >= -1e-9``,
which no bounded SPEF that merely failed to fold can violate. Two states hit
that at full scale:

  * COUPLING CAPS WITH ZERO VALUE. The pairs exist, ``floor_folded_caps`` keys
    every victim net, ``nets_checked`` is maximal, every expectation is 0.
    Measured on a derivative of a tracked coupled artefact whose 4,932 two-node
    ``*CAP`` values were collapsed to 0 (16% of them already are 0 as tracked):
    the first cut reported ``examined 732``, a denominator block byte-identical
    to the genuinely-proved run, and rc 0 PASS. It now reports
    ``considered 732, examined 0`` -> VACUOUS_PASS, rc 2.
  * THE HOLD CORNER IN FLOOR MODE, BY CONSTRUCTION. ``MCF_HOLD_WORST`` is 0, so
    ``floor_folded_caps(pairs, "hold")`` is 0.0 for every net and no hold
    comparison can fail on the fold axis. Every real-artefact run in this
    repo's tracked corpus is floor mode (the windows JSON path is machine-local
    and absent), so the honest headline for a coupled tracked variant is
    ``examined 365`` of ``considered 732``, not 732. ``details`` carries both
    axes per corner (``nets_compared_per_corner`` / ``folds_proved_per_corner``)
    so ``{"setup": 365, "hold": 0}`` is readable without re-deriving it. NOT
    CLOSED BY THIS CHANGE: a bounded SPEF that drops the hold fold entirely
    still exits 0 in floor mode, because in floor mode there is no lower bound
    to violate. The change makes that gap visible in the report; whether a
    corner proving nothing should move the whole verdict is a sign-off-policy
    question, not a bug.

WHY A SKIP AND NOT A FAIL — the two causes of a zero, and how far they separate.
A grounded-only extraction (mode, corner, or a tool that emitted no 2-node caps)
genuinely leaves the SI fold nothing to verify; failing it would trade a
false-clean for a false-alarm. A SPEF that is not the one the numbers came from
(wrong file, truncated, a parse that matched nothing) means the gate is
reporting on the wrong artefact. From what this checker can observe the two are
PARTLY separable, and only partly:

  * SEPARABLE — the file the report names resolves to NO net at all under ALL
    THREE readings this gate has: the ``*D_NET`` recount, the shared
    ``parse_spef`` (which additionally models ``*D_PNET`` and pin membership),
    and the ``*R_NET`` reduced-format count — ``SPEF_NO_NET_RECORDS``.
    Requiring all three is what keeps this from failing a SPEF whose shape some
    of them do not model. TWO READINGS WERE NOT ENOUGH: neither the recount nor
    ``parse_spef`` models the REDUCED (``*R_NET``) form, so the two-reading
    version hard-FAILED a legal IEEE-1481 artefact that this repo's own
    ``spef_extraction_check`` certifies as sound (``has_nets = bool(d_nets or
    r_nets)``) — one half of a single change calling the other half's clean
    artefact the wrong file. A reduced-format SPEF now takes the skip tier,
    with a reason naming why a lumped RC pi model has no per-net fold to
    re-derive. Nothing carrying slack numbers can come from a file that is
    empty under all three. ERROR.
  * SEPARABLE — the emitter's own report says it saw ``coupling_pairs > 0`` and
    the gate re-parsing the SAME path sees none (``COUPLING_LOST_SINCE_EMIT``).
    Both use the same parser on the same file, so the bytes changed after the
    numbers were produced. ERROR. (The mirror direction — gate sees pairs the
    emitter did not — needs no new rule: the recount then finds residual
    coupling or a missing fold and FAILs on rule 2/3.)
  * SEPARABLE — with no coupling in the original, the bounded SPEF still
    carries MORE grounded charge than the original (``FOLD_WITHOUT_SOURCE``).
    There was nothing to fold, so the two files are not a matched pair. This is
    the over-application half of rule 3, which was unreachable at zero pairs
    because its ceiling is derived from the pairs. ERROR.
  * NOT SEPARABLE — a well-formed SPEF of the WRONG design, or a
    correctly-read grounded-only extraction. Both parse to net records, grounded
    caps and zero pairs, and nothing in the checker's inputs tells them apart.
    This is the conservative tier: VACUOUS_PASS, whose written reason states
    that a reader may NOT conclude anything about crosstalk delay from it.

A PAIR IS NOT A CAP, and the disclosure must not trade one for the other.
``coupling_pairs`` counts INTER-NET pairs after ``parse_spef`` has resolved both
node ends and dropped any two-node cap landing twice on the same net; on one
tracked artefact 4,932 coupling ``*CAP`` entries collapse to 1,558 pairs. A
reason that reported the pair count under the words "two-node capacitances"
would therefore state a falsehood about a file that plainly carries them —
which is what the first cut of this fix did. Both numbers are now measured
(``coupling_caps`` via ``si_mcf_sta.count_coupling_caps``) and the reason names
whichever it means, including the case where caps exist but couple no two
distinct nets.

WHERE THE WRITTEN REASON DOES AND DOES NOT SURFACE. It is in the JSON report
(``summary.denominator.not_applicable_reason``) and on stderr. It does NOT
reach the flow's per-step listing: ``flow_compliance_check.
_check_program_exit_zero`` discards the captured snippet on rc 2 and returns
the generic ``__VACUOUS_HINT__`` marker, so the step renders with the repo-wide
"input not applicable" wording rather than this gate's own prose. That is a
pre-existing convention shared by every rc-2 gate; changing it is a repo-wide
behaviour change and is deliberately not made here. A reviewer who needs the
reason must read the JSON.

AND THE SAME DEFECT ONCE RAN INVERTED — a run that examined NOTHING reported as
a design defect (#506). Until this was split, the verdict precedence was "any
ERROR outranks vacuity", and the gate had THREE verdict tokens for FOUR states.
The fourth — THE GATE COULD NOT OBTAIN ITS INPUT — had nowhere to go, so a run
whose ``spef`` path does not exist on the reading host emitted, in one JSON,
``verdict: FAIL`` beside ``vacuous: true`` and a reason ending "Read this as NOT
CHECKED". Two contradictory answers in one artefact: a reader keying on
``verdict`` learned the design failed SI sign-off, a reader keying on
``vacuous`` learned nothing had been checked. On a PUBLISHED report whose
``spef`` field is an absolute path from the authoring machine (see the paragraph
above — still not fixed in the emitter), that made the verdict a function of
WHICH HOST read the file, and the visible remedy for "this design fails SI" is
to go change the design.

THE ERROR CATEGORIES ARE NOT ONE KIND OF THING, and ``NOT_RUN_CATEGORIES`` is
where that is written down:

    NO_REPORT  BAD_JSON  NO_SPEF  NO_CORNER  NO_BOUNDED_SPEF
        the gate never got to look                            -> ``NOT_RUN``
    SPEF_NO_NET_RECORDS  COUPLING_LOST_SINCE_EMIT
    FOLD_WITHOUT_SOURCE  FOLD_NOT_APPLIED  SLACK_BETTER_THAN_BOUND
        the gate looked at a real artefact and it was wrong    -> ``FAIL``

Only the first list is enumerated. Anything NOT on it is a substantive defect,
so a category added later defaults to the LOUD tier and can never be demoted
into a skip by omission — the fail-safe direction for a gate whose whole purpose
is catching a false-clean.

THE EXIT CODE DELIBERATELY DOES NOT MOVE. ``NOT_RUN`` is rc 1, exactly as the
FAIL it was carved out of, and the "1 = FAIL and every refused / mis-invoked
run" policy below is UNCHANGED by #506. The tempting alternative — rc 2, the
disclosed-skip tier — was measured against ``flow_compliance_check.
_check_program_exit_zero``, which credits rc 2 as a PASS unconditionally.
``NO_BOUNDED_SPEF`` fires when the emitter's OWN report names a bounded SPEF
that is absent: an INCOMPLETE SIGN-OFF, not an inapplicable one. Under rc 2 that
step would render as a vacuous pass and a genuinely broken sign-off would look
skipped — trading #506's false negative for a false clean, which is the very
trade this gate exists to refuse. #506 asked for ONE answer per artefact, not
for a quieter one: the token disambiguates, the exit code stays loud.

CONSEQUENTLY ``summary.vacuous`` IS THE VERDICT TIER, NOT THE RAW ZERO. Three of
the substantive-defect categories (``SPEF_NO_NET_RECORDS``,
``COUPLING_LOST_SINCE_EMIT``, ``FOLD_WITHOUT_SOURCE``) fire with
``examined == 0``, because a file that is the wrong artefact is decided WITHOUT
any fold being re-derivable from it. Deriving ``vacuous`` straight from
``examined`` therefore reproduced the contradiction on those three as well.
``vacuous`` now means "this run reached no conclusion" (true for ``NOT_RUN`` and
``VACUOUS_PASS``, false for ``PASS`` and ``FAIL``); the raw count stays visible
and unmodified at ``summary.denominator.examined``, and a rejected artefact
still owes the written reason ``_gate_denominator`` requires — it is simply the
reason a REJECTED artefact gets (``_rejected_reason``) rather than a skip's, so
the NOT-CHECKED disclaimer never ships beside a decided failure.

A VACUITY A WAIVER MAY ACCEPT IS A SEPARATE FIELD, NOT A SEPARATE CONVENTION
===========================================================================
``details.vacuity_code`` is the token a tapeout acceptance must quote
(``signoff_audit``'s ``si_vacuity_accepted``). ``_vacuity`` has NINE branches
and that contract is unchanged — every one of them still has its own stable
UPPER_SNAKE name, and the could-not-run states keep a machine-readable name
rather than being silenced. What changed in #535 is WHICH FIELD each name is
published in.

MEASURED, driving this CLI over the shipped fixture
``tests/fixtures/si_mcf_zero_coupling/grounded_only`` with one perturbation
each, on the tree before the split::

    perturbation                          rc  verdict       vacuity_code
    (none)                                 2  VACUOUS_PASS  SPEF_NO_COUPLING_PAIRS
    emitter report absent                  1  NOT_RUN       EMITTER_REPORT_UNREADABLE
    emitter report unparseable             1  NOT_RUN       EMITTER_REPORT_UNREADABLE
    named SPEF absent                      1  NOT_RUN       SPEF_UNREADABLE
    no corner record at all                1  NOT_RUN       NO_CORNER_RECOUNTED
    bounded SPEF absent, both corners      1  NOT_RUN       NO_CORNER_RECOUNTED
    HOLD corner absent, SETUP recounts     1  NOT_RUN       SPEF_NO_COUPLING_PAIRS

THE LAST ROW IS THE ONE THAT DECIDES THE DESIGN. Rows 2-6 publish names a
reader can at least recognise as could-not-run states. Row 7 publishes
``SPEF_NO_COUPLING_PAIRS`` — BYTE-IDENTICAL to row 1, the genuine vacuity — on
a run that never obtained its hold corner. So the hazard is not "the
could-not-run states have names of their own that a consumer might mistake for
vacuities". It is that the SAME NAME is published in both states, and no
scheme keyed on the NAME can tell them apart: narrowing which branches may
publish would delete row 1's legitimate disclosure along with row 7's, and a
per-code prefix or namespace would have to prefix row 1 and row 7 identically.
The distinction is a property of the RUN, so the split has to be made where
the run is known.

TWO FIELDS, AND A CODE LANDS IN EXACTLY ONE (``vacuity_publication``):

    details.vacuity_code     WAIVABLE. The gate held every input it audits,
                             looked, and there was nothing to prove.
    details.unwaivable_code  NOT WAIVABLE. Either an input was never obtained
                             (an ERROR in ``NOT_RUN_CATEGORIES`` is present),
                             or the branch is not on ``WAIVABLE_VACUITY_CODES``.

Both are empty when ``examined > 0`` (nothing to explain) and — the guarantee
landed in #533, unchanged and now stated over both channels — when the
artefact was REJECTED. A decided FAILURE publishes NO code in EITHER field, so
there is nothing for an operator to copy into ``si_vacuity_accepted``.

WHY A FIELD RATHER THAN A CONVENTION. The two consumer-side defences in
``signoff_audit`` (the body-outranks-the-label defect read, and ``NOT_RUN`` not
being one of the verdicts it credits) are untouched and still pinned; this is a
third line, not a replacement. The difference is where the guarantee lives. A
convention — "read the defect channel first" — has to be re-earned by every
consumer written from now on. A field cannot be: a consumer that reads
``details["vacuity_code"]`` is structurally incapable of seeing an un-waivable
state, whether or not its author ever heard the rule.

Exit 0 = PASS (every corner's bound is genuinely applied + reported honestly),
1 = FAIL **and every refused / mis-invoked run** (including the ``NOT_RUN``
tier — see above), 2 = VACUOUS_PASS (nothing was re-derived; NOT a sign-off).
rc 2 was formerly the arg-error code; it is now reserved for the disclosed skip,
because ``flow_compliance_check._check_program_exit_zero`` credits rc 2 as a
pass unconditionally and an argparse-rejected invocation must never be credited
as one (same reasoning as ``drc_report_check``). Writes
reports/phase3/si_mcf_sta_check.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _gate_denominator as _gd
import _path_layout as _pl
import _record_adjudication as _ra
import si_mcf_sta as M

#: Exit codes. 2 is the DISCLOSED SKIP tier, never an error tier — see the
#: module docstring. The ``NOT_RUN`` verdict shares ``RC_FAIL`` on purpose: it
#: is a distinct ANSWER, not a quieter one (#506).
RC_PASS = 0
RC_FAIL = 1
RC_VACUOUS = 2

#: The ERROR categories that mean THE GATE NEVER GOT TO LOOK — the input it
#: audits could not be obtained, read, or located (#506).
#:
#: ENUMERATED IN THIS DIRECTION ON PURPOSE. The complement — "the gate looked at
#: a real artefact and it was wrong" — is NOT listed anywhere, so membership of
#: the loud tier is the DEFAULT. A category added to this gate later is a
#: substantive defect until someone deliberately writes it into this set, which
#: is a reviewable edit; the opposite arrangement would let a new category slip
#: into the skip tier by nobody remembering to list it. For a gate whose whole
#: purpose is catching a false-clean, the failure mode of forgetting must be
#: "too loud", never "too quiet".
NOT_RUN_CATEGORIES = frozenset({
    "NO_REPORT",         # the emitter's report is not there
    "BAD_JSON",          # ... or is not parseable
    "NO_SPEF",           # the SPEF the report names is not on this host
    "NO_CORNER",         # the report carries no record for a corner
    "NO_BOUNDED_SPEF",   # ... or names a bounded SPEF that is not there
})

#: The vacuity codes a tapeout acceptance MAY quote (#535). See the
#: "A VACUITY A WAIVER MAY ACCEPT" section of the module docstring.
#:
#: ENUMERATED IN THE OPPOSITE DIRECTION FROM ``NOT_RUN_CATEGORIES``, for the
#: same fail-safe reason read off a different axis. There the complement is
#: unlisted, so a NEW ERROR CATEGORY defaults to the LOUD verdict tier. Here
#: the complement is unlisted, so a NEW VACUITY BRANCH defaults to
#: UN-WAIVABLE: it is still named, in ``details.unwaivable_code``, where no
#: acceptance can reach it, until someone deliberately writes it into this set
#: — a reviewable edit. Both directions make "nobody remembered" fail towards
#: BLOCKING a tapeout, never towards signing one off.
#:
#: Every member is a state the gate reached WITH THE ARTEFACT IN HAND. The
#: three ``_vacuity`` branches deliberately NOT here — ``EMITTER_REPORT_
#: UNREADABLE``, ``SPEF_UNREADABLE``, ``NO_CORNER_RECOUNTED`` — are the ones
#: whose predicate is an input the gate never obtained.
WAIVABLE_VACUITY_CODES = frozenset({
    "SPEF_REDUCED_FORMAT_ONLY",      # read; states a lumped RC pi model
    "SPEF_NO_D_NET_RECORDS",         # read; no *D_NET to attribute a fold to
    "COUPLING_CAPS_INTRA_NET_ONLY",  # read; every cap resolves within one net
    "SPEF_NO_COUPLING_PAIRS",        # read; no inter-net coupling exists
    "NO_VICTIM_NET_RESOLVED",        # read; no victim resolves to a *D_NET
    "ALL_EXPECTATIONS_ZERO",         # compared; every expectation was 0.0
})

#: The two ``details`` keys a vacuity code may be published under. Neither is a
#: substring of the other, so a consumer grepping for the waivable channel
#: cannot land on the un-waivable one, or the reverse.
VACUITY_CODE_KEY = "vacuity_code"
UNWAIVABLE_CODE_KEY = "unwaivable_code"

#: One unit of what this gate measures. Named here so the report, the reason
#: prose and any consumer sweeping the gate set agree by construction.
#:
#: A COMPARISON IS NOT A PROOF. The recount's own ``nets_checked`` counts nets
#: that ENTERED its loop, which includes every net whose re-derived expectation
#: is exactly 0.0 — the assertion then degenerates to ``increase >= -1e-9`` and
#: cannot fail whatever the bounded SPEF contains. Two states produce that at
#: scale: coupling caps carrying value 0 (already 16% of the entries in one
#: tracked artefact), and the whole HOLD corner in window-independent floor mode
#: (``MCF_HOLD_WORST == 0``, so ``floor_folded_caps`` is 0 for every net).
#: Counting those as examined coverage is the same displaced zero this gate was
#: fixed for, one notch in. ``examined`` therefore counts only the comparisons a
#: dropped fold could actually have FAILED; the wider population lands in
#: ``considered``.
DENOMINATOR_UNIT = ("victim-net MCF folds re-derived and PROVED against the "
                    "bounded SPEF (one per coupled net per corner, counting "
                    "only nets whose re-derived expectation is non-zero — a "
                    "comparison against an expected fold of 0.0 cannot fail "
                    "and proves nothing)")

#: Passed explicitly to ``independent_recount`` so the tolerance the recount
#: applies and the tolerance ``_is_falsifiable`` reasons about cannot drift
#: apart into a denominator that counts comparisons the recount would skip.
RECOUNT_REL_TOL = 0.02
RECOUNT_ABS_TOL_PF = 1e-9

#: Appended to every vacuous reason. The point of the tier is that it says what
#: a reader may NOT conclude, which a bare "PASS" cannot.
_NOT_SAID = (
    " WHAT THIS VERDICT DOES NOT SAY: it is NOT a crosstalk-delay sign-off — "
    "no fold was re-derived, so nothing about SI was verified. The checker "
    "cannot distinguish a genuinely grounded-only extraction from a coupled "
    "one that was replaced, truncated, or never handed to it, beyond the "
    "cases it fails outright; both parse to zero coupling pairs. Read this as "
    "NOT CHECKED.")


@dataclass
class Finding:
    severity: str          # ERROR / WARNING / INFO
    category: str
    message: str


def error_categories(findings: List[Finding]) -> Tuple[List[str], List[str]]:
    """Split the ERROR findings into (could-not-run, examined-and-wrong).

    Order-preserving and de-duplicated, because both lists are quoted verbatim
    into the written reason a reader gets. WARNING / INFO findings are not a
    verdict and never enter either list."""
    not_run: List[str] = []
    defect: List[str] = []
    for f in findings:
        if f.severity != "ERROR":
            continue
        bucket = not_run if f.category in NOT_RUN_CATEGORIES else defect
        if f.category not in bucket:
            bucket.append(f.category)
    return not_run, defect


def _is_falsifiable(expected_fold_pf: float) -> bool:
    """Could a silently-dropped fold have FAILED this net's comparison?

    ``independent_recount`` flags a net when
    ``increase < exp - max(rel_tol*exp, abs_tol)``. With ``exp == 0`` that floor
    is ``-abs_tol``, so any bounded SPEF that did not LOSE charge satisfies it —
    the comparison ran but could not have failed. Written from the same two
    constants the recount is handed, so the two readings cannot diverge."""
    exp = float(expected_fold_pf)
    return exp - max(RECOUNT_REL_TOL * exp, RECOUNT_ABS_TOL_PF) > 0.0


def count_r_net_records(spef_text: str) -> int:
    """Number of ``*R_NET`` (REDUCED-format) net records.

    THE THIRD READING, and the reason ``SPEF_NO_NET_RECORDS`` needs one. IEEE
    1481 reduced format states a net as a driver + a lumped RC pi model instead
    of a detailed node network, so a valid ``*R_NET``-only SPEF resolves to zero
    under ``net_grounded_totals`` (keys on ``*D_NET``) AND zero under
    ``parse_spef`` (models ``*D_NET`` / ``*D_PNET``). Failing on those two
    readings alone therefore hard-FAILED a legitimate artefact that this repo's
    own ``spef_extraction_check`` certifies — it computes
    ``has_nets = bool(d_nets or r_nets)``. Counting the third form is what keeps
    a legal SPEF out of an ERROR whose message asserts the gate is reading the
    wrong file."""
    return sum(1 for raw in spef_text.splitlines()
               if raw.strip().startswith("*R_NET"))


def _load_windows(report: dict, net_driver_pins) -> Tuple[Optional[dict], bool]:
    """Load the emitter's per-pin timing-window JSON. Returns (net_windows, exact).
    exact=False means no window JSON was found (gate uses the floor instead)."""
    wj = report.get("windows_json")
    if wj and Path(wj).exists():
        try:
            timing = json.loads(Path(wj).read_text())
            return M.net_windows_from_timing(timing, net_driver_pins), True
        except (OSError, ValueError):
            return None, False
    return None, False


def audit(project_dir: Path,
          report_path: Optional[Path] = None) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    rp = report_path or _pl.report_path(project_dir, "si_mcf_sta.json")
    stats: dict = {"report": str(rp), "corners_checked": [],
                   "recount": {}, "monotonicity": {}}

    if not rp.exists():
        findings.append(Finding("ERROR", "NO_REPORT",
                                f"si_mcf_sta.json not found at {rp}"))
        return findings, stats
    try:
        report = json.loads(rp.read_text())
    except (OSError, ValueError) as exc:
        findings.append(Finding("ERROR", "BAD_JSON",
                                f"cannot parse si_mcf_sta.json: {exc}"))
        return findings, stats
    stats["report_read"] = True

    orig_spef = report.get("spef")
    if not orig_spef or not Path(orig_spef).exists():
        findings.append(Finding("ERROR", "NO_SPEF",
                                f"original coupling SPEF missing: {orig_spef}"))
        return findings, stats
    orig_text = Path(orig_spef).read_text(errors="replace")
    stats["spef_read"] = True
    sp = M.parse_spef(orig_text)
    pairs = M.coupling_pairs(sp)
    stats["coupling_pairs"] = len(pairs)
    stats["coupling_nets"] = len({n for pair in pairs for n in pair})
    # PAIRS ARE NOT CAPS, and the disclosure prose must not say one and mean the
    # other. `coupling_pairs` is a count of INTER-NET pairs after `parse_spef`
    # has resolved both nodes and DROPPED any 2-node cap whose ends land on the
    # SAME net; on one tracked artefact 4,932 coupling *CAP entries collapse to
    # 1,558 pairs. A file can therefore plainly carry two-node capacitances and
    # still have zero pairs. Both numbers are recorded so the reason can name
    # the one it means.
    stats["coupling_caps"] = M.count_coupling_caps(orig_text)

    # SUBSTANCE OF THE ARTEFACT ABOUT TO BE CERTIFIED. `net_grounded_totals`
    # seeds one entry per `*D_NET` record, so its length is the net-record
    # count AS THE RECOUNT ITSELF SEES IT — a counter that cannot disagree with
    # the code it is guarding.
    orig_grounded = M.net_grounded_totals(orig_text)
    stats["spef_net_records"] = len(orig_grounded)
    stats["emitter_coupling_pairs"] = report.get("coupling_pairs")

    # SECOND AND THIRD INDEPENDENT VIEWS of "did anything parse as a net". The
    # recount's counter keys on `*D_NET` only; the shared `parse_spef` also
    # resolves `*D_PNET` and pin/port membership; neither models the REDUCED
    # (`*R_NET`) form at all. The ERROR below fires only when ALL THREE find
    # nothing, so a SPEF shaped in a way some of them do not model can never be
    # failed by it — the readings that are blind leave a zero in the disclosure
    # instead, and the gate takes its skip tier.
    parsed_nets = (set(sp["cg"]) | set(sp["node_net"].values())
                   | set(sp["net_driver_pins"]) | set(sp["net_load_pins"]))
    stats["spef_parsed_nets"] = len(parsed_nets)
    stats["spef_r_net_records"] = count_r_net_records(orig_text)

    if not orig_grounded and not parsed_nets and not stats["spef_r_net_records"]:
        # Cause (b), decided: the file the report NAMES as the SPEF the slack
        # numbers came from resolves to no net at all, by either reading.
        # Whatever it is, the reported STA cannot have been derived from it, so
        # this gate is certifying the wrong artefact. Not a skip — a
        # contradiction.
        findings.append(Finding(
            "ERROR", "SPEF_NO_NET_RECORDS",
            f"the SPEF named by the report resolves to 0 nets under ALL THREE "
            f"readings — the *D_NET recount, the shared SPEF parser "
            f"(*D_NET/*D_PNET) and the *R_NET reduced-format count: "
            f"{orig_spef} — a report carrying corner slacks cannot have come "
            f"from it; the gate is reading the wrong artefact"))
        return findings, stats

    emitted_pairs = report.get("coupling_pairs")
    if isinstance(emitted_pairs, int) and emitted_pairs > 0 and not pairs:
        # Cause (b), decided: emitter and gate ran the SAME parser over the
        # SAME path and disagree about whether coupling EXISTS. The bytes
        # changed after the numbers were produced.
        findings.append(Finding(
            "ERROR", "COUPLING_LOST_SINCE_EMIT",
            f"the report states it extracted {emitted_pairs} coupling pair(s) "
            f"from {orig_spef}, but re-parsing that path with the same parser "
            f"finds 0 — the SPEF is not the one the reported slacks were "
            f"derived from"))

    net_windows, exact = _load_windows(report, sp["net_driver_pins"])
    stats["windows_exact"] = exact
    guard = float(report.get("overlap_guard_ns", 0.0) or 0.0)

    corners = report.get("corners", {})
    nominal = report.get("nominal", {})
    for corner in ("setup", "hold"):
        cinfo = corners.get(corner)
        if not isinstance(cinfo, dict):
            findings.append(Finding("ERROR", "NO_CORNER",
                                    f"report missing corner '{corner}'"))
            continue
        bounded = cinfo.get("bounded_spef")
        if not bounded or not Path(bounded).exists():
            findings.append(Finding("ERROR", "NO_BOUNDED_SPEF",
                                    f"{corner}: bounded SPEF missing: {bounded}"))
            continue
        bounded_text = Path(bounded).read_text(errors="replace")

        # (1-3) independent cap-level recount (the false-clean-proof).
        # `expected` is computed HERE for both modes — identical arithmetic to
        # what `independent_recount` would do internally when handed None — so
        # the gate can count how many of those comparisons were capable of
        # failing without re-deriving the fold a second time or guessing.
        if exact:
            expected, _worst = M.victim_folded_caps(pairs, net_windows or {},
                                                    corner, guard)
        else:
            expected = M.floor_folded_caps(pairs, corner)
        rc = M.independent_recount(orig_text, bounded_text,
                                   net_windows or {}, corner, guard,
                                   rel_tol=RECOUNT_REL_TOL,
                                   abs_tol_pf=RECOUNT_ABS_TOL_PF,
                                   expected=expected)
        # THE LOAD-BEARING HALF of `nets_checked`. `independent_recount` skips a
        # net with no *D_NET block, so intersecting with `orig_grounded` matches
        # its loop exactly; `_is_falsifiable` then keeps only the nets whose
        # expectation a dropped fold could have violated.
        proved = sum(1 for net, exp in expected.items()
                     if net in orig_grounded and _is_falsifiable(exp))
        stats["recount"][corner] = {
            "ok": rc["ok"], "nets_checked": rc["nets_checked"],
            "folds_proved": proved,
            "residual_coupling_caps": rc["residual_coupling_caps"],
            "violations": rc["violations"][:20],
            "mode": "exact-window" if exact else "window-independent-floor",
        }
        stats["corners_checked"].append(corner)

        # (3b) THE OVER-APPLICATION HALF OF RULE 3, AT ZERO PAIRS. The recount's
        # ceiling is `MCF * sum(Cc)` per net, so with no coupling pairs the
        # ceiling is 0 for every net and the loop that would enforce it never
        # runs (`expected` is empty). Enforce it directly: nothing to fold means
        # the bounded SPEF must not carry MORE grounded charge than the
        # original. If it does, the emitter folded from a source that is not in
        # the file this gate read — cause (b), decided.
        if not pairs:
            bounded_g = M.net_grounded_totals(bounded_text)
            inflated: List[str] = []
            for net, before in orig_grounded.items():
                after = bounded_g.get(net, before)   # net absent => no delta
                if after - before > max(1e-9, 0.02 * abs(before)):
                    inflated.append(net)
            stats["recount"][corner]["fold_without_source_nets"] = len(inflated)
            if inflated:
                findings.append(Finding(
                    "ERROR", "FOLD_WITHOUT_SOURCE",
                    f"{corner}: the original SPEF carries no coupling caps, yet "
                    f"{len(inflated)} net(s) gained grounded charge in the "
                    f"bounded SPEF — the fold has no source in the file this "
                    f"gate read; the two SPEFs are not a matched pair"))

        if not rc["ok"]:
            n = len(rc["violations"])
            findings.append(Finding(
                "ERROR", "FOLD_NOT_APPLIED",
                f"{corner}: {n} net(s) fail the independent MCF recount "
                f"(Cc*MCF under/over-applied or coupling not folded) — "
                f"the bounded SPEF does not carry the re-derived bound"))

        # (4) monotonicity vs the nominal grounded run
        before = cinfo.get("worst_slack_before_ns")
        after = cinfo.get("worst_slack_after_ns")
        mono_ok = True
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            # setup: MORE cap => after <= before; hold: LESS cap => after <= before.
            # a tiny positive epsilon tolerates STA rounding at the reported digits.
            if after > before + 5e-3:
                mono_ok = False
                findings.append(Finding(
                    "ERROR", "SLACK_BETTER_THAN_BOUND",
                    f"{corner}: reported SI-bounded slack {after} ns is BETTER "
                    f"than the nominal grounded {before} ns — a conservative "
                    f"MCF bound can only DEGRADE it; number is not honest"))
        stats["monotonicity"][corner] = {
            "before_ns": before, "after_ns": after, "ok": mono_ok}

    _ = nominal  # (kept for future cross-checks; corner records carry before/after)
    return findings, stats


def _vacuity(stats: dict) -> Tuple[str, str]:
    """``(code, prose)`` naming what was searched for and not found (#496).

    The PROSE is what a human reads. The CODE is what a machine may cite: a
    stable UPPER_SNAKE token identifying WHICH vacuity this is, so a consumer
    that must decide whether a specific vacuity was accepted does not have to
    substring-match a paragraph of English. Prose is rewritten whenever it can
    be made clearer; a code is a contract. Both are derived from the SAME
    branch, so they cannot disagree about which state the gate is in.

    A consumer requiring the code to be named ALSO gets expiry for free: when
    the underlying state changes (a grounded-only extraction replaced by an
    unreadable SPEF, say) the code changes, and an acceptance recorded against
    the old code no longer matches the new one.

    Only ever consumed when the gate examined 0 units AND rejected nothing. A
    zero reached by REJECTING the artefact is a decided FAILURE, not a vacuity,
    and ``denominator`` publishes no code for it — see the branch there. It is
    computed unconditionally so ``Denominator`` can never be constructed
    without a reason."""
    recount = stats.get("recount", {}) or {}
    pairs = int(stats.get("coupling_pairs") or 0)
    caps = int(stats.get("coupling_caps") or 0)
    nets = int(stats.get("spef_net_records") or 0)
    r_nets = int(stats.get("spef_r_net_records") or 0)
    compared = sum(int((v or {}).get("nets_checked", 0) or 0)
                   for v in recount.values())
    if not stats.get("report_read"):
        code = "EMITTER_REPORT_UNREADABLE"
        why = ("the emitter's si_mcf_sta.json could not be read, so no fold "
               "was re-derived.")
    elif not stats.get("spef_read"):
        code = "SPEF_UNREADABLE"
        why = ("the coupling SPEF the report names could not be read, so no "
               "fold was re-derived.")
    elif not nets and r_nets:
        code = "SPEF_REDUCED_FORMAT_ONLY"
        why = (f"the SPEF the report names carries {r_nets} *R_NET record(s) "
               f"and no *D_NET block. The REDUCED format states a lumped RC pi "
               f"model instead of the node-level capacitances this gate folds, "
               f"so there is nothing here to re-derive a per-net fold from.")
    elif not nets:
        code = "SPEF_NO_D_NET_RECORDS"
        why = (f"the SPEF the report names parses to 0 *D_NET records "
               f"({stats.get('spef_parsed_nets', 0)} net(s) resolved by the "
               f"shared parser), so there is no net to attribute a fold to.")
    elif not recount:
        code = "NO_CORNER_RECOUNTED"
        why = ("no corner produced a bounded SPEF this gate could recount, so "
               "the MCF fold was never re-derived.")
    elif caps and not pairs:
        # A count of CAPS is not a count of PAIRS: `parse_spef` drops a 2-node
        # cap whose ends resolve to the same net, so this state is reachable
        # with plainly-present two-node capacitances.
        code = "COUPLING_CAPS_INTRA_NET_ONLY"
        why = (f"the SPEF named by the report parses to {nets} net record(s) "
               f"and {caps} two-node (coupling) *CAP entr(y/ies), but none of "
               f"them couples two DIFFERENT nets — every one resolves within a "
               f"single net — so there is no inter-net fold to re-derive.")
    elif not pairs:
        code = "SPEF_NO_COUPLING_PAIRS"
        why = (f"the SPEF named by the report parses to {nets} net record(s), "
               f"0 two-node (coupling) *CAP entries and therefore 0 inter-net "
               f"coupling pairs, so the MCF fold has nothing to re-derive.")
    elif not compared:
        code = "NO_VICTIM_NET_RESOLVED"
        why = (f"{pairs} coupling pair(s) parsed, but none of their victim "
               f"nets resolves to a *D_NET block carrying grounded caps, so "
               f"no fold could be measured against the bounded SPEF.")
    else:
        code = "ALL_EXPECTATIONS_ZERO"
        why = (f"{pairs} coupling pair(s) parsed and {compared} victim-net "
               f"comparison(s) ran, but EVERY one carried a re-derived "
               f"expectation of 0.0 — a comparison a dropped fold could not "
               f"have failed. Reachable when the coupling capacitances "
               f"themselves are zero-valued, and by construction on the hold "
               f"corner in window-independent floor mode (MCF is 0 there). "
               f"Nothing was proved about the fold.")
    return code, why + _NOT_SAID


def vacuity_publication(code: str, not_run: bool) -> Tuple[str, str]:
    """``(vacuity_code, unwaivable_code)`` — WHICH FIELD may carry ``code`` (#535).

    Exactly one of the two is ``code`` and the other is ``""``. See the
    "A VACUITY A WAIVER MAY ACCEPT" section of the module docstring for the
    measurement this exists for.

    TWO CONDITIONS, AND NEITHER SUBSUMES THE OTHER — which is why both are
    written:

    * ``not_run`` demotes a code that IS on the waivable list. Reachable today:
      the SETUP corner recounts to zero coupling pairs while the HOLD corner is
      missing, which publishes ``SPEF_NO_COUPLING_PAIRS`` — a genuinely
      waivable name — on a run that never obtained an input. Set membership
      alone cannot see this, because the name is the same one row 1 publishes.
    * set membership demotes a code that arrives with no ``NOT_RUN`` finding to
      demote it. Nothing reaches that state through ``audit`` today — all three
      unlisted branches require an input the gate could not obtain, and every
      one of those raises a ``NOT_RUN_CATEGORIES`` ERROR. It is the guard for a
      TENTH BRANCH added later: whatever state it names, and whatever findings
      accompany it, it is named in ``unwaivable_code`` until someone writes it
      into ``WAIVABLE_VACUITY_CODES`` on purpose.

    The default direction is the whole point. A branch nobody classified is
    un-waivable, so forgetting blocks a tapeout instead of signing one off.
    """
    if not_run or code not in WAIVABLE_VACUITY_CODES:
        return "", code
    return code, ""


def _vacuous_reason(stats: dict) -> str:
    """The prose half of :func:`_vacuity`. Kept as the name #496's contract
    refers to; the branch logic lives in one place."""
    return _vacuity(stats)[1]


def _rejected_reason(defect_categories: List[str]) -> str:
    """The written reason a DECIDED FAILURE with a zero denominator owes (#506).

    Three substantive-defect categories fire with ``examined == 0``:
    ``SPEF_NO_NET_RECORDS``, ``COUPLING_LOST_SINCE_EMIT`` and
    ``FOLD_WITHOUT_SOURCE``. A file that is the WRONG ARTEFACT is decided
    without any fold being re-derivable from it, so the zero is real — but
    ``_vacuous_reason``'s prose ends "Read this as NOT CHECKED", which denies a
    conclusion the gate demonstrably reached. Shipping that beside
    ``verdict: FAIL`` is the #506 contradiction with the categories swapped.

    ``_gate_denominator.Denominator`` still REQUIRES a reason at zero and that
    requirement is kept: the zero is disclosed, it is simply disclosed as what
    it is."""
    cats = ", ".join(defect_categories) or "a substantive finding"
    return (f"no victim-net fold was re-derived because the artefact was "
            f"REJECTED before one could be: {cats}. WHAT THIS VERDICT DOES "
            f"SAY: the gate DID reach a conclusion about the artefact it was "
            f"handed and that conclusion is a FAILURE — this zero is a decided "
            f"verdict, not a skip, and must not be read as one. The findings "
            f"carry it.")


def denominator(stats: dict,
                findings: Optional[List[Finding]] = None) -> _gd.Denominator:
    """What the re-derivation actually PROVED (#496).

    ``examined`` is the number of victim-net comparisons a silently-dropped
    fold could have FAILED — the recount's own loop, minus every net whose
    re-derived expectation is 0.0 and whose assertion therefore degenerates to
    ``increase >= -1e-9``. ``considered`` is the wider population that entered
    that loop (the old ``nets_checked``), kept so ``considered > 0`` with
    ``examined == 0`` — the exact shape #496 exists to make visible — is
    readable straight off the report instead of only from the source.

    Per-corner counts are in ``details`` on BOTH axes, because the two diverge
    structurally: in window-independent floor mode the hold corner's
    expectation is 0 for every net, so it contributes comparisons and no
    proofs, and a reader must be able to see that without re-deriving it.

    ``findings`` (optional, #506) selects WHICH written reason a zero gets: a
    zero reached because the artefact was REJECTED is a decided verdict, not a
    skip, and must not carry the skip's NOT-CHECKED disclaimer. Omitting the
    argument keeps the pre-#506 behaviour for direct callers that only have the
    stats dict.

    The same choice governs the machine-citable name a tapeout waiver must
    quote to accept a vacuity. FOUR STATES, and only the last names itself in
    the field an acceptance can reach:

        examined > 0              -> no reason, no code at all
        examined == 0, defect     -> rejected reason, NO CODE IN EITHER FIELD
                                     (a decided FAILURE is not a waivable
                                     vacuity — #533)
        examined == 0, no defect,
          could-not-run           -> vacuity prose, code in `unwaivable_code`
                                     (named for a human and a machine, out of
                                     reach of `si_vacuity_accepted` — #535)
        examined == 0, no defect,
          gate held its inputs    -> vacuity prose AND its `vacuity_code`

    Every code comes from the same ``_vacuity`` call as the prose beside it, so
    the code can never name a state the prose contradicts; and
    ``vacuity_publication`` chooses the FIELD from the same ``findings`` list
    the ``defect`` split above is read from, so the two cannot disagree about
    what the run was."""
    recount = stats.get("recount", {}) or {}
    examined = sum(int((v or {}).get("folds_proved", 0) or 0)
                   for v in recount.values())
    considered = sum(int((v or {}).get("nets_checked", 0) or 0)
                     for v in recount.values())
    not_run, defect = error_categories(findings or [])
    code, prose = _vacuity(stats)
    vacuity_code = unwaivable_code = ""
    # ONE BRANCH DECIDES THE PROSE AND THE CODE AND THE FIELD, and the
    # assignment is written per-branch rather than as independent conditions
    # further down. `not_applicable_reason`, `vacuity_code` and
    # `unwaivable_code` describe the SAME state; a separate `if` for each is
    # another place to remember, and those conditions drifting apart is
    # precisely how the code would come to name a vacuity the prose says is not
    # one, or to name it in the field an acceptance can reach.
    if examined:
        # Something was proved. There is no zero to explain and no vacuity to
        # name in either field.
        reason = ""
    elif defect:
        # #506: the artefact was REJECTED, so the zero is a DECIDED VERDICT,
        # not a skip. It gets the rejected reason — and NO code, in EITHER
        # field. Publishing one in `vacuity_code` would name this failure as a
        # vacuity, which is the one state `signoff_audit` lets a tapeout waiver
        # through: an operator could copy the code out of a FAIL report into
        # `si_vacuity_accepted` and hold an acceptance for a genuine SI defect.
        # A rejection is not waivable, so it publishes nothing to waive — and
        # it is not a could-not-run either, so `unwaivable_code` stays empty
        # too and the #533 guarantee reads the same over both channels.
        reason = _rejected_reason(defect)
    else:
        # The gate reached nothing and says which nothing. WHICH FIELD that
        # name is published in is decided by `vacuity_publication` from the
        # same findings list the `defect` split above came from: a run that
        # never obtained an input is disclosed by name, in a field no
        # acceptance reads. See #535.
        reason = prose
        vacuity_code, unwaivable_code = vacuity_publication(code, bool(not_run))
    return _gd.Denominator(
        unit=DENOMINATOR_UNIT,
        examined=examined,
        considered=considered,
        not_applicable_reason=reason,
        details={
            # THE WAIVABLE CHANNEL. The machine-citable name of a vacuity a
            # tapeout acceptance may quote. Empty unless the gate examined
            # nothing, rejected nothing, AND held every input it audits — see
            # `vacuity_publication`. A consumer that must decide whether a
            # specific vacuity was accepted cites this, never
            # `not_applicable_reason`, and it may do so WITHOUT first reading
            # the defect channel: a state this field can name is waivable by
            # construction, not by the reader remembering a rule (#535).
            VACUITY_CODE_KEY: vacuity_code,
            # THE UN-WAIVABLE CHANNEL. The same nine-branch vocabulary, for the
            # states an acceptance may NOT cover — so a could-not-run run is
            # still named for a machine instead of being silenced, without
            # that name being reachable through `si_vacuity_accepted`. At most
            # one of the two is ever non-empty.
            UNWAIVABLE_CODE_KEY: unwaivable_code,
            "coupling_pairs": stats.get("coupling_pairs"),
            "coupling_caps": stats.get("coupling_caps"),
            "coupling_nets": stats.get("coupling_nets"),
            "spef_net_records": stats.get("spef_net_records"),
            "spef_parsed_nets": stats.get("spef_parsed_nets"),
            "spef_r_net_records": stats.get("spef_r_net_records"),
            "emitter_coupling_pairs": stats.get("emitter_coupling_pairs"),
            "nets_compared_per_corner": {
                c: (v or {}).get("nets_checked") for c, v in recount.items()},
            "folds_proved_per_corner": {
                c: (v or {}).get("folds_proved") for c, v in recount.items()},
        },
    )


def verdict_for(defect: bool, not_run: bool, vacuous: bool) -> str:
    """This gate's verdict precedence, in one place (#506, #510).

    FOUR STATES, FOUR TOKENS (#506). The old precedence was "any ERROR
    outranks vacuity", which left "the gate could not obtain its input" with
    nowhere to go and rendered it as the design carrying a violation.

    A gate that examined nothing has not signed anything off. `pass` keeps its
    literal meaning — the fold was re-derived and found honest — so a consumer
    reading only that field can no longer be handed a vacuous run as a clean
    one. The four-way answer is in `verdict`.

    EXTRACTED FROM ``build_report`` FOR #510, and the extraction is the point:
    ``RECORD_ADJUDICATION`` re-adjudicates already-published records against
    this same function, so a change to the precedence reaches the post-hoc
    check by construction. A copy of these five lines living beside the rules
    would be a second thing to remember to update, which is exactly the
    staleness #510 is about.
    """
    if defect:
        # Examined a real artefact and found it wrong. UNCHANGED, deliberately:
        # this is the rule the gate was written for and #506 does not soften it.
        return "FAIL"
    if not_run and vacuous:
        # Could not obtain the input, and proved nothing. The fourth state.
        return "NOT_RUN"
    if not_run:
        # PARTIAL, and the other direction of the same lie. Some corner's fold
        # WAS re-derived and proved; another corner's input was missing. Calling
        # that "NOT_RUN" would deny work the gate demonstrably did, so it keeps
        # the FAIL it had. There is no contradiction to resolve here: the
        # denominator is non-zero, so `vacuous` is false and the reason is
        # empty — the artefact already carried exactly one answer.
        return "FAIL"
    if vacuous:
        return "VACUOUS_PASS"
    return "PASS"


def build_report(findings: List[Finding], stats: dict, project_dir: str) -> dict:
    denom = denominator(stats, findings)
    not_run, defect = error_categories(findings)
    verdict = verdict_for(bool(defect), bool(not_run), denom.is_vacuous)
    summary = {
        "corners_checked": stats.get("corners_checked", []),
        "windows_exact": stats.get("windows_exact"),
        "coupling_pairs": stats.get("coupling_pairs"),
        "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
        "findings_count": len(findings),
        "pass": verdict == "PASS",
        # THE VERDICT TIER, NOT THE RAW ZERO (#506). Three substantive-defect
        # categories fire with `examined == 0` — a file that is the wrong
        # artefact is decided without any fold being re-derivable from it — so
        # deriving this flag straight from the denominator put `vacuous: true`
        # beside `verdict: FAIL` and the report answered its reader twice. It
        # now means "this run reached no conclusion", which is exactly the set
        # {NOT_RUN, VACUOUS_PASS}. The raw count is unmodified and still
        # visible at `summary.denominator.examined`.
        "vacuous": verdict in ("NOT_RUN", "VACUOUS_PASS"),
    }
    _gd.attach(summary, denom)
    return {
        "program": "si_mcf_sta_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "verdict": verdict,
        "summary": summary,
        "recount": stats.get("recount", {}),
        "monotonicity": stats.get("monotonicity", {}),
        "findings": [asdict(f) for f in findings],
    }


# ── re-adjudicating THIS gate's already-published records (#510) ────────────
# A landed rule changes what this gate certifies from now on and does nothing
# to the records already committed. `published_record_staleness_check` asks
# every gate that appears in the corpus which of its published verdicts it
# would still issue, decided FROM THE RECORD ALONE — the original SPEFs are
# gone (#506), so re-running is not available and never will be for old cells.

def _zero_fold_supersession(record: dict):
    """Would this gate still issue the verdict this record carries?

    THE ONE THING A RECORD PROVES ON PAPER. ``examined`` counts victim-net
    folds re-derived and PROVED, and every expectation is built from the
    coupling pairs (`victim_folded_caps` / `floor_folded_caps` are handed
    `pairs`). With no pairs the expectation map is empty on every corner, so
    ``examined == 0`` follows from ``summary.coupling_pairs == 0`` with no
    other input — no SPEF, no report, no host. That is the whole reason this
    rule is expressible and a timing claim would not be.

    THE CONVERSE IS NOT CLAIMED. A non-zero pair count does NOT prove
    ``examined > 0``: a coupled net whose re-derived expectation is 0.0 —
    zero-valued coupling caps, or the entire hold corner in
    window-independent floor mode — contributes a comparison and no proof. So
    the rule declines to speak rather than certify a record it cannot decide.
    """
    pairs = _ra.read_field(record, "summary.coupling_pairs")
    if isinstance(pairs, bool) or not isinstance(pairs, int):
        return _ra.Undecidable(
            f"summary.coupling_pairs is {pairs!r}, not a count, so whether "
            f"this run re-derived any fold cannot be read off the record")
    if pairs != 0:
        return None
    findings = record.get("findings")
    if not isinstance(findings, list) or any(
            not isinstance(f, dict) for f in findings):
        return _ra.Undecidable(
            "`findings` is not a list of objects, so the ERROR categories the "
            "verdict precedence reads cannot be recovered from the record")
    rebuilt = [Finding(severity=str(f.get("severity", "")),
                       category=str(f.get("category", "")),
                       message=str(f.get("message", ""))) for f in findings]
    not_run, defect = error_categories(rebuilt)
    # The gate's OWN precedence function, not a copy of it — see `verdict_for`.
    would = verdict_for(bool(defect), bool(not_run), vacuous=True)
    carried = record.get("verdict")
    if would == carried:
        return None
    return _ra.Supersession(
        would_issue=would,
        because=(f"the record states summary.coupling_pairs: 0, so no "
                 f"inter-net fold existed to re-derive and this run proved "
                 f"nothing (examined == 0) — its own recount agrees at "
                 f"nets_checked 0. Under the rule landed in #502 a run that "
                 f"re-derived nothing is a DISCLOSED SKIP, not a sign-off: "
                 f"this gate would answer {would} today, not {carried}. "
                 f"Decided entirely from fields the record carries; the "
                 f"original extraction was not consulted and is not needed."))


RECORD_ADJUDICATION = _ra.declare(
    __file__,
    gate="si_mcf_sta_check",
    # The entry point of the verdict decision. The fingerprint follows the
    # module-local call closure from here, so `verdict_for`, `denominator`
    # (which DEFINES vacuity) and `error_categories` are all covered without
    # being listed — an author cannot under-declare the surface.
    decision_roots=("build_report",),
    # Regenerate with:
    #   python3 published_record_staleness_check.py \
    #       --print-decision-digest si_mcf_sta_check
    # It changes when the decision logic changes — INCLUDING the written
    # reasons, which are part of what a rule pins. Updating it is the act of
    # re-reviewing the rules below against the new logic; that is the point,
    # and a fingerprint that stayed quiet through a prose rewrite of a verdict
    # reason would be the wrong kind of quiet.
    # Re-reviewed TWICE in succession, and the note is kept for both because
    # each records a different question that was asked of the same rules.
    #
    # v1.7.90, after #533 reworked this closure: `_vacuity` returns
    # (code, prose), and `denominator` assigns `not_applicable_reason` and
    # `vacuity_code` together per branch so a REJECTED artefact publishes no
    # vacuity code. The declared digest still named the pre-#533 closure, so
    # `RECORD_ADJUDICATION.drift()` was non-None and this gate could not
    # adjudicate its own published records at all — every test in
    # `test_published_record_staleness_check.py` fails in that state.
    #
    # #535, which splits the un-waivable states into `unwaivable_code`, moves
    # the closure again and this digest is regenerated for it.
    #
    # The rule below was re-read against BOTH changes: `zero-fold-is-not-a-
    # signoff` decides from `summary.coupling_pairs` and `findings` through
    # `verdict_for`, and neither split touches that path — the codes and the
    # fields carrying them are disclosure, not verdict. Verified by running the
    # rule against both corpus records carrying `coupling_pairs: 0`, which
    # still supersede PASS -> VACUOUS_PASS.
    decision_digest=(
        "bab7cda2e01f1c85cd400009a4beab95dc537219e931d8667b88a7d390e06ce3"),
    rules=(
        _ra.Rule(
            rule_id="si_mcf_sta_check.zero-fold-is-not-a-signoff",
            landed_in="#502",
            requires=("summary.coupling_pairs", "findings"),
            decide=_zero_fold_supersession,
            what=("a run that re-derived zero coupling folds signed nothing "
                  "off; PASS is no longer one of its available verdicts"),
        ),
    ),
)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="GATE: verify the MCF-bounded SI-aware STA fold is genuinely "
                    "applied + reported honestly (false-clean-proof).")
    ap.add_argument("project_dir")
    ap.add_argument("--report", default=None,
                    help="path to si_mcf_sta.json (default: reports/phase3/)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        # rc 1, NOT 2: rc 2 is the disclosed-skip tier and the flow credits it
        # as a pass unconditionally. A run that never started must not be
        # credited as one. See the module docstring.
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return RC_FAIL

    findings, stats = audit(
        project_dir, Path(args.report) if args.report else None)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)
    dst = (Path(args.json) if args.json
           else _pl.report_path(project_dir, "si_mcf_sta_check.json"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out + "\n")
    print(out)
    denom = report["summary"][_gd.DENOMINATOR_KEY]
    if report["verdict"] == "VACUOUS_PASS":
        # STDOUT STAYS THE REPORT JSON AND NOTHING ELSE; the token goes to
        # stderr, which `flow_compliance_check._check_program_exit_zero` also
        # captures into the snippet `_stdout_signals_vacuous` scans. rc 2 alone
        # already promotes the step to the VACUOUS-PASS tier — the token is the
        # second, rc-independent channel, for consumers that read text.
        print(f"VACUOUS_PASS: {denom['not_applicable_reason']}",
              file=sys.stderr)
        return RC_VACUOUS
    if report["verdict"] == "NOT_RUN":
        # #506 — the text channel for the fourth state, and it must NOT be the
        # `VACUOUS_PASS` token: `flow_compliance_check._stdout_signals_vacuous`
        # matches that at line start and would promote the step to the pass
        # tier, which is precisely the trade the rc decision refuses (see the
        # module docstring). rc stays 1, so the step FAILs exactly as before.
        print(f"NOT_RUN: {denom['not_applicable_reason']}", file=sys.stderr)
        return RC_FAIL
    return RC_PASS if report["verdict"] == "PASS" else RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
