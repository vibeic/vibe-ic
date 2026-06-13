"""Logic tests for `fix_fault_cut_names.py` (moved from skill in v0.1.50).

Doctrine note: this program was previously hidden inside
`skills/atpg-name-harmonize/`. Per the user's audit (2026-05-29), it was
already-deterministic code mis-housed under skills/, so v0.1.50 moves it
to `programs/` and the skill is retired. These tests pin the rewriter
behavior so any regression is caught by pytest.
"""
import importlib

mod = importlib.import_module("fix_fault_cut_names")


class TestUufRewrites:
    def test_basic_uuf_pin(self):
        before = "  .\\__uuf__._123_ (sig)"
        after, b, a = mod.rewrite(before)
        assert "UUF_123" in after
        assert "__uuf__" not in after
        assert b == 1 and a == 0

    def test_uuf_with_d_suffix(self):
        before = "wire \\__uuf__._99_.d ;"
        after, _, _ = mod.rewrite(before)
        assert "UUF_99_d" in after
        assert "__uuf__" not in after

    def test_uuf_bus_index(self):
        before = "  \\__uuf__._42_[7]"
        after, _, _ = mod.rewrite(before)
        assert "UUF_42_7" in after

    def test_no_uuf_means_no_change(self):
        before = "wire clk;"
        after, b, a = mod.rewrite(before)
        assert after == before
        assert b == 0 and a == 0


class TestBareScanRegister:
    def test_bare_srn_with_d(self):
        before = "  \\_2962_.d "
        after, _, _ = mod.rewrite(before)
        assert "SRN_2962_d" in after

    def test_bare_srn_bus_index(self):
        before = "  \\_500_[3]"
        after, _, _ = mod.rewrite(before)
        assert "SRN_500_3" in after


class TestBoundaryScanRegister:
    def test_input_boundary_scan(self):
        before = "  \\__BoundaryScanRegister_input__7__ "
        after, _, _ = mod.rewrite(before)
        assert "BSR_in_7" in after

    def test_output_boundary_scan(self):
        before = "  \\__BoundaryScanRegister_output__12__ "
        after, _, _ = mod.rewrite(before)
        assert "BSR_out_12" in after

    def test_boundary_scan_with_subfield(self):
        before = "  \\__BoundaryScanRegister_input__3__data "
        after, _, _ = mod.rewrite(before)
        assert "BSR_in_3_data" in after


class TestCatchAllEscapedDottyIds:
    def test_catchall_replaces_dot_in_escape(self):
        before = "  \\my_thing.x "
        after, _, _ = mod.rewrite(before)
        assert "my_thing_x" in after
        assert "\\my_thing" not in after

    def test_catchall_replaces_brackets(self):
        before = "  \\bus[7] "
        after, _, _ = mod.rewrite(before)
        assert "bus_7" in after


class TestCounters:
    def test_before_after_uuf_counters(self):
        before = "  \\__uuf__._1_ \\__uuf__._2_ \\__uuf__._3_ "
        after, b, a = mod.rewrite(before)
        # All three UUF tokens should be rewritten
        assert b == 3
        assert a == 0
        # And three UUF_N tokens should appear
        assert after.count("UUF_") == 3


class TestIdempotence:
    def test_already_rewritten_text_is_stable(self):
        once, _, _ = mod.rewrite("  \\__uuf__._5_.d ")
        twice, _, _ = mod.rewrite(once)
        assert once == twice
