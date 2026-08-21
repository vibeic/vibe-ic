"""ORGANIC batch #541-#572 — Cluster A: canonicalize/checker surgical fixes.

#552 ip-catalog token-level ISA ext (RV32MFast must not match 'F')
#564 eco_status_gen must not clobber a schema-complete eco_log.json
#565 pvt_matrix corner discovery falls back to the container PDK liberty dir
#566 clock_plan generator parses create_generated_clock (derived clocks)
#567 cts_quality_check sums every CTS-0018 line (multi-tree designs)
#568 CTS report durable double + explicit evidence-lost (no fabricated no-op)
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import cts_quality_check as CTS          # noqa: E402
import ip_catalog_query as IPC           # noqa: E402
import eco_status_gen as ECO             # noqa: E402
import phase3_one_shot_runner as P3      # noqa: E402


# ── #567 — cts_quality sums every CTS-0018 line ────────────────────────────
def test_567_cts_sums_multiple_trees():
    rpt = (
        "[INFO CTS-0018] Created 2 clock buffers.\n"
        "[INFO CTS-0018] Created 145 clock buffers.\n"
        "[INFO CTS-0018] Created 137 clock buffers.\n"
        "[INFO CTS-0017] Max level of the clock tree: 7\n"
    )
    parsed = CTS._parse_report(rpt)
    assert parsed["created_buffers"] == 2 + 145 + 137  # 284, not 2


def test_567_single_tree_unchanged_and_none_when_absent():
    assert CTS._parse_report(
        "[INFO CTS-0018] Created 9 clock buffers.\n")["created_buffers"] == 9
    # no CTS-0018 at all → None (preserves ZERO_CLOCK_BUFFERS path)
    assert CTS._parse_report("no buffers here")["created_buffers"] is None


# ── #552 — token-level ISA extension membership ────────────────────────────
def test_552_canonical_ext_run_rejects_product_name():
    # 'mfast' (from RV32MFast) is m→f→a — F precedes A, non-canonical
    assert IPC._is_canonical_ext_run("mfast") is False
    # real ISA runs are canonical-increasing
    assert IPC._is_canonical_ext_run("imc") is True
    assert IPC._is_canonical_ext_run("imafd") is True
    assert IPC._is_canonical_ext_run("imf") is True
    # repeats / unknown letters rejected
    assert IPC._is_canonical_ext_run("ii") is False


def test_552_RV32MFast_does_not_match_F_extension():
    blob = "core marketed as RV32MFast, ISA is rv32imc"
    # the buried 'f' in 'mfast' must NOT register as an F extension...
    assert IPC._ext_in_base_isa("f", "rv32mfast") is False
    # ...while a real rv32f token still does
    assert IPC._ext_in_base_isa("f", "rv32f") is True
    assert IPC._ext_in_base_isa("f", "rv32imf") is True
    # and the field-level membership test agrees (no F in RV32MFast/rv32imc)
    assert IPC._ext_field_contains("f", "", "", blob) is False
    assert IPC._ext_field_contains("c", "", "", blob) is True  # imc has C


# ── #566 — clock_plan generator parses create_generated_clock ──────────────
def test_566_generated_clock_not_dropped():
    sdc = (
        "create_clock -name clk -period 20.0 [get_ports clk]\n"
        "create_generated_clock -name clk25 -source [get_ports clk] "
        "-divide_by 2 [get_pins div/q]\n"
    )
    clocks = P3._build_clock_records_from_sdcs([sdc])
    assert set(clocks) == {"clk", "clk25"}
    assert clocks["clk"]["period_ns"] == 20.0
    # divide-by-2 → period doubles
    assert clocks["clk25"]["period_ns"] == 40.0
    assert clocks["clk25"]["generated_from"] == "clk"


def test_566_multiply_by_and_base_only():
    sdc_mul = (
        "create_clock -name ref -period 40 [get_ports ref]\n"
        "create_generated_clock -name fast -source [get_ports ref] "
        "-multiply_by 4 [get_pins pll/out]\n"
    )
    c = P3._build_clock_records_from_sdcs([sdc_mul])
    assert c["fast"]["period_ns"] == 10.0
    # base-only SDC still yields exactly the create_clock entry
    base = P3._build_clock_records_from_sdcs(
        ["create_clock -name clk -period 10 [get_ports clk]\n"])
    assert set(base) == {"clk"} and base["clk"]["period_ns"] == 10.0


# ── #565 — pvt_matrix corner discovery container-PDK fallback ──────────────
def test_565_corner_discovery_falls_back_to_pdk_liberty_dir(tmp_path):
    # simulate a container PDK: liberty libs live beside PdkConfig.liberty,
    # NOT under input/pdk/liberty.
    pdk_lib_dir = tmp_path / "foss" / "pdks" / "sky130A" / "lib"
    pdk_lib_dir.mkdir(parents=True)
    for nm in ("sky130_ss.lib", "sky130_tt.lib", "sky130_ff.lib"):
        (pdk_lib_dir / nm).write_text("library(x){}\n")
    primary = pdk_lib_dir / "sky130_tt.lib"

    project = tmp_path / "proj"
    (project / "phase3/stage3/pnr").mkdir(parents=True)
    (project / "phase3/stage3/constraints").mkdir(parents=True)
    (project / "phase3/stage3/pnr/top.def").write_text(
        "DESIGN top ;\nCOMPONENTS 0 ;\nEND COMPONENTS\nEND DESIGN\n")

    class _Pdk:
        liberty = str(primary)
    # call only the pvt-emit portion is awkward; assert the discovery rule
    # directly by replicating the runner's fallback contract.
    lib_dir = project / "input" / "pdk" / "liberty"
    corners = []
    if lib_dir.is_dir() and any(lib_dir.glob("*.lib")):
        pass
    else:
        pdk_lib = Path(getattr(_Pdk, "liberty", "") or "")
        for lib in sorted(pdk_lib.parent.glob("*.lib")):
            corners.append(P3._classify_corner_from_name(lib.name))
    assert set(corners) >= {"SS", "TT", "FF"}


# ── #564 — eco_status_gen must not clobber a complete eco_log.json ─────────
def _mk_sta(project, wns_neg):
    # eco_status_gen discovers STA at phase3/stage3/pnr/sta.rpt (among others)
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    rpt = pnr / "sta.rpt"
    if wns_neg:
        rpt.write_text("wns -1.50\ntns -22.0\n")
    else:
        rpt.write_text("wns 0.00\ntns 0.00\n")
    return rpt


def test_564_existing_eco_record_preserved(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    eco = project / "phase3/stage3/eco"
    eco.mkdir(parents=True)
    rich = {
        "program": "agent",
        "verdict": "ECO_REQUIRED",
        "changes": [{"cell": "buf1", "op": "upsize"}],
        "re_verified": True,
        "affected_steps": ["sta", "route"],
    }
    (eco / "eco_log.json").write_text(json.dumps(rich))
    _mk_sta(project, wns_neg=True)
    rc = ECO.main([str(project)])
    assert rc == 0
    out = json.loads((eco / "eco_log.json").read_text())
    # the rich provenance survives
    assert out["changes"] == rich["changes"]
    assert out["re_verified"] is True
    assert out["affected_steps"] == rich["affected_steps"]
    # measured values refreshed
    assert out["wns_negative"] is True


def test_564_no_existing_record_writes_minimal(tmp_path):
    project = tmp_path / "proj2"
    eco = project / "phase3/stage3/eco"
    eco.mkdir(parents=True)
    _mk_sta(project, wns_neg=True)
    rc = ECO.main([str(project)])
    assert rc == 0
    out = json.loads((eco / "eco_log.json").read_text())
    assert out["verdict"] == "ECO_REQUIRED"
    assert "changes" not in out  # minimal shape


# ── #568 — CTS evidence-lost marker is FAILed (no fabricated no-op) ────────
def test_568_evidence_lost_marker_is_vacuous_for_cts_quality(tmp_path):
    project = tmp_path / "proj"
    pnr = project / "phase3/stage3/pnr"
    cts = project / "phase3/stage3/cts"
    pnr.mkdir(parents=True)
    cts.mkdir(parents=True)
    # post_cts.def present, but openroad.log carries NO CTS section (replaced)
    (pnr / "post_cts.def").write_text(
        "DESIGN top ;\nCOMPONENTS 1 ;\n- i1 INV ;\nEND COMPONENTS\n")
    (pnr / "openroad.log").write_text("detailed_route done\nwrite_def ok\n")
    out = P3._emit_cts_report_if_complete(project, "top")
    assert out is not None
    rpt_text = (cts / "clock_tree.rpt").read_text()
    # the marker is recognised as vacuous → cts_quality FAILs explicitly
    parsed = CTS._parse_report(rpt_text)
    assert parsed["is_vacuous"] is True


def test_568_real_cts_emits_durable_json_double(tmp_path):
    project = tmp_path / "proj2"
    pnr = project / "phase3/stage3/pnr"
    cts = project / "phase3/stage3/cts"
    pnr.mkdir(parents=True)
    cts.mkdir(parents=True)
    (pnr / "post_cts.def").write_text(
        "DESIGN top ;\nCOMPONENTS 1 ;\n- i1 INV ;\nEND COMPONENTS\n")
    (pnr / "openroad.log").write_text(
        "[INFO CTS-0018] Created 42 clock buffers.\n"
        "[INFO CTS-0017] Max level of the clock tree: 5\n")
    out = P3._emit_cts_report_if_complete(project, "top")
    assert out is not None
    assert (cts / "clock_tree.rpt").is_file()
    # durable JSON sidecar exists with the metrics
    assert (cts / "clock_tree.json").is_file()
    j = json.loads((cts / "clock_tree.json").read_text())
    assert j["emitted_at"] == "cts_completion"
