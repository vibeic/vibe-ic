"""Unit tests for `xor_layout_check.py`.

Pin the deterministic verdict logic + the §4.05 honesty invariants of the XOR
layout sign-off gate:

  (a) synthetic zero-delta XOR report            -> PASS
  (b) residual on met1                           -> FAIL naming the layer + area
  (c) residual only inside an allow-listed macro -> PASS_WITH_WAIVER
  (d) residual OUTSIDE the allow-list            -> FAIL  (§4.05 negative — a
                                                    waiver must NOT swallow a
                                                    real, out-of-macro delta)
  (e) absent report                              -> INCOMPLETE, never PASS

Plus emit-script coverage and a few defensive edges (unattributed residual,
mixed waived+outside, script-error report).
"""
import importlib
import json

import pytest

mod = importlib.import_module("xor_layout_check")


# ---------------------------------------------------------------------------
# Report fixtures
# ---------------------------------------------------------------------------
def _zero_delta_report():
    return {
        "tool": "klayout-xor",
        "top": "user_project_wrapper",
        "layout_under_test": "assembled.gds",
        "golden_reference": "golden.gds",
        "dbu": 0.001,
        "total_residual_count": 0,
        "total_residual_area_um2": 0.0,
        "layers": [],
    }


def _residual_report(by_cell, layer="met1", count=3, area=1.25):
    """A report with residual on one layer, attributed per `by_cell`."""
    return {
        "tool": "klayout-xor",
        "top": "user_project_wrapper",
        "layout_under_test": "assembled.gds",
        "golden_reference": "golden.gds",
        "dbu": 0.001,
        "total_residual_count": count,
        "total_residual_area_um2": area,
        "layers": [
            {"layer": layer, "residual_count": count,
             "residual_area_um2": area, "by_cell": by_cell},
        ],
    }


def _write(tmp_path, obj, name="xor_report.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# (a) zero-delta -> PASS
# ---------------------------------------------------------------------------
class TestZeroDeltaPass:
    def test_classify_zero_delta_is_pass(self):
        verdict, waived, failing = mod.classify_report(_zero_delta_report(), [])
        assert verdict == "PASS"
        assert waived == []
        assert failing == []

    def test_evaluate_zero_delta_is_pass(self, tmp_path):
        rp = _write(tmp_path, _zero_delta_report())
        res = mod.evaluate(rp, [])
        assert res["verdict"] == "PASS"
        assert res["failing_residual"] == []
        assert mod.verdict_exit_code(res["verdict"]) == 0


# ---------------------------------------------------------------------------
# (b) residual on met1 -> FAIL naming layer + area
# ---------------------------------------------------------------------------
class TestResidualFail:
    def test_unattributed_met1_residual_fails_naming_layer_and_area(self, tmp_path):
        # No by_cell attribution at all -> cannot be waived.
        rep = _residual_report(by_cell=[], layer="met1", count=3, area=1.25)
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=[])
        assert res["verdict"] == "FAIL"
        assert mod.verdict_exit_code(res["verdict"]) == 1
        assert len(res["failing_residual"]) == 1
        f = res["failing_residual"][0]
        assert f["layer"] == "met1"
        assert f["area_um2"] == pytest.approx(1.25)
        assert f["count"] == 3

    def test_outside_bucket_residual_fails(self, tmp_path):
        rep = _residual_report(
            by_cell=[{"cell": mod.OUTSIDE_SENTINEL, "count": 3, "area_um2": 1.25}],
            layer="met1")
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["sram_macro"])
        assert res["verdict"] == "FAIL"
        assert res["failing_residual"][0]["layer"] == "met1"


# ---------------------------------------------------------------------------
# (c) residual only inside an allow-listed macro -> PASS_WITH_WAIVER
# ---------------------------------------------------------------------------
class TestBlackboxWaiver:
    def test_residual_inside_allowlisted_macro_is_documented_waiver(self, tmp_path):
        rep = _residual_report(
            by_cell=[{"cell": "sram_1kbyte_1rw", "count": 3, "area_um2": 1.25}],
            layer="met1")
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["sram_1kbyte_1rw"])
        assert res["verdict"] == "PASS_WITH_WAIVER"
        assert res["failing_residual"] == []
        assert len(res["waived_residual"]) == 1
        w = res["waived_residual"][0]
        assert w["cell"] == "sram_1kbyte_1rw"
        assert w["layer"] == "met1"
        # A PASS-with-waiver is still a success exit.
        assert mod.verdict_exit_code(res["verdict"]) == 0


# ---------------------------------------------------------------------------
# (d) §4.05 negative: residual OUTSIDE the allow-list -> FAIL
# ---------------------------------------------------------------------------
class TestForbiddenWaiverSwallow:
    def test_residual_on_non_allowlisted_cell_still_fails(self, tmp_path):
        # A real logic cell delta — NOT a documented blackbox macro.
        rep = _residual_report(
            by_cell=[{"cell": "user_adder", "count": 4, "area_um2": 2.0}],
            layer="met2")
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["sram_1kbyte_1rw"])
        assert res["verdict"] == "FAIL", (
            "a waiver allow-list must NEVER swallow a delta on a cell that is "
            "not explicitly allow-listed (§4.05)")
        assert res["waived_residual"] == []
        f = res["failing_residual"][0]
        assert f["cell"] == "user_adder"
        assert f["layer"] == "met2"

    def test_mixed_waived_and_outside_delta_fails_overall(self, tmp_path):
        # Part inside an allow-listed macro (waivable) AND part outside every
        # macro (a real delta). Overall MUST fail — the waiver cannot hide the
        # out-of-macro part.
        rep = _residual_report(
            by_cell=[
                {"cell": "sram_1kbyte_1rw", "count": 2, "area_um2": 0.5},
                {"cell": mod.OUTSIDE_SENTINEL, "count": 1, "area_um2": 0.3},
            ],
            layer="met1", count=3, area=0.8)
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["sram_1kbyte_1rw"])
        assert res["verdict"] == "FAIL"
        assert len(res["waived_residual"]) == 1     # the macro part is recorded
        assert len(res["failing_residual"]) == 1    # the outside part fails
        assert res["failing_residual"][0]["cell"] == mod.OUTSIDE_SENTINEL

    def test_empty_allowlist_cannot_waive_anything(self, tmp_path):
        rep = _residual_report(
            by_cell=[{"cell": "sram_1kbyte_1rw", "count": 3, "area_um2": 1.25}])
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=[])
        assert res["verdict"] == "FAIL"

    def test_positive_total_no_breakdown_fails(self, tmp_path):
        # Malformed/short report: claims a delta but attributes nothing.
        rep = {"tool": "klayout-xor", "top": "t",
               "total_residual_count": 5, "total_residual_area_um2": 9.0,
               "layers": []}
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["sram_1kbyte_1rw"])
        assert res["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# Inert allow-list advisory (live-driven, from the real caravel full-chip run):
# `--allow-macro spm` at `--top caravel` is a silent no-op because `spm` is
# nested (caravel -> caravel_core -> user_project_wrapper -> spm) and the
# macro-bbox attribution keys only on the DIRECT children of the XOR top, so the
# residual is attributed to `caravel_core`/`chip_io` and `spm` never appears.
# The advisory surfaces that inert waiver (never changes the verdict, §4.05).
# ---------------------------------------------------------------------------
class TestInertAllowMacroAdvisory:
    def test_nested_macro_allowlist_is_flagged_inert_at_wrong_top(self, tmp_path):
        # Mirrors the live caravel run: residual attributed to `caravel_core`
        # while the submitter allow-lists `spm` (nested one+ level deeper).
        rep = _residual_report(
            by_cell=[{"cell": "caravel_core", "count": 33227, "area_um2": 960.26}],
            layer="66/44", count=33227, area=960.26)
        rep["top"] = "caravel"
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["spm"])
        # Verdict is unchanged (still a real out-of-macro delta -> FAIL).
        assert res["verdict"] == "FAIL"
        assert res["waived_residual"] == []
        # The advisory names the inert allow-list entry.
        assert res["inert_allow_macros"] == ["spm"]
        assert res["advisories"], "an inert waiver with residual must be surfaced"
        assert "spm" in res["advisories"][0]
        assert "caravel" in res["advisories"][0]

    def test_matched_allowlist_is_not_flagged_inert(self, tmp_path):
        # The allow-listed macro DID get residual attributed -> not inert.
        rep = _residual_report(
            by_cell=[{"cell": "spm", "count": 3, "area_um2": 1.25}], layer="met1")
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["spm"])
        assert res["verdict"] == "PASS_WITH_WAIVER"
        assert res["inert_allow_macros"] == []
        assert res["advisories"] == []

    def test_zero_delta_pass_does_not_warn_on_unused_allowlist(self, tmp_path):
        # A clean PASS with an unused allow-list is benign: no residual exists,
        # so an unmatched allow-macro must NOT raise a (spurious) advisory.
        rp = _write(tmp_path, _zero_delta_report())
        res = mod.evaluate(rp, allow_macros=["spm"])
        assert res["verdict"] == "PASS"
        assert res["inert_allow_macros"] == ["spm"]   # factual: matched nothing
        assert res["advisories"] == []                # but no residual -> no warn

    def test_advisory_never_upgrades_or_downgrades_verdict(self, tmp_path):
        # A mixed report: allow-listed macro matched (waived) AND an inert entry.
        rep = _residual_report(
            by_cell=[
                {"cell": "spm", "count": 2, "area_um2": 0.5},
                {"cell": mod.OUTSIDE_SENTINEL, "count": 1, "area_um2": 0.3},
            ], layer="met1", count=3, area=0.8)
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=["spm", "not_present_macro"])
        assert res["verdict"] == "FAIL"                      # unchanged
        assert res["inert_allow_macros"] == ["not_present_macro"]
        assert any("not_present_macro" in a for a in res["advisories"])


# ---------------------------------------------------------------------------
# (e) absent report / GDS -> INCOMPLETE, never PASS
# ---------------------------------------------------------------------------
class TestIncompleteNeverPass:
    def test_absent_report_is_incomplete(self, tmp_path):
        res = mod.evaluate(tmp_path / "does_not_exist.json", allow_macros=[])
        assert res["verdict"] == "INCOMPLETE"
        assert res["verdict"] != "PASS"
        assert "absent" in res["incomplete_reason"]
        assert mod.verdict_exit_code(res["verdict"]) == 2

    def test_none_report_is_incomplete(self):
        res = mod.evaluate(None, allow_macros=[])
        assert res["verdict"] == "INCOMPLETE"

    def test_unparseable_report_is_incomplete(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        res = mod.evaluate(p, allow_macros=[])
        assert res["verdict"] == "INCOMPLETE"
        assert "unparseable" in res["incomplete_reason"]

    def test_absent_gds_is_incomplete_even_with_a_report(self, tmp_path):
        rp = _write(tmp_path, _zero_delta_report())
        res = mod.evaluate(rp, allow_macros=[],
                           layout_under_test=tmp_path / "missing.gds")
        assert res["verdict"] == "INCOMPLETE"
        assert "GDS absent" in res["incomplete_reason"]

    def test_script_error_report_is_incomplete(self, tmp_path):
        rep = {"tool": "klayout-xor", "top": "user_project_wrapper",
               "error": "top cell not found in one/both layouts"}
        rp = _write(tmp_path, rep)
        res = mod.evaluate(rp, allow_macros=[])
        assert res["verdict"] == "INCOMPLETE"
        assert "error" in res["incomplete_reason"].lower()


# ---------------------------------------------------------------------------
# (a) emit — the KLayout XOR script
# ---------------------------------------------------------------------------
class TestEmitScript:
    def test_emit_contains_core_xor_ops(self):
        s = mod.emit_xor_script(
            "user_project_wrapper", "assembled.gds", "golden.gds",
            "xor_report.json")
        # Standard pya layer-by-layer boolean XOR + report write.
        assert "import pya" in s
        assert "ra ^ rb" in s               # the per-layer XOR
        assert "find_layer" in s            # layer matching across layouts
        assert "begin_shapes_rec" in s      # flattened per-layer shapes
        assert "json.dump" in s             # writes a machine-readable report
        assert mod.OUTSIDE_SENTINEL in s    # outside-macro sentinel bucket
        # Regression (live-validated): the per-macro attribution path must copy
        # a Region with .dup(), NOT the pya.Region(<region>) copy-constructor,
        # which this KLayout build rejects on the residual path (the zero-delta
        # path never hits it, so only a live run with a real delta catches it).
        assert "xor.dup()" in s
        assert "pya.Region(xor)" not in s

    def test_emit_embeds_top_and_paths(self):
        s = mod.emit_xor_script(
            "caravel", "chip.gds", "golden_caravel.gds", "out/rep.json")
        assert "caravel" in s
        assert "chip.gds" in s
        assert "golden_caravel.gds" in s
        assert "out/rep.json" in s

    def test_emitted_script_is_valid_python(self):
        s = mod.emit_xor_script("t", "a.gds", "b.gds", "r.json")
        compile(s, "<emitted-xor-script>", "exec")  # must parse

    def test_command_hint_is_batch_klayout(self):
        hint = mod.klayout_command_hint("/tmp/xor.py")
        assert "klayout" in hint and "-b -r" in hint and "/tmp/xor.py" in hint


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------
class TestCli:
    def test_cli_emit_writes_script(self, tmp_path):
        script = tmp_path / "xor.py"
        rc = mod._cli([
            "--emit-script", str(script),
            "--top", "user_project_wrapper",
            "--layout", str(tmp_path / "a.gds"),
            "--golden", str(tmp_path / "b.gds"),
            "--report-out", str(tmp_path / "rep.json"),
        ])
        assert rc == 0
        assert script.is_file()
        assert "ra ^ rb" in script.read_text(encoding="utf-8")

    def test_cli_report_pass_exit_zero(self, tmp_path, capsys):
        rp = _write(tmp_path, _zero_delta_report())
        rc = mod._cli(["--report", str(rp)])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"

    def test_cli_report_fail_exit_one(self, tmp_path, capsys):
        rep = _residual_report(
            by_cell=[{"cell": "user_adder", "count": 1, "area_um2": 0.1}])
        rp = _write(tmp_path, rep)
        rc = mod._cli(["--report", str(rp), "--allow-macro", "sram_1kbyte_1rw"])
        assert rc == 1
        assert json.loads(capsys.readouterr().out)["verdict"] == "FAIL"

    def test_cli_report_incomplete_exit_two(self, tmp_path, capsys):
        rc = mod._cli(["--report", str(tmp_path / "nope.json")])
        assert rc == 2
        assert json.loads(capsys.readouterr().out)["verdict"] == "INCOMPLETE"


# ---------------------------------------------------------------------------
# Nested-macro waiver — the emit script threads the allow-list in and discovers
# an allow-listed macro RECURSIVELY (any depth below --top), so `--allow-macro
# spm` at `--top caravel` is effective even though spm is nested (caravel ->
# caravel_core -> user_project_wrapper -> spm), NOT a silent no-op. §4.05 is
# preserved: residual OUTSIDE the nested macro still FAILs.
# ---------------------------------------------------------------------------
class TestEmitNestedAllowMacro:
    def test_emit_threads_allow_macros_into_script(self):
        s = mod.emit_xor_script(
            "caravel", "chip.gds", "golden_caravel.gds", "rep.json",
            allow_macros=["spm"])
        # The waiver allow-list is embedded so the script can act on it.
        assert "ALLOW_MACROS = " in s
        assert "'spm'" in s
        compile(s, "<emit-nested>", "exec")   # still valid Python

    def test_emit_has_recursive_nested_bbox_discovery(self):
        s = mod.emit_xor_script(
            "caravel", "chip.gds", "golden_caravel.gds", "rep.json",
            allow_macros=["spm"])
        # A recursive walk of the hierarchy that transforms each nested macro
        # placement's bbox into TOP coordinates (this is what reaches `spm`).
        assert "_macro_region_in_top" in s
        assert "each_inst()" in s
        assert "cell_index" in s
        assert "transformed(" in s          # bbox -> top coordinates
        assert "each_cplx_trans" in s       # array-aware placement transforms

    def test_emit_partitions_with_allowlisted_macros_first(self):
        s = mod.emit_xor_script(
            "caravel", "chip.gds", "golden_caravel.gds", "rep.json",
            allow_macros=["spm"])
        # §4.05 in the emitter: allow-listed macros are ordered FIRST and each
        # claimed region is carved out of `remaining` (a true partition). The
        # intersection is with the macro bbox ONLY, so a waiver can never claim
        # residual outside its own macro.
        assert "allow_first" in s
        assert "ordered_cells" in s
        assert "remaining.dup() &" in s        # intersect residual w/ macro bbox
        assert "remaining - macro_boxes" in s  # carve the claimed region out

    def test_emit_empty_allowlist_is_valid_and_inert(self):
        s = mod.emit_xor_script("t", "a.gds", "b.gds", "r.json")
        assert "ALLOW_MACROS = []" in s
        compile(s, "<emit-empty>", "exec")


class TestNestedMacroWaiver:
    def _nested_report(self, by_cell, layer="met1", count=3, area=1.25):
        rep = _residual_report(by_cell, layer=layer, count=count, area=area)
        rep["top"] = "caravel"       # full-chip top, spm is nested below it
        return rep

    def test_nested_macro_residual_is_waived_at_fullchip_top(self, tmp_path):
        # Residual genuinely INSIDE the nested `spm` macro (attributed to `spm`
        # by the recursive emit script) -> WAIVED at --top caravel.
        rp = _write(tmp_path, self._nested_report(
            [{"cell": "spm", "count": 3, "area_um2": 1.25}]))
        res = mod.evaluate(rp, allow_macros=["spm"])
        assert res["verdict"] == "PASS_WITH_WAIVER"
        assert res["waived_residual"][0]["cell"] == "spm"
        assert res["failing_residual"] == []
        assert res["inert_allow_macros"] == []   # spm matched -> not inert
        assert res["advisories"] == []
        assert mod.verdict_exit_code(res["verdict"]) == 0

    def test_out_of_nested_macro_delta_still_fails_at_fullchip_top(self, tmp_path):
        # §4.05 NEGATIVE (load-bearing): a residual OUTSIDE the nested spm macro
        # at --top caravel must STILL FAIL even with --allow-macro spm. A nested
        # waiver can NEVER launder an out-of-macro delta.
        rp = _write(tmp_path, self._nested_report(
            [{"cell": mod.OUTSIDE_SENTINEL, "count": 4, "area_um2": 2.0}],
            layer="met2", count=4, area=2.0))
        res = mod.evaluate(rp, allow_macros=["spm"])
        assert res["verdict"] == "FAIL", (
            "an out-of-nested-macro delta at --top caravel must not be laundered "
            "by --allow-macro spm (§4.05)")
        assert res["waived_residual"] == []
        assert res["failing_residual"][0]["cell"] == mod.OUTSIDE_SENTINEL
        assert mod.verdict_exit_code(res["verdict"]) == 1

    def test_straddling_nested_macro_outside_part_fails(self, tmp_path):
        # A straddling residual: part inside the nested spm (waivable) + part
        # outside (a real delta). Overall FAILs; the spm part is recorded waived,
        # the outside part fails — the outside part is never laundered (§4.05).
        rp = _write(tmp_path, self._nested_report(
            [{"cell": "spm", "count": 2, "area_um2": 0.5},
             {"cell": mod.OUTSIDE_SENTINEL, "count": 1, "area_um2": 0.3}],
            layer="met1", count=3, area=0.8))
        res = mod.evaluate(rp, allow_macros=["spm"])
        assert res["verdict"] == "FAIL"
        assert len(res["waived_residual"]) == 1
        assert res["waived_residual"][0]["cell"] == "spm"
        assert len(res["failing_residual"]) == 1
        assert res["failing_residual"][0]["cell"] == mod.OUTSIDE_SENTINEL

    def test_residual_on_nonallowlisted_sibling_still_fails(self, tmp_path):
        # Residual attributed to a non-allow-listed DIRECT child (caravel_core),
        # spm allow-listed but got no bucket -> FAIL + inert advisory for spm.
        rp = _write(tmp_path, self._nested_report(
            [{"cell": "caravel_core", "count": 5, "area_um2": 3.0}],
            layer="met3", count=5, area=3.0))
        res = mod.evaluate(rp, allow_macros=["spm"])
        assert res["verdict"] == "FAIL"
        assert res["failing_residual"][0]["cell"] == "caravel_core"
        assert res["inert_allow_macros"] == ["spm"]   # spm matched nothing
        assert res["advisories"]                       # surfaced as inert
        assert "spm" in res["advisories"][0]


# --- the exit code is what the sign-off ladder reads, and no test drove _cli()

class TestCliExitCode:
    """`gate_cli_mutation_probe` reported this gate SILENT.

    464 lines of tests, organised in eight classes, all driving `evaluate()`
    and asserting the VERDICT. The sign-off ladder reads the EXIT CODE, and
    nothing exercised the mapping — so a residual-XOR FAIL could have started
    exiting 0 with every one of those classes still green.

    It was NO_ENTRY before that: `_cli()` is the entry point (not `main()`) and
    its `__main__` guard carries a trailing `# pragma: no cover`, which the
    probe's `:\n`-anchored pattern could not match. The probe was widened; the
    gap it then exposed is this one.
    """

    def test_a_residual_report_exits_non_zero(self, tmp_path):
        import xor_layout_check as X
        rpt = _write(tmp_path, _residual_report(by_cell=[], layer="met1"))
        rc = X._cli(["--report", str(rpt), "--top", "user_project_wrapper"])
        assert rc != 0, f"a residual XOR exited {rc}"

    def test_a_zero_delta_report_exits_zero(self, tmp_path):
        """The other direction, or the test above is met by always failing."""
        import xor_layout_check as X
        rpt = _write(tmp_path, _zero_delta_report())
        assert X._cli(["--report", str(rpt), "--top", "user_project_wrapper"]) == 0

    def test_a_missing_report_is_a_usage_error(self, tmp_path):
        """rc 2 — could not ask, distinct from a verdict about the layout."""
        import xor_layout_check as X
        assert X._cli(["--report", str(tmp_path / "nope.json")]) == 2
