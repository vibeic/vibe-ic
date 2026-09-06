#!/usr/bin/env python3
"""#2052 item 4 / #564 — the port comparison's own DENOMINATOR.

`spec_conformance_check` skips every port rule when the spec contract carries no
ports. It then printed

    spec_conformance_check: PASS — findings: 0 (0 error, 0 warn, 0 info)
    [spec ports=0(json), rtl ports=5, spec reset=-/-]

and returned rc 0. Measured on base 91d9063b4 through the flow's own front-door
command over a real project tree whose L9 carries an empty `ports` list. A reader
reads PASS; what happened is that five RTL ports were compared against nothing.

The zero WAS disclosed — `spec ports=0` — but in a shape no instrument in this
repo can read: `gate_zero_denominator_refuses_check`'s predicate (#564) wants a
zero beside a population word, `0 ports read`, and `ports=0` matches none of its
alternatives. A disclosure only a human might notice is not a disclosure the
flow can act on.

So the zero is now stated twice, in both output channels and in the house shape:
an INFO finding for the `--json` consumer, and the summary line for the reader.
INFO and not ERROR, deliberately: 110 of the 142 JSON contracts carrying a
`ports` key in the corpus on this base carry it EMPTY, and a port-less spec is a
legitimate input. What is not legitimate is calling the resulting silence
conformance.

Both directions throughout: a contract that DOES carry ports must produce neither
the finding nor the note.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import spec_conformance_check as SC                       # noqa: E402
import gate_zero_denominator_refuses_check as GZ          # noqa: E402
from _specrtl_common import Port, SpecContract            # noqa: E402

_RULE = 'spec-port-comparison-not-measured'
_RTL = [Port('clk', 'input', 1), Port('rst', 'input', 1), Port('q', 'output', 1)]
_BODY = 'module m(input clk, input rst, output q); endmodule'


def _findings(ports):
    spec = SpecContract(module='m', ports=list(ports), source='json')
    return SC.check(spec, 'm', _RTL, {}, None, 'x.v', _BODY)


def _hits(ports):
    return [f for f in _findings(ports) if f.rule == _RULE]


def test_an_empty_port_contract_reports_the_comparison_not_measured():
    hits = _hits([])
    assert len(hits) == 1
    assert hits[0].severity == 'INFO'
    assert 'NOT_MEASURED' in hits[0].message
    # it must state the denominator it read, not merely that it read nothing
    assert '0 port(s) read' in hits[0].message


def test_a_contract_that_carries_ports_says_nothing():
    """CONTROL — the finding is about the EMPTY population only."""
    assert _hits([Port('clk', 'input', 1)]) == []


def test_the_note_is_not_emit_blocking():
    """A legitimate port-less spec snippet must not be blocked by this.

    The clause states a denominator; it does not accuse the design of anything.
    """
    assert _RULE not in SC.EMIT_BLOCKING_CONFORMANCE_RULES
    assert all(f.severity != 'ERROR' for f in _findings([]))


# --------------------------------------------------------------------------
# the summary line, bound to the HOUSE predicate rather than to a string I chose
# --------------------------------------------------------------------------
#
# These read the line THE PROGRAM ACTUALLY PRINTS, by driving `main()` over a
# real spec/RTL pair and capturing stdout. Reconstructing the line inside the
# test would have proved only that the test can build a string: it would have
# stayed green with the emitter deleted.

import contextlib                                    # noqa: E402
import io                                            # noqa: E402
import json                                          # noqa: E402
import tempfile                                      # noqa: E402

_RTL_SRC = "module m(input clk, input rst, output q);\nendmodule\n"


def _run_main(spec_ports):
    """Drive the program end to end and return (rc, its printed summary line)."""
    root = tempfile.mkdtemp(prefix="cz2035c_denom_")
    rtl = Path(root) / "rtl"
    rtl.mkdir()
    (rtl / "m.v").write_text(_RTL_SRC)
    spec = Path(root) / "L9.json"
    spec.write_text(json.dumps({"module": "m", "ports": spec_ports}))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SC.main(["--rtl-dir", str(rtl), "--spec", str(spec)])
    lines = [ln for ln in buf.getvalue().splitlines()
             if ln.startswith("spec_conformance_check:")]
    assert len(lines) == 1, buf.getvalue()
    return rc, lines[0]


def test_the_old_summary_shape_was_invisible_to_the_house_predicate():
    """The measurement that forced this change, kept executable.

    `ports=0` is a zero the repo's own zero-denominator predicate cannot see.
    """
    old = ("spec_conformance_check: PASS — findings: 0 (0 error, 0 warn, 0 info) "
           "[spec ports=0(json), rtl ports=5, spec reset=-/-]")
    assert GZ.states_zero_population(old) is False


def test_the_printed_summary_states_its_zero_in_the_shape_the_house_reads():
    rc, line = _run_main([])
    assert GZ.states_zero_population(line) is True, line
    assert "NOT_MEASURED" in line
    # the verdict is NOT turned into a failure: this states a denominator, it
    # does not accuse the design.
    assert rc == 0


def test_a_non_zero_denominator_prints_no_zero_population():
    """CONTROL — the note must not appear when ports were actually read."""
    rc, line = _run_main([{"name": "clk", "direction": "input", "width": 1},
                          {"name": "rst", "direction": "input", "width": 1},
                          {"name": "q", "direction": "output", "width": 1}])
    assert "NOT_MEASURED" not in line, line
    assert GZ.states_zero_population(line) is False, line
    assert rc == 0
