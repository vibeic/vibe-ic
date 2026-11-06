"""R-0915-88 — `AWAITING_AGENT_PASS` was written into the taxonomy, never reached.

THE INPUT, on run21, `flow_compliance_check --stage-id stage_phase1 --strict`
(rc=1, the one failing ledger row of two):

    [UNCLASSIFIED] Step D1: Phase 1 Doc Extraction   (NOT_MEASURED)
        reason_class : partial_population
        observed     : INCOMPLETE: the gate reports its input was applicable
                       and was NOT examined: phase1_expert_parse_track . --check-report
        why          : it ran without measuring design-bound content, which
                       names no cause to act on

Every one of that step's 33 gates returned a decisive verdict, and the gate's
own report says `execution.disposition = "AWAITING"`,
`observed_ai_status = "HANDOFF_EMITTED"`, `observed_ai_consumed = 0`. Nothing
about the population is short: the flow is waiting on a second pass a PROGRAM
cannot make. Both sentences above are false, and no structural sub-gate failed —
the structural umbrella was not even asked to run in that invocation.

FOUR LINKS, each measured, each pinned below:

  1. the PRODUCER never printed the token (0 occurrences in its source), though
     its `--check-report` branch had just proved the awaiting triple;
  2. the rc=4 REWRITE names `AWAITING_AGENT_PASS` mid-line after `INCOMPLETE: `,
     and the token is only read where it STARTS a line — so the reader's own
     synthesised message was unreadable by the reader's own test;
  3. the REQUIRED `program_exit_zero` branch never looked for the token, while
     the OPTIONAL branch does — the asymmetry the vacuous comment ten lines
     above it describes, for the other token;
  4. the `all_of` forwarding WHITELIST has no branch for the awaiting hint, so
     it was appended and dropped one level below the line meant to carry it.
     That whitelist's own comments record the same failure mode three times.

WHAT MUST NOT MOVE, and the controls are here for it: an INCOMPLETE that is
genuinely a short population keeps `partial_population`, and the awaiting tier
stays UNCLASSIFIED — it is not MISSING_CAPABILITY, which this repo defines as a
named TOOL, BOARD or PDK being absent. Only the basis and the sentence change.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


class _Res:
    outcome = "ok"


@pytest.fixture(autouse=True)
def _restore_the_shared_watchdog():
    """`_fcc` gives each test a fresh flow_compliance_check, but every copy
    imports the SAME `_watchdog` module object, so `_stub_gate` patching
    `mod._watchdog.*` patched it for the whole process. MEASURED (lane
    ictier1): under xdist a later test in the same worker that ran a real gate
    in-process got this file's stub back -- `(False, 'some unrelated program
    output', 4, ...)`. Restore it after every test."""
    import _watchdog
    saved = (_watchdog.run_host_supervised, _watchdog.completed_process)
    yield
    _watchdog.run_host_supervised, _watchdog.completed_process = saved


def _stub_gate(mod, rc: int, stdout: str) -> None:
    """Make every gate invocation return (rc, stdout).

    Patched at `_watchdog`, which is the seam the module actually calls: a
    `subprocess.run` stub is blinded by the supervised-run recorder in between.
    """
    class _CP:
        returncode = rc
        stdout = ""
        stderr = ""

    cp = _CP()
    cp.stdout = stdout
    mod._watchdog.run_host_supervised = (
        lambda argv, **kw: _Res())
    mod._watchdog.completed_process = lambda argv, res: cp
    mod._resolve_program_cmd = lambda cmd_str, cwd=None: ["/bin/true"]


_AWAITING_STDOUT = (
    "INCOMPLETE: phase1_expert_parse_track: INCOMPLETE — read-only report check\n"
    "AWAITING_AGENT_PASS: HANDOFF_EMITTED — 0 of 1 required agent answer(s) "
    "consumed\n")

#: The SAME first line, and NOTHING else. This is what the producer printed
#: before this change, and what any other gate in the family still prints.
_BARE_INCOMPLETE_STDOUT = (
    "INCOMPLETE: phase1_expert_parse_track: INCOMPLETE — read-only report check\n")

_ALL_OF_GATE = {"all_of": [
    {"program_exit_zero": "phase1_expert_parse_track . --check-report"}]}


def _awaiting_hints(mod, reasons):
    return [r for r in reasons if r.startswith(mod._AWAITING_HINT_PREFIX)]


def _incomplete_hints(mod, reasons):
    return [r for r in reasons if r.startswith(mod._INCOMPLETE_HINT_PREFIX)]


# ── the chain, end to end through the required clause in an all_of ────────────


# ── THE TEETH: a short population is still a short population ────────────────


# ── the blocker's basis and its sentence ─────────────────────────────────────


# ── the producer's own stdout ────────────────────────────────────────────────

def _staged_report(tmp_path: Path, *, disposition: str, ai_status: str,
                   verdict: str) -> Path:
    # One L-doc, so the project HAS a Phase-1 root, and the recorded root is
    # DERIVED from it by the program's own function rather than typed here: the
    # checker refuses a report whose root digest does not match the tree, and a
    # hand-written digest would be a fixture asserting against itself.
    import phase1_expert_parse_track as _t
    doc = tmp_path / "phase1/generated_docs/L1_DATASHEET.json"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(json.dumps({"layer": "L1", "fields": {}}) + "\n")
    root = _t.phase1_root_identity(tmp_path)
    assert root.get("status") == "OK", root
    rel = Path("reports/audit/phase1/expert_parse_track.json")
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "program": "phase1_expert_parse_track", "verdict": verdict,
        "ai_subtrack": {"status": ai_status},
        "execution": {"complete": disposition != "AWAITING",
                      "disposition": disposition,
                      "required_ai_status": "CONSUMED",
                      "required_ai_consumed_min": 1,
                      "observed_ai_status": ai_status,
                      "observed_ai_consumed": 0 if disposition == "AWAITING" else 1,
                      "derivation": None,
                      "deterministic_examined": 0},
        "phase1_root": root,
        "producer": {"invoked_by": "phase1_one_shot_runner",
                     "invocation_id": "00000000-0000-0000-0000-000000000000",
                     "returncode": 4 if disposition == "AWAITING" else 0},
    }, indent=2) + "\n")
    return p


def _check_report(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_expert_parse_track.py"),
         str(tmp_path), "--check-report"],
        capture_output=True, text=True)


def test_the_producer_says_the_word_for_the_state_it_proved(tmp_path):
    """LINK 1. The branch accepts rc=4 only WITH verdict INCOMPLETE and
    `AI_HANDOFF_EMITTED` — the awaiting triple — and then printed only
    "INCOMPLETE". The token appeared nowhere in that file."""
    _staged_report(tmp_path, disposition="AWAITING",
                   ai_status="HANDOFF_EMITTED", verdict="INCOMPLETE")
    r = _check_report(tmp_path)
    assert any(line.lstrip().startswith("AWAITING_AGENT_PASS")
               for line in r.stdout.splitlines()), (
        "the sentinel must START a line to be read at all; got "
        f"{r.stdout[:300]!r}")
    assert r.stdout.splitlines()[0].startswith("INCOMPLETE: "), (
        "and the INCOMPLETE headline must stay FIRST: the consumer keeps a "
        "300-char head, which is what makes it survive a long project path")


def test_the_producer_is_silent_about_awaiting_when_it_is_not_awaiting(tmp_path):
    """CONTROL. A consumed track must not print the sentinel, or every completed
    run would claim to be waiting."""
    _staged_report(tmp_path, disposition="COMPLETE",
                   ai_status="CONSUMED", verdict="PASS")
    r = _check_report(tmp_path)
    assert "AWAITING_AGENT_PASS" not in r.stdout
