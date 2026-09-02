#!/usr/bin/env python3
"""#511, third instance: `analog_netlist_path_lint` signed off over nothing.

THE REPRODUCTION, measured on 79d3ebbe8 (v1.16.45)
==================================================
Two projects, one deliberately empty, one carrying a clean deck::

    empty project        [PASS] analog_netlist_path_lint     rc 0
    one clean deck       [PASS] analog_netlist_path_lint     rc 0

Byte for byte the same line, and the same exit code. That is the #511 class
verbatim — the issue was opened on `analog_flow_compliance_check` and
`analog_netlist_include_order_check`, and this is the THIRD gate in the same
directory, driven side by side with the second one by
`analog_a3_netlist_emit.verify_with_checkers`, which records

    {"checker": "path_lint", "rc": 0, "detail": "[PASS] analog_netlist_path_lint"}

into the netlist-emit record. A staging tree whose layout shifts so the lint
reaches no `.sp` produces that identical record, so the artefact says the deck's
include paths were linted when nothing was read.

WHICH HALF WAS BROKEN, because the two diagnoses are different
==============================================================
The gate is NOT blind: `summary.files_checked` / `files_with_includes` /
`skipped` were correct in the JSON report all along, and the module docstring
already promised "it reports files_with_includes so a 0 there is visible".

THE DISCLOSURE WAS GONE ON THE CHANNEL THE CONSUMERS READ. `main()` prints
`[{status}] {GATE}` and then only ERROR/WARNING findings; the skip findings are
INFO and `PATH_LINT_OK` is INFO, so on every passing run stdout is exactly one
line with no number on it. `verify_with_checkers` captures `cp.stdout`, and
`gate_discloses_denominator_check.discloses()` reads text — both consumers were
handed the half that had been emptied.

WHY THE STANDING CHECK DID NOT CATCH IT
=======================================
`gate_discloses_denominator_check --population project` probes
`programs_dir.glob("*_check.py")`. This gate is a `_lint.py`. The population is
a FILENAME, and the defect is a BEHAVIOUR. That is a second, separate reason and
it is fixed in its own commit; this file pins the gate.

THE FIX IS THE SIBLING'S, VERBATIM: `_gate_denominator` on stdout and in
`summary`, an examination of nothing as `VACUOUS_PASS` / rc 2 with a written
reason plus a `VACUOUS_PASS:` token on the rc-independent channel — the same
idiom `analog_netlist_include_order_check` already carries, so the two gates the
A3 producer drives together answer in one grammar.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "analog_netlist_path_lint.py"

sys.path.insert(0, str(PROGRAMS))
import _gate_denominator as GDEN  # noqa: E402
import gate_discloses_denominator_check as GD  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

GATE = "analog_netlist_path_lint"

_CLEAN_DECK = ("* deck\n"
               ".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice\n"
               ".lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical\n"
               ".subckt amp vin vout vss\n.ends\n")
# The username here is the PLACEHOLDER form on purpose. What this deck has
# to be, for the rule under test, is an absolute path that is neither under
# WHITELIST_PREFIXES nor inside the project root — `_is_whitelisted` never
# looks at the shape of the name, so a placeholder violates exactly as a
# real account name does. Writing a real-looking username instead put a
# personal home path into shipped source, which is the thing
# `shipped_path_portability_check` R1 exists to refuse, and it FAILed the
# whole tree on this line. Do not "restore" a name here.
_FOREIGN_DECK = ("* deck\n"
                 ".include /home/<your-user>/scratch/my_models.lib\n"
                 ".subckt amp vin vout vss\n.ends\n")
_NO_INCLUDE_DECK = ("* deck\n.subckt amp vin vout vss\n.ends\n")


def _empty_project(tmp_path: Path, name: str) -> Path:
    proj = tmp_path / name
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    return proj


def _with_decks(tmp_path: Path, name: str, decks) -> Path:
    proj = _empty_project(tmp_path, name)
    d = proj / "analog" / "amp"
    d.mkdir(parents=True)
    for fname, body in decks:
        (d / fname).write_text(body)
    return proj


def _run(proj: Path, *args: str):
    return _pr.run([sys.executable, str(PROG), ".", *args],
                   cwd=str(proj), capture_output=True, text=True)


# ── 1. the reproduction, inverted ──────────────────────────────────────────

def test_empty_project_is_a_disclosed_skip_not_a_pass(tmp_path):
    """The exact line the sibling gate now prints, from this gate."""
    r = _run(_empty_project(tmp_path, "empty"))
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    first = r.stdout.strip().splitlines()[0]
    assert first.startswith(f"[VACUOUS_PASS] {GATE}:"), first
    assert first != f"[PASS] {GATE}"
    assert "examined 0" in first, first
    assert "NOT a sign-off" in first, first
    assert r.stderr.strip().startswith("VACUOUS_PASS:"), r.stderr


def test_empty_project_report_carries_a_compliant_denominator(tmp_path):
    proj = _empty_project(tmp_path, "empty_json")
    out = proj / "r.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 2, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "VACUOUS_PASS"
    assert GDEN.disclosure_violations(rep["summary"]) == []
    denom = rep["summary"][GDEN.DENOMINATOR_KEY]
    assert denom["examined"] == 0
    assert denom["unit"].strip()
    assert denom["not_applicable_reason"].strip()
    # Under --json stdout is deliberately empty; the text channel is still not
    # silence.
    assert "VACUOUS_PASS:" in r.stderr


def test_the_two_runs_are_no_longer_byte_identical(tmp_path):
    """THE DEFECT ITSELF: a clean run and a run over nothing printed the same
    line and the same rc. Both halves must now differ."""
    empty = _run(_empty_project(tmp_path, "d_empty"))
    clean = _run(_with_decks(tmp_path, "d_clean", [("amp.sp", _CLEAN_DECK)]))
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert empty.stdout.strip() != clean.stdout.strip()
    assert empty.returncode != clean.returncode


def test_a_clean_run_states_how_many_decks_it_read(tmp_path):
    proj = _with_decks(tmp_path, "two", [("a.sp", _CLEAN_DECK),
                                         ("b.sp", _CLEAN_DECK)])
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    first = r.stdout.strip().splitlines()[0]
    assert first.startswith(f"[PASS] {GATE}:"), first
    assert "examined 2" in first, first
    assert GD.discloses(r.stdout), r.stdout


def test_decks_without_any_directive_are_counted_not_hidden(tmp_path):
    """A deck carrying no `.include`/`.lib` at all was READ and put through the
    rule — that is a real examination of 1, and the count of directive-carrying
    files is the second number, not a substitute for the first."""
    proj = _with_decks(tmp_path, "nodir", [("amp.sp", _NO_INCLUDE_DECK)])
    out = proj / "r.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["files_checked"] == 1
    assert rep["summary"]["files_with_includes"] == 0
    denom = rep["summary"][GDEN.DENOMINATOR_KEY]
    assert denom["examined"] == 1
    assert GDEN.disclosure_violations(rep["summary"]) == []


# ── 2. the harm at the consumer: the A3 emit record ────────────────────────

def test_a3_style_record_distinguishes_a_linted_deck_from_no_deck(tmp_path):
    """`analog_a3_netlist_emit.verify_with_checkers` stores `cp.stdout[-200:]`
    per checker. Two staging trees that differ ONLY in whether the deck is
    reachable must not produce the same stored detail."""
    reachable = _run(_with_decks(tmp_path, "stage_ok", [("amp.sp", _CLEAN_DECK)]))
    unreachable = _run(_empty_project(tmp_path, "stage_lost"))
    detail_ok = (reachable.stdout or "").strip()[-200:]
    detail_lost = (unreachable.stdout or "").strip()[-200:]
    assert detail_ok != detail_lost, detail_ok
    # …and the unreachable one is not recorded as a zero exit either, so the
    # producer's `ok` flag sees it.
    assert reachable.returncode == 0 and unreachable.returncode != 0


# ── 3. NO GATE GOT QUIETER: every rejection it made before, it still makes ──

def test_foreign_absolute_path_still_fails(tmp_path):
    proj = _with_decks(tmp_path, "bad", [("amp.sp", _FOREIGN_DECK)])
    out = proj / "r.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["passed"] is False
    assert "NON_WHITELISTED_ABSOLUTE_PATH" in {f["rule"] for f in rep["findings"]}
    # A FAIL states its denominator too.
    assert GDEN.disclosure_violations(rep["summary"]) == []
    assert rep["summary"][GDEN.DENOMINATOR_KEY]["examined"] == 1


def test_project_internal_absolute_path_is_still_accepted_and_stated(tmp_path):
    proj = _empty_project(tmp_path, "internal")
    d = proj / "analog" / "amp"
    d.mkdir(parents=True)
    (d / "amp.sp").write_text(
        f"* deck\n.include {proj}/input/pdk/models/sm141064.ngspice\n")
    out = proj / "r.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert "PROJECT_INTERNAL_ABSOLUTE_PATH" in {f["rule"] for f in rep["findings"]}


def test_non_directory_still_exits_2(tmp_path):
    r = _pr.run([sys.executable, str(PROG), str(tmp_path / "nope")],
                capture_output=True, text=True)
    assert r.returncode == 2


# ── 4. the predicate the standing check uses agrees, both ways ─────────────

@pytest.mark.parametrize("populated", [False, True])
def test_the_standing_checks_predicate_accepts_both_verdict_lines(
        tmp_path, populated):
    proj = (_with_decks(tmp_path, "p_yes", [("amp.sp", _CLEAN_DECK)])
            if populated else _empty_project(tmp_path, "p_no"))
    r = _run(proj)
    assert GD.discloses(r.stdout + r.stderr), (r.stdout, r.stderr)
