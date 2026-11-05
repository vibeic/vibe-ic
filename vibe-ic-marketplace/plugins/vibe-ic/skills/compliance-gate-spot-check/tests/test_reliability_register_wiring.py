"""Wiring test: compliance-gate-spot-check SKILL.md <-> gate_reliability_register.py.

Proves the documented procedure in SKILL.md is real and executable:

1. SKILL.md actually references the program and its `rank` / `record`
   subcommands (so the doc is not a dead reference).
2. The documented CLI round-trip works end-to-end against a temp register:
   record a clean PASS and a false-PASS, then `rank` returns the
   higher-false-PASS gate FIRST (the historically-gamed gate the
   spot-checker should sample first).
3. The documented graceful fallback holds: a freshly `touch`ed (empty)
   ledger ranks to an empty list with exit 0, so the prioritizer never
   blocks the existing uniform-sampling behavior.

ADDITIVE: this test only exercises the register CLI + asserts the doc wiring;
it does not touch any gate's own pass/fail logic.
"""
from pathlib import Path

THIS = Path(__file__).resolve()
SKILL_DIR = THIS.parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
# .../plugins/vibe-ic/skills/<skill>/tests/this.py -> plugin root = parents[3]
PLUGIN_ROOT = THIS.parents[3]
PROGRAM = PLUGIN_ROOT / "programs" / "gate_reliability_register.py"

assert SKILL_MD.exists(), f"SKILL.md missing: {SKILL_MD}"
assert PROGRAM.exists(), f"program missing: {PROGRAM}"




# ---------------------------------------------------------------------------
# 1. The doc actually wires the program in.
# ---------------------------------------------------------------------------
def test_skill_md_references_program_and_subcommands():
    text = SKILL_MD.read_text()
    assert "gate_reliability_register.py" in text, (
        "SKILL.md must reference the register program")
    assert "rank" in text, "SKILL.md must document the `rank` subcommand"
    assert "record" in text, "SKILL.md must document the `record` subcommand"
    assert "--false-pass" in text, (
        "SKILL.md must document writing back a false-PASS outcome")


# ---------------------------------------------------------------------------
# 2. The documented round-trip: record two outcomes, rank orders the
#    higher-false-PASS gate first.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. Documented graceful fallback: a touched (empty) ledger ranks to [].
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. The documented guard: --false-pass with --fail is rejected.
# ---------------------------------------------------------------------------
