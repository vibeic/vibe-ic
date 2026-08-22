#!/usr/bin/env python3
"""A programmable non-volatile memory needs a way in for its programming supply.

THE CONVENTION UNDER TEST
-------------------------
Any programmable non-volatile memory — one-time-programmable, fuse-based,
multiple-time-programmable, antifuse — is WRITTEN at a voltage above the
digital core supply, delivered from OUTSIDE the die through a dedicated
terminal: a package pin for in-field programming, or a wafer-probe pad for
programming before the part ships. READING it generally needs only the core
supply, which is why a read-only integration looks complete while a
programming integration is not.

Physics, not vendor preference: within one process, two INDEPENDENT
programmable-memory IP families — one native to the process, one third-party —
both specify their programming supply as externally supplied and both specify a
window above that process's core supply. Unrelated vendors do not converge by
accident.

THE DEFECT
----------
A design instantiates such a memory, its RTL carries a full programming
handshake, and its top level declares no programming supply pin at all. It
cannot do the thing it is built to do — and nothing in the digital flow says
so, because the digital logic is entirely correct. What actually surfaces is
five steps later and names none of this: synthesis tie-cells the macro's supply
pin, a signal net lands on a power terminal, and detailed routing aborts.

RELATIONSHIP TO #309
--------------------
#309 blocks that SYMPTOM before routing. This blocks the CAUSE before anything
runs. Both live in `hardmacro_supply_intent` so the judgement cannot drift, but
they answer different questions — a pin can be perfectly DECLARED in the
power-intent layer (#309's question) and still have no package pin, because
that layer describes internal rails and an internal rail can never answer for a
supply that is above core voltage by definition.

Every fixture below is synthetic and generic: a made-up macro with made-up pin
names, exercising the LEF `USE POWER` record and the design's own port list.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import hardmacro_supply_intent as H  # noqa: E402
import nvm_program_supply_pin_check as N  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic fixtures — a programmable-memory macro with a core supply and a
# separate programming supply, plus a plain volatile RAM with only a core rail.
# ---------------------------------------------------------------------------
_FUSE_LEF = """VERSION 5.8 ;
MACRO fuse_array_256x8
  CLASS BLOCK ;
  SIZE 40.0 BY 30.0 ;
  PIN clk
    DIRECTION INPUT ; USE SIGNAL ;
  END clk
  PIN prog_req
    DIRECTION INPUT ; USE SIGNAL ;
  END prog_req
  PIN prog_busy
    DIRECTION OUTPUT ; USE SIGNAL ;
  END prog_busy
  PIN VDD
    DIRECTION INOUT ; USE POWER ;
  END VDD
  PIN VPGM
    DIRECTION INOUT ; USE POWER ;
  END VPGM
  PIN VSS
    DIRECTION INOUT ; USE GROUND ;
  END VSS
END fuse_array_256x8
END LIBRARY
"""

# Same macro shape, but every name is read-side only: no programming verb
# anywhere. A part programmed by its vendor before delivery looks like this.
_READONLY_LEF = (_FUSE_LEF
                 .replace("fuse_array_256x8", "romblock_256x8")
                 .replace("prog_req", "rd_en")
                 .replace("prog_busy", "rd_valid"))

_RAM_LEF = """VERSION 5.8 ;
MACRO ram_1024x32
  CLASS BLOCK ;
  PIN clk
    DIRECTION INPUT ; USE SIGNAL ;
  END clk
  PIN VDD
    DIRECTION INOUT ; USE POWER ;
  END VDD
  PIN VSS
    DIRECTION INOUT ; USE GROUND ;
  END VSS
END ram_1024x32
END LIBRARY
"""


def _rtl(master: str, extra_port: str = "", inst_pins: str = "") -> str:
    port = f"    {extra_port},\n" if extra_port else ""
    return f"""module chip_top (
    input  wire       clk,
    input  wire       rst_n,
{port}    input  wire       prog_req,
    input  wire [7:0] prog_addr,
    input  wire [7:0] prog_data,
    output wire       prog_busy,
    output wire [7:0] rd_data
);
    {master} u_mem (
        .clk       (clk),
        .prog_req  (prog_req),
        .prog_busy (prog_busy){inst_pins}
    );
    assign rd_data = 8'h00;
endmodule
"""


def _mk(tmp_path, lef: str, rtl: str, name="proj", docs=None):
    d = tmp_path / name
    (d / "input" / "pdk_local" / "vendor").mkdir(parents=True)
    (d / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (d / "input" / "pdk_local" / "vendor" / "mem.lef").write_text(lef)
    (d / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(rtl)
    for stem, blob in (docs or {}).items():
        g = d / "phase1" / "generated_docs"
        g.mkdir(parents=True, exist_ok=True)
        (g / f"{stem}.json").write_text(json.dumps(blob))
    return d


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL — the same check must FAIL before the fix and PASS after.
# A test that cannot fail is not a test.
# ---------------------------------------------------------------------------
def test_before_fix_missing_programming_supply_pin_is_a_finding(tmp_path):
    d = _mk(tmp_path, _FUSE_LEF, _rtl("fuse_array_256x8"))
    rep = N.check(d)
    assert rep["verdict"] == "FAIL"
    assert rep["pass"] is False
    f = rep["findings"][0]
    assert f["rule"] == "NVM_PROGRAM_SUPPLY_PIN_ABSENT"
    assert f["master"] == "fuse_array_256x8"
    assert "VPGM" in f["pins"]
    # The finding must SHOW its programming-intent evidence, not assert it.
    assert f["program_intent"], "a finding with no evidence is an assertion"


def test_after_fix_declaring_the_pin_at_top_level_passes(tmp_path):
    """The ONLY difference from the test above is one top-level port."""
    d = _mk(tmp_path, _FUSE_LEF, _rtl("fuse_array_256x8", "inout  wire VPGM"))
    rep = N.check(d)
    assert rep["verdict"] == "PASS"
    assert rep["findings"] == []


def test_after_fix_a_probe_pad_declared_in_the_pinout_also_counts(tmp_path):
    """Programming before the part ships uses a wafer-probe pad, which is a
    real terminal even when it is not an RTL port. The design declares it in
    its own pinout, and that must count — otherwise the gate would force every
    factory-programmed part to invent an RTL port it does not need."""
    d = _mk(tmp_path, _FUSE_LEF, _rtl("fuse_array_256x8"),
            docs={"L1_DATASHEET": {"pinout": {"VPGM": {"type": "probe_pad"}}}})
    rep = N.check(d)
    assert rep["verdict"] == "PASS"
    assert rep["findings"] == []


# ---------------------------------------------------------------------------
# The three terms of the triad, each removed in turn — none alone may fire.
# ---------------------------------------------------------------------------
def test_no_programming_intent_is_recorded_not_raised(tmp_path):
    """A memory programmed by its vendor before delivery carries no programming
    logic, needs no programming pin, and is a legitimate design. Recorded so
    the assumption is visible; NOT a finding, and the run is not blocked."""
    d = _mk(tmp_path, _READONLY_LEF,
            _rtl("romblock_256x8").replace("prog_", "rd_"))
    rep = N.check(d)
    assert rep["findings"] == []
    assert rep["verdict"] == "PASS_WITH_REVIEW"
    assert rep["notes"][0]["rule"] == "NVM_NO_PROGRAM_INTENT"


def test_volatile_ram_with_only_a_core_rail_never_fires(tmp_path):
    """The common case on the fleet: one POWER pin, which is the core rail the
    PDN provides internally. Nothing is required from outside."""
    d = _mk(tmp_path, _RAM_LEF, _rtl("ram_1024x32"))
    rep = N.check(d)
    assert rep["findings"] == [] and rep["notes"] == []
    assert rep["verdict"] == "PASS"


def test_macro_staged_but_never_instantiated_skips(tmp_path):
    """A macro sitting in the vendor drop the RTL does not use is not this
    design's integration problem."""
    d = _mk(tmp_path, _FUSE_LEF, _rtl("some_other_block"))
    rep = N.check(d)
    assert rep["verdict"] == "SKIP"


def test_no_macro_lef_skips(tmp_path):
    d = tmp_path / "p"
    (d / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (d / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(
        _rtl("fuse_array_256x8"))
    rep = N.check(d)
    assert rep["verdict"] == "SKIP" and rep["pass"] is True


def test_no_rtl_skips_rather_than_guessing(tmp_path):
    """Without RTL neither instantiation nor programming intent is readable.
    Guessing either way would be dishonest."""
    d = tmp_path / "p"
    (d / "input" / "pdk_local" / "v").mkdir(parents=True)
    (d / "input" / "pdk_local" / "v" / "mem.lef").write_text(_FUSE_LEF)
    rep = N.check(d)
    assert rep["verdict"] == "SKIP"


# ---------------------------------------------------------------------------
# Core-vs-programming supply discrimination — no pin name is hardcoded, so the
# rule must hold under BOTH rail-naming conventions.
# ---------------------------------------------------------------------------
def test_rails_matching_the_macro_naming_name_the_core_pin_exactly(tmp_path):
    d = _mk(tmp_path, _FUSE_LEF, _rtl("fuse_array_256x8"))
    rep = N.check(d, rails=["VDD"])
    m = rep["macros"][0]
    assert m["core_rail_identified"] == ["VDD"]
    assert rep["findings"][0]["pins"] == ["VPGM"]
    assert "not the core rail" in rep["findings"][0]["message"]


def test_rails_named_differently_fall_back_to_at_most_one_core_rail(tmp_path):
    """A design whose rail names differ from the macro vendor's is routine. We
    can no longer say WHICH pin is the core supply — only that at most one is,
    so at least one of two uncarried supplies has no way in. The verdict must
    still be right in both directions, and the message must not over-claim."""
    broken = _mk(tmp_path, _FUSE_LEF, _rtl("fuse_array_256x8"), name="b")
    rep = N.check(broken, rails=["VPWR"])
    assert rep["verdict"] == "FAIL"
    assert rep["macros"][0]["core_rail_identified"] == []
    assert "cannot be said" in rep["findings"][0]["message"]

    fixed = _mk(tmp_path, _FUSE_LEF,
                _rtl("fuse_array_256x8", "inout  wire VPGM"), name="f")
    assert N.check(fixed, rails=["VPWR"])["verdict"] == "PASS"


def test_a_single_power_pin_is_always_the_core_rail(tmp_path):
    """Even when its name matches no declared rail — a die has one core rail,
    and a macro with one POWER pin is asking for exactly that."""
    d = _mk(tmp_path, _RAM_LEF, _rtl("ram_1024x32"))
    assert N.check(d, rails=["VPWR"])["findings"] == []


# ---------------------------------------------------------------------------
# The name matching itself — the only place a literal could sneak in.
# ---------------------------------------------------------------------------
def test_program_intent_tokens_match_whole_tokens_only():
    assert H._carries_token("prog_req", H.PROGRAM_INTENT_TOKENS) == "prog"
    assert H._carries_token("pgmAddr", H.PROGRAM_INTENT_TOKENS) == "pgm"
    assert H._carries_token("burn_en", H.PROGRAM_INTENT_TOKENS) == "burn"
    # Substring lookalikes must NOT match.
    assert H._carries_token("progress_ctr", H.PROGRAM_INTENT_TOKENS) is None
    assert H._carries_token("defuser", H.PROGRAM_INTENT_TOKENS) is None
    assert H._carries_token("blowout_x", H.PROGRAM_INTENT_TOKENS) is None


def test_a_ram_write_is_not_a_fuse_programming_operation():
    """`write`/`we`/`wr` are deliberately OUT of the vocabulary: including them
    would fire on every design with a RAM macro."""
    for sig in ("we", "wr_en", "write_enable", "wdata"):
        assert H._carries_token(sig, H.PROGRAM_INTENT_TOKENS) is None


def test_external_entry_matching_is_token_contiguous_not_substring():
    assert H.external_entry_for("VPGM", ["clk", "vpgm"]) == "vpgm"
    assert H.external_entry_for("VPGM", ["vpgm_pad"]) == "vpgm_pad"
    assert H.external_entry_for("VPGM", ["pad_vpgm"]) == "pad_vpgm"
    # A different terminal must never be accepted as this one.
    assert H.external_entry_for("VPGM", ["VPGMX"]) is None
    assert H.external_entry_for("VPGM", ["VPG"]) is None


def test_no_macro_pin_or_vendor_literal_in_the_gate_source():
    """The judgement must be driven by the design's inputs. The only literals
    permitted are generic English words for the ACT of programming."""
    src = (_PROGRAMS / "nvm_program_supply_pin_check.py").read_text()
    for fixture_literal in ("VPGM", "fuse_array_256x8", "VPWR", "VDD", "VPP"):
        assert fixture_literal not in src, (
            f"{fixture_literal!r} is hardcoded in the gate — the pin name must "
            f"come from the macro's own LEF, not from this source")


# ---------------------------------------------------------------------------
# The shared decision module must keep answering #309's question unchanged.
# ---------------------------------------------------------------------------
def test_lef_pg_pins_still_returns_only_power_and_ground():
    pg = H.lef_pg_pins(_FUSE_LEF)
    assert {(p["pin"], p["use"]) for p in pg} == {
        ("VDD", "POWER"), ("VPGM", "POWER"), ("VSS", "GROUND")}
    assert all(p["master"] == "fuse_array_256x8" for p in pg)


def test_lef_all_pins_adds_the_signal_pins_and_defaults_to_signal():
    allp = {p["pin"]: p["use"] for p in H.lef_all_pins(_FUSE_LEF)}
    assert allp["prog_req"] == "SIGNAL"
    assert allp["VPGM"] == "POWER"
    # A PIN with no USE record defaults to SIGNAL (the LEF default).
    no_use = "MACRO m\n  PIN a\n    DIRECTION INPUT ;\n  END a\nEND m\n"
    assert H.lef_all_pins(no_use) == [
        {"master": "m", "pin": "a", "use": "SIGNAL"}]


# ---------------------------------------------------------------------------
# ENFORCEMENT — #306 measured that 62 of 72 flow gates can only describe a run
# after it happened. This gate CLAIMS to block; the claim must be verifiable.
# ---------------------------------------------------------------------------
def test_gate_declares_its_enforcement_intent():
    src = (_PROGRAMS / "nvm_program_supply_pin_check.py").read_text()
    assert "ENFORCEMENT: blocking" in src


def test_gate_is_wired_into_the_flow_definition():
    flow = (_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text()
    assert "nvm_program_supply_pin_check" in flow


def test_the_shipped_audit_classifies_this_gate_as_enforced():
    """Not read from the source — measured by the same audit that produced the
    62-of-72 number, so the claim and the measurement cannot drift."""
    import flow_gate_enforcement_audit as A
    rep = A.audit(_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml",
                  _PROGRAMS)
    row = [r for r in rep["gates"]
           if r["gate"].startswith("nvm_program_supply_pin_check")]
    assert row, "gate is not visible to the enforcement audit at all"
    assert row[0]["enforcement"] == "ENFORCED"
    assert row[0]["declared"] == "blocking"
    assert not [c for c in rep["contradictions"]
                if c["gate"].startswith("nvm_program_supply_pin_check")]
    assert not [o for o in rep["orphaned"]
                if o["gate"].startswith("nvm_program_supply_pin_check")]


def test_phase3_runner_invokes_the_gate_before_any_backend_step():
    """It must run at the top of main(), not inside a late step — the whole
    point is to refuse before the run spends time producing a shell."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "import nvm_program_supply_pin_check" in src
    assert "nvm_program_supply_pin_check.check(" in src
    # Before the banner that precedes the step plan.
    assert (src.index("nvm_program_supply_pin_check.check(")
            < src.index("=== phase3_one_shot_runner — pdk="))


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------
def _cli(project, *extra):
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "nvm_program_supply_pin_check.py"),
         str(project), *extra],
        capture_output=True, text=True, timeout=300)


def test_cli_exit_1_on_the_finding_and_0_after_the_fix(tmp_path):
    broken = _mk(tmp_path, _FUSE_LEF, _rtl("fuse_array_256x8"), name="b")
    fixed = _mk(tmp_path, _FUSE_LEF,
                _rtl("fuse_array_256x8", "inout  wire VPGM"), name="f")
    out = tmp_path / "r.json"
    r = _cli(broken, "--json", str(out))
    assert r.returncode == 1
    assert "NVM_PROGRAM_SUPPLY_PIN_ABSENT" in r.stderr
    assert json.loads(out.read_text())["verdict"] == "FAIL"
    assert _cli(fixed).returncode == 0


def test_cli_exit_2_on_a_bad_project_path(tmp_path):
    assert _cli(tmp_path / "nope").returncode == 2
