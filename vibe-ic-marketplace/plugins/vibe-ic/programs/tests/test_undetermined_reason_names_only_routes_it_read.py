#!/usr/bin/env python3
"""An UNDETERMINED field must not report a search the program did not run.

Tier 3 of `spec_declaration_emit` -- `key = value` lines in an RTL COMMENT
block -- is OPT-IN behind `--from-rtl-declaration`, and the runner does not
pass it. Without the flag `rtl_declared` is empty because the route was NEVER
READ, which is indistinguishable, inside `resolve`, from "read it and found
nothing". The UNDETERMINED reason said "no `<field> = <value>` line in an RTL
comment block" either way.

MEASURED (sha256 x sky130A, 2026-08-10): an author read that sentence, wrote a
conforming `DECLARED CHOICES` block into the RTL header, and the CLI reported
all seven fields undeclared with the same sentence -- while `_rtl_declared`,
called directly on the same project, returned all seven values. The sentence
did not merely omit a caveat; it named the one route that would not be read
and sent the author down it.

The REVERSE case is the load-bearing half: with the flag passed the route IS
consulted, and the wording must be exactly what it has always been.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "spec_declaration_emit.py"

#: A spec that declares a machine-readable declaration contract. The field name
#: is INVENTED so no real design's field list can satisfy this fixture.
SPEC = """\
# L7 - Verification Plan

## 7.0 Plugin Declaration Requirements

The implementer MUST emit `plugin_output/declaration.json` carrying:

| Field | Required | Example |
|---|---|---|
| `widget_port_name` | YES | `"w_in"` |
"""

RTL = """// DECLARED CHOICES
//
//   widget_port_name = w_in
//
// END
module dut(input wire clk); endmodule
"""


def _project(tmp_path):
    proj = tmp_path / "p"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "input" / "docs" / "L7_verification_plan.md").write_text(SPEC)
    (proj / "phase2" / "stage1" / "rtl" / "dut.v").write_text(RTL)
    return proj


def _run(proj, *args):
    return subprocess.run([sys.executable, str(PROG), ".", *args],
                          cwd=str(proj), capture_output=True, text=True,
                          timeout=120)


# ── FORWARD ────────────────────────────────────────────────────────────────

def test_without_the_flag_the_reason_says_the_route_was_not_consulted(tmp_path):
    proj = _project(tmp_path)
    txt = _run(proj).stdout + _run(proj).stderr
    assert "NOT consulted" in txt, txt
    assert "--from-rtl-declaration" in txt, txt


def test_without_the_flag_it_does_not_claim_an_empty_rtl_block(tmp_path):
    """The specific false sentence, pinned so it cannot come back."""
    proj = _project(tmp_path)
    txt = _run(proj).stdout + _run(proj).stderr
    assert "no `widget_port_name = <value>` line in an RTL comment block" not in txt, txt


# ── REVERSE: the opt-in path is untouched ─────────────────────────────────

def test_with_the_flag_the_route_is_read_and_the_field_resolves(tmp_path):
    proj = _project(tmp_path)
    res = _run(proj, "--from-rtl-declaration")
    assert res.returncode == 0, res.stdout + res.stderr
    decl = json.loads((proj / "plugin_output" / "declaration.json").read_text())
    assert decl["widget_port_name"] == "w_in", decl


def test_with_the_flag_and_nothing_to_find_the_wording_is_unchanged(tmp_path):
    """When the route IS consulted and genuinely finds nothing, the sentence
    must be exactly the one this program has always printed. This test passes
    against the PRE-FIX file too, which is what makes it a control."""
    proj = _project(tmp_path)
    (proj / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire clk); endmodule\n")
    txt = (_run(proj, "--from-rtl-declaration").stdout
           + _run(proj, "--from-rtl-declaration").stderr)
    assert "no `widget_port_name = <value>` line in an RTL comment block" in txt, txt
    assert "NOT consulted" not in txt, txt


def test_an_explicit_set_still_wins_without_the_flag(tmp_path):
    """REVERSE -- the intended, non-legacy route is unaffected."""
    proj = _project(tmp_path)
    res = _run(proj, "--set", "widget_port_name=w_in")
    assert res.returncode == 0, res.stdout + res.stderr
    decl = json.loads((proj / "plugin_output" / "declaration.json").read_text())
    assert decl["widget_port_name"] == "w_in"
