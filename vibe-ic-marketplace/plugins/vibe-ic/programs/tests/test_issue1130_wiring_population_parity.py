"""vibe-ic#1130 — a program must not opt out of the wiring audit by its filename.

#1130 names two routes to "a checker that nothing but its own test runs". The
first — a checker with no runner — is already ratcheted by
`checker_execution_wiring_audit`. The second is quieter: a program that the
audit's POPULATION never contained, so it was never even a candidate.

MEASURED on a38902d1, before the fix:

    programs/*.py                              1136
      checker_execution_wiring_audit population 585
      gate_is_wired_check population            581
      in the wiring audit, NOT in gate_is_wired   4
      the other direction                        0   <- a strict subset

`checker_execution_wiring_audit` added `*_gate.py` to its own population in
#693, after `gitignore_scratch_guard.py` proved a wired-to-nothing gate could
hide behind a filename. `gate_is_wired_check` never got the same widening. Two
instruments that both audit wiring, disagreeing about their own subject — and
the disagreement is invisible because each one reports confidently about the
population it happens to hold.

Widening it found a REAL gate, which is the whole point of the change:
`plugin_change_pytest_gate`, 316 lines implementing benchmark-verify's final
"Plugin-test hard rule", named only in a SKILL.md — it ran when an agent
remembered and produced no verdict when one did not.

THE PARITY IS ASSERTED FROM THE TWO MODULES' OWN CONSTANTS, never from a list
written here. A third copy of "what counts as a gate" would be the same defect
these tests exist to close, one level up.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_GIW = _PROGRAMS / "gate_is_wired_check.py"
_WIRING = _PROGRAMS / "checker_execution_wiring_audit.py"
_ROUTING = _PLUGIN / "benchmark" / "CAPTURE_ROUTING.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GIW = _load(_GIW, "giw")
WIR = _load(_WIRING, "wir")


def _population_giw() -> set:
    return {p.name for p in _PROGRAMS.glob("*.py")
            if p.name != "__init__.py" and GIW._GATE_RE.search(p.stem)}


def _population_wiring() -> set:
    """The CHECKER-SHAPED-BY-NAME population, read from the audit's constant.

    DELIBERATELY NOT `WIR.checker_population()`, and this is the load-bearing
    choice in this file. PR #1174 — same issue, no file overlap with this PR,
    open at the time of writing — widens that FUNCTION from
    `_CHECKER_SUFFIXES` to `suffixes | programs the flow names`. MEASURED on
    the two branches merged together:

        _CHECKER_SUFFIXES constant   585
        checker_population(+flow)    593    -> +8

    and the 8 are `bsdl_emit.py`, `metal_fill_emit.py`, `coverage_closure.py`,
    `fmeda_fault_injection_coverage.py`, `mixed_signal_top_lvs_run.py`,
    `phase1_expert_parse_track.py` and their kind — EMITTERS and producers the
    flow invokes, not gates.

    Reading the function would make this test assert that every one of those
    must be visible to `gate_is_wired_check`, i.e. that an emitter is a gate.
    That is the "population chosen for convenience rather than for the
    question" defect `checker_execution_wiring_audit`'s own docstring rejected
    with measurements, and asserting it here would be adopting it.

    So the parity claimed is the one that is TRUE and is what this PR fixed:
    every CHECKER-SHAPED-BY-NAME program the wiring audit sees must also be a
    gate `gate_is_wired_check` can see. Whether `gate_is_wired` should also
    cover #1174's flow-named additions is a separate question about what a gate
    IS, and it belongs to whoever lands these two — not to this test.
    """
    return {p.name for suf in WIR._CHECKER_SUFFIXES
            for p in _PROGRAMS.glob(suf)}


# ==========================================================================
# 1. THE POPULATIONS AGREE
# ==========================================================================
def test_every_checker_shaped_name_the_wiring_audit_sees_is_also_a_gate():
    """The direction that was broken. Both sets come from the modules' own
    constants, so this cannot pass by a list here agreeing with itself."""
    missing = sorted(_population_wiring() - _population_giw())
    assert not missing, (
        "checker_execution_wiring_audit audits these and gate_is_wired_check "
        "cannot see them, so they can be unwired without either instrument "
        f"saying so: {missing}")


def test_the_gate_regex_actually_admits_the_gate_suffix():
    """The paired guard's target, stated as a property rather than a count.

    Reverting `_GATE_RE` to `_(check|lint|audit|guard)$` makes this fail, which
    is what makes the test above worth having.
    """
    assert GIW._GATE_RE.search("some_thing_gate"), GIW._GATE_RE.pattern
    for suf in ("check", "lint", "audit", "guard", "gate"):
        assert GIW._GATE_RE.search(f"x_{suf}"), suf


def test_a_program_is_not_admitted_by_a_mere_substring():
    """The other side: widening must not turn the predicate into 'anything'.

    Without this, `_GATE_RE = re.compile(".")` would satisfy the parity test
    above and quietly make the population every program — the exact
    convenience-over-question defect `checker_execution_wiring_audit`'s own
    docstring rejected with measurements.
    """
    for stem in ("gate_is_wired_check_helper", "gateway_client",
                 "investigate_thing", "a2b_protocol_synth"):
        if stem.endswith(("_check", "_lint", "_audit", "_guard", "_gate")):
            continue
        assert not GIW._GATE_RE.search(stem), stem


# ==========================================================================
# 2. THE REAL GATE THE WIDENING FOUND
# ==========================================================================
def test_plugin_change_pytest_gate_is_routed_to_a_rail():
    """It is REAL, not dead: benchmark-verify's 'Plugin-test hard rule'.

    Asserted on the ROUTING TABLE rather than on `gate_is_wired`'s verdict, so
    the test names the thing that must stay true. `benchmark/*.json` is one of
    that gate's accepted rails.
    """
    doc = json.loads(_ROUTING.read_text(encoding="utf-8"))
    routed = [k for k, v in doc["steps"].items()
              if isinstance(v, dict)
              and "plugin_change_pytest_gate" in str(v.get("bucket_A_program", ""))]
    assert routed, (
        "plugin_change_pytest_gate is not routed in CAPTURE_ROUTING.json — it "
        "would again be a 316-line gate that runs only if an agent remembers "
        "a skill document")
    entry = doc["steps"][routed[0]]
    assert "benchmark-verify" in str(entry.get("bucket_B_skill_file", "")), entry
    assert len(str(entry.get("description", ""))) > 80, (
        "a routing entry with no reason is a wiring nobody can review")


def test_the_gate_it_found_still_exists_and_is_a_real_program():
    """If someone deletes the gate instead of wiring it, that is issue ask #4
    (dead code) and this test should be deleted WITH it — deliberately, not by
    the routing entry quietly pointing at nothing."""
    p = _PROGRAMS / "plugin_change_pytest_gate.py"
    assert p.is_file(), p
    doc = json.loads(_ROUTING.read_text(encoding="utf-8"))
    missing = []
    for k, v in doc["steps"].items():
        if not isinstance(v, dict):
            continue
        prog = v.get("bucket_A_program")
        # `null` is a DECLARED absence (a step with no deterministic half) and
        # is not a dangling route; only a named path can dangle.
        if not isinstance(prog, str) or not prog.strip():
            continue
        # SCOPED TO `programs/*.py`, which is the class this change touches, and
        # NOT because the wider assertion was inconvenient. Measured on
        # a38902d1, three entries under `mcp_eda.*` route to
        # `mcp-eda/src/tools/{lint,synth,cocotb}.js` and that directory does not
        # exist anywhere in the tree — a real dangling route, PRE-EXISTING, and
        # a different defect from #1130's. Asserting it here would redden this
        # PR for something it did not cause; it is reported in the PR body
        # instead so it gets its own change and its own measurement.
        if not prog.startswith("programs/"):
            continue
        if not (_PLUGIN / prog).is_file():
            missing.append(f"{k} -> {prog}")
    assert not missing, (
        f"CAPTURE_ROUTING routes program(s) under programs/ that do not "
        f"exist: {missing}")


# ==========================================================================
# 3. ISSUE ASK #5 — the number is reported even when it is zero
# ==========================================================================
#: Already true on both wiring gates before this change; pinned so it stays
#: true. A gate that speaks only when it finds something cannot be told apart
#: from one that is not running.
@pytest.mark.parametrize("prog,args,needle", [
    ("gate_is_wired_check.py", ["--root", str(_PLUGIN)], "gates:"),
    ("checker_execution_wiring_audit.py", [], "checker-shaped program(s)"),
])
def test_the_wiring_gates_state_their_denominator_on_a_clean_run(prog, args, needle):
    #: 55s, not 170s. The harness runs this suite under `--timeout=180` and
    #: `ci_harness_timeout_ceiling_check` derives a per-call ceiling of
    #: `min(180, 300) // 3 = 60s` from it. A bound ABOVE that promises time the
    #: harness will not give: pytest-timeout's thread method cannot interrupt a
    #: blocking subprocess, so it calls `os._exit(1)` and takes the whole
    #: SESSION down instead of failing this one test.
    #: MEASURED, 3 runs each on a loaded host: `gate_is_wired_check` 14.3-14.7s,
    #: `checker_execution_wiring_audit` 18.9-20.3s. 55s is ~2.7x the slowest
    #: observed and still inside the ceiling.
    #: RE-MEASURED at vibe-ic#1347, which made the audit read each haystack
    #: file a second time UNSTRIPPED to test invocation shape: same host, 3
    #: runs each, origin/main 21.0-21.3s and the tightened audit 24.0-25.0s
    #: (+15%). 55s is now ~2.2x the slowest observed, still inside the 60s
    #: ceiling. Recorded rather than left standing: a bound whose stated
    #: margin has drifted from the thing it bounds is the shape this suite
    #: exists to find.
    p = subprocess.run([sys.executable, str(_PROGRAMS / prog), *args],
                       capture_output=True, text=True, timeout=55)
    out = p.stdout + p.stderr
    assert needle in out, out[:600]
    assert re.search(r"\d", out), out[:600]
