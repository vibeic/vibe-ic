"""`check_placement` returns a violation count, and the flow threw it away.

From the installed binary's own `info body check_placement`:

    # Returns the violation count. Without -no_abort a non-zero count raises
    # DPL-33 instead of returning, so an illegal placement can never be
    # mistaken for a legal one by a caller that ignores the result.
    return [dpl::check_placement_cmd $verbose $file_name $no_abort]

Both `check_placement` call sites outside the legalization ladder — after
spare-cell insertion, and after the repair's own legalization — wrapped the
RAISING form in a `catch` and printed the tool's refusal as a warning string
(`SPARE_CHECK_PLACEMENT_WARN: DPL-0033` / `POSTROUTE_TIMING_REPAIR_CHECK_PLACEMENT_WARN: ...`).
Nothing read it. `placement_legality_check` read the DEF STATUS FIELD instead,
and a status field cannot express an overlap: an illegally placed instance
still carries `+ PLACED ( x y ) N`.

MEASURED with the real tool, on a DEF whose ONLY edit is one instance moved
from site 3 to site 1 (a 3-site-wide cell, so it lands on top of its
neighbour). Both DEFs and the LEF were written for this measurement; there is
no chip, PDK, library or vendor literal in either.

    legal.def    ->  no raise;  check_placement -no_abort == 0
    overlap.def  ->  [WARNING DPL-0005] Overlap check failed (1).
                     [WARNING DPL-0011] Padding check failed (1).
                     [ERROR   DPL-0033] detailed placement checks failed
                                        during check placement.
                     check_placement -no_abort == 2

Running the runner's PRE-FIX Tcl over overlap.def produced, verbatim:

    SPARE_CHECK_PLACEMENT_WARN: DPL-0033

and this gate, with that log and that DEF in place, reported:

    === placement_legality_check (proj) ===
      verdict: PASS
    EXIT=0

POSITIVE (a converged run must not turn red):
  - a `_VIOLATIONS 0` record passes, and records the verdict as LEGAL;
  - a run with NO check_placement record at all does not manufacture a
    failure — it is disclosed as NOT DETERMINED.

NEGATIVE no-leak — each must FAIL a token-clean `placed.def`:
  - `_CHECK_PLACEMENT_VIOLATIONS n` for any n > 0, at any site;
  - the legacy `_CHECK_PLACEMENT_WARN: DPL-0033` shape, so logs already on
    disk are read the way the tool meant them;
  - `_CHECK_PLACEMENT_RAISED: DPL-0033`;
  - a clean count at one site does not cancel a non-zero count at another.

The DEF checks are KEPT — they catch a different failure (a floorplan.def
copy, a truncated DEF) — but they no longer stand in for legality, and the
gate now says which of the two it actually verified.

chip-AGNOSTIC: an OpenROAD command's own output grammar and the runner's
marker prefix; no chip, PDK, library or design literal.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import placement_legality_check as P  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402


def _placed_def(n: int = 4) -> str:
    """A DEF whose every component carries the placement STATUS TOKEN — the
    shape the pre-existing checks call fully legal."""
    out = ["VERSION 5.8 ;", "DESIGN top ;", "COMPONENTS %d ;" % n]
    out += ["  - U_%d CELL_A + PLACED ( %d 0 ) N ;" % (i, i * 100)
            for i in range(n)]
    out += ["END COMPONENTS", "END DESIGN"]
    return "\n".join(out) + "\n"


def _mk(tmp_path, *log_lines):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "placed.def").write_text(_placed_def())
    if log_lines:
        (pnr / "openroad.log").write_text("\n".join(log_lines) + "\n")
    return tmp_path


def _run(tmp_path):
    verdict, rc, findings, summary = P.inspect(tmp_path)
    return verdict, rc, {f["rule"] for f in findings}, summary


# The two lines the container actually printed for overlap.def, verbatim.
_REAL_DPL_WARNINGS = [
    "[WARNING DPL-0005] Overlap check failed (1).",
    "[WARNING DPL-0011] Padding check failed (1).",
]
_REAL_DPL_ERROR = ("[ERROR DPL-0033] detailed placement checks failed during "
                   "check placement.")


# --------------------------------------------------------------- POSITIVE ---

def test_a_zero_count_passes_and_is_recorded_as_the_verdict(tmp_path):
    _mk(tmp_path, "INITIAL_DPL_LEGALIZE_OK disp=default",
        "SPARE_CHECK_PLACEMENT_VIOLATIONS 0")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "CHECK_PLACEMENT_CLEAN" in rules
    assert summary["placer_legality_verdict"] == "LEGAL"
    assert summary["check_placement_violations"] == [["SPARE", 0]]


def test_no_record_at_all_is_not_determined_not_a_failure(tmp_path):
    """A run that never recorded the tool's verdict is not thereby illegal —
    but the gate must SAY that legality was not determined rather than let the
    status-token checks read as one."""
    _mk(tmp_path, "INITIAL_DPL_LEGALIZE_OK disp=default")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "CHECK_PLACEMENT_NOT_RUN" in rules
    assert summary["placer_legality_verdict"] == "NOT DETERMINED"


def test_an_unavailable_check_is_disclosed_never_scored_legal(tmp_path):
    _mk(tmp_path, "SPARE_CHECK_PLACEMENT_UNAVAILABLE: non-numeric result ''")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("PASS", 0)
    assert "CHECK_PLACEMENT_UNAVAILABLE" in rules
    assert summary["placer_legality_verdict"] == "NOT DETERMINED"


# ------------------------------------------------------- NEGATIVE no-leak ---

def test_the_measured_overlap_count_fails_a_token_clean_def(tmp_path):
    """The measured shape: one instance moved onto its neighbour, the tool
    returns 2, every component still carries `+ PLACED`."""
    _mk(tmp_path, "INITIAL_DPL_LEGALIZE_OK disp=default",
        *_REAL_DPL_WARNINGS,
        "[WARNING DPL-0040] detailed placement checks failed during check "
        "placement: 2 violation(s) returned to caller.",
        "SPARE_CHECK_PLACEMENT_VIOLATIONS 2")
    verdict, rc, rules, summary = _run(tmp_path)
    assert summary["unplaced"] == 0, "fixture must be token-clean"
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_VIOLATIONS" in rules
    assert summary["placer_legality_verdict"] == "ILLEGAL"
    assert summary["check_placement_violations"] == [["SPARE", 2]]


def test_a_single_violation_is_enough(tmp_path):
    _mk(tmp_path, "POSTROUTE_TIMING_REPAIR_CHECK_PLACEMENT_VIOLATIONS 1")
    verdict, rc, rules, _ = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_VIOLATIONS" in rules


def test_the_legacy_warn_shape_still_fails(tmp_path):
    """The exact line the pre-fix runner printed. Logs already on disk must be
    read the way the tool meant them, not as a warning nobody owns."""
    _mk(tmp_path, *_REAL_DPL_WARNINGS, _REAL_DPL_ERROR,
        "SPARE_CHECK_PLACEMENT_WARN: DPL-0033")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "CHECK_PLACEMENT_RAISED" in rules
    assert summary["check_placement_raised"] == [["SPARE", "DPL-0033"]]


def test_the_raised_shape_fails(tmp_path):
    _mk(tmp_path, "POSTROUTE_TIMING_REPAIR_CHECK_PLACEMENT_RAISED: DPL-0033")
    verdict, rc, _rules, _s = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)


def test_a_clean_site_does_not_cancel_a_dirty_one(tmp_path):
    """Legalization succeeding earlier does not make a later overlap go away."""
    _mk(tmp_path, "SPARE_CHECK_PLACEMENT_VIOLATIONS 0",
        "POSTROUTE_TIMING_REPAIR_CHECK_PLACEMENT_VIOLATIONS 3")
    verdict, rc, _rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert summary["placer_legality_verdict"] == "ILLEGAL"


def test_the_record_is_found_in_any_pnr_log(tmp_path):
    _mk(tmp_path, "SPARE_CHECK_PLACEMENT_VIOLATIONS 0")
    (tmp_path / "phase3" / "stage3" / "pnr" / "repair.log").write_text(
        "POSTROUTE_TIMING_REPAIR_CHECK_PLACEMENT_VIOLATIONS 7\n")
    _v, rc, _rules, summary = _run(tmp_path)
    assert rc == 1
    assert ["POSTROUTE_TIMING_REPAIR", 7] in summary["check_placement_violations"]


def test_the_repair_stages_own_log_is_scanned(tmp_path):
    """The timing repair is a SEPARATE OpenROAD invocation writing
    `phase3/stage3/postroute_timing_repair/postroute_timing_repair.log`. A `pnr/`-only scan is blind to every
    verdict it emits, including the repair's own legalization failure."""
    _mk(tmp_path, "SPARE_CHECK_PLACEMENT_VIOLATIONS 0")
    repair = tmp_path / "phase3" / "stage3" / "postroute_timing_repair"
    repair.mkdir(parents=True, exist_ok=True)
    (repair / "postroute_timing_repair.log").write_text("POSTROUTE_TIMING_REPAIR_CHECK_PLACEMENT_VIOLATIONS 5\n")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert ["POSTROUTE_TIMING_REPAIR", 5] in summary["check_placement_violations"]


def test_the_repair_stages_legalizer_failure_is_scanned(tmp_path):
    """The same blind spot on the pre-existing marker reader: the escalating
    legalizer runs inside the repair script too, and its `_LEGALIZE_FAILED` was
    written to a log nothing looked at."""
    _mk(tmp_path, "INITIAL_DPL_LEGALIZE_OK disp=default")
    repair = tmp_path / "phase3" / "stage3" / "postroute_timing_repair"
    repair.mkdir(parents=True, exist_ok=True)
    (repair / "postroute_timing_repair.log").write_text("POSTROUTE_TIMING_REPAIR_DPL_LEGALIZE_FAILED\n")
    verdict, rc, rules, summary = _run(tmp_path)
    assert (verdict, rc) == ("FAIL", 1)
    assert "LEGALIZER_REPORTED_FAILURE" in rules
    assert summary["legalizer_failed_markers"] == ["POSTROUTE_TIMING_REPAIR_DPL_LEGALIZE_FAILED"]


def test_cli_exit_code_and_json_carry_the_count(tmp_path):
    """The gate is wired into step 17's `all_of` by EXIT CODE, and the JSON is
    the artefact of record."""
    _mk(tmp_path, "SPARE_CHECK_PLACEMENT_VIOLATIONS 2")
    out = tmp_path / "plc.json"
    rc = P.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert data["placer_legality_verdict"] == "ILLEGAL"
    assert data["check_placement_violations"] == [["SPARE", 2]]


# ------------------------------------------- the runner must EMIT the count --

def test_the_runner_asks_the_tool_for_its_count(tmp_path):
    """A gate that reads a marker no runner writes checks nothing."""
    tcl = R._build_check_placement_verdict_tcl("SPARE", "_spare")
    assert "check_placement -no_abort" in tcl, (
        "-no_abort is what makes the tool RETURN the count instead of raising")
    assert "SPARE_CHECK_PLACEMENT_VIOLATIONS $_cpv_spare" in tcl
    assert "SPARE_CHECK_PLACEMENT_RAISED" in tcl


def test_the_runner_no_longer_demotes_the_verdict_to_a_warning():
    """The two call sites that printed `..._CHECK_PLACEMENT_WARN` are gone."""
    src = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
    for site in ("SPARE", "POSTROUTE_TIMING_REPAIR"):
        assert f'puts \\"{site}_CHECK_PLACEMENT_WARN' not in src, (
            f"{site} still prints the tool's refusal as a warning string")


def test_both_call_sites_use_the_shared_builder():
    """One builder, so the two sites cannot drift apart again."""
    src = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
    assert src.count('_build_check_placement_verdict_tcl("SPARE"') == 1
    assert src.count(
        '"POSTROUTE_TIMING_REPAIR", "_postroute_timing_repair_cp"'
    ) == 1
