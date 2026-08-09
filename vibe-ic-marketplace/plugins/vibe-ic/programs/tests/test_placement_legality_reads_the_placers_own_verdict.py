"""`placement_legality_check` returned PASS on a run whose placer reported that
it could not legalize the design.

The gate has two blind spots and they compound:

* **the window** — it reads `phase3/stage3/pnr/placed.def`, the PRE-CTS
  snapshot. CTS and hold repair insert instances *after* that file is written,
  so an instance that ends up illegal is not in the file the gate reads.
* **the predicate** — "is a `+ PLACED|FIXED|COVER` token present". That token is
  written for an instance regardless of whether it overlaps a neighbour or sits
  off-site, so `unplaced == 0` is fully compatible with a design the placer
  could not legalize at all.

OBSERVED, one run: `placed.def` 1058 components, all carrying the token, gate
verdict PASS. In the same run the PnR log recorded `POST_HOLD_LEGALIZE_FAILED`,
and `check_placement` on the DEF that is actually routed reported 40 padding
failures and 22 site-alignment failures, with named instances overlapping both
logic cells and tap cells. Those instances appear first in `post_cts.def` — 38
of them, zero in `placed.def` — so the bisect is exact and entirely outside the
gate's window. Detailed routing then failed pin access on 18 of them, the DEF
shipped with zero signal routing, and DRC, LVS and EM each reported a failure of
their own rather than of placement.

OpenROAD's `check_placement` is the verdict that does see this, the runner
already runs it after every legalization attempt, and it condenses the result
into `<SITE>_LEGALIZE_OK` / `<SITE>_LEGALIZE_FAILED` in the PnR log. A gate
named `placement_legality_check` must read it.

The marker is a clean discriminator, measured on two runs that differ only in
PDK: the converged one logs `INITIAL_DPL_LEGALIZE_OK` + `POST_HOLD_LEGALIZE_OK`
and no failure marker; the broken one logs `INITIAL_DPL_LEGALIZE_OK` +
`POST_HOLD_LEGALIZE_FAILED`.

POSITIVE: `*_LEGALIZE_OK` only, or no marker at all, does not manufacture a
failure — the fix must not turn a converged run red.

NEGATIVE no-leak — each of these must FAIL:
  - a token-clean `placed.def` plus any `*_LEGALIZE_FAILED` marker;
  - the same when an OK marker from an earlier rung is also present (a later
    failure is not cancelled by an earlier success).

chip-AGNOSTIC: the runner's own marker grammar; no chip, PDK, library or design
literal in the fix or in this test.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import placement_legality_check as P  # noqa: E402


def _placed_def(n: int) -> str:
    """A DEF whose every component carries the placement STATUS TOKEN — i.e.
    one the pre-existing checks call fully legal."""
    out = ["VERSION 5.8 ;", "DESIGN top ;", "COMPONENTS %d ;" % n]
    out += ["  - U_%d CELL_A + PLACED ( %d 0 ) N ;" % (i, i * 100)
            for i in range(n)]
    out += ["END COMPONENTS", "END DESIGN"]
    return "\n".join(out) + "\n"


def _mk(tmp_path, *, log_lines=None, n=6):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "placed.def").write_text(_placed_def(n))
    if log_lines is not None:
        (pnr / "openroad.log").write_text("\n".join(log_lines) + "\n")
    return tmp_path


def _run(tmp_path):
    verdict, rc, findings, summary = P.inspect(tmp_path)
    return verdict, rc, {f["rule"] for f in findings}, summary


_OK_INITIAL = "INITIAL_DPL_LEGALIZE_OK disp=default"
_OK_POST_HOLD = "POST_HOLD_LEGALIZE_OK disp=clkswap"
_FAILED_POST_HOLD = "POST_HOLD_LEGALIZE_FAILED"


# --------------------------------------------------------------- POSITIVE ---

def test_all_legalize_ok_still_passes(tmp_path):
    """The converged shape must be untouched."""
    _mk(tmp_path, log_lines=[_OK_INITIAL, _OK_POST_HOLD])
    verdict, rc, rules, summary = _run(tmp_path)
    assert verdict == "PASS" and rc == 0
    assert "LEGALIZER_REPORTED_OK" in rules
    assert summary["legalizer_failed_markers"] == []
    assert summary["legalizer_ok_markers"] == [
        "INITIAL_DPL_LEGALIZE_OK", "POST_HOLD_LEGALIZE_OK"]


def test_no_marker_at_all_does_not_manufacture_a_failure(tmp_path):
    """A run that records no placer verdict is not thereby illegal — the
    status-token checks stand alone and the absence is stated, not scored."""
    _mk(tmp_path, log_lines=None)
    verdict, rc, rules, _ = _run(tmp_path)
    assert verdict == "PASS" and rc == 0
    assert "LEGALIZER_VERDICT_ABSENT" in rules


# ------------------------------------------------------- NEGATIVE no-leak ---

def test_legalize_failed_marker_fails_a_token_clean_placed_def(tmp_path):
    """The observed shape: every component carries the token, and the placer
    still could not legalize the design."""
    _mk(tmp_path, log_lines=[_OK_INITIAL, _FAILED_POST_HOLD])
    verdict, rc, rules, summary = _run(tmp_path)
    assert summary["unplaced"] == 0, "fixture must be token-clean"
    assert summary["placed"] == 6
    assert verdict == "FAIL" and rc == 1
    assert "LEGALIZER_REPORTED_FAILURE" in rules
    assert summary["legalizer_failed_markers"] == [_FAILED_POST_HOLD]


def test_an_earlier_success_does_not_cancel_a_later_failure(tmp_path):
    """`INITIAL_DPL_LEGALIZE_OK` is real and is reported — it does not make
    the later failure disappear."""
    _mk(tmp_path, log_lines=[_OK_INITIAL, _FAILED_POST_HOLD])
    _v, rc, _rules, summary = _run(tmp_path)
    assert summary["legalizer_ok_markers"] == ["INITIAL_DPL_LEGALIZE_OK"]
    assert rc == 1


def test_marker_is_found_in_any_pnr_log(tmp_path):
    """The runner may write more than one log under pnr/."""
    _mk(tmp_path, log_lines=[_OK_INITIAL])
    (tmp_path / "phase3" / "stage3" / "pnr" / "resume.log").write_text(
        _FAILED_POST_HOLD + "\n")
    _v, rc, rules, _ = _run(tmp_path)
    assert rc == 1 and "LEGALIZER_REPORTED_FAILURE" in rules


def test_cli_exit_code_and_json_carry_the_verdict(tmp_path, capsys):
    """The gate is wired by exit code, and the JSON is the artefact of record."""
    _mk(tmp_path, log_lines=[_FAILED_POST_HOLD])
    out = tmp_path / "plc.json"
    rc = P.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert _FAILED_POST_HOLD in json.dumps(data)
