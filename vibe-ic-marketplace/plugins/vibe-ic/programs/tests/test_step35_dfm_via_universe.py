"""Step 35 — the DFM screen's via universe is what routing REFERENCES.

MEASURED DEFECT (a real converged OpenROAD run, ihp-sg13g2):
`routed.def` declares 6 VIARULE array vias in its VIAS section — all of them
used by SPECIALNETS power straps — while the signal NETS section references
`Via1_XY` x461, `Via1_YY` x797, `Via2_YX` x969, `Via3_XY` x13 = 2240 uses of
the ROUTER'S DEFAULT vias, which are FIXED VIAs defined in the tech LEF and
declared NOWHERE in the DEF.

The screen built its via universe from the VIAS section alone and then counted
uses of only those names, so it reported

    via_redundancy = {via_defs: 6, multi_cut_defs: 5, signal_via_uses: 0,
                      single_cut_uses: 0, single_cut_fraction: null}
    findings = [DENSITY_REF, LITHO_MIN_WIDTH_OWNERSHIP]     # no via finding
    verdict  = PASS

— a *structurally unreachable* measurement, not a wrong one: on that class of
DEF the redundant-via screen could never say anything, and its silence was
indistinguishable from a clean result.

The fix derives the universe from the DEF regularWiring grammar and resolves
cut counts per referenced name (DEF VIAS → tech LEF → UNRESOLVED). An
unresolved name is DISCLOSED, never assumed single-cut: inferring a cut count
from an absent declaration would be a fabricated measurement, which is the
exact failure class this campaign exists to remove.

chip-AGNOSTIC: DEF/LEF structure fixtures only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dfm_screen_check as DFM  # noqa: E402


# The measured shape: a VIAS section holding only power-strap array vias, and
# signal routing that references the router's LEF-defined default vias.
_ROUTER_DEFAULT_DEF = """\
VERSION 5.8 ;
DESIGN top ;
VIAS 1 ;
    - via1_2_2200_440_1_5_410_410 + VIARULE via1Array + CUTSIZE 190 190 \
+ ROWCOL 1 5  ;
END VIAS
NETS 3 ;
    - _000_ ( _530_ D ) ( _291_ Y ) + USE SIGNAL
      + ROUTED Metal2 ( 130560 178500 ) ( * 178920 )
      NEW Metal1 ( 130560 178920 ) Via1_YY
      NEW Metal1 ( 129120 178500 ) Via1_YY ;
    - _001_ ( _529_ D ) ( _296_ Y ) + USE SIGNAL
      + ROUTED Metal3 ( 87840 176400 ) ( 96000 * )
      NEW Metal1 ( 87840 176400 ) Via1_YY
      NEW Metal2 ( 87840 176400 ) Via2_YX
      NEW Metal2 ( 87840 176400 ) RECT ( -100 -570 100 0 )  ;
    - _002_ ( _528_ D ) ( _301_ Y ) + USE SIGNAL
      + ROUTED Metal2 ( 18720 164640 ) ( * 165480 )
      NEW Metal1 ( 18720 164640 ) Via2_YX ;
END NETS
SPECIALNETS 1 ;
    - VDD ( * VDD ) + USE POWER
      + ROUTED Metal1 ( 0 0 ) ( 100 0 ) via1_2_2200_440_1_5_410_410 ;
END SPECIALNETS
"""

# A tech LEF that DOES define those router vias: Via1_YY single-cut,
# Via2_YX dual-cut.
_TECH_LEF = """\
LAYER Metal1
  TYPE ROUTING ;
END Metal1
LAYER Via1
  TYPE CUT ;
END Via1
LAYER Metal2
  TYPE ROUTING ;
END Metal2
VIA Via1_YY DEFAULT
  LAYER Metal1 ;
    RECT -0.15 -0.15 0.15 0.15 ;
  LAYER Via1 ;
    RECT -0.095 -0.095 0.095 0.095 ;
  LAYER Metal2 ;
    RECT -0.15 -0.15 0.15 0.15 ;
END Via1_YY
VIA Via2_YX DEFAULT
  LAYER Metal1 ;
    RECT -0.3 -0.15 0.3 0.15 ;
  LAYER Via1 ;
    RECT -0.285 -0.095 -0.095 0.095 ;
    RECT 0.095 -0.095 0.285 0.095 ;
  LAYER Metal2 ;
    RECT -0.3 -0.15 0.3 0.15 ;
END Via2_YX
"""


def _proj(tmp_path, def_text=_ROUTER_DEFAULT_DEF):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(def_text)
    return tmp_path


def _cats(rep):
    return {f["category"] for f in rep["findings"]}


# ── the vacuum itself ────────────────────────────────────────────────────────

def test_router_default_vias_are_counted_even_when_the_def_declares_none():
    """3 Via1_YY + 2 Via2_YX = 5 signal-net via uses, none of them declared."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = _proj(Path(td))
        rep = DFM.audit(p)
    vr = rep["via_redundancy"]
    assert vr["signal_via_uses"] == 5, (
        "the via universe must come from what routing REFERENCES; counting "
        "only DECLARED vias made this 0 on a DEF holding 2240 real uses")
    assert vr["via_defs"] == 1 and vr["multi_cut_defs"] == 1, \
        "the DEF-declared counts must keep their existing meaning"


def test_unresolved_via_uses_are_disclosed_by_name(tmp_path):
    rep = DFM.audit(_proj(tmp_path))
    vr = rep["via_redundancy"]
    assert vr["unresolved_via_uses"] == 5
    assert vr["resolved_via_uses"] == 0
    assert vr["unresolved_via_names"] == ["Via1_YY", "Via2_YX"]
    assert "VIA_CUTS_UNRESOLVED" in _cats(rep), \
        "an unmeasurable via universe must be NAMED, not silent"
    fnd = next(f for f in rep["findings"]
               if f["category"] == "VIA_CUTS_UNRESOLVED")
    assert fnd["severity"] == "WARNING"
    assert "Via1_YY" in fnd["message"] and "Via2_YX" in fnd["message"]


def test_unresolved_via_is_never_assumed_single_cut(tmp_path):
    """ANTI-FABRICATION. 'Undeclared therefore single-cut' would hand the
    screen a 100% single-cut fraction it never measured."""
    rep = DFM.audit(_proj(tmp_path))
    vr = rep["via_redundancy"]
    # The `signal_via_uses` clause is load-bearing: without it this assertion
    # also holds on the broken tree, where the fraction is None only because
    # the universe was empty. What must hold is "5 uses seen, 0 of them
    # classified" — seen, and honestly unmeasured.
    assert vr["signal_via_uses"] == 5
    assert vr["single_cut_uses"] == 0
    assert vr["single_cut_fraction"] is None
    assert "VIA_REDUNDANCY_LOW" not in _cats(rep)
    assert "VIA_REDUNDANCY_OK" not in _cats(rep), \
        "a fraction computed over zero resolved uses is not a clean result"


def test_the_silent_vacuum_cannot_return(tmp_path):
    """The one-line invariant: never report zero uses on a DEF with them."""
    rep = DFM.audit(_proj(tmp_path))
    vr = rep["via_redundancy"]
    assert not (vr["signal_via_uses"] == 0
                and "Via1_YY" in _ROUTER_DEFAULT_DEF)


# ── resolution from the tech LEF ─────────────────────────────────────────────

def test_tech_lef_in_the_project_resolves_router_via_cut_counts(tmp_path):
    p = _proj(tmp_path)
    lef = p / "input" / "pdk" / "lef"
    lef.mkdir(parents=True)
    (lef / "tech.lef").write_text(_TECH_LEF)
    rep = DFM.audit(p)
    vr = rep["via_redundancy"]
    assert vr["resolved_via_uses"] == 5 and vr["unresolved_via_uses"] == 0
    # Via1_YY (1 cut) x3 single, Via2_YX (2 cuts) x2 multi -> 3/5 = 60%
    assert vr["single_cut_uses"] == 3
    assert vr["single_cut_fraction"] == 0.6
    assert "VIA_CUTS_UNRESOLVED" not in _cats(rep)
    assert "VIA_REDUNDANCY_OK" in _cats(rep)
    assert any(s.endswith("tech.lef") for s in vr["cut_count_sources"])


def test_lef_read_by_the_router_is_used_when_it_still_exists(tmp_path):
    """The run's own pnr.tcl records the exact LEFs the router read. When one
    is still on this filesystem it is the authoritative cut-count source."""
    p = _proj(tmp_path)
    elsewhere = tmp_path / "outside_the_project"
    elsewhere.mkdir()
    (elsewhere / "sg13g2_tech.lef").write_text(_TECH_LEF)
    (p / "phase3" / "stage3" / "pnr" / "pnr.tcl").write_text(
        f"read_lef {elsewhere / 'sg13g2_tech.lef'}\n")
    vr = DFM.audit(p)["via_redundancy"]
    assert vr["resolved_via_uses"] == 5 and vr["single_cut_uses"] == 3


def test_unreachable_lef_path_stays_unresolved_not_guessed(tmp_path):
    """DIRECTION-1 GUARD, and the real run's actual situation: the tech LEF
    lives inside a container image. An unreachable path must leave the uses
    UNRESOLVED — it must never be treated as 'therefore single-cut'."""
    p = _proj(tmp_path)
    (p / "phase3" / "stage3" / "pnr" / "pnr.tcl").write_text(
        "read_lef /foss/pdks/ihp-sg13g2/libs.ref/nope/sg13g2_tech.lef\n")
    vr = DFM.audit(p)["via_redundancy"]
    assert vr["unresolved_via_uses"] == 5
    assert vr["single_cut_fraction"] is None


def test_a_lef_with_no_cut_layer_declaration_resolves_nothing(tmp_path):
    """Which shapes are CUTs is only knowable from `TYPE CUT`. Without it the
    honest answer is UNRESOLVED, not a shape count."""
    p = _proj(tmp_path)
    lef = p / "input" / "pdk" / "lef"
    lef.mkdir(parents=True)
    (lef / "tech.lef").write_text(
        _TECH_LEF.replace("  TYPE CUT ;", "  TYPE ROUTING ;"))
    assert DFM.audit(p)["via_redundancy"]["unresolved_via_uses"] == 5


# ── the extractor keys on grammar, not on tokens ─────────────────────────────

def test_a_net_named_like_a_via_is_not_counted_as_a_via_use(tmp_path):
    """The old counter did a bare substring scan of the NETS body, so a NET
    whose name matched a declared via inflated the use count. Keying on the
    routing grammar (`)` -> viaName) is what keeps net and instance names
    out."""
    body = """\
VERSION 5.8 ;
DESIGN top ;
VIAS 1 ;
- via_dual + VIARULE vr + ROWCOL 1 2 ;
END VIAS
NETS 2 ;
- via_dual ( u1 A ) ( u2 B ) + USE SIGNAL ;
- n2 ( u3 C ) + ROUTED met1 ( 0 0 ) via_dual ;
END NETS
"""
    p = _proj(tmp_path, body)
    vr = DFM.audit(p)["via_redundancy"]
    assert vr["signal_via_uses"] == 1, \
        "the net named `via_dual` is not a via use"
    assert vr["resolved_via_uses"] == 1 and vr["single_cut_uses"] == 0


def test_rect_and_new_keywords_are_not_via_names(tmp_path):
    uses = DFM._via_uses_from_nets(_ROUTER_DEFAULT_DEF)
    assert set(uses) == {"Via1_YY", "Via2_YX"}
    assert uses == {"Via1_YY": 3, "Via2_YX": 2}


def test_masked_via_reference_is_counted(tmp_path):
    """DEF 5.8 allows `[ MASK viaMaskNum ] viaName` after a routing point."""
    body = _ROUTER_DEFAULT_DEF.replace(
        "NEW Metal1 ( 130560 178920 ) Via1_YY",
        "NEW Metal1 ( 130560 178920 ) MASK 2 Via1_YY")
    assert DFM._via_uses_from_nets(body)["Via1_YY"] == 3


def test_specialnets_power_vias_are_not_signal_uses(tmp_path):
    """SCOPE GUARD (exercises the new extractor, so it cannot run on the base
    tree): the screen is scoped to SIGNAL-net redundancy, exactly as before.
    Power-strap array vias in SPECIALNETS must stay out of the count."""
    uses = DFM._via_uses_from_nets(_ROUTER_DEFAULT_DEF)
    assert "via1_2_2200_440_1_5_410_410" not in uses


# ── honest skips preserved ───────────────────────────────────────────────────

def test_def_with_neither_declarations_nor_references_is_an_honest_skip(
        tmp_path):
    """DIRECTION-1 GUARD: the VIA_DEFS_NOT_FOUND disclosure must survive."""
    p = _proj(tmp_path, "VERSION 5.8 ;\nDESIGN top ;\nNETS 0 ;\nEND NETS\n")
    rep = DFM.audit(p)
    assert rep["via_redundancy"] is None
    assert "VIA_DEFS_NOT_FOUND" in _cats(rep)
    assert rep["verdict"] == "PASS" and rep["rc"] == 0


def test_declared_vias_with_no_signal_use_are_disclosed_not_silent(tmp_path):
    body = """\
VERSION 5.8 ;
DESIGN top ;
VIAS 1 ;
- via_dual + VIARULE vr + ROWCOL 1 2 ;
END VIAS
NETS 1 ;
- n1 ( u1 A ) + ROUTED met1 ( 0 0 ) ( 10 0 ) ;
END NETS
"""
    rep = DFM.audit(_proj(tmp_path, body))
    assert "VIA_USES_NOT_FOUND" in _cats(rep)
    assert rep["via_redundancy"] is None


def test_no_routed_def_is_still_a_vacuous_skip(tmp_path):
    """DIRECTION-1 GUARD: rc 2 (VACUOUS_PASS at the flow gate) is untouched."""
    assert DFM.audit(tmp_path)["rc"] == 2


# ── the tier the exit code now carries ───────────────────────────────────────

def test_unresolved_universe_reaches_the_advisory_tier(tmp_path):
    """The two halves of this fix meet here: a via universe that cannot be
    measured is a WARNING, a WARNING is PASS_WITH_ADVISORIES, and
    PASS_WITH_ADVISORIES now has its own exit code so the flow gate can see
    it."""
    rep = DFM.audit(_proj(tmp_path))
    assert rep["verdict"] == "PASS_WITH_ADVISORIES"
    assert rep["rc"] == 1


def test_advisory_trailer_is_printed_last_and_names_the_finding(
        tmp_path, capsys):
    """`flow_compliance_check` keeps only the LAST 300 chars of stdout as the
    gate's reason snippet. Without a trailer the ADVISORY step line showed a
    fragment of the JSON body — recorded but unreadable."""
    p = _proj(tmp_path)
    assert DFM.main([str(p)]) == 1
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines[-1].startswith("dfm_screen_check: PASS_WITH_ADVISORIES")
    assert "VIA_CUTS_UNRESOLVED" in lines[-1]
    assert len(lines[-1]) < 300
    assert json.loads(
        (p / "reports" / "phase3" / "dfm_screen.json").read_text()
    )["verdict"] == "PASS_WITH_ADVISORIES"
