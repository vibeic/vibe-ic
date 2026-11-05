#!/usr/bin/env python3
"""D10: the two siblings D6 left — the #732 vendor branch, and the registry
class generators — read "supplied RTL" the way consume does.

(1) MEASURED at v1.25.64: `input/vendor_rtl/{spm.v, tb_spm.v}` made the
    rtl_gen WAIVE say "2 file(s)" and the #732 manifest publish
    `ip_list: ['spm', 'tb_spm']`, while consume staged only `spm.v`. Both now
    use `discover_provided_build_rtl` restricted to vendor_rtl: a testbench or
    an oracle segment is never IP.

(2) MEASURED on the mixed_signal_otp fixture at v1.25.64: with the design's
    own `chip_top.v` supplied, `aid_class_rtl_gen` still wrote `chip_top.sv`,
    and consume then staged `chip_top.v` beside it (two definitions of the
    top). The class generators (aid_class_half_duplex_single_wire,
    mixed_signal_otp -> aid_class_rtl_gen; data_converter ->
    data_converter_rtl_gen) now decline when the supplied RTL defines the
    design's declared top.

    What stays: a generated design that INSTANTIATES supplied IP. MEASURED on
    the same fixture: the generated `otp_mem` instantiates `otp_macro_wrapper`,
    the project supplies it, and consume's closure path stages it around the
    generated tree. That still happens, pinned below.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

import design_one_shot_runner as R                       # noqa: E402
import reused_ip_rtl_consume as C                        # noqa: E402
import staged_rtl_reused_ip_manifest_emit as SRM         # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d10_{name}", TESTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OTP_FX = _load("test_aid_class_rtl_gen_mixed_signal_otp_skeleton")
DC_FX = _load("test_issue2197_data_converter_datapath_generator")

OTP_MACRO = ("module otp_macro_wrapper(input clk, input [6:0] addr,\n"
             "  output [7:0] rdata);\n  assign rdata = 8'h0;\nendmodule\n")


def _rtl_files(p):
    d = p / "phase2/stage1/rtl"
    return sorted(f.name for f in d.glob("*") if f.suffix in (".v", ".sv")) \
        if d.is_dir() else []


def _defs(p, module):
    d = p / "phase2/stage1/rtl"
    rx = re.compile(r"^\s*module\s+" + re.escape(module) + r"\b", re.M)
    return sum(len(rx.findall(f.read_text(errors="replace")))
               for f in d.glob("*") if f.suffix in (".v", ".sv"))


# --------------------------------------------------------------------------- #
# (1) the #732 vendor branch
# --------------------------------------------------------------------------- #
def _vendor(tmp_path, files):
    vd = tmp_path / "input/vendor_rtl"
    for rel, text in files.items():
        (vd / rel).parent.mkdir(parents=True, exist_ok=True)
        (vd / rel).write_text(text)
    return tmp_path


SPM = "module spm(input clk, output p);\n  assign p = clk;\nendmodule\n"
TB = "module tb_spm;\n  spm u ();\nendmodule\n"


def test_the_manifest_lists_no_testbench_as_ip(tmp_path):
    p = _vendor(tmp_path, {"spm.v": SPM, "tb_spm.v": TB,
                           "tb/harness.v": "module harness; endmodule\n"})
    mf = json.loads(SRM.emit_prestaged_reused_ip_manifest(p).read_text())
    assert mf["ip_list"] == ["spm"]
    assert [f.name for f in SRM.vendor_build_rtl(p)] == ["spm.v"]


def test_the_waive_counts_what_consume_stages(tmp_path):
    p = _vendor(tmp_path, {"spm.v": SPM, "tb_spm.v": TB})
    res = R.step_rtl_gen(p, "digital_cmd_driven")
    assert res.extras.get("fallback_skill") == "catalog-glue-author"
    assert "1 file(s)" in res.detail and "tb_spm" not in res.detail, \
        res.detail[:400]


def test_a_vendor_tree_of_testbenches_only_is_not_reused_ip(tmp_path):
    p = _vendor(tmp_path, {"tb_spm.v": TB})
    assert SRM.emit_prestaged_reused_ip_manifest(p) is None
    res = R.step_rtl_gen(p, "digital_cmd_driven")
    assert "source_manifest_emitted" not in (res.extras or {})


# --------------------------------------------------------------------------- #
# (2) the registry class generators
# --------------------------------------------------------------------------- #
def _otp_project(root):
    root.mkdir(parents=True, exist_ok=True)
    OTP_FX._seed_fixture(root)
    return root


def _dc_project(root):
    """The REAL data_converter shape: L9 names the chip (`adc_top`, as a real
    converter's L9 names its own top), while `data_converter_rtl_gen` emits
    `cic_decimator` -- a module that is NOT the declared top."""
    p = DC_FX._mk(root, DC_FX.FULL)
    (p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "adc_top", "top_ports": []}))
    return p


#: (class, project, the declared L9 top, a NON-top module the generator emits)
CLASSES = [("aid_class_half_duplex_single_wire", _otp_project, "chip_top",
            "otp_mem"),
           ("mixed_signal_otp", _otp_project, "chip_top", "otp_mem"),
           ("data_converter", _dc_project, "adc_top", "cic_decimator")]


@pytest.mark.parametrize("cls,mk,top,emitted", CLASSES,
                         ids=[c[0] for c in CLASSES])
def test_the_generator_runs_without_supplied_rtl(tmp_path, cls, mk, top,
                                                 emitted):
    """The control: each class really reaches its generator here, and the
    generator really emits the module the next test supplies."""
    p = mk(tmp_path / "p")
    res = R.step_rtl_gen(p, cls)
    assert res.status == "PASS", res.detail[:300]
    assert _defs(p, emitted) == 1


PARTIAL = [c for c in CLASSES if c[0] != "data_converter"]


@pytest.mark.parametrize("cls,mk,top,emitted", PARTIAL,
                         ids=[c[0] for c in PARTIAL])
def test_a_supplied_submodule_replaces_only_that_generated_file(
        tmp_path, cls, mk, top, emitted):
    """review_wave4a MAJOR (partial overlap): the input supplies ONE module
    the generator emits. The rest of the generated design stays, only the
    generated file defining that module is dropped, consume stages the
    supplied one into the now-open tree, and nothing forbids authoring.
    RED on 77f5ba13e: rtl/ was emptied and the whole design handed off."""
    p = mk(tmp_path / "p")
    _vendor(p, {f"{emitted}.v": f"// supplied\nmodule {emitted}"
                                f"(input clk, output q);\n"
                                f"  assign q = clk;\nendmodule\n"})
    res = R.step_rtl_gen(p, cls)
    assert res.status == "PASS", res.detail[:300]
    rec = res.extras["supplied_replaces_generated"]
    assert rec["replaced_by"] == {emitted: f"input/vendor_rtl/{emitted}.v"}
    assert rec["modules_now_owed"] == []
    # MEMBERS, not a count (review_wave7): exactly the no-supply control's
    # files, minus the dropped generated one, plus the staged supplied one
    control = _control_rtl(tmp_path, mk, cls)
    assert rec["dropped_generated_files"] == [f"{emitted}.sv"]
    assert set(_rtl_files(p)) == (control - {f"{emitted}.sv"}) | {f"{emitted}.v"}
    # rtl_gen itself stages the supplied module (review_wave4c): one
    # definition, the supplied bytes, the rest of the design kept
    assert rec["staged_by_rtl_gen"] == [f"{emitted}.v"]
    assert _defs(p, top) == 1 and _defs(p, emitted) == 1
    assert len(_rtl_files(p)) > 5            # the rest of the design is there
    assert "Do NOT author" not in res.detail
    assert not res.extras.get("fallback_skill")
    out = C.consume_reused_ip_rtl(p)
    assert out["staged"] == [] and "supplied_rtl_not_staged" not in out
    assert (p / "phase2/stage1/rtl" / f"{emitted}.v").read_text().startswith(
        "// supplied")


def test_a_supplied_generator_top_is_full_coverage_and_yields(tmp_path):
    """FULL coverage: data_converter's own top is the one module it emits
    (`cic_decimator`, not the L9 top `adc_top`); supplying it supplies the
    design, so the generated tree is discarded and the supplied RTL handed
    off."""
    p = _dc_project(tmp_path / "p")
    _vendor(p, {"cic_decimator.v": "// supplied\nmodule cic_decimator"
                                   "(input clk, output q);\n"
                                   "  assign q = clk;\nendmodule\n"})
    res = R.step_rtl_gen(p, "data_converter")
    assert res.status == "PASS_WITH_WAIVERS", res.detail[:300]
    assert res.extras["declined_generator"] == "data_converter_rtl_gen.py"
    assert res.extras["generated_tops"] == ["cic_decimator"]
    assert _rtl_files(p) == []
    out = C.consume_reused_ip_rtl(p)
    assert out["staged"] == ["cic_decimator.v"]
    assert _defs(p, "cic_decimator") == 1


def test_a_dropped_file_that_held_other_modules_names_them_owed(tmp_path):
    """A generated file defining the supplied module AND another one is
    dropped whole; the other module is named as OWED, never silently lost."""
    p = tmp_path / "p"
    rtl = p / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "pair.v").write_text("module a(input x); endmodule\n"
                                "module b(input x); endmodule\n")
    (rtl / "top.v").write_text("module top(input x);\n  a ua(.x(x));\n"
                               "  b ub(.x(x));\nendmodule\n")
    _vendor(p, {"a.v": "module a(input x); endmodule\n"})
    rec = R._yield_generated_modules(p, rtl, ["a"])
    assert rec == {"replaced_by": {"a": "input/vendor_rtl/a.v"},
                   "dropped_generated_files": ["pair.v"],
                   "modules_now_owed": ["b"]}
    assert sorted(f.name for f in rtl.glob("*.v")) == ["top.v"]


@pytest.mark.parametrize("cls,mk,top,emitted", CLASSES,
                         ids=[c[0] for c in CLASSES])
def test_a_supplied_top_declines_the_class_generator(tmp_path, cls, mk, top,
                                                     emitted):
    p = mk(tmp_path / "p")
    _vendor(p, {f"{top}.v": f"module {top}(input clk, output q);\n"
                            f"  assign q = clk;\nendmodule\n",
                f"tb_{top}.v": f"module tb_{top};\n  {top} u ();\nendmodule\n"})
    res = R.step_rtl_gen(p, cls)
    assert res.status == "PASS_WITH_WAIVERS", res.detail[:300]
    assert res.extras["fallback_skill"] == "catalog-glue-author"
    assert res.extras["declined_generator"] == R._lookup_class(cls)["rtl_gen"]
    assert res.extras["declared_top"] == top
    assert res.extras["design_rtl_sample"] == [f"input/vendor_rtl/{top}.v"]
    assert _rtl_files(p) == []
    staged = C.consume_reused_ip_rtl(p)["staged"]
    assert staged == [f"{top}.v"] and _defs(p, top) == 1


def test_a_generated_design_still_wraps_supplied_ip(tmp_path):
    """The cooperation case, through consume's closure path: supplied IP that
    does not define the top leaves the generator running, and consume stages
    the IP the generated tree instantiates."""
    p = _otp_project(tmp_path / "p")
    _vendor(p, {"otp_macro_wrapper.v": OTP_MACRO})
    res = R.step_rtl_gen(p, "mixed_signal_otp")
    assert res.status == "PASS", res.detail[:300]
    gen = [f for f in (p / "phase2/stage1/rtl").glob("*")
           if f.suffix in (".v", ".sv")]
    assert "otp_macro_wrapper" in C._unresolved_module_refs(gen)
    assert "supplied_rtl_blocked_by" not in res.extras
    assert "will NOT be staged" not in res.detail
    out = C.consume_reused_ip_rtl(p)
    assert out["staged"] == ["otp_macro_wrapper.v"]
    assert "otp_macro_wrapper" in out["unresolved_module_refs"]
    assert _defs(p, "chip_top") == 1 and _defs(p, "otp_macro_wrapper") == 1


@pytest.mark.parametrize("files", [
    {"tb/chip_top.v": "module chip_top; endmodule\n"},
    {"tb_chip_top.v": "module chip_top; endmodule\n"},
], ids=["oracle-segment", "testbench-stem"])
def test_a_testbench_that_defines_the_top_is_not_the_design(tmp_path, files):
    p = _otp_project(tmp_path / "p")
    _vendor(p, files)
    assert R.step_rtl_gen(p, "mixed_signal_otp").status == "PASS"


def test_no_declared_top_and_no_emitted_module_never_stops_the_generator(
        tmp_path):
    """Without a declared top, only the generator's OWN output decides: IP it
    does not emit leaves it running (and a module it emits declines it, see
    test_a_supplied_module_the_generator_emits_declines_it)."""
    p = _otp_project(tmp_path / "p")
    spec = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(spec.read_text())
    doc.pop("top_module", None)
    spec.write_text(json.dumps(doc))
    _vendor(p, {"some_ip.v": "module some_ip(input clk); endmodule\n"})
    assert R._supplied_rtl_defining_declared_top(p) == (None, [])
    assert R.step_rtl_gen(p, "mixed_signal_otp").status == "PASS"


# =========================================================================== #
# review of D6, follow-ups (a)-(d)
# =========================================================================== #
import hashlib                                                  # noqa: E402

D6 = _load("test_d6_supplied_rtl_outranks_every_generator")
ARITH = D6.ARITH


@pytest.fixture
def _session(monkeypatch):
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# (a) supplied VHDL never disappears silently -------------------------------
VHDL = "entity top is end entity;\narchitecture rtl of top is begin end;\n"


def test_a_vhdl_only_design_still_declines_the_rtl_spec_dispatcher(tmp_path):
    """#403 refused on *.vhd/*.vhdl before D6; D6's .v/.sv helper let the
    generator replace a VHDL design with a PASS that never named it."""
    stage = tmp_path / "phase2/stage1"
    stage.mkdir(parents=True)
    (stage / "rtl_spec.json").write_text(json.dumps(D6.TRUTH_TABLE_SPEC))
    D6._supply(tmp_path, "input/vendor_rtl", "top.vhd", VHDL)
    res = R._try_deterministic_rtl_dispatch(tmp_path, 0.0)
    assert res is not None and res.status == "NOT_APPLICABLE", res
    assert res.extras["design_rtl_sample"] == ["input/vendor_rtl/top.vhd"]
    assert _rtl_files(tmp_path) == []


def test_a_supplied_vhdl_is_named_in_the_rtl_gen_result(tmp_path, _session):
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/rtl", "spm.vhd", VHDL)
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["unconsumed_supplied_hdl"] == ["input/rtl/spm.vhd"]
    assert "input/rtl/spm.vhd" in res.detail and "VHDL" in res.detail


# (b) a deferral is recorded, and every input root gets the reused-IP hand-off
@pytest.mark.parametrize("route", ["input/rtl", "input/design_src/impl/rtl",
                                   "input/vendor_rtl"])
def test_b_a_deferral_is_recorded_and_hands_off_as_reused_ip(
        tmp_path, _session, route):
    p = D6._spm_project(tmp_path)
    D6._supply(p, route, "spm.v", D6.SUPPLIED_SPM)
    res = R.step_rtl_gen(p, ARITH)
    assert res.status == "PASS_WITH_WAIVERS", res.detail[:300]
    assert res.extras["fallback_skill"] == (
        "catalog-glue-author" if route == "input/vendor_rtl"
        else "spec-to-rtl"), res.extras
    assert res.extras["supplied_build_rtl"] == [f"{route}/spm.v"]
    assert "rtl_gen" in [
        d["generator"] for d in res.extras["deferred_generators"]]
    assert ("Do NOT author the design itself" in res.detail) is (
        route == "input/vendor_rtl")


def test_b_force_regen_overridden_by_supplied_rtl_is_said(tmp_path, _session):
    p = D6._prose_project(tmp_path, "bf", D6.BEHAVIORAL_PROSE)
    D6._supply(p, "input/rtl", "own_top.v", D6._supplied("own_top"))
    res = R.step_rtl_gen(p, ARITH, force_regen=True)
    bf = [d for d in res.extras["deferred_generators"]
          if d["generator"] == "behavioral_fsm"]
    assert bf and bf[0]["force_rtl_regen_overridden"] is True
    assert "--force-rtl-regen overridden" in res.detail


# (c) a module-less .v is not a design ---------------------------------------
DEFINES = "// spm widths\n`define SPM_BITS 8\n`define SPM_SIGNED 0\n"


def test_c_a_define_only_v_file_does_not_stop_the_generator(tmp_path, _session):
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/rtl", "spm_defines.v", DEFINES)
    res = R.step_rtl_gen(p, ARITH)
    assert res.status == "PASS", res.detail[:300]
    assert res.extras.get("deterministic_generator") == \
        "serial_parallel_mul_synth", res.extras
    assert "deferred_generators" not in res.extras
    assert C.discover_supplied_design_sources(p) == []


def test_c_a_define_only_vendor_file_is_not_ip(tmp_path):
    p = _vendor(tmp_path, {"spm.v": SPM, "spm_defines.v": DEFINES})
    assert [f.name for f in SRM.vendor_build_rtl(p)] == ["spm.v"]


# (d) a previous run's generated rtl/ does not block the supplied design ----
def test_d_a_stale_generated_tree_is_reclaimed_for_the_supplied_design(
        tmp_path, _session, monkeypatch):
    """A previous run's REGISTRY-generated tree (ledger-stamped GENERATED)
    is moved to the backup, and consume stages the supplied design."""
    p = _otp_project(tmp_path / "p")
    first = R.step_rtl_gen(p, "mixed_signal_otp")
    assert first.status == "PASS" and _defs(p, "chip_top") == 1
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)   # a new run
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    own = _vendor(p, {"chip_top.v": "// the supplied design\n"
                                    "module chip_top(input clk, output q);\n"
                                    "  assign q = clk;\nendmodule\n"})
    own = p / "input/vendor_rtl/chip_top.v"
    res = R.step_rtl_gen(p, "mixed_signal_otp")
    assert res.extras["reclaimed_generated_rtl"] == {
        "backup": "rtl.pre_gen_backup", "published": True}, res.extras
    assert _rtl_files(p) == []
    assert (p / "phase2/stage1/rtl.pre_gen_backup/chip_top.sv").is_file()
    out = C.consume_reused_ip_rtl(p)
    assert out["staged"] == ["chip_top.v"]
    assert _sha(p / "phase2/stage1/rtl/chip_top.v") == _sha(own)


def test_d_a_serial_generated_tree_is_reclaimed_for_supplied_rtl(tmp_path, _session):
    """The serial producer's GENERATED ledger authorizes the same safe reclaim
    path as registry generators; consume then stages the supplied design."""
    p = D6._spm_project(tmp_path)
    R.step_rtl_gen(p, ARITH)
    assert _rtl_files(p) == ["spm.v"]
    generated = _sha(p / "phase2/stage1/rtl/spm.v")
    R._RTL_SESSION_OWNED = False
    D6._supply(p, "input/rtl", "spm.v", D6.SUPPLIED_SPM)
    supplied = _sha(p / "input/rtl/spm.v")
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["reclaimed_generated_rtl"] == {
        "backup": "rtl.pre_gen_backup", "published": True}
    assert _rtl_files(p) == []
    assert _sha(p / "phase2/stage1/rtl.pre_gen_backup/spm.v") == generated
    out = C.consume_reused_ip_rtl(p)
    assert out["staged"] == ["spm.v"]
    assert _sha(p / "phase2/stage1/rtl/spm.v") == supplied



# =========================================================================== #
# review_wave2 (branch D10) fixes
# =========================================================================== #
# MAJOR 1 — the "supplied RTL was NOT staged" disclosures must answer no when
# rtl/ already holds the supplied design (consume staged it).
def test_consume_twice_does_not_claim_the_supplied_rtl_is_missing(tmp_path):
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/rtl", "spm.v", D6.SUPPLIED_SPM)
    first = C.consume_reused_ip_rtl(p)
    assert first["staged"] == ["spm.v"]
    second = C.consume_reused_ip_rtl(p)
    assert "supplied_rtl_not_staged" not in second, second
    assert "NOT staged" not in second["reason"]


def test_rtl_gen_after_consume_does_not_claim_the_supplied_rtl_is_blocked(
        tmp_path, _session):
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/vendor_rtl", "spm.v", D6.SUPPLIED_SPM)
    R.step_rtl_gen(p, ARITH)
    assert C.consume_reused_ip_rtl(p)["staged"] == ["spm.v"]
    # the catalog-glue author writes its wrapper, then the flow re-enters
    (p / "phase2/stage1/rtl/chip_top.v").write_text(
        "module chip_top(input clk, output y);\n  spm u (.clk(clk));\n"
        "endmodule\n")
    again = R.step_rtl_gen(p, ARITH)
    assert "supplied_rtl_blocked_by" not in again.extras, again.extras
    assert "will NOT be staged" not in again.detail


def test_a_changed_supplied_file_is_still_reported(tmp_path):
    """The filter is by content: the same name with DIFFERENT bytes, not
    listed as staged, is still reported."""
    p = D6._spm_project(tmp_path)
    rtl = p / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text("module spm(input clk); endmodule\n")
    D6._supply(p, "input/rtl", "spm.v", D6.SUPPLIED_SPM)
    out = C.consume_reused_ip_rtl(p)
    assert out["supplied_rtl_not_staged"] == ["input/rtl/spm.v"]


# MAJOR 3 — context RTL for a task that MODIFIES it keeps the spec-to-rtl
# WAIVE, told to start from the supplied RTL; reused IP gets catalog-glue.
@pytest.mark.parametrize("route", ["input/rtl", "input/design_src/impl/rtl"])
def test_context_rtl_keeps_spec_to_rtl_and_is_the_starting_point(
        tmp_path, _session, route):
    p = D6._spm_project(tmp_path)
    D6._supply(p, route, "spm.v", "module spm(input clk);\n  // TODO\n"
                                  "endmodule\n")
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["fallback_skill"] == "spec-to-rtl", res.extras
    assert "Do NOT author" not in res.detail
    assert "starting point" in res.detail.lower()
    assert f"{route}/spm.v" in res.detail
    # a re-run after consume wrote ITS manifest is still not "reused IP"
    C.consume_reused_ip_rtl(p)
    again = R.step_rtl_gen(p, ARITH)
    assert again.extras["fallback_skill"] == "spec-to-rtl", again.extras


def test_reused_ip_under_vendor_rtl_gets_catalog_glue(tmp_path, _session):
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/vendor_rtl", "spm.v", D6.SUPPLIED_SPM)
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["fallback_skill"] == "catalog-glue-author"
    assert "Do NOT author the design itself" in res.detail


def test_a_declared_reused_ip_manifest_gets_catalog_glue(tmp_path, _session):
    """Reused IP through the runner's own loader: a manifest that DECLARES
    reused_ip (not consume's own staging record) under input/rtl."""
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/rtl", "spm.v", D6.SUPPLIED_SPM)
    rtl = p / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(
        {"reused_ip": True, "rtl_strategy": "catalog_lookup_plus_ai_glue"}))
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["fallback_skill"] == "catalog-glue-author"


# MINOR — an unregistered class with a supplied design is not told to author
# from scratch either.
@pytest.mark.parametrize("route,skill", [
    ("input/vendor_rtl", "catalog-glue-author"), ("input/rtl", "spec-to-rtl")])
def test_an_unregistered_class_uses_the_same_supplied_rtl_hand_off(
        tmp_path, _session, route, skill):
    p = D6._spm_project(tmp_path)
    D6._supply(p, route, "spm.v", D6.SUPPLIED_SPM)
    res = R.step_rtl_gen(p, "no_such_class_d10")
    assert res.extras["fallback_skill"] == skill, res.extras
    assert res.extras["supplied_build_rtl"] == [f"{route}/spm.v"]


# MINOR — the per-dispatch records never leak into the next call.
def test_records_of_a_previous_call_never_reach_the_next_result(
        tmp_path, _session, monkeypatch):
    R._SUPPLY_DEFERRALS.append({"generator": "stale", "reason": "stale"})
    R._SUPPLY_RECLAIMED.append("stale_backup")
    R._SUPPLY_BLOCKED.append({"rtl_files": ["x.v"], "provenance": "unknown"})
    monkeypatch.setattr(R, "_step_rtl_gen_bound", lambda *a, **k: R.StepResult(
        "rtl_gen", "FAIL", 0.0, "an early refusal"))
    res = R.step_rtl_gen(D6._spm_project(tmp_path), ARITH)
    assert res.detail == "an early refusal", res.detail
    assert not (res.extras or {}).get("deferred_generators")


# MINOR — a guard that stepped aside says it was NOT evaluated, not that the
# generator "deferred" as if it applied.
def test_a_skipped_generator_is_recorded_as_not_evaluated(tmp_path, _session):
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/vendor_rtl", "spm.v", D6.SUPPLIED_SPM)
    res = R.step_rtl_gen(p, ARITH, force_regen=True)
    recs = res.extras["deferred_generators"]
    assert recs and all(r["applicability"] == "not_evaluated" for r in recs)
    assert "not run" in res.detail and "deferred to the supplied RTL" \
        not in res.detail



# =========================================================================== #
# review_wave4a (branch D10) MINORs
# =========================================================================== #
def _staged_once(tmp_path):
    p = D6._spm_project(tmp_path)
    own = D6._supply(p, "input/rtl", "spm.v", D6.SUPPLIED_SPM)
    assert C.consume_reused_ip_rtl(p)["staged"] == ["spm.v"]
    return p, own


def test_an_input_changed_after_staging_is_reported(tmp_path):
    p, own = _staged_once(tmp_path)
    own.write_text(own.read_text() + "// revised input\n")
    out = C.consume_reused_ip_rtl(p)
    assert out["supplied_rtl_not_staged"] == ["input/rtl/spm.v"], out


def test_a_deleted_staged_copy_is_reported(tmp_path):
    p, _own = _staged_once(tmp_path)
    (p / "phase2/stage1/rtl/spm.v").unlink()
    (p / "phase2/stage1/rtl/chip_top.v").write_text(
        "module chip_top(input clk); endmodule\n")
    out = C.consume_reused_ip_rtl(p)       # rtl/ is closed: consume skips
    assert out["staged"] == []
    assert out["supplied_rtl_not_staged"] == ["input/rtl/spm.v"], out


def test_an_in_place_edit_of_the_staged_copy_is_not_reported(tmp_path):
    p, _own = _staged_once(tmp_path)
    rtl_spm = p / "phase2/stage1/rtl/spm.v"
    rtl_spm.write_text(rtl_spm.read_text() + "// completed in place\n")
    out = C.consume_reused_ip_rtl(p)
    assert "supplied_rtl_not_staged" not in out, out
    mf = json.loads((p / "phase2/stage1/rtl/SOURCE_MANIFEST.json").read_text())
    assert list(mf["staged_from_input_sha256"]) == ["input/rtl/spm.v"]


def test_mixed_context_stub_and_vendor_ip_hand_off_per_file(tmp_path, _session):
    """A completion stub in input/rtl beside a vendor IP: the stub is the
    starting point (spec-to-rtl), the vendor file is kept as IP; nothing says
    "Do NOT author". RED on 77f5ba13e (one vendor file made it all IP)."""
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/rtl", "spm.v", "module spm(input clk);\n  // TODO\n"
                                        "endmodule\n")
    D6._supply(p, "input/vendor_rtl", "ip_core.v",
               "module ip_core(input clk); endmodule\n")
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["fallback_skill"] == "spec-to-rtl", res.extras
    assert res.extras["supplied_rtl_roles"] == {
        "starting_point": ["input/rtl/spm.v"],
        "reused_ip": ["input/vendor_rtl/ip_core.v"]}
    assert "Do NOT author" not in res.detail
    assert "input/vendor_rtl/ip_core.v" in res.detail


def test_input_source_manifest_declares_reused_ip(tmp_path, _session):
    """`input/SOURCE_MANIFEST.json` reused_ip:true is a supported declaration
    path: RTL under input/rtl it covers is reused IP (catalog-glue). RED on
    77f5ba13e (only the phase2 manifest was read)."""
    p = D6._spm_project(tmp_path)
    D6._supply(p, "input/rtl", "spm.v", D6.SUPPLIED_SPM)
    (p / "input/SOURCE_MANIFEST.json").write_text(json.dumps(
        {"reused_ip": True}))
    res = R.step_rtl_gen(p, ARITH)
    assert res.extras["fallback_skill"] == "catalog-glue-author", res.extras


# =========================================================================== #
# review_wave4c (branch D10)
# =========================================================================== #
_SUPPLIED_OTP = ("// supplied\nmodule otp_mem(input clk, output q);\n"
                 "  assign q = clk;\nendmodule\n")


def test_a_repair_rerun_keeps_the_supplied_module_in_rtl(tmp_path,
                                                        monkeypatch):
    """MAJOR: consume runs once; the repair loop re-runs rtl_gen ALONE (its
    order -- producer, digest, re-dispatch -- is pinned by #2225). A partial
    overlap therefore stages the supplied module itself, so every re-run --
    first pass or repair pass -- leaves it in rtl/. RED before: after the
    re-run no otp_mem was defined at all."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    p = _otp_project(tmp_path / "p")
    _vendor(p, {"otp_mem.v": _SUPPLIED_OTP})
    first = R.step_rtl_gen(p, "mixed_signal_otp")
    assert first.extras["supplied_replaces_generated"]["staged_by_rtl_gen"] \
        == ["otp_mem.v"]
    assert _defs(p, "otp_mem") == 1
    again = R.step_rtl_gen(p, "mixed_signal_otp")    # the repair loop's re-run
    assert again.status == "PASS", again.detail[:300]
    assert _defs(p, "otp_mem") == 1 and _defs(p, "chip_top") == 1
    control = _control_rtl(tmp_path, _otp_project, "mixed_signal_otp")
    assert set(_rtl_files(p)) == (control - {"otp_mem.sv"}) | {"otp_mem.v"}
    assert (p / "phase2/stage1/rtl/otp_mem.v").read_text().startswith(
        "// supplied")
    assert str(p / "phase2/stage1/rtl/otp_mem.v") in again.output_files
    # consume afterwards is a no-op and reports nothing missing
    out = C.consume_reused_ip_rtl(p)
    assert out["staged"] == [] and "supplied_rtl_not_staged" not in out


def test_a_context_file_overlapping_a_generated_module_is_a_hand_off(
        tmp_path, monkeypatch):
    """MAJOR (integrity): a CONTEXT file (input/rtl — e.g. a stub to finish)
    that defines a generated module is the starting point to complete, never
    a silent replacement of a complete generated module."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    p = _otp_project(tmp_path / "p")
    stub = p / "input/rtl/otp_mem.v"
    stub.parent.mkdir(parents=True)
    stub.write_text("module otp_mem(input clk, output q);\n  // TODO\n"
                    "endmodule\n")
    res = R.step_rtl_gen(p, "mixed_signal_otp")
    assert res.status == "PASS_WITH_WAIVERS", res.detail[:300]
    assert res.extras["fallback_skill"] == "spec-to-rtl"
    assert res.extras["supplied_rtl_roles"] == {
        "starting_point": ["input/rtl/otp_mem.v"], "reused_ip": []}
    assert "complete or modify it in place" in res.detail
    assert "Do NOT author" not in res.detail
    assert _defs(p, "chip_top") == 1          # the rest of the design stays
    control = _control_rtl(tmp_path, _otp_project, "mixed_signal_otp")
    assert set(_rtl_files(p)) == (control - {"otp_mem.sv"}) | {"otp_mem.v"}


def test_a_reused_ip_file_still_replaces_silently_with_its_role(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    p = _otp_project(tmp_path / "p")
    _vendor(p, {"otp_mem.v": _SUPPLIED_OTP})
    res = R.step_rtl_gen(p, "mixed_signal_otp")
    assert res.status == "PASS" and not res.extras.get("fallback_skill")
    assert res.extras["supplied_rtl_roles"] == {
        "starting_point": [], "reused_ip": ["input/vendor_rtl/otp_mem.v"]}



# =========================================================================== #
# review_wave7 (branch D10)
# =========================================================================== #
def _control_rtl(tmp_path, mk, cls):
    """The generated file set with NOTHING supplied (the control)."""
    c = mk(tmp_path / "control")
    R._RTL_SESSION_OWNED = False
    R.step_rtl_gen(c, cls)
    R._RTL_SESSION_OWNED = False
    return set(_rtl_files(c))


def test_the_default_flow_still_returns_an_extras_dict(tmp_path, monkeypatch):
    """MAJOR: with nothing supplied, the generator's PASS carried
    `extras=None` (the partial-overlap record's default), so the phase-2
    row read `extras: null` and a finalize cleanup warning raised TypeError
    after rtl/ was published."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    real = R._phase1_finalize_accepted_transaction

    def _warn(tx):
        real(tx)
        return "stage cleanup left a temp dir behind"
    monkeypatch.setattr(R, "_phase1_finalize_accepted_transaction", _warn)
    res = R.step_rtl_gen(_otp_project(tmp_path / "p"), "mixed_signal_otp")
    assert res.status == "PASS", res.detail[:300]
    assert isinstance(res.extras, dict)
    assert res.extras["transaction_cleanup_warning"] == \
        "stage cleanup left a temp dir behind"


def test_only_the_needed_supplied_files_are_staged(tmp_path, monkeypatch):
    """MINOR: the partial path staged EVERY supplied file. Now: the replaced
    module's source plus what it instantiates; an orphan is disclosed."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    p = _otp_project(tmp_path / "p")
    _vendor(p, {
        "otp_mem.v": "// supplied\nmodule otp_mem(input clk, output q);\n"
                     "  otp_cell u (.clk(clk), .q(q));\nendmodule\n",
        "otp_cell.v": "module otp_cell(input clk, output q);\n"
                      "  assign q = clk;\nendmodule\n",
        "orphan.v": "module orphan(input a); endmodule\n"})
    res = R.step_rtl_gen(p, "mixed_signal_otp")
    assert res.status == "PASS", res.detail[:300]
    rec = res.extras["supplied_replaces_generated"]
    assert rec["staged_by_rtl_gen"] == ["otp_cell.v", "otp_mem.v"]
    assert rec["supplied_not_staged"] == ["input/vendor_rtl/orphan.v"]
    assert "orphan.v" not in _rtl_files(p)
    assert "input/vendor_rtl/orphan.v" in res.detail
    mf = json.loads((p / "phase2/stage1/rtl/SOURCE_MANIFEST.json").read_text())
    assert set(mf["staged_from_input_sha256"]) == {
        "input/vendor_rtl/otp_mem.v", "input/vendor_rtl/otp_cell.v"}


def test_a_supplied_module_that_cannot_be_staged_is_refused_and_restored(
        tmp_path, monkeypatch):
    """The post-condition answers NO: the supplied `otp_mem` lives in a file
    named like a generated one (`rx_phy.sv`), first-wins keeps the generated
    file, so `otp_mem` would end up defined 0 times. The generated file is
    restored and the step refuses by name, with the collision."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    p = _otp_project(tmp_path / "p")
    _vendor(p, {"rx_phy.sv": _SUPPLIED_OTP})
    res = R.step_rtl_gen(p, "mixed_signal_otp")
    assert res.status == "FAIL", res.detail[:300]
    assert res.extras["finding"] == "SUPPLIED_MODULE_NOT_STAGED"
    assert res.extras["staged_name_collisions"] == {
        "rx_phy.sv": ["input/vendor_rtl/rx_phy.sv"]}
    assert "otp_mem is defined 0 time(s)" in res.detail
