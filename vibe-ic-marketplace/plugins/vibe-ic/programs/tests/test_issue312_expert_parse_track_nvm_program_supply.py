#!/usr/bin/env python3
"""test_issue312_expert_parse_track_nvm_program_supply.py

Two things land together and are tested together because one is the mechanism
and the other is its first payload:

  * `phase1_expert_parse_track` — the SECOND track, which reads the same design
    input independently, states what the L-docs SHOULD contain, and names every
    divergence. ADVISORY findings, MANDATORY execution.
  * `nvm_program_supply_intent` — the assessment library behind the track's one
    deterministic rule: the programmable-NVM programming-supply convention.

DEFERRED, deliberately: a standalone BLOCKING Phase-1 gate over that same
library. The convention is REPORTED here (named, printed, in the report) but
nothing stops on it. Turning a finding into an automatic stop is a separate
enforcement decision, and this one has never been observed firing on a real
design — every design on the fleet assesses as not-applicable. See
`test_the_deferred_hard_stop_is_a_recorded_fact_not_a_silence`, which fails if
that deferral ever stops being stated.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue312_expert_parse_track_nvm_program_supply.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import nvm_program_supply_intent as N          # noqa: E402
import phase1_expert_parse_track as T          # noqa: E402
import ic_expert_db_consistency_check as DBC   # noqa: E402
import _path_layout as _pl                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _track_report(project: Path) -> Path:
    """The track's report location, resolved through the SAME helper the track
    uses. Hardcoding the path here would let the two drift, and a report a
    reader cannot find is a track that looks like it never ran."""
    return _pl.report_path(project, "phase1/expert_parse_track.json")


def _answer(project: Path, expected_tokens=("VDDC",)) -> None:
    """Leave a minimal schema-valid IC Expert reading for execution tests."""
    out = _track_report(project).parent / "expert_parse_track_pack"
    out.mkdir(parents=True, exist_ok=True)
    (out / "l_doc_expectations.json").write_text(json.dumps({
        "expectations": [{
            "id": "supply_inventory::core_rail",
            "layer": "L1_DATASHEET",
            "field_path": "fields.pinout",
            "requirement": "the input-stated core supply terminal",
            "evidence": ["input RTL: core supply terminal"],
            "expected_tokens": list(expected_tokens),
        }],
    }))


# ── fixture construction ────────────────────────────────────────────────────

def _lef(master: str, power_pins, ground_pins=("VSS",)) -> str:
    body = [f"VERSION 5.8 ;", f"MACRO {master}", "  CLASS BLOCK ;",
            "  SIZE 100.0 BY 100.0 ;"]
    for p in power_pins:
        body += [f"  PIN {p}", "    DIRECTION INOUT ;", "    USE POWER ;",
                 f"  END {p}"]
    for g in ground_pins:
        body += [f"  PIN {g}", "    DIRECTION INOUT ;", "    USE GROUND ;",
                 f"  END {g}"]
    body += ["  PIN clk", "    DIRECTION INPUT ;", "    USE SIGNAL ;",
             "  END clk", f"END {master}", "END LIBRARY"]
    return "\n".join(body) + "\n"


_RTL_WITH_BURN_LOGIC = """
module chip_top (
  input         clk,
  input         rst_n,
  input         prog_req,
  input  [8:0]  prog_addr,
  input  [31:0] prog_data,
  output        prog_busy,
  input         VDDC,
  input         VSS
);
  wire       burn_start;
  wire [8:0] burn_addr;
  reg        burn_busy;
  {MASTER} u_array (.clk(clk));
  assign prog_busy = burn_busy;
endmodule
"""

# Same burn logic, but the top declares no supply ports at all — the shape of a
# design whose boundary/pinout has not been stated yet.
_RTL_NO_SUPPLY_PORTS = """
module chip_top (
  input         clk,
  input         rst_n,
  input         prog_req,
  input  [8:0]  prog_addr,
  input  [31:0] prog_data,
  output        prog_busy
);
  reg burn_busy;
  {MASTER} u_array (.clk(clk));
  assign prog_busy = burn_busy;
endmodule
"""

_RTL_READ_ONLY = """
module chip_top (
  input        clk,
  input        rst_n,
  input  [8:0] rd_addr,
  output [31:0] rd_data,
  input        VDDC,
  input        VSS
);
  {MASTER} u_array (.clk(clk));
endmodule
"""


def _project(tmp_path, master="mem_array_512x32",
             power_pins=("VDDC", "VPROG"), rtl=_RTL_WITH_BURN_LOGIC,
             pinout=("VDDC", "VSS", "clk"), l21=None, name="proj"):
    p = tmp_path / name
    (p / "input" / "pdk_local" / "memlib").mkdir(parents=True)
    (p / "input" / "design_src" / "rtl").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "pdk_local" / "memlib" / f"{master}.lef").write_text(
        _lef(master, power_pins))
    (p / "input" / "design_src" / "rtl" / "chip_top.v").write_text(
        rtl.replace("{MASTER}", master))
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"doc_id": "L1", "fields": {
            "pinout": {n: {"type": "supply"} for n in pinout}}}))
    if l21 is not None:
        (p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
            json.dumps(l21))
    return p


# ── the LEF-side discriminator ──────────────────────────────────────────────

def test_two_power_pins_is_the_programmable_signature():
    """A memory that must be BURNED declares two supply terminals — a read
    supply and a programming supply. That declaration, in the macro's own LEF,
    is the whole discriminator: no name is consulted."""
    assert N.multi_supply_macros([_lef("m", ("VDDC", "VPROG"))]) == {
        "m": ["VDDC", "VPROG"]}


def test_single_supply_macro_is_never_considered():
    """An ordinary single-supply memory declares ONE `USE POWER`. This is what
    keeps every plain SRAM instance out of the finding set without any
    name-based exclusion list — the property the fleet sweep depends on."""
    assert N.multi_supply_macros([_lef("m", ("VDD",))]) == {}


def test_a_second_ground_is_not_a_second_supply():
    """A return path is not a supply. Counting grounds toward the threshold
    would make a two-ground single-supply macro look programmable."""
    assert N.multi_supply_macros(
        [_lef("m", ("VDD",), ground_pins=("VSS", "VSSA"))]) == {}


# ── the RTL side ────────────────────────────────────────────────────────────

def test_macro_stub_declaration_is_not_an_instantiation():
    """A macro's Verilog stub ships beside its LEF. Counting `module <master>`
    as an instantiation would make every macro in the PDK directory look like
    part of the design."""
    stub = "module mem_array (input clk); endmodule\n"
    assert N.instantiated_masters([stub], ["mem_array"]) == set()
    used = stub + "module top; mem_array u0 (.clk(c)); endmodule\n"
    assert N.instantiated_masters([used], ["mem_array"]) == {"mem_array"}


def test_program_intent_needs_more_than_the_word():
    """A lone PROGRAM-category token states no intent — a burn needs an
    address, data and a completion handshake because it is not a single-cycle
    write. Requiring the supporting signals is what keeps a read-only user of a
    programmable macro out of the finding set."""
    only_word = "module m; wire otp_present; endmodule"
    assert N.program_control_evidence([only_word])["intends_to_program"] is False

    real = ("module m; wire prog_req; wire [7:0] prog_addr; "
            "reg burn_busy; endmodule")
    assert N.program_control_evidence([real])["intends_to_program"] is True


def test_program_intent_needs_the_program_category():
    """Address plus data plus a handshake describes any bus. Without a
    PROGRAM-category signal there is no statement of intent to burn."""
    bus = ("module m; wire [7:0] addr; wire [31:0] data; wire ready; "
           "endmodule")
    assert N.program_control_evidence([bus])["intends_to_program"] is False


def test_role_tokens_match_whole_words_only():
    """`progress` must not match `prog`, and `dating` must not match `dat`.
    Substring matching here would fire the whole gate on unrelated designs."""
    assert N._name_tokens("progress_counter") == {"progress", "counter"}
    noise = "module m; wire progress_counter; wire [7:0] addr; endmodule"
    assert N.program_control_evidence([noise])["intends_to_program"] is False


# ── the boundary side ───────────────────────────────────────────────────────

def test_pinout_keyed_by_pin_name_is_harvested(tmp_path):
    """`L1.pinout` is commonly a dict KEYED by terminal name. Reading only
    `name`-style values would miss the whole package pinout and invent a gap
    the design does not have."""
    p = _project(tmp_path, pinout=("VDDC", "VPROG", "VSS"))
    names = N.boundary_entry_points(p)["names"]
    assert "VPROG" in names and "VDDC" in names


def test_per_pin_attribute_names_are_not_terminals(tmp_path):
    """Recursing into a pin's attributes would harvest `type` / `direction` as
    if they were terminals — junk that can only ever MASK a real gap."""
    p = _project(tmp_path)
    assert "type" not in N.boundary_entry_points(p)["names"]


# ── the decision, both directions ───────────────────────────────────────────

def test_missing_program_supply_is_found(tmp_path):
    """The defect: a programmable array the design means to burn, with no
    terminal that can carry the programming supply."""
    rep = N.assess(_project(tmp_path))
    assert rep["applicable"] is True
    assert [(g["master"], g["pin"]) for g in rep["gaps"]] == [
        ("mem_array_512x32", "VPROG")]


def test_adding_the_terminal_clears_it(tmp_path):
    """The other direction. A test that cannot fail is not a test; a test that
    cannot PASS after the fix does not describe the fix."""
    rep = N.assess(_project(tmp_path, pinout=("VDDC", "VPROG", "VSS")))
    assert rep["gaps"] == []
    assert all(p["status"] == "external_pin" for p in rep["pins"])


_MACRO_STUB = """
module mem_array_512x32 (clk, VDDC, VPROG, VSS);
  input clk;
  input VDDC;
  input VPROG;
  input VSS;
endmodule
"""


def test_macro_vendor_stub_does_not_manufacture_a_boundary_terminal(tmp_path):
    """#785-class circularity: a macro's OWN vendor-supplied Verilog view
    (staged beside its LEF, the same handoff tree `load_macro_lefs` reads)
    types its own VPROG pin as a port — normal for a behavioural simulation
    model. Before the fix, `input_rtl_files()` swept that file into the
    boundary-inventory scan too, so the macro's own declaration of its own
    pin was read as proof the CHIP's top level exposes a path for it: the
    missing-supply defect this whole module exists to catch went silent on
    every macro whose vendor stub types its power pins, which most do.
    MEASURED (this is the finding, not a hypothetical): before the fix this
    exact fixture returned gaps=[] and every pin external_pin; after,
    correctly, VPROG is still a gap because the CHIP's own top level (in
    input/design_src/rtl/, not input/pdk_local/) never declares it."""
    p = _project(tmp_path)
    (p / "input" / "pdk_local" / "memlib" / "mem_array_512x32.v").write_text(
        _MACRO_STUB)
    rep = N.assess(p)
    assert rep["applicable"] is True
    assert [(g["master"], g["pin"]) for g in rep["gaps"]] == [
        ("mem_array_512x32", "VPROG")]


def test_reverse_the_chip_top_level_declaring_the_pin_still_clears_it(
    tmp_path,
):
    """The other direction, so the fix above is not merely 'never trust
    pdk_local': WITH the same vendor stub present, a chip top level that
    genuinely, independently exposes VPROG at its OWN boundary must still
    clear the gap — the exclusion narrows the EVIDENCE source, it does not
    disable the finding."""
    p = _project(tmp_path, pinout=("VDDC", "VPROG", "VSS"))
    (p / "input" / "pdk_local" / "memlib" / "mem_array_512x32.v").write_text(
        _MACRO_STUB)
    rep = N.assess(p)
    assert rep["gaps"] == []
    assert all(x["status"] == "external_pin" for x in rep["pins"])


def test_read_only_use_of_a_programmable_macro_is_not_a_defect(tmp_path):
    """A design may legitimately read a pre-programmed array. It needs no
    programming supply, and must not be accused of missing one."""
    rep = N.assess(_project(tmp_path, rtl=_RTL_READ_ONLY))
    assert rep["applicable"] is False
    assert "read-only" in rep["reason"]


def test_declared_integration_gap_is_disclosure(tmp_path):
    """#309's escape hatch, from #309's field. A known, OWNED gap is
    disclosure, not silence — and sharing the field means a design that
    discloses once is disclosed to both gates."""
    p = _project(tmp_path, l21={"doc_id": "L21", "fields": {
        "hard_macro_supplies": [{"master": "mem_array_512x32",
                                 "pin": "VPROG", "integration_gap": True}]}})
    rep = N.assess(p)
    assert rep["gaps"] == []
    assert any(x["status"] == "declared_gap" for x in rep["pins"])


def test_a_ghost_disclosure_does_not_count(tmp_path):
    """`integration_gap` must be explicitly true. An entry that merely mentions
    the pin is not a disclosure — otherwise naming the pin anywhere would buy a
    pass."""
    p = _project(tmp_path, l21={"doc_id": "L21", "fields": {
        "hard_macro_supplies": [{"master": "mem_array_512x32",
                                 "pin": "VPROG"}]}})
    assert len(N.assess(p)["gaps"]) == 1


def test_no_boundary_recorded_at_all_is_inconclusive_not_a_finding(tmp_path):
    """When NOT ONE of the macro's supply or ground pins appears in the design's
    boundary inventory, the inventory records no supply terminals at all and
    cannot answer the question. Accusing here would flag every design whose
    pinout has not been extracted yet — a different defect with a different
    owner. It is reported, never swallowed."""
    p = _project(tmp_path, pinout=("clk",), rtl=_RTL_NO_SUPPLY_PORTS)
    rep = N.assess(p)
    assert rep["inconclusive"] is True and rep["applicable"] is False
    assert rep["gaps"] == []


# ── enforcement: what this landing does and does NOT stop on ────────────────

def test_track_declares_its_enforcement_intent():
    """#306: 66 of 72 gates ended up de-facto advisory because nobody declared
    an intent. The audit reads this token out of the docstring."""
    head_t = (_PROGRAMS / "phase1_expert_parse_track.py").read_text()[:4000]
    assert "ENFORCEMENT: advisory" in head_t


def test_the_phase1_runner_actually_invokes_the_track():
    """A track a runner never calls can only describe a run afterwards (#306).
    `phase1_one_shot_runner` is the runner the enforcement audit inspects."""
    src = (_PROGRAMS / "phase1_one_shot_runner.py").read_text()
    assert "phase1_expert_parse_track.py" in src


def test_the_deferred_hard_stop_is_a_recorded_fact_not_a_silence(tmp_path):
    """#312's own rule, applied to this landing's own scope decision.

    The convention has a payload and the track REPORTS the divergence, but
    nothing STOPS on it: a standalone blocking Phase-1 gate is a separate
    enforcement decision, deferred here because its blocking behaviour has
    never been observed on a real design (9/9 fleet designs assess as
    not-applicable). A deferral nobody can see is the same defect this issue
    names, so the report states it — and this test fails the moment the words
    stop matching what the code does."""
    p = _project(tmp_path)
    _run_track(p)
    rep = json.loads(_track_report(p).read_text())
    d = rep["deferred_enforcement"]
    assert d["blocking_gate_landed"] is False
    assert "nvm_program_supply" in d["subject"]
    # The finding it would have blocked on IS present and named.
    assert any(f["rule"].startswith("EXPERT_TRACK_EXPECTATION_UNMET")
               and f["about"] == "design" for f in rep["findings"])
    # ...and the deferral claim must be TRUE: no such gate exists in-tree.
    assert not (_PROGRAMS / "nvm_program_supply_check.py").exists()


# ── the second track ────────────────────────────────────────────────────────

def _run_track(project: Path, env_extra=None):
    import os
    env = dict(os.environ)
    env["VIBE_IC_DISABLE_LLM_CONFIRM"] = "1"     # force the offline path
    if env_extra:
        env.update(env_extra)
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def test_expert_track_names_each_divergence_individually(tmp_path):
    """Not a count. `2 expectations unmet` tells nobody what to do."""
    p = _project(tmp_path)
    _answer(p)
    rc, out, _ = _run_track(p)
    assert rc == 0
    rep = json.loads(_track_report(p).read_text())
    unmet = [f["rule"] for f in rep["findings"]
             if f["rule"].startswith("EXPERT_TRACK_EXPECTATION_UNMET")]
    assert any("boundary_terminal::mem_array_512x32/VPROG" in r for r in unmet)
    assert any("power_intent_rail::mem_array_512x32/VPROG" in r for r in unmet)


def test_expert_track_quotes_the_expert_lesson_it_rests_on(tmp_path):
    """A finding whose justification cannot be traced back to stated knowledge
    is an assertion. Each one carries the verbatim DB lesson."""
    p = _project(tmp_path)
    _run_track(p)
    rep = json.loads(_track_report(p).read_text())
    srcs = [f.get("expert_source") for f in rep["findings"]
            if f.get("expert_source")]
    assert srcs, "no finding carried its expert source"
    assert all(s["db_class"] == "nvm-fuse-array" and s["lesson"]
               for s in srcs)


def test_an_unread_ai_half_is_a_named_finding_not_an_absence(tmp_path):
    """The failure mode this whole task exists to prevent: a second track that
    quietly does nothing and reads as 'nothing to report'.

    The STATUS moved from SKIPPED-CONDITION to HANDOFF_EMITTED when the AI half
    stopped being vetoed by the in-process-SDK probe (a backend nothing on this
    path uses — see `test_issue312_ai_subtrack_convergence`). HANDOFF_EMITTED
    is the accurate statement: the pack is written and the subagent has not
    answered yet, which is actionable, where "no LLM on this host" was not.
    The INVARIANT under test is unchanged and is the one that matters — a run
    whose AI half did not read says so, by name, in the findings, out loud."""
    p = _project(tmp_path)
    rc, out, _ = _run_track(p)
    rep = json.loads(_track_report(p).read_text())
    assert rep["ai_subtrack"]["status"] == "HANDOFF_EMITTED"
    assert rep["verdict"] == "INCOMPLETE" and rc == 1
    assert any(f["rule"] == "EXPERT_TRACK_AI_SUBTRACK_SKIPPED"
               for f in rep["findings"])
    assert "EXPERT_TRACK_AI_SUBTRACK_SKIPPED" in out, "and it must be PRINTED"


def test_expert_track_findings_do_not_block(tmp_path):
    """ADVISORY, proven by the exit code of a run that HAS findings AND a
    consumed expert answer. Before #1973 the missing answer in this fixture
    accidentally mixed mandatory execution with advisory finding policy."""
    p = _project(tmp_path)
    _answer(p)
    rc, out, _ = _run_track(p)
    assert rc == 0
    assert "FINDINGS" in out


def test_expert_track_report_is_mandatory_output(tmp_path):
    """Findings are advisory; RUNNING is not. The report is the artefact the
    runner refuses to proceed without."""
    p = _project(tmp_path)
    _run_track(p)
    assert _track_report(p).is_file()


def test_expert_track_records_the_unwritten_sidecar_as_a_visible_fact(tmp_path):
    """The missing `ai_deep_review_patches.json` writer is what exposed the
    missing track. It stays a recorded observation — and this track must NOT be
    its writer: the gates that read it merge it into the haystack they then
    measure, so a track writing there would score itself."""
    p = _project(tmp_path)
    _run_track(p)
    rep = json.loads(_track_report(p).read_text())
    assert rep["track_health"]["ai_patch_sidecar_present"] is False
    assert not (p / "phase1" / "ai_deep_review_patches.json").exists(), \
        "the expert track must never write the sidecar it would be scored by"


def test_expert_track_clean_when_the_design_is_correct(tmp_path):
    p = _project(tmp_path, pinout=("VDDC", "VPROG", "VSS"),
                 l21={"doc_id": "L21", "fields": {
                     "power_rails": ["VDDC", "VPROG"]}})
    _answer(p)
    rc, _, _ = _run_track(p)
    rep = json.loads(_track_report(p).read_text())
    unmet = [f for f in rep["findings"]
             if f["rule"].startswith("EXPERT_TRACK_EXPECTATION_UNMET")]
    assert unmet == []
    assert rc == 0 and rep["verdict"] == "PASS"


# ── the knowledge payload ───────────────────────────────────────────────────

def test_the_convention_is_in_the_expert_db():
    lesson = T.expert_db_lesson("nvm-fuse-array")
    assert lesson, "the expert layer carries no such knowledge"
    low = lesson.lower()
    for token in ("outside", "above the core", "terminal", "read"):
        assert token in low, f"lesson does not state {token!r}"


def test_the_expert_db_still_passes_its_ship_gate():
    """Blindness, oracle-source ban, advisory boundary, related-link integrity.
    A new entry that breaks any of them must not ship."""
    db = _PROGRAMS.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"
    rep = DBC.check(db)
    assert rep["pass"], rep["findings"]


def test_the_lesson_names_no_part_no_process_no_ip_model():
    """The convention is general. Its evidence came from confidential parts;
    the knowledge must carry none of that across."""
    lesson = T.expert_db_lesson("nvm-fuse-array") or ""
    import re
    # a part-number / SKU shape: letters immediately followed by >=3 digits
    assert not re.search(r"\b[A-Za-z]{2,}\d{3,}\b", lesson)
    # a process-node shape
    assert not re.search(r"\b\d{1,3}\s?nm\b", lesson, re.I)
    assert not re.search(r"\b\d{2,3}\s?[uµ]m\b", lesson, re.I)


# ── the fleet ───────────────────────────────────────────────────────────────

_FLEET = _PROGRAMS.parents[3] / "benchmark-data" / "ic"


@pytest.mark.skipif(not _FLEET.is_dir(), reason="fleet corpus not present")
@pytest.mark.parametrize("design", sorted(
    p.name for p in _FLEET.iterdir() if p.is_dir()) if _FLEET.is_dir() else [])
def test_no_false_positive_on_any_fleet_design(design):
    """Zero false positives across every design on the fleet. Most have no
    programmable NVM at all and must skip cleanly — including the one that DOES
    carry a real memory macro, which skips because that macro declares a single
    `USE POWER`."""
    rep = N.assess(_FLEET / design)
    assert rep["gaps"] == [], f"{design}: {rep['gaps']}"
    assert rep["applicable"] is False
    assert rep["inconclusive"] is False


def test_a_track_finding_and_a_design_finding_are_different_things(tmp_path):
    """A run whose only entry is "my AI half was unavailable" found NOTHING in
    the design. Counting it as a design finding would report a track that found
    something — the same conflation of two different zeros that this whole
    second track exists to stop, one level in."""
    import phase1_expert_track_evidence_check as E

    clean = _project(tmp_path, pinout=("VDDC", "VPROG", "VSS"),
                     l21={"doc_id": "L21",
                          "fields": {"power_rails": ["VDDC", "VPROG"]}})
    _run_track(clean)
    rep = json.loads(_track_report(clean).read_text())
    assert [f["rule"] for f in rep["findings"]] == [
        "EXPERT_TRACK_AI_SUBTRACK_SKIPPED"]
    assert all(f["about"] == "track" for f in rep["findings"])
    # The evidence check must read this as "ran, found nothing", not "ran,
    # found one thing" — and must still carry WHY coverage was partial.
    ev = E.assess(clean, _PROGRAMS)
    assert ev["state"] == "INCOMPLETE" and ev["patch_count"] == 0
    # HANDOFF_EMITTED, not SKIPPED-CONDITION: the AI half is no longer vetoed
    # by an unrelated backend probe, so "it has not answered yet" is the true
    # statement. What this assertion is really pinning is unchanged — the
    # evidence check must still carry WHY coverage was partial.
    assert ev["ai_subtrack"] == "HANDOFF_EMITTED"

    broken = _project(tmp_path, name="broken")
    _answer(broken)
    _run_track(broken)
    ev2 = E.assess(broken, _PROGRAMS)
    assert ev2["state"] == "RAN" and ev2["patch_count"] > 0


# ── the AI sub-track's other two branches ───────────────────────────────────
#
# This host has no LLM backend, so SKIPPED-CONDITION is the path every run
# above actually takes. Shipping the other two branches untested would leave
# the hand-off — the part that makes this a dual TRACK rather than one program
# with a disclaimer — unexercised. `ic_expert_backup_pack.assemble` performs no
# network call (it retrieves, renders two independent digests, and writes a
# descriptor), so both branches run deterministically offline once the backend
# probe is answered.

def _force_backend(monkeypatch, available: bool):
    import llm_semantic_confirm as _llm
    monkeypatch.setattr(_llm, "backend_available", lambda: available)


def test_ai_subtrack_emits_a_handoff_naming_the_subagent(tmp_path, monkeypatch):
    _force_backend(monkeypatch, True)
    p = _project(tmp_path)
    out = tmp_path / "pack"
    st = T.ai_subtrack(p, T.input_text(p), out)
    assert st["status"] == "HANDOFF_EMITTED"

    descriptor = json.loads((out / "ic_expert_agent_handoff.json").read_text())
    assert descriptor["subagent_type"] == "vibe-ic:ic-expert-agent"
    # The Phase-1 parse track asks for L-doc EXPECTATIONS, not an RTL body —
    # the one thing that had to change in the assembler to reuse it here.
    assert descriptor["output_target"] == "l_doc_expectations.json"
    assert descriptor["prompt_is_input_only"] is True
    # Two INDEPENDENT authors, which is the measured reason this assembler
    # exists at all (folded: 38->31; independent: 51).
    assert set(descriptor["dual_track"]) >= {
        "track1_general_blind", "track2_db_informed", "converge"}


def test_ai_subtrack_consumes_a_prior_agent_answer(tmp_path, monkeypatch):
    _force_backend(monkeypatch, True)
    p = _project(tmp_path)
    out = tmp_path / "pack"
    out.mkdir()
    (out / "l_doc_expectations.json").write_text(json.dumps({
        "expectations": [{"id": "ai::x", "layer": "L21_POWER_INTENT"}]}))
    st = T.ai_subtrack(p, T.input_text(p), out)
    assert st["status"] == "CONSUMED"
    assert len(st["expectations"]) == 1


def test_ai_subtrack_treats_an_unreadable_answer_as_an_error(tmp_path,
                                                             monkeypatch):
    """Not as an empty answer. Unreadable evidence is not evidence — the same
    rule the sidecar and the track report are held to."""
    _force_backend(monkeypatch, True)
    p = _project(tmp_path)
    out = tmp_path / "pack"
    out.mkdir()
    (out / "l_doc_expectations.json").write_text("{not json")
    st = T.ai_subtrack(p, T.input_text(p), out)
    assert st["status"] == "ERROR" and "does not parse" in st["reason"]


def test_assembler_default_target_is_unchanged_for_its_original_caller():
    """The RTL-authoring hand-off keeps its exact prior shape: the parse track
    reuses the assembler, it does not repurpose it."""
    import inspect
    import ic_expert_backup_pack as P
    assert inspect.signature(P.assemble).parameters[
        "output_target"].default == "rtl.sv"


def test_a_stale_report_cannot_stand_in_for_a_run(tmp_path):
    """The runner clears the previous report before invoking the track, so
    "the report exists" can only mean THIS run wrote it. Without that, a track
    that died would still look like a track that ran — the exact substitution
    #312 is about."""
    import unittest.mock as mock

    import phase1_one_shot_runner as R
    p = _project(tmp_path)
    stale = _pl.report_path(p, "phase1/expert_parse_track.json")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(json.dumps({"verdict": "PASS", "findings": [],
                                 "stale": True}))

    # Point the runner at a track program that exits without writing anything.
    broken = tmp_path / "programs"
    broken.mkdir()
    (broken / R._EXPERT_TRACK).write_text("import sys; sys.exit(0)\n")
    with mock.patch.object(R, "PROGRAMS_DIR", broken):
        assert R._run_expert_track(p) == 1, \
            "a run that wrote no report must not inherit the previous one"
    assert not stale.exists()


def test_a_crashed_track_does_not_read_as_a_pass(tmp_path):
    """A track whose failure mode is "return 0" is not a track. 0 and 2 are its
    verdicts; anything else means it never reached one, and an unreached
    verdict is not a clean one."""
    import unittest.mock as mock

    import phase1_one_shot_runner as R
    p = _project(tmp_path)
    broken = tmp_path / "programs"
    broken.mkdir()
    (broken / R._EXPERT_TRACK).write_text(
        "import sys; sys.stderr.write('boom\\n'); sys.exit(3)\n")
    with mock.patch.object(R, "PROGRAMS_DIR", broken):
        assert R._run_expert_track(p) == 1

    # And a track program that is not there at all is not a silent skip.
    (broken / R._EXPERT_TRACK).unlink()
    with mock.patch.object(R, "PROGRAMS_DIR", broken):
        assert R._run_expert_track(p) == 1, \
            "a missing second track must not pass as 'nothing to run'"
