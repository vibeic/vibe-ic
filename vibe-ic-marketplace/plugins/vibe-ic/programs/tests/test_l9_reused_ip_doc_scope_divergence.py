"""ORGANIC — l9_rtl_pin_consistency_check had no honest path for a reused-IP
design whose vendor DOCS describe a DIFFERENT integration entity than the one
the project builds.

DEFECT (organic, ibex x sky130A converge cell, v1.5.28):
  input/phase1_prompt.md designates `ibex_core` as top and stages exactly the
  pruned ibex_core source set. input/docs/ibex_integration.rst, however, opens
  with "The main module is named ``ibex_top``" and documents ibex_top's signal
  table + instantiation template. Phase-1 harvests BOTH into L9.top_ports, so
  L9 carries 17 ports that belong to `ibex_top` — the SecureIbex-capable outer
  wrapper (lockstep `*_shadow_o` + lockstep_cmp_en_o, bus/ECC integrity
  `*_intg_*`, ram_cfg_i, crash_dump_o, double_fault_seen_o, alert_major_bus_o)
  — which the staged vendor set does not contain and no staged module drives.

  The gate then reported `L9 declares pins missing from RTL top: [...17...]`
  and hard-FAILed phase 2 under --strict-structural. The only ways to clear it
  were (a) declaring the 17 as manifest `tie_offs` — asserting the wrapper
  drives a redundancy/integrity surface the delivered IC does not have, i.e.
  exactly the false PASS this gate exists to prevent — or (b) a blanket
  waiver. Neither is honest, so a correctly-built design had no honest PASS.

FIX (chip-AGNOSTIC): `split_doc_scope_divergence` demotes an L9-only pin to a
  disclosed advisory ONLY under three structural predicates:
    (1) SOURCE_MANIFEST.json declares reused_ip=true;
    (2) the L9-DECLARED top module is declared by NO file in the project RTL
        tree — proof L9's contract is for a different entity;
    (3) the pin is a port of NO module in the project RTL tree — proof no
        staged IP provides it.

§4.05 NO-LEAK: a pin that ANY staged module DOES provide but the wrapper
  dropped is a genuine dropped pin and still hard-FAILs; a non-reused-IP
  design never enters the branch; when L9's top IS in the tree (the normal
  case) the split is a no-op. The demotion is DISCLOSED on both the PASS and
  the FAIL path — never silent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as G  # noqa: E402


# The staged IP: an inner core that drives ONE combined major-alert output and
# has NO redundancy/integrity ports. Mirrors the ibex_core shape.
_IP_CORE = """
module ip_core (
    input  logic        clk_i,
    input  logic        rst_ni,
    output logic        data_req_o,
    input  logic        data_gnt_i,
    output logic        alert_major_o,
    output logic        core_sleep_o
);
endmodule
"""

# The catalog-glue wrapper: exposes exactly what the staged IP provides.
_WRAPPER = """
module chip_top (
    input  logic        clk_i,
    input  logic        rst_ni,
    output logic        data_req_o,
    input  logic        data_gnt_i,
    output logic        alert_major_o,
    output logic        core_sleep_o
);
  ip_core u_core (
      .clk_i(clk_i), .rst_ni(rst_ni), .data_req_o(data_req_o),
      .data_gnt_i(data_gnt_i), .alert_major_o(alert_major_o),
      .core_sleep_o(core_sleep_o));
endmodule
"""

# Ports the DOCS declare for the outer wrapper `ip_top`, which is NOT staged.
_DOC_ONLY_PORTS = [
    "lockstep_cmp_en_o",
    "data_req_shadow_o",
    "data_wdata_intg_o",
    "ram_cfg_i",
]


def _mkproject(tmp_path: Path, *, wrapper: str = _WRAPPER,
               reused_ip: bool = True, l9_top: str = "ip_top") -> Path:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "ip_core.sv").write_text(_IP_CORE)
    (rtl / "chip_top.sv").write_text(wrapper)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "reused_ip": reused_ip,
        "ip_list": ["ip_core"],
        "rtl_strategy": "catalog_lookup_plus_ai_glue",
    }))
    return tmp_path


def _l9_only(*names: str) -> list:
    return sorted(names)


# ── the defect, end-state ──────────────────────────────────────────────────
def test_doc_scope_ports_demoted_to_advisory(tmp_path):
    """END-STATE: doc-only ports of an unstaged top become advisory."""
    proj = _mkproject(tmp_path)
    residual, out_of_scope = G.split_doc_scope_divergence(
        _l9_only(*_DOC_ONLY_PORTS), proj, "ip_top")
    assert residual == [], residual
    assert sorted(out_of_scope) == sorted(_DOC_ONLY_PORTS), out_of_scope


def test_manifest_reused_ip_true_is_read_from_disk(tmp_path):
    """The keystone predicate (1) is the on-disk manifest the gate loads."""
    proj = _mkproject(tmp_path)
    assert G.load_source_manifest(proj) is not None
    proj2 = _mkproject(tmp_path / "b", reused_ip=False)
    assert G.load_source_manifest(proj2) is None


# ── §4.05 NO-LEAK ──────────────────────────────────────────────────────────
def test_noleak_dropped_pin_the_staged_ip_provides_still_residual(tmp_path):
    """A pin a STAGED module really has, dropped by the wrapper, still FAILs.

    This is the exact failure class the gate exists to catch — the guard must
    not be able to swallow it."""
    wrapper = _WRAPPER.replace("    input  logic        data_gnt_i,\n", "")
    wrapper = wrapper.replace(".data_gnt_i(data_gnt_i), ", "")
    proj = _mkproject(tmp_path, wrapper=wrapper)
    residual, out_of_scope = G.split_doc_scope_divergence(
        _l9_only("data_gnt_i", *_DOC_ONLY_PORTS), proj, "ip_top")
    assert residual == ["data_gnt_i"], residual
    assert "data_gnt_i" not in out_of_scope


def test_noleak_l9_top_present_in_tree_is_a_noop(tmp_path):
    """Predicate (2): when L9's top IS the module the project builds, the
    split does nothing — the ordinary design gets zero relaxation."""
    proj = _mkproject(tmp_path)
    residual, out_of_scope = G.split_doc_scope_divergence(
        _l9_only(*_DOC_ONLY_PORTS), proj, "chip_top")
    assert sorted(residual) == sorted(_DOC_ONLY_PORTS), residual
    assert out_of_scope == []


def test_noleak_no_l9_top_name_is_a_noop(tmp_path):
    """No L9-declared top name → no proof of scope divergence → no-op."""
    proj = _mkproject(tmp_path)
    residual, out_of_scope = G.split_doc_scope_divergence(
        _l9_only(*_DOC_ONLY_PORTS), proj, None)
    assert sorted(residual) == sorted(_DOC_ONLY_PORTS)
    assert out_of_scope == []


def test_noleak_unparseable_rtl_tree_fails_closed(tmp_path):
    """No parseable RTL tree → no relaxation (fail-closed, not fail-open)."""
    empty = tmp_path / "empty"
    (empty / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    residual, out_of_scope = G.split_doc_scope_divergence(
        _l9_only(*_DOC_ONLY_PORTS), empty, "ip_top")
    assert sorted(residual) == sorted(_DOC_ONLY_PORTS)
    assert out_of_scope == []


def test_tree_scan_sees_every_staged_module_and_port(tmp_path):
    """The predicate-(3) evidence set spans the WHOLE tree, not just the top."""
    proj = _mkproject(tmp_path)
    modules, ports = G.rtl_tree_modules_and_ports(proj)
    assert {"ip_core", "chip_top"} <= modules
    assert "ip_top" not in modules
    assert {"data_gnt_i", "alert_major_o", "core_sleep_o"} <= ports
    assert not (set(_DOC_ONLY_PORTS) & ports)


# ── disclosure ─────────────────────────────────────────────────────────────
def test_demotion_is_disclosed_on_both_verdict_paths(capsys):
    """A relaxation that fires silently is indistinguishable from one that
    never fired — the advisory must print on PASS and on FAIL alike."""
    G._print_doc_scope_advisory(list(_DOC_ONLY_PORTS), "ip_top")
    out = capsys.readouterr().out
    assert "DOC-SCOPE divergence" in out
    assert "ip_top" in out
    for p in _DOC_ONLY_PORTS:
        assert p in out


def test_advisory_silent_when_nothing_demoted(capsys):
    G._print_doc_scope_advisory([], "ip_top")
    assert capsys.readouterr().out == ""


# ── end-to-end through main() ──────────────────────────────────────────────
def _write_l9(proj: Path, top_module: str, port_names: list) -> None:
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    ports = [{"name": n,
              "direction": "output" if n.endswith("_o") else "input"}
             for n in port_names]
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2, "doc_class": "integration_spec",
        "top_module": top_module, "top_ports": ports,
    }))


_WRAPPER_PORTS = ["data_req_o", "data_gnt_i", "alert_major_o", "core_sleep_o"]


def test_main_passes_with_doc_scope_divergence_only(tmp_path, capsys):
    proj = _mkproject(tmp_path)
    _write_l9(proj, "ip_top", _WRAPPER_PORTS + _DOC_ONLY_PORTS)
    rc = G.main(["l9_rtl_pin_consistency_check", str(proj)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert out.startswith("PASS"), out
    assert "DOC-SCOPE divergence" in out, out


def test_main_still_fails_on_a_real_dropped_pin(tmp_path, capsys):
    """§4.05 end-to-end: the guard does not rescue a genuinely dropped pin."""
    wrapper = _WRAPPER.replace("    input  logic        data_gnt_i,\n", "")
    wrapper = wrapper.replace(".data_gnt_i(data_gnt_i), ", "")
    proj = _mkproject(tmp_path, wrapper=wrapper)
    _write_l9(proj, "ip_top", _WRAPPER_PORTS + _DOC_ONLY_PORTS)
    rc = G.main(["l9_rtl_pin_consistency_check", str(proj)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "data_gnt_i" in out, out
    # …and the demoted set is still disclosed alongside the FAIL.
    assert "DOC-SCOPE divergence" in out, out


def test_main_no_manifest_gets_no_relaxation(tmp_path, capsys):
    proj = _mkproject(tmp_path, reused_ip=False)
    _write_l9(proj, "ip_top", _WRAPPER_PORTS + _DOC_ONLY_PORTS)
    rc = G.main(["l9_rtl_pin_consistency_check", str(proj)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "DOC-SCOPE divergence" not in out, out


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
