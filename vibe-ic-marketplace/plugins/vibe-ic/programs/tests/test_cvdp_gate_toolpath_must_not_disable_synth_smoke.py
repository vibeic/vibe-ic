"""Regression — a SPACE in the caller's workdir path must not silently switch
the cvdp_gate synthesizability smoke OFF.

Observed on origin/main 24ff9530: `yosys -p` takes a SCRIPT string, and
`yosys_smoke` / `_confirming_rerun` interpolated the scratch path into it
UNQUOTED (`read_verilog -sv {f}; synth -top {top}; stat`). yosys re-splits that
script on whitespace, so a workdir whose path contained a SPACE made
`read_verilog` try to open two non-existent files and abort BEFORE the SYNTH
pass ever ran. `yosys_smoke` infers a host FRONTEND GAP from the ABSENCE of a
SYNTH/HIERARCHY pass header and TOLERATES that — so the #531 synthesizability
gate degraded to a no-op while the record still reported PASS.

Demonstrated: the identical unsynthesizable design (two edge-sensitive events
on one signal → PROC_DFF fatal) was

    BLOCKED  under  /tmp/x/plain/wd
    PASSED   under  /tmp/x/has space/wd   ← "yosys-frontend-gap tolerated"

i.e. the exact silent false-PASS class #531 exists to catch, manufactured by
the smoke's own plumbing rather than by the design.

Fix: quote the path inside the `-p` script at all three yosys call sites.

BOTH DIRECTIONS are asserted here (the gate-mutation doctrine): the guard must
be able to FAIL — an unsynthesizable design is still BLOCKED on a hostile path
— and to PASS — a clean design is not false-blocked, AND its smoke really ran
rather than being tolerated away. A can-pass-only test would go green again the
moment the gate is re-broken into tolerating everything.

NOT COVERED, deliberately: a workdir path containing a NEWLINE. iverilog hands
its source list to `ivlpp` through a LINE-DELIMITED command file, so it cannot
compile such a path at all ("Preprocessor failed with 1 error(s)") — an
upstream tool limit, not a cvdp_gate defect, and not reachable from any real
`--workdir`. It IS reachable from pytest's `tmp_path` when the runner's
username is malformed (`getpass.getuser()` feeds `/tmp/pytest-of-<user>`);
that is a harness-environment bug, fixed in the harness, not here.

chip-AGNOSTIC: synthetic 3-line drafts; pure path/plumbing structure.
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
import cvdp_gate as G  # noqa: E402

_HAS_TOOLS = (shutil.which("iverilog") is not None
              and shutil.which("yosys") is not None)
_needs_tools = pytest.mark.skipif(
    not _HAS_TOOLS, reason="iverilog and yosys are both required")

# iverilog-LEGAL but yosys-synth FATAL: two edge-sensitive events on one
# signal (PROC_DFF "Multiple edge sensitive events"). A synth-STAGE error is
# exactly what yosys_smoke must BLOCK on — it is none of the tolerated classes
# (latch-inferred / missing context module / frontend gap).
UNSYNTHESIZABLE = ("module bad(input clk, input x, output reg q);\n"
                   "  always @(posedge clk or posedge x) q <= x;\n"
                   "endmodule\n")

# Trivially clean and synthesizable — must never be false-blocked.
CLEAN = ("module baz(input e, output f);\n"
         "  assign f = e;\n"
         "endmodule\n")

# Path components a caller's workdir may legitimately contain. "has space" is
# the one that silently downgraded the gate.
HOSTILE = ["has space", "semi;colon"]


def _gate(completion: str, base: Path):
    wd = base / "wd"
    wd.mkdir(parents=True, exist_ok=True)
    return G.gate_record({"id": "t", "completion": completion}, wd)


# ── CAN-FAIL: the guard must still bite on a hostile path ────────────────────

def test_unsynthesizable_is_blocked_on_a_plain_path(tmp_path):
    """Control. Establishes that the fixture really is blocked by the synth
    smoke on a well-behaved path — without it, the hostile-path assertions
    below could pass for the wrong reason (e.g. a gate that blocks
    everything)."""
    if not _HAS_TOOLS:
        pytest.skip("iverilog and yosys are both required")
    ok, _rec, entry = _gate(UNSYNTHESIZABLE, tmp_path / "plain")
    assert not ok and entry["verdict"] == "BLOCKED", entry
    assert "yosys-smoke failed" in (entry.get("synth") or ""), entry


@_needs_tools
@pytest.mark.parametrize("component", HOSTILE)
def test_unsynthesizable_still_blocked_on_hostile_path(tmp_path, component):
    """THE REGRESSION. The same design the plain-path control blocks must
    still be BLOCKED when the workdir path carries a space or a semicolon.
    Before the fix the 'has space' case returned PASS with 'yosys-frontend-gap
    tolerated' — the synth gate silently switched off."""
    ok, _rec, entry = _gate(UNSYNTHESIZABLE, tmp_path / component)
    assert not ok and entry["verdict"] == "BLOCKED", (
        f"synth gate did not enforce under workdir component "
        f"{component!r} — entry={entry}")
    assert "frontend-gap" not in (entry.get("synth") or ""), (
        f"a real synth-stage fatal was mis-tolerated as a host frontend gap "
        f"under workdir component {component!r}: {entry.get('synth')!r}")


# ── CAN-PASS: no false block, and the smoke really ran ───────────────────────

@_needs_tools
@pytest.mark.parametrize("component", HOSTILE)
def test_clean_design_not_false_blocked_on_hostile_path(tmp_path, component):
    """The mirror direction. A clean, synthesizable module must still PASS —
    and the smoke must have actually RUN rather than been tolerated away, so
    the fix cannot be 'satisfied' by widening the tolerance."""
    ok, _rec, entry = _gate(CLEAN, tmp_path / component)
    assert ok and entry["verdict"] == "PASS", (
        f"clean design false-blocked under workdir component "
        f"{component!r} — entry={entry}")
    assert entry.get("compile") == "compile clean", entry
    assert "frontend-gap" not in (entry.get("synth") or ""), (
        f"the smoke did not really run under workdir component "
        f"{component!r}: {entry.get('synth')!r}")


# ── the structural half: EVERY site, not just the one the fixture drives ─────
def test_every_read_verilog_interpolation_in_the_gate_is_QUOTED():
    """vibe-ic#1379. The behavioural test above drives ONE call site.

    Measured by the reviewer: unquoting the other two (`cvdp_gate.py:654` and
    `:925`) leaves the whole suite GREEN, because the fixture only reaches
    `:1009`. Two thirds of the fix was therefore unpinned, and a future edit
    dropping either quote would reintroduce a silent no-op gate — the failure
    mode here is not a red test, it is the synth pass never running while the
    record still says PASS.

    So this asserts the PROPERTY over the whole population rather than the
    three sites known today: any `read_verilog` whose path is interpolated must
    have that interpolation inside double quotes. A fourth site added tomorrow
    is covered the day it is written, which a list of line numbers would not be.
    """
    src = (PLUGIN / "benchmark" / "cvdp_gate.py").read_text(encoding="utf-8")

    # every `read_verilog ...` up to the statement separator or closing quote
    sites = re.findall(r"read_verilog[^;'\"]*", src)
    assert sites, "no read_verilog call sites found — the guard would be vacuous"

    unquoted = [s for s in sites if re.search(r'(?<!")\{[^}]+\}(?!")', s)]
    assert not unquoted, (
        "a yosys -p script interpolates a path WITHOUT quotes, so a workdir "
        "containing a space splits the argument and read_verilog aborts before "
        "synth ever runs — the gate then reports a tolerated frontend gap "
        "instead of a failure:\n  " + "\n  ".join(unquoted))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
