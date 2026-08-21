"""Floor G-CATALOG-GLUE — DETERMINISTIC reused-IP RTL CONSUME.

DEFECT (survey, verified on opentitan_aes / ibex / caravel / subservient): a
reused_ip design whose rtl_gen WAIVES (fallback_skill=catalog-glue-author) left
``phase2/stage1/rtl/`` EMPTY on a runner-only (hands-off) run, so
``yosys synth -top chip_top`` hit "Module chip_top not found" → HALT at phase2.
The backend was never reached even though the design's INPUT itself PROVIDES the
build RTL (caravel ships ``input/design_src/verilog/rtl/*.v``).

FIX (chip-AGNOSTIC):
  ``reused_ip_rtl_consume.consume_reused_ip_rtl`` DETERMINISTICALLY stages the
  design's provided build RTL (``input/vendor_rtl/`` and/or
  ``input/design_src/**/rtl/``, or a SOURCE_MANIFEST-declared dir CONFINED under
  input/) into ``phase2/stage1/rtl/``; ``design_one_shot_runner``'s new
  ``step_reused_ip_consume`` then resolves a synthesizable top by the SAME order
  the synth path uses (instantiation-graph root, else the deterministic
  ``_autoemit_chip_top_wrapper`` chip_top). The residual glue that genuinely
  needs an LLM STILL WAIVES to catalog-glue-author.

§4.05 NO-LEAK: reads ONLY the design's legitimate INPUT build source; NEVER a
  testbench, a ``gl/`` gate-level netlist, ``output/`` (golden), or a
  manifest-declared path that escapes ``input/``. A design that ships NO build
  RTL gets NO staging — the WAIVE-to-catalog-glue-author path is unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import reused_ip_rtl_consume as C  # noqa: E402
import design_one_shot_runner as R  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────
def _write_l9(root: Path, top_module: str) -> None:
    d = root / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": top_module}))


def _rtl_mods(project: Path) -> set:
    return set(R._v661_rtl_module_names(project))


def _staged_rtl_dir(project: Path) -> Path:
    return project / "phase2" / "stage1" / "rtl"


# ── (A) design_src single-leaf → stage + top resolves ───────────────────────
def test_design_src_stages_rtl_and_top_resolves(tmp_path):
    """A design that ships its own build RTL under input/design_src/**/rtl/
    gets that RTL DETERMINISTICALLY staged, and a synthesizable top is
    resolved — so synth no longer halts on an empty rtl/."""
    rtl = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "widget_core.v").write_text(
        "module widget_core(input clk, input rst_n, "
        "input [7:0] din, output [7:0] dout);\nassign dout=din;\nendmodule\n")
    _write_l9(tmp_path, "widget_soc_top")  # phantom integration top

    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS"
    assert sr.extras["reused_ip"] is True
    assert "widget_core.v" in sr.extras["staged"]
    # rtl/ is populated deterministically
    assert (_staged_rtl_dir(tmp_path) / "widget_core.v").is_file()
    # a synthesizable top EXISTS: either a staged module OR an emitted chip_top
    resolved = sr.extras["synth_top_resolved"]
    emitted = sr.extras["chip_top_emitted"]
    assert (resolved in _rtl_mods(tmp_path)) or (emitted is not None)


def test_genericity_different_module_and_port_names(tmp_path):
    """Prove genericity — a DIFFERENT module + port naming behaves identically
    (no chip / vendor literal anywhere in the detection)."""
    rtl = tmp_path / "input" / "design_src" / "hdl" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spinner_engine.v").write_text(
        "module spinner_engine(input p1, input p2, output z);\n"
        "assign z = p1 & p2;\nendmodule\n")
    _write_l9(tmp_path, "spinner_platform")

    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS"
    assert "spinner_engine.v" in sr.extras["staged"]
    resolved = sr.extras["synth_top_resolved"]
    emitted = sr.extras["chip_top_emitted"]
    assert (resolved in _rtl_mods(tmp_path)) or (emitted is not None)


# ── (B) multi-module named top → bind graph root, NOT the inner leaf ─────────
def test_multi_module_named_top_binds_graph_root_not_inner_leaf(tmp_path):
    """A design that ships a genuine named integration top (a *_wrapper the
    auto-emit suffix-heuristic would skip) must resolve to that graph ROOT —
    NOT wrap an inner leaf, and NOT pre-empt the synth path's resolution."""
    rtl = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "soc_wrapper.v").write_text(
        "module soc_wrapper(input clk, input rst_n, output [3:0] q);\n"
        " soc_core u(.clk(clk),.rst_n(rst_n),.q(q));\nendmodule\n")
    (rtl / "soc_core.v").write_text(
        "module soc_core(input clk, input rst_n, output [3:0] q);\n"
        "assign q=4'd0;\nendmodule\n")
    _write_l9(tmp_path, "my_integration_top")

    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS"
    # the instantiation-graph ROOT (soc_wrapper) is bound, not the inner leaf
    assert sr.extras["synth_top_resolved"] == "soc_wrapper"
    # NO wrong chip_top wrapping the inner leaf
    assert sr.extras["chip_top_emitted"] is None
    assert not (_staged_rtl_dir(tmp_path) / "chip_top.v").exists()


# ── (C) the deterministic chip_top wrapper emitter (task step 2) ────────────
def test_chip_top_wrapper_emitter_produces_module(tmp_path):
    """The reused chip_top wrapper emitter (_autoemit_chip_top_wrapper, extracted
    from step_yosys_synth) deterministically produces a `module chip_top` thin
    pass-through with NAMED-port connections to the staged leaf."""
    rtl = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "alu_block.v").write_text(
        "module alu_block(input [3:0] a, input [3:0] b, output [3:0] y);\n"
        "assign y = a ^ b;\nendmodule\n")
    _write_l9(tmp_path, "alu_soc")
    C.consume_reused_ip_rtl(tmp_path)
    # emit against the fixed wrapper name (graph-root bypassed)
    p = R._autoemit_chip_top_wrapper(tmp_path, _staged_rtl_dir(tmp_path),
                                     "chip_top")
    assert p is not None and p.name == "chip_top.v"
    txt = p.read_text()
    assert "module chip_top" in txt
    assert "alu_block" in txt
    # named-port connections, not raw declarations splatted into the instance
    assert ".a(a)" in txt and ".b(b)" in txt and ".y(y)" in txt


# ── (D) vendor_rtl (pre-staged reusable IP) path also stages ────────────────
def test_vendor_rtl_path_also_stages(tmp_path):
    """input/vendor_rtl/ (the pre-staged reusable-IP WAIVE path) is also
    DETERMINISTICALLY staged into rtl/ (previously it only WAIVED)."""
    vd = tmp_path / "input" / "vendor_rtl" / "core"
    vd.mkdir(parents=True)
    (vd / "ip_top.v").write_text(
        "module ip_top(input clk, output done);\nassign done=1'b1;\nendmodule\n")
    _write_l9(tmp_path, "ip_top")
    res = C.consume_reused_ip_rtl(tmp_path)
    assert res["reused_ip"] is True
    assert "ip_top.v" in res["staged"]
    assert (_staged_rtl_dir(tmp_path) / "ip_top.v").is_file()


# ── (E) NEGATIVE: no build RTL → SKIP, no false population, WAIVE unchanged ──
def test_no_build_rtl_skips_no_false_population(tmp_path):
    """§4.05: a design that ships NO build RTL under input/ gets NO staging —
    consume returns reused_ip=False, rtl/ stays empty, no manifest, and the
    step is a clean SKIP (WAIVE-to-catalog-glue-author unchanged)."""
    _write_l9(tmp_path, "some_top")
    res = C.consume_reused_ip_rtl(tmp_path)
    assert res["reused_ip"] is False
    assert res["staged"] == []
    assert res["manifest_emitted"] is None
    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "SKIP"
    # rtl/ was never created / populated
    rtl = _staged_rtl_dir(tmp_path)
    assert not rtl.exists() or not any(
        p.suffix in (".v", ".sv") for p in rtl.glob("*"))
    # no spurious reused_ip manifest
    assert not (rtl / "SOURCE_MANIFEST.json").exists()


def test_step_rtl_gen_waive_then_consume_skip_end_to_end(tmp_path):
    """END-TO-END negative: on a non-reused project step_rtl_gen WAIVES and the
    following CONSUME step SKIPs — no RTL is fabricated from nowhere."""
    _write_l9(tmp_path, "some_top")
    waive = R.step_rtl_gen(tmp_path, "digital_cmd_driven")
    assert waive.status == "WAIVED"
    consume = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert consume.status == "SKIP"
    rtl = _staged_rtl_dir(tmp_path)
    assert not rtl.exists() or not list(rtl.glob("*.v"))


# ── (F) never clobber an author's / generator's RTL ─────────────────────────
def test_never_clobbers_existing_rtl(tmp_path):
    """If phase2/stage1/rtl/ already holds RTL (a generator/author owns it),
    CONSUME is a no-op SKIP and the existing file is untouched."""
    rtl = _staged_rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "authored.v").write_text("module authored(); endmodule\n")
    # design ALSO ships input RTL — must still be ignored (rtl/ owned)
    src = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    src.mkdir(parents=True)
    (src / "shipped.v").write_text("module shipped(input a, output b);"
                                   "assign b=a; endmodule\n")
    _write_l9(tmp_path, "authored")
    res = C.consume_reused_ip_rtl(tmp_path)
    assert res["reused_ip"] is False
    assert (rtl / "authored.v").read_text() == "module authored(); endmodule\n"
    assert not (rtl / "shipped.v").exists()


# ── (G) §4.05 NO-LEAK: testbenches + gate-level netlists are NOT staged ──────
def test_noleak_excludes_tb_and_gl(tmp_path):
    """A testbench file and a gate-level (gl/) netlist that live under the
    provided rtl/ tree are NEVER staged — only real build RTL."""
    rtl = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    (rtl / "gl").mkdir(parents=True)
    (rtl / "real_core.v").write_text(
        "module real_core(input a, output b);\nassign b=a;\nendmodule\n")
    (rtl / "tb_real_core.v").write_text(
        "module tb_real_core;\ninitial $finish;\nendmodule\n")
    (rtl / "real_core_tb.sv").write_text(
        "module real_core_tb;\nendmodule\n")
    (rtl / "gl" / "real_core.v").write_text(
        "module real_core(input a, output b);\n// GATE-LEVEL golden netlist\n"
        "endmodule\n")
    _write_l9(tmp_path, "real_soc")
    res = C.consume_reused_ip_rtl(tmp_path)
    assert res["reused_ip"] is True
    assert res["staged"] == ["real_core.v"]
    staged_dir = _staged_rtl_dir(tmp_path)
    assert not (staged_dir / "tb_real_core.v").exists()
    assert not (staged_dir / "real_core_tb.sv").exists()
    # the gl/ gate-level netlist was NOT pulled in as a build source
    prov = json.loads((staged_dir / "SOURCE_MANIFEST.json").read_text())
    assert all("gl/" not in p and "/gl/" not in p
               for p in prov.get("staged_from_input", []))


def test_noleak_manifest_declared_source_confined_to_input(tmp_path):
    """§4.05: a SOURCE_MANIFEST build_rtl_dirs entry that escapes input/ (e.g.
    points at ../output golden) is IGNORED — the consumer never reads outside
    the input sandbox."""
    # a golden tree OUTSIDE input/
    golden = tmp_path / "output" / "golden"
    golden.mkdir(parents=True)
    (golden / "answer.v").write_text(
        "module answer(input a, output b);\nassign b=~a;\nendmodule\n")
    # manifest tries to point the consumer at it
    mf_dir = tmp_path / "input"
    mf_dir.mkdir(parents=True, exist_ok=True)
    (mf_dir / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "build_rtl_dirs": ["../output/golden", "output/golden",
                           str(golden)]}))
    _write_l9(tmp_path, "some_top")
    # no legitimate input RTL at all → nothing to consume
    res = C.consume_reused_ip_rtl(tmp_path)
    assert res["reused_ip"] is False
    assert res["staged"] == []
    assert not (_staged_rtl_dir(tmp_path) / "answer.v").exists()


# ── (H) SV-ingest: staged SystemVerilog is not silently dropped ─────────────
def test_sv_ingest_note_not_silently_dropped(tmp_path):
    """G-SV-INGEST: a raw .sv build file is STAGED and a LOUD sv_ingest_note is
    emitted (do not silently drop) — the downstream slang/sv2v pre-pass lowers
    it."""
    rtl = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "sv_block.sv").write_text(
        "module sv_block(input logic clk, output logic q);\n"
        "always_ff @(posedge clk) q <= ~q;\nendmodule\n")
    _write_l9(tmp_path, "sv_soc")
    res = C.consume_reused_ip_rtl(tmp_path)
    assert res["reused_ip"] is True
    assert "sv_block.sv" in res["staged"]
    assert res["sv_files"] == ["sv_block.sv"]
    assert res["sv_ingest_note"] is not None
    assert "SV-ingest" in res["sv_ingest_note"]
    assert "not silently" in res["sv_ingest_note"].lower()


# ── (I) keystone manifest: reused_ip:true + provenance ──────────────────────
def test_consume_manifest_reused_ip_true_and_provenance(tmp_path):
    """The consume path emits a keystone SOURCE_MANIFEST.json with
    reused_ip:true + build_rtl_provided:true + a staged_from_input provenance
    list — so #659/#711/#712 relaxations + l9_rtl_pin_consistency_check are
    live on the design-provided path too."""
    rtl = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "m_core.v").write_text(
        "module m_core(input a, output b);\nassign b=a;\nendmodule\n")
    _write_l9(tmp_path, "m_soc")
    res = C.consume_reused_ip_rtl(tmp_path)
    mf = json.loads(
        (_staged_rtl_dir(tmp_path) / "SOURCE_MANIFEST.json").read_text())
    assert mf["reused_ip"] is True
    assert mf["build_rtl_provided"] is True
    assert mf["ip_list"] == ["m_core"]
    assert any("m_core.v" in p for p in mf["staged_from_input"])
    # empty reconciliation scaffold (verdict-neutral) present
    assert mf["renamed_interfaces"] == []
    assert mf["flattened_buses"] == []


def test_consume_manifest_merge_preserves_hand_authored(tmp_path):
    """MERGE: a pre-existing hand-authored tie_offs / renamed_interfaces block
    (e.g. from the pre-staged vendor manifest) is NEVER clobbered by consume."""
    rtl_out = _staged_rtl_dir(tmp_path)
    rtl_out.mkdir(parents=True)
    (rtl_out / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "reused_ip": True,
        "generated_by": "hand-author",
        "tie_offs": ["edn_i"],
        "renamed_interfaces": [{"l9": ["sram"], "rtl": ["sram_w", "sram_r"]}],
        "ip_list": ["curated"],
    }))
    src = tmp_path / "input" / "design_src" / "verilog" / "rtl"
    src.mkdir(parents=True)
    (src / "g_core.v").write_text(
        "module g_core(input a, output b);\nassign b=a;\nendmodule\n")
    _write_l9(tmp_path, "g_soc")
    C.consume_reused_ip_rtl(tmp_path)
    mf = json.loads((rtl_out / "SOURCE_MANIFEST.json").read_text())
    assert mf["tie_offs"] == ["edn_i"]
    assert mf["renamed_interfaces"] == [
        {"l9": ["sram"], "rtl": ["sram_w", "sram_r"]}]
    assert mf["generated_by"] == "hand-author"  # setdefault preserved
    assert mf["ip_list"] == ["curated"]         # richer list not clobbered
    assert mf["build_rtl_provided"] is True     # keystone asserted


# ── (J) reproduce on the REAL caravel benchmark input ───────────────────────
def _find_caravel_input() -> Path | None:
    for anc in Path(__file__).resolve().parents:
        cand = (anc / "benchmark-data" / "ic" / "caravel_user_project"
                / "input" / "design_src")
        if cand.is_dir():
            return cand
    return None


def test_reproduce_on_real_caravel_input(tmp_path):
    """REPRODUCE on the real caravel_user_project input (ships
    input/design_src/verilog/rtl/*.v): consume populates rtl/ deterministically
    and the synth top resolves to the real integration top
    (user_project_wrapper), NOT an inner leaf — the phase2 empty-rtl HALT is
    gone."""
    caravel_src = _find_caravel_input()
    if caravel_src is None:
        pytest.skip("benchmark-data caravel input not present in this checkout")
    import shutil
    dst = tmp_path / "input" / "design_src"
    shutil.copytree(caravel_src, dst)
    # minimal L9 with the phantom doc-prose integration top
    _write_l9(tmp_path, "caravel_user_project")

    sr = R.step_reused_ip_consume(tmp_path, "chip_top")
    assert sr.status == "PASS"
    staged = sr.extras["staged"]
    assert "user_project_wrapper.v" in staged
    assert "user_proj_example.v" in staged
    # the real Caravel top is bound (graph root), not the inner example
    assert sr.extras["synth_top_resolved"] == "user_project_wrapper"
    # rtl/ is genuinely populated so synth has sources
    assert (_staged_rtl_dir(tmp_path) / "user_project_wrapper.v").is_file()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
