#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P0 (LVS) — the tapeout tier must NOT credit a POWER_PIN_ONLY
waiver as a genuine LVS match, and must FAIL a real signal-net mismatch.

This is the honest half of the load-bearing LVS gap: the triage-tier
POWER_PIN_ONLY→LVS_MATCH_POWER_AWARE waiver (in _run_extraction_lvs) is fine for
triage, but a tape-out is defined by a GENUINE match. The tapeout gate refuses the
waiver. (The root fix — a power-aware gate netlist that reaches a genuine match — is
the tracked follow-up.)
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lvs_tapeout_signoff_check as G  # noqa: E402


# A genuine netgen unique-match transcript.
_MATCH = """\
Subcircuit summary:
Circuit 1: spm                          |Circuit 2: spm
Number of devices: 812                  |Number of devices: 812
Netlists match uniquely.
Final result: Circuits match uniquely.
"""

# A power-pin-only mismatch (the universal sky130 OSS artifact): the only failing
# rows are power/tie nets; no signal-net evidence.
_POWER_PIN_ONLY = """\
Top level cell failed pin matching.
Cell pin lists for spm and spm do not match.
  VPWR|(no matching pin)
  VGND|(no matching pin)
  VPB |(no matching pin)
  VNB |(no matching pin)
Final result: Netlists do not match.
"""

# A real signal-net mismatch: `(no pin, node is …)` rows (the aes 517-row class).
_SIGNAL_NET = """\
Top level cell failed pin matching.
Cell pin lists for aes and aes do not match.
  (no pin, node is /_54440_/Y)
  (no pin, node is /_54441_/Y)
  data_out[7]|(no matching pin)
Final result: Netlists do not match.
"""


def test_genuine_match_passes():
    res = G.evaluate(_MATCH)
    assert res["tapeout_verdict"] == "GENUINE_MATCH"
    assert res["passed"] is True


def test_power_pin_only_is_not_a_tapeout_pass():
    # §4.05 (the whole point): POWER_PIN_ONLY is a triage waiver, NEVER a tapeout
    # pass — it must NOT release the tapeout tier.
    res = G.evaluate(_POWER_PIN_ONLY)
    assert res["tapeout_verdict"] == "WAIVED_PENDING_POWER_AWARE"
    assert res["passed"] is False
    assert "power-aware" in res["detail"]


def test_signal_net_mismatch_fails():
    res = G.evaluate(_SIGNAL_NET)
    assert res["tapeout_verdict"] == "SIGNAL_NET_MISMATCH"
    assert res["passed"] is False


def test_incomplete_run_fails_not_pass():
    # a truncated hierarchical run (match line but no Final result) is INCOMPLETE.
    incomplete = "Cell spm matches uniquely.\n(no Final result line)\n"
    res = G.evaluate(incomplete)
    assert res["tapeout_verdict"] == "INCOMPLETE"
    assert res["passed"] is False


def test_absent_report_is_io_error(tmp_path):
    res = G.check(tmp_path / "nope")
    assert res["tapeout_verdict"] == "IO_ERROR"
    assert res["passed"] is False


def test_check_reads_from_dir_and_main_exit_codes(tmp_path):
    (tmp_path / "lvs.rpt").write_text(_MATCH)
    assert G.main([str(tmp_path)]) == 0                    # genuine match → PASS
    ppo = tmp_path / "ppo"
    ppo.mkdir()
    (ppo / "comp.out").write_text(_POWER_PIN_ONLY)
    assert G.main([str(ppo)]) == 1                         # waived-pending → not a pass
    assert G.main([str(tmp_path / "absent")]) == 2         # IO error


def test_consistency_with_lvs_verdict_tokens():
    # the tapeout gate must agree with the shared classifier's base verdict.
    import lvs_verdict_tokens as lvt
    assert lvt.classify(_MATCH) == "MATCH"
    assert lvt.classify(_POWER_PIN_ONLY) == "MISMATCH"
    assert lvt.mismatch_class(_POWER_PIN_ONLY) == "POWER_PIN_ONLY"
    assert lvt.mismatch_class(_SIGNAL_NET) == "SIGNAL_NET_MISMATCH"
