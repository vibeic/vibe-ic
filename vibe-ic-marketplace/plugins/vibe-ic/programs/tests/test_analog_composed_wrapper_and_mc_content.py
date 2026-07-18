"""GAP-ANALOG — composed ngspice corner wrapper + MC-lib ranking by verified
statistical content. Two chip-AGNOSTIC selection-layer fixes exercised with
SYNTHETIC PDK families only — NO NDA / vendor / SKU / foundry token anywhere.

GAP A (analog_pdk_deck_context.custom_family_context): when a PDK ships BOTH a
  COMPOSED corner-wrapper lib (a lib whose corner section pulls in the
  prerequisite blocks + device model section as a unit) AND a bare raw device
  lib, the deck context PREFERS the composed wrapper for ngspice. The raw lib
  DEFINES the device subckts (wins the #149 device-defining signal) but a bare
  `.lib <raw-lib> <corner>` skips the prerequisites the ngspice bridge needs and
  errors — the wrapper composes them. Detected STRUCTURALLY (a `.lib <section>`
  block that itself include-forms other sections), never by a PDK-name.

GAP B (analog_pdk_availability.resolve_pdk + analog_mc_yield_run):
  * mc_libs are ranked by PARSE-VERIFIED statistical content — a lib actually
    carrying agauss/gauss/mc_global cards outranks a pure name-hinted alias with
    none — never by filename order (an alphabetical mc_libs[0] can be the alias).
  * _pick_native_mc_section loads BOTH the GLOBAL MC-enable block (mc_global)
    AND the per-device MISMATCH block(s) (mc_mos_tn) — the global block alone
    resamples nothing (sigma≈0).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_availability as APA         # noqa: E402
import analog_pdk_deck_context as APDC        # noqa: E402
import analog_mc_yield_run as MC              # noqa: E402
import analog_real_corner_sweep as ARS        # noqa: E402


# ── synthetic composed-wrapper + raw device libs (NO NDA content) ────────────

def _composed_shim_text(raw_name="foo_raw.lib") -> str:
    """A composed corner wrapper: each `.lib <corner>_lv` section include-forms
    the prerequisite blocks + the raw device section (structurally a wrapper)."""
    out = ["* foo synthetic ngspice shim — composed corner wrapper (NO NDA)"]
    for corner in ("ss", "tt", "ff"):
        out += [
            f".lib {corner}_lv",
            f'.lib "{raw_name}" noiseflag',
            ".temp 27",
            f'.lib "{raw_name}" {corner}',
            ".endl",
        ]
    return "\n".join(out) + "\n"


def _raw_device_text() -> str:
    """A bare raw device lib: `.lib <section>` DEFINITIONS carrying the device
    subckts, but NO include forms (not a wrapper)."""
    out = ["* foo synthetic raw device lib (NO NDA content)",
           ".lib noiseflag", ".param nflag=0", ".endl"]
    for corner in ("ss", "tt", "ff"):
        out += [
            f".lib {corner}",
            ".subckt foo_nch d g s b w=1 l=1", ".ends",
            ".subckt foo_pch d g s b w=1 l=1", ".ends",
            ".endl",
        ]
    return "\n".join(out) + "\n"


def _two_lib_res(shim: str, raw: str):
    return {"available": True, "source": "project_custom_pdk",
            "family": "synthfab", "spice_libs": [shim, raw]}


# ══ GAP A — composed wrapper preferred over raw device lib ═══════════════════

def test_wrapper_detector_is_structural():
    assert APDC._lib_is_composed_wrapper(_composed_shim_text()) is True
    # a bare raw device lib DEFINES sections but never include-forms them
    assert APDC._lib_is_composed_wrapper(_raw_device_text()) is False
    # consecutive single-arg `.lib <section>` DEFINITION lines are NOT a wrapper
    assert APDC._lib_is_composed_wrapper(".lib tt\n.lib ss\n.lib ff\n") is False


def test_gapA_composed_wrapper_is_primary_over_raw():
    shim = "/stage/pdk/spice/foo_ngspice_shim.lib"
    raw = "/stage/pdk/spice/foo_raw.lib"
    texts = {shim: _composed_shim_text(), raw: _raw_device_text()}
    ctx = APDC.custom_family_context(_two_lib_res(shim, raw),
                                     reader=lambda p: texts.get(p))
    assert ctx.status == "OK"
    # the COMPOSED wrapper is the deck's model lib even though the RAW lib is the
    # device-defining one (it wins the #149 signal) — the wrapper composes it.
    assert ctx.model_lib == shim
    # device roles still resolve from the UNION (the raw lib's subckts)
    assert ctx.device_map == {"nmos": "foo_nch", "pmos": "foo_pch"}
    # the wrapper's own `<corner>_lv` sections drive the corner grid
    assert ctx.typ_section == "tt_lv"
    assert [c[0] for c in ctx.process_corners] == ["ss_lv", "tt_lv", "ff_lv"]


def test_gapA_reversed_order_still_picks_wrapper():
    """Order-independent: the wrapper wins regardless of spice_libs order."""
    shim = "/stage/pdk/spice/foo_ngspice_shim.lib"
    raw = "/stage/pdk/spice/foo_raw.lib"
    texts = {shim: _composed_shim_text(), raw: _raw_device_text()}
    ctx = APDC.custom_family_context(_two_lib_res(raw, shim),   # raw first
                                     reader=lambda p: texts.get(p))
    assert ctx.model_lib == shim


def test_gapA_no_leak_bare_only_pdk_unchanged():
    """No-leak: a PDK that ships ONLY bare libs (no wrapper) still picks the bare
    device-defining lib exactly as before — sky130-style behaviour preserved."""
    raw = "/stage/pdk/spice/foo_raw.lib"
    ctx = APDC.custom_family_context(
        {"available": True, "source": "project_custom_pdk", "family": "synthfab",
         "spice_libs": [raw]},
        reader=lambda p: _raw_device_text())
    assert ctx.status == "OK"
    assert ctx.model_lib == raw
    assert ctx.device_map == {"nmos": "foo_nch", "pmos": "foo_pch"}


def test_gapA_end_to_end_via_resolver(tmp_path):
    """Full chain: stage BOTH libs on disk → APA.resolve_pdk (rung 1) →
    resolve_deck_context reads them locally → the composed wrapper is primary."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "foo_ngspice_shim.lib").write_text(_composed_shim_text())
    (sp / "foo_raw.lib").write_text(_raw_device_text())
    res = APA.resolve_pdk("SynthFab 180 (custom)", project=str(tmp_path))
    assert res["available"] and res["source"] == "project_custom_pdk"
    ctx = APDC.resolve_deck_context("sky130", res=res)   # local reader
    assert ctx.status == "OK"
    assert ctx.model_lib.endswith("foo_ngspice_shim.lib")
    assert ctx.device_map["nmos"] == "foo_nch"
    assert ctx.device_map["pmos"] == "foo_pch"


# ══ GAP B1 — mc_libs ranked by verified statistical content ══════════════════

_ALIAS_LIB = ".lib mc_alias\n* alias / wrapper only — no statistical cards\n.endl\n"
_REAL_MC_LIB = (
    ".lib mc_global\n.param mc_g = agauss(0, 1, 3)\n.endl\n"
    ".lib mc_mos_tn\n.subckt zzz_nch d g s b\n"
    ".param vth = agauss(0.5, 0.02, 3)\n.ends\n.endl\n"
)


def test_statistical_card_count():
    assert APA._statistical_card_count.__doc__  # exists
    # counts agauss (x2) + mc_global (x1); no double-count of gauss inside agauss
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".lib", delete=False) as fh:
        fh.write(_REAL_MC_LIB)
        real = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".lib", delete=False) as fh:
        fh.write(_ALIAS_LIB)
        alias = fh.name
    assert APA._statistical_card_count(real) == 3
    assert APA._statistical_card_count(alias) == 0
    assert APA._statistical_card_count("/no/such/file.lib") == 0


def test_gapB1_resolve_ranks_real_agauss_lib_first(tmp_path):
    """The alias sorts alphabetically BEFORE the real lib, so the pre-fix
    filename-order pick returned the alias (no spread → UNSCOREABLE). The fix
    ranks by verified statistical content: the real-agauss lib is mc_libs[0]."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "synthfab_models.lib").write_text(
        ".lib tt\n.subckt nch d g s b\n.ends\n.endl\n")
    (sp / "aaa_mc_alias.lib").write_text(_ALIAS_LIB)     # name-hint, 0 cards
    (sp / "zzz_mc.lib").write_text(_REAL_MC_LIB)         # name-hint, 3 cards
    r = APA.resolve_pdk("SynthFab 180", project=str(tmp_path))
    assert r["available"] and r["tech_present"]["mc"] is True
    names = [Path(m).name for m in r["mc_libs"]]
    assert set(names) == {"aaa_mc_alias.lib", "zzz_mc.lib"}
    # verified-content wins over the alphabetical alias
    assert names[0] == "zzz_mc.lib"
    # the deterministic models lib is NOT an MC lib
    assert not any("synthfab_models" in m for m in r["mc_libs"])


def test_gapB1_self_contained_beats_higher_card_overlay(tmp_path):
    """A SELF-CONTAINED stat lib (cards + device `.subckt` defs) outranks a pure
    param-OVERLAY lib that has MORE cards but defines NO devices — the MC-run
    layer wraps ONE model file, and only the self-contained lib resamples the
    device standalone (the overlay's devices live in a separate base lib)."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    # overlay: many agauss cards, NO device subckt (needs a separate base lib)
    (sp / "aaa_mc_overlay.lib").write_text(
        ".lib mc_h\n" + "".join(f".param p{i} = agauss(0,1,3)\n" for i in range(9))
        + ".endl\n")
    # self-contained: fewer cards, but DEFINES the device it resamples
    (sp / "zzz_mc_selfcontained.lib").write_text(
        ".lib mc_global\n.param g = agauss(0,1,3)\n.endl\n"
        ".lib mc_mos_tn\n.subckt nch d g s b\n.param v = agauss(0.5,0.02,3)\n"
        ".ends\n.endl\n")
    r = APA.resolve_pdk("SynthFab 180", project=str(tmp_path))
    names = [Path(m).name for m in r["mc_libs"]]
    # self-contained wins despite FEWER cards (9 overlay cards vs 2)
    assert names[0] == "zzz_mc_selfcontained.lib"


# ══ GAP B2 — _pick_native_mc_section loads global + device sections ══════════

def test_gapB2_picks_global_and_device_sections(tmp_path):
    lib = tmp_path / "zzz_mc.lib"
    lib.write_text(_REAL_MC_LIB)
    secs = MC._pick_native_mc_section(str(lib))
    # BOTH the global MC-enable block AND the device mismatch block, global first
    assert secs == ["mc_global", "mc_mos_tn"]


def test_gapB2_device_only_lib_still_returns_it(tmp_path):
    lib = tmp_path / "mm.lib"
    lib.write_text(".lib mc_mm\n.subckt nch d g s b\n.ends\n.endl\n")
    assert MC._pick_native_mc_section(str(lib)) == ["mc_mm"]


def test_gapB2_no_sections_returns_empty(tmp_path):
    lib = tmp_path / "flat.lib"
    lib.write_text("* just a flat model file, no `.lib` sections\n.model n nmos\n")
    assert MC._pick_native_mc_section(str(lib)) == []


def test_gapB2_device_tag_selects_matching_section(tmp_path):
    """With the deck's device family tag, ONLY the matching MOS mismatch block is
    loaded (global + mc_mos_<tag>) — NOT every mc_* variant (over-loading pulls
    in undefined per-corner params / HSPICE idioms → ngspice errors)."""
    lib = tmp_path / "multi.lib"
    lib.write_text(
        ".lib mc_global\n.param g = agauss(0,1,3)\n.endl\n"
        ".lib mc_global_local\n.param gl = agauss(0,1,3)\n.endl\n"
        ".lib mc_mos_tn\n.param a = agauss(0,1,3)\n.endl\n"
        ".lib mc_mos_tn_na\n.param an = agauss(0,1,3)\n.endl\n"
        ".lib mc_mos_ff\n.param b = agauss(0,1,3)\n.endl\n"
        ".lib mc_mosdh_tn\n.param c = agauss(0,1,3)\n.endl\n")
    # device family {devn_tn, devp_tn} → tag 'tn' → only mc_global + mc_mos_tn
    secs = MC._pick_native_mc_section(str(lib), dev_names={"devn_tn", "devp_tn"})
    assert secs == ["mc_global", "mc_mos_tn"]
    # the `mc_global_local` variant, `mc_mos_tn_na`/`mc_mosdh_tn`/`mc_mos_ff`
    # are NOT loaded (wrong role / wrong corner / not a plain mc_mos block)
    assert "mc_global_local" not in secs
    assert "mc_mos_ff" not in secs
    assert "mc_mosdh_tn" not in secs


def test_device_family_tag_helper():
    assert MC._device_family_tag({"devn_tn", "devp_tn"}) == "tn"
    assert MC._device_family_tag({"nfet_tt", "pfet_tt"}) == "tt"
    # no single common tail → None (fallback to conservative single-section)
    assert MC._device_family_tag({"devn_tn", "devp_ff"}) is None
    assert MC._device_family_tag(None) is None


# ── the single-model-family guard admits multi-section-same-file + the same-PDK
#    passive companion, rejects an out-of-set (foreign) file

def test_guard_allows_multi_section_same_file():
    wrap = (".lib /stage/pdk/spice/zzz_mc.lib mc_global\n"
            ".lib /stage/pdk/spice/zzz_mc.lib mc_mos_tn\n"
            "xmn out g 0 0 nch\n.control\nop\n.endc\n.end\n")
    # two `.lib` lines but ONE (allowed) model file → allowed
    MC._assert_single_model_family(wrap, {"/stage/pdk/spice/zzz_mc.lib"})


def test_guard_allows_passive_companion_file():
    """The MC lib PLUS the same-PDK passive companion (well-diode) are both in
    the allowed set → allowed (not a cross-family overlay)."""
    wrap = (".lib /stage/pdk/spice/zzz_mc.lib mc_global\n"
            ".lib /stage/pdk/spice/zzz_mc.lib mc_mos_tn\n"
            ".lib /stage/pdk/spice/shim.lib ttt_passive\n"
            "xmp out g vdd vdd vdd pch\n.end\n")
    MC._assert_single_model_family(
        wrap, {"/stage/pdk/spice/zzz_mc.lib", "/stage/pdk/spice/shim.lib"})


def test_guard_rejects_out_of_set_file():
    wrap = (".lib /stage/pdk/spice/zzz_mc.lib mc_global\n"
            ".lib /other/pdk/spice/second.lib tt\n"
            "xmn out g 0 0 nch\n.end\n")
    with pytest.raises(AssertionError):
        MC._assert_single_model_family(wrap, {"/stage/pdk/spice/zzz_mc.lib"})


# ══ GAP B2 end-to-end — native MC deck composes global+device from ONE file ══

def _native_mc_project(tmp_path: Path) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"fields": {"pdk_target": "synthfab180"}}))
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "synthfab_models.lib").write_text(
        ".lib tt\n.subckt nch d g s b\n.ends\n.endl\n")
    (sp / "synthfab_mc.lib").write_text(_REAL_MC_LIB)   # mc_global + mc_mos_tn
    blk = tmp_path / "phase2" / "analog" / "ldo"
    blk.mkdir(parents=True)
    (blk / "ldo.sp").write_text(
        ".lib /stage/pdk/spice/synthfab_models.lib tt\n"
        "* runnable native deck\n.meas dc vout FIND v(out) AT=1u\n.end\n")
    spec = tmp_path / "phase1" / "analog" / "ldo"
    spec.mkdir(parents=True)
    (spec / "spec.json").write_text(json.dumps(
        {"specs": [{"name": "vout", "min": 1.7, "max": 1.9}]}))
    return tmp_path


def _fake_ngspice(values):
    it = iter(values)
    def fake(container, sp, cwd=None):
        v = next(it)
        return True, {"vout": v}, f"vout = {v}\n"
    return fake


def test_gapB2_native_mc_deck_composes_global_and_device(tmp_path, monkeypatch):
    p = _native_mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    monkeypatch.setattr(ARS, "_run_ngspice",
                        _fake_ngspice([1.78, 1.80, 1.82, 1.84, 1.86,
                                       1.88, 1.79, 1.81, 1.83, 1.85]))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    MC.run_block(p, "ldo", "x", "sky130", 10)
    decks = sorted((p / "phase2/analog/ldo/mc_runs").glob("mc_*.sp"))
    assert decks
    for d in decks:
        t = d.read_text()
        # BOTH sections of the native mc lib are composed
        assert "synthfab_mc.lib mc_global" in t
        assert "synthfab_mc.lib mc_mos_tn" in t
        assert "sky130" not in t.lower()             # NO cross-family overlay
        assert "synthfab_models.lib" not in t        # native corner stripped
        # structurally single-FAMILY: exactly one distinct model file
        paths = set()
        for m in MC._INCLUDE_FORM_MODEL_PATH_RE.finditer(t):
            paths.add(m.group(1) or m.group(2))
        assert len(paths) == 1


# ══ multi-terminal device + LV/passive split (bench-adc recipe (b)) ═══════════

def _shim_lv_passive_text(raw="foo_raw.lib") -> str:
    """A composed shim with a LV corner + a PASSIVE companion section (each
    include-forms the raw lib), the general shape of a commercial ngspice shim."""
    return (f".lib ttt_lv\n.lib \"{raw}\" noiseflag\n.lib \"{raw}\" tt\n.endl\n"
            f".lib ttt_passive\n.lib \"{raw}\" passive\n.endl\n")


def _raw_5term_pmos_text() -> str:
    """Raw device lib: 4-terminal NMOS, 5-terminal PMOS (d g s b + well), and a
    passive well-diode subckt in the passive section."""
    return (".lib noiseflag\n.param nf=0\n.endl\n"
            ".lib tt\n.subckt foo_nch d g s b w=1 l=1\n.ends\n"
            ".subckt foo_pch d g s b nw w=1 l=1\n.ends\n.endl\n"
            ".lib passive\n.subckt foo_welldio a c\n.ends\n.endl\n")


def test_deck_context_resolves_terminals_and_passive():
    shim = "/stage/pdk/spice/foo_ngspice_shim.lib"
    raw = "/stage/pdk/spice/foo_raw.lib"
    texts = {shim: _shim_lv_passive_text(), raw: _raw_5term_pmos_text()}
    ctx = APDC.custom_family_context(
        {"available": True, "source": "project_custom_pdk", "family": "synthfab",
         "spice_libs": [shim, raw]}, reader=lambda p: texts.get(p))
    assert ctx.status == "OK"
    assert ctx.model_lib == shim                       # composed shim primary
    assert ctx.device_map == {"nmos": "foo_nch", "pmos": "foo_pch"}
    # 4-terminal NMOS, 5-terminal PMOS captured
    assert ctx.device_terms == {"nmos": 4, "pmos": 5}
    # the LV corner is paired with its passive companion
    assert ctx.passive_sections.get("ttt_lv") == "ttt_passive"


def test_render_deck_pads_multiterminal_pmos_and_pairs_passive():
    deck, _ = ARS.render_deck(
        "ldo", "u_ldo", "custom", "/x.lib", "ttt_lv", "m_pass", 40,
        devices={"nmos": "foo_nch", "pmos": "foo_pch"},
        device_terms={"nmos": 4, "pmos": 5},
        passive_section="ttt_passive")
    # PMOS instances grow the 5th (well) terminal = a repeat of the 4th (bulk)
    for line in deck.splitlines():
        if line.startswith("xmp"):
            nodes = line.split()[1:line.split().index("foo_pch")]
            assert len(nodes) == 5, line          # d g s b + well
            assert nodes[3] == nodes[4]           # well ties to bulk rail
    # NMOS instances stay 4-terminal
    for line in deck.splitlines():
        if line.startswith("xmn"):
            nodes = line.split()[1:line.split().index("foo_nch")]
            assert len(nodes) == 4, line
    # LV + passive pairing emitted
    assert ".lib /x.lib ttt_lv" in deck
    assert ".lib /x.lib ttt_passive" in deck
    assert "sky130_fd_pr" not in deck


def test_render_deck_sky130_new_args_are_noop():
    """No-leak: sky130 with the new device_terms(4)/passive(None) args renders
    byte-identical to the pre-existing no-context path (no pad, no pairing)."""
    a, _ = ARS.render_deck("ldo", "u_ldo", "sky130", "/x.lib", "tt", "m_pass", 40,
                           devices=None)
    b, _ = ARS.render_deck("ldo", "u_ldo", "sky130", "/x.lib", "tt", "m_pass", 40,
                           devices={"nmos": "sky130_fd_pr__nfet_01v8",
                                    "pmos": "sky130_fd_pr__pfet_01v8"},
                           device_terms={"nmos": 4, "pmos": 4},
                           passive_section=None)
    assert a == b


def test_pad_mos_instances_helper():
    line = "xmp_pass vout vg vdd vdd sky130_fd_pr__pfet_01v8 w=5 l=0.5\n"
    out = ARS._pad_mos_instances(line, "sky130_fd_pr__pfet_01v8", "foo_pch", 5)
    assert out.strip() == "xmp_pass vout vg vdd vdd vdd foo_pch w=5 l=0.5"
    # 4-terminal device: no padding, just token remap
    out4 = ARS._pad_mos_instances(line, "sky130_fd_pr__pfet_01v8", "foo_nch", 4)
    assert out4.strip() == "xmp_pass vout vg vdd vdd foo_nch w=5 l=0.5"


# ── degeneracy CONTROL — a deterministic (no-spread) MC is UNSCOREABLE, never a
#    fabricated 100% (the positive control bench-adc requires) ─────────────────

def test_mc_degeneracy_control_unscoreable(tmp_path, monkeypatch):
    """Same measure with NO real resample (identical samples) → the guard flags
    UNSCOREABLE, never a fake yield — proving a real yield means real spread."""
    p = _native_mc_project(tmp_path)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    # every seed returns the SAME value (a deterministic corner → sigma 0)
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice([1.80] * 8))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    rep = MC.run_block(p, "ldo", "x", "sky130", 8)
    assert rep["verdict"] == "UNSCOREABLE"
    assert (rep.get("spec_yield") or {}).get("vout", {}).get("degenerate") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
