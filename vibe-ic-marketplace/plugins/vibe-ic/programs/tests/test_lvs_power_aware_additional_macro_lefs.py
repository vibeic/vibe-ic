#!/usr/bin/env python3
"""Power-aware LVS must model physical IO macros from their own LEFs."""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import lvs_power_aware_netlist_emit as E  # noqa: E402


NETLIST = """module chip_top (input a, output y);
  gf180mcu_fd_sc_mcu7t5v0__inv_1 u_core (.I(a), .ZN(y));
  sample_io_in u_pad (.PAD(a), .Y(y));
  sample_io_fill u_fill ();
endmodule
"""


IO_LEF = """VERSION 5.8 ;
MACRO sample_io_in
  PIN PAD
    DIRECTION INPUT ;
  END PAD
  PIN DVDD
    USE POWER ;
  END DVDD
  PIN DVSS
    USE GROUND ;
  END DVSS
  PIN VDD
    USE POWER ;
  END VDD
  PIN VSS
    USE GROUND ;
  END VSS
END sample_io_in
MACRO sample_io_fill
  PIN DVDD
    USE POWER ;
  END DVDD
  PIN DVSS
    USE GROUND ;
  END DVSS
  PIN VDD
    USE POWER ;
  END VDD
  PIN VSS
    USE GROUND ;
  END VSS
END sample_io_fill
END LIBRARY
"""


def test_additional_macro_lef_patches_signal_and_physical_only_io(tmp_path):
    io_lef = tmp_path / "io.extract.lef"
    io_lef.write_text(IO_LEF)
    out, stats = E.emit_power_aware_netlist(
        NETLIST, "gf180mcuD", top="chip_top", tie_wells_to_rails=True,
        additional_lefs=[io_lef])

    assert out.count(".DVDD(DVDD)") == 2
    assert out.count(".DVSS(DVSS)") == 2
    assert out.count(".VDD(VDD)") == 3
    assert out.count(".VSS(VSS)") == 3
    assert ".PAD(a), .Y(y)" in out
    assert stats["instances_patched"] == 3
    assert set(stats["rails"]) == {"VDD", "VSS", "VNW", "VPW", "DVDD", "DVSS"}


def test_overlapping_io_rails_are_declared_once(tmp_path):
    io_lef = tmp_path / "io.extract.lef"
    io_lef.write_text(IO_LEF)
    out, _ = E.emit_power_aware_netlist(
        NETLIST, "gf180mcuD", top="chip_top", tie_wells_to_rails=True,
        additional_lefs=[io_lef])

    assert out.count("wire VDD, VSS;") == 1
    assert out.count("wire DVDD, DVSS;") == 1


def test_absent_additional_views_preserve_the_named_pdk_output():
    before, before_stats = E.emit_power_aware_netlist(
        NETLIST, "gf180mcuD", top="chip_top", tie_wells_to_rails=True)
    after, after_stats = E.emit_power_aware_netlist(
        NETLIST, "gf180mcuD", top="chip_top", tie_wells_to_rails=True,
        additional_lefs=[])
    assert after == before
    assert after_stats == before_stats
