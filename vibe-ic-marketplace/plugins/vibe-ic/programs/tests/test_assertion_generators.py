"""Unit tests for the 3 assertion-gen scripts:
  - tristate_bus_check.py
  - protocol_gap_check.py
  - rx_tolerance_sweep.py
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent
BUS_SCRIPT = SCRIPTS_DIR / 'tristate_bus_check.py'
GAP_SCRIPT = SCRIPTS_DIR / 'protocol_gap_check.py'
RX_SCRIPT = SCRIPTS_DIR / 'rx_tolerance_sweep.py'
for s in (BUS_SCRIPT, GAP_SCRIPT, RX_SCRIPT):
    assert s.exists(), s

sys.path.insert(0, str(SCRIPTS_DIR))
import tristate_bus_check as tbc     # noqa: E402
import protocol_gap_check as pgc     # noqa: E402
import rx_tolerance_sweep as rts     # noqa: E402


# ===========================================================================
# tristate_bus_check.py
# ===========================================================================
class TestTristateBusCheck:
    def _run(self, tmp_path, **kw):
        args = [sys.executable, str(BUS_SCRIPT),
                '--bus-name', kw.get('bus_name', 'id_bus'),
                '--drivers', kw.get('drivers', 'mac_tx_oe,wake_oe'),
                '--sync-depth', str(kw.get('sync_depth', 3)),
                '--out-dir', str(tmp_path)]
        if kw.get('mutex'):
            args += ['--mutex', kw['mutex']]
        return subprocess.run(args, capture_output=True, text=True)

    def test_generates_three_files(self, tmp_path):
        res = self._run(tmp_path)
        assert res.returncode == 0, res.stderr
        assert (tmp_path / 'id_bus_check_assertions.sv').exists()
        assert (tmp_path / 'id_bus_check.sby').exists()
        assert (tmp_path / 'README_id_bus.md').exists()

    def test_sva_contains_single_driver_assertion(self, tmp_path):
        self._run(tmp_path, drivers='a,b,c')
        sva = (tmp_path / 'id_bus_check_assertions.sv').read_text()
        assert 'a_single_driver' in sva
        # Sum of OE signals
        assert '(a + b + c)' in sva or 'a + b + c' in sva
        # Assertion that sum <= 1
        assert '<= 1' in sva

    def test_sva_contains_readback_property_per_driver(self, tmp_path):
        self._run(tmp_path, drivers='drv1,drv2', sync_depth=4)
        sva = (tmp_path / 'id_bus_check_assertions.sv').read_text()
        assert 'a_readback_drv1' in sva
        assert 'a_readback_drv2' in sva
        assert '##4' in sva

    def test_mutex_pairs_emitted(self, tmp_path):
        self._run(tmp_path, drivers='wake_oe,tx_oe',
                  mutex='wake_oe:tx_oe,wake_oe:rx_active')
        sva = (tmp_path / 'id_bus_check_assertions.sv').read_text()
        assert 'a_mutex_wake_oe_tx_oe' in sva
        assert 'a_mutex_wake_oe_rx_active' in sva
        assert '!(wake_oe && tx_oe)' in sva

    def test_readme_mentions_config(self, tmp_path):
        self._run(tmp_path, bus_name='i2c_sda', drivers='master,slave',
                  sync_depth=2)
        readme = (tmp_path / 'README_i2c_sda.md').read_text()
        assert 'i2c_sda' in readme
        assert 'master' in readme and 'slave' in readme
        assert '2 cycles' in readme

    def test_sby_file_is_syntactically_valid(self, tmp_path):
        self._run(tmp_path)
        sby = (tmp_path / 'id_bus_check.sby').read_text()
        # Required SBY sections
        assert '[options]' in sby
        assert '[engines]' in sby
        assert '[script]' in sby
        assert '[files]' in sby
        assert 'smtbmc' in sby

    def test_sync_depth_zero_rejected(self, tmp_path):
        res = self._run(tmp_path, sync_depth=0)
        assert res.returncode == 2, res.stdout + res.stderr


# ===========================================================================
# protocol_gap_check.py
# ===========================================================================
class TestProtocolGapCheck:
    def _run(self, tmp_path, **kw):
        args = [sys.executable, str(GAP_SCRIPT),
                '--name', kw.get('name', 'p1'),
                '--end-signal', kw.get('end', 'byte_done'),
                '--bus-idle', kw.get('idle', '!oe'),
                '--min-cycles', str(kw.get('min_c', 10)),
                '--out-dir', str(tmp_path)]
        if kw.get('max_c'):
            args += ['--max-cycles', str(kw['max_c'])]
        return subprocess.run(args, capture_output=True, text=True)

    def test_min_gap_property_present(self, tmp_path):
        self._run(tmp_path, name='uart', end='tx_done',
                  idle='tx_line', min_c=16)
        sva = (tmp_path / 'uart_gap_assertions.sv').read_text()
        assert 'p_min_gap' in sva
        assert 'a_min_gap' in sva
        assert 'bus_idle[*16]' in sva

    def test_no_max_by_default(self, tmp_path):
        self._run(tmp_path, min_c=5)
        sva = (tmp_path / 'p1_gap_assertions.sv').read_text()
        assert 'p_max_gap_timeout' not in sva

    def test_max_cycles_enables_cover(self, tmp_path):
        self._run(tmp_path, min_c=5, max_c=100)
        sva = (tmp_path / 'p1_gap_assertions.sv').read_text()
        assert 'p_max_gap_timeout' in sva
        assert 'cov_max_gap_timeout' in sva
        assert 'bus_idle[*100]' in sva

    def test_zero_min_cycles_rejected(self, tmp_path):
        res = self._run(tmp_path, min_c=0)
        assert res.returncode == 2, res.stdout + res.stderr

    def test_cover_property_always_emitted(self, tmp_path):
        self._run(tmp_path, name='any', end='x_done', min_c=3)
        sva = (tmp_path / 'any_gap_assertions.sv').read_text()
        assert 'cov_end_pulse' in sva

    def test_sby_depth_scales_with_cycles(self, tmp_path):
        self._run(tmp_path, min_c=200, max_c=500)
        sby = (tmp_path / 'p1_gap.sby').read_text()
        # Depth must exceed max(min, max) cycles
        assert 'depth 510' in sby


# ===========================================================================
# rx_tolerance_sweep.py
# ===========================================================================
class TestRxToleranceSweep:
    def _write_table(self, tmp_path, table):
        p = tmp_path / 'table.json'
        p.write_text(json.dumps(table))
        return p

    def _run(self, tmp_path, table):
        tp = self._write_table(tmp_path, table)
        out = tmp_path / 'out.json'
        res = subprocess.run(
            [sys.executable, str(RX_SCRIPT),
             '--decode-table', str(tp), '--json-out', str(out)],
            capture_output=True, text=True)
        findings = json.loads(out.read_text()) if out.exists() else None
        return res, findings

    def test_detects_width8_gap_lightning(self, tmp_path):
        """This is the exact USB-HID tester bug #2: H1=1..7, H0=9..23 leaves gap at 8."""
        table = {
            "max_width": 30,
            "symbols": [
                {"name": "H1", "widths": list(range(1, 8))},
                {"name": "H0", "widths": list(range(9, 24))},
            ]
        }
        res, data = self._run(tmp_path, table)
        assert res.returncode == 1, "should flag findings"
        gap_widths = [f['width'] for f in data['findings']
                      if f['kind'] == 'gap']
        assert 8 in gap_widths

    def test_detects_overlap(self, tmp_path):
        table = {
            "max_width": 10,
            "symbols": [
                {"name": "A", "widths": [1, 2, 3]},
                {"name": "B", "widths": [3, 4, 5]},   # overlap at 3
            ]
        }
        _, data = self._run(tmp_path, table)
        overlap = [f for f in data['findings'] if f['kind'] == 'overlap']
        assert len(overlap) == 1
        assert overlap[0]['width'] == 3
        assert set(overlap[0]['symbols']) == {'A', 'B'}

    def test_detects_boundary_asymmetry(self, tmp_path):
        table = {
            "max_width": 10,
            "symbols": [
                {"name": "A", "widths": [1, 2, 3]},
                {"name": "B", "widths": [5, 6]},
            ]
        }
        _, data = self._run(tmp_path, table)
        bas = [f for f in data['findings']
               if f['kind'] == 'boundary-asymmetry']
        assert len(bas) >= 1

    def test_clean_table_reports_no_gaps(self, tmp_path):
        """Every width from 1 to max covered contiguously → no findings at all."""
        table = {
            "max_width": 6,
            "symbols": [
                {"name": "X", "widths": [1, 2, 3]},
                {"name": "Y", "widths": [4, 5, 6]},
            ]
        }
        res, data = self._run(tmp_path, table)
        assert res.returncode == 0, \
            f"clean table must have zero findings, got: {data['findings']}"
        assert data['findings'] == []

    def test_jitter_robustness_scores_in_report(self, tmp_path):
        table = {
            "max_width": 10,
            "symbols": [{"name": "X", "widths": [5, 6, 7]}]
        }
        _, data = self._run(tmp_path, table)
        # Robustness field should exist and be a float in [0,1]
        assert 'jitter_robustness' in data
        assert 0.0 <= data['jitter_robustness']['X'] <= 1.0

    def test_analyze_function_unit(self):
        """Direct white-box test of analyze()."""
        table = {
            "max_width": 5,
            "symbols": [
                {"name": "A", "widths": [1, 2]},
                {"name": "B", "widths": [4, 5]},
            ]
        }
        findings = rts.analyze(table)
        gap_widths = [f.width for f in findings if f.kind == 'gap']
        assert gap_widths == [3]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
