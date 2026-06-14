"""Regression for ORGANIC #669 — Phase-1 prose-FSM state walker emits generic
English verbs/adjectives as FSM states (bare-word `to` escape not closed by an
enumerated deny-list).

現象 (round-4 v1.0.42 6-IC clean-room): on an FSM-heavy theory-of-operation
doc the bare-word `to` operator of `_V1_6_484_FSM_STATE_TO_STATE_RE` captured
ordinary-English narrative clauses as FSM state pairs and emitted them into
L6/L9 fsm_states:

    "constantly compared to detect potential faults"  → COMPARED / DETECT
    "Similar to the cipher core FSM"                   → SIMILAR
    "refer to Security Hardening"                      → REFER

The existing structural guards are an ENUMERATED deny-list
(`_V1_6_625_TRANSITION_VERBS`) + a data-movement-verb gate — neither rejects
this open-ended class. The surrounding FSM-heavy prose makes the ±300-char
context anchor fire, so the lowercase words slip through. The hallucinated
doc-states then have no RTL transition and fsm_state_coverage_check hard-FAILs
("L9/L11 docs name 4 FSM state(s) but RTL FSM(s) lack matches for 4:
[REFER, COMPARED, DETECT, SIMILAR]").

Fix (chip-AGNOSTIC, structural — closes the bare-word `to` leak by SHAPE, not
by extending the word-list): for the bare-word `to` operator a match is a
candidate only when BOTH endpoints are identifier-shaped — UPPER_SNAKE
(`^[A-Z][A-Z0-9_]+$`) OR backtick-wrapped (the canonical-vocab convention real
FSM specs use for lowercase state names like ``running``). Otherwise the WHOLE
match is rejected (neither endpoint promoted). Real ASCII FSM prose names a
transition either with arrow notation (`A -> B`) or with capitalised state
identifiers, so on reused-IP designs the prose walker no longer pollutes the
L6/L9/L11 catalogue and defers to the vendor RTL state enum the coverage gate
compares against.

NEGATIVE no-leak (the load-bearing half — proves the relaxation-free gate does
not drop real states):
  (a) ARROW-form transitions (`IDLE -> LOAD -> COMPUTE -> DONE`) are never
      touched — both endpoints survive;
  (b) backtick-wrapped lowercase states (``running`` to ``halted``) — a real
      RV-CPU debug-spec idiom — still survive;
  (c) UPPER_SNAKE state pairs via bare-word `to` still survive.

chip-AGNOSTIC: pure grammar/structure + markup; NO chip / vendor / SKU literal
and NO dependency on an enumerated English word-list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

_GEN_DIR = Path("phase1") / "generated_docs"


def _state_names(l6: dict) -> set:
    out = set()
    for s in l6.get("fsm_states") or []:
        nm = s.get("name") if isinstance(s, dict) else s
        if nm:
            out.add(str(nm).upper())
    return out


def _run_l6(tmp_path: Path, extracted: dict) -> dict:
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l6_control_logic(tmp_path, extracted)
    return json.loads(
        (tmp_path / _GEN_DIR / "L6_CONTROL_LOGIC.json").read_text())


# ── reconstructed #669 defect prose (FSM-heavy so the context anchor fires) ──

NOISE_PROSE = """## Theory of Operation

The cipher core FSM controls the round operations of this accelerator. The
state machine sequences through the encryption rounds under control of the
control FSM. During operation, the output is constantly compared to detect
potential faults injected by an attacker. Similar to the cipher core FSM, the
key expansion uses its own state machine. For hardening details please refer
to Security Hardening below.

The FSM transitions through several states under control of the state machine.
"""


def test_english_verbs_not_emitted_as_fsm_states(tmp_path: Path):
    l6 = _run_l6(tmp_path, {"aes_theory_of_operation.md": NOISE_PROSE})
    states = _state_names(l6)
    noise = {"COMPARED", "DETECT", "SIMILAR", "REFER", "SECURITY", "THE",
             "POTENTIAL", "CONSTANTLY"}
    leaked = noise & states
    assert not leaked, f"English-verb prose leaked as FSM states: {leaked}"


# ── unit: the structural gate classifies bare-word `to` noise vs real states ─

@pytest.mark.parametrize("clause,is_noise", [
    ("compared to detect", True),
    ("Similar to the FSM", True),
    ("refer to Security", True),
    ("IDLE to LOAD", False),          # UPPER_SNAKE pair
    ("`running` to `halted`", False),  # backtick-wrapped lowercase states
])
def test_bareword_to_prose_noise_classifier(clause, is_noise):
    matches = list(R._V1_6_484_FSM_STATE_TO_STATE_RE.finditer(clause))
    assert matches, f"regex did not match the clause: {clause!r}"
    m = matches[0]
    assert R._v1_0_44_is_bareword_to_prose_noise(clause, m) is is_noise


def test_arrow_form_never_flagged_as_noise_NOLEAK():
    """Arrow notation (`A -> B`) is the real FSM-diagram form — never gated,
    even with lowercase endpoints."""
    for clause in ("running -> halted", "idle -> load", "AAA -> BBB"):
        m = next(R._V1_6_484_FSM_STATE_TO_STATE_RE.finditer(clause))
        assert R._v1_0_44_is_bareword_to_prose_noise(clause, m) is False, clause


# ── (1) NEGATIVE no-leak: arrow-form + backticked real states survive ─────────

POSITIVE_FSM = """## Control FSM

The control FSM is described here. The state machine moves
IDLE -> LOAD -> COMPUTE -> DONE during a normal computation cycle.

Lowercase debug states also appear: ``running`` to ``halted`` and ``halted``
to ``running`` are valid transitions of the debug state machine.
"""


def test_real_arrow_and_backtick_states_survive_NOLEAK(tmp_path: Path):
    l6 = _run_l6(tmp_path, {"fsm_spec.md": POSITIVE_FSM})
    states = _state_names(l6)
    # arrow-form states
    for st in ("IDLE", "COMPUTE", "DONE"):
        assert st in states, f"arrow-form state {st!r} dropped: {sorted(states)}"
    # backtick-wrapped lowercase states (RV-CPU debug-spec idiom)
    for st in ("RUNNING", "HALTED"):
        assert st in states, f"backticked state {st!r} dropped: {sorted(states)}"


def test_upper_snake_bareword_to_survives_NOLEAK(tmp_path: Path):
    """A genuine UPPER_SNAKE `to` transition in FSM context is kept."""
    doc = """## State Machine

The FSM state machine works as follows. WAIT_REQ to PROCESS_DATA is a valid
transition, and PROCESS_DATA to WRITE_BACK is another, under the state machine.
"""
    l6 = _run_l6(tmp_path, {"fsm.md": doc})
    states = _state_names(l6)
    for st in ("WAIT_REQ", "PROCESS_DATA", "WRITE_BACK"):
        assert st in states, f"UPPER_SNAKE state {st!r} dropped: {sorted(states)}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
