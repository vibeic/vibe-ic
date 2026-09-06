#!/usr/bin/env python3
"""#czl9docs — the sufficiency gate must not depend on which front door a
design came through.

Measured on this base, the SAME input declaring five ports:

    docs mode    sufficiency line printed, extraction gap BLOCKS   (after the
                 first czl9docs commit)
    prompt mode  no sufficiency line at all, rc 0, L9 ports=0      <- unexamined

So a design got looked at or not depending on how it was staged. That is the
shape `phase1_one_shot_runner` itself already names, in the comment above the
prompt branch's own pre-flight gate:

    "one flow step, two mode branches, one question. Gating only one of them
     would leave whichever front door a given design used unexamined"

These tests are a PARITY guard, not a copy of the docs-branch tests: they
compare the two doors against each other, so wiring one and not the other
cannot go green again.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

_RUNNER = PROGRAMS / "phase1_one_shot_runner.py"

_PORTFUL = ("Implement a framed serial receiver.\n"
            "\n"
            " - input  clk\n"
            " - input  rx\n"
            " - output cmd_out (4 bits)\n"
            " - output frame_done\n"
            "\n"
            "`cmd_out` must be valid in the same clock cycle that\n"
            "`frame_done` asserts.\n")
_PORTLESS = ("Each frame is one start bit, an 8-bit payload and one stop\n"
             "bit. Frames are separated by three idle periods.\n")


def _stage(root: Path, mode: str, text: str) -> Path:
    proj = root / mode
    if mode == "docs":
        (proj / "input" / "docs").mkdir(parents=True)
        (proj / "input" / "docs" / "spec.md").write_text(text)
    else:
        (proj / "input").mkdir(parents=True)
        (proj / "input" / "phase1_prompt.md").write_text(text)
    return proj


def _run(proj: Path, mode: str):
    return subprocess.run(
        [sys.executable, str(_RUNNER), str(proj), "--ic-name", "dut",
         "--mode", mode],
        capture_output=True, text=True, timeout=600)


def _reason(proj: Path):
    hits = list(proj.rglob("phase1_sufficiency.json"))
    if not hits:
        return None            # NOT_MEASURED — the gate never wrote a report
    return json.loads(hits[0].read_text()).get("ports_reason")


def test_both_front_doors_run_the_sufficiency_gate_at_all(tmp_path):
    for mode in ("docs", "prompt"):
        proj = _stage(tmp_path, mode, _PORTFUL)
        cp = _run(proj, mode)
        assert "phase1_sufficiency_check:" in cp.stdout, (
            f"{mode} mode never ran the sufficiency gate:\n{cp.stdout[-2000:]}")
        assert _reason(proj) is not None, (
            f"{mode} mode wrote no sufficiency report")


def test_neither_front_door_reports_green_over_an_empty_port_list(tmp_path):
    """The property the finding is about, stated per door.

    NOT "both doors reach the same verdict" — I wrote that first and it failed
    honestly: the two doors run DIFFERENT extractors (docs mode goes through
    `phase1_doc_one_shot_runner`, prompt mode delegates to the bundled
    `phase1_engine` CLI), and today only the docs extractor reads a bullet that
    states its own direction. Demanding identical REASONS would either be a
    lie about the code or pressure to make one door's answer match the other's
    by narrowing something. The invariant that actually matters, and that this
    finding is about, is weaker and true of both:

        a door may extract the ports, or it may halt — it may NOT report a
        green Phase 1 over an L9 that carries no ports when the input declares
        some.

    If the prompt extractor later learns this grammar, its branch moves from
    (b) to (a) and this test still passes, deliberately."""
    for mode in ("docs", "prompt"):
        proj = _stage(tmp_path, mode, _PORTFUL)
        cp = _run(proj, mode)
        reason = _reason(proj)
        assert reason is not None, (mode, "no sufficiency report")
        extracted_ok = reason == "ports_extracted" and cp.returncode == 0
        halted = reason == "extraction_gap" and cp.returncode != 0
        assert extracted_ok or halted, (
            f"{mode} mode reported rc={cp.returncode} with "
            f"ports_reason={reason} — a verdict over an empty port list\n"
            f"{cp.stdout[-1500:]}")


def test_the_measured_divergence_is_a_halt_not_a_pass(tmp_path):
    """Name the divergence explicitly rather than leaving it implied.

    Measured on this base: the docs door EXTRACTS this input's five ports; the
    prompt door does not, because it runs a different extractor. What must be
    true either way is that the door which cannot read them stops. This test
    asserts only that no door both fails to extract AND exits 0 — the exact
    state the finding reported."""
    blind_and_green = []
    for mode in ("docs", "prompt"):
        proj = _stage(tmp_path, mode, _PORTFUL)
        cp = _run(proj, mode)
        if _reason(proj) != "ports_extracted" and cp.returncode == 0:
            blind_and_green.append(mode)
    assert blind_and_green == [], (
        f"{blind_and_green} reported a green Phase 1 over an empty port list")


def test_a_portless_input_is_allowed_through_by_BOTH_doors(tmp_path):
    # The other direction. A gate that refuses everything is not a gate, and it
    # must not refuse differently per door either.
    for mode in ("docs", "prompt"):
        proj = _stage(tmp_path, mode, _PORTLESS)
        cp = _run(proj, mode)
        assert _reason(proj) == "input_declares_no_ports", (mode, cp.stdout[-1500:])
        assert cp.returncode == 0, (mode, cp.stdout[-1500:])


def test_the_prompt_branch_passes_the_strict_flag_and_can_block(tmp_path):
    # A gate invoked without its strict flag cannot block, and the branch that
    # never prints the FAIL line cannot halt. Pin the call shape, not only the
    # observed rc.
    src = _RUNNER.read_text()
    prompt_half = src.split("# Prompt mode: original phase1_engine path")[1]
    assert "_czl9_sufficiency_gate(project)" in prompt_half
    assert "FAIL: EXTRACTION GAP" in prompt_half
    assert '"--strict-extraction-gap"' in src
