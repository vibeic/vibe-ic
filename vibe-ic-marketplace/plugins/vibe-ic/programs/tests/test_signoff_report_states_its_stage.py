"""Declared timing and power evidence says which side of place-and-route it is.

WHY
===
MEASURED: of three reports in one sign-off family, ONE carried the stage
statement because its own emitter wrote it; the siblings deciding the slow and
fast corners were written by emitters that did not. 48 of 56 timing rows were
dropped as out of scope and both setup and hold reported an incomplete view set
rather than a failure. The READ side is already correct — the single reader
returns *undeclared* — so the gap is entirely producer-side.

THE POPULATION IS DRAWN FROM THE FLOW, AND IT IS TESTED
=======================================================
"A report a step offers as sign-off evidence" is not a judgement call: the flow
declares it. Two exclusions are load-bearing and are asserted from both sides,
because each one was a measured false positive or would force a wrong value:

  * NOT a report  — without the `.rpt` requirement this matched a power-INTENT
    document and synthesis stats, taking the population 2 -> 78 and producing
    six wrong findings. `test_a_power_intent_document_is_not_a_report`.
  * INEXPRESSIBLE — the stamp has exactly two values, and a post-CTS pre-route
    report can answer neither honestly. Disclosed, never silently dropped.
    `test_an_inexpressible_stage_is_disclosed_not_refused`.

chip-AGNOSTIC: flow declarations and stamp vocabulary.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "signoff_report_states_its_stage.py"

_spec = importlib.util.spec_from_file_location("srsis", _TOOL)
srsis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srsis)

_FLOW_REL = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
_PROG_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

_FLOW = ("steps:\n"
         "  - id: 23\n"
         "    required_outputs:\n"
         "      - phase3/stage3/sta/post_route_timing.rpt\n")

_UNSTAMPED = ('def emit(project, body):\n'
              '    p = project / "sta" / "post_route_timing.rpt"\n'
              '    p.write_text(body)\n')
_STAMPED = ('def emit(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n')



def _count_in(text: str, phrase: str) -> bool:
    """`phrase` (which begins with a count) appears with NO digit before it.

    MEASURED: `assert _count_in(out, "1 inexpressible")` is satisfied by an output saying
    `21 inexpressible`, and `"0 key(s) observed"` by `10 key(s) observed`. A
    substring assertion on a count is not a pin — every one of these tests would
    have passed against a tenfold-wrong number. Taken from the census lane's
    "a substring assertion on a count is not a pin — parse the number".
    """
    return re.search(r"(?<!\d)" + re.escape(phrase), text) is not None


def test_the_count_anchor_actually_fires():
    """PROVE THE PIN FIRES. `_count_in` exists because a substring assertion on a
    count is not a pin — `"1 inexpressible" in out` is satisfied by an output
    saying `21 inexpressible`. A helper that silently never rejects anything would
    reinstate exactly the defect it was added to remove, and nothing else in this
    file would notice, because every other use of it asserts the TRUE case.

    So: the true case passes, and a preceding digit is refused.
    """
    assert _count_in("examined 1 thing", "1 thing")
    assert not _count_in("examined 21 thing", "1 thing"), (
        "the anchor did not fire: a tenfold-wrong count still satisfies the pin")
    assert not _count_in("examined 10 thing", "0 thing")
    assert _count_in("a, 0 thing", "0 thing")





# ------------------------------------------------------------ red control











# ------------------------------------------------- the exclusions, tested









# ------------------------------------- the gap the record came from, disclosed



# ------------------------------- the population cannot silently go empty











# THE DEFECT THIS PINNED IS FIXED, AND THE PIN NOW HOLDS IT SHUT.
#
# Arm A (flow `required_outputs`) is clean and stays clean. Arm B — the family
# rule — used to report two emitters in `phase3_one_shot_runner.py` that wrote a
# timing/power report without STA_BASIS while the same module stamped another
# one it emits: `_emit_power_report` (power.rpt) and `_emit_si_crosstalk_report`
# (si_crosstalk.rpt, both the SPEF and the no-SPEF branch).
#
# The earlier note here said the stamps were NOT authored "on purpose", because
# asserting POST_ROUTE for a session whose inputs were never checked is the
# unearned claim this whole lane exists to prevent, and that "the other two need
# their sessions read first". The sessions have now been read, and each stamp is
# derived rather than chosen:
#
#   * `_emit_power_report` already computed `basis_stamp` from what the session
#     LINKED — POST_ROUTE_SPEF / POST_ROUTE_NO_SPEF when it linked the routed
#     netlist, PRE_LAYOUT_ESTIMATE when it did not. The value was being written
#     as `POWER_BASIS:` and as prose `basis:`, neither of which any reader
#     parses. The stamp writes the SAME derived value in the one spelling
#     `_sta_basis.declared_basis` reads; nothing new is asserted.
#   * `_emit_si_crosstalk_report` is Step 27, guarded at its call site on
#     `pnr_out/<top>.def`, and its two branches differ only in whether the
#     extracted SPEF was available — which is exactly what the shipped
#     `POST_ROUTE_SPEF` / `POST_ROUTE_NO_SPEF` suffixes distinguish. The
#     no-SPEF branch's own body already said "decoupled-C wire-RC screen on
#     routed DB" in prose; the stamp says it where it can be read.
#
# MEASURED, and the direction matters. Over an otherwise-unchanged tree with
# ONLY `phase3_one_shot_runner.py` swapped, the finding set went 2 -> 0 while
# every denominator in the summary stayed put: 4 examined emitters of 8
# flow-declared reports, 1 inexpressible, 18 emitted-but-undeclared disclosed,
# and the sibling arm judging 9 reports in 1 module. A finding set that empties
# because the corpus emptied proves only the vacuity path, so the counts are
# pinned below beside the empty set rather than left implicit.
#
# This test still pins the SET, in the other direction: it goes red if any
# unstamped sibling appears — including these two coming back.

#: BOTH DENOMINATORS, pinned because an EMPTY finding set is satisfied by a gate
#: that judged nothing — and this file's repository anchor now expects exactly
#: that empty set on both arms. The gate's own rc=2 NOT-CHECKED tier covers only
#: the TOTAL collapse (`population == 0`, `found == 0`); these cover the partial
#: one, where the corpus shrinks enough to make the empty sets meaningless while
#: the gate still reports a pass.
#:
#: ARM A IS PINNED AS A SET OF PATHS, NOT A COUNT, and the difference is what a
#: red says. This population is DECLARED IN THE FLOW and it moves whenever a
#: step declares a new `.rpt` — it moved twice in the batch this test was
#: written in. A bare `8 != 9` sends the next reader to go find which one; the
#: set names it on the failure line, and the remedy (add it here once its
#: emitter stamps, or fix the emitter) reads off the diff. Same reason
#: `_KNOWN_UNSTAMPED` above is a set.
#:
#: WHAT IS AND IS NOT IN IT, because two near-misses have already been raised:
#: `is_timing_or_power` requires a `.rpt` basename, so neither
#: `phase2/stage2/constraints/*.upf` (a power-INTENT document — the gate's own
#: docstring names it as the measured false positive that motivated the `.rpt`
#: requirement, population 2 -> 78 and six wrong findings) nor
#: `reports/spare_preservation.json` can enter this population, whether or not
#: the flow declares them. Withdrawing or re-adding either moves nothing here.
_ARM_A_DECLARED = {
    "phase2/stage1/fpga/output_files/*.map.rpt",     # step 6
    "phase2/stage2/dft/atpg_coverage.rpt",           # step 11
    "phase2/stage2/synth/area.rpt",                  # step 9
    "phase3/stage3/cts/clock_tree.rpt",              # step 19 — the 1 inexpressible
    "phase3/stage3/sta/post_route_timing.rpt",       # step 23
    "phase3/stage3/sta/pre_pnr_timing.rpt",          # step 10
    "reports/phase3/power.rpt",                      # step 33
    "reports/phase3/si_crosstalk.rpt",               # step 27
    # Step 23's SPEF-backed STA pass, mirrored into `reports/`. It is a
    # `required_outputs` entry of step 23 in the flow, and a `.rpt` timing
    # report, so the arm-A scan reads it exactly as it reads the eight above —
    # the population legitimately GREW and this set had not been told.
    "reports/phase3/sta_spef_based.rpt",             # step 23
    # R-0915-107 — step 27's SI (crosstalk/MCF) STA report. It was in the
    # emitted-but-undeclared DISCLOSURE until that ruling: nothing wrote
    # `reports/phase3/si_mcf_sta.rpt` at all, because `si_mcf_sta.py` ran its
    # three OpenSTA corners into the WORK dir as `si_mcf_sta_<tag>.rpt` and
    # published only the verdict JSON, while `_path_layout` carried a routing row
    # for the untagged name that no writer used. `si_mcf_sta.run` now publishes
    # it with `STA_BASIS: POST_ROUTE_MCF_SPEF` and step 27 declares it, so it
    # enters this population exactly as this set's own comment prescribes —
    # "add it here once its emitter stamps".
    "reports/phase3/si_mcf_sta.rpt",                 # step 27
}

#: Of the 8 above, the count whose EMITTER the arm-A scan could identify. Left a
#: count because there is no set to read at this API — `scan` returns the
#: findings, not the found. It is the number that makes "0 unstamped" mean
#: something: at 0 the gate refuses (rc=2), and between 0 and 4 it would be
#: passing over a shrinking read.
#: 4 -> 5 under R-0915-107: `si_mcf_sta.py` now NAMES the report it publishes at
#: its write site, so the arm-A scan can identify its emitter and hold it to the
#: stamp. Had the destination stayed derived (`out_json_p.with_suffix(".rpt")`)
#: the report would have been declared while its emitter remained unidentifiable
#: — measured: population 10, found 4 — which is a declaration the scan cannot
#: enforce, and the debt this ruling closes would have survived the fix.
_ARM_A_FOUND = 5

#: Arm B: modules that demonstrate a stamping convention, and the reports they
#: emit. If a module stops writing its reports, is reclassified as a COPIER, or
#: fails to parse, these drop and the empty finding set stops meaning anything.
#: 1 -> 3 modules and 9 -> 11 reports, in TWO separate increments, attributed
#: rather than adjusted:
#:
#:   1 -> 2   `digital_hardmacro_gen.characterise_liberty` began emitting AND
#:            stamping `sta_mcorner_ocv.rpt`, at 43626797b (2026-09-16,
#:            "hardmacro: the Liberty carries the run's own timing, or it is
#:            NOT_MEASURED (R-0915-87 part 3)"), landed by bd308d420 (PR #2343).
#:            This pin was set at 755c9326e (2026-08-26) and therefore PREDATES
#:            that landing — `git merge-base --is-ancestor <pin> <that commit>`
#:            is true — so the pin was stale and the growth is the DESIRED
#:            direction: a second module ADOPTED the convention. That is the
#:            1/9 -> 2/10 this test reported as "the sibling arm's population
#:            moved", and no unstamped sibling appeared with it.
#:   2 -> 3   `si_mcf_sta.py` joins under R-0915-107, for the same reason: it now
#:            stamps a timing report it emits.
_ARM_B_MODULES = 3
_ARM_B_JUDGED = 11




# ── ARM B — the family rule ─────────────────────────────────────────────────
# Arm A is keyed on the flow's `required_outputs` and CANNOT reach the capture's
# own incident: both multi-corner sign-off reports are emitted and never
# declared, so arm A files them under DISCLOSED. These pin the arm that can.

_SIBLING_RED = (
    'def emit_a(project, body):\n'
    '    p = project / "sta" / "post_route_timing.rpt"\n'
    '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
    '\n'
    'def emit_b(project, body):\n'
    '    q = project / "sta" / "sta_mcorner_ocv_postrepair.rpt"\n'
    '    q.write_text(body)\n')
