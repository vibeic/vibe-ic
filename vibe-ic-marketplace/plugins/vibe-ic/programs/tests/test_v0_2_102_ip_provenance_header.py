"""v0.2.102 — IP/provenance header on flow-GENERATED design artifacts
(README §"IP ownership & commercial-tool firewall" follow-through).

Pins:
  * the shared _GENERATED_DESIGN_HEADER constant exists and states the
    three load-bearing facts (user's work product / no claim on outputs
    / signoff responsibility);
  * the auto-emitted chip_top wrapper embeds it right after the SPDX
    line;
  * the header is comment-only Verilog (every line starts with //) so
    it can never perturb synthesis.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as P2  # noqa: E402


def test_header_constant_states_the_three_facts():
    h = P2._GENERATED_DESIGN_HEADER
    assert "USER'S work product" in h
    assert "no claim" in h
    assert "responsibility" in h
    assert "Apache-2.0" in h


def test_header_is_comment_only_verilog():
    for ln in P2._GENERATED_DESIGN_HEADER.strip().splitlines():
        assert ln.startswith("//"), ln


def test_wrapper_embeds_header_after_spdx():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    i = src.index('f"// SPDX-License-Identifier: Apache-2.0\\n"')
    window = src[i:i + 300]
    assert "_GENERATED_DESIGN_HEADER" in window, (
        "the auto-emitted chip_top wrapper must stamp the provenance "
        "header right after the SPDX line")
