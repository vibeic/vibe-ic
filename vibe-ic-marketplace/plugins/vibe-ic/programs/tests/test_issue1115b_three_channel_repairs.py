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
    """rc was 0 here until vibe-ic#564. The prose disclosure this test pins was
    right and is unchanged; the EXIT CODE was the half that did not land.

    `gate_zero_denominator_refuses_check` measured the consequence: the P0
    umbrella reads exit codes, not prose, so rc 0 still recorded a silent pass
    and this gate was the ONE `ZERO_DENOMINATOR_EXITS_ZERO` finding out of 534
    programs probed. rc 2 does NOT fail a run — it is this file's own
    disclosed-skip convention, `flow_compliance_check` maps it to "n/a (input
    not present)", and the `NOT_CHECKED` branch already returns it for the
    analogous case. So the concern that motivated rc 0 is met by rc 2.
    """
    rc, out = _run("professional_tb_check.py", str(_seed(tmp_path)))
    assert rc == 2, (
        "a gate that states it read NOTHING must not exit 0 — the umbrella "
        f"reads the rc, not the sentence:\n{out}")
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
    assert rc == 0, (
        "this report carries NO `files` key at all — the SKIP class and every "
        "older report look exactly like this. Nothing was claimed, so nothing "
        f"is owed, and it must stay a plain pass:\n{out}")


# --------------------------------------------------------------------------
# THE OTHER ZERO (vibe-ic#564) — a zero because the SELECTION produced nothing
# is a different answer from a zero because the step did not run, and the
# difference has to survive into the exit code. Both directions asserted.
# --------------------------------------------------------------------------
def test_declared_files_with_nowhere_to_look_is_a_defect(tmp_path):
    """`files` NON-EMPTY with no `out_dir`: a declaration the gate cannot act
    on. It fell through to a plain PASS, having verified none of the files it
    was told about.

    rc 1, not rc 2: rc 2 is reserved for "I could not look", and here the gate
    looked — the report is present and names artefacts. Collapsing this into
    rc 2 would file a producer defect under the same code as a project that
    legitimately has no such step.
    """
    p = _seed(tmp_path)
    rep = p / "reports" / "phase2" / "gates"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "professional_tb.json").write_text(json.dumps(
        {"functional_mismatch": False, "status": "PASS", "ran_cocotb": True,
         "files": ["tb_top.py", "Makefile"]}))
    rc, out = _run("professional_tb_check.py", str(p))
    assert rc == 1, (
        f"two declared files with no out_dir were verified as present:\n{out}")
    assert "EMPTY_DECLARATION" in out, out
    assert not _stdout_signals_vacuous(out), (
        f"a producer defect was disclosed as a vacuous SKIP:\n{out}")


def test_the_two_zeros_do_not_share_an_exit_code(tmp_path):
    """The discriminator itself. If these two ever agree, the distinction this
    change exists to make has been silently undone — and it would still look
    green, because each arm on its own is a perfectly ordinary verdict."""
    empty_corpus = _seed(tmp_path / "a")
    rc_absent, out_absent = _run("professional_tb_check.py", str(empty_corpus))

    unfollowable = _seed(tmp_path / "b")
    rep = unfollowable / "reports" / "phase2" / "gates"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "professional_tb.json").write_text(json.dumps(
        {"functional_mismatch": False, "status": "PASS", "ran_cocotb": True,
         "files": ["tb_top.py"]}))
    rc_bad, out_bad = _run("professional_tb_check.py", str(unfollowable))

    assert rc_absent == 2 and rc_bad == 1, (
        f"absent-step rc={rc_absent} (want 2), unfollowable-declaration "
        f"rc={rc_bad} (want 1)\n--- absent ---\n{out_absent}\n"
        f"--- unfollowable ---\n{out_bad}")
    assert rc_absent != rc_bad, (
        "a genuinely empty corpus and a declaration the gate cannot follow "
        "are different answers and must not share an exit code")


def test_a_producer_that_declared_NOTHING_still_owes_nothing(tmp_path):
    """The scoping control on the branch above, restating a property that is
    already pinned in `test_professional_tb_bundle_completeness` — because my
    first version of this change broke it.

    I originally failed `files: []` too, reasoning that emitting the key with
    an empty list is a claim of nothing. The repo had already decided
    otherwise, with a reason: `step_professional_tb_gen` SKIPs for a class with
    no derivable interface. A producer that declared nothing must not be failed
    for not delivering it. The existing GUARD caught it, and this is the local
    reminder so the next narrowing does not re-widen by accident.
    """
    p = _seed(tmp_path)
    rep = p / "reports" / "phase2" / "gates"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "professional_tb.json").write_text(json.dumps(
        {"status": "PASS", "out_dir": "", "files": [],
         "functional_mismatch": False}))
    rc, out = _run("professional_tb_check.py", str(p))
    assert rc == 0, (
        f"an empty declaration was failed — nothing was claimed:\n{out}")
    assert "EMPTY_DECLARATION" not in out, out
