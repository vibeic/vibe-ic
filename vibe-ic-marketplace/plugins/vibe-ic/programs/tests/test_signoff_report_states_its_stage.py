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
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "signoff_report_states_its_stage.py"
_REPO = _PROGRAMS.parents[3]

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

def _tree(tmp_path, flow, modules):
    f = tmp_path / _FLOW_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(flow)
    d = tmp_path / _PROG_REL
    d.mkdir(parents=True, exist_ok=True)
    for n, b in modules.items():
        (d / n).write_text(b)
    return tmp_path


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------ red control

def test_an_unstamped_declared_report_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the sibling emitter that never writes the stamp."""
    root = _tree(tmp_path, _FLOW, {"runner.py": _UNSTAMPED})
    rc, out = _run(root)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "post_route_timing.rpt" in out
    assert "UNDECLARED" in out


def test_the_same_emitter_with_the_stamp_passes(tmp_path):
    """BIDIRECTIONAL: add only the stamp and the identical emitter goes green."""
    root = _tree(tmp_path, _FLOW, {"runner.py": _STAMPED})
    rc, out = _run(root)
    assert rc == 0, out


def test_a_comment_mentioning_the_stamp_does_not_count(tmp_path):
    """MEASURED FALSE PASS, now pinned.

    The check was `STA_BASIS in <function source text>`, so an emitter carrying

        # TODO: we should write STA_BASIS here one day

    reported PASS. A comment ADMITTING the stamp is missing certified it as
    present — the defect certifying itself, which is the strongest possible form
    of what this rule exists to refuse.
    """
    root = _tree(tmp_path, _FLOW, {"runner.py":
        'def emit(project, body):\n'
        '    # TODO: we should write STA_BASIS here one day\n'
        '    p = project / "sta" / "post_route_timing.rpt"\n'
        '    p.write_text(body)\n'})
    rc, out = _run(root)
    assert rc == 1, f"a comment satisfied the stamp check:\n{out}"


def test_a_docstring_mentioning_the_stamp_does_not_count(tmp_path):
    """Describing a stamp is not emitting one."""
    root = _tree(tmp_path, _FLOW, {"runner.py":
        'def emit(project, body):\n'
        '    """Writes the report; STA_BASIS is handled elsewhere."""\n'
        '    p = project / "sta" / "post_route_timing.rpt"\n'
        '    p.write_text(body)\n'})
    rc, out = _run(root)
    assert rc == 1, f"a docstring satisfied the stamp check:\n{out}"


def test_the_stamp_must_be_in_the_emitting_function(tmp_path):
    """Module granularity cannot answer this: one module emits many reports."""
    other = ('def unrelated():\n'
             '    return "# STA_BASIS: POST_ROUTE_SPEF"\n')
    root = _tree(tmp_path, _FLOW, {"runner.py": other + _UNSTAMPED})
    rc, out = _run(root)
    assert rc == 1, ("a stamp in a DIFFERENT function must not satisfy the "
                     "emitter of this report\n" + out)


# ------------------------------------------------- the exclusions, tested

def test_a_power_intent_document_is_not_a_report():
    assert not srsis.is_timing_or_power(
        "phase1/generated_docs/L21_POWER_INTENT.json")
    assert not srsis.is_timing_or_power("phase2/stage2/synth/stats.json")
    assert srsis.is_timing_or_power("phase3/stage3/sta/post_route_timing.rpt")


def test_a_geometry_report_is_not_in_the_population():
    for p in ["reports/phase3/drc_signoff.rpt", "reports/phase3/lvs.rpt",
              "reports/phase3/antenna.rpt", "reports/density.rpt"]:
        assert not srsis.is_timing_or_power(p), p


def test_an_inexpressible_stage_is_disclosed_not_refused(tmp_path):
    flow = ("steps:\n"
            "  - id: 19\n"
            "    required_outputs:\n"
            "      - phase3/stage3/cts/clock_tree.rpt\n"
            "  - id: 23\n"
            "    required_outputs:\n"
            "      - phase3/stage3/sta/post_route_timing.rpt\n")
    cts = ('def emit(project, body):\n'
           '    p = project / "cts" / "clock_tree.rpt"\n'
           '    p.write_text(body)\n')
    root = _tree(tmp_path, flow, {"runner.py": _STAMPED, "cts.py": cts})
    rc, out = _run(root)
    assert rc == 0, out
    assert "cannot describe a report written after CTS" in out
    assert _count_in(out, "1 inexpressible")


def test_the_inexpressible_count_is_never_silently_zero(tmp_path):
    root = _tree(tmp_path, _FLOW, {"runner.py": _STAMPED})
    rc, out = _run(root)
    # Same reason as the disclosure pin in the pointer file: the denominator is
    # printed before the verdict line, so without this the assertion survives a
    # gate that never judged anything.
    assert rc == 0, out
    assert _count_in(out, "0 inexpressible")


# ------------------------------------- the gap the record came from, disclosed

def test_an_emitted_but_undeclared_timing_report_is_disclosed(tmp_path):
    stray = ('def emit(project, body):\n'
             '    p = project / "reports" / "power.rpt"\n'
             '    p.write_text(body)\n')
    root = _tree(tmp_path, _FLOW, {"runner.py": _STAMPED, "power.py": stray})
    rc, out = _run(root)
    assert rc == 0, out
    assert "power.rpt" in out
    assert "nothing declares it as evidence" in out


# ------------------------------- the population cannot silently go empty

def test_the_real_flow_still_declares_timing_reports():
    declared = srsis.declared_outputs(_REPO / srsis.FLOW_REL)
    wanted = [p for p in declared if srsis.is_timing_or_power(p)]
    assert "phase3/stage3/sta/post_route_timing.rpt" in wanted
    assert "phase3/stage3/sta/pre_pnr_timing.rpt" in wanted
    assert len(wanted) >= 2, wanted


def test_an_empty_population_is_not_checked(tmp_path):
    root = _tree(tmp_path, "steps: []\n", {"runner.py": _STAMPED})
    rc, out = _run(root)
    assert rc == 2, out
    assert "Not a pass" in out


def test_no_identifiable_emitter_is_not_checked(tmp_path):
    root = _tree(tmp_path, _FLOW, {"unrelated.py": "x = 1\n"})
    rc, out = _run(root)
    assert rc == 2, out


def test_a_missing_flow_is_not_checked(tmp_path):
    (tmp_path / _PROG_REL).mkdir(parents=True)
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


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
_KNOWN_UNSTAMPED: set = set()

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
}

#: Of the 8 above, the count whose EMITTER the arm-A scan could identify. Left a
#: count because there is no set to read at this API — `scan` returns the
#: findings, not the found. It is the number that makes "0 unstamped" mean
#: something: at 0 the gate refuses (rc=2), and between 0 and 4 it would be
#: passing over a shrinking read.
_ARM_A_FOUND = 4

#: Arm B: modules that demonstrate a stamping convention, and the reports they
#: emit. If a module stops writing its reports, is reclassified as a COPIER, or
#: fails to parse, these drop and the empty finding set stops meaning anything.
_ARM_B_MODULES = 1
_ARM_B_JUDGED = 9


def test_repository_arm_a_is_clean_and_arm_b_reports_the_known_set():
    rc, out = _run(_REPO)
    assert rc == 0, out
    # The verdict line is the one place both arms are stated together, so a
    # rc=0 reached down some other path (there is none today) would not slip by.
    assert "PASS — no declared timing/power report with an identified emitter " \
           "is unstamped" in out, out
    # DISCLOSED lines also contain "emitted by" and share the stream, so the
    # filter names the finding shape rather than a substring both carry.
    seen = {ln.split(":", 1)[0] for ln in out.splitlines()
            if "emitted by" in ln and not ln.startswith("[")
            and not ln.startswith("DISCLOSED")}
    assert seen == _KNOWN_UNSTAMPED, (
        "arm B's finding set moved.\n  expected %s\n  got      %s\n%s"
        % (sorted(_KNOWN_UNSTAMPED), sorted(seen), out))
    # ...over denominators that are still there. Called directly rather than
    # regex-scraped out of the summary line, so the numbers are the gate's own.
    unstamped, _undeclared, _inexpr, population, found, _unparsed = \
        srsis.scan(_REPO)
    assert [str(e) for e in unstamped] == [], (
        "arm A regressed: a flow-declared report lost its stamp\n" + out)
    # The set, re-derived from the CURRENT flow through the gate's own two
    # functions — never scraped from the summary line, and never carried
    # forward from the last time someone looked.
    declared = {path for path in srsis.declared_outputs(_REPO / srsis.FLOW_REL)
                if srsis.is_timing_or_power(path)}
    assert declared == _ARM_A_DECLARED, (
        "arm A's declared population moved.\n  appeared: %s\n  vanished: %s\n"
        "A report that APPEARED joins this set once its emitter stamps; one "
        "that VANISHED means the clean verdict now covers less than it did.\n%s"
        % (sorted(declared - _ARM_A_DECLARED),
           sorted(_ARM_A_DECLARED - declared), out))
    assert (population, found) == (len(_ARM_A_DECLARED), _ARM_A_FOUND), (
        "arm A's scan disagrees with the flow it read.\n  expected %s declared "
        "/ %s with an emitter\n  got      %s / %s\n%s"
        % (len(_ARM_A_DECLARED), _ARM_A_FOUND, population, found, out))
    findings, modules, judged = srsis.sibling_stamp_gaps(_REPO)
    assert [str(f) for f in findings] == [], findings
    assert (modules, judged) == (_ARM_B_MODULES, _ARM_B_JUDGED), (
        "the sibling arm's population moved, so the empty finding set above is "
        "no longer evidence of anything.\n  expected %s module(s) / %s report(s)"
        "\n  got      %s / %s\n%s"
        % (_ARM_B_MODULES, _ARM_B_JUDGED, modules, judged, out))


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


def test_arm_b_an_unstamped_sibling_of_a_stamped_report_goes_red(tmp_path):
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": _SIBLING_RED}))
    assert rc == 1, out
    assert "sta_mcorner_ocv_postrepair.rpt" in out, out
    assert "the same module stamps another" in out, out


def test_arm_b_a_module_that_stamps_nothing_is_outside_the_population(tmp_path):
    """No convention demonstrated, so the omission is a scope question, not a
    finding. This is what keeps the arm from reddening every report in the tree.

    THE rc IS PINNED, AND THE FIRST VERSION OF THIS TEST NEEDED IT. It renamed the
    stamped report to `other_sta.rpt`, which left the flow-declared report with no
    emitter — so arm A bailed out at NOT CHECKED (rc=2) before arm B judged
    anything, and the absence assertion below was satisfied by a gate that never
    ran. A green assertion under rc=2 proves nothing at all. The declared report
    keeps its emitter here so the gate actually reaches a verdict.
    """
    body = ('def emit_b(project, body):\n'
            '    q = project / "sta" / "aging_sta.rpt"\n'
            '    q.write_text(body)\n')
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": _STAMPED, "n.py": body}))
    assert rc == 0, out
    assert "aging_sta.rpt" not in out.split("examined")[0], out


def test_arm_b_sees_a_write_made_by_atomic_rename(tmp_path):
    """THE GAP THAT HID THE CAPTURE'S OWN REPORT.

    The atomic-write doctrine here is temp-file + `os.replace`, so a correct
    emitter never calls `write_text` on its destination. While this scan knew
    only the direct write forms, `sta_mcorner_ocv_postrepair.rpt` — written by
    `_measure_postrepair_mcorner_ocv` via `replace` — was invisible to it.
    """
    body = ('import os\n'
            'def emit_a(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
            '\n'
            'def emit_b(project, body):\n'
            '    tmp = project / "sta" / "sta_mcorner_ocv_postrepair.rpt.tmp"\n'
            '    tmp.write_bytes(body)\n'
            '    os.replace(tmp, project / "sta" / "sta_mcorner_ocv_postrepair.rpt")\n')
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": body}))
    assert rc == 1, out
    assert "sta_mcorner_ocv_postrepair.rpt" in out, out


def test_arm_b_does_not_require_a_copier_to_stamp(tmp_path):
    """A republished byte-identical copy cannot state a basis its producer did
    not. Reddening the mirror would demand a stamp from the one function that
    provably has nothing to stamp it with."""
    body = ('def emit_a(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
            '\n'
            'def mirror(src, dst):\n'
            '    payload = src.read_bytes()\n'
            '    dst.write_bytes(payload)\n'
            '    return "sta_spef_based.rpt"\n')
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": body}))
    assert rc == 0, out
    assert "sta_spef_based.rpt" not in out.split("examined")[0], out


def test_arm_b_a_bare_read_is_not_a_copy(tmp_path):
    """The copy signal is the DATAFLOW, not the read. Every report generator
    reads the tool log it summarises; treating that as copying emptied this
    arm's population and turned the gate green — measured, not supposed."""
    body = ('def emit_a(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
            '\n'
            'def emit_b(project, log):\n'
            '    raw = log.read_text()\n'
            '    q = project / "sta" / "si_crosstalk.rpt"\n'
            '    q.write_text("slack " + raw.split()[0])\n')
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": body}))
    assert rc == 1, out
    assert "si_crosstalk.rpt" in out, out


def test_arm_b_follows_one_hop_delegation_to_a_stamper(tmp_path):
    """A wrapper that hands its report to a stamping helper is NOT a finding.

    This is the false positive that shipped: the wrapper stamps nothing in its own
    body, so a scope-local reading calls the report unstamped when the stamp is
    written one call away, into that very file.
    """
    body = ('def emit_a(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
            '\n'
            'def _session(rpt_out, body):\n'
            '    rpt_out.write_text("STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
            '\n'
            'def wrapper(project, body):\n'
            '    out = project / "sta" / "sta_mcorner_ocv_postrepair.rpt"\n'
            '    _session(out, body)\n'
            '    out.write_bytes(b"")\n')
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": body}))
    assert rc == 0, out
    assert "sta_mcorner_ocv_postrepair.rpt" not in out.split("examined")[0], out


def test_arm_b_still_reddens_a_wrapper_whose_callee_does_not_stamp(tmp_path):
    """The other direction — delegation is not a blanket excuse."""
    body = ('def emit_a(project, body):\n'
            '    p = project / "sta" / "post_route_timing.rpt"\n'
            '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n'
            '\n'
            'def _plain(rpt_out, body):\n'
            '    rpt_out.write_text(body)\n'
            '\n'
            'def wrapper(project, body):\n'
            '    out = project / "sta" / "si_crosstalk.rpt"\n'
            '    _plain(out, body)\n'
            '    out.write_bytes(b"")\n')
    rc, out = _run(_tree(tmp_path, _FLOW, {"m.py": body}))
    assert rc == 1, out
    assert "si_crosstalk.rpt" in out, out
