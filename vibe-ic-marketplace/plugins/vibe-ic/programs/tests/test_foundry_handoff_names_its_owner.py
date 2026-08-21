"""Step 38 must say WHO each open item is pending on, and must not report a kit
complete over the shuttle operator's own refusal.

THE TWO DEFECTS
===============
(1) THE PILE. Nine fields carried the prefix `PENDING_FOUNDRY_` and nothing
    else. They shared a prefix and a silence about who would close them, and
    they were not one thing: the mask layer table and the stepper are the party
    that owns the RETICLE; the yield target and the WAT limits are a CONTRACT
    that does not exist at all for a shuttle slot buyer; the ATE loadboard is
    the TEST HOUSE's; the test patterns are OURS. The prefix was doing the work
    of an answer.

(2) THE MODE. On a multi-project shuttle the submitter buys a SLOT, not a
    reticle — the scribe line, the PCM structures and the mask layer table are
    the OPERATOR's, and `PENDING_FOUNDRY` is then the CORRECT answer rather
    than a gap. On a dedicated mask set the same fields are the customer's
    problem. Step 38 did not know which case it was in, and neither did its
    gate.

    Step 37.5ic — declared 2026-08-20 — runs the shuttle operator's own
    container and records its verdict at `reports/phase3/shuttle_precheck.json`.
    That report names the operator, so on the shuttle path the owner's identity
    is a MEASURED fact off a run rather than a declaration. Step 38 had no idea
    the step existed: the flow declares `blocks_on: [37]` for step 38, NOT
    37.5ic, so a kit could be assembled, gated and reported complete while the
    counterparty's own tool had already refused the layout it describes.

WHAT IS NOT ASSUMED
===================
The ABSENCE of a precheck report is NOT a dedicated mask set. It is far more
likely that 37.5ic has not run. Reading absence as a determination would
rebuild this repository's own recurring defect — an empty result made
indistinguishable from a determined one — one level up, so the third value is
UNDECLARED and it is neither of the other two. Pinned below.

SCOPE OF THE NEW GATE RULES, and why the corpus does not move
=============================================================
The ownership rule applies only to members that declare `handoff_mode`, i.e.
members this generation wrote. MEASURED over the 8 published roots carrying a
hand-off kit: the rule set and rc are IDENTICAL before and after, 8 of 8. Those
kits predate `open_items` and are untouched; they are already red for reasons
this change does not touch (`cell_count=-1`, `pdk=unknown`, absent chip GDS).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import foundry_handoff_pack_gen as FH  # noqa: E402

CHECKER = PROGRAMS / "foundry_handoff_package_check.py"


def _gate(proj):
    """(rc, set-of-rules) from the substance gate."""
    out = proj / "gate.json"
    rc = subprocess.run(
        [sys.executable, str(CHECKER), str(proj), "--json", str(out)],
        capture_output=True, text=True).returncode
    try:
        rules = {f["rule"] for f in json.loads(out.read_text())["findings"]}
    except (OSError, ValueError, KeyError):
        rules = set()
    return rc, rules


# ── the mode is three-valued, and absence is the third value ───────────────

def test_no_precheck_report_is_undeclared_not_dedicated(tmp_path):
    proj = _project(tmp_path)
    mode = FH._handoff_mode(proj)
    assert mode["mode"] == FH.MODE_UNDECLARED
    assert mode["operator"] is None
    # The basis must SAY why, not merely be empty — the whole point is that a
    # reader can tell "nobody asked" from "asked and got a no".
    assert "37.5ic" in mode["basis"]


def test_a_precheck_report_puts_the_kit_on_the_shuttle_path(tmp_path):
    proj = _project(tmp_path)
    _precheck(proj, verdict="PASS")
    mode = FH._handoff_mode(proj)
    assert mode["mode"] == FH.MODE_SHUTTLE
    assert mode["operator"] == "an_open_mpw_operator"
    # The kit REFERENCES the operator's verdict and pins the bytes it saw,
    # rather than copying the report: a copy can drift from what it was copied
    # from, and "the artefact changed after the evidence" is the shape this
    # repository fails on most expensively.
    assert mode["precheck_report"] == "reports/phase3/shuttle_precheck.json"
    assert (mode["precheck_report_sha256"] or "").startswith("sha256:")


# ── ownership: every open item names the party that closes it ──────────────

def test_every_pending_field_names_an_owner_and_a_closing_artefact(tmp_path):
    proj = _project(tmp_path)
    FH.main([str(proj)])
    kit = proj / "phase3/stage4/foundry_handoff"
    seen = {}
    for member in ("mask_spec.json", "wat_plan.json",
                   "corner_test_vectors.json"):
        data = json.loads((kit / member).read_text())
        pending = {k for k in data if k.startswith("PENDING_FOUNDRY_")}
        owned = {i["field"] for i in data["open_items"] if i.get("owner")}
        assert pending <= owned, f"{member}: unowned {pending - owned}"
        for item in data["open_items"]:
            assert item["closed_by"], f"{member}:{item['field']} names no artefact"
            seen[item["field"]] = item["owner"]
    # The differentiation is the point: three DIFFERENT parties, and one of the
    # items is ours. A taxonomy that maps everything to "foundry" would pass
    # every assertion above and would still be the pile.
    assert seen["PENDING_FOUNDRY_test_patterns"] == FH.OWNER_US
    assert seen["PENDING_FOUNDRY_loadboard_id"] == FH.OWNER_TEST_HOUSE
    assert seen["PENDING_FOUNDRY_yield_target_pct"] == FH.OWNER_CONTRACT
    assert seen["PENDING_FOUNDRY_mask_layers"] == FH.OWNER_FOUNDRY


def test_the_shuttle_reassigns_the_reticle_items_to_the_operator(tmp_path):
    """The reticle, its scribe line and its PCM structures are shared across
    every project in a shuttle. On that path they are the OPERATOR's, and the
    kit must name that operator rather than an abstract foundry."""
    proj = _project(tmp_path)
    _precheck(proj, verdict="PASS")
    FH.main([str(proj)])
    kit = proj / "phase3/stage4/foundry_handoff"
    mask = json.loads((kit / "mask_spec.json").read_text())
    by_field = {i["field"]: i for i in mask["open_items"]}
    item = by_field["PENDING_FOUNDRY_mask_layers"]
    assert item["owner"] == FH.OWNER_OPERATOR
    assert item["owner_name"] == "an_open_mpw_operator"
    # A slot buyer has no per-customer lot yield target: the item does not
    # merely have a different owner on this path, it does not exist.
    wat = json.loads((kit / "wat_plan.json").read_text())
    yt = {i["field"]: i for i in wat["open_items"]}[
        "PENDING_FOUNDRY_yield_target_pct"]
    assert yt["status"] == FH.STATUS_NA


def test_the_scribe_note_names_the_owner_and_cites_the_search(tmp_path):
    """LibreLane's `KLayout.SealRing` skips with a message naming the PDK and
    the missing variable. The note copies that shape: the mode, the party, the
    artefact that would close it — and the measured search that established no
    open PDK ships a scribe layout at all."""
    proj = _project(tmp_path)
    _precheck(proj, verdict="PASS")
    FH.main([str(proj)])
    note = (proj / "phase3/stage4/foundry_handoff"
            / "scribe_line_layout.PENDING_FOUNDRY.txt").read_text()
    assert "shuttle_operator" in note
    assert "an_open_mpw_operator" in note
    assert "closed by" in note
    assert "process_monitor" in note and "0 files" in note
    # It must still not be a file wearing the .gds name (#446).
    assert not (proj / "phase3/stage4/foundry_handoff"
                / "scribe_line_layout.gds").exists()


# ── the gate: each new rule fires on the break it defends, and only then ────

def test_clean_kit_with_an_accepting_operator_passes(tmp_path):
    """The green control. Without it, every red below proves nothing."""
    proj = _project(tmp_path, with_chip_gds=True)
    _precheck(proj, verdict="PASS")
    FH.main([str(proj)])
    rc, rules = _gate(proj)
    assert rc == 0, rules
    assert "FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED" not in rules
    assert "FOUNDRY_HANDOFF_UNOWNED_PENDING" not in rules
    assert "FOUNDRY_HANDOFF_MODE_MISDECLARED" not in rules


def test_an_operator_refusal_stops_the_handoff(tmp_path):
    proj = _project(tmp_path, with_chip_gds=True)
    _precheck(proj, verdict="FAIL")
    FH.main([str(proj)])
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED" in rules


def test_not_determined_is_not_an_acceptance(tmp_path):
    """`tapeout_readiness_check` returns rc 1 for NOT_DETERMINED as well as for
    FAIL, "because a silence credited as a pass is the defect this gate exists
    for". Accepting it here would re-open that door one step downstream."""
    proj = _project(tmp_path, with_chip_gds=True)
    _precheck(proj, verdict="NOT_DETERMINED")
    FH.main([str(proj)])
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED" in rules


def test_an_unreadable_precheck_report_is_not_an_acceptance(tmp_path):
    proj = _project(tmp_path, with_chip_gds=True)
    (proj / "reports/phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports/phase3/shuttle_precheck.json").write_text("{ truncated")
    FH.main([str(proj)])
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED" in rules


def test_a_pending_field_with_no_owner_fails(tmp_path):
    """Plant the shrug the taxonomy exists to stop."""
    proj = _project(tmp_path, with_chip_gds=True)
    _precheck(proj, verdict="PASS")
    FH.main([str(proj)])
    member = proj / "phase3/stage4/foundry_handoff/mask_spec.json"
    data = json.loads(member.read_text())
    data["PENDING_FOUNDRY_overlay_budget"] = "Author: somebody."
    member.write_text(json.dumps(data, indent=2))
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_UNOWNED_PENDING" in rules


def test_deleting_open_items_does_not_escape_the_rule(tmp_path):
    """The obvious way round an ownership rule is to delete the list it reads.
    A member that declares `handoff_mode` and omits `open_items` is itself the
    finding."""
    proj = _project(tmp_path, with_chip_gds=True)
    _precheck(proj, verdict="PASS")
    FH.main([str(proj)])
    member = proj / "phase3/stage4/foundry_handoff/mask_spec.json"
    data = json.loads(member.read_text())
    data.pop("open_items")
    member.write_text(json.dumps(data, indent=2))
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_UNOWNED_PENDING" in rules


def test_a_kit_that_misstates_its_mode_fails(tmp_path):
    """The generator RECORDS the mode; the gate RE-DERIVES it from the same
    evidence and compares. Here the kit says shuttle and the operator's report
    is gone, so the kit and the run describe different situations — and the
    mode decides who owns the scribe line, the reticle and the mask layers."""
    proj = _project(tmp_path, with_chip_gds=True)
    _precheck(proj, verdict="PASS")
    FH.main([str(proj)])
    (proj / "reports/phase3/shuttle_precheck.json").unlink()
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_MODE_MISDECLARED" in rules


def test_a_kit_from_an_older_generator_is_not_reddened(tmp_path):
    """SCOPE CONTROL. The corpus carries kits that predate `open_items`; they
    must be left exactly as they were. Measured on the published corpus: rule
    set and rc identical before and after, 8 of 8."""
    proj = _project(tmp_path, with_chip_gds=True)
    FH.main([str(proj)])
    kit = proj / "phase3/stage4/foundry_handoff"
    for member in ("mask_spec.json", "wat_plan.json",
                   "corner_test_vectors.json"):
        data = json.loads((kit / member).read_text())
        data.pop("open_items", None)
        data.pop("handoff_mode", None)      # an OLD kit declares neither
        (kit / member).write_text(json.dumps(data, indent=2))
    rc, rules = _gate(proj)
    assert "FOUNDRY_HANDOFF_UNOWNED_PENDING" not in rules
    assert "FOUNDRY_HANDOFF_MODE_MISDECLARED" not in rules
    assert rc == 0, rules


def test_an_incomplete_kit_does_not_silence_a_proved_refusal(tmp_path):
    """LADDER ORDER, which this gate's own comment calls load-bearing: rc 2 is
    read as VACUOUS_PASS by `flow_compliance_check`, so a defect the gate has
    already PROVED must never be downgraded to it by an incomplete kit. A
    refusal is such a defect. The negative control is the line above it — with
    no kit AND no refusal there is nothing proved, and SKIP is correct."""
    proj = _project(tmp_path)                 # no hand-off kit generated
    rc, _ = _gate(proj)
    assert rc == 2, "nothing proved and no kit is a SKIP, not a verdict"
    _precheck(proj, verdict="FAIL")
    rc, rules = _gate(proj)
    assert rc == 1
    assert "FOUNDRY_HANDOFF_SHUTTLE_PRECHECK_REFUSED" in rules


# ── fixtures ───────────────────────────────────────────────────────────────

def _precheck(proj, verdict):
    """37.5ic's own report, in the shape `tapeout_readiness_check` writes.
    chip-AGNOSTIC: the operator name is a generic placeholder, not a real
    programme."""
    d = proj / "reports/phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "shuttle_precheck.json").write_text(json.dumps({
        "program": "tapeout_readiness_check",
        "verdict": verdict,
        "shuttle": "an_open_mpw_operator",
        "shuttle_status": "LIVE",
        "layouts_found": 1,
    }, indent=2))


def _project(tmp_path, with_chip_gds=False):
    p = tmp_path / "alpha"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/chip_top.sv").write_text(
        "module chip_top(input clk);\nendmodule\n")
    (p / "phase2/stage2/synth").mkdir(parents=True)
    (p / "phase2/stage2/synth/netlist.v").write_text(
        "module top(input clk);\n  buf_cell _0_ (.A(clk), .X());\nendmodule\n")
    (p / "phase3/stage3/pnr").mkdir(parents=True)
    (p / "phase3/stage3/pnr/pnr.tcl").write_text(
        "read_liberty /foss/pdks/examplepdk/examplepdk_sc__tt_025C_1v80.lib\n"
        "link_design chip_top\n")
    (p / "phase3/stage4/gds").mkdir(parents=True)
    name = "alpha.gds" if with_chip_gds else "chip_top.gds"
    (p / "phase3/stage4/gds" / name).write_bytes(b"\x00\x06\x00\x02alph")
    (p / "phase1/generated_docs").mkdir(parents=True)
    (p / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "alpha"}))
    return p
