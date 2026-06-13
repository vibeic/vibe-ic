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
import json
import subprocess
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
SKILL_DIR = THIS.parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
# .../plugins/vibe-ic/skills/<skill>/tests/this.py -> plugin root = parents[3]
PLUGIN_ROOT = THIS.parents[3]
PROGRAM = PLUGIN_ROOT / "programs" / "gate_reliability_register.py"

assert SKILL_MD.exists(), f"SKILL.md missing: {SKILL_MD}"
assert PROGRAM.exists(), f"program missing: {PROGRAM}"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(PROGRAM), *args],
        capture_output=True, text=True)


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
def test_documented_record_then_rank_roundtrip(tmp_path):
    ledger = tmp_path / "reports" / "gate_reliability_register.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)

    # clean PASS gate (held up under inspection)
    r1 = _run("record", str(ledger), "--gate", "drc_report_check", "--pass")
    assert r1.returncode == 0, r1.stderr

    # false-PASS gate (gate lied — reported PASS but design was wrong)
    r2 = _run("record", str(ledger), "--gate", "lec_check",
              "--pass", "--false-pass")
    assert r2.returncode == 0, r2.stderr

    rank = _run("rank", str(ledger), "--top", "5")
    assert rank.returncode == 0, rank.stderr
    ordered = json.loads(rank.stdout)
    gates = [e["gate"] for e in ordered]
    assert gates, "rank must return a non-empty list after two records"
    # the false-PASS gate must be sampled first
    assert gates[0] == "lec_check", (
        f"expected the false-PASS gate first, got order {gates}")
    assert gates.index("lec_check") < gates.index("drc_report_check")
    # priorities are sorted descending
    prios = [e["spotcheck_priority"] for e in ordered]
    assert prios == sorted(prios, reverse=True)
    assert ordered[0]["spotcheck_priority"] > ordered[-1]["spotcheck_priority"]


# ---------------------------------------------------------------------------
# 3. Documented graceful fallback: a touched (empty) ledger ranks to [].
# ---------------------------------------------------------------------------
def test_empty_ledger_falls_back_to_empty_rank(tmp_path):
    ledger = tmp_path / "gate_reliability_register.json"
    ledger.write_text("")  # `touch`ed empty file, per the documented step
    rank = _run("rank", str(ledger))
    assert rank.returncode == 0, rank.stderr
    assert json.loads(rank.stdout) == [], (
        "empty ledger must rank to [] so uniform sampling is preserved")


# ---------------------------------------------------------------------------
# 4. The documented guard: --false-pass with --fail is rejected.
# ---------------------------------------------------------------------------
def test_false_pass_on_fail_is_rejected(tmp_path):
    ledger = tmp_path / "gate_reliability_register.json"
    r = _run("record", str(ledger), "--gate", "g", "--fail", "--false-pass")
    assert r.returncode == 1
