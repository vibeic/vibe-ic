#!/usr/bin/env python3
"""The stage-2 ON-PASS review — and the control that stops it manufacturing
confidence in either direction.

WHAT WAS MISSING, MEASURED
==========================
Stage 2 turns the RTL into the netlist place-and-route builds. It declares
twelve steps, and MEASURED on `flow/phase1_phase2_phase3.yaml` at v1.12.100
every gate on them reads the ARTEFACT or another artefact:

    step 9        synth_netlist_check     is it technology-mapped
                  provenance_check        did Yosys produce it
    step 13       lec_equivalence_check   does it match the RTL
    11/DT1-DT3    dft_*_coverage_check    what did ATPG reach
    steps 7/8/14  sdc_*, yosys_*          the constraints and the script

Exactly ONE of them opens `phase1/generated_docs/` at all — `sdc_validator_check
--l8`, for the clock period. NOTHING in stage 2 compares the netlist to the
design's own declared INTERFACE. So the stage signs off the thing stage 3 will
build without once asking whether it is the thing that was asked for, and a
netlist that carries the wrong pins passes every gate in the stage and is then
carried faithfully to GDS by every downstream gate doing its job correctly:
LVS proves the layout matches the netlist, DRC proves it against the PDK, and
both are correct about an interface nobody asked for.

R2 IS NOT R1 AT A DIFFERENT ADDRESS
===================================
Stage 1's R1 asks whether the intent's top-module NAME is a module the RTL
declares. R2 asks whether the intent's PINS are ports the netlist BUILDS. The
netlist is the first artefact in the flow whose interface is concrete —
parameters resolved, the wrapper chosen, widths fixed — and it is the artefact
stage 3 consumes. `test_r1_disarms_on_the_cell_r2_rejects` pins the case that
makes them different rather than nested.

BOTH DIRECTIONS, ON REAL PUBLISHED ARTEFACTS
============================================
A reviewer that never rejects is worse than none; one that rejects everything
is worse still. Every case below runs on a published cell, none invented:

  ACCEPT  `accept_spm`            ic/spm/v1.10.18_sky130A — the intent's five
                                  pins are the netlist top's five ports.
  REJECT  `reject_opentitan_aes`  ic/opentitan_aes — the intent declares six
                                  pins out of the design input's own interface
                                  table (`input/docs/aes_interfaces.md`), and
                                  the netlist tops out at `chip_top` carrying
                                  eight ports of which NOT ONE is among them.
                                  The chip has no entropy interface, no
                                  key-manager sideload, no life-cycle escalation
                                  input and no idle output.
  DISARM  `disarm_caravel`        ic/caravel_user_project/v1.9.43_sky130A — two
                                  intent pins are absent from the netlist and
                                  the intent ITSELF marks both a supply. This is
                                  the narrowing control: MEASURED over the
                                  published corpus the rejection set is 3 of 11
                                  comparable cells without the disarm and 1 of
                                  11 with it, and 2 of the 3 are this one cell's
                                  two supply pins.

`fixtures/.../PROVENANCE.json` carries every source file's sha256. One file is a
disclosed REDUCTION (the 12 MB opentitan_aes netlist, cut to its interface by a
command recorded there); `test_the_reduced_fixture_and_the_live_netlist_agree`
proves the reduction changed no verdict.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIX = Path(__file__).resolve().parent / "fixtures" / "stage2_on_pass_review"
ACCEPT = FIX / "accept_spm"
REJECT = FIX / "reject_opentitan_aes"
DISARM = FIX / "disarm_caravel"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")


def run(project, *extra, stage="stage2", flow=None, emit=None):
    """Invoke the review exactly as the flow declares it."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", stage,
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


def tree(tmp_path, which):
    """A writable copy of one published fixture cell. A rejection WRITES the
    run's own regression into the run tree, so nothing here ever writes into
    the shipped fixture."""
    d = tmp_path / which.name
    if not d.exists():
        shutil.copytree(which, d)
    return d


def declaration(stage="stage2"):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == stage:
            return st.get("on_pass_review")
    raise AssertionError(f"{stage} is not declared")


def flow_with(tmp_path, **override):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == "stage2":
            st["on_pass_review"] = {**st["on_pass_review"], **override}
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_stage2_declares_an_on_pass_review_naming_a_verification_tier_skill():
    d = declaration()
    assert d is not None, "stage2 declares no on_pass_review"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking"), (
        "BLOCKING vs ADVISORY must be declared, and declared HERE — whether a "
        "rejection stops the flow is the flow's decision, not the reviewer's")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, (
        f"{d['skill']!r} is not a member of the verification tier {tier}")
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()


def test_the_declaration_is_not_a_second_membership_roster():
    """`flow_stage_membership_single_declaration_check` P1 discovers a roster by
    SHAPE: any stage key whose value is a list naming declared step ids is a
    second membership declaration. This block is a mapping and names no step."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step_ids = {str(s["id"]) for s in doc["steps"]}
    d = declaration()
    for key, val in d.items():
        if isinstance(val, list):
            named = {str(v) for v in val} & step_ids
            assert not named, f"on_pass_review.{key} names step id(s) {named}"


def test_the_four_required_parts_are_declared_by_the_flow():
    assert declaration()["rejection_requires"] == [
        "intent", "artefact", "contradiction", "test"]


def test_stage1s_declaration_is_untouched():
    """The control that must not move. Seven stages are being wired in
    parallel; stage 1 is the one already on main and this change may not
    disturb it."""
    d = declaration("stage1")
    assert d["skill"] == "phase2-rtl-verify"
    assert d["artefact"] == ["phase2/stage1/rtl/", "reports/phase2/"]
    assert d["rejection_requires"] == ["intent", "artefact", "contradiction",
                                       "test"]


# ─────────────────────────────────────────────────────────────────────────────
# BOTH DIRECTIONS, ON REAL ARTEFACTS
# ─────────────────────────────────────────────────────────────────────────────
def test_a_real_known_good_artefact_is_accepted(tmp_path):
    r = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ACCEPT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == []
    assert rec["not_checked"] == []
    art = rec["observations"][0]["artefact"]
    assert art["top"] == "spm"
    assert art["port_names"] == ["clk", "p", "rst", "x", "y"]


def test_a_real_netlist_that_builds_none_of_the_declared_pins_is_rejected(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == "R2_INTENT_PIN_NOT_IN_NETLIST"

    # the INTENT it read — the design INPUT's own interface table, via L9
    assert f["intent"]["field"] == "top_ports"
    assert f["intent"]["value"] == ["idle_o", "lc_escalate_en_i", "edn_o",
                                    "edn_i", "keymgr_key_i", "aes"]
    assert all(p["evidence"] == "input/docs/aes_interfaces.md"
               for p in f["intent"]["pins"])

    # the ARTEFACT fact it read
    assert f["artefact"]["top"] == "chip_top"
    assert f["artefact"]["port_names"] == [
        "aes_input", "aes_key", "aes_output", "alert_fatal_o",
        "alert_recov_o", "clk_i", "rst_ni", "test_done_o"]

    # the CONTRADICTION — the intersection is EMPTY, all six, not some
    assert [r_["name"] for r_ in f["absent_signal_pins"]] == f["intent"]["value"]
    assert f["disarmed"] == [], "no supply pin is involved in this rejection"
    assert "keymgr_key_i" in f["contradiction"]

    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (tmp_path / REJECT.name / f["test"]).is_file(), f["test"]


def test_the_emitted_test_fails_today_and_passes_when_the_run_is_repaired(tmp_path):
    """The doctrine, executable. A rejection must be proven by an executable
    test, and that is only wired if the test discriminates: run the EMITTED
    file against the defective run (must fail), then synthesise a top that
    carries the declared pins and run THE SAME FILE again (must pass)."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout
    emitted = run_dir / json.loads((tmp_path / "r.json").read_text())[
        "rejections"][0]["test"]
    assert emitted.is_file()

    before = subprocess.run([sys.executable, str(emitted)],
                            capture_output=True, text=True)
    assert before.returncode == 1, (
        "the emitted test does not fail on the artefact it was emitted from:\n"
        + before.stdout + before.stderr)
    assert "keymgr_key_i" in before.stdout

    netlist = run_dir / "phase2" / "stage2" / "synth" / "netlist.v"
    netlist.write_text(
        "module chip_top(clk_i, idle_o, lc_escalate_en_i, edn_o, edn_i,\n"
        "                keymgr_key_i, aes);\n"
        "  input clk_i;\n  output idle_o;\n  input lc_escalate_en_i;\n"
        "  output edn_o;\n  input edn_i;\n  input keymgr_key_i;\n"
        "  input aes;\nendmodule\n", encoding="utf-8")
    after = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True)
    assert after.returncode == 0, (
        "the emitted test still fails after the repair it asks for:\n"
        + after.stdout + after.stderr)


def test_the_emitted_test_refuses_an_empty_artefact_rather_than_passing(tmp_path):
    """The emitted test carries the same rule its emitter does: an empty
    artefact refutes nothing and certifies nothing. Emptying the netlist must
    not be a way to make the run's own regression go green."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads((tmp_path / "r.json").read_text())[
        "rejections"][0]["test"]
    (run_dir / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "// nothing was synthesised\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "declares no module" in out.stdout


def test_the_rejection_is_caused_by_the_port_list_and_nothing_else(tmp_path):
    """The negative control for the rejection itself. Copy the REAL reject tree
    and change ONE thing — the netlist top's port list — leaving the same L9,
    the same cell, the same everything. It must flip to ACCEPT, which is what
    proves the finding is about the artefact rather than about that cell."""
    repaired = tmp_path / "repaired"
    shutil.copytree(REJECT, repaired)
    (repaired / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module chip_top(idle_o, lc_escalate_en_i, edn_o, edn_i,\n"
        "                keymgr_key_i, aes);\n"
        "  output idle_o;\n  input lc_escalate_en_i;\n  output edn_o;\n"
        "  input edn_i;\n  input keymgr_key_i;\n  input aes;\nendmodule\n",
        encoding="utf-8")
    assert run(tree(tmp_path, REJECT), "--stage-verdict", "PASS").returncode == 1
    after = run(repaired, "--stage-verdict", "PASS")
    assert after.returncode == 0, after.stdout + after.stderr


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """All three directions in ONE invocation shape. A rule that started
    refusing everything would take the accept and disarm cases with it; a rule
    that stopped biting would take the reject case. None may move alone."""
    good = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS")
    bad = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    dis = run(tree(tmp_path, DISARM), "--stage-verdict", "PASS")
    assert (good.returncode, bad.returncode, dis.returncode) == (0, 1, 0), (
        f"good={good.returncode} bad={bad.returncode} disarm={dis.returncode}\n"
        f"{good.stdout}\n---\n{bad.stdout}\n---\n{dis.stdout}")


# ─────────────────────────────────────────────────────────────────────────────
# the disarm, and the measurement that narrowed it
# ─────────────────────────────────────────────────────────────────────────────
def test_a_pin_the_intent_itself_declares_a_supply_disarms(tmp_path):
    """A non-power-aware synthesised netlist carries no supply port, and supply
    connectivity is signed off in stage 3 by the power grid and power-aware
    LVS. The disarm reads the intent's OWN role field and says which."""
    r = run(tree(tmp_path, DISARM), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DISARMED" in r.stdout
    f = json.loads((tmp_path / "r.json").read_text())["observations"][0]
    assert [d["name"] for d in f["disarmed"]] == ["vccd1", "vssd1"]
    assert [d["intent_declares_supply"] for d in f["disarmed"]] == [
        "io='POWER'", "io='GROUND'"]


def test_without_the_disarm_the_same_cell_would_reject(tmp_path):
    """The measurement that made the disarm a NARROWING and not a decoration.
    Strip the intent's own role fields from the two supply pins — nothing else
    changes, same netlist, same cell — and the cell rejects. That is the 3-of-11
    the disarm removes; leaving it in would have made the rule fire on the two
    pins Yosys is correct not to emit."""
    widened = tmp_path / "widened"
    shutil.copytree(DISARM, widened)
    l9p = widened / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    d = json.loads(l9p.read_text(encoding="utf-8"))
    for field in ("top_ports", "ports", "top_module_pins"):
        for pin in d.get(field) or []:
            if isinstance(pin, dict) and pin.get("name") in ("vccd1", "vssd1"):
                pin["io"] = None
    l9p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = run(widened, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    f = json.loads((tmp_path / "r.json").read_text())["rejections"][0]
    assert [p["name"] for p in f["absent_signal_pins"]] == ["vccd1", "vssd1"]


def test_the_disarm_is_read_off_the_intent_and_not_off_the_pin_name(tmp_path):
    """A name-shaped disarm would silence a real signal pin that happens to be
    named like a rail. Rename the two pins to something no rail convention
    covers, keep the declared role, and the disarm must still fire; keep the
    names and drop the role, and it must not (the test above)."""
    renamed = tmp_path / "renamed"
    shutil.copytree(DISARM, renamed)
    l9p = renamed / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    d = json.loads(l9p.read_text(encoding="utf-8"))
    for field in ("top_ports", "ports", "top_module_pins"):
        for pin in d.get(field) or []:
            if isinstance(pin, dict) and pin.get("name") in ("vccd1", "vssd1"):
                pin["name"] = pin["name"] + "_renamed_beyond_any_convention"
    l9p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = run(renamed, "--stage-verdict", "PASS")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DISARMED" in r.stdout


def test_ports_the_netlist_adds_are_reported_and_never_rejected(tmp_path):
    """DFT insertion, the chip_top wrapper and tie cells all add ports the
    intent never declares, and they are the flow doing its job. The reverse
    direction is an observation, and asserting it here is what stops a later
    author promoting it to a finding without measuring first."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    f = json.loads((tmp_path / "r.json").read_text())["rejections"][0]
    assert f["artefact"]["extra_ports_not_in_intent"] == \
        f["artefact"]["port_names"]
    assert "NOT A FINDING" in r.stdout

    # and a cell whose ONLY difference from its intent is extra ports accepts
    extra = tmp_path / "extra_only"
    shutil.copytree(ACCEPT, extra)
    n = extra / "phase2" / "stage2" / "synth" / "netlist.v"
    n.write_text(n.read_text(encoding="utf-8", errors="replace")
                 .replace("module spm(clk, rst, x, y, p);",
                          "module spm(clk, rst, x, y, p, sin, shift, sout);\n"
                          "  input sin;\n  input shift;\n  output sout;"),
                 encoding="utf-8")
    assert run(extra, "--stage-verdict", "PASS").returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# R2 is not R1 at a different address
# ─────────────────────────────────────────────────────────────────────────────
def test_r1_disarms_on_the_cell_r2_rejects(tmp_path):
    """The case that makes the two rules different rather than nested. This
    cell's intent discloses `no_top_module_in_input: true`, so stage 1's R1
    correctly says nothing about it — and its netlist still builds none of the
    six pins the design input declares."""
    d = json.loads((REJECT / "phase1" / "generated_docs"
                    / "L9_INTEGRATION_SPEC.json").read_text(encoding="utf-8"))
    assert d["no_top_module_in_input"] is True
    assert d["top_module_extraction_strategy"] == "canonical_chip_top_sentinel"
    assert run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
               stage="stage2").returncode == 1


# ─────────────────────────────────────────────────────────────────────────────
# it fires on SUCCESS, and only on an ESTABLISHED success
# ─────────────────────────────────────────────────────────────────────────────
def test_the_review_does_not_run_on_a_stage_that_failed(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "FAIL")
    assert r.returncode == 2, r.stdout
    assert "did not pass" in r.stdout


def test_an_unestablished_verdict_is_not_a_pass(tmp_path):
    r = run(tree(tmp_path, REJECT))
    assert r.returncode == 2, r.stdout
    assert "unestablished" in r.stdout


def test_a_compliance_report_supplies_the_verdict(tmp_path):
    """BOTH ways: a green stage-2 row reaches the rules, a red one does not."""
    green = tmp_path / "green.json"
    green.write_text(json.dumps({"steps": [
        {"id": 9, "stage": "stage2", "status": "PASS"},
        {"id": 1, "stage": "stage1", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": 9, "stage": "stage2", "status": "PASS"},
        {"id": 13, "stage": "stage2", "status": "FAIL"}]}))
    assert run(tree(tmp_path, REJECT), "--compliance", str(green)).returncode == 1
    assert run(tree(tmp_path, ACCEPT), "--compliance", str(green)).returncode == 0
    assert run(tree(tmp_path / "red", REJECT),
               "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        "benchmark/golden/expected_netlist_ports.json"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "golden" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: same shape, no denied segment, and the review
    reaches its rules and rejects as before. A guard that refused everything
    would pass the test above."""
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        "phase1/generated_docs/L2_FRS.json"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 1, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# a rejection carries evidence or it is not a rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_an_unproven_rejection_is_not_emitted_as_a_rejection(tmp_path):
    """Raise the evidence bar to something this finding does not carry. It must
    NOT come out as rc 1 with a missing part and must NOT be downgraded to a
    pass: it is NOT CHECKED, and the reason names the part that is missing."""
    flow = flow_with(tmp_path, rejection_requires=[
        "intent", "artefact", "contradiction", "test", "waiver_reference"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"), flow=flow)
    assert r.returncode == 2, r.stdout
    assert "could not be proven" in r.stdout
    assert "waiver_reference" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [], "an unproven finding was emitted anyway"
    assert rec["unproven_rejections"][0]["missing_evidence"] == ["waiver_reference"]


# ─────────────────────────────────────────────────────────────────────────────
# an empty or ambiguous artefact certifies nothing
# ─────────────────────────────────────────────────────────────────────────────
def test_a_declared_netlist_that_was_never_published_is_not_checked(tmp_path):
    bare = tmp_path / "no_netlist"
    (bare / "phase1" / "generated_docs").mkdir(parents=True)
    shutil.copy(ACCEPT / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json",
                bare / "phase1" / "generated_docs")
    r = run(bare, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "no netlist" in r.stdout


def test_an_intent_with_no_pin_list_is_not_checked(tmp_path):
    """An absent declaration is not an agreement. MEASURED: 4 of the 15
    published cells carrying a stage-2 netlist declare no pin in any of L9's
    three pin fields, and answering ACCEPT for them would be a review of
    nothing reporting a pass."""
    d = tmp_path / "no_pins"
    shutil.copytree(ACCEPT, d)
    l9p = d / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    doc = json.loads(l9p.read_text(encoding="utf-8"))
    for field in ("top_ports", "ports", "top_module_pins"):
        doc[field] = []
    l9p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "declares no external pin" in r.stdout


def test_a_netlist_with_no_single_structural_root_is_not_checked(tmp_path):
    """Two roots is two candidate interfaces, and picking one would be the
    reviewer choosing which chip it is reviewing."""
    d = tmp_path / "two_roots"
    shutil.copytree(ACCEPT, d)
    n = d / "phase2" / "stage2" / "synth" / "netlist.v"
    n.write_text(n.read_text(encoding="utf-8", errors="replace")
                 + "\nmodule second_root(input a);\nendmodule\n",
                 encoding="utf-8")
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "structural root" in r.stdout


def test_a_top_with_no_port_is_not_an_acceptance(tmp_path):
    d = tmp_path / "no_ports"
    shutil.copytree(ACCEPT, d)
    (d / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module spm;\nendmodule\n", encoding="utf-8")
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "declares NO port" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the partition, pinned, and the fixture's fidelity
# ─────────────────────────────────────────────────────────────────────────────
#: MEASURED on benchmark-data, 2026-08-30, over every published cell carrying
#: both an L9 and `phase2/stage2/synth/netlist.v`. `ic/opentitan_aes` is a
#: verified true positive: its netlist's structural top builds none of the six
#: pins `input/docs/aes_interfaces.md` declares.
_CORPUS_REJECTS = {"ic/opentitan_aes"}


def _corpus_cells(root):
    return sorted({p.parents[2] for p in
                   root.rglob("phase1/generated_docs/L9_INTEGRATION_SPEC.json")
                   if (p.parents[2] / "phase2/stage2/synth/netlist.v").is_file()})


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_partition_over_the_published_corpus_does_not_move():
    """Pins BOTH sides on the live corpus. The reject set is named cell by cell
    so a rule that widened shows up as an extra name rather than as a count
    nobody reads; the accept side is required to be non-empty so a rule that
    stopped biting cannot pass by rejecting everything."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cells = _corpus_cells(root)
    if not cells:
        pytest.skip("the corpus carries no cell with an L9 and a stage-2 netlist")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_stage2_corpus_"))
    rejects, accepts = set(), set()
    for i, cell in enumerate(cells):
        rc = run(cell, "--stage-verdict", "PASS", emit=scratch / f"cell{i}").returncode
        rel = str(cell.relative_to(root))
        if rc == 1:
            rejects.add(rel)
        elif rc == 0:
            accepts.add(rel)
    assert rejects == _CORPUS_REJECTS & {str(c.relative_to(root)) for c in cells}, (
        f"the rejection set moved: {sorted(rejects)}")
    assert accepts, "every cell was refused; a reviewer that rejects all is none"


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_reduced_fixture_and_the_live_netlist_agree(tmp_path):
    """PROVENANCE.json discloses that the reject tree's netlist is a REDUCTION
    of an 11973774-byte source. A reduction that changed the verdict would make
    the whole control a fixture the author wrote, so where the corpus resolves
    the live cell is measured directly and must reach the same rejection."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    live = root / json.loads((FIX / "PROVENANCE.json").read_text(
        encoding="utf-8"))["trees"]["reject_opentitan_aes"]["cell"]
    if not (live / "phase2/stage2/synth/netlist.v").is_file():
        pytest.skip(f"{live} is not in this corpus")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_stage2_live_"))
    live_run = run(live, "--stage-verdict", "PASS", emit=scratch,
                   **{})
    fixture_run = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    assert live_run.returncode == fixture_run.returncode == 1, (
        f"live={live_run.returncode} fixture={fixture_run.returncode}")
    for pin in ("idle_o", "lc_escalate_en_i", "edn_o", "edn_i",
                "keymgr_key_i", "aes"):
        assert pin in live_run.stdout and pin in fixture_run.stdout


def test_the_fixture_is_what_provenance_says_it_is():
    """Every shipped byte is either a verbatim copy or a disclosed reduction,
    and the sha256 recorded here is the shipped file's. A fixture whose
    provenance record drifted would let an authored artefact ship as a
    published one."""
    import hashlib
    prov = json.loads((FIX / "PROVENANCE.json").read_text(encoding="utf-8"))
    seen = set()
    for name, t in prov["trees"].items():
        for rel, rec in t["files"].items():
            f = FIX / name / rel
            assert f.is_file(), f
            assert hashlib.sha256(f.read_bytes()).hexdigest() == rec["sha256"], rel
            assert f.stat().st_size == rec["bytes"], rel
            if not rec["verbatim"]:
                assert rec["source_sha256"] and rec["reduction"], rel
            seen.add(f.resolve())
    on_disk = {p.resolve() for p in FIX.rglob("*")
               if p.is_file() and p.name != "PROVENANCE.json"}
    assert on_disk == seen, (
        f"undeclared fixture file(s): {sorted(str(p) for p in on_disk - seen)}")


# ─────────────────────────────────────────────────────────────────────────────
# the interface is read out of CODE, not out of a retired-interface note
# ─────────────────────────────────────────────────────────────────────────────
#
# `_NETLIST_PORT_RE` is `^[ \t]*(input|output|inout)\b ... [;,]`. A `//` prefix
# breaks that anchor, but a `/* ... */` block does not: a line inside one starts
# at column 0 like any other. R2 compares these names against the pins the
# intent declared, so a port that exists only in a comment is either a pin the
# netlist appears to build and does not, or an "extra port" reported against a
# netlist that has none.
#
# Both cases are PAIRED with the same declaration uncommented, so a fix that
# stopped finding ports would fail the control.

sys.path.insert(0, str(PROGRAMS))
import stage_on_pass_review as _sopr  # noqa: E402

_BODY_WITH_A_RETIRED_NOTE = """
input  clk;
output done;
/* retired in rev C, kept for the record:
input  phantom_clk;
output phantom_done;
*/
"""


def test_a_port_declared_only_inside_a_block_comment_is_not_a_port():
    ports = _sopr.netlist_port_directions(_BODY_WITH_A_RETIRED_NOTE)
    assert set(ports) == {"clk", "done"}, (
        f"a /* */ note was read as a port declaration: {sorted(ports)}")


def test_control_the_same_ports_uncommented_are_found():
    """The pair. Without it, `return {}` satisfies the case above."""
    live = _BODY_WITH_A_RETIRED_NOTE.replace(
        "/* retired in rev C, kept for the record:\n", "").replace("*/\n", "")
    ports = _sopr.netlist_port_directions(live)
    assert set(ports) == {"clk", "done", "phantom_clk", "phantom_done"}
    assert ports["phantom_clk"] == "input"
    assert ports["phantom_done"] == "output"


def test_a_line_comment_after_a_real_declaration_does_not_lose_it():
    """Stripping must not reach past the declaration it trails."""
    ports = _sopr.netlist_port_directions(
        "input  clk;   // the only clock\noutput done;  // pulse\n")
    assert ports == {"clk": "input", "done": "output"}


def test_the_strip_is_idempotent_on_the_live_caller_path(tmp_path):
    """`read_netlist_interface` already hands over a stripped body, so this
    call changes nothing on the live path -- asserted, not assumed."""
    nl = tmp_path / "netlist.v"
    nl.write_text("module top (clk, done);\n" + _BODY_WITH_A_RETIRED_NOTE +
                  "endmodule\n")
    got = _sopr.read_netlist_interface(nl)
    assert got["readable"] is True and got["top"] == "top"
    assert got["port_names"] == ["clk", "done"]
