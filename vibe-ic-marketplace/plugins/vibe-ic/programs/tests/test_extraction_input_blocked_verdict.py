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

Public behaviour only: everything below drives `step_lvs`, `_aggregate_verdict`
and the Step-31 gate through their real entry points and reads the artifacts
and statuses they publish.

chip-AGNOSTIC: synthetic generic tech/LEF/netgen text. No PDK, foundry, layer
or design literal is used as detection logic anywhere in this file.
"""
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as runner  # noqa: E402
import extraction_input_capability_check as eicap  # noqa: E402
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


def _pdk(tech_lef="/t.tlef"):
    return runner.PdkConfig(
        name="generic_pdk", liberty="/x.lib", tech_lef=tech_lef,
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\n"
        "NETS 1 ;\n- n0 ( i0 A ) ( i1 Z ) + ROUTED routing_a ;\nEND NETS\n"
        "END DESIGN\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    return tmp_path


def _fake_docker(tech_text, netgen_transcript,
                 spice_body=".subckt chip_top a b\n.ends\n"):
    """Container stub: tools + tech files present; `cat` serves the rc and the
    tech file; magic writes an extracted netlist; netgen writes lvs.rpt."""
    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if cmd.startswith("cat "):
            if ".magicrc" in cmd:
                return (0, MAGICRC, "")
            if ".tech" in cmd:
                return (0, tech_text, "")
            return (1, "", "no such file")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            m = re.search(r"SPICE_OUT=(\S+)", cmd)
            out = Path(m.group(1))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(spice_body)
            (out.parent / "ext2spice.log").write_text(
                "MAGIC_EXT2SPICE_DONE\n")
            return (0, "MAGIC_EXT2SPICE_DONE\n", "")
        if "netgen" in cmd:
            m = re.search(r"(\S+/lvs\.rpt)", cmd)
            if m:
                rpt = Path(m.group(1))
                rpt.parent.mkdir(parents=True, exist_ok=True)
                rpt.write_text(netgen_transcript)
            return (0, netgen_transcript, "")
        return (0, "", "")
    return fake


def _run(tmp_path, monkeypatch, tech_text, transcript, tech_lef="/t.tlef"):
    p = _proj(tmp_path)
    monkeypatch.setattr(runner, "_docker_exec",
                        _fake_docker(tech_text, transcript))
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    return p, runner.step_lvs(p, "chip_top", _pdk(tech_lef), "x")


def _verdict(project):
    return json.loads(
        (project / "reports" / "phase3" / "lvs_verdict.json").read_text())


# ==========================================================================
# FIXTURE 1 — stub tech file -> BLOCKED
# ==========================================================================
def test_stub_tech_file_is_blocked_not_fail_not_pass(tmp_path, monkeypatch):
    """A stub tech file must yield BLOCKED, naming the file and what it lacks.

    The transcript handed to netgen here is a CLEAN MATCH. It must never be
    reached: the precondition fires before extraction, so a stub tech file
    cannot borrow a clean verdict from a compare that never legitimately ran.
    """
    p, r = _run(tmp_path, monkeypatch, STUB_TECH, MATCH_TRANSCRIPT)

    assert r.status == "BLOCKED", (r.status, r.detail)
    assert r.status != "PASS"
    assert r.status != "FAIL"
    assert r.extras.get("finding") == "LVS_INPUT_TECH_INCAPABLE"

    # names the offending FILE
    assert "generic.tech" in r.detail
    assert "generic.tech" in r.extras.get("tech_file", "")

    # names the missing CAPABILITY (not just "something is wrong")
    missing = r.extras.get("missing_capabilities") or []
    assert any("extraction rules" in m for m in missing), missing
    assert any("connectivity" in m for m in missing), missing
    assert any("style" in m for m in missing), missing

    # says cannot-verify, in words that cannot be read as either verdict
    assert "BLOCKED" in r.detail
    assert "NOT a pass" in r.detail and "NOT a design failure" in r.detail

    v = _verdict(p)
    assert v["status"] == "BLOCKED"
    assert v["result"] == "BLOCKED"
    assert v["finding"] == "LVS_INPUT_TECH_INCAPABLE"
    assert "generic.tech" in v["tech_file"]
    assert v["capability"]["usable"] is False
    assert "styles" in v["capability"]["empty_sections"]


def test_stub_tech_that_actually_extracts_nothing_is_blocked_not_fail(
        tmp_path, monkeypatch):
    """The FIELD SHAPE, reproduced: a stub tech from which Magic emits nothing.

    This is what the flow actually did before the fix. Magic exits rc=0 having
    written no netlist, and the run landed on:

        LVS_EXTRACTION_NO_NETLIST -> FAIL
        "Magic ext2spice produced no extracted netlist (rc=0); see
         phase3/stage3/extracted/ext2spice.log"

    That is a FAIL — the same terminal class as a genuine mismatch — and it
    names the log, never the tech file that made extraction impossible. The
    cause was recoverable only by opening the tech file by hand.

    After the fix the precondition fires FIRST, so the verdict is BLOCKED and
    it names the tech file and the capability it lacks.
    """
    p = _proj(tmp_path)

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("command -v") or cmd.startswith("test -f"):
            return (0, "", "")
        if cmd.startswith("cat "):
            if ".magicrc" in cmd:
                return (0, MAGICRC, "")
            if ".tech" in cmd:
                return (0, STUB_TECH, "")
            return (1, "", "no such file")
        if "magic" in cmd and "SPICE_OUT=" in cmd:
            # Magic cannot resolve the layers: it exits 0 having written
            # NOTHING. No SPICE_OUT file is created.
            m = re.search(r"SPICE_OUT=(\S+)", cmd)
            ext_dir = Path(m.group(1)).parent
            ext_dir.mkdir(parents=True, exist_ok=True)
            (ext_dir / "ext2spice.log").write_text(
                "Magic 8.3\nno such layer\nCouldn't find type\n")
            return (0, "no such layer\n", "")
        return (0, "", "")

    monkeypatch.setattr(runner, "_docker_exec", fake)
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")

    assert r.status == "BLOCKED", (r.status, r.detail)
    assert r.extras.get("finding") == "LVS_INPUT_TECH_INCAPABLE"
    assert r.extras.get("finding") != "LVS_EXTRACTION_NO_NETLIST"
    # the verdict names the CAUSE (the tech file), not just the symptom (a log)
    assert "generic.tech" in r.detail
    assert _verdict(p)["status"] == "BLOCKED"


def test_blocked_verdict_reports_which_sections_were_empty_vs_absent(
        tmp_path, monkeypatch):
    """Triage needs the distinction: declared-but-empty vs never-declared."""
    p, r = _run(tmp_path, monkeypatch, STUB_TECH, MATCH_TRANSCRIPT)
    cap = _verdict(p)["capability"]
    assert cap["empty_sections"] == ["styles"]
    assert set(cap["absent_sections"]) >= {"connect", "extract"}


# ==========================================================================
# FIXTURE 2 — complete tech + matching design -> PASS, UNCHANGED
# ==========================================================================
def test_complete_tech_with_matching_design_still_passes(tmp_path,
                                                         monkeypatch):
    """The load-bearing negative: a checker that cannot return clean is an
    alarm, not a checker. A complete tech file must not be blocked."""
    p, r = _run(tmp_path, monkeypatch, COMPLETE_TECH, MATCH_TRANSCRIPT)
    assert r.status == "PASS", (r.status, r.detail)
    assert r.status != "BLOCKED"
    assert r.extras.get("finding") != "LVS_INPUT_TECH_INCAPABLE"


def test_complete_tech_passes_with_real_tech_lef_layer_crosscheck(
        tmp_path, monkeypatch):
    """With the design's OWN layers supplied, a complete tech still passes.

    The layer set is read from the tech LEF (what THIS design is routed on),
    not from any fixed list — and it must not become a new way to block.
    """
    lef = tmp_path / "gen.tlef"
    lef.write_text(TECH_LEF)
    p, r = _run(tmp_path, monkeypatch, COMPLETE_TECH, MATCH_TRANSCRIPT,
                tech_lef=str(lef))
    assert r.status == "PASS", (r.status, r.detail)


def test_unreadable_tech_does_not_block(tmp_path, monkeypatch):
    """Capability UNKNOWN must never block — only positive evidence does.

    The tech file cannot be read here (the `cat` fails). The run must proceed
    exactly as it did before this check existed.
    """
    p = _proj(tmp_path)

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("cat "):
            return (1, "", "no such file")
        return _fake_docker(COMPLETE_TECH, MATCH_TRANSCRIPT)(
            container, cmd, timeout)

    monkeypatch.setattr(runner, "_docker_exec", fake)
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "PASS", (r.status, r.detail)


# ==========================================================================
# FIXTURE 3 — complete tech + genuine mismatch -> STILL FAIL
# ==========================================================================
def test_complete_tech_with_real_mismatch_still_fails(tmp_path, monkeypatch):
    """The whole risk of this change: weakening a real failure detector.

    A genuine netgen mismatch on a usable tech file must stay FAIL and must
    NOT be relabelled BLOCKED — "we could not verify" would excuse a defect
    the flow actually did detect.
    """
    p, r = _run(tmp_path, monkeypatch, COMPLETE_TECH, MISMATCH_TRANSCRIPT)
    assert r.status == "FAIL", (r.status, r.detail)
    assert r.status != "BLOCKED"
    assert r.extras.get("finding") != "LVS_INPUT_TECH_INCAPABLE"
    v = _verdict(p)
    assert v["status"] != "BLOCKED"


# ==========================================================================
# 4 — BLOCKED IS NEVER A PASS DOWNSTREAM
# ==========================================================================
def test_blocked_step_never_aggregates_to_a_green_run():
    """`_aggregate_verdict` returns PASS for any status it does not
    enumerate. A BLOCKED step must never reach that catch-all."""
    plan = [runner.StepResult("synth", "PASS"),
            runner.StepResult("lvs", "BLOCKED")]
    verdict = runner._aggregate_verdict(plan)
    assert verdict != "PASS"
    assert verdict != "PASS_WITH_WAIVERS"
    assert "PASS" not in verdict


def test_blocked_does_not_mask_other_failures():
    plan = [runner.StepResult("drc", "FAIL"),
            runner.StepResult("lvs", "BLOCKED")]
    assert runner._aggregate_verdict(plan) == "FAIL"


def test_all_clean_run_still_aggregates_to_pass():
    """Control for the aggregate change — a clean plan is still PASS."""
    plan = [runner.StepResult("synth", "PASS"),
            runner.StepResult("lvs", "PASS")]
    assert runner._aggregate_verdict(plan) == "PASS"


def test_blocked_is_in_the_verdict_tier_vocabulary():
    assert "BLOCKED" in runner._VERDICT_TIERS


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
def test_requirements_are_derived_from_the_recipe_not_a_fixed_list():
    """Different recipes need different sections — that is the derivation.

    A recipe that never streams GDS must not require CIF/GDS output rules;
    one that does, must. A fixed "every tech file needs these sections" list
    could not tell these apart.
    """
    ext2spice = {c.name for c in
                 eicap.required_capabilities(eicap.DEFAULT_EXT2SPICE_COMMANDS)}
    gds = {c.name for c in eicap.required_capabilities("gds write out.gds")}

    assert "extraction rules" in ext2spice
    assert "CIF/GDS output rules" not in ext2spice
    assert "CIF/GDS output rules" in gds
    assert "extraction rules" not in gds


def test_disabled_drc_requires_no_drc_rules():
    assert eicap.required_capabilities("drc off") == []
    assert any(c.name == "DRC rules"
               for c in eicap.required_capabilities("drc check"))


def test_tech_lacking_only_an_unneeded_section_is_not_blocked():
    """A complete-for-extraction tech with no `cifoutput` is USABLE for the
    ext2spice recipe. Blocking it would be a false BLOCKED."""
    rep = eicap.check_magic_tech(COMPLETE_TECH,
                                 eicap.DEFAULT_EXT2SPICE_COMMANDS)
    assert rep.usable is True
    assert rep.inconclusive is False
    assert "cifoutput" not in rep.sections_found
    # ...but the same file cannot support a GDS-streaming recipe.
    rep_gds = eicap.check_magic_tech(COMPLETE_TECH, "gds write out.gds")
    assert rep_gds.usable is False


def test_design_layers_come_from_the_lef_not_a_hardcoded_list():
    """Only ROUTING layers, read from whatever LEF the design uses."""
    layers = eicap.lef_layers(TECH_LEF)
    assert layers == ["routing_a", "routing_b"]  # the CUT layer is excluded


def test_unrecognised_file_is_inconclusive_never_blocked():
    rep = eicap.check_magic_tech("#!/usr/bin/env tclsh\nputs hello\n",
                                 eicap.DEFAULT_EXT2SPICE_COMMANDS)
    assert rep.inconclusive is True
    assert rep.usable is True


def test_comment_only_section_counts_as_empty():
    """A stub's 'TODO' comment is not content."""
    secs = eicap.parse_tech_sections(STUB_TECH)
    assert secs["styles"].is_empty is True
    assert secs["types"].is_empty is False


def test_nested_style_blocks_do_not_end_the_parent_section():
    """`cifoutput`/`extract` carry nested `style ... end`; a naive parser
    would end the section at the first inner `end` and under-report."""
    tech = COMPLETE_TECH + """\
cifoutput
    style generic
    scalefactor 10
    layer RA routing_a
    end
end
"""
    secs = eicap.parse_tech_sections(tech)
    assert "cifoutput" in secs
    assert secs["cifoutput"].is_empty is False
    # the section AFTER a nested block is still parsed
    assert "extract" in secs and secs["extract"].is_empty is False


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


def test_technology_split_across_include_files_is_usable():
    """`extract` in an included sibling must count as present."""
    def resolver(name):
        return SPLIT_EXTRACT_TECH if name == "generic-extract" else None

    rep = eicap.check_magic_tech(SPLIT_MAIN_TECH,
                                 eicap.DEFAULT_EXT2SPICE_COMMANDS,
                                 resolver=resolver)
    assert rep.usable is True, rep.reason
    assert rep.inconclusive is False
    assert "extract" in rep.sections_found


def test_split_technology_without_resolver_is_inconclusive_not_blocked():
    """An include we cannot read must SUPPRESS a would-be BLOCKED.

    The capability that looks missing may be sitting in the file we could not
    open. Blocking on that would condemn a complete technology.
    """
    rep = eicap.check_magic_tech(SPLIT_MAIN_TECH,
                                 eicap.DEFAULT_EXT2SPICE_COMMANDS)
    assert rep.usable is True
    assert rep.inconclusive is True
    assert "could not be read" in rep.note


def test_include_resolution_is_depth_limited_and_cycle_safe():
    """A self-including tech must terminate, not recurse forever."""
    rep = eicap.check_magic_tech(
        SPLIT_MAIN_TECH + "include loop\n",
        eicap.DEFAULT_EXT2SPICE_COMMANDS,
        resolver=lambda n: ("include loop\n" if n == "loop"
                            else SPLIT_EXTRACT_TECH))
    assert rep.usable is True


def test_stub_with_unreadable_include_is_not_blocked_by_the_runner(
        tmp_path, monkeypatch):
    """End-to-end: a stub whose includes cannot be read must NOT be BLOCKED."""
    p = _proj(tmp_path)

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("cat ") and ".magicrc" in cmd:
            return (0, MAGICRC, "")
        if cmd.startswith("cat ") and cmd.rstrip().endswith("generic.tech"):
            return (0, STUB_TECH + "include generic-extract\n", "")
        if cmd.startswith("cat "):
            return (1, "", "no such file")   # the include is unreadable
        return _fake_docker(STUB_TECH, MATCH_TRANSCRIPT)(container, cmd,
                                                         timeout)

    monkeypatch.setattr(runner, "_docker_exec", fake)
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status != "BLOCKED", (r.status, r.detail)


def test_magicrc_tech_path_resolution():
    assert eicap.tech_path_from_magicrc_text(
        "tech load generic.tech\n") == "generic.tech"
    # an unexpanded Tcl variable is never guessed at
    assert eicap.tech_path_from_magicrc_text(
        "tech load $env(PDK)/x.tech\n") is None
    assert eicap.tech_path_from_magicrc_text("puts hi\n") is None


@pytest.mark.parametrize("status", ["PASS", "FAIL", "INCOMPLETE", "WARN"])
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

def _tech(*, lef=True, device=True, substrate=True, styles=True,
          types_block="    metalplane routing_a,ra\n    metalplane routing_b,rb\n"):
    """A structurally COMPLETE generic tech, with one capability knocked out.

    Built by removal from a known-good file so each fixture differs from the
    passing control in exactly ONE respect — otherwise a fixture can be caught
    for a reason other than the one it was written to prove.
    """
    out = ["tech\n    format 32\n    generic\nend\n",
           "planes\n    metalplane,mp\nend\n",
           f"types\n{types_block}end\n"]
    out.append("styles\n" + ("    styletype generic\n    routing_a 1\n"
                             if styles else
                             "    # TODO: not authored yet\n") + "end\n")
    out.append("connect\n    routing_a routing_a\nend\n")
    if lef:
        out.append("lef\n    routing routing_a routing_a RA\n"
                   "    routing routing_b routing_b RB\nend\n")
    ext = ["extract\n    style generic\n    lambda 1.0\n"
           "    resist routing_a 100\n"]
    if substrate:
        ext.append("    substrate space/w well generic_sub\n")
    if device:
        ext.append("    device mosfet gate_a routing_a routing_b generic_dev\n")
    ext.append("end\n")
    out.append("".join(ext))
    return "\n".join(out)


COMPLETE_GENERIC_TECH = _tech()


def _check(tech, layers=None):
    return eicap.check_magic_tech(tech, eicap.DEFAULT_EXT2SPICE_COMMANDS,
                                  design_layers=layers)


# -- GAP A: populated `styles`, but no `lef` section ------------------------
def test_populated_styles_but_no_lef_section_is_blocked():
    """The gap that produced the field transcript.

    #212 required `styles` for `lef read` and stopped there, so a tech file
    with a fully populated `styles` section and NO `lef` section reported
    USABLE — and the run then failed with Magic unable to parse the layer
    names the LEF actually carries, because the `lef` section IS the map from
    LEF-namespace names onto Magic types.
    """
    rep = _check(_tech(lef=False))
    assert rep.usable is False, rep.note
    assert rep.inconclusive is False
    # It must name the missing thing, not merely refuse.
    assert "LEF layer map" in rep.missing_capability_names
    assert "lef" in rep.reason
    # and it must be caught for THAT reason alone — styles is fine here
    assert "layer styles" not in rep.missing_capability_names


def test_the_styles_gap_212_did_catch_still_blocks():
    """The one gap #212 caught must keep being caught (no regression)."""
    rep = _check(_tech(styles=False))
    assert rep.usable is False
    assert "layer styles" in rep.missing_capability_names


# -- GAP B: `extract` present, but no `device` ------------------------------
def test_extract_without_device_is_blocked_although_section_is_non_empty():
    """`extract` non-empty is an ADJACENT measurement, not the answer.

    An `extract` section carrying only parasitic rules parses perfectly and
    satisfies "the section exists and is non-empty" — while emitting ZERO
    devices, so the netlist has nothing to compare and LVS is vacuous.
    """
    tech = _tech(device=False)
    secs = eicap.parse_tech_sections(tech)
    # the premise: the section really is present and non-empty
    assert "extract" in secs and secs["extract"].is_empty is False
    rep = _check(tech)
    assert rep.usable is False, rep.note
    assert "device extraction rules" in rep.missing_capability_names
    assert "device" in rep.reason


def test_missing_substrate_is_reported_but_never_blocks():
    """Fail-safe direction held: substrate absence DEGRADES, it does not stop.

    Devices are still emitted without a `substrate` statement, so asserting
    incapability would be a false BLOCKED. It must still be visible — a defect
    that is not terminal is not thereby uninteresting.
    """
    rep = _check(_tech(substrate=False))
    assert rep.usable is True, rep.reason
    assert rep.inconclusive is False
    assert "substrate declaration" in [a["capability"] for a in rep.advisories]
    assert "substrate" in rep.note


# -- GAP C: a design layer the tech file does not define --------------------
def test_design_layer_crosscheck_can_block_on_its_own():
    """The cross-check must be able to be the SOLE reason for BLOCKED.

    In #212 it only appended text to an already-failing reason, so a tech file
    that was structurally complete but defined NONE of the design's layers
    returned USABLE — the cross-check could never catch anything by itself.
    """
    # structurally complete: nothing else can be the cause
    assert _check(COMPLETE_GENERIC_TECH).usable is True
    rep = _check(COMPLETE_GENERIC_TECH,
                 layers=["foreign_x", "foreign_y", "foreign_z"])
    assert rep.usable is False, rep.note
    assert rep.inconclusive is False
    assert "design layer coverage" in rep.missing_capability_names
    assert rep.design_layers_checked == 3
    assert rep.design_layers_undefined == ["foreign_x", "foreign_y",
                                           "foreign_z"]
    # names what is missing
    assert "foreign_x" in rep.reason


def test_partial_layer_coverage_stays_advisory_and_does_not_block():
    """Only TOTAL non-coverage is positive evidence.

    A LEF legitimately carries layers this flow never routes on, so blocking
    on partial coverage would be a false BLOCKED.
    """
    rep = _check(COMPLETE_GENERIC_TECH, layers=["routing_a", "foreign_y"])
    assert rep.usable is True, rep.reason
    assert rep.design_layers_undefined == ["foreign_y"]
    assert "not found" in rep.note


def test_lef_section_names_resolve_design_layers():
    """A LEF name defined ONLY in the `lef` section must count as defined.

    Measured on the open-source PDKs available during review: LEF-namespace
    names appear in the `lef` section and NOT in `types`. Resolving design
    layers against `types` alone is the wrong name space, and would have made
    the now-blocking cross-check condemn working technologies.
    """
    secs = eicap.parse_tech_sections(COMPLETE_GENERIC_TECH)
    assert "ra" in eicap.defined_layer_names(secs)   # via the lef section
    # a design using only the LEF-namespace spellings is fully covered
    rep = _check(COMPLETE_GENERIC_TECH, layers=["RA", "RB"])
    assert rep.usable is True, rep.reason
    assert rep.design_layers_undefined == []


# -- GAP D: `include` that is indented, or inside a section -----------------
def test_indented_include_is_followed():
    """#212 matched `include` only at column 0 and only BETWEEN sections.

    An indented include parsed as a bogus section named "include", silently
    dropping every capability the included file supplies — which, for a
    technology composed via include, manufactures a false BLOCKED.

    The included file must supply a capability the main file does NOT have,
    otherwise the test passes whether or not the include was followed — which
    is the same adjacent-measurement error this whole change is about. Here
    `extract` (with its devices) lives ONLY behind the indented include, so a
    parser that drops it necessarily reaches the wrong verdict.
    """
    main = _tech(device=False).replace(
        "extract\n    style generic\n    lambda 1.0\n"
        "    resist routing_a 100\n"
        "    substrate space/w well generic_sub\nend\n",
        "   include generic-extract\n")
    # premise: `extract` exists ONLY behind the include, so a parser that
    # drops the include cannot reach a usable verdict by any other route
    assert "extract" not in eicap.parse_tech_sections(main)
    body = ("extract\n    style generic\n    lambda 1.0\n"
            "    resist routing_a 100\n"
            "    substrate space/w well generic_sub\n"
            "    device mosfet gate_a routing_a routing_b generic_dev\nend\n")
    secs = eicap.parse_tech_sections(main, resolver=lambda n: body)
    assert "include" not in secs, "indented include parsed as a section"
    assert "extract" in secs, "indented include was not followed"
    rep = eicap.check_magic_tech(main, eicap.DEFAULT_EXT2SPICE_COMMANDS,
                                 resolver=lambda n: body)
    assert rep.usable is True, rep.reason
    assert rep.inconclusive is False


def test_include_inside_a_section_splices_that_sections_body():
    """Magic's `include` is a textual splice, so it is legal INSIDE a section.

    A PDK that factors a long `extract` body out to a sibling file must not be
    read as having an empty/incomplete `extract`.
    """
    main = _tech(device=False).replace(
        "    resist routing_a 100\n",
        "    resist routing_a 100\n    include generic-devices\n")
    devices = "    device mosfet gate_a routing_a routing_b generic_dev\n"
    rep = eicap.check_magic_tech(main, eicap.DEFAULT_EXT2SPICE_COMMANDS,
                                 resolver=lambda n: devices)
    assert rep.usable is True, rep.reason
    secs = eicap.parse_tech_sections(main, resolver=lambda n: devices)
    assert secs["extract"].has_statement("device")


def test_unresolvable_indented_include_suppresses_a_would_be_blocked():
    """Fail-safe unchanged for the new include positions."""
    main = _tech(device=False).replace(
        "    resist routing_a 100\n",
        "    resist routing_a 100\n    include generic-devices\n")
    rep = eicap.check_magic_tech(main, eicap.DEFAULT_EXT2SPICE_COMMANDS,
                                 resolver=lambda n: None)
    assert rep.usable is True
    assert rep.inconclusive is True


# -- GAP E: a `tech load` path the check cannot resolve ---------------------
def test_tcl_variable_tech_load_is_a_finding_not_a_silent_pass(tmp_path,
                                                               monkeypatch):
    """A magicrc loading its tech through a Tcl variable disabled the check.

    #212 returned a bare None for BOTH "no tech load" and "unexpandable Tcl",
    and the runner then skipped the pre-flight entirely, with no error and no
    artifact. Downstream, that silence is indistinguishable from "the check
    ran and found nothing wrong" — the pre-flight was off and nothing said so.
    """
    raw, why, verbatim = eicap.tech_load_directive(
        "tech load $env(PDK_ROOT)/x.tech\n")
    assert raw is None                       # still never guessed
    assert why == eicap.TECH_LOAD_UNEXPANDED  # ... but now NAMED
    assert "$env(PDK_ROOT)" in verbatim

    assert eicap.tech_load_directive("puts hi\n")[1] == eicap.TECH_LOAD_NONE
    assert eicap.tech_load_directive(
        "tech load generic.tech\n")[1] == eicap.TECH_LOAD_OK

    # ... and the runner leaves EVIDENCE that it could not look.
    p = _proj(tmp_path)

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("cat ") and ".magicrc" in cmd:
            return (0, "tech load $env(PDK_ROOT)/generic.tech\n", "")
        return _fake_docker(COMPLETE_GENERIC_TECH,
                            MATCH_TRANSCRIPT)(container, cmd, timeout)

    monkeypatch.setattr(runner, "_docker_exec", fake)
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    # never a false BLOCKED — we still cannot judge the technology
    assert r.status != "BLOCKED"
    pre = json.loads((p / "reports" / "phase3"
                      / "lvs_extraction_preflight.json").read_text())
    assert pre["performed"] is False
    assert pre["verdict"] == "INCONCLUSIVE"
    assert "Tcl variable" in pre["note"]


def test_magicrc_naming_a_nonexistent_tech_file_is_blocked(tmp_path,
                                                           monkeypatch):
    """The existence gate proved the magicrc exists — never what it loads.

    Magic cannot load a technology file that is not there, so this is positive
    evidence of incapability, not an unknown.
    """
    p = _proj(tmp_path)

    def fake(container, cmd, timeout=0, **_):
        if cmd.startswith("cat ") and ".magicrc" in cmd:
            return (0, MAGICRC, "")
        if cmd.startswith("cat "):
            return (1, "", "no such file")    # the tech file is absent
        return _fake_docker(COMPLETE_GENERIC_TECH,
                            MATCH_TRANSCRIPT)(container, cmd, timeout)

    monkeypatch.setattr(runner, "_docker_exec", fake)
    monkeypatch.setattr(runner, "_to_container_path", lambda s, c: s)
    r = runner.step_lvs(p, "chip_top", _pdk(), "x")
    assert r.status == "BLOCKED", (r.status, r.detail)
    assert "generic.tech" in r.detail


# -- THE TWO CONTROLS: a check that cannot return clean is an alarm ---------
def test_complete_generic_tech_still_passes_end_to_end(tmp_path, monkeypatch):
    """MANDATORY control. A complete, working tech file must still PASS.

    Every capability the recipe consumes is present, including the two this
    change added. If this ever goes BLOCKED the change has become an alarm.

    This assertion deliberately uses NO new API, so it holds on pristine
    `origin/main` as well: that is what makes it a control. It proves this
    change does not move a passing run, rather than merely proving the new
    code agrees with itself.
    """
    p, r = _run(tmp_path, monkeypatch, COMPLETE_GENERIC_TECH, MATCH_TRANSCRIPT)
    assert r.status == "PASS", (r.status, r.detail)
    assert _verdict(p)["status"] != "BLOCKED"


def test_a_passing_run_still_records_that_the_preflight_ran(tmp_path,
                                                            monkeypatch):
    """Clean must be distinguishable from unchecked, on the clean path too."""
    p, _ = _run(tmp_path, monkeypatch, COMPLETE_GENERIC_TECH, MATCH_TRANSCRIPT)
    pre = json.loads((p / "reports" / "phase3"
                      / "lvs_extraction_preflight.json").read_text())
    assert pre["performed"] is True and pre["verdict"] == "USABLE"


def test_complete_generic_tech_with_a_real_mismatch_still_fails(tmp_path,
                                                                monkeypatch):
    """MANDATORY control. The whole RISK of this change is laundering a real
    FAIL into "blocked". A complete tech file plus a genuine device mismatch
    must still be reported as FAIL — a compare RAN and it did not match.
    """
    p, r = _run(tmp_path, monkeypatch, COMPLETE_GENERIC_TECH,
                MISMATCH_TRANSCRIPT)
    assert r.status == "FAIL", (r.status, r.detail)
    assert r.status != "BLOCKED"
    assert _verdict(p)["status"] not in ("BLOCKED", "PASS")


def test_every_new_requirement_is_recipe_derived_not_hardcoded():
    """The added requirements must follow the RECIPE, like #212's did.

    The same technology file that cannot support extraction is perfectly
    capable of streaming GDS, and the check must say so — otherwise the model
    is a hardcoded section list wearing a derivation's clothes.
    """
    ext = [c.name for c in eicap.required_capabilities(
        eicap.DEFAULT_EXT2SPICE_COMMANDS)]
    gds = [c.name for c in eicap.required_capabilities(
        "gds read in.gds\ngds write out.gds\n")]
    assert "LEF layer map" in ext and "LEF layer map" not in gds
    assert "device extraction rules" in ext
    assert "device extraction rules" not in gds
    assert "CIF/GDS output rules" in gds and "CIF/GDS output rules" not in ext

    # ... and behaviourally, on the SAME file: lacking `lef` and `device` is
    # terminal for extraction and IRRELEVANT to GDS streaming, which is blocked
    # only for the thing IT consumes (`cifoutput`). Neither requirement leaks
    # into the recipe that does not ask for it.
    tech = _tech(lef=False, device=False, substrate=False)
    ext_rep = eicap.check_magic_tech(tech, eicap.DEFAULT_EXT2SPICE_COMMANDS)
    gds_rep = eicap.check_magic_tech(tech, "gds write out.gds\n")
    assert ext_rep.usable is False
    assert {"LEF layer map", "device extraction rules"} <= set(
        ext_rep.missing_capability_names)
    assert gds_rep.missing_capability_names == ["CIF/GDS output rules"]

    # and with `cifoutput` supplied, the same lef/device-less file streams GDS
    with_cif = tech + "\ncifoutput\n    style gdsii\n    scalefactor 10\nend\n"
    assert eicap.check_magic_tech(with_cif, "gds write out.gds\n").usable is True
    assert eicap.check_magic_tech(
        with_cif, eicap.DEFAULT_EXT2SPICE_COMMANDS).usable is False


# ==========================================================================
# 8 — BLOCKED IS STILL NEVER A ROUTE TO GREEN, FOR THE *NEW* PATHS TOO
# ==========================================================================
# #212 verified this for the one BLOCKED path it introduced. This change adds
# more (missing `lef`, missing `device`, total layer non-coverage, an absent
# technology file), and a new verdict path is exactly where a "cannot verify"
# quietly becomes a pass. Verified against the REAL aggregate + gate, not
# assumed from the fact that the first path was safe.

@pytest.mark.parametrize("tech,label", [
    (_tech(lef=False), "no lef section"),
    (_tech(device=False), "extract without device"),
    (_tech(styles=False), "empty styles"),
])
def test_every_new_blocked_path_lands_non_green(tmp_path, monkeypatch,
                                                tech, label):
    """Each new BLOCKED cause must reach a non-green run verdict.

    The netgen transcript is a CLEAN MATCH throughout: if any path let the
    flow reach the compare, it would borrow a pass it never earned.
    """
    p, r = _run(tmp_path, monkeypatch, tech, MATCH_TRANSCRIPT)
    assert r.status == "BLOCKED", (label, r.status, r.detail)
    # the real aggregate, not a re-implementation of it
    assert runner._aggregate_verdict([r]) == "FAIL", label
    assert runner._aggregate_verdict(
        [runner.StepResult("synth", "PASS", 0.0, ""), r]) == "FAIL", label
    # the Step-31 sign-off gate refuses it and names the file
    blocked = audit._lvs_blocked_verdict(p)
    assert blocked is not None, label
    # and the verdict artifact is not a pass under any spelling
    v = _verdict(p)
    assert v["status"] == "BLOCKED" and v["result"] == "BLOCKED", label


def test_blocked_run_exit_code_is_nonzero():
    """The process exit code is the last consumer, and the coarsest."""
    for verdict in ("FAIL",):
        assert verdict not in ("PASS", "PASS_WITH_WAIVERS",
                               "PASS_WITH_OPEN_SOURCE_CONSTRAINTS")
    blocked = runner.StepResult("lvs", "BLOCKED", 0.0, "")
    assert runner._aggregate_verdict([blocked]) == "FAIL"


def test_preflight_artifact_never_asserts_a_pass(tmp_path, monkeypatch):
    """The new artifact must not become a second, softer place to look green.

    `performed` distinguishes "checked and clean" from "could not check" —
    without it, an absent finding reads as a clean bill of health.
    """
    p, r = _run(tmp_path, monkeypatch, _tech(lef=False), MATCH_TRANSCRIPT)
    pre = json.loads((p / "reports" / "phase3"
                      / "lvs_extraction_preflight.json").read_text())
    assert pre["verdict"] == "BLOCKED"
    assert pre["usable"] is False
    assert "LEF layer map" in [m["capability"] for m in pre["missing"]]
    assert "status" not in pre and "result" not in pre


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
_REAL_PDK_ROOTS = [
    Path("/usr/share/pdk"), Path("/opt/pdk"),
    Path.home() / ".volare" / "volare",
]


def _real_tech_files():
    roots = list(_REAL_PDK_ROOTS)
    # so the guard is runnable wherever the PDKs actually live
    env = os.environ.get("VIBEIC_PDK_ROOT")
    if env:
        roots = [Path(p) for p in env.split(os.pathsep) if p] + roots
    out = []
    for root in roots:
        if root.is_dir():
            out.extend(sorted(root.glob("*/libs.tech/magic/*.tech")))
    return out


@pytest.mark.skipif(not _real_tech_files(),
                    reason="no real PDK technology files installed here")
def test_no_real_extraction_technology_file_is_blocked():
    """A working PDK must never be called incapable.

    The `-GDS` variants are excluded BY NAME-SHAPE, not by PDK: they are the
    GDS-streaming technologies, which a magicrc never loads for extraction and
    which genuinely carry no extraction rules. Under a GDS-streaming recipe
    the very same files come back usable — asserted below, so this exclusion
    is a derivation and not a waiver.
    """
    blocked = []
    for t in _real_tech_files():
        rep = eicap.check_magic_tech_file(t, eicap.DEFAULT_EXT2SPICE_COMMANDS)
        if not rep.usable and "-GDS" not in t.name:
            blocked.append((t.name, rep.missing_capability_names))
    assert blocked == [], f"false BLOCKED on working technology files: {blocked}"


@pytest.mark.skipif(not _real_tech_files(),
                    reason="no real PDK technology files installed here")
def test_gds_only_technologies_are_usable_under_a_gds_recipe():
    """Proves the exclusion above is recipe-derived, not a special case."""
    for t in _real_tech_files():
        if "-GDS" not in t.name:
            continue
        rep = eicap.check_magic_tech_file(t, "gds read a.gds\ngds write b.gds\n")
        assert rep.usable is True, (t.name, rep.reason)
