"""Unit tests for `protocol_timeline_assert_gen.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("protocol_timeline_assert_gen")


class TestExtractParams:
    def test_complete_l2(self):
        l2 = {
            "clock_period_ns": 10,
            "delimiter_typical_ns": 5000,
            "turnaround_min_ns": 8000,
            "turnaround_max_ns": 12000,
            "spec_ref": "DS § 8.3",
        }
        p = mod.extract_params(l2, tx_start_signal="resp_start")
        assert p.clock_period_ns == 10
        assert p.delimiter_typical_ns == 5000
        assert p.t_turnaround_min_ns == 8000
        assert p.t_turnaround_max_ns == 12000
        assert p.tx_start_signal == "resp_start"
        assert p.spec_section == "DS § 8.3"
        assert p.is_complete()

    def test_nested_clock(self):
        l2 = {"clock": {"period_ns": 4}}
        p = mod.extract_params(l2)
        assert p.clock_period_ns == 4

    def test_missing_returns_zero(self):
        p = mod.extract_params({})
        assert not p.is_complete()
        assert p.clock_period_ns == 0


class TestEmitTb:
    def _params(self):
        return mod.TurnaroundParams(
            clock_period_ns=10,
            delimiter_typical_ns=5000,
            t_turnaround_min_ns=8000,
            t_turnaround_max_ns=12000,
            tx_start_signal="tx_start",
            spec_section="DS § 8.3",
        )

    def test_has_cocotb_imports(self):
        tb = mod.emit_tb(self._params())
        assert "import cocotb" in tb
        assert "from cocotb.clock import Clock" in tb

    def test_constants_substituted(self):
        tb = mod.emit_tb(self._params())
        assert "CLOCK_PERIOD_NS                = 10" in tb
        assert "T_TURNAROUND_MIN_NS            = 8000" in tb
        assert "T_TURNAROUND_MAX_NS            = 12000" in tb
        assert 'TX_START_SIGNAL                = "tx_start"' in tb
        assert 'SPEC_SECTION                   = "DS § 8.3"' in tb

    def test_attribution(self):
        tb = mod.emit_tb(self._params())
        assert f"(Vibe-IC plugin v{shipped_plugin_version()})." in tb
        assert "protocol_timeline_assert_gen.py" in tb
        assert "Do not edit; regenerate" in tb

    def test_assert_statement_present(self):
        tb = mod.emit_tb(self._params())
        assert "T_TURNAROUND_MIN_NS <= turnaround_ns <= T_TURNAROUND_MAX_NS" in tb

    def test_idempotent_emit(self):
        a = mod.emit_tb(self._params())
        b = mod.emit_tb(self._params())
        assert a == b


class TestParamsValidation:
    def test_max_below_min_incomplete(self):
        p = mod.TurnaroundParams(10, 5, 100, 50, "tx_start", "x")
        assert not p.is_complete()

    def test_zero_clock_incomplete(self):
        p = mod.TurnaroundParams(0, 5, 100, 200, "tx_start", "x")
        assert not p.is_complete()

    def test_empty_signal_incomplete(self):
        p = mod.TurnaroundParams(10, 5, 100, 200, "", "x")
        assert not p.is_complete()
