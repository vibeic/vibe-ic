#!/usr/bin/env python3
"""Tests for pulse_decoder_edge_check.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "pulse_decoder_edge_check.py"


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_empty_rtl(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0


def test_strict_q_pair_passes(tmp_path):
    """Classic strict-form edge detector — same name with `_q` suffix."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input id_bus_rx);
  reg id_bus_rx_q;
  reg [15:0] low_cnt;
  always @(posedge clk) id_bus_rx_q <= id_bus_rx;
  wire rising = id_bus_rx && !id_bus_rx_q;
  always @(posedge clk) begin
    if (rising)              low_cnt <= 0;
    else if (id_bus_rx == 0) low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0


def test_fuzzy_pair_id_bus_rx_eff_vs_q_passes(tmp_path):
    """v0.119.25 fuzzy variant: vendor case `id_bus_rx_eff && !id_bus_rx_q`
    where the registered companion's stem (`id_bus_rx`) is a prefix of
    the live signal (`id_bus_rx_eff`). Previously rejected because
    strict regex required an exact `<X> && !<X>_q` pair."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input id_bus_rx);
  reg id_bus_rx_q;
  wire id_bus_rx_eff = id_bus_rx;
  reg [15:0] low_cnt;
  always @(posedge clk) id_bus_rx_q <= id_bus_rx;
  wire rising = id_bus_rx_eff && !id_bus_rx_q;
  always @(posedge clk) begin
    if (rising)              low_cnt <= 0;
    else if (id_bus_rx == 0) low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0, \
        f"fuzzy edge pair should be recognised: {r.stdout}"


def test_v029_bitwise_and_form_accepted(tmp_path):
    """v0.119.29: `(sig & ~sig_q)` (bitwise) is logically equivalent to
    `(sig && !sig_q)` (logical) for 1-bit signals; both forms appear
    in real RTL. Earlier strict regex rejected the bitwise form
    silently."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input id_bus_rx);
  reg id_bus_rx_q;
  reg [15:0] low_cnt;
  always @(posedge clk) id_bus_rx_q <= id_bus_rx;
  wire rising = id_bus_rx & ~id_bus_rx_q;
  always @(posedge clk) begin
    if (rising)              low_cnt <= 0;
    else if (id_bus_rx == 0) low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0, \
        f"bitwise rising-edge form should be recognised: {r.stdout}"


def test_unrelated_signals_still_fail(tmp_path):
    """Negative: completely unrelated names like `(foo && !bar_q)` must
    NOT be treated as a valid edge-detector pair (no shared prefix)."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input foo, input bar);
  reg bar_q;
  reg [15:0] low_cnt;
  always @(posedge clk) bar_q <= bar;
  wire bogus = foo && !bar_q;
  always @(posedge clk) begin
    if (bogus)               low_cnt <= 0;
    else if (foo == 0)       low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 1, \
        f"unrelated names must not satisfy edge-detector check: {r.stdout}"


def test_v026_food_vs_foo_rejected(tmp_path):
    """v0.119.26 adversarial: `food && !foo_q` — `foo` is mechanically a
    prefix of `food`, so v0.119.25's bare `startswith` shortcut
    incorrectly returned True. The tightened predicate requires the
    longer name's extra suffix to be in `_STAGED_SUFFIXES`; a bare `d`
    is not, so this pair is now correctly rejected."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input food, input foo);
  reg foo_q;
  reg [15:0] low_cnt;
  always @(posedge clk) foo_q <= foo;
  wire bogus = food && !foo_q;
  always @(posedge clk) begin
    if (bogus)              low_cnt <= 0;
    else if (food == 0)     low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 1, \
        f"food/foo prefix coincidence must not satisfy gate: {r.stdout}"


def test_v026_module_group_prefix_rejected(tmp_path):
    """v0.119.26 adversarial: `data_rx_eff && !data_tx_q` — names share
    only the module-group prefix `data_` (5 chars). v0.119.25's
    `min_common=4` accepted this; v0.119.26 raises to 6 AND rejects
    when the boundary ends at `_` (typical group prefix). rx and tx
    are functionally orthogonal — must NOT count as an edge pair."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input data_rx_eff, input data_tx);
  reg data_tx_q;
  reg [15:0] low_cnt;
  always @(posedge clk) data_tx_q <= data_tx;
  wire bogus = data_rx_eff && !data_tx_q;
  always @(posedge clk) begin
    if (bogus)                 low_cnt <= 0;
    else if (data_rx_eff == 0) low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 1, \
        f"data_/group-prefix only must not satisfy gate: {r.stdout}"


def test_v026_staged_suffix_d_still_passes(tmp_path):
    """v0.119.26 sanity: legitimate stage-suffix `_d` must keep working
    so that `sig_d && !sig_q` (delayed-signal companion of registered
    sig) still counts. `d` is in `_STAGED_SUFFIXES`; only `food`/`foo`
    style coincidence is excluded."""
    (tmp_path / "rx.sv").write_text("""\
module rx_phy(input clk, input sig);
  reg sig_q;
  wire sig_d = sig;
  reg [15:0] low_cnt;
  always @(posedge clk) sig_q <= sig;
  wire rising = sig_d && !sig_q;
  always @(posedge clk) begin
    if (rising)         low_cnt <= 0;
    else if (sig == 0)  low_cnt <= low_cnt + 1;
  end
  reg ok = (low_cnt >= 8) && (low_cnt < 16);
  reg br = (low_cnt >= 32);
endmodule
""")
    r = _run(["--rtl-dir", str(tmp_path)])
    assert r.returncode == 0, \
        f"staged-suffix _d must still satisfy gate: {r.stdout}"
