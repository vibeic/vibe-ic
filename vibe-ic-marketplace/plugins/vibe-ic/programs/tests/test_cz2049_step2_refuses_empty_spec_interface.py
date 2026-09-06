#!/usr/bin/env python3
"""#2049 item 4 (czl9docs O5) — step 2 reported PASS over an EMPTY interface.

`spec_conformance_check.check` skips every port rule when the spec contract
carries no ports, with the documented reason that a reset/latency-only snippet
must not flag every RTL port as "extra". That reason is sound for ONE of the two
causes of "0 spec ports". The other cause is an extraction gap — a blind L9 —
and in that case the gate compares the RTL against nothing and prints PASS with
0 findings. The only thing standing between a design and that vacuous PASS is
the Phase-1 HALT, so the clause stays reachable by any hand-run of this program
and by any caller that reaches step 2 without the Phase-1 gate.

Both directions, because a check that refuses everything is not a check: the
extraction gap must be an ERROR, and the genuinely port-less snippet must stay
exactly as silent as it is today.

NARROWED ON MEASURED EVIDENCE (lane cz2035c, base 91d9063b4). The clause as first
written re-read the spec text with the WHOLE of `phase1_port_extract.extract_ports`,
including its PROSE fallback tier. Swept over 9064 documents of
`benchmark-data` + `benchmark_external` (oracle/golden/solution paths excluded),
that armed on 82 documents; all 16 fires landing on a genuine INPUT document came
from the prose tier and every one of them was a phantom — a FlexRay POC state
name, a SAS primitive, two of a protocol narrative's twenty-odd signals. Since
this rule is EMIT-BLOCKING, those would have blocked legitimate designs. The
clause now arms only on the HIGH-CONFIDENCE tiers (a markdown interface table, or
ports parsed out of a real Verilog region), which is the same structured evidence
`extract_spec_contract` itself reads — so a disagreement there is an extraction
gap by construction. `test_a_prose_only_declaration_does_not_arm_the_rule`
records the narrowing in the other direction and names the cost.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import spec_conformance_check as SC          # noqa: E402
from _specrtl_common import Port             # noqa: E402

#: A STRUCTURED interface declaration — a markdown interface table, the highest
#: confidence form and one `extract_spec_contract` reads itself.
_DECLARES = (
    "Implement a framed serial receiver.\n\n"
    "| Signal | Direction | Width | Description |\n"
    "|--------|-----------|-------|-------------|\n"
    "| clk    | input     | 1     | system clock |\n"
    "| rst    | input     | 1     | synchronous reset |\n"
    "| q      | output    | 1     | decoded bit |\n"
)

#: The SAME declaration in the prose-bullet form. Legitimate English, but the
#: grammar that reads it also reads a state-name list as an interface, so it does
#: NOT arm this emit-blocking rule. See the module docstring.
_DECLARES_PROSE = ("Implement a framed serial receiver.\n\n"
                   " - input  clk\n - input  rst\n - output q\n")

#: A genuinely port-less snippet — the legitimate cause of "0 spec ports".
_SNIPPET = "Reset is active low and the output is registered.\n"

#: A structured declaration in the other high-confidence form: real Verilog.
_DECLARES_VERILOG = (
    "Implement a framed serial receiver.\n\n"
    "```verilog\n"
    "module framed_rx(input clk, input rst, output q);\n"
    "endmodule\n"
    "```\n"
)

_RTL = [Port('clk', 'input', 1), Port('q', 'output', 1)]
_RULE = 'spec-interface-empty-but-declared'


def _findings(spec_text):
    """A BLIND L9: the contract carries no interface, whatever the text says."""
    spec = SC.extract_spec_contract(spec_text)
    spec.ports = []
    return SC.check(spec, 'framed_rx', _RTL, {}, None, 'x.v',
                    'module framed_rx(); endmodule', spec_text=spec_text)


def _hits(spec_text):
    return [f for f in _findings(spec_text) if f.rule == _RULE]


def test_an_empty_contract_over_a_declaring_spec_is_an_error():
    hits = _hits(_DECLARES)
    assert len(hits) == 1
    assert hits[0].severity == 'ERROR'
    for name in ('clk', 'rst', 'q'):
        assert name in hits[0].message


def test_a_verilog_declaration_arms_the_rule_too():
    """The OTHER high-confidence tier: a real Verilog region, not a table."""
    hits = _hits(_DECLARES_VERILOG)
    assert len(hits) == 1
    assert hits[0].severity == 'ERROR'
    for name in ('clk', 'rst', 'q'):
        assert name in hits[0].message


def test_a_genuinely_portless_snippet_stays_silent():
    """CONTROL — the documented legitimate cause is untouched."""
    assert _hits(_SNIPPET) == []


def test_the_rule_is_emit_blocking():
    """A vacuous PASS that only WARNs is still a vacuous PASS."""
    assert _RULE in SC.EMIT_BLOCKING_CONFORMANCE_RULES


def test_a_contract_that_does_carry_ports_is_unaffected():
    """CONTROL — the clause fires only on the EMPTY population."""
    spec = SC.extract_spec_contract(_DECLARES)
    assert spec.ports
    fs = SC.check(spec, 'framed_rx', _RTL, {}, None, 'x.v',
                  'module framed_rx(); endmodule', spec_text=_DECLARES)
    assert [f for f in fs if f.rule == _RULE] == []


def test_a_prose_only_declaration_does_not_arm_the_rule():
    """THE NARROWING, in the direction that costs something.

    This is the measured trade, written down rather than left implicit: the same
    prose grammar that reads `- input clk` as an interface reads a FlexRay POC
    state list and a SAS primitive list as one too, on real corpus inputs. An
    EMIT-BLOCKING rule may not rest on it. The cost is that a prompt declaring
    its pins ONLY in that form is not caught here.
    """
    assert _hits(_DECLARES_PROSE) == []


def test_the_two_corpus_phantoms_that_forced_the_narrowing_stay_silent():
    """Both shapes are transcribed from real corpus INPUT documents.

    Neither is a module interface; both were read as one by the prose tier.
    """
    flexray_shaped = (
        "The behavior of the Communication Controller is governed by the\n"
        "Protocol Operation Control (POC) state machine. The principal POC\n"
        "states are:\n\n"
        "  - DEFAULT_CONFIG : entered after reset/power-up; unconfigured.\n"
        "  - CONFIG         : the host configures the controller.\n")
    narrative_shaped = (
        "2.2 Global signals\n"
        "--------------------\n\n"
        "  - ACLK    : the single clock. All signals are sampled on the rising\n"
        "              edge of ACLK.\n"
        "  - ARESETn : the active-LOW reset.\n")
    assert _hits(flexray_shaped) == []
    assert _hits(narrative_shaped) == []
