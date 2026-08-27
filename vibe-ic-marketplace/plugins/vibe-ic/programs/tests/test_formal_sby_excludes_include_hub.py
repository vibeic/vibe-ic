"""Step 5's .sby must not read an include-hub aggregator next to its siblings.

An INCLUDE-HUB AGGREGATOR is a source whose body ```include``s SIBLING sources
that are ALSO staged standalone (the ChipFoundry/eFabless ``uprj_netlists.v``
shape is the canonical one). Handing both to one ``read_verilog`` elaborates
every included module twice and yosys ABORTS::

    ERROR: Re-definition of module `\\user_proj_example'!

sby then reports ``rc=16`` / "engine_0 did not return a status" for every task,
NO proof engine ever runs, and the flow self-reports a FORMAL-VERIFICATION
capability gap it does not actually have.

Measured on caravel_user_project x sky130A: the unpatched runner produced
``verdict=INCONCLUSIVE, proved=0`` with that yosys error in the sby log; with
the aggregator dropped from the read list the SAME harness and the SAME design
gave ``verdict=PASS, proved=2`` (``abc pdr`` unbounded + ``abc bmc3`` depth 12,
both "returned PASS").

These tests exercise the SHIPPED emitter end-to-end through
``formal_property_run.run()`` and assert the PROPERTY (what ends up on the
``read_verilog`` line), never a source literal.

THE PROOF IS NOT RUN HERE, AND THAT IS NOW ENFORCED RATHER THAN ASSUMED.
=======================================================================
This file used to rest its isolation on an ENVIRONMENTAL ACCIDENT: "``run``
needs no tool to reach the emit - it writes the .sby, then fails to find
sby/docker". The guarantee was "the tool will not be found". Inside our OWN
image the tool IS found - ``sby`` is at ``/usr/local/bin/sby`` and ``docker``
is absent, which is exactly the ambient-PATH branch - so when the suite ran
where it is designed to run, ``run`` wrote the .sby AND THEN RAN THE PROOF.
MEASURED: two ``yosys`` at 35.6 GB apiece on a 125 GB host, no log output for
twelve minutes, memory falling ~2 GB per 20 s. The host stopped answering ssh.
``test_filter_never_empties_the_read_list`` stages two sources that ``include``
each other, so the proof it launched was an unterminated include recursion.

Two mechanisms now make the isolation STRUCTURAL, and both are load-bearing:

* ``emit_only=True`` is an explicit entry point that returns BEFORE any
  executor is reached - no engine probe, no solver, no ``results.json``. There
  is no code path from it to a proof, whatever tools are installed.
* ``_no_solver_may_be_launched`` (autouse) replaces the executor with a
  tripwire for the whole module. If a future change routes any test here back
  through a launch, the test FAILS LOUDLY instead of quietly eating the host.

What this file must never become is a ``skipif(which("sby"))``: that would
delete the coverage in precisely the environment the coverage is for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formal_property_run as fpr  # noqa: E402


class SolverLaunched(AssertionError):
    """Raised if anything in this module reaches a proof executor."""


@pytest.fixture(autouse=True)
def _no_solver_may_be_launched(monkeypatch):
    """ENFORCEMENT, not belief: no test in this file may launch a proof.

    The emit-only entry point already returns before the executor exists; this
    tripwire is what makes that a checked property rather than a claim about
    today\'s control flow. It also covers the engine PROBE, so the module spawns
    no sub-process of any kind.
    """
    def _tripwire(*a, **kw):
        raise SolverLaunched(
            "a test in test_formal_sby_excludes_include_hub.py reached a proof "
            "executor. This file wants the EMIT and must never run the PROOF: "
            "inside vibeic-eda sby IS on PATH, so a launch here is a real "
            "unbounded solver on the test host, not a no-op. Route the call "
            "through fpr.run(..., emit_only=True).")
    monkeypatch.setattr(fpr, "_run_sby", _tripwire)
    monkeypatch.setattr(fpr, "_run_sby_ambient", _tripwire)
    monkeypatch.setattr(fpr, "_run_group_bounded", _tripwire)
    monkeypatch.setattr(fpr, "detect_engines", _tripwire)


HUB_BODY = """\
`include "defines.v"
`ifdef GL
    `include "gl/leaf_a.v"
`else
    `include "leaf_a.v"
`endif
"""

LEAF_A = """\
`default_nettype none
module leaf_a (input wire clk, input wire rst, output reg q);
    always @(posedge clk) if (rst) q <= 1'b0; else q <= ~q;
endmodule
`default_nettype wire
"""

HARNESS = """\
`default_nettype none
module formal_leaf_a (input wire clk);
    (* anyseq *) wire rst;
    wire q;
    leaf_a dut (.clk(clk), .rst(rst), .q(q));
    reg f_past_valid = 1'b0;
    always @(posedge clk) f_past_valid <= 1'b1;
    reg rst_q = 1'b0;
    always @(posedge clk) rst_q <= rst;
    a_reset: assert property (@(posedge clk) (f_past_valid && rst_q) |-> (q == 1'b0));
endmodule
`default_nettype wire
"""

# A macro-only header: including it is ordinary composition, NOT an aggregator
# signal. Dropping it would strand a real source list.
DEFINES = "`ifndef DEFS\n`define DEFS 1\n`endif\n"


def _stage(tmp_path: Path, files: dict) -> tuple[Path, Path, list[Path]]:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    formal = proj / "phase2" / "stage1" / "formal"
    rtl.mkdir(parents=True)
    formal.mkdir(parents=True)
    for name, body in files.items():
        (rtl / name).write_text(body)
    harness = formal / "formal_leaf_a.sv"
    harness.write_text(HARNESS)
    return proj, harness, sorted(rtl.glob("*.v"))


def _read_line(sby_text: str) -> str:
    for line in sby_text.splitlines():
        if "read_verilog" in line:
            return line
    raise AssertionError("no read_verilog line in the emitted .sby:\n" + sby_text)


def _emit(tmp_path: Path, files: dict) -> str:
    """Drive the SHIPPED emitter and read the artefact it wrote.

    `emit_only=True` is what makes this safe by construction: the runner stages
    the sources, authors the .sby and returns, with no executor between here and
    a solver. No `except Exception` swallow either - the emit is not allowed to
    fail, and a swallowed failure is how "the runner emitted no .sby" would read
    as a passing test.
    """
    proj, harness, rtl = _stage(tmp_path, files)
    res = fpr.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                  container=None, emit_only=True)
    assert res["verdict"] == "EMIT_ONLY", res
    assert res["all_proved"] is False, "an emit is not a pass"
    sbys = sorted((proj / "phase2" / "stage1" / "formal").glob("*.sby"))
    assert sbys, "the runner emitted no .sby at all"
    return sbys[0].read_text()


def test_aggregator_is_dropped_from_the_read_list(tmp_path):
    """The hub is excluded; every module-declaring sibling is kept."""
    text = _emit(tmp_path, {"defines.v": DEFINES,
                            "leaf_a.v": LEAF_A,
                            "uprj_netlists.v": HUB_BODY})
    line = _read_line(text)
    assert "uprj_netlists.v" not in line, (
        "the include-hub aggregator is still on the read_verilog line, so "
        "leaf_a is elaborated twice and yosys aborts before any engine runs:\n"
        + line)
    assert "leaf_a.v" in line
    assert "defines.v" in line


def test_macro_only_header_is_never_dropped(tmp_path):
    """Including a module-less macro header is normal composition.

    Negative direction: a source list with no aggregator at all must come
    through untouched, or a real design loses a source and synth dies.
    """
    leaf_with_header = '`include "defines.v"\n' + LEAF_A
    text = _emit(tmp_path, {"defines.v": DEFINES,
                            "leaf_a.v": leaf_with_header})
    line = _read_line(text)
    assert "leaf_a.v" in line, line
    assert "defines.v" in line, line


def test_filter_never_empties_the_read_list(tmp_path):
    """Fail-open: if everything looks like a hub, keep the unfiltered list.

    Reading a redundant file is recoverable; reading nothing is not.
    """
    # NOTE: these two sources `include` each other. Handed to a real yosys this
    # is an unterminated include recursion - it is the input that took a 125 GB
    # host off the network when this file still launched proofs.
    mutual_a = '`include "b.v"\nmodule a (input wire c); endmodule\n'
    mutual_b = '`include "a.v"\nmodule b (input wire c); endmodule\n'
    proj, harness, rtl = _stage(tmp_path, {"a.v": mutual_a, "b.v": mutual_b})
    res = fpr.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                  container=None, emit_only=True)
    assert res["verdict"] == "EMIT_ONLY", res
    sbys = sorted((proj / "phase2" / "stage1" / "formal").glob("*.sby"))
    assert sbys
    line = _read_line(sbys[0].read_text())
    srcs = [t for t in line.split() if t.endswith(".v")]
    assert srcs, "the read_verilog line lost every design source: " + line


def test_files_block_matches_the_read_list(tmp_path):
    """Whatever is read must also be staged, or sby cannot resolve it."""
    text = _emit(tmp_path, {"defines.v": DEFINES,
                            "leaf_a.v": LEAF_A,
                            "uprj_netlists.v": HUB_BODY})
    line = _read_line(text)
    read_srcs = {t for t in line.split() if t.endswith((".v", ".sv"))}
    block = text.split("[files]", 1)[1]
    listed = {ln.strip() for ln in block.splitlines() if ln.strip()}
    missing = read_srcs - listed
    assert not missing, f"read but not staged under [files]: {sorted(missing)}"


# ── the isolation itself, tested in both directions ────────────────────────
def test_emit_only_returns_before_any_executor_exists(tmp_path):
    """THE CONTROL FOR THE FIX. The tripwire above replaces every executor with
    a raise; if `emit_only` reached one, this test would error rather than pass.
    So a green here IS the statement "no proof was launched", and it holds with
    every tool present because nothing about the tool is consulted."""
    proj, harness, rtl = _stage(tmp_path, {"defines.v": DEFINES,
                                           "leaf_a.v": LEAF_A})
    res = fpr.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                  container=None, emit_only=True)
    assert res["verdict"] == "EMIT_ONLY"
    assert res["all_proved"] is False
    assert res["rc"] == fpr.RC_EMIT_ONLY != 0, "an emit must not exit 0"
    formal = proj / "phase2" / "stage1" / "formal"
    # Nothing that could be mistaken downstream for proof evidence.
    assert not (formal / "results.json").exists()
    assert not list(formal.glob("*.sby.log"))


def test_the_tripwire_would_catch_a_launch(tmp_path, monkeypatch):
    """A guard that cannot fire is not a guard.

    Drive the SAME runner without emit_only, with the engine probe stubbed out
    so the only thing left to trip is the solver launch itself. It trips - which
    is what makes the green in the test above mean something.
    """
    monkeypatch.setattr(fpr, "detect_engines", lambda container: {})
    proj, harness, rtl = _stage(tmp_path, {"defines.v": DEFINES,
                                           "leaf_a.v": LEAF_A})
    with pytest.raises(SolverLaunched):
        fpr.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                container=None)
