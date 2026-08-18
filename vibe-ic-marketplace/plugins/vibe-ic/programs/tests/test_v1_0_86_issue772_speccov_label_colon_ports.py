#!/usr/bin/env python3
"""ORGANIC #772 [P2 structural real_gap] — spec declares ports only in the
markdown 'direction-LABEL + colon' bullet form (`- **Input**: `binary_in`
(`BINARY_WIDTH` bits) ...` / `- Output: valid (1 bit)`). `_specrtl_common._NL_PORT`
required the direction word to be immediately followed by a bare name, so this
common datasheet style returned ZERO ports → `spec_coverage_check --strict`
reported a VACUOUS `spec-coverage ok` on a spec that clearly declares two ports
(per the gate's own #697 doctrine a chain requirement dropped at extraction is an
extraction-gap, never a PASS).

Fix: a new `_NL_PORT_LABEL` regex accepts the direction-label-colon form
(optional markdown emphasis, colon, optionally-backticked name) REQUIRING a
structural width anchor `(N bits)` / `(`WIDTH` bits)` so ordinary prose bullets
(`- **Note**: ...`) without a width annotation do NOT become phantom ports.

§4.05 NO-LEAK: this is a STRUCTURAL real_gap that must KEEP catching defects —
after the fix, an RTL that omits one of the two declared ports (or declares the
wrong direction) must STILL be caught; and a prose bullet with no width anchor
must STILL NOT become a phantom port.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _specrtl_common as S  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"


def _names(line):
    return [p.name for p in S._parse_nl_ports(line)]


# ── NEW-PATH: the label-colon datasheet form parses ──────────────────────────
def test_772_label_colon_forms_parse():
    assert _names("- **Input**: `binary_in` (`BINARY_WIDTH` bits) is the value") \
        == ["binary_in"]
    assert _names("- **Output**: `one_hot_out` (`OUTPUT_WIDTH` bits)") \
        == ["one_hot_out"]
    assert _names("- Input: addr (8 bits)") == ["addr"]
    assert _names("- **Output**: valid (1 bit)") == ["valid"]


def test_772_canonical_form_still_parses():
    assert _names("- input binary_in (5 bits)") == ["binary_in"]


# ── §4.05 NO-LEAK: prose bullets WITHOUT a width anchor are NOT phantom ports ─
def test_772_noleak_prose_bullets_not_ports():
    assert _names("- **Note**: the output is registered") == []
    assert _names("- Input ports: the following signals") == []
    assert _names("- Output latency is 1 clock cycle") == []
    assert _names("- **Output**: described in the next section") == []


# ── #478 END-STATE: a label-colon spec is no longer a vacuous pass; a genuine
#    missing port is caught ─────────────────────────────────────────────────
_SPEC = ("# Binary to one-hot decoder\n\nPorts:\n"
         "- **Input**: `binary_in` (`BINARY_WIDTH` bits) is the binary value.\n"
         "- **Output**: `one_hot_out` (`OUTPUT_WIDTH` bits) is the result.\n")


def test_772_endstate_ports_derived_not_vacuous(tmp_path):
    (tmp_path / "spec.md").write_text(_SPEC)
    c = S.extract_spec_contract(_SPEC, confirm=False)
    names = sorted(p.name for p in c.ports)
    assert names == ["binary_in", "one_hot_out"], names


def test_772_endstate_noleak_missing_port_caught(tmp_path):
    """An RTL that OMITS one_hot_out must STILL fail spec-coverage --strict
    (the port checklist item is now derived, so the gap is real). Uses iface
    too via a TB that does not cover one_hot_out."""
    (tmp_path / "spec.md").write_text(_SPEC)
    # TB references only binary_in, never one_hot_out → uncovered port gap.
    (tmp_path / "tb.sv").write_text(
        "module tb; reg [2:0] binary_in; dut u(binary_in);\n"
        "initial begin binary_in=0; #1; $finish; end endmodule\n")
    r = subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "spec.md"),
         "--tb", str(tmp_path / "tb.sv"), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "one_hot_out" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
