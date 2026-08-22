"""Three gates that computed a skip and never said so on the channel. vibe-ic#1115.

Found by `tools/liar_census.py --probes empty_output`, which seeds every
declared output as PRESENT AND EMPTY — the LibreLane `klayout.py:486-490` shape
(`return {}` when the PDK has no DRC deck, so `Checker.KLayoutDRC` finds nothing
to check, warns, and passes).

The seven it flagged do NOT share one shape. These three do, and it is the
narrowest one: each had ALREADY DECIDED the run was inapplicable, and each said
so somewhere no consumer reads. `flow_compliance_check` reads the exit code, and
on the passing path exactly one stdout channel —
`_stdout_signals_vacuous` — so a skip announced anywhere else is recorded as an
ordinary PASS.

    professional_tb_check      handles NOT_CHECKED correctly (VACUOUS_PASS,
                               rc 2) and let NOT_APPLICABLE — the SAME "the
                               step did not run" case, one branch over — fall
                               through to a plain rc 0
    sta_corner_..._check       printed `[PASS] …: NOT_APPLICABLE`, i.e. the
                               word inside a PASS banner
    drv_promotion_..._check    printed `verdict: VACUOUS_PASS`, the right word
                               in a shape the consumer cannot match

MEASURED against the consumer itself, not inferred:

    _stdout_signals_vacuous("verdict: VACUOUS_PASS …")  -> False
    _stdout_signals_vacuous("VACUOUS_PASS: …")          -> True

rc stays 0 in all three. Flipping it would fail every legitimately analog-free,
sim-free or unpromoted run, and a permanently red gate is one people route
around. What changes is that the flow stops recording "checked, fine" for a
thing nobody checked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
from flow_compliance_check import _stdout_signals_vacuous  # noqa: E402

_T = 55


def _run(prog: str, *args: str):
    p = subprocess.run([sys.executable, str(PROGRAMS / prog), *args],
                       capture_output=True, text=True, timeout=_T)
    return p.returncode, p.stdout + p.stderr


def _seed(tmp_path: Path) -> Path:
    for rel in ("reports", "phase1/generated_docs", "phase2/stage2/synth",
                "phase3/stage3/pnr", "input/docs"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    return tmp_path


# --------------------------------------------------------------------------
# the shared property
# --------------------------------------------------------------------------
def test_professional_tb_not_applicable_reaches_the_consumer(tmp_path):
    rc, out = _run("professional_tb_check.py", str(_seed(tmp_path)))
    assert rc == 0, out
    assert '"verdict": "NOT_APPLICABLE"' in out, out
    assert _stdout_signals_vacuous(out), (
        "the step did not run, the gate said so in its own JSON, and exited 0 "
        f"with nothing the consumer reads — so the flow records PASS:\n{out}")


def test_sta_corner_not_applicable_reaches_the_consumer(tmp_path):
    rc, out = _run("sta_corner_record_completeness_check.py", str(_seed(tmp_path)))
    assert rc == 0, out
    assert "NOT_APPLICABLE" in out, out
    assert _stdout_signals_vacuous(out), (
        "the gate printed NOT_APPLICABLE inside a [PASS] banner, which no "
        f"consumer reads as a skip:\n{out}")


def test_drv_promotion_vacuous_reaches_the_consumer(tmp_path):
    rc, out = _run("drv_promotion_corroboration_check.py", str(_seed(tmp_path)))
    assert rc == 0, out
    assert "VACUOUS_PASS" in out, out
    assert _stdout_signals_vacuous(out), (
        "the gate emitted the right WORD in a shape the consumer cannot "
        f"match — `verdict: VACUOUS_PASS` is not the prefix:\n{out}")


def test_the_consumer_is_shape_sensitive_which_is_why_this_was_invisible():
    """The measurement the three repairs rest on. If this ever stopped being
    true, all three would be cargo-culting a prefix nobody needs."""
    assert _stdout_signals_vacuous("VACUOUS_PASS: no route promotion this run")
    assert not _stdout_signals_vacuous(
        "=== DRV promotion corroboration ===\nverdict: VACUOUS_PASS\nno route")


# --------------------------------------------------------------------------
# PAIRED GUARDS — the disclosure must not become a blanket amnesty
# --------------------------------------------------------------------------
def test_professional_tb_still_FAILS_a_real_finding(tmp_path):
    """If this went green the gate would be a disclosure with no teeth."""
    p = _seed(tmp_path)
    rep = p / "reports" / "phase2" / "gates"
    rep.mkdir(parents=True, exist_ok=True)
    # The gate's own unambiguous FAIL path: `functional_mismatch` — "cocotb
    # functional mismatch — real RTL bug". My first fixture guessed at
    # assertion/coverage fields the gate does not judge, and it correctly
    # returned PASS; the gate was right and the fixture was wrong.
    (rep / "professional_tb.json").write_text(json.dumps(
        {"functional_mismatch": True, "dut_kind": "rtl",
         "cocotb_xml_failures": 3, "status": "FAIL"}))
    rc, out = _run("professional_tb_check.py", str(p))
    assert rc == 1, (
        f"a report that IS present and IS deficient was waved through:\n{out}")
    assert not _stdout_signals_vacuous(out), (
        f"a real finding was disclosed as vacuous:\n{out}")


def test_a_populated_run_is_not_marked_vacuous(tmp_path):
    """The false-positive control for all three: a gate with real evidence must
    not be demoted to VACUOUS_PASS, or every honest run loses its PASS."""
    p = _seed(tmp_path)
    rep = p / "reports" / "phase2" / "gates"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "professional_tb.json").write_text(json.dumps(
        {"functional_mismatch": False, "dut_kind": "rtl",
         "status": "PASS", "ran_cocotb": True}))
    rc, out = _run("professional_tb_check.py", str(p))
    assert not _stdout_signals_vacuous(out), (
        f"a populated run was demoted to VACUOUS_PASS:\n{out}")
