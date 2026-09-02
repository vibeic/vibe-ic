"""#701 — a hard macro the power grid could not reach looked like no macro.

THE DEFECT
----------
`_macro_pdn_grid_plan` returned `None` when a hard macro's own OBS blocked
EVERY routing layer above its supply-pin layer. `None` was ALSO what the same
function returned for "this design has no hard macros at all", so
`_build_macro_pdn_grid_tcl` emitted the empty string and the run's PDN note was
BYTE-IDENTICAL to a macro-free design.

Reproduced on PUBLIC sky130A material (the sky130 1kbyte SRAM macro + the
sky130_fd_sc_hd tech LEF), three cases, one flow:

    A. macro as the PDK ships it          -> plan BUILT, 586 bytes of Tcl,
                                             note " + macro_grid(met3->met4@…)"
    B. same macro, vendor also blocking
       the layers above the pin layer     -> plan None, 0 bytes, note ""
    C. CONTROL: no hard macro at all      -> plan None, 0 bytes, note ""

B and C agreed in every observable the flow produced. Two different facts about
the world collapsed onto one output, and the dropped macro first surfaced
several steps downstream as PSM-0038/0039/0069 with nothing pointing back.

The plan dict already carried `refused_for_blockage` for exactly this report —
and it could only ever be populated on the SUCCESS path. When the OBS rule
removed every candidate strap layer there was no plan to hang the reason on,
and the reason was discarded.

WHAT THIS FILE PINS
-------------------
The OBSERVABLE PROPERTY, at the altitude the flow actually emits: the PDN Tcl
that `_build_pdn_tcl` writes into pnr.tcl. Nothing here asserts a sentinel
value, a return type or a field name of the planner, so a DIFFERENT correct fix
passes these unchanged. What must hold:

  * B and C no longer produce the same text.
  * B NAMES the macro and the layers its OBS took off the table.
  * B does NOT build a grid anyway — the OBS is not overridden. A green run and
    a defiant grid are both wrong answers; the right one is a loud refusal.
  * C is unchanged: a genuinely macro-free design must not start emitting a
    refusal, and it must stay byte-identical to a run with no macro LEFs.
  * A is unchanged: a macro the grid CAN reach still gets exactly the grid it
    got before, to the byte.

The last two are the controls that matter. A "fix" that refuses more and more
until nothing is ever planned would satisfy the first three and destroy the
flow; only A and C catch it.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "programs"))
mod = importlib.import_module("phase3_one_shot_runner")


# --------------------------------------------------------------- fixtures --
# No PDK literal anywhere: layer names, directions, pitches and every dimension
# are invented here, exactly as the neighbouring PDN tests do. The public-PDK
# reproduction that opened the issue lives in the PR body; this file reproduces
# the same SHAPE without vendoring a foundry LEF.
def _stack(prefix: str = "M",
           dirs=("HORIZONTAL", "VERTICAL", "HORIZONTAL",
                 "VERTICAL", "HORIZONTAL", "VERTICAL"),
           pitch: float = 0.5, width: float = 0.2) -> str:
    return "".join(
        f"LAYER {prefix}{i}\n  TYPE ROUTING ;\n  DIRECTION {d} ;\n"
        f"  PITCH {pitch} ;\n  WIDTH {width} ;\nEND {prefix}{i}\n"
        for i, d in enumerate(dirs, 1))


CELL_LEF = """\
MACRO cellA
  CLASS core ;
  SIZE 2.0 BY 10.0 ;
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER M1 ;
        RECT 0.0 9.6 2.0 10.4 ;
    END
  END VDD
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER M1 ;
        RECT 0.0 -0.4 2.0 0.4 ;
    END
  END VSS
END cellA
"""

MACRO_W, MACRO_H = 400.0, 140.0
MACRO_NAME = "HARDBLOCK_NVMA"

# One hard macro. Supply pins on M3, each with a port wide enough in BOTH axes
# for a legal strap pitch on either strap layer, so the ONLY thing that can stop
# the grid is the OBS. (A port that is a sliver in one axis is a different, real
# refusal — exercised separately below — and would confound this one.)
MACRO_HEAD = f"""\
MACRO {MACRO_NAME}
    CLASS BLOCK ;
    SIZE {MACRO_W} BY {MACRO_H} ;
    PIN PWRA
        DIRECTION INPUT ;
        USE POWER ;
        PORT
         LAYER M3 ;
          RECT 160 0 172 12 ;
        END
    END PWRA
    PIN GNDA
        DIRECTION INPUT ;
        USE GROUND ;
        PORT
         LAYER M3 ;
          RECT 120 0 132 12 ;
        END
    END GNDA
"""

# The same macro with SLIVER supply ports: 12um along the strap, 0.4um across
# it. No legal pitch can be guaranteed to cross those, which was ANOTHER silent
# `None` on the same code path.
SLIVER_MACRO = f"""\
MACRO SLIVERBLOCK
    CLASS BLOCK ;
    SIZE {MACRO_W} BY {MACRO_H} ;
    PIN PWRA
        DIRECTION INPUT ;
        USE POWER ;
        PORT
         LAYER M3 ;
          RECT 160 0 160.4 12 ;
        END
    END PWRA
END SLIVERBLOCK
"""


def _macro(obs_layers=(), obs_size=None) -> str:
    """The macro, optionally declaring `obs_layers` blocked over `obs_size`
    (its whole footprint by default) — plain LEF grammar, and the ordinary
    vendor stance for an NVM or high-voltage block."""
    lef = MACRO_HEAD
    if obs_layers:
        w, h = obs_size or (MACRO_W, MACRO_H)
        lef += "  OBS\n    LAYER OVERLAP ;\n" \
               f"      RECT 0 0 {MACRO_W} {MACRO_H} ;\n"
        for layer in obs_layers:
            lef += f"    LAYER {layer} ;\n      RECT 0 0 {w} {h} ;\n"
        lef += "  END\n"
    return lef + f"END {MACRO_NAME}\n"


SIGNAL_ONLY_MACRO = """\
MACRO SIGBLOCK
    CLASS BLOCK ;
    SIZE 10 BY 10 ;
    PIN A
        DIRECTION INPUT ;
        USE SIGNAL ;
        PORT
         LAYER M3 ;
          RECT 0 0 1 1 ;
        END
    END A
END SIGBLOCK
"""


def _pdk(tmp_path, macro_lef_text=None, *, tag="m"):
    """A PDK whose adaptive PDN path is the one under test. `macro_lef_text`
    None == case C: a design with no hard macro at all."""
    cl = tmp_path / f"cells_{tag}.lef"
    cl.write_text(CELL_LEF)
    tl = tmp_path / f"tech_{tag}.lef"
    tl.write_text(_stack())
    macro_lefs = []
    if macro_lef_text is not None:
        ml = tmp_path / f"macro_{tag}.lef"
        ml.write_text(macro_lef_text)
        macro_lefs = [str(ml)]
    return mod.PdkConfig(
        name="unit", liberty="/nonexistent/x.lib", tech_lef=str(tl),
        cell_lef=str(cl), cell_gds=None, site="SITE", drc_deck=None,
        metal_prefix="M", tapcell_master=None, macro_lefs=macro_lefs)


def _pdn(tmp_path, macro_lef_text=None, *, tag="m") -> str:
    return mod._build_pdn_tcl(_pdk(tmp_path, macro_lef_text, tag=tag))


# The macro grid the flow builds for the REACHABLE macro, to the byte. Pinned
# as a literal so any change to what a reachable macro gets is a deliberate,
# visible edit — this is the half of the contract a refusal must not touch.
GRID_A_LINES = (
    "  define_pdn_grid -macro -name macro_grid -voltage_domains CORE \\\n"
    "      -cells {" + MACRO_NAME + "} -grid_over_pg_pins\n"
    "  add_pdn_stripe -grid macro_grid -layer M4 -width 0.8 -pitch 12.0"
    " -offset 0\n"
    "  add_pdn_connect -grid macro_grid -layers {M3 M4}\n"
    "  add_pdn_connect -grid macro_grid -layers {M4 M5}\n")


# ═══════════════════════════════════════════════════════════════════════════
# THE DEFECT: B and C were the same text
# ═══════════════════════════════════════════════════════════════════════════
def test_a_refused_macro_no_longer_reads_as_a_macro_free_design(tmp_path):
    """THE bidirectional control. Pre-fix these two strings were equal; the
    whole issue is that equality."""
    blocked = _pdn(tmp_path, _macro(obs_layers=("M4", "M5")), tag="b")
    macro_free = _pdn(tmp_path, None, tag="c")
    assert blocked != macro_free, (
        "a hard macro whose supply the grid could not reach still produces the "
        "same PDN text as a design containing no hard macro")


def test_the_refusal_names_the_macro_and_why(tmp_path):
    """'Something went wrong somewhere' is the same silence, one step quieter.
    The output must carry the MASTER and the LAYERS its OBS removed."""
    tcl = _pdn(tmp_path, _macro(obs_layers=("M4", "M5")), tag="b")
    assert MACRO_NAME in tcl, "the refused macro is not named"
    # NOT `"M4" in tcl`: the core strap lines mention M4 and M5 whatever
    # happens, so that would pass on a completely silent build. The layers the
    # OBS removed must appear on the text that NAMES the macro.
    about_the_macro = "\n".join(ln for ln in tcl.splitlines()
                                if MACRO_NAME in ln)
    assert "M4" in about_the_macro and "M5" in about_the_macro, \
        "the refusal does not say WHICH layers the OBS took off the table"
    assert re.search(r"(?i)obs|block", about_the_macro), \
        "the refusal does not say WHY no macro grid was built"


def test_the_refusal_does_not_build_a_grid_in_defiance_of_the_OBS(tmp_path):
    """The correct outcome is a LOUD refusal, not a grid the macro forbids.
    A fix that satisfies the two tests above by strapping a blocked layer has
    replaced a silent omission with a silent violation."""
    tcl = _pdn(tmp_path, _macro(obs_layers=("M4", "M5")), tag="b")
    assert "define_pdn_grid -macro" not in tcl
    assert "add_pdn_stripe -grid macro_grid" not in tcl


def test_the_refusal_survives_into_the_runs_own_transcript(tmp_path):
    """A reason recorded where nobody reads it is not a fix. The refusal is
    emitted as a `puts`, so it lands in openroad.log next to the PDN marker
    that a reader is already looking at — not in a side file."""
    tcl = _pdn(tmp_path, _macro(obs_layers=("M4", "M5")), tag="b")
    said = [ln for ln in tcl.splitlines()
            if ln.strip().startswith("puts") and MACRO_NAME in ln]
    assert said, "the refusal never reaches the OpenROAD transcript"


# ═══════════════════════════════════════════════════════════════════════════
# THE REVERSE CASES — the controls that catch a filter tightened to zero
# ═══════════════════════════════════════════════════════════════════════════
def test_case_A_a_reachable_macro_still_gets_exactly_its_grid(tmp_path):
    """THE control that matters most. A macro the grid CAN reach must be
    planned and rendered UNCHANGED — byte-for-byte the same four commands."""
    tcl = _pdn(tmp_path, _macro(), tag="a")
    assert GRID_A_LINES in tcl, (
        "the macro grid for a reachable macro changed; the refusal path must "
        "not touch it")
    assert "macro_grid(M3->M4@12.0)" in tcl, "the PDN note lost its grid clause"


def test_case_A_a_reachable_macro_emits_no_refusal(tmp_path):
    """A grid that WAS built must not also report that it was not."""
    tcl = _pdn(tmp_path, _macro(), tag="a")
    assert "REFUSED" not in tcl


def test_case_C_a_macro_free_design_is_byte_identical_to_before(tmp_path):
    """The reverse-direction control: nothing to do must stay nothing said.
    A macro-free design's PDN Tcl must be exactly a run with no macro LEFs,
    and must contain no refusal of any kind."""
    tcl = _pdn(tmp_path, None, tag="c")
    assert "REFUSED" not in tcl
    assert "macro_grid" not in tcl
    assert "define_pdn_grid -macro" not in tcl
    # and it is still the ordinary successful adaptive PDN
    assert "PDN_INSERTED_ADAPTIVE" in tcl
    assert "straps(auto:M4,M5)" in tcl


def test_a_macro_with_no_supply_pins_is_nothing_to_do_not_a_refusal(tmp_path):
    """A block declaring no POWER/GROUND port asks the grid for nothing. That
    is the one case where `no plan` genuinely means `nothing to do`, and
    reporting a refusal there would be the false alarm this fix must not add."""
    tcl = _pdn(tmp_path, SIGNAL_ONLY_MACRO, tag="s")
    assert "REFUSED" not in tcl
    # byte-identical to the macro-free design, which here is the CORRECT
    # answer rather than the bug: there is genuinely nothing to reach.
    assert tcl == _pdn(tmp_path, None, tag="c2")


def test_a_partially_blocked_layer_is_not_a_refusal(tmp_path):
    """Half the footprint blocked is ordinary and a strap routes around it.
    A rule that refuses these refuses nearly every real macro, and a rule that
    refuses everything is a rule someone turns off."""
    partial = _macro(obs_layers=("M4", "M5"),
                     obs_size=(MACRO_W / 2.0, MACRO_H))
    tcl = _pdn(tmp_path, partial, tag="p")
    assert "REFUSED" not in tcl
    assert GRID_A_LINES in tcl, "a partial obstruction must not change the grid"


def test_one_blocked_layer_still_falls_through_to_the_next(tmp_path):
    """Refusing a layer is not refusing the macro. With M4 blocked the grid
    must move UP to M5, not give up — the pre-existing #685 behaviour, pinned
    here because a refusal path is exactly what could swallow it."""
    tcl = _pdn(tmp_path, _macro(obs_layers=("M4",)), tag="o")
    assert "REFUSED" not in tcl
    assert "add_pdn_stripe -grid macro_grid -layer M5" in tcl
    assert "add_pdn_stripe -grid macro_grid -layer M4" not in tcl


def test_the_other_total_silence_on_this_path_also_speaks_now(tmp_path):
    """Same defect, different cause: when EVERY supply port is narrower across
    the strap than the smallest legal pitch, the planner also returned a bare
    `None`. The PARTIAL version of this was already reported
    (MACRO_PDN_PORT_UNREACHABLE) — but that marker lives on the plan, so the
    total version emitted nothing at all."""
    tcl = _pdn(tmp_path, SLIVER_MACRO, tag="v")
    assert "SLIVERBLOCK" in tcl
    assert tcl != _pdn(tmp_path, None, tag="c4")
    # Round 15 (u_hawaii_adc): a sliver port is exactly what a PER-PIN STUB
    # reaches — one strap of one net across the pin, sized from the pin
    # positions — so the pattern planner's refusal is now answered with a
    # stub grid instead of standing as the last word. The stub grid IS a
    # `define_pdn_grid -macro`, and the refusal marker is gone because the
    # supply is reached; what remains loud is the stub's own marker.
    assert "MACRO_SUPPLY_STUBS:" in tcl
    assert "MACRO_PDN_GRID_REFUSED" not in tcl
    assert "define_pdn_grid -macro" in tcl


# ═══════════════════════════════════════════════════════════════════════════
# THE RUNNER READS IT BACK  (this implementation's seam, stated as such)
# ═══════════════════════════════════════════════════════════════════════════
def test_the_marker_is_read_back_and_not_merely_printed(tmp_path):
    """#685's sibling defect was a marker `git grep` found in exactly one
    place: the line that printed it. This one is parsed."""
    tcl = _pdn(tmp_path, _macro(obs_layers=("M4", "M5")), tag="b")
    got = mod._parse_macro_pdn_grid_refusals(tcl)
    assert [r["master"] for r in got] == [MACRO_NAME]
    assert got[0]["pin_layer"] == "M3"
    assert got[0]["reason"]  # a stable machine token, whatever it is


def test_the_parser_is_silent_on_a_macro_free_transcript(tmp_path):
    assert mod._parse_macro_pdn_grid_refusals("") == []
    assert mod._parse_macro_pdn_grid_refusals("nothing here") == []
    assert mod._parse_macro_pdn_grid_refusals(_pdn(tmp_path, None,
                                                   tag="c3")) == []


def test_it_reaches_the_pnr_steps_own_detail_and_extras():
    """The refusal has to land where a person reading the run looks. Pinned on
    the source because the surrounding step needs a full OpenROAD invocation to
    execute — the same way the PG-audit markers are pinned."""
    import inspect
    src = inspect.getsource(mod)
    assert "_parse_macro_pdn_grid_refusals(_pg_log_txt)" in src, \
        "the PnR step does not read the marker"
    assert "MACRO_PDN_GRID_REFUSED: {len(_mg_refused)}" in src, \
        "the refusal never reaches the step's detail line"
    assert '"macro_pdn_grid_refusals": _mg_refused' in src, \
        "the refusal is not machine-readable in the step's extras"


HOSTILE_NAME = 'B$AD["x"]'


def _hostile_macro(obs_layers=()) -> str:
    lef = MACRO_HEAD.replace(MACRO_NAME, HOSTILE_NAME)
    if obs_layers:
        lef += "  OBS\n    LAYER OVERLAP ;\n" \
               f"      RECT 0 0 {MACRO_W} {MACRO_H} ;\n"
        for layer in obs_layers:
            lef += f"    LAYER {layer} ;\n" \
                   f"      RECT 0 0 {MACRO_W} {MACRO_H} ;\n"
        lef += "  END\n"
    return lef + f"END {HOSTILE_NAME}\n"


def _diagnostic_puts(tcl: str):
    """Every `puts` line carrying a LEF-derived name.

    `puts "PDN_NONFATAL: $_pdn_err"` is excluded: its `$` is a Tcl variable the
    EMITTER owns and means to substitute, not a name read out of somebody
    else's LEF. This test is about the second kind.

    Round 15: the same exclusion, stated as the rule it always was. A `puts`
    whose `$` names an EMITTER-owned runtime variable (`$_...` — the retype
    audit's `$_pgt`, the stub grid's `$_m`, ...) substitutes a VALUE, and a
    value is never re-parsed, so a hostile name reaching it through the
    database cannot break the script. The hazard this test guards is a raw
    LEF name pasted into the script TEXT at emit time; those lines carry the
    name (scrubbed or raw) literally, and only those are examined here."""
    names = (HOSTILE_NAME, mod._tcl_puts_safe(HOSTILE_NAME), MACRO_NAME)
    return [ln.strip() for ln in tcl.splitlines()
            if ln.strip().startswith("puts ") and "$_pdn_err" not in ln
            and any(n in ln for n in names)]


def _is_one_tcl_literal(puts_line: str) -> bool:
    body = puts_line[len("puts "):]
    if not (body.startswith('"') and body.endswith('"')):
        return False
    inner = body[1:-1]
    return not any(c in inner for c in ('"', "$", "[", "]", "\\", "{", "}"))


def test_a_tcl_hostile_master_name_cannot_break_the_script(tmp_path):
    """Master names come out of a third-party LEF. A `$`, `[` or `"` in one
    turns a diagnostic line into a Tcl substitution and takes the whole pnr.tcl
    down — a report that crashes the run it was added to explain.

    MEASURED under a real `tclsh` while building this fix, on a macro renamed
    to `B$AD["x"]`:  can't read "AD": no such variable.

    Checked over EVERY `puts` the block emits, not just the refusal: the first
    version of this test looked only at the refusal line and passed while the
    marker line one row above was still broken."""
    tcl = _pdn(tmp_path, _hostile_macro(obs_layers=("M4", "M5")), tag="h")
    # not vacuous: the hostile macro must actually be refused, or this test
    # would pass by simply never emitting anything
    assert any("MACRO_PDN_GRID_REFUSED" in ln for ln in _diagnostic_puts(tcl))
    for line in _diagnostic_puts(tcl):
        assert _is_one_tcl_literal(line), line


def test_a_tcl_hostile_name_is_safe_on_the_REACHABLE_path_too(tmp_path):
    """The same names reach the SUCCESS marker and the unreachable-port lines.
    Both directions or neither — the marker line one row above the refusal was
    broken in the first version of this fix.

    SCOPE, stated so the gap is not mistaken for coverage: this covers the
    DIAGNOSTIC lines only. `define_pdn_grid -macro ... -cells {<master>}` still
    interpolates the master raw, and always has. That is a COMMAND argument,
    where scrubbing would hand `pdngen` a cell name the design does not
    contain — a silent wrong grid, which is worse than a syntax error. It is
    unchanged by this fix and left as its own problem."""
    tcl = _pdn(tmp_path, _hostile_macro(), tag="hr")
    assert "PDN_INSERTED_ADAPTIVE" in tcl
    for line in _diagnostic_puts(tcl):
        assert _is_one_tcl_literal(line), line


# ═══════════════════════════════════════════════════════════════════════════
# REPORTED, NOT BLOCKING — and the argument for it, kept next to the code
# ═══════════════════════════════════════════════════════════════════════════
def test_no_reachable_path_returns_no_grid_with_no_explanation():
    """COVERAGE CONTROL, and coupled to this implementation on purpose.

    The defect was ONE `return None` with no reason. There were seven of them,
    and six were silent for the same reason the seventh was. This walks every
    exit of the planner and asserts the invariant that replaced them: once a
    hard-macro POWER/GROUND port has been seen, "no grid" is never the whole
    answer. A branch added later that returns no plan and no reason fails here.

    The one exemption is stated explicitly, not left implicit: a block with no
    PG port at all asked for nothing, so nothing is the complete answer."""
    tech = _stack()
    stripes = [{"layer": "M4", "width": 0.8, "pitch": 20, "offset": 0},
               {"layer": "M5", "width": 0.8, "pitch": 20, "offset": 0}]

    def plan_for(lefs, t=tech, st=stripes):
        return mod._macro_pdn_grid_outcome(lefs, t, st, "M1")

    # (label, args) -> every distinct exit the planner has
    exits = {
        "no routing layers":     ([_macro()], "not a lef", stripes),
        "pin layer not routing": ([_macro().replace("LAYER M3", "LAYER NOPE")],
                                  tech, stripes),
        "pins above every strap": ([_macro().replace("LAYER M3", "LAYER M6")],
                                   tech, stripes),
        "all candidates blocked": ([_macro(obs_layers=("M4", "M5"))], tech,
                                   stripes),
        "no perpendicular partner": ([_macro()], tech, [stripes[0]]),
        "strap width unusable":  ([_macro()], tech,
                                  [{"layer": "M4", "width": 0, "pitch": 20,
                                    "offset": 0}, stripes[1]]),
        "no port wide enough":   ([SLIVER_MACRO], tech, stripes),
    }
    reasons = set()
    for label, args in exits.items():
        got = plan_for(*args)
        assert got["plan"] is None, label
        assert got["refusals"], f"{label}: no grid AND no reason — the defect"
        for rec in got["refusals"]:
            assert rec["masters"], f"{label}: refused without naming a macro"
            assert rec["reason"].strip(), f"{label}: no machine token"
            assert rec["detail"].strip(), f"{label}: no sentence for a human"
            reasons.add(rec["reason"])
    # every exit has its OWN token: one token for seven causes is the same
    # collapse this issue is about, moved down a level
    assert len(reasons) == len(exits), sorted(reasons)

    # the exemption, and the success path, both still hold
    assert plan_for([SIGNAL_ONLY_MACRO]) == {"plan": None, "refusals": []}
    built = plan_for([_macro()])
    assert built["plan"] is not None and built["refusals"] == []


def test_a_multi_macro_refusal_over_names_rather_than_under_names(tmp_path):
    """MEASURED LIMITATION, pinned so it is a known state and not a surprise.

    The planner has always built ONE plan for all macro LEFs together: the OBS
    reader merges every master's blocked layers into a single candidate filter
    (#685). So one macro that blocks every candidate takes the macro grid away
    from a second, unblocked macro too — which was ALSO silent before this fix,
    and is the same defect wearing a second hat.

    The refusal therefore names every master with a supply port, not only the
    one whose OBS caused it. That over-names rather than under-names, which is
    the conservative direction for a report: a reader is pointed at a macro that
    turns out to be fine, rather than not told about one that is not.

    Narrowing it means per-macro plans — a different change, with its own
    blast radius, and not one to smuggle in behind a reporting fix."""
    two = _macro(obs_layers=("M4", "M5")) + SIGNAL_ONLY_MACRO.replace(
        "USE SIGNAL", "USE POWER").replace(
        "RECT 0 0 1 1", "RECT 0 0 12 12").replace("SIZE 10 BY 10", "SIZE 400 BY 140")
    tcl = _pdn(tmp_path, two, tag="mm")
    got = mod._parse_macro_pdn_grid_refusals(tcl)
    named = {r["master"] for r in got}
    assert MACRO_NAME in named, "the macro that caused it must be named"
    # Round 15: the per-pin STUB planner reads each master's OWN OBS, so the
    # second macro no longer loses its supply to the first one's blockage —
    # it gets a stub grid, and the refusal names only the macro whose own OBS
    # blocks every layer above its pins. This is the "narrowing" the docstring
    # above deferred; the pattern planner itself is unchanged.
    assert "SIGBLOCK" not in named, (
        "the unblocked macro is reached by a stub and must not be refused")
    assert "MACRO_SUPPLY_STUBS:" in tcl
    assert "define_pdn_grid -macro" in tcl


def test_the_refusal_is_reported_and_does_not_fail_the_run():
    """DELIBERATE. This planner reads `pdk.macro_lefs` — a CONFIG list — and
    never the netlist or the placement, so it cannot tell whether the master is
    instantiated at all, nor whether the supply arrives by a construct it does
    not model (a ring, a pre-routed abstract). Failing the run from that would
    manufacture a stop out of configuration. What blocks is the DEF-geometry
    verdict and the tool's own connectivity check, both of which read the real
    layout; this marker is what lets them be traced back to a named macro."""
    import inspect
    src = inspect.getsource(mod)
    assert "REPORTED, NOT BLOCKING here" in src
    # never wired into a verdict-bearing finding
    assert 'finding": "MACRO_PDN_GRID_REFUSED' not in src
    assert '"MACRO_PDN_GRID_REFUSED"' not in src.replace(
        '"MACRO_PDN_GRID_REFUSED: ', "")
