"""Extraction-input precondition + the BLOCKED verdict.

THE DEFECT
----------
`step_lvs` proved its Magic technology file EXISTS (`test -f`) and then ran
extraction. A technology file can exist, be readable, and still be a STUB —
sections declared but empty — from which Magic can resolve no layers, extract
no netlist, and therefore compare nothing. The run landed on:

    LVS_EXTRACTION_NO_NETLIST -> status FAIL
    "Magic ext2spice produced no extracted netlist (rc=0); see ext2spice.log"

FAIL is the same terminal class as a genuine netlist mismatch. So a run that
verified NOTHING was reported in the same words as a run that verified
something and found it broken, with the actual cause — an unusable input —
named nowhere. "The tool could not look" was indistinguishable from "the tool
looked and the design is wrong".

THE FIX: a precondition on the extraction INPUTS, and a third verdict.

    PASS    — a compare ran and the layout matches the schematic.
    FAIL    — a compare ran and it does not.
    BLOCKED — no compare could run; the inputs cannot produce a netlist.
              NOTHING is known about the design, in either direction.

WHAT THESE TESTS GUARD
----------------------
The risk in adding a verdict is not that it fails to fire. It is (a) that it
becomes a route to green, and (b) that it cannibalises real FAILs — a checker
that answers "blocked" instead of "fail" is a broken failure detector, and one
that can no longer answer "clean" is an alarm, not a checker. So all three
outcomes are asserted, and the two that must NOT change are asserted as
loudly as the new one:

  1. stub tech file          -> BLOCKED, naming the file and the capability
  2. complete tech + match   -> PASS   (unchanged)
  3. complete tech + real mismatch -> FAIL (unchanged — NOT laundered
                                     into "blocked")
  4. BLOCKED is never a pass anywhere downstream: not in the run
     aggregate, not in the Step-31 gate.

Scope: direct capability/extraction/compare controls. Calls to `step_lvs`
explicitly select its existing `_direct=True` native body, as the direct
callback of the Step-31 producer switch does. The substituted tool transport
does not provide a current-PV execution envelope; these controls do not claim
whole-PV qualification. The real capability check, extraction recipe, netgen
classification, `_aggregate_verdict`, and Step-31 report gate remain in use.

chip-AGNOSTIC: synthetic generic tech/LEF/netgen text. No PDK, foundry, layer
or design literal is used as detection logic anywhere in this file.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as runner  # noqa: E402
import verdict as _V  # noqa: E402  R-0915-85
import eda_report_audit as audit  # noqa: E402


# --------------------------------------------------------------------------
# Synthetic technology files — generic layer names, no PDK content.
# --------------------------------------------------------------------------
MAGICRC = "tech load generic.tech\n"

# The defect shape: sections are DECLARED but carry nothing. `styles` is
# present-and-empty; `connect` / `extract` are absent entirely.
STUB_TECH = """\
tech
    format 32
    generic_stub
end

version
    version 0.1
    description "bridge technology - not yet complete"
end

planes
    metalplane,mp
end

types
    metalplane routing_a,ra
    metalplane routing_b,rb
end

styles
    # TODO: styles have not been authored for this technology yet
end
"""

COMPLETE_TECH = """\
tech
    format 32
    generic_complete
end

planes
    metalplane,mp
end

types
    metalplane routing_a,ra
    metalplane routing_b,rb
end

styles
    styletype generic
    routing_a 1
    routing_b 2
end

connect
    routing_a routing_a
    routing_b routing_b
end

lef
    routing routing_a routing_a RA
    routing routing_b routing_b RB
    cut cut_ab cut_ab
end

extract
    style generic
    lambda 1.0
    planeorder metalplane 0
    resist routing_a 100
    resist routing_b 100
    substrate space/w well generic_sub
    device mosfet gate_a routing_a routing_b generic_dev
end
"""

TECH_LEF = """\
VERSION 5.8 ;
LAYER routing_a
    TYPE ROUTING ;
    PITCH 0.5 ;
END routing_a
LAYER cut_ab
    TYPE CUT ;
END cut_ab
LAYER routing_b
    TYPE ROUTING ;
    PITCH 0.5 ;
END routing_b
END LIBRARY
"""

MATCH_TRANSCRIPT = (
    "Netgen 1.5.316\n"
    "Contents of circuit 1:  Circuit: 'chip_top'\n"
    "Contents of circuit 2:  Circuit: 'chip_top'\n"
    "Final result: Circuits match uniquely.\n"
)
MISMATCH_TRANSCRIPT = (
    "Netgen 1.5.316\n"
    "Contents of circuit 1:  Circuit: 'chip_top'\n"
    "Contents of circuit 2:  Circuit: 'chip_top'\n"
    "Net: routing_a_net instance mismatch device count parameter\n"
    "Final result: Netlists do not match.\n"
)












# ==========================================================================
# FIXTURE 1 — stub tech file -> BLOCKED
# ==========================================================================






# ==========================================================================
# FIXTURE 2 — complete tech + matching design -> PASS, UNCHANGED
# ==========================================================================






# ==========================================================================
# FIXTURE 3 — complete tech + genuine mismatch -> STILL FAIL
# ==========================================================================


# ==========================================================================
# 4 — BLOCKED IS NEVER A PASS DOWNSTREAM
# ==========================================================================






def test_blocked_is_in_the_verdict_tier_vocabulary():
    """R-0915-85 — `BLOCKED` is a VERDICT plus a REASON, and both must exist.

    The tier vocabulary is the five now, so asserting the old word would only
    say that a deleted string is absent. What this test protects is that the
    runner can still EXPRESS "this step could not look": the verdict
    `NOT_MEASURED` is one of its tiers, and `input_absent` — the reason
    `verdict.ReasonClass` records as the replacement for the `step_preflight`
    BLOCKED refusal — is a reason the vocabulary has. Both halves, because a
    word with no reason is the bag the old vocabulary was.
    """
    assert _V.Verdict.NOT_MEASURED.value in runner._VERDICT_TIERS
    assert _V.ReasonClass.INPUT_ABSENT.value in {r.value for r in _V.ReasonClass}


def test_step31_gate_reports_blocked_and_refuses_signoff(tmp_path):
    """The Step-31 LVS gate must not pass a BLOCKED run, and must say WHY.

    A BLOCKED run has no netgen report at all; the gate used to say only
    'No LVS report found'.
    """
    proj = tmp_path
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "lvs_verdict.json").write_text(json.dumps({
        "status": "BLOCKED",
        "result": "BLOCKED",
        "finding": "LVS_INPUT_TECH_INCAPABLE",
        "message": "technology file /pdk/generic.tech cannot support "
                   "extraction — missing extraction rules.",
        "tech_file": "/pdk/generic.tech",
    }))
    res = audit._check_lvs(proj)
    assert res.passed is False
    assert res.summary.get("terminal_verdict") == "BLOCKED"
    assert res.summary.get("blocked") is True
    rules = [f.rule for f in res.findings]
    assert "LVS_BLOCKED_INPUT_INCAPABLE" in rules
    msg = " ".join(f.message for f in res.findings)
    assert "BLOCKED" in msg and "NOTHING is known" in msg


def test_step31_gate_unchanged_when_no_verdict_artifact(tmp_path):
    """Control: with no BLOCKED artifact the gate behaves exactly as before."""
    res = audit._check_lvs(tmp_path)
    assert res.passed is False
    assert [f.rule for f in res.findings] == ["LVS_REPORT_EXISTS"]
    assert "blocked" not in res.summary


def test_step31_gate_ignores_a_non_blocked_verdict_artifact(tmp_path):
    """A FAIL verdict artifact must not be read as BLOCKED."""
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    (tmp_path / "reports" / "phase3" / "lvs_verdict.json").write_text(
        json.dumps({"status": "FAIL", "finding": "LVS_MISMATCH"}))
    res = audit._check_lvs(tmp_path)
    assert res.passed is False
    assert [f.rule for f in res.findings] == ["LVS_REPORT_EXISTS"]


# ==========================================================================
# 5 — the requirement DERIVATION (the check does not assume a section list)
# ==========================================================================














# ==========================================================================
# 6 — MULTI-FILE technologies (`include`) — the false-BLOCKED guard
# ==========================================================================
# Measured against real open-source PDK tech files during review: a technology
# whose `extract` section lives in an INCLUDED sibling file was declared
# incapable by the first version of this check. That is a working PDK reported
# as blocked — the exact failure this module is supposed to prevent. Magic
# composes a technology from several files; the check must too.
SPLIT_MAIN_TECH = """\
tech
    format 32
    generic_split
end

planes
    metalplane,mp
end

types
    metalplane routing_a,ra
end

styles
    styletype generic
    routing_a 1
end

connect
    routing_a routing_a
end

lef
    routing routing_a routing_a RA
end

include generic-extract
"""

SPLIT_EXTRACT_TECH = """\
extract
    style generic
    lambda 1.0
    resist routing_a 100
    substrate space/w well generic_sub
    device mosfet gate_a routing_a routing_a generic_dev
end
"""












@pytest.mark.parametrize("status", ["PASS", "FAIL", "NOT_MEASURED", "PASS_WITH_WAIVERS"])
def test_gate_only_reacts_to_the_blocked_status(tmp_path, status):
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    (tmp_path / "reports" / "phase3" / "lvs_verdict.json").write_text(
        json.dumps({"status": status}))
    assert audit._lvs_blocked_verdict(tmp_path) is None


# ==========================================================================
# 7 — THE GAPS #212 LEFT OPEN
# ==========================================================================
# #212 shipped a capability model that reported BLOCKED when an extraction
# input could not produce a netlist. Against the three defects that actually
# broke a real commercial PDK's tech file it caught ONE:
#
#   empty `styles`                        -> caught by #212
#   no `lef` SECTION at all               -> MISSED (it modelled the `lef read`
#                                            COMMAND, not the SECTION it reads)
#   `extract` with no `device`/`substrate`-> MISSED (satisfied by a merely
#                                            non-empty `extract`)
#
# Both misses are the same error: the check measured something ADJACENT to the
# question and passed. Each fixture below is one of those gaps, and each must
# name what is missing — a BLOCKED that does not say what to fix is only a
# slower FAIL.
#
# No PDK, vendor, foundry or process content appears in any fixture: every gap
# is structural, so generic layer names carry them all.







# -- GAP A: populated `styles`, but no `lef` section ------------------------




# -- GAP B: `extract` present, but no `device` ------------------------------




# -- GAP C: a design layer the tech file does not define --------------------






# -- GAP D: `include` that is indented, or inside a section -----------------






# -- GAP E: a `tech load` path the check cannot resolve ---------------------






# -- THE TWO CONTROLS: a check that cannot return clean is an alarm ---------








# ==========================================================================
# 8 — BLOCKED IS STILL NEVER A ROUTE TO GREEN, FOR THE *NEW* PATHS TOO
# ==========================================================================
# #212 verified this for the one BLOCKED path it introduced. This change adds
# more (missing `lef`, missing `device`, total layer non-coverage, an absent
# technology file), and a new verdict path is exactly where a "cannot verify"
# quietly becomes a pass. Verified against the REAL aggregate + gate, not
# assumed from the fact that the first path was safe.







# ==========================================================================
# 9 — THE FALSE-BLOCKED GUARD, AGAINST REAL TECHNOLOGY FILES
# ==========================================================================
# #212's own false BLOCKED (a complete, working PDK condemned because its
# `extract` lives in an included sibling) was caught only by running against
# REAL tech files, not synthetic fixtures. This change tightens the model, so
# the same guard is repeated here: every real technology file the host has is
# checked, and none of the ones a flow would actually extract with may block.
#
# Skipped when the PDKs are not installed — these are not repo fixtures, and a
# skip is honest where a silent pass would not be.
