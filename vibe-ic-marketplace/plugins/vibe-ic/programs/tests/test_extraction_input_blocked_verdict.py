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

extract
    style generic
    lambda 1.0
    planeorder metalplane 0
    resist routing_a 100
    resist routing_b 100
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

include generic-extract
"""

SPLIT_EXTRACT_TECH = """\
extract
    style generic
    lambda 1.0
    resist routing_a 100
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
