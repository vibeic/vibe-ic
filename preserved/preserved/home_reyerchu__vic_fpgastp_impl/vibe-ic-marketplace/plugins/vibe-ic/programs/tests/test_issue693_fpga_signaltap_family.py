"""vibe-ic#693 — the `fpga-signaltap` family, wired or registered with a reason.

Three shipped, gate-shaped programs were referenced from NO executable location:
`fpga_led_probe_lint`, `signaltap_recompile_sequence_check`,
`signaltap_stp_completeness_check`. None had ever run outside its own unit test.

This file re-derives, rather than asserts, the three decisions taken:

  * `fpga_led_probe_lint` is WIRED at step 6 — and specifically as
    `advisory_program_exit_zero`, because that is the ONLY slot in an `all_of`
    that executes on the published corpus. `_evaluate_gate` short-circuits
    `all_of` at the first failing leg and re-runs only advisory legs afterwards;
    step 6's first leg is `files_exist: phase2/stage1/fpga/output_files/*.sof`
    and zero .sof files exist in any published run. Wired as
    `optional_program_exit_zero` the gate never executed at all — measured, no
    JSON written — and `optional_` is additionally BLOCKING, which contradicts
    the non-blocking staging this landing is.

  * both SignalTap gates are REGISTERED at step 39 and deliberately NOT in any
    `gate:` block, with the reason recorded beside them. `_UNROUTED_INVENTORY`
    is not their register (it counts unrouted SKIP PATHS, and injecting a gate
    makes that ratchet exit 1); nor are `_SEMANTIC_ARGV_UNDRIVABLE` /
    `_NOT_A_PROJECT_GATE` / `_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA`, each of which
    carries a parametrized test requiring membership in `_STRUCTURAL_RTL_GATES`.

  * all three declare their "nothing examined" path with rc 2 and a `[SKIP]`
    line-start token, so `flow_compliance_check` files it as VACUOUS_PASS
    rather than PASS and `gate_skip_routing_check._skip_token` can see it.

BIDIRECTIONAL: if someone promotes a SignalTap gate into step 39's `gate:`
block, `test_signaltap_gates_are_registered_but_not_wired` fails — the record
cannot outlive its truth. If the advisory leg is demoted back to `optional_`,
`test_led_probe_lint_is_wired_as_advisory_not_optional` fails.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
import yaml

_PLUGIN = pathlib.Path(__file__).resolve().parents[2]
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_PROGRAMS = _PLUGIN / "programs"

_FLOW_DOC = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
_STEPS = _FLOW_DOC.get("steps") or []

_FAMILY = (
    "fpga_led_probe_lint",
    "signaltap_recompile_sequence_check",
    "signaltap_stp_completeness_check",
)
_SIGNALTAP = _FAMILY[1:]


def _step(sid):
    for s in _STEPS:
        if isinstance(s, dict) and str(s.get("id")) == str(sid):
            return s
    raise AssertionError(f"step {sid} not found in {_FLOW}")


def _gate_mappings(gate):
    """Every gate mapping in the tree.

    `any_of` is overloaded in this yaml: it is a LIST of sub-gates on some
    steps and a BOOLEAN modifier of `files_exist` on others. Only the list form
    is a sub-gate container.
    """
    if not isinstance(gate, dict):
        return
    yield gate
    for key in ("all_of", "any_of"):
        subs = gate.get(key)
        if not isinstance(subs, list):
            continue
        for sub in subs:
            yield from _gate_mappings(sub)


def _all_gate_commands():
    out = []
    for s in _STEPS:
        if not isinstance(s, dict):
            continue
        for g in _gate_mappings(s.get("gate")):
            for key, spec in g.items():
                if not key.endswith("program_exit_zero"):
                    continue
                cmd = spec if isinstance(spec, str) else (
                    spec.get("command") if isinstance(spec, dict) else None)
                if cmd:
                    out.append((str(s.get("id")), key, cmd))
    return out


# ---------------------------------------------------------------------------
# 1. Nothing in the family is left both unwired and unlisted.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate", _FAMILY)
def test_every_family_gate_is_referenced_from_the_flow(gate):
    """The #693 disclosure floor: a gate is wired, or listed with a reason."""
    listed = any(gate in (s.get("programs") or [])
                 for s in _STEPS if isinstance(s, dict))
    wired = any(cmd.split()[0] == gate for _sid, _k, cmd in _all_gate_commands())
    assert listed or wired, (
        f"{gate} appears in no step's `programs:` list and in no gate command; "
        f"it is unwired AND unlisted, which is the state #693 measured")


@pytest.mark.parametrize("gate", _FAMILY)
def test_every_family_gate_exists(gate):
    assert (_PROGRAMS / f"{gate}.py").is_file()


# ---------------------------------------------------------------------------
# 2. fpga_led_probe_lint: wired at step 6, ADVISORY, condition-guarded.
# ---------------------------------------------------------------------------
def test_led_probe_lint_is_wired_as_advisory_not_optional():
    hits = [(sid, key, cmd) for sid, key, cmd in _all_gate_commands()
            if cmd.split()[0] == "fpga_led_probe_lint"]
    assert hits, "fpga_led_probe_lint is not wired into any gate"
    for sid, key, _cmd in hits:
        assert sid == "6", f"expected step 6, found step {sid}"
        assert key == "advisory_program_exit_zero", (
            f"fpga_led_probe_lint is wired as `{key}`. `optional_"
            f"program_exit_zero` NEVER EXECUTES in step 6's all_of (the "
            f"short-circuit at the .sof leg) and is BLOCKING when it does; "
            f"`advisory_` is the only slot that both runs and does not block.")


def test_led_probe_lint_leg_is_guarded_by_a_qsf_condition():
    """Without the guard the leg runs on 28/28 published runs and reports a
    vacuous result on 27 of them."""
    step6 = _step(6)
    legs = [g for g in _gate_mappings(step6.get("gate"))
            if "advisory_program_exit_zero" in g]
    spec = None
    for g in legs:
        s = g["advisory_program_exit_zero"]
        if isinstance(s, dict) and "fpga_led_probe_lint" in (s.get("command") or ""):
            spec = s
    assert spec is not None, "advisory leg for fpga_led_probe_lint not found"
    assert spec.get("condition_files_exist") == ["phase2/stage1/fpga/*.qsf"], spec
    assert "--qsf" in spec["command"], (
        "without --qsf the per-bit shared-pin-vs-QSF rule — the one rule no "
        "other wired gate covers — silently does not run")


def test_led_probe_lint_is_declared_in_step6_programs():
    assert "fpga_led_probe_lint" in (_step(6).get("programs") or [])


# ---------------------------------------------------------------------------
# 3. The SignalTap gates: registered at step 39, deliberately not wired.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate", _SIGNALTAP)
def test_signaltap_gates_are_registered_but_not_wired(gate):
    assert gate in (_step(39).get("programs") or []), (
        f"{gate} is no longer registered at step 39; it would be back to "
        f"unwired AND unlisted")
    wired = [(sid, key) for sid, key, cmd in _all_gate_commands()
             if cmd.split()[0] == gate]
    assert not wired, (
        f"{gate} is now wired at {wired}. That may be right — but the "
        f"registration comment at step 39 says it is NOT, and the measurement "
        f"behind it (0 subjects in 28/28 published run roots) must be redone "
        f"and rewritten before this test is updated.")


@pytest.mark.parametrize("gate", _SIGNALTAP)
def test_registration_carries_a_written_reason(gate):
    """A bare name in a list is not a disclosure. The reason must be in the
    file, next to the entry."""
    text = _FLOW.read_text(encoding="utf-8")
    idx = text.index(f"      - {gate}\n")
    window = text[max(0, idx - 4000):idx]
    assert "WHY NOT WIRED" in window, (
        f"{gate} is registered at step 39 with no `WHY NOT WIRED` rationale "
        f"in the preceding comment block")


# ---------------------------------------------------------------------------
# 4. The skip tier: rc 2 + a token the ratchet can see, for all three.
# ---------------------------------------------------------------------------
_NO_INPUT_ARGV = {
    # argv that reaches each gate's "nothing to examine" path
    "fpga_led_probe_lint": ["<EMPTYDIR>"],
    "signaltap_recompile_sequence_check": [],
    "signaltap_stp_completeness_check": [],
}


@pytest.mark.parametrize("gate", _FAMILY)
def test_nothing_examined_exits_2_and_declares_a_visible_skip(gate, tmp_path):
    """rc 0 on nothing is credited by `flow_compliance_check` as a plain PASS.

    And the declaration has to START with a token
    `gate_skip_routing_check._skip_token` knows, because that function uses
    `str.startswith`: the previous `<prog>: SKIP — ...` form made all three
    report `skip_paths: 0` to the ratchet built to count exactly this.
    """
    argv = [str(tmp_path) if a == "<EMPTYDIR>" else a
            for a in _NO_INPUT_ARGV[gate]]
    proc = subprocess.run([sys.executable, str(_PROGRAMS / f"{gate}.py"), *argv],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2, (
        f"{gate} exits {proc.returncode} on nothing; rc 2 is the disclosed-skip "
        f"tier, rc 0 is a pass\n{proc.stderr}")
    assert proc.stderr.lstrip().startswith("[SKIP]"), proc.stderr


def test_skip_token_vocabulary_actually_matches_our_declarations():
    """Re-derive the ratchet's own predicate rather than trusting the prefix."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gate_skip_routing_check", _PROGRAMS / "gate_skip_routing_check.py")
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules[cls.__module__]
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for gate in _FAMILY:
        line = f"[SKIP] {gate}: no input — NOTHING EXAMINED, this is not a pass"
        assert mod._skip_token(line), (
            f"the ratchet cannot see {gate}'s skip declaration: {line!r}")
