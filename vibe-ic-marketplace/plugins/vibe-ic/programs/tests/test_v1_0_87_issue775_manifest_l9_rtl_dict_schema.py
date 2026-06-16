"""ORGANIC #775 — SOURCE_MANIFEST `flattened_outputs` / `flattened_buses`
consumer ignored the DOCUMENTED `{l9, rtl}` dict schema → silent no-op →
false chip_top pin hard-FAIL.

DEFECT (round-14 v1.0.85, ibex reused-IP, adversarial-verified NEW):
  `catalog-glue-author/SKILL.md` documents the SOURCE_MANIFEST keys
  `flattened_buses` / `flattened_outputs` with the dict schema
  `[{"l9": "alert", "rtl": ["alert_n_o", "alert_p_o"]}]`. But
  `l9_rtl_pin_consistency_check._manifest_name_set()` only read string-list
  entries or dicts carrying a name/port/interface/root key — NOT l9/rtl. So a
  manifest authored EXACTLY per the docs yielded an empty exposed/flatten set
  (silent no-op) and the chip_top pin reconcile hard-FAILed
  "L9 ↔ RTL top pin/direction mismatch". Only `renamed_interfaces` parsed
  {l9, rtl} (via `_manifest_renamed_groups`, the #711 path).

FIX (chip-AGNOSTIC): `_manifest_name_set()` now ALSO accepts the `{l9, rtl}`
  dict — it FOLDS the `l9` root name(s) (for the flatten-key consumer, which is
  keyed on the L9 ROOT) AND EXPANDS the `rtl` wire name(s) (for the
  exposed-output consumer, which is keyed on the RTL PAD name). Doc-and-code now
  agree. `l9` / `rtl` may each be a bare string or a string list.

§4.05 NO-LEAK: only the names declared in the manifest reconcile. An undeclared
  extra RTL output (a genuinely-dropped/extra functional pin) STILL FAILs; a
  genuine L9-only functional pin STILL FAILs. The relaxation never masks a real
  mismatch.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as G  # noqa: E402

_GATE = _PROGRAMS / "l9_rtl_pin_consistency_check.py"


# ─────────────────────────────────────────────────────────────────────
# 1. NEW-PATH: the documented {l9, rtl} dict schema is now parsed.
# ─────────────────────────────────────────────────────────────────────
def test_repro_exposed_outputs_l9_rtl_dict_was_silent_noop():
    """`flattened_outputs:[{l9,rtl}]` (the documented form) now yields a
    non-empty set — the exposed RTL pad names are EXPANDED."""
    mf = {"flattened_outputs": [{"l9": "alert_major_o",
                                 "rtl": ["alert_n_o", "alert_p_o"]}]}
    got = G._manifest_name_set(mf, G._MANIFEST_EXPOSED_OUTPUT_KEYS)
    # The RTL pad names (exposed-output consumer keys on these) are present.
    assert {"alert_n_o", "alert_p_o"} <= got, got
    # The L9 root is folded too (harmless for the exposed consumer; used by
    # the flatten-key consumer). The key property is: NOT an empty set.
    assert got, "documented {l9,rtl} schema must not produce a silent no-op"


def test_flattened_buses_l9_rtl_dict_folds_root():
    """`flattened_buses:[{l9,rtl}]` folds the L9 struct ROOT (the flatten-key
    consumer is keyed on the root)."""
    mf = {"flattened_buses": [{"l9": "tl", "rtl": ["tl_a_o", "tl_d_i"]}]}
    got = G._manifest_name_set(mf, G._MANIFEST_FLATTEN_KEYS)
    assert "tl" in got, got


def test_l9_rtl_dict_accepts_bare_string_values():
    """`l9` / `rtl` may each be a bare string (not only a list). #775 r2
    Step-2.7: the expansion is CONSUMER-AWARE — the EXPOSED-output consumer
    (keys on the RTL pad) takes ONLY the `rtl` name, never the `l9` root (folding
    both was a §4.05 cross-contamination leak)."""
    mf = {"flattened_outputs": [{"l9": "x", "rtl": "x_pad"}]}
    exposed = G._manifest_name_set(mf, G._MANIFEST_EXPOSED_OUTPUT_KEYS)
    assert exposed == {"x_pad"}, exposed          # only the RTL pad, NOT the L9 root
    mf2 = {"flattened_buses": [{"l9": "x", "rtl": "x_pad"}]}
    flatten = G._manifest_name_set(mf2, G._MANIFEST_FLATTEN_KEYS)
    assert flatten == {"x"}, flatten              # only the L9 root, NOT the RTL pad


def test_770r2_review_manifest_no_cross_family_contamination():
    """#775 r2 §4.05 NO-LEAK: an L9 root must NOT appear in the exposed(rtl-pad)
    set, nor an rtl wire in the flatten(l9-root) set — else a genuine missing /
    extra functional port could be silently waved through."""
    m = {"flattened_outputs": [{"l9": "alert_major_o",
                                "rtl": ["alert_n_o", "alert_p_o"]}]}
    assert "alert_major_o" not in G._manifest_name_set(
        m, G._MANIFEST_EXPOSED_OUTPUT_KEYS)
    mf = {"flattened_buses": [{"l9": "tl", "rtl": ["tl_a_o", "tl_d_i"]}]}
    assert "tl_a_o" not in G._manifest_name_set(mf, G._MANIFEST_FLATTEN_KEYS)


def test_existing_string_and_name_keyed_forms_unchanged():
    """Regression: the pre-#775 string-list and name/port-keyed-dict forms
    still parse exactly as before (no behaviour change)."""
    assert G._manifest_name_set(
        {"flattened_outputs": ["alert_n_o"]},
        G._MANIFEST_EXPOSED_OUTPUT_KEYS) == {"alert_n_o"}
    assert G._manifest_name_set(
        {"flattened_outputs": [{"name": "alert_n_o"}]},
        G._MANIFEST_EXPOSED_OUTPUT_KEYS) == {"alert_n_o"}
    # dict-of-keys form (interface names as KEYS) is also unaffected.
    assert G._manifest_name_set(
        {"flattened_buses": {"tl": {}}},
        G._MANIFEST_FLATTEN_KEYS) == {"tl"}


# ─────────────────────────────────────────────────────────────────────
# 2. RECONCILE end-state: documented {l9,rtl} flattened_outputs gives
#    residual_rtl == [] (the issue's exact regression criterion).
# ─────────────────────────────────────────────────────────────────────
def test_reconcile_flattened_outputs_l9_rtl_residual_rtl_empty():
    """ISSUE REGRESSION: flattened_outputs:[{l9,rtl}] reconciles
    residual_rtl==[] (ibex alert_major_o → split outputs L9 lacks entirely)."""
    mf = {"reused_ip": True,
          "flattened_outputs": [{"l9": "alert_major_o",
                                 "rtl": ["alert_major_internal_o",
                                         "alert_major_bus_o"]}]}
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        [], ["alert_major_internal_o", "alert_major_bus_o"], mf)
    assert res_rtl == [], res_rtl
    assert any(lbl == "(wrapper-exposed-output)" for lbl, _ in pm), pm


def test_reconcile_flattened_buses_l9_rtl_root_recognised():
    """flattened_buses:[{l9,rtl}] — the L9 struct root reconciles with its
    prefix-expanded pads (root folded into declared_flatten)."""
    mf = {"reused_ip": True,
          "flattened_buses": [{"l9": "tl", "rtl": ["tl_a_o", "tl_d_i"]}]}
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        ["tl"], ["tl_a_o", "tl_d_i"], mf)
    assert res_l9 == [] and res_rtl == [], (res_l9, res_rtl)
    assert any(root == "tl" for root, _ in pm), pm


# ─────────────────────────────────────────────────────────────────────
# 3. §4.05 NO-LEAK — the relaxation must NOT mask a genuine defect.
# ─────────────────────────────────────────────────────────────────────
def test_noleak_undeclared_extra_rtl_output_still_residual():
    """§4.05: an RTL output NOT in the declared {l9,rtl} rtl-list is a genuine
    extra functional port and STILL surfaces as residual."""
    mf = {"reused_ip": True,
          "flattened_outputs": [{"l9": "alert_major_o",
                                 "rtl": ["alert_n_o", "alert_p_o"]}]}
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        [], ["alert_n_o", "alert_p_o", "rogue_extra_o"], mf)
    assert res_rtl == ["rogue_extra_o"], res_rtl


def test_noleak_genuine_l9_only_pin_still_residual():
    """§4.05: a genuine L9-only functional pin (not a declared flatten root,
    not tied, not bound) STILL surfaces as residual."""
    mf = {"reused_ip": True,
          "flattened_outputs": [{"l9": "alert_major_o",
                                 "rtl": ["alert_n_o", "alert_p_o"]}]}
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        ["genuinely_missing_i"], ["alert_n_o", "alert_p_o"], mf)
    assert res_l9 == ["genuinely_missing_i"], res_l9


# ─────────────────────────────────────────────────────────────────────
# 4. #478 END-STATE — DIRECT-write a tmp_path artifact, invoke the REAL
#    program via subprocess, assert the returncode.
# ─────────────────────────────────────────────────────────────────────
def _scaffold(tmp_path: Path, l9_ports, chip_body: str, manifest: dict) -> Path:
    proj = tmp_path
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (gd / "L9_integration.json").write_text(json.dumps({
        "ic_name": "ibex_soc", "top_module": "chip_top",
        "top_ports": l9_ports,
    }))
    (rtl / "chip_top.sv").write_text(
        "module chip_top (\n" + chip_body + "\n);\nendmodule\n")
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return proj


def _run(proj: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_GATE), str(proj)],
        capture_output=True, text=True)


def test_endstate_docs_authored_manifest_now_passes(tmp_path):
    """#478 END-STATE: a SOURCE_MANIFEST authored EXACTLY per the SKILL.md
    `{l9,rtl}` docs (wrapper exposes split outputs L9 lacks entirely) now
    PASSes the real gate (rc=0) instead of the false hard-FAIL."""
    proj = _scaffold(
        tmp_path,
        l9_ports=[{"name": "clk", "direction": "input"},
                  {"name": "rst_n", "direction": "input"},
                  {"name": "data_o", "direction": "output"}],
        chip_body=("  input  wire clk,\n  input  wire rst_n,\n"
                   "  output wire data_o,\n"
                   "  output wire alert_major_internal_o,\n"
                   "  output wire alert_major_bus_o"),
        manifest={"reused_ip": True, "ip_list": ["ibex"],
                  "flattened_outputs": [{"l9": "alert_major_o",
                                         "rtl": ["alert_major_internal_o",
                                                 "alert_major_bus_o"]}]},
    )
    r = _run(proj)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "PASS" in r.stdout, r.stdout


def test_endstate_noleak_undeclared_extra_output_still_fails(tmp_path):
    """#478 END-STATE §4.05: a docs-authored manifest does NOT mask a genuine
    extra RTL output — the undeclared rogue port STILL hard-FAILs (rc=1)."""
    proj = _scaffold(
        tmp_path,
        l9_ports=[{"name": "clk", "direction": "input"},
                  {"name": "rst_n", "direction": "input"},
                  {"name": "data_o", "direction": "output"}],
        chip_body=("  input  wire clk,\n  input  wire rst_n,\n"
                   "  output wire data_o,\n"
                   "  output wire alert_major_internal_o,\n"
                   "  output wire alert_major_bus_o,\n"
                   "  output wire rogue_extra_o"),
        manifest={"reused_ip": True, "ip_list": ["ibex"],
                  "flattened_outputs": [{"l9": "alert_major_o",
                                         "rtl": ["alert_major_internal_o",
                                                 "alert_major_bus_o"]}]},
    )
    r = _run(proj)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "rogue_extra_o" in r.stdout, r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
