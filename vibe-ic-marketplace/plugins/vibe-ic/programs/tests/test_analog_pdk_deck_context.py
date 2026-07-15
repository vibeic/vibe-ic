"""Family-agnostic corner-sweep deck-context consumption (v1.4.27).

The v1.4.24 resolver (analog_pdk_availability) DECIDES the native PDK path;
analog_pdk_deck_context CONSUMES it so the emitted ngspice deck's model-lib
include, corner SECTION names, and DEVICE MAP come from the RESOLVED family —
never a hardcoded sky130 literal against a foreign lib.

Fixtures (per the batch spec):
  (i)   a staged custom family emits decks including ITS libs / sections /
        devices (family-agnostic device mapping parsed from the resolved libs);
  (ii)  the sky130 container family is UNCHANGED (bit-identical regression);
  (iii) an unresolvable device role → honest NEEDS_NATIVE_TEMPLATE failure,
        NEVER a cross-family sky130 deck.

NDA hygiene: SYNTHETIC family names only (MyFoundry X180 etc.) — no NDA token.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_availability as APA          # noqa: E402
import analog_pdk_deck_context as APDC          # noqa: E402
import analog_real_corner_sweep as ARS          # noqa: E402


# ── synthetic custom PDK model libs (subckt-based, sectioned) ───────────────

def _custom_lib_text(nch="myfoundry_x180_nch", pch="myfoundry_x180_pch",
                     sections=("ss", "tt", "ff")) -> str:
    out = ["* MyFoundry X180 synthetic model lib (NO NDA content)"]
    for sec in sections:
        out.append(f".lib {sec}")
        out.append(f".subckt {nch} d g s b w=1 l=1")
        out.append(".ends")
        out.append(f".subckt {pch} d g s b w=1 l=1")
        out.append(".ends")
        out.append(".endl")
    return "\n".join(out) + "\n"


def _custom_res(lib_path="/pdk/myfoundry_x180.lib"):
    return {"available": True, "source": "project_custom_pdk",
            "family": "myfoundryx180", "target": "MyFoundry X180 (custom node)",
            "spice_libs": [lib_path], "spice_lib": lib_path,
            "drc_deck": None, "lvs_deck": None}


# ── (ii) sky130 known family — bit-identical regression ─────────────────────

def test_sky130_known_family_unchanged():
    ctx = APDC.resolve_deck_context("sky130")
    assert ctx.status == "OK"
    assert ctx.source == "known_family"
    assert ctx.device_map == {"nmos": "sky130_fd_pr__nfet_01v8",
                              "pmos": "sky130_fd_pr__pfet_01v8"}
    assert ctx.typ_section == "tt"
    assert [c[0] for c in ctx.process_corners] == ["ss", "tt", "ff"]
    assert ctx.model_lib.endswith("sky130.lib.spice")


def test_sky130_render_deck_is_byte_identical_to_no_context():
    """A deck rendered with the known-sky130 device map == a deck rendered with
    devices=None (the pre-v1.4.27 path). No sky130 literal is disturbed."""
    ctx = APDC.resolve_deck_context("sky130")
    a, _ = ARS.render_deck("ldo", "u_ldo", "sky130", "/x.lib", "tt",
                           "m_pass", 40, devices=ctx.device_map)
    b, _ = ARS.render_deck("ldo", "u_ldo", "sky130", "/x.lib", "tt",
                           "m_pass", 40, devices=None)
    assert a == b
    assert "sky130_fd_pr__nfet_01v8" in a and "sky130_fd_pr__pfet_01v8" in a


def test_default_no_resolver_is_known_family():
    """No L19 target / no resolver result → known open-PDK fast path (the
    common case; every existing sky130 project stays on the unchanged path)."""
    ctx = APDC.resolve_deck_context("sky130", res=None)
    assert ctx.source == "known_family"
    ctx2 = APDC.resolve_deck_context("sky130",
                                     res={"available": False, "source": None})
    assert ctx2.source == "known_family"


# ── (i) staged custom family emits ITS libs / sections / devices ────────────

def test_custom_family_parses_own_devices_and_sections():
    lib = _custom_lib_text()
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: lib)
    assert ctx.status == "OK"
    assert ctx.source == "project_custom_pdk"
    assert ctx.device_map == {"nmos": "myfoundry_x180_nch",
                              "pmos": "myfoundry_x180_pch"}
    assert ctx.corner_sections == ["ss", "tt", "ff"]
    assert ctx.typ_section == "tt"
    assert ctx.model_lib == "/pdk/myfoundry_x180.lib"


def test_custom_family_deck_carries_family_devices_not_sky130():
    lib = _custom_lib_text()
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: lib)
    deck, _ = ARS.render_deck("ldo", "u_ldo", "custom", ctx.model_lib,
                              ctx.typ_section, "m_pass", 40,
                              devices=ctx.device_map)
    assert "myfoundry_x180_nch" in deck
    assert "myfoundry_x180_pch" in deck
    assert "sky130_fd_pr" not in deck        # NO cross-family sky130 literal


def test_custom_family_nonstandard_section_names():
    """A custom family whose sections are slow/typ/fast (not ss/tt/ff) still
    resolves — the nominal + process corners come from ITS sections."""
    lib = _custom_lib_text(sections=("slow", "typ", "fast"))
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: lib)
    assert ctx.status == "OK"
    assert ctx.typ_section == "typ"
    assert [c[0] for c in ctx.process_corners] == ["slow", "typ", "fast"]


def test_custom_family_end_to_end_via_resolver(tmp_path):
    """Full chain: stage a custom PDK on disk → APA.resolve_pdk (rung 1) →
    resolve_deck_context reads the staged lib locally (no injected reader)."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "myfoundry_x180.lib").write_text(_custom_lib_text())
    res = APA.resolve_pdk("MyFoundry X180 (custom node)", project=str(tmp_path))
    assert res["available"] and res["source"] == "project_custom_pdk"
    ctx = APDC.resolve_deck_context("sky130", res=res)   # local reader
    assert ctx.status == "OK"
    assert ctx.device_map["nmos"] == "myfoundry_x180_nch"
    assert ctx.device_map["pmos"] == "myfoundry_x180_pch"


# ── (iii) unresolvable role → honest NEEDS_NATIVE_TEMPLATE, never sky130 ─────

def test_missing_pmos_role_is_needs_native_template():
    lib = ".lib tt\n.subckt onlyfoundry_nch d g s b\n.ends\n.endl\n"
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: lib)
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE"
    assert "pmos" in ctx.unresolved_roles
    assert ctx.work_items
    assert any("NEEDS_NATIVE_TEMPLATE" in w for w in ctx.work_items)


def test_model_only_devices_are_not_template_compatible():
    """A `.model`-only lib (no `.subckt` wrapper) is NOT compatible with the
    templates' `X<inst> ... <subckt> w= l=` instantiation → honest fail."""
    lib = ".lib tt\n.model nch nmos\n.model pch pmos\n.endl\n"
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: lib)
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE"
    assert set(ctx.unresolved_roles) == {"nmos", "pmos"}


def test_three_terminal_mos_is_rejected():
    """A subckt named like a MOS but with <4 terminals cannot host the d/g/s/b
    templates → the role stays unresolved (never silently substituted)."""
    lib = (".lib tt\n.subckt foundry_nch d g s\n.ends\n"
           ".subckt foundry_pch d g s b\n.ends\n.endl\n")
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: lib)
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE"
    assert "nmos" in ctx.unresolved_roles      # 3-terminal nch rejected
    assert "pmos" not in ctx.unresolved_roles  # 4-terminal pch accepted


def test_unreadable_libs_are_needs_native_template():
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), reader=lambda p: None)
    assert ctx.status == "NEEDS_NATIVE_TEMPLATE"
    assert any("not readable" in w or "no readable" in w for w in ctx.work_items)


# ── unit coverage of the parse/role/section primitives ──────────────────────

def test_parse_devices_subckt_and_model():
    text = (".subckt fam_nfet_x d g s b w=1 l=1\n.ends\n"
            ".model fam_res r\n")
    dev = APDC.parse_devices(text)
    assert dev["subckts"]["fam_nfet_x"] == 4
    assert dev["models"]["fam_res"] == "r"


def test_assign_role_ambiguous_is_unassigned():
    # a name matching BOTH n- and p- tokens is left unassigned (honest)
    assert APDC._assign_role("fam_nfet_x") == "nmos"
    assert APDC._assign_role("fam_pfet_x") == "pmos"
    # a name carrying BOTH an n- and a p- token is ambiguous → unassigned
    assert APDC._assign_role("fam_nfet_pfet_dual") is None


def test_required_roles_from_template():
    # bandgap uses only nfet devices → nmos-only required (no pmos gate)
    assert ARS._template_required_roles("bandgap") == ("nmos",)
    # ldo uses both
    assert set(ARS._template_required_roles("ldo")) == {"nmos", "pmos"}


def test_nmos_only_family_ok_for_nmos_only_block():
    """An nmos-only family resolves for an nmos-only template (bandgap) — the
    per-template required-roles gate does not demand a pmos it never uses."""
    lib = ".lib tt\n.subckt fam_nch d g s b\n.ends\n.endl\n"
    ctx = APDC.resolve_deck_context(
        "sky130", res=_custom_res(), required=("nmos",), reader=lambda p: lib)
    assert ctx.status == "OK"
    assert ctx.device_map == {"nmos": "fam_nch"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
