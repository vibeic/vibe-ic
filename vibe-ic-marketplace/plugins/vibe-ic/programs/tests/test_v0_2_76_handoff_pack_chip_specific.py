"""v0.2.76 — #446: foundry handoff pack is chip-specific, no fabricated
artifacts.

The audited rot: foundry_handoff_pack_gen emitted byte-identical
README/wat_plan/corner_vectors across three designs, mask_spec with
pdk=unknown / cell_count=-1, and a 137-byte TEXT file named
scribe_line_layout.gds.

Pins:
  * cell_count: synth.log miss → netlist instance count → null, NEVER -1;
  * pdk: derived from the PDK's own liberty/LEF names, NEVER "unknown";
  * no file wearing the .gds name unless it is a GDS — the scribe need
    is a plainly-named TODO.txt; an old text placeholder is removed;
  * wat_plan / corner kit carry design+PDK facts and L10 pattern seeds
    so two designs cannot emit identical members.

chip-AGNOSTIC: synthetic fixtures with generic names.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import foundry_handoff_pack_gen as FH  # noqa: E402


def _proj(tmp_path, name="alpha", lib="examplepdk_sc_hd__tt_025C.lib",
          l10_cases=("TC_RESET", "TC_SMOKE")):
    p = tmp_path / name
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.sv").write_text(f"module top_{name}(input clk);\nendmodule\n")
    synth = p / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text(
        "module top(input clk);\n"
        + "".join(f"  buf_cell _{i}_ (.A(clk), .X());\n" for i in range(7))
        + "endmodule\n")
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (p / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (p / "phase3" / "stage4" / "gds" / f"{name}.gds").write_bytes(
        b"\x00\x06\x00\x02" + name.encode())
    lib_dir = p / "input" / "pdk" / "liberty"
    lib_dir.mkdir(parents=True)
    (lib_dir / lib).write_text("library(x){}")
    gen = p / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    (gen / "L10_TEST_CASES.json").write_text(json.dumps(
        {"test_cases": [{"id": c} for c in l10_cases]}))
    return p


def test_cell_count_never_negative(tmp_path):
    p = _proj(tmp_path)
    assert FH.main([str(p)]) == 0
    mask = json.loads(
        (p / "phase3/stage4/foundry_handoff/mask_spec.json").read_text())
    assert mask["cell_count"] == 7      # netlist fallback counted instances
    assert mask["cell_count"] >= 0


def test_pdk_derived_not_unknown(tmp_path):
    p = _proj(tmp_path)
    FH.main([str(p)])
    mask = json.loads(
        (p / "phase3/stage4/foundry_handoff/mask_spec.json").read_text())
    assert mask["pdk"] == "examplepdk_sc_hd"
    assert mask["pdk"] != "unknown"


def test_no_fake_scribe_gds(tmp_path):
    p = _proj(tmp_path)
    FH.main([str(p)])
    hd = p / "phase3/stage4/foundry_handoff"
    assert not (hd / "scribe_line_layout.gds").exists()
    assert (hd / "scribe_line_layout.PENDING_FOUNDRY.txt").is_file()


def test_old_placeholder_scribe_is_removed(tmp_path):
    p = _proj(tmp_path)
    hd = p / "phase3/stage4/foundry_handoff"
    hd.mkdir(parents=True)
    (hd / "scribe_line_layout.gds").write_bytes(
        b"# PLACEHOLDER scribe_line_layout.gds -- old fabricated file\n")
    FH.main([str(p)])
    assert not (hd / "scribe_line_layout.gds").exists()


def test_real_foundry_scribe_gds_untouched(tmp_path):
    p = _proj(tmp_path)
    hd = p / "phase3/stage4/foundry_handoff"
    hd.mkdir(parents=True)
    real = b"\x00\x06\x00\x02real-binary-gds"
    (hd / "scribe_line_layout.gds").write_bytes(real)
    FH.main([str(p)])
    assert (hd / "scribe_line_layout.gds").read_bytes() == real


def test_two_designs_never_byte_identical(tmp_path):
    pa = _proj(tmp_path, "alpha", l10_cases=("TC_A1", "TC_A2"))
    pb = _proj(tmp_path, "beta", lib="otherpdk_sc_ms__ss_125C.lib",
               l10_cases=("TC_B1",))
    FH.main([str(pa)])
    FH.main([str(pb)])
    for member in ("mask_spec.json", "wat_plan.json",
                   "corner_test_vectors.json", "README.txt"):
        a = (pa / "phase3/stage4/foundry_handoff" / member).read_bytes()
        b = (pb / "phase3/stage4/foundry_handoff" / member).read_bytes()
        assert a != b, f"{member} byte-identical across designs (#446)"


def test_corner_kit_carries_l10_seeds(tmp_path):
    p = _proj(tmp_path, l10_cases=("TC_RESET", "TC_SMOKE", "TC_CRC"))
    FH.main([str(p)])
    kit = json.loads(
        (p / "phase3/stage4/foundry_handoff/corner_test_vectors.json")
        .read_text())
    assert kit["test_pattern_seeds_from_l10"] == [
        "TC_RESET", "TC_SMOKE", "TC_CRC"]
    assert kit["test_pattern_seed_count"] == 3
