"""v0.2.56 stale-netlist guard regressions.

Pins the #426 fix (ORGANIC-20260606-synth-netlist-stale-on-regate): during
a close-loop re-gate the synth step refreshed `netlist_yosys.v` while the
canonical `netlist.v` alias was written ONLY when absent — every check that
reads the canonical name kept judging the PRE-EDIT design's ghost netlist.
Two defenses shipped:
  1. the runner now refreshes the alias UNCONDITIONALLY on every synth pass
     (pinned here as a source-shape assertion + by the guard below);
  2. `synth_netlist_check --rtl …` REFUSES (STALE_NETLIST, rc=1) any
     netlist older than the RTL it judges — even a future alias regression
     cannot silently grade ghost data again.

chip-AGNOSTIC: fixtures are generic counter modules.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import synth_netlist_check as snc  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent

_NETLIST = ("module TopModule(input clk, output reg q);\n"
            "  $_DFF_P_ a (.C(clk), .D(q), .Q(q));\n"
            "  $_NOT_ b (.A(q), .Y(w));\n"
            "endmodule\n")
_RTL = ("module TopModule(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\n"
        "endmodule\n")


def _write(p: Path, text: str, mtime: float) -> Path:
    p.write_text(text)
    os.utime(p, (mtime, mtime))
    return p


def test_netlist_older_than_rtl_is_refused(tmp_path):
    now = time.time()
    nl = _write(tmp_path / "netlist.v", _NETLIST, now - 100)
    rtl = _write(tmp_path / "top.v", _RTL, now)          # RTL edited AFTER
    findings, stats = snc.audit_netlist(nl, 10, [rtl])
    assert stats["stale_vs_rtl"] is True
    assert [f.category for f in findings] == ["STALE_NETLIST"]
    assert findings[0].severity == "ERROR"
    assert "ghost" in findings[0].message


def test_fresh_netlist_passes_staleness_guard(tmp_path):
    now = time.time()
    rtl = _write(tmp_path / "top.v", _RTL, now - 100)
    nl = _write(tmp_path / "netlist.v", _NETLIST, now)   # synth AFTER edit
    findings, stats = snc.audit_netlist(nl, 10, [rtl])
    assert stats["stale_vs_rtl"] is False
    assert "STALE_NETLIST" not in [f.category for f in findings]


def test_no_rtl_given_keeps_legacy_behavior(tmp_path):
    nl = tmp_path / "netlist.v"
    nl.write_text(_NETLIST)
    findings, stats = snc.audit_netlist(nl, 10)
    assert "STALE_NETLIST" not in [f.category for f in findings]


def test_cli_exit_code_on_stale(tmp_path):
    now = time.time()
    nl = _write(tmp_path / "netlist.v", _NETLIST, now - 100)
    rtl = _write(tmp_path / "top.v", _RTL, now)
    rc = snc.main(["--netlist", str(nl), "--rtl", str(rtl)])
    assert rc == 1


def test_runner_refreshes_canonical_alias_unconditionally():
    # source-shape pin: the pre-fix `if not canon_v.is_file()` guard around
    # the alias write must stay gone — the alias is refreshed on EVERY pass.
    src = (PLUGIN / "programs" / "design_one_shot_runner.py").read_text()
    i = src.index('canon_v = synth_dir / "netlist.v"')
    window = src[i:i + 700]
    assert "if not canon_v.is_file()" not in window
    assert "canon_v.write_text(out_v.read_text())" in window
    assert "#426" in window  # rationale stays attached to the write
